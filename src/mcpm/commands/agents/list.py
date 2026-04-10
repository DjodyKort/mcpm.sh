"""Agents list command."""

from pathlib import Path

from rich.console import Console
from rich.table import Table

from mcpm.skills.agents.parser import discover_agents
from mcpm.skills.parser import find_skills_repo
from mcpm.utils.rich_click_config import click

console = Console()


@click.command(name="ls")
@click.option("--path", type=click.Path(), default=None, help="Skills repo root (default: auto-detect)")
@click.help_option("-h", "--help")
def list_agents(path):
    """List all agents in the repository.

    \b
        mcpm agents ls
    """
    start_path = Path(path).resolve() if path else None
    repo_path = find_skills_repo(start_path)
    if not repo_path:
        console.print("[yellow]No skills repository found.[/]")
        return

    found_agents = discover_agents(repo_path)
    if not found_agents:
        console.print("[yellow]No agents found.[/]")
        return

    console.print(f"\n[green]Found {len(found_agents)} agent(s) in {repo_path}[/]\n")

    table = Table(show_header=True, header_style="bold")
    table.add_column("Name", style="cyan")
    table.add_column("Model")
    table.add_column("Tools", overflow="fold")
    table.add_column("Description", overflow="fold", max_width=50)

    for agent in found_agents:
        fm = agent.frontmatter
        model = fm.model or "[dim]default[/]"
        tools = ", ".join(fm.tools) if fm.tools else "[dim]all[/]"
        desc = fm.description[:50] + "..." if len(fm.description) > 50 else fm.description
        table.add_row(fm.name, model, tools, desc)

    console.print(table)
