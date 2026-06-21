"""`mcpm compression` — manage the swappable context-compression layer."""
from __future__ import annotations

import os
import shutil

import click
from rich.console import Console
from rich.table import Table

from .config import load_config
from .mcp_presence import in_client, is_present, present_entry
from .providers import get_provider, provider_names
from .runtime import launchd_plist_path
from .runtime.shell import SHELL_SNIPPET_PATH
from .schema import DEFAULT_PORT, CompressionConfig
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
    table.add_row("scope", ", ".join(config.scope))
    ok = health.get("ok")
    table.add_row("engine", f"[green]healthy[/] — {health.get('detail','')}" if ok
                  else f"[red]down[/] — {health.get('detail','')}")
    if health.get("version"):
        table.add_row("version", str(health["version"]))
    entry = present_entry("headroom")
    table.add_row("MCP server", "[green]registered in mcpm[/]" if entry else "[dim]not in mcpm servers.json[/]")
    table.add_row("shell snippet", str(SHELL_SNIPPET_PATH) if SHELL_SNIPPET_PATH.exists()
                  else "[dim]none[/]")
    table.add_row("launchd plist", str(launchd_plist_path()) if launchd_plist_path().exists()
                  else "[dim]none[/]")
    console.print(table)


@compression.command(help="Enable compression with a provider (default: headroom).")
@click.option("--provider", "provider_name", type=click.Choice(provider_names()),
              default="headroom", show_default=True)
@click.option("--port", type=int, default=DEFAULT_PORT, show_default=True)
@click.option("--telemetry", type=click.Choice(["off", "on"]), default="off", show_default=True)
def enable(provider_name: str, port: int, telemetry: str) -> None:
    config = CompressionConfig(
        provider=provider_name,
        runtime=_DEFAULT_RUNTIME.get(provider_name, "none"),
        options={"port": port, "telemetry": telemetry},
    )
    console.print(f"[bold]Enabling compression: {provider_name}[/]")
    report = apply(config)
    _print_report(report)
    console.print("\n[bold]Next steps:[/]")
    if provider_name == "headroom":
        console.print(f"  • launch via your headroom wrapper, or [cyan]source {SHELL_SNIPPET_PATH}[/] (sets ANTHROPIC_BASE_URL)")
        console.print(f"  • optional always-warm proxy: [cyan]launchctl load -w {launchd_plist_path()}[/]")
    console.print("  • verify: [cyan]mcpm compression status[/] / [cyan]doctor[/]   (MCP presence already propagated)")


@compression.command(help="Disable compression (remove MCP entry + artifacts).")
def disable() -> None:
    console.print("[bold]Disabling compression[/]")
    report = do_disable()
    _print_report(report)
    console.print(f"\n  Note: unload launchd if you loaded it: [cyan]launchctl unload {launchd_plist_path()}[/]")


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
    health = get_provider(config.provider).health(config)
    checks.append(("engine reachable", bool(health.get("ok")), health.get("detail", "")))
    checks.append(("MCP registered", is_present("headroom"),
                   "headroom in servers.json" if is_present("headroom") else "not registered"))
    clients = in_client("headroom")
    checks.append(("MCP in clients", bool(clients),
                   ", ".join(clients) if clients else "not in any client config"))
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "")
    checks.append(("proxy env", base_url.endswith(str(config.port)),
                   base_url or "ANTHROPIC_BASE_URL unset (launch via wrapper)"))
    try:
        import subprocess
        loaded = subprocess.run(
            ["launchctl", "list", "sh.mcpm.compression.proxy"],
            capture_output=True, timeout=3,
        ).returncode == 0
    except Exception:
        loaded = False
    checks.append(("launchd proxy", loaded,
                   "loaded" if loaded else "not loaded (wrapper mode — ok)"))
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
    provider_name = config.resolved_provider(cwd)
    if provider_name == "headroom" and config.runtime == "proxy":
        for k, v in get_provider("headroom").runtime_spec(config).env.items():
            click.echo(f'export {k}="{v}"')
        click.echo("HRCOMPRESS_LAUNCH=wrap")
    else:
        # rtk-only / none → launch plain `claude` (rtk's hook is global; no proxy).
        click.echo("HRCOMPRESS_LAUNCH=plain")
