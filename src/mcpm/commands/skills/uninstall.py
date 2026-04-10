"""Skills uninstall command -- remove an installed skill."""

import shutil
from pathlib import Path

from rich.console import Console

from mcpm.skills.config import SkillsConfigManager
from mcpm.skills.transpiler import get_all_transpilers
from mcpm.utils.rich_click_config import click

console = Console()


@click.command(name="uninstall")
@click.argument("name")
@click.option("--path", type=click.Path(), default=".", help="Skills repo root (default: current directory)")
@click.help_option("-h", "--help")
def uninstall_skill(name, path):
    """Remove an installed skill and its transpiled outputs.

    Does NOT uninstall MCP servers (they may be used by other skills).

    \b
        mcpm skills uninstall code-review
    """
    project_root = Path(path).resolve()

    # Find the skill directory
    skill_path = None
    for subdir in ["skills", "rules"]:
        candidate = project_root / subdir / name
        if candidate.exists():
            skill_path = candidate
            break

    if not skill_path:
        console.print(f"[red]Error: Skill '{name}' not found.[/]")
        return

    # Remove transpiled outputs from all clients
    transpilers = get_all_transpilers()
    removed_outputs = 0
    for client_key, transpiler in transpilers.items():
        removed = transpiler.clean(project_root, managed_skills=[name])
        removed_outputs += len(removed)
        for p in removed:
            console.print(f"  [dim]Removed {p.relative_to(project_root)}[/]")

    # Remove the source skill directory
    shutil.rmtree(skill_path)
    console.print(f"  [red]Removed {skill_path.relative_to(project_root)}[/]")

    # Update lockfile
    config_manager = SkillsConfigManager(project_root=project_root)
    lockfile = config_manager.load_lockfile()
    if lockfile:
        lockfile.skills.pop(name, None)
        lockfile.rules.pop(name, None)
        config_manager.save_lockfile(lockfile)

    console.print(f"\n[green]Uninstalled '{name}' and removed {removed_outputs} output file(s).[/]")
