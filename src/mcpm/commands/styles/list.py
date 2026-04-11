"""List available output styles."""

from pathlib import Path

from rich.console import Console
from rich.table import Table

from mcpm.skills.config import SkillsConfigManager
from mcpm.skills.parser import find_skills_repo
from mcpm.styles.parser import discover_styles
from mcpm.utils.rich_click_config import click

console = Console()


@click.command(name="ls")
@click.option("--path", type=click.Path(), default=None, help="Skills repo root (default: auto-detect)")
@click.help_option("-h", "--help")
def list_styles(path):
    """List available output styles and their active status.

    \b
        mcpm styles ls
    """
    start_path = Path(path).resolve() if path else None
    repo_path = find_skills_repo(start_path)
    if not repo_path:
        console.print("[red]Error: No skills repository found. Run 'mcpm skills init' first.[/]")
        return

    found_styles = discover_styles(repo_path)
    if not found_styles:
        console.print("[yellow]No styles found. Run 'mcpm styles add <name>' to create one.[/]")
        return

    config_manager = SkillsConfigManager(project_root=repo_path)
    lockfile = config_manager.load_lockfile()

    table = Table(show_header=True, header_style="bold")
    table.add_column("Style", style="cyan")
    table.add_column("Description", overflow="fold")
    table.add_column("Keep coding instructions")
    table.add_column("Synced to", overflow="fold")

    for style in found_styles:
        desc = style.frontmatter.description
        if len(desc) > 60:
            desc = desc[:60] + "..."
        keep = "[green]yes[/]" if style.frontmatter.keep_coding_instructions else "[red]no[/]"

        synced = ""
        if lockfile and style.name in lockfile.styles:
            entry = lockfile.styles[style.name]
            synced = ", ".join(entry.clients_synced) if entry.clients_synced else "[dim]--[/]"
        else:
            synced = "[dim]not synced[/]"

        table.add_row(style.name, desc, keep, synced)

    console.print(table)

    # Show active Tier 2 styles
    if lockfile and lockfile.active_styles:
        console.print("\n[bold]Active styles (Tier 2 clients):[/]")
        for ck, sn in sorted(lockfile.active_styles.items()):
            console.print(f"  {ck}: [green]{sn}[/]")
