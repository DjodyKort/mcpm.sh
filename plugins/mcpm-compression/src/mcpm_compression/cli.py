"""`mcpm compression` — manage the swappable context-compression layer."""
from __future__ import annotations

import os
import shutil

import click
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from .capability import (
    effective_config as cap_effective,
    inert_for as cap_inert,
    split_unsealed,
    unsealed_for as cap_unsealed,
)
from .config import load_config, load_config_verbose, save_config
from .ledger import append_launch
from .mcp_presence import in_client, is_present, present_entry
from .providers import get_provider, provider_names
from .providers.headroom_runtime import (
    HeadroomUnavailable,
    install as hr_install,
    latest_version as hr_latest,
    proxy_down as hr_proxy_down,
    proxy_up as hr_proxy_up,
    snapshot_profile_env,
    version as hr_version,
)
from .runtime import LAUNCHD_LABEL, launchd_plist_path
from .runtime.shell import SHELL_SNIPPET_PATH, SHIMS_PATH
from .schema import DEFAULT_PORT, KnobSpec
from .sync import apply, disable as do_disable
from .versions import version_tuple
from .verify import compare, iter_transcripts, measure, partition, partition_by_pin, schema_ok

console = Console()
err = Console(stderr=True)

# Provider → default runtime, so `enable` infers a sane runtime when omitted.
_DEFAULT_RUNTIME = {"headroom": "proxy", "rtk-only": "hook", "none": "none"}


def _print_report(report) -> None:
    for a in report.actions:
        console.print(f"  [green]✓[/] {a}")
    for w in report.warnings:
        err.print(f"  [yellow]![/] {w}")


@click.group(
    help="Manage the swappable context-compression layer (headroom / rtk-only / none).",
    context_settings=dict(help_option_names=["-h", "--help"]),
)
def compression() -> None:
    pass


@compression.command(help="Show current provider, proxy health, MCP presence, and artifacts.")
def status() -> None:
    config = load_config()
    provider = get_provider(config.provider)
    health = provider.health(config)

    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_row("provider", f"[bold]{config.provider}[/]")
    table.add_row("runtime", config.runtime)
    preset = config.preset_for()
    table.add_row("preset", f"{config.active_preset}  "
                  f"(mode={preset.mode}, profile={preset.savings_profile or '—'}, port={preset.port})")
    table.add_row("scope", ", ".join(config.scope))
    ok = health.get("ok")
    table.add_row("engine", f"[green]healthy[/] — {health.get('detail','')}" if ok
                  else f"[red]down[/] — {health.get('detail','')}")
    if health.get("version"):
        table.add_row("version", str(health["version"]))
    if config.provider == "headroom":
        pin = config.provider_version.pin
        v = hr_version()
        if not v:
            table.add_row("headroom", f"[yellow]not on PATH (pin {pin})[/]")
        elif v == pin:
            table.add_row("headroom", f"[green]{v}[/] (pinned)")
        else:
            # Any mismatch is drift — including newer. "Newer" is unverified, not fine:
            # 0.31 was newer than 0.27 and shipped a measured cache-busting regression.
            table.add_row("headroom", f"[red]{v} ≠ pin {pin}[/] — run "
                          f"[cyan]mcpm compression pin --install[/]")
    desired = provider.mcp_server_config(config)
    mcp_name = desired["name"] if desired else None
    if mcp_name:
        entry = present_entry(mcp_name)
        table.add_row("MCP server",
                      f"[green]registered in mcpm[/] ({mcp_name})" if entry
                      else f"[dim]not in mcpm servers.json[/] ({mcp_name})")
    else:
        table.add_row("MCP server", "[dim]n/a — provider has no MCP server[/]")
    table.add_row("shell snippet", str(SHELL_SNIPPET_PATH) if SHELL_SNIPPET_PATH.exists()
                  else "[dim]none[/]")
    table.add_row("lifecycle", "on-demand (wrapper)")
    if launchd_plist_path().exists():
        table.add_row("legacy plist",
                      f"[yellow]{launchd_plist_path()} — run `mcpm compression sync` to remove[/]")
    console.print(table)


@compression.command(help="Enable compression with a provider (default: headroom).")
@click.option("--provider", "provider_name", type=click.Choice(provider_names()),
              default="headroom", show_default=True)
