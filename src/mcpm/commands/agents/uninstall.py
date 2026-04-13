"""Agents uninstall command -- remove an installed agent."""

import shutil
from pathlib import Path

from rich.console import Console

from mcpm.skills.agents.transpiler import get_all_agent_transpilers
from mcpm.skills.config import SkillsConfigManager
from mcpm.utils.rich_click_config import click

console = Console()


@click.command(name="uninstall")
@click.argument("name")
@click.option("--path", type=click.Path(), default=".", help="Skills repo root (default: current directory)")
@click.help_option("-h", "--help")
def uninstall_agent(name, path):
    """Remove an installed agent and its transpiled outputs.

    \b
        mcpm agents uninstall reviewer
    """
    project_root = Path(path).resolve()

    agent_path = project_root / "agents" / name
    if not agent_path.exists():
        console.print(f"[red]Error: Agent '{name}' not found.[/]")
        return

    # Remove transpiled outputs from all clients
    transpilers = get_all_agent_transpilers()
    removed_outputs = 0
    for client_key, transpiler in transpilers.items():
        removed = transpiler.clean(project_root, managed_skills=[name])
        removed_outputs += len(removed)
        for p in removed:
            console.print(f"  [dim]Removed {p.relative_to(project_root)}[/]")

    # Remove the source agent directory
    shutil.rmtree(agent_path)
    console.print(f"  [red]Removed {agent_path.relative_to(project_root)}[/]")

    # Update lockfile
    config_manager = SkillsConfigManager(project_root=project_root)
    lockfile = config_manager.load_lockfile()
    if lockfile and hasattr(lockfile, "agents") and lockfile.agents:
        lockfile.agents.pop(name, None)
        config_manager.save_lockfile(lockfile)

    console.print(f"\n[green]Uninstalled '{name}' and removed {removed_outputs} output file(s).[/]")
