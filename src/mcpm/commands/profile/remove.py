"""Profile remove command."""

import logging

from rich.console import Console
from rich.prompt import Confirm

from mcpm.profile.profile_config import ProfileConfigManager
from mcpm.utils.rich_click_config import click

logger = logging.getLogger(__name__)

console = Console()
profile_config_manager = ProfileConfigManager()


@click.command(name="rm")
@click.argument("profile_name")
@click.option("--force", "-f", is_flag=True, help="Force removal without confirmation")
@click.option(
    "--no-clients",
    is_flag=True,
    help="Skip client config cleanup. Stale `mcpm_profile_<name>` entries will remain "
    "until you run `mcpm client edit` (or remove them manually).",
)
@click.help_option("-h", "--help")
def remove_profile(profile_name, force, no_clients):
    """Remove a profile.

    Deletes the specified profile and all its server associations, and (by
    default) prunes matching `mcpm_profile_<name>` entries from every
    installed client config so the client doesn't try to invoke a profile
    that no longer exists. The underlying servers remain in the global
    configuration.

    Examples:

    \\b
        mcpm profile rm old-profile             # Remove with confirmation
        mcpm profile rm old-profile --force     # Remove without confirmation
        mcpm profile rm old-profile --no-clients  # Leave client configs untouched
    """
    # Check if profile exists
    if profile_config_manager.get_profile(profile_name) is None:
        console.print(f"[red]Error: Profile '[bold]{profile_name}[/]' not found[/]")
        console.print()
        console.print("[yellow]Available options:[/]")
        console.print("  • Run 'mcpm profile ls' to see available profiles")
        return 1

    # Get profile info for confirmation
    profile_servers = profile_config_manager.get_profile(profile_name)
    server_count = len(profile_servers) if profile_servers else 0

    # Confirmation (unless forced)
    if not force:
        console.print(f"[yellow]About to remove profile '[bold]{profile_name}[/]'[/]")
        if server_count > 0:
            console.print(f"[dim]This profile contains {server_count} server(s)[/]")
            console.print("[dim]The servers will remain in global configuration[/]")
        console.print()

        confirm_removal = Confirm.ask("Are you sure you want to remove this profile?", default=False)

        if not confirm_removal:
            console.print("[yellow]Profile removal cancelled[/]")
            return 0

    # Remove the profile
    success = profile_config_manager.delete_profile(profile_name)

    if success:
        console.print(f"[green]✅ Profile '[cyan]{profile_name}[/]' removed successfully[/]")
        if server_count > 0:
            console.print(f"[dim]{server_count} server(s) remain available in global configuration[/]")

        # Propagate removal to installed clients so they don't keep stale
        # `mcpm_profile_<name>` entries pointing at a profile that no longer
        # exists. Symmetric with how `mcpm uninstall` handles servers.
        if not no_clients:
            try:
                from mcpm.commands.client import _remove_profile_from_clients

                results = _remove_profile_from_clients(profile_name)
            except Exception as exc:
                logger.debug(f"Client config propagation failed for profile '{profile_name}': {exc}")
                console.print(
                    f"[yellow]Could not propagate removal to client configs: {exc}.[/] "
                    "Run [cyan]mcpm client edit[/] manually to clean up."
                )
                return 0

            if results:
                total = sum(len(removed) for _, _, removed in results)
                console.print(
                    f"[dim]Cleaned {total} entr"
                    f"{'y' if total == 1 else 'ies'} from "
                    f"{len(results)} client(s):[/]"
                )
                for _, display, removed in results:
                    console.print(f"  [dim]•[/] {display}: {', '.join(removed)}")
                console.print("[dim]Restart your MCP clients for the changes to take effect.[/]")
    else:
        console.print(f"[red]Error removing profile '[bold]{profile_name}[/]'[/]")
        return 1

    return 0
