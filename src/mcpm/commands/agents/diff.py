"""Agents diff command -- show changes since last sync."""

from pathlib import Path

from rich.console import Console

from mcpm.skills.agents.parser import discover_agents
from mcpm.skills.agents.transpiler import compute_agent_hash
from mcpm.skills.config import SkillsConfigManager
from mcpm.skills.parser import find_skills_repo
from mcpm.utils.rich_click_config import click

console = Console()


@click.command(name="diff")
@click.option("--path", type=click.Path(), default=None, help="Skills repo root (default: auto-detect)")
@click.help_option("-h", "--help")
def diff_agents(path):
    """Show what has changed since last sync.

    Compares current agent files against the lockfile to detect new, modified, or deleted agents.

    \b
        mcpm agents diff
    """
    start_path = Path(path).resolve() if path else None
    repo_path = find_skills_repo(start_path)
    if not repo_path:
        console.print("[yellow]No skills repository found.[/]")
        return

    config_manager = SkillsConfigManager(project_root=repo_path)
    lockfile = config_manager.load_lockfile()

    agents = discover_agents(repo_path)
    current_names = {a.name for a in agents}

    if lockfile is None or not hasattr(lockfile, "agents"):
        console.print("[yellow]No lockfile found. All agents are new.[/]\n")
        for agent in agents:
            console.print(f"  [green]+ {agent.name}[/]")
        return

    locked_names = set(lockfile.agents.keys()) if lockfile.agents else set()
    locked_entries = lockfile.agents or {}

    new_agents = current_names - locked_names
    removed_agents = locked_names - current_names
    common_agents = current_names & locked_names

    modified_agents = set()
    for agent in agents:
        if agent.name in common_agents:
            current_hash = compute_agent_hash(agent)
            locked_hash = locked_entries[agent.name].hash
            if current_hash != locked_hash:
                modified_agents.add(agent.name)

    unchanged = common_agents - modified_agents

    if not new_agents and not removed_agents and not modified_agents:
        console.print("[green]No changes since last sync.[/]")
        return

    console.print()
    for name in sorted(new_agents):
        console.print(f"  [green]+ {name}[/] (new)")
    for name in sorted(modified_agents):
        console.print(f"  [yellow]~ {name}[/] (modified)")
    for name in sorted(removed_agents):
        console.print(f"  [red]- {name}[/] (removed)")
    if unchanged:
        console.print(f"  [dim]{len(unchanged)} unchanged[/]")
    console.print()
