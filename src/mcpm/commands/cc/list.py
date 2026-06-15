"""``mcpm cc list`` -- read-only view of Claude Code marketplaces and plugins."""

from rich.console import Console
from rich.table import Table

from mcpm.cc import claude_cli, state, updater
from mcpm.utils.rich_click_config import click

console = Console()


@click.command(name="list", context_settings=dict(help_option_names=["-h", "--help"]))
@click.help_option("-h", "--help")
def list_cc():
    """List Claude Code marketplaces and installed plugins.

    Read-only: reads Claude Code's on-disk state and ``claude plugin list``; makes no
    changes.
    """
    if not claude_cli.is_available():
        console.print(
            "[yellow]Claude Code CLI not found.[/] 'mcpm cc' needs the [bold]claude[/] "
            "command on your PATH."
        )
        return

    marketplaces = state.read_known_marketplaces()
    if marketplaces:
        mkt_table = Table(title="Marketplaces", title_justify="left", show_edge=False, pad_edge=False)
        mkt_table.add_column("name", style="cyan")
        mkt_table.add_column("source", style="dim")
        mkt_table.add_column("last updated", style="dim")
        for name, meta in sorted(marketplaces.items()):
            source = meta.get("source") or {}
            src = source.get("repo") or source.get("url") or source.get("source") or "-"
            mkt_table.add_row(name, str(src), str(meta.get("lastUpdated") or "-"))
        console.print(mkt_table)
    else:
        console.print("[yellow]No marketplaces configured.[/]")

    console.print()

    # Plugins (no catalog refresh -- this is a read-only view of current state).
    check = updater.check_plugin_updates(refresh=False)
    if not check.checks:
        console.print("[yellow]No plugins installed.[/] Use [bold]claude plugin install[/] to add one.")
        return

    plug_table = Table(title="Installed plugins", title_justify="left", show_edge=False, pad_edge=False)
    plug_table.add_column("plugin", style="cyan")
    plug_table.add_column("marketplace", style="dim")
    plug_table.add_column("version", style="dim")
    plug_table.add_column("status")
    for c in sorted(check.checks, key=lambda x: x.plugin_id):
        if c.blocked:
            status = "[red]blocked[/]"
        elif not c.enabled:
            status = "[dim]disabled[/]"
        else:
            status = "[green]enabled[/]"
        plug_table.add_row(c.name, c.marketplace or "-", c.current_version or "-", status)
    console.print(plug_table)