@click.option("--port", type=int, default=None,
              help=f"Proxy port (default {DEFAULT_PORT}; preserved if already set).")
@click.option("--telemetry", type=click.Choice(["off", "on"]), default=None,
              help="Telemetry (default off; preserved if already set).")
@click.option("--preset", "preset_name", default=None,
              help="Active preset (e.g. interactive/agent/balanced).")
@click.option("--mode", type=click.Choice(["cache", "token"]), default=None,
              help="Override the active preset's compression mode.")
def enable(provider_name: str, port: int | None, telemetry: str | None,
           preset_name: str | None, mode: str | None) -> None:
    # Load-merge so we never clobber existing contexts/clients/scope/presets.
    config = load_config()
    config.provider = provider_name
    config.runtime = _DEFAULT_RUNTIME.get(provider_name, "none")
    if preset_name:
        if preset_name not in config.presets:
            err.print(f"[red]unknown preset {preset_name!r}[/] (have: {', '.join(config.presets)})")
            raise SystemExit(1)
        config.active_preset = preset_name
    if mode:
        config.presets[config.active_preset].mode = mode
    if port is not None:
        config.presets[config.active_preset].port = port
    if telemetry is not None:
        config.options["telemetry"] = telemetry
    console.print(f"[bold]Enabling compression: {provider_name}[/] "
                  f"(preset {config.active_preset}, mode {config.preset_for().mode})")
    report = apply(config)
    _print_report(report)
    console.print("\n[bold]Next steps:[/]")
    if provider_name == "headroom":
        console.print(f"  • add to ~/.zshrc: [cyan]source {SHIMS_PATH}[/]  "
                      "(hrclaude/hrup/hrdown — replaces headroom-aliases.zsh)")
        console.print("  • or launch directly: [cyan]mcpm compression run -- <claude args>[/]  "
                      "(resolves the per-dir preset, ensures the proxy, execs claude)")
    console.print("  • verify: [cyan]mcpm compression status[/] / [cyan]doctor[/]   (MCP presence already propagated)")


@compression.command(help="Disable compression (remove MCP entry + artifacts).")
@click.option("--teardown", is_flag=True,
              help="Also run headroom's own removal (mcp uninstall + unwrap claude).")
def disable(teardown: bool) -> None:
    console.print("[bold]Disabling compression[/]")
    report = do_disable()
    _print_report(report)
    if teardown:
        from .providers.headroom_runtime import mcp_uninstall, unwrap
        for label, (ok, detail) in [("headroom mcp uninstall", mcp_uninstall()),
                                     ("headroom unwrap claude", unwrap("claude"))]:
            (console.print if ok else err.print)(f"  [{'green' if ok else 'yellow'}]"
                                                  f"{'✓' if ok else '!'}[/] {label} — {detail}")
        console.print("  [dim]Note: ~/.headroom/ data (toin/savings/memory) is left in place.[/]")
    if launchd_plist_path().exists():
        console.print(f"\n  Note: a legacy launchd job may still be loaded — remove with "
                      f"[cyan]launchctl bootout gui/$(id -u)/{LAUNCHD_LABEL}[/]")


@compression.command(name="set-provider", help="Swap the active provider and re-apply.")
@click.argument("provider_name", type=click.Choice(provider_names()))
def set_provider(provider_name: str) -> None:
    config = load_config()
    config.provider = provider_name
    config.runtime = _DEFAULT_RUNTIME.get(provider_name, config.runtime)
    console.print(f"[bold]Switching provider → {provider_name}[/]")
    report = apply(config)
    _print_report(report)
    console.print("  Then [cyan]mcpm client sync[/].")


@compression.command(name="use", help="Switch the active preset and re-apply.")
@click.argument("preset_name")
def use_preset(preset_name: str) -> None:
    config = load_config()
    if preset_name not in config.presets:
        err.print(f"[red]unknown preset {preset_name!r}[/] (have: {', '.join(config.presets)})")
        raise SystemExit(1)
    config.active_preset = preset_name
    p = config.presets[preset_name]
    console.print(f"[bold]Active preset → {preset_name}[/] "
                  f"(mode={p.mode}, profile={p.savings_profile or '—'}, port={p.port})")
    report = apply(config)
    _print_report(report)
    console.print("  Note: mode is fixed at proxy cold-start — restart the proxy to apply a mode change.")


