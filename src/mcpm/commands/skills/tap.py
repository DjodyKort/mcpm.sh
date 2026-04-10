"""Skills tap commands -- manage remote skill repositories."""

from rich.console import Console
from rich.table import Table

from mcpm.skills.taps import TapManager
from mcpm.utils.rich_click_config import click

console = Console()


@click.group()
@click.help_option("-h", "--help")
def tap():
    """Manage remote skill repository taps.

    Taps are git repositories containing skills in the mcpm format.
    Register taps to search and install skills from them.

    \b
        mcpm skills tap add anthropics/skills
        mcpm skills tap list
    """
    pass


@click.command(name="add")
@click.argument("repo")
@click.option("--name", type=str, default=None, help="Alias for the tap")
@click.help_option("-h", "--help")
def tap_add(repo, name):
    """Register and clone a remote skills repository.

    REPO should be in user/repo format (e.g. 'anthropics/skills').

    \b
        mcpm skills tap add anthropics/skills
        mcpm skills tap add myorg/private-skills --name work
    """
    manager = TapManager()

    console.print(f"[cyan]Cloning {repo}...[/]")
    if manager.add(repo, alias=name):
        display_name = name or repo.replace("/", "-")
        console.print(f"[green]Tap '{display_name}' added successfully.[/]")
    else:
        console.print("[red]Failed to add tap. Check that the repository exists and is accessible.[/]")


@click.command(name="remove")
@click.argument("name")
@click.help_option("-h", "--help")
def tap_remove(name):
    """Unregister and remove a tap.

    \b
        mcpm skills tap remove anthropics-skills
    """
    manager = TapManager()
    if manager.remove(name):
        console.print(f"[green]Tap '{name}' removed.[/]")
    else:
        console.print(f"[red]Tap '{name}' not found.[/]")


@click.command(name="update")
@click.argument("name", required=False)
@click.help_option("-h", "--help")
def tap_update(name):
    """Update one or all taps (git pull).

    \b
        mcpm skills tap update
        mcpm skills tap update anthropics-skills
    """
    manager = TapManager()
    results = manager.update(name)

    if not results:
        console.print("[yellow]No taps registered.[/]")
        return

    for tap_name, success in results.items():
        if success:
            console.print(f"  [green]Updated {tap_name}[/]")
        else:
            console.print(f"  [red]Failed to update {tap_name}[/]")


@click.command(name="ls")
@click.help_option("-h", "--help")
def tap_list():
    """List all registered taps.

    \b
        mcpm skills tap list
    """
    manager = TapManager()
    taps = manager.list_taps()

    if not taps:
        console.print("[yellow]No taps registered. Run 'mcpm skills tap add user/repo' to add one.[/]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Name", style="cyan")
    table.add_column("Repository")
    table.add_column("Path", overflow="fold")

    for name, info in taps.items():
        table.add_row(name, info.get("repo", ""), info.get("path", ""))

    console.print(table)


# Register subcommands
tap.add_command(tap_add)
tap.add_command(tap_remove)
tap.add_command(tap_update)
tap.add_command(tap_list)
