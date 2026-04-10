"""Skills diff command -- show changes since last sync."""

from pathlib import Path

from rich.console import Console

from mcpm.skills.config import SkillsConfigManager
from mcpm.skills.parser import discover_skills, find_skills_repo
from mcpm.skills.transpiler import compute_skill_hash
from mcpm.utils.rich_click_config import click

console = Console()


@click.command(name="diff")
@click.option("--path", type=click.Path(), default=None, help="Skills repo root (default: auto-detect)")
@click.help_option("-h", "--help")
def diff_skills(path):
    """Show what has changed since last sync.

    Compares current skill files against the lockfile to detect new, modified, or deleted skills.

    \b
        mcpm skills diff
    """
    start_path = Path(path).resolve() if path else None
    repo_path = find_skills_repo(start_path)
    if not repo_path:
        console.print("[yellow]No skills repository found.[/]")
        return

    config_manager = SkillsConfigManager(project_root=repo_path)
    lockfile = config_manager.load_lockfile()

    skills = discover_skills(repo_path)
    current_names = {s.name for s in skills}

    if lockfile is None:
        console.print("[yellow]No lockfile found. All skills are new.[/]\n")
        for skill in skills:
            console.print(f"  [green]+ {skill.name}[/] ({skill.skill_type})")
        return

    locked_names = set(lockfile.skills.keys()) | set(lockfile.rules.keys())
    locked_entries = {**lockfile.skills, **lockfile.rules}

    new_skills = current_names - locked_names
    removed_skills = locked_names - current_names
    common_skills = current_names & locked_names

    modified_skills = set()
    for skill in skills:
        if skill.name in common_skills:
            current_hash = compute_skill_hash(skill)
            locked_hash = locked_entries[skill.name].hash
            if current_hash != locked_hash:
                modified_skills.add(skill.name)

    unchanged = common_skills - modified_skills

    if not new_skills and not removed_skills and not modified_skills:
        console.print("[green]No changes since last sync.[/]")
        return

    console.print()
    for name in sorted(new_skills):
        console.print(f"  [green]+ {name}[/] (new)")
    for name in sorted(modified_skills):
        console.print(f"  [yellow]~ {name}[/] (modified)")
    for name in sorted(removed_skills):
        console.print(f"  [red]- {name}[/] (removed)")
    if unchanged:
        console.print(f"  [dim]{len(unchanged)} unchanged[/]")
    console.print()
