"""Skills clean command -- remove all mcpm-managed skill files."""

from pathlib import Path

from rich.console import Console

from mcpm.skills.config import SkillsConfigManager
from mcpm.skills.transpiler import get_all_transpilers
from mcpm.utils.rich_click_config import click

console = Console()


@click.command(name="clean")
@click.option("--client", type=str, default=None, help="Clean a specific client only")
@click.option("--path", type=click.Path(), default=None, help="Project root (default: auto-detect)")
@click.help_option("-h", "--help")
def clean_skills(client, path):
    """Remove all mcpm-managed skill files from clients.

    Uses the lockfile to determine which files were managed by mcpm.
    Only removes files that mcpm created.

    \b
        mcpm skills clean
        mcpm skills clean --client cursor
    """
    project_root = Path(path).resolve() if path else Path.cwd()
    config_manager = SkillsConfigManager(project_root=project_root)
    lockfile = config_manager.load_lockfile()

    if lockfile is None:
        console.print("[yellow]No lockfile found. Nothing to clean.[/]")
        return

    managed_names = list(lockfile.skills.keys()) + list(lockfile.rules.keys())
    if not managed_names:
        console.print("[yellow]No managed skills in lockfile.[/]")
        return

    transpilers = get_all_transpilers()
    if client:
        transpilers = {k: v for k, v in transpilers.items() if k == client}

    total_removed = 0
    for client_key, transpiler in transpilers.items():
        try:
            removed = transpiler.clean(project_root, managed_skills=managed_names)
            for p in removed:
                try:
                    display = p.relative_to(project_root)
                except ValueError:
                    display = p  # Global path (e.g., Claude Desktop skills dir)
                console.print(f"  [red]Removed[/] {display}")
            total_removed += len(removed)
        except Exception as e:
            console.print(f"  [dim]Skipped {client_key}: {e}[/]")

    # Remove lockfile
    if not client and config_manager.lockfile_path.exists():
        config_manager.lockfile_path.unlink()
        console.print(f"  [red]Removed[/] {config_manager.lockfile_path.name}")
        total_removed += 1

    if total_removed:
        console.print(f"\n[green]Cleaned {total_removed} file(s).[/]")
    else:
        console.print("[yellow]No managed files found to clean.[/]")