@compression.command(help="List presets (optionally re-snapshot their knobs from the pinned binary).")
@click.option("--refresh", is_flag=True, help="Re-snapshot each preset's knobs from `headroom agent-savings`.")
def presets(refresh: bool) -> None:
    config = load_config()
    if refresh:
        _refresh_snapshots(config)
    table = Table(show_header=True, box=None)
    for col in ("", "preset", "mode", "savings", "port", "knobs", "snapshot"):
        table.add_column(col)
    for name, p in config.presets.items():
        table.add_row("●" if name == config.active_preset else "",
                      name, p.mode, p.savings_profile or "—", str(p.port),
                      str(len(p.knobs)),
                      p.snapshot_version or "[yellow]unknown[/]")
    console.print(table)


@compression.command(help="Show or set the exact headroom pin (and optionally install it).")
@click.argument("version", required=False)
@click.option("--install", "do_install", is_flag=True,
              help="Install the pinned build exactly (uv tool install ==<pin> --force).")
@click.option("--refresh", is_flag=True,
              help="Re-snapshot preset knobs from the pinned binary after installing.")
def pin(version: str | None, do_install: bool, refresh: bool) -> None:
    config = load_config()
    pv = config.provider_version

    if version:
        pv.pin = version
        save_config(config)
        # escape(): the extras marker reads as Rich markup and would be swallowed, leaving
        # a requirement that installs headroom without its proxy.
        console.print(f"[bold]Pin → {version}[/]  (requirement: [cyan]{escape(pv.requirement())}[/])")
        console.print("  [dim]presets still hold values snapshotted from another build — "
                      "re-snapshot with `--install --refresh`.[/]")

    live = hr_version()
    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_row("pin", f"[bold]{pv.pin}[/]")
    table.add_row("requirement", escape(pv.requirement()))
    table.add_row("installed", live or "[yellow]not on PATH[/]")
    if live and live != pv.pin:
        table.add_row("", "[red]drift — installed ≠ pin[/]")
    console.print(table)

    if not do_install:
        if live and live != pv.pin:
            console.print("\n  Install the pin: [cyan]mcpm compression pin --install --refresh[/]")
        return

    console.print(f"\n[bold]Installing {escape(pv.requirement())}[/]")
    ok, detail, before, after = hr_install(pv.requirement())
    (console.print if ok else err.print)(f"  [{'green' if ok else 'red'}]{'✓' if ok else '✗'}[/] {detail}")
    if not ok:
        raise SystemExit(1)
    if refresh:
        _refresh_snapshots(config)
    if before != after:
        console.print("  • restart proxies to run the pinned build: "
                      "[cyan]mcpm compression proxy restart[/] (close attached sessions first)")


def _refresh_snapshots(config) -> None:
    """Re-snapshot every profile-backed preset from the installed binary.

    Only `profile`-sourced knobs are replaced. Our own declarations (`policy`) survive and
    win — a re-snapshot that dropped them would hand those knobs back to the vendor's
    default, which is exactly the drift the pin exists to stop. Raises rather than
    inventing a snapshot when the binary is unavailable.
    """
    live = hr_version()
    changed = 0
    for name, preset in config.presets.items():
        if not preset.savings_profile:
            continue
        try:
            env = snapshot_profile_env(preset.savings_profile)
        except HeadroomUnavailable as e:
            err.print(f"  [red]✗[/] preset '{name}': {e}")
            raise SystemExit(1)
        before = {k: s.value for k, s in preset.knobs.items()}
        kept = {k: s for k, s in preset.knobs.items() if s.source == "policy"}
        merged = {k: KnobSpec(value=v, source="profile") for k, v in env.items()}
        merged.update(kept)  # our declarations outrank the vendor's profile
        preset.knobs = merged
        preset.snapshot_version = live

        after = {k: s.value for k, s in merged.items()}
        added = set(after) - set(before)
        removed = set(before) - set(after)
        moved = {k for k in set(after) & set(before) if after[k] != before[k]}
        if added or removed or moved:
            changed += 1
            console.print(f"  [green]✓[/] preset '{name}' re-snapshotted from {live}")
            for k in sorted(added):
                console.print(f"      [green]+[/] {k}={after[k]}")
            for k in sorted(removed):
                console.print(f"      [red]-[/] {k}  [dim](was {before[k]})[/]")
            for k in sorted(moved):
                console.print(f"      [yellow]~[/] {k}: {before[k]} → {after[k]}")
        if kept:
            console.print(f"      [dim]kept {len(kept)} declared knob(s): "
                          f"{', '.join(sorted(kept))}[/]")
    save_config(config)
    if not changed:
        console.print(f"  [green]✓[/] preset knobs already match {live}")


