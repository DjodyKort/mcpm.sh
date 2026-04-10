"""Skills add command -- create a new skill from template."""

from pathlib import Path

from rich.console import Console

from mcpm.skills.config import SkillsConfigManager
from mcpm.skills.schema import SkillFrontmatter
from mcpm.utils.rich_click_config import click

console = Console()


@click.command(name="add")
@click.argument("name")
@click.option("--type", "skill_type", type=click.Choice(["skill", "rule"]), default="skill", help="Type of skill")
@click.option("--path", type=click.Path(), default=".", help="Skills repo root (default: current directory)")
@click.help_option("-h", "--help")
def add_skill(name, skill_type, path):
    """Create a new skill or rule from a template.

    NAME should be kebab-case (e.g., 'code-review', 'commit-conventions').

    \b
        mcpm skills add code-review
        mcpm skills add commit-conventions --type rule
    """
    # Validate name early
    try:
        SkillFrontmatter(name=name, description="placeholder")
    except Exception as e:
        console.print(f"[red]Error: Invalid skill name '{name}': {e}[/]")
        return

    repo_path = Path(path).resolve()
    manager = SkillsConfigManager(project_root=repo_path)

    # Check if skill already exists
    base_dir = "rules" if skill_type == "rule" else "skills"
    if (repo_path / base_dir / name).exists():
        console.print(f"[red]Error: {skill_type.capitalize()} '{name}' already exists.[/]")
        return

    skill_file = manager.scaffold_skill(name, skill_type=skill_type)

    console.print(f"\n[green]{skill_type.capitalize()} '{name}' created at {skill_file}[/]\n")
    console.print("Edit the SKILL.md file, then run 'mcpm skills sync' to transpile to all clients.\n")
