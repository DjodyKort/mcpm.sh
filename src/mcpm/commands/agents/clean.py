"""Agents clean command -- remove all mcpm-managed agent files."""

from pathlib import Path

from rich.console import Console

from mcpm.skills.agents.transpiler import get_all_agent_transpilers
from mcpm.skills.config import SkillsConfigManager
from mcpm.utils.rich_click_config import click

console = Console()


@click.command(name="clean")
@click.option("--client", type=str, default=None, help="Clean a specific client only")
@click.option("--path", type=click.Path(), default=None, help="Project root (default: auto-detect)")
@click.option("--global", "global_mode", is_flag=True, help="Clean user-level paths (~/) instead of project-level")
@click.help_option("-h", "--help")
def clean_agents(client, path, global_mode):
    """Remove all mcpm-managed agent files from clients.

    Uses the lockfile to determine which files were managed by mcpm.

    \b
        mcpm agents clean
        mcpm agents clean --global
        mcpm agents clean --client claude-code
    """
    if global_mode:
        from mcpm.utils.platform import get_config_directory

        project_root = get_config_directory()
    else:
        project_root = Path(path).resolve() if path else Path.cwd()
    config_manager = SkillsConfigManager(project_root=project_root)
    lockfile = config_manager.load_lockfile()

    if lockfile is None:
        console.print("[yellow]No lockfile found. Nothing to clean.[/]")
        return

    managed_names = list(lockfile.agents.keys()) if hasattr(lockfile, "agents") and lockfile.agents else []
    if not managed_names:
        console.print("[yellow]No managed agents in lockfile.[/]")
        return

    transpilers = get_all_agent_transpilers()
    if client:
        transpilers = {k: v for k, v in transpilers.items() if k == client}

    clean_root = Path.home() if global_mode else project_root

    total_removed = 0
    for client_key, transpiler in transpilers.items():
        try:
            removed = transpiler.clean(clean_root, managed_skills=managed_names)
            for p in removed:
                try:
                    display = p.relative_to(project_root)
                except ValueError:
                    display = p
                console.print(f"  [red]Removed[/] {display}")
            total_removed += len(removed)
        except Exception as e:
            console.print(f"  [dim]Skipped {client_key}: {e}[/]")

    if total_removed:
        console.print(f"\n[green]Cleaned {total_removed} file(s).[/]")
    else:
        console.print("[yellow]No managed files found to clean.[/]")