@compression.command(help="Bump the pin to a target build (or the newest published one), install it, and re-snapshot.")
@click.option("--to", "to_version", metavar="VERSION",
              help="Bump to this exact version (e.g. 0.31.0).")
@click.option("--latest", "to_latest", is_flag=True,
              help="Resolve the newest published headroom-ai from PyPI and bump to it.")
@click.option("--accept", is_flag=True,
              help="Actually move the pin, install, and re-snapshot. Without it this only previews.")
def update(to_version: str | None, to_latest: bool, accept: bool) -> None:
    """Move the exact pin deliberately — the one sanctioned path off the current build.

    A bare `update` (or `--latest`) resolves the newest published build; `--to` names one.
    Either way the target becomes an *exact* pin (`==<version>`), so the config still says
    which build it describes — the invariant the whole pinning stance rests on. `--accept`
    gates the mutation, so `hrupdate` can be one keystroke while a stray invocation only
    previews.
    """
    if to_version and to_latest:
        err.print("[red]✗[/] pass either --to or --latest, not both")
        raise SystemExit(2)

    config = load_config()
    pv = config.provider_version
    current = pv.pin

    # No explicit target means "newest" — that is what auto-detection buys.
    if to_version:
        target = to_version
    else:
        console.print("[dim]Resolving newest headroom-ai from PyPI…[/]")
        target = hr_latest(pv.package)
        if not target:
            err.print("[red]✗[/] could not resolve the latest version from PyPI "
                      "(offline?). Name it explicitly: [cyan]mcpm compression update --to X[/]")
            raise SystemExit(1)

    if not version_tuple(target):
        err.print(f"[red]✗[/] '{target}' is not a parseable X.Y.Z version")
        raise SystemExit(2)

    same = target == current
    console.print(f"[bold]Update pin[/]  "
                  f"{'already pinned at ' + target if same else current + ' → ' + target}")
    # Newest is unverified against the recorded fixtures/contract by construction — the
    # reason the pin exists. Surface it every time, then let verify be the arbiter.
    console.print("  [yellow]![/] this build is unverified against the recorded contract — "
                  "run [cyan]mcpm compression verify[/] after, and sanity-check the savings.")

    if not accept:
        console.print("\n  [dim]preview only — re-run with [cyan]--accept[/] "
                      "to move the pin, install, and re-snapshot.[/]")
        return

    pv.pin = target
    save_config(config)
    console.print(f"\n[bold]Installing {escape(pv.requirement())}[/]")
    ok, detail, before, after = hr_install(pv.requirement())
    (console.print if ok else err.print)(f"  [{'green' if ok else 'red'}]{'✓' if ok else '✗'}[/] {detail}")
    if not ok:
        raise SystemExit(1)
    _refresh_snapshots(config)
    if before != after:
        console.print("  • restart proxies to run the new build: "
                      "[cyan]mcpm compression proxy restart[/] (close attached sessions first)")


