"""Skills list command -- show installed skills with status."""

from pathlib import Path

from rich.console import Console
from rich.table import Table

from mcpm.skills.parser import discover_skills, find_skills_repo
from mcpm.utils.rich_click_config import click

console = Console()


@click.command(name="ls")
@click.option("--path", type=click.Path(), default=None, help="Skills repo root (default: auto-detect)")
@click.help_option("-h", "--help")
def list_skills(path):
    """List all skills in the repository.

    \b
        mcpm skills ls
    """
    start_path = Path(path).resolve() if path else None
    repo_path = find_skills_repo(start_path)
    if not repo_path:
        console.print("[yellow]No skills repository found. Run 'mcpm skills init' first.[/]")
        return

    skills = discover_skills(repo_path)
    if not skills:
        console.print("[yellow]No skills found.[/]")
        return

    console.print(f"\n[green]Found {len(skills)} skill(s) in {repo_path}[/]\n")

    table = Table(show_header=True, header_style="bold")
    table.add_column("Name", style="cyan")
    table.add_column("Type")
    table.add_column("Activation")
    table.add_column("Description", overflow="fold", max_width=60)
    table.add_column("Globs", overflow="fold")

    for skill in skills:
        fm = skill.frontmatter
        table.add_row(
            fm.name,
            skill.skill_type,
            fm.activation,
            fm.description[:60] + "..." if len(fm.description) > 60 else fm.description,
            fm.globs or "[dim]--[/]",
        )

    console.print(table)
