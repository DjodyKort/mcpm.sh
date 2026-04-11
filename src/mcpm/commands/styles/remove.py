"""Remove the active output style from Tier 2 clients."""

from pathlib import Path

from rich.console import Console

from mcpm.skills.config import SkillsConfigManager
from mcpm.skills.parser import find_skills_repo
from mcpm.styles.transpiler import remove_style
from mcpm.utils.rich_click_config import click

console = Console()


@click.command(name="remove")
@click.option("--client", type=str, default=None, help="Remove from a specific client only")
@click.option("--dry-run", is_flag=True, help="Show what would change without removing files")
@click.option("--path", type=click.Path(), default=None, help="Skills repo root (default: auto-detect)")
@click.help_option("-h", "--help")
def remove_style_cmd(client, dry_run, path):
    """Remove the active output style from non-native clients.

    Deletes the injected style rule files. Does not affect Tier 1 clients
    (Claude Code, Roo Code) -- manage those through the client's own UI.

    \b
        mcpm styles remove
        mcpm styles remove --client cursor
    """
    start_path = Path(path).resolve() if path else None
    repo_path = find_skills_repo(start_path)
    if not repo_path:
        console.print("[red]Error: No skills repository found. Run 'mcpm skills init' first.[/]")
        return

    config_manager = SkillsConfigManager(project_root=repo_path)
    lockfile = config_manager.load_lockfile()

    if not lockfile or not lockfile.active_styles:
        console.print("[yellow]No active styles to remove.[/]")
        return

    client_keys = [client] if client else None

    # Show what will be removed
    targets = lockfile.active_styles
    if client_keys:
        targets = {k: v for k, v in targets.items() if k in client_keys}

    if not targets:
        console.print(f"[yellow]No active style on client '{client}'.[/]")
        return

    if dry_run:
        console.print("[cyan]Dry run -- no files will be removed.[/]\n")

    for ck, sn in targets.items():
        prefix = "[cyan](dry run)[/] " if dry_run else ""
        console.print(f"{prefix}Removing style '{sn}' from {ck}")

    lockfile = remove_style(repo_path, client_keys=client_keys, dry_run=dry_run, lockfile=lockfile)

    if not dry_run:
        config_manager.save_lockfile(lockfile)

    console.print(f"\n[green]Done. Removed active style from {len(targets)} client(s).[/]")