@compression.command(help="Declare the posture a live proxy is running, so an upgrade can't move it.")
@click.argument("preset_name", required=False)
@click.option("--apply", "do_apply", is_flag=True, help="Write the captured posture into policy.")
def seal(preset_name: str | None, do_apply: bool) -> None:
    """Capture `/health.config` from the running proxy into `policy` knobs.

    Behaviour-preserving by construction: it declares what the proxy is *already* running,
    so sealing changes nothing today — it only stops a future build from quietly deciding
    differently. Settings reported as unset (`None`) are headroom's own internal defaults
    and cannot be expressed as env, so they are listed, never invented.
    """
    config = load_config()
    name = preset_name or config.active_preset
    if name not in config.presets:
        err.print(f"[red]unknown preset {name!r}[/] (have: {', '.join(config.presets)})")
        raise SystemExit(1)
    preset = config.presets[name]

    if not cap_effective(preset.port):
        err.print(f"  [red]✗[/] no proxy on :{preset.port} — start one first "
                  f"([cyan]mcpm compression proxy up[/]). /health is the only truthful "
                  f"source for what a build actually runs.")
        raise SystemExit(1)

    declarable, unset = split_unsealed(cap_unsealed(preset.knobs, preset.port))
    if not declarable and not unset:
        console.print(f"  [green]✓[/] preset '{name}' already declares its whole posture")
        return

    console.print(f"[bold]Posture of '{name}' on :{preset.port} (headroom {hr_version()})[/]")
    for k, v in sorted(declarable.items()):
        console.print(f"  [green]+[/] {k}={v}   [dim]vendor default → would become policy[/]")
    for k, v in sorted(unset.items()):
        console.print(f"  [dim]·[/] {k}  [dim]unset — headroom's internal default; not "
                      f"expressible as env, stable only because the build is pinned[/]")

    if not do_apply:
        console.print(f"\n  {len(declarable)} declarable, {len(unset)} unsealable. "
                      f"Apply with [cyan]mcpm compression seal {name} --apply[/]")
        return
    for k, v in declarable.items():
        preset.knobs[k] = KnobSpec(value=v, source="policy")
    save_config(config)
    console.print(f"\n  [green]✓[/] sealed {len(declarable)} knob(s) into '{name}' as policy "
                  f"(runtime unchanged — these are the values already in force)")
    if unset:
        console.print(f"  [dim]{len(unset)} setting(s) remain at headroom's internal default; "
                      f"a pin bump will diff them.[/]")


@compression.command(help="Measure real prompt-cache behaviour from Claude Code's own transcripts.")
@click.option("--limit", type=int, default=None, help="Only the N most recent sessions.")
@click.option("--min-turns", type=int, default=5, show_default=True,
              help="Ignore sessions with fewer billed turns.")
@click.option("--by-pin", is_flag=True,
              help="Break the proxied bucket down by the headroom pin each session ran "
                   "against (A/B by version).")
