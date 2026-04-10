"""Skills search command -- search across taps."""

from rich.console import Console
from rich.table import Table

from mcpm.skills.taps import TapManager
from mcpm.utils.rich_click_config import click

console = Console()


@click.command(name="search")
@click.argument("query")
@click.help_option("-h", "--help")
def search_skills(query):
    """Search across all taps for skills matching a query.

    Searches skill names, descriptions, and tags.

    \b
        mcpm skills search "code review"
        mcpm skills search terraform
    """
    manager = TapManager()
    results = manager.search(query)

    if not results:
        console.print(f"[yellow]No skills found matching '{query}'.[/]")
        taps = manager.list_taps()
        if not taps:
            console.print("No taps registered. Run 'mcpm skills tap add user/repo' to add one.")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Skill", style="cyan")
    table.add_column("Tap")
    table.add_column("Description", overflow="fold", max_width=60)

    for result in results:
        desc = result["description"][:60] + "..." if len(result["description"]) > 60 else result["description"]
        table.add_row(result["name"], result["tap"], desc)

    console.print(table)
    console.print(f"\n{len(results)} result(s). Install with: mcpm skills install @<repo>/<skill-name>")
