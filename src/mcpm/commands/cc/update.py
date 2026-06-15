"""``mcpm cc update`` -- refresh marketplace catalogs and update installed plugins.

Mirrors the flow of ``mcpm update`` for MCP servers: check, render a summary, then
(optionally) apply with a confirmation prompt.
"""

from rich.console import Console
from rich.prompt import Confirm

from mcpm.cc import claude_cli, updater
from mcpm.utils.non_interactive import is_non_interactive, should_force_operation
from mcpm.utils.rich_click_config import click

console = Console()


def _require_claude() -> bool:
    """Print a friendly message and return False when the Claude Code CLI is missing."""
    if claude_cli.is_available():
        return True
    console.print(
        "[yellow]Claude Code CLI not found.[/] 'mcpm cc' manages Claude Code plugins and "
        "needs the [bold]claude[/] command on your PATH.\n"
        "Install it from https://docs.anthropic.com/en/docs/claude-code"
    )
    return False


@click.command(name="update", context_settings=dict(help_option_names=["-h", "--help"]))
@click.argument("plugin", required=False)
@click.option("--check", "--dry-run", "-c", "check_only", is_flag=True, help="Check for updates only, don't apply them")
@click.option("--marketplace", "-m", help="Limit to plugins from one marketplace")
@click.option("--force", is_flag=True, help="Skip confirmation prompts")
@click.option("--verbose", "-V", is_flag=True, help="Show detailed output")
def update_cc(plugin, check_only, marketplace, force, verbose):
    """Update installed Claude Code plugins from their remotes.

    Refreshes the marketplace catalog(s) first (the "pull latest from remote" step), then
    updates installed plugins. Updates require a Claude Code restart to take effect.

    Examples:

    \b
        mcpm cc update                       # Refresh catalogs + update all plugins
        mcpm cc update my-plugin             # Update one plugin
        mcpm cc update --check               # Dry run -- show what's available
        mcpm cc update -m my-marketplace     # Limit to one marketplace
    """
    if not _require_claude():
        return

    console.print("[bold]Refreshing marketplace catalogs...[/]")
    result = updater.check_plugin_updates(plugin=plugin, marketplace=marketplace, refresh=True)

    if result.refresh_error:
        console.print(f"  [yellow]marketplace update warning:[/] {result.refresh_error}")

    checks = result.checks
    if plugin and not checks:
        console.print(f"\n[bold red]Error:[/] Plugin '{plugin}' is not installed.")
        return

    if not checks:
        console.print("\n[yellow]No plugins installed.[/] Use [bold]claude plugin install[/] to add one.")
        return

    console.print()
    updatable = []
    for check in checks:
        flags = []
        if not check.enabled:
            flags.append("[dim]disabled[/]")
        if check.blocked:
            flags.append("[red]blocked[/]")
        suffix = f"  {' '.join(flags)}" if flags else ""

        if check.error:
            console.print(f"  [cyan]{check.name:<28}[/] [red]error[/]   {check.error}{suffix}")
            continue
        if check.can_update and not check.blocked:
            updatable.append(check)
            console.print(f"  [cyan]{check.name:<28}[/] [green]update[/]  {check.summary}{suffix}")
        elif check.summary == "up to date":
            if verbose:
                console.print(f"  [cyan]{check.name:<28}[/] [dim]current[/] {check.summary}{suffix}")
        else:
            console.print(f"  [cyan]{check.name:<28}[/] [yellow]?[/]       {check.summary}{suffix}")

    # If the user named a plugin, honor it directly even when version detection is unknown
    # (claude plugin update is idempotent).
    if plugin and not updatable:
        target = next((c for c in checks if not c.blocked), None)
        if target:
            updatable = [target]

    if not updatable:
        console.print("\n[green]Nothing to update.[/] "
                      "[dim]Name a plugin explicitly to force an update if a version couldn't be compared.[/]")
        return

    if check_only:
        console.print(f"\n[bold]{len(updatable)} plugin(s) have updates available.[/]")
        return

    if not should_force_operation(force) and not is_non_interactive():
        if not Confirm.ask(f"\n{len(updatable)} plugin(s) will be updated. Continue?"):
            console.print("[yellow]Cancelled.[/]")
            return

    console.print()
    success_count = 0
    restart_needed = False
    for check in updatable:
        console.print(f"[bold]Updating {check.plugin_id}...[/]")
        outcome = updater.apply_plugin_update(check.plugin_id)
        if outcome.error:
            console.print(f"  [red]✗[/] {outcome.error}")
        else:
            console.print(f"  [green]✓[/] {outcome.message}")
            success_count += 1
            restart_needed = restart_needed or outcome.restart_required
        console.print()

    console.print(f"[bold green]Done.[/] {success_count} plugin(s) updated.")
    if restart_needed:
        console.print("[yellow]Restart Claude Code to apply the updates.[/]")
