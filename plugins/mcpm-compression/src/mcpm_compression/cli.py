"""`mcpm compression` — manage the swappable context-compression layer."""
from __future__ import annotations

import os
import shutil

import click
from rich.console import Console
from rich.table import Table

from .config import load_config, save_config
from .mcp_presence import in_client, is_present, present_entry
from .providers import get_provider, provider_names
from .providers.headroom_runtime import (
    PINNED_VERSION,
    proxy_down as hr_proxy_down,
    proxy_up as hr_proxy_up,
    version as hr_version,
)
from .runtime import LAUNCHD_LABEL, launchd_plist_path
from .runtime.shell import SHELL_SNIPPET_PATH, SHIMS_PATH
from .schema import DEFAULT_PORT
from .sync import apply, disable as do_disable

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
        v = hr_version()
        if v and v != PINNED_VERSION:
            table.add_row("headroom", f"[yellow]{v} — pinned {PINNED_VERSION} (drift)[/]")
        elif v:
            table.add_row("headroom", f"{v} (pinned {PINNED_VERSION})")
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


@compression.command(help="List presets (optionally re-snapshot their headroom env).")
@click.option("--refresh", is_flag=True, help="Re-snapshot each preset's env from `headroom agent-savings`.")
def presets(refresh: bool) -> None:
    config = load_config()
    if refresh:
        from .providers.headroom_runtime import snapshot_profile_env
        for p in config.presets.values():
            if p.savings_profile:
                p.env = snapshot_profile_env(p.savings_profile)
        save_config(config)
        console.print("[green]re-snapshotted preset env from headroom[/]")
    table = Table(show_header=True, box=None)
    for col in ("", "preset", "mode", "savings", "port", "read-outliner"):
        table.add_column(col)
    for name, p in config.presets.items():
        table.add_row("●" if name == config.active_preset else "",
                      name, p.mode, p.savings_profile or "—", str(p.port),
                      "on" if p.intercept_tool_results else "off")
    console.print(table)


@compression.command(help="Re-apply the current config (idempotent reconcile).")
def sync() -> None:
    config = load_config()
    report = apply(config)
    _print_report(report)


@compression.command(help="Diagnose the setup (binaries, port, config sanity).")
def doctor() -> None:
    config = load_config()
    checks = []
    checks.append(("headroom binary", shutil.which("headroom") is not None,
                   shutil.which("headroom") or "not on PATH"))
    checks.append(("rtk binary", shutil.which("rtk") is not None,
                   shutil.which("rtk") or "not on PATH (optional)"))
    if shutil.which("headroom"):
        v = hr_version()
        checks.append(("headroom version", v == PINNED_VERSION,
                       f"{v} (pinned {PINNED_VERSION})" if v else "unknown"))
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
@click.argument("claude_args", nargs=-1, type=click.UNPROCESSED)
def run(cwd: str, claude_args: tuple) -> None:
    cwd = cwd or os.getcwd()
    config = load_config()
    provider_name, preset_name = config.resolve(cwd)
    child_env = dict(os.environ)
    if provider_name == "headroom" and _DEFAULT_RUNTIME.get(provider_name) == "proxy":
        preset = config.preset_for(preset_name)
        env = get_provider("headroom").env_for_preset(config, preset)
        ok, detail = hr_proxy_up(preset.port, env)
        (err.print if not ok else lambda *_: None)(f"  [yellow]![/] {detail}")
        child_env.update(env)
    else:
        # none / rtk-only → go direct (rtk's hook is global; no proxy).
        child_env.pop("ANTHROPIC_BASE_URL", None)
    # Hand the TTY to claude: replace this process, do not wrap it.
    os.execvpe("claude", ["claude", *claude_args], child_env)


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
