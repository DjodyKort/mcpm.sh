"""`mcpm mode <server> <mode>` — flip proxy_mode for one server."""

from __future__ import annotations

import sys
from typing import get_args

from rich.console import Console

from mcpm.core.schema import ProxyMode
from mcpm.global_config import GlobalConfigManager
from mcpm.utils.rich_click_config import click

console = Console()
err_console = Console(stderr=True)

VALID_MODES = list(get_args(ProxyMode))


@click.command(name="mode", context_settings=dict(help_option_names=["-h", "--help"]))
@click.argument("server_name")
@click.argument("mode", type=click.Choice(VALID_MODES, case_sensitive=False))
def mode_cmd(server_name: str, mode: str):
    """Change a server's proxy_mode.

    \b
    Modes:
      auto      Default. HTTP servers go direct, stdio servers go through router.
      direct    Force raw command/url into client config. Bypasses mcpm at runtime.
      router    Force routing through the local router (stdio only).
      legacy    Use the old `mcpm run X` shape. Backward-compat escape hatch.

    \b
    Examples:
      mcpm mode clickup direct      # native OAuth flow
      mcpm mode anna-mcp router     # share one worker across clients
      mcpm mode broken-server legacy

    After changing the mode, run `mcpm client sync` to rewrite client configs.
    """
    config = GlobalConfigManager()
    server = config.get_server(server_name)
    if server is None:
        err_console.print(f"[red]Server '{server_name}' is not registered.[/]")
        err_console.print("[dim]Run `mcpm ls` to see installed servers.[/]")
        sys.exit(1)

    previous = getattr(server, "proxy_mode", "auto")
    if previous == mode:
        console.print(f"[dim]'{server_name}' is already in mode '{mode}'.[/]")
        return

    server.proxy_mode = mode  # type: ignore[assignment]
    if not config.update_server(server):
        err_console.print(f"[red]Failed to persist mode change for '{server_name}'.[/]")
        sys.exit(2)

    console.print(f"[green]Changed[/] '{server_name}': {previous} → {mode}")
    console.print("[dim]Run `mcpm client sync` to update client configs.[/]")