def verify(limit: int | None, min_turns: int, by_pin: bool) -> None:
    paths = list(iter_transcripts())
    if limit:
        paths = paths[:limit]
    if not paths:
        err.print("  [yellow]![/] no Claude Code transcripts found — nothing to measure")
        raise SystemExit(1)
    if not schema_ok(paths):
        # Skip loudly. Zeros here would read as a total cache collapse rather than a
        # field Claude Code stopped writing.
        err.print("  [red]✗[/] transcripts carry no cache_* usage fields — Claude Code's "
                  "format may have changed. Refusing to report a number.")
        raise SystemExit(1)

    buckets = partition(paths)
    metrics = {k: measure(v, min_turns=min_turns) for k, v in buckets.items()}
    proxied, plain, unattr = metrics["proxied"], metrics["plain"], metrics["unattributed"]

    table = Table(show_header=True, box=None)
    for col in ("bucket", "sessions", "turns", "read ratio", "read:write"):
        table.add_column(col)
    for label, m, note in (
        ("proxied", proxied, "through headroom"),
        ("plain", plain, "control — run, not routed"),
        ("unattributed", unattr, "baseline — predates the ledger"),
    ):
        if not m.sessions:
            table.add_row(f"[dim]{label}[/]", "[dim]—[/]", "[dim]—[/]", "[dim]—[/]",
                          f"[dim]{note}[/]")
            continue
        table.add_row(label, f"{m.sessions:,}", f"{m.turns:,}",
                      f"[bold]{m.read_ratio:.1%}[/]" if m.read_ratio is not None else "—",
                      f"[bold]{m.read_write:.2f}x[/]" if m.read_write is not None else "—")
    console.print(table)

    if not proxied.sessions:
        console.print("\n  [yellow]![/] no proxied sessions yet — nothing to judge. "
                      "Enable headroom, work through [cyan]hrclaude[/], then re-run.")
        console.print(f"  [dim]baseline for comparison: "
                      f"{unattr.read_ratio:.1%} read ratio, {unattr.read_write:.2f}x "
                      f"over {unattr.sessions:,} sessions.[/]"
                      if unattr.read_ratio is not None else "")
        return

    ok, detail = proxied.verdict()
    console.print(f"\n  [{'green' if ok else 'red'}]{'✓ pass' if ok else '✗ fail'}[/] "
                  f"proxied — {detail}")
    # The comparison is the point: an absolute ratio means little without the counterfactual.
    for label, base in (("plain", plain), ("baseline", unattr)):
        delta = compare(base, proxied)
        if delta is None:
            continue
        colour = "green" if delta >= -1 else "red"
        console.print(f"  vs {label}: [{colour}]{delta:+.1f} pp[/] read ratio "
                      f"[dim]({base.read_ratio:.1%} → {proxied.read_ratio:.1%})[/]")
    if by_pin:
        by = partition_by_pin(buckets["proxied"])
        base_rw = unattr.read_write
        if not by:
            console.print("\n  [dim]--by-pin: no pin-tagged proxied sessions yet.[/]")
        else:
            console.print("\n  [bold]proxied by pin[/] — A/B by headroom version:")
            pin_table = Table(show_header=True, box=None)
            for col in ("pin", "sessions", "turns", "read ratio", "read:write", "vs baseline"):
                pin_table.add_column(col)
            for pin in sorted(by):
                pm = measure(by[pin], min_turns=min_turns)
                if not pm.sessions:
                    continue
                if pm.read_write is not None and base_rw is not None:
                    colour = "green" if pm.read_write >= base_rw else "red"
                    vs_base = f"[{colour}]{pm.read_write - base_rw:+.2f}x[/]"
                else:
                    vs_base = "—"
                pin_table.add_row(
                    pin, f"{pm.sessions:,}", f"{pm.turns:,}",
                    f"{pm.read_ratio:.1%}" if pm.read_ratio is not None else "—",
                    f"{pm.read_write:.2f}x" if pm.read_write is not None else "—",
                    vs_base,
                )
            console.print(pin_table)
            if base_rw is not None:
                console.print(f"  [dim]a pin earns re-enable only if it does not degrade vs "
                              f"baseline ({base_rw:.2f}x read:write).[/]")
    console.print("  [dim]source: provider-billed usage in Claude Code transcripts — "
                  "never headroom's own /stats (its accounting was wrong four ways across "
                  "0.28–0.31).[/]")
    if not ok:
        raise SystemExit(1)


@compression.command(help="Re-apply the current config (idempotent reconcile).")
def sync() -> None:
    config = load_config()
    report = apply(config)
    _print_report(report)


