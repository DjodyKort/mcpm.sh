"""Add a new output style scaffold."""

from pathlib import Path

from rich.console import Console

from mcpm.skills.config import SkillsConfigManager
from mcpm.skills.parser import find_skills_repo
from mcpm.styles.schema import StyleFrontmatter
from mcpm.utils.rich_click_config import click

console = Console()


@click.command(name="add")
@click.argument("name")
@click.option("--path", type=click.Path(), default=None, help="Skills repo root (default: auto-detect)")
@click.help_option("-h", "--help")
def add_style(name, path):
    """Create a new output style from a template.

    \b
        mcpm styles add concise-engineer
        mcpm styles add verbose-teacher
    """
    # Validate name early
    try:
        StyleFrontmatter(name=name, description="placeholder")
    except ValueError as e:
        console.print(f"[red]Invalid style name: {e}[/]")
        return

    start_path = Path(path).resolve() if path else None
    repo_path = find_skills_repo(start_path)
    if not repo_path:
        console.print("[red]Error: No skills repository found. Run 'mcpm skills init' first.[/]")
        return

    config_manager = SkillsConfigManager(project_root=repo_path)

    # Check if style already exists
    style_dir = repo_path / "styles" / name
    if style_dir.exists():
        console.print(f"[red]Style '{name}' already exists at {style_dir}[/]")
        return

    style_file = config_manager.scaffold_style(name)
    console.print(f"[green]Created style '{name}' at {style_file}[/]")
    console.print("[dim]Edit the file to add your style instructions, then run 'mcpm styles sync'.[/]")
