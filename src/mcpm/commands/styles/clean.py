"""Clean all mcpm-managed style files from clients."""

from pathlib import Path

from rich.console import Console

from mcpm.skills.config import SkillsConfigManager
from mcpm.skills.parser import find_skills_repo
from mcpm.styles.transpiler import get_all_style_transpilers
from mcpm.utils.rich_click_config import click

console = Console()


@click.command(name="clean")
@click.option("--path", type=click.Path(), default=None, help="Skills repo root (default: auto-detect)")
@click.help_option("-h", "--help")
def clean_styles(path):
    """Remove all mcpm-managed output style files from all clients.

    \b
        mcpm styles clean
    """
    start_path = Path(path).resolve() if path else None
    repo_path = find_skills_repo(start_path)
    if not repo_path:
        console.print("[red]Error: No skills repository found. Run 'mcpm skills init' first.[/]")
        return

    config_manager = SkillsConfigManager(project_root=repo_path)
    lockfile = config_manager.load_lockfile()

    # Gather all managed style names from lockfile
    managed_names = []
    if lockfile:
        managed_names = list(lockfile.styles.keys())

    transpilers = get_all_style_transpilers()
    total_removed = 0

    for client_key, transpiler in transpilers.items():
        try:
            removed = transpiler.clean(repo_path, managed_styles=managed_names)
            if removed:
                total_removed += len(removed)
                for p in removed:
                    console.print(f"  [dim]Removed: {p}[/]")
        except Exception as e:
            console.print(f"  [red]Error cleaning {client_key}: {e}[/]")

    # Clear lockfile style data
    if lockfile:
        lockfile.styles = {}
        lockfile.active_styles = {}
        config_manager.save_lockfile(lockfile)

    if total_removed > 0:
        console.print(f"\n[green]Cleaned {total_removed} style file(s) from clients.[/]")
    else:
        console.print("[yellow]No style files found to clean.[/]")