@compression.command(help="Diagnose the setup (binaries, port, config sanity).")
def doctor() -> None:
    config, notes = load_config_verbose()
    for n in notes:
        console.print(f"  [cyan]migrated[/] {n}")
    checks = []
    checks.append(("headroom binary", shutil.which("headroom") is not None,
                   shutil.which("headroom") or "not on PATH"))
    checks.append(("rtk binary", shutil.which("rtk") is not None,
                   shutil.which("rtk") or "not on PATH (optional)"))
    pin = config.provider_version.pin
    if shutil.which("headroom"):
        v = hr_version()
        # Exact match only. "Newer" is unverified, not fine — 0.31 was newer than the old
        # 0.27 contract and shipped a measured cache-busting regression that this check,
        # written as `>=`, reported as ok.
        checks.append(("headroom version", v == pin,
                       f"{v} == pin {pin}" if v == pin
                       else f"{v or 'unknown'} ≠ pin {pin} — run `pin --install`"))
    # Provenance: a preset whose knobs came from an unknown build is a preset whose
    # behaviour nobody can predict.
    stale = [n for n, p in config.presets.items()
             if p.savings_profile and p.snapshot_version != pin]
    checks.append(("preset provenance", not stale,
                   "all snapshots match the pin" if not stale
                   else f"snapshotted from another build: {', '.join(stale)} — `presets --refresh`"))

    # Inert: we declare it, the pinned build never reads it. headroom's own agent-savings
    # emits two such knobs, so this is not hypothetical.
    inert_all = {}
    for name, preset in config.presets.items():
        for knob, alt in cap_inert(preset.knobs).items():
            inert_all.setdefault(knob, (alt, []))[1].append(name)
    if inert_all:
        detail = "; ".join(
            f"{k} ({', '.join(v[1])}) → {v[0] or 'no equivalent'}" for k, v in inert_all.items()
        )
        checks.append(("inert knobs", False, f"declared but never read: {detail}"))
    else:
        checks.append(("inert knobs", True, "every declared knob is read by this build"))

    # Unsealed: the live proxy holds a posture value we never declared, i.e. the vendor is
    # deciding it. Needs a running proxy — /health is the only truthful source.
    port = config.preset_for().port
    live_cfg = cap_effective(port)
    if not live_cfg:
        checks.append(("sealed posture", True,
                       f"no proxy on :{port} — start one and re-run to audit the live posture"))
    else:
        declarable, unset = split_unsealed(cap_unsealed(config.preset_for().knobs, port))
        # Only `declarable` is actionable. `unset` is headroom's internal default, which no
        # env value can express — warning about it forever would be noise you can't clear.
        note = ("vendor-decided, declarable: "
                + ", ".join(f"{k}={v}" for k, v in sorted(declarable.items()))
                + " — run `seal --apply`") if declarable else "every declarable knob is policy"
        if unset:
            note += f"; {len(unset)} at headroom's internal default (unsealable, pinned)"
        checks.append(("sealed posture", not declarable, note))
    health = get_provider(config.provider).health(config)
    checks.append(("engine reachable", bool(health.get("ok")), health.get("detail", "")))
    desired = get_provider(config.provider).mcp_server_config(config)
    mcp_name = desired["name"] if desired else None
    if mcp_name:
        present = is_present(mcp_name)
        checks.append(("MCP registered", present,
                       f"{mcp_name} in servers.json" if present else f"{mcp_name} not registered"))
        clients = in_client(mcp_name)
        checks.append(("MCP in clients", bool(clients),
                       ", ".join(clients) if clients else "not in any client config"))
    else:
        checks.append(("MCP registered", True, "provider has no MCP server (ok)"))
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "")
    checks.append(("proxy env", base_url.endswith(str(config.preset_for().port)),
                   base_url or "ANTHROPIC_BASE_URL unset (launch via wrapper)"))
    legacy = launchd_plist_path().exists()
    checks.append(("legacy plist", not legacy,
                   "none (on-demand wrapper)" if not legacy
                   else f"{launchd_plist_path()} — run `mcpm compression sync` to remove"))
    table = Table(show_header=True, box=None)
    table.add_column("check")
    table.add_column("")
    table.add_column("detail")
    for name, ok, detail in checks:
        table.add_row(name, "[green]ok[/]" if ok else "[yellow]—[/]", detail)
    console.print(table)


@compression.command(
    name="env",
    help="Print exportable shell env for a directory's compression policy "
    "(consumed by launchers like hrclaude; plain stdout for `eval`).",
)
@click.option("--cwd", "cwd", default=None,
              help="Directory to resolve the policy for (default: current dir).")
def env_cmd(cwd: str) -> None:
    # Plain stdout only — this is meant to be `eval`'d by a shell, so no rich markup.
    cwd = cwd or os.getcwd()
    config = load_config()
    provider_name, preset_name = config.resolve(cwd)
    # Runtime follows the *resolved* provider, not the global default — a context rule
    # selecting headroom must engage the proxy even when the global provider isn't headroom.
    runtime = _DEFAULT_RUNTIME.get(provider_name, "none")
    if provider_name == "headroom" and runtime == "proxy":
        preset = config.preset_for(preset_name)
        for k, v in get_provider("headroom").env_for_preset(config, preset).items():
            click.echo(f'export {k}="{v}"')
        click.echo(f"HRCOMPRESS_PORT={preset.port}")
        click.echo(f"HRCOMPRESS_PRESET={preset_name}")
        click.echo("HRCOMPRESS_LAUNCH=route")
    else:
        # rtk-only / none → launch plain `claude` (rtk's hook is global; no proxy).
        click.echo("HRCOMPRESS_LAUNCH=plain")


