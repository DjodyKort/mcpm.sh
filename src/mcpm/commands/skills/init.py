"""Skills init command -- scaffold a new skills repository."""

from pathlib import Path

from rich.console import Console

from mcpm.skills.config import SkillsConfigManager
from mcpm.utils.rich_click_config import click

console = Console()


@click.command(name="init")
@click.option("--path", type=click.Path(), default=".", help="Directory to initialize (default: current directory)")
@click.option("--name", type=str, default=None, help="Repository name (default: directory name)")
@click.help_option("-h", "--help")
def init_skills(path, name):
    """Initialize a new skills repository.

    Creates the directory structure and manifest file for a skills repo:
    mcpm-skills.yaml, skills/, rules/, profiles/

    \b
        mcpm skills init
        mcpm skills init --path ./my-skills --name my-skills
    """
    repo_path = Path(path).resolve()
    if name is None:
        name = repo_path.name

    manager = SkillsConfigManager(project_root=repo_path)

    if manager.has_skills_repo():
        console.print(f"[yellow]Skills repository already exists at {repo_path}[/]")
        return

    manager.init_repo(name=name)

    console.print(f"\n[green]Skills repository initialized at {repo_path}[/]\n")
    console.print("Created:")
    console.print("  mcpm-skills.yaml  (repo manifest)")
    console.print("  skills/           (progressive-disclosure skills)")
    console.print("  rules/            (always-on rules)")
    console.print("  profiles/         (named groupings)")
    console.print("\nNext: run 'mcpm skills add <name>' to create your first skill.\n")