@compression.command(
    name="run",
    help="Launch claude under this directory's compression policy "
    "(resolves the preset, ensures the proxy, then execs claude).",
    context_settings=dict(ignore_unknown_options=True),
)
@click.option("--cwd", "cwd", default=None, help="Directory to resolve the policy for.")
@click.option("--force", is_flag=True,
              help="Route even when the installed build doesn't match the pin.")
@click.argument("claude_args", nargs=-1, type=click.UNPROCESSED)
def run(cwd: str, force: bool, claude_args: tuple) -> None:
    cwd = cwd or os.getcwd()
    config = load_config()
    provider_name, preset_name = config.resolve(cwd)
    preset = config.preset_for(preset_name)
    child_env = dict(os.environ)
    pin = config.provider_version.pin

    def _launch(routed: bool):
        # The transcript records no endpoint, so this is the only moment anyone knows
        # whether these turns went through the proxy. Log it, then hand over the TTY.
        append_launch(cwd=cwd, provider=provider_name, preset=preset_name, routed=routed,
                      port=preset.port if routed else None, pin=pin)
        os.execvpe("claude", ["claude", *claude_args], child_env)

    if provider_name == "headroom" and _DEFAULT_RUNTIME.get(provider_name) == "proxy":
        if not _pin_ok(config, force):
            # Fail safe: an unverified proxy is how headroom#2085 burned 36% of a weekly
            # cap in one session. Losing compression is cheap; losing the cache is not.
            child_env.pop("ANTHROPIC_BASE_URL", None)
            _launch(routed=False)
            return  # execvpe replaces the process; only reachable under test
        env = get_provider("headroom").env_for_preset(config, preset)
        ok, detail = hr_proxy_up(preset.port, env)
        if not ok:
            # A proxy we couldn't start is not a proxy we're routing through — say so, and
            # record the launch as plain so `verify` never credits it to headroom.
            err.print(f"  [yellow]![/] {detail} — launching plain claude")
            child_env.pop("ANTHROPIC_BASE_URL", None)
            _launch(routed=False)
            return
        child_env.update(env)
        _launch(routed=True)
        return
    # none / rtk-only → go direct (rtk's hook is global; no proxy).
    child_env.pop("ANTHROPIC_BASE_URL", None)
    _launch(routed=False)


def _pin_ok(config, force: bool) -> bool:
    """Guard the launch path: refuse to route through an unpinned build."""
    pin = config.provider_version.pin
    live = hr_version()
    if live == pin:
        return True
    what = f"installed {live}" if live else "headroom not on PATH"
    if force:
        err.print(f"  [yellow]![/] {what} ≠ pin {pin} — routing anyway (--force)")
        return True
    err.print(f"  [red]![/] {what} ≠ pin {pin} — [bold]not routing[/]; launching plain claude.")
    err.print("      fix: [cyan]mcpm compression pin --install --refresh[/]  "
              "(or --force to override)")
    return False


@compression.group(help="Proxy lifecycle for the active preset (up / down / restart).")
def proxy() -> None:
    pass


def _active_port_env():
    config = load_config()
    preset = config.preset_for()
    env = get_provider("headroom").env_for_preset(config, preset)
    return preset.port, env


@proxy.command("up", help="Start the proxy for the active preset (if not already up).")
def proxy_up_cmd() -> None:
    port, env = _active_port_env()
    ok, detail = hr_proxy_up(port, env)
    (console.print if ok else err.print)(f"  [{'green' if ok else 'red'}]"
                                         f"{'✓' if ok else '✗'}[/] {detail}")


@proxy.command("down", help="Stop the proxy on the active preset's port.")
def proxy_down_cmd() -> None:
    port, _ = _active_port_env()
    ok, detail = hr_proxy_down(port)
    (console.print if ok else err.print)(f"  [{'green' if ok else 'yellow'}]"
                                         f"{'✓' if ok else '!'}[/] {detail}")


@proxy.command("restart", help="Restart the proxy (needed to change a cold-start mode).")
def proxy_restart_cmd() -> None:
    port, env = _active_port_env()
    hr_proxy_down(port)
    ok, detail = hr_proxy_up(port, env)
    (console.print if ok else err.print)(f"  [{'green' if ok else 'red'}]"
                                         f"{'✓' if ok else '✗'}[/] {detail}")
