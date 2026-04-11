"""Styles sync command -- transpile to Tier 1 (native toggle) clients."""

from pathlib import Path

from rich.console import Console
from rich.table import Table

from mcpm.skills.config import SkillsConfigManager
from mcpm.skills.parser import find_skills_repo
from mcpm.styles.parser import discover_styles
from mcpm.styles.transpiler import sync_styles
from mcpm.utils.rich_click_config import click

console = Console()


@click.command(name="sync")
@click.option("--client", type=str, default=None, help="Sync to a specific client only")
@click.option("--dry-run", is_flag=True, help="Show what would change without writing files")
@click.option("--path", type=click.Path(), default=None, help="Skills repo root (default: auto-detect)")
@click.help_option("-h", "--help")
def sync_styles_cmd(client, dry_run, path):
    """Transpile output styles to native toggle clients (Claude Code, Roo Code).

    Writes all styles so the user can toggle between them in each client's UI.
    For other clients, use 'mcpm styles apply <name>' instead.

    \b
        mcpm styles sync
        mcpm styles sync --client claude-code
        mcpm styles sync --dry-run
    """
    start_path = Path(path).resolve() if path else None
    repo_path = find_skills_repo(start_path)
    if not repo_path:
        console.print("[red]Error: No skills repository found. Run 'mcpm skills init' first.[/]")
        return

    found_styles = discover_styles(repo_path)
    if not found_styles:
        console.print("[yellow]No styles found in repository. Run 'mcpm styles add <name>' first.[/]")
        return

    client_keys = [client] if client else None

    if dry_run:
        console.print("[cyan]Dry run -- no files will be written.[/]\n")

    config_manager = SkillsConfigManager(project_root=repo_path)
    lockfile = config_manager.load_lockfile()

    lockfile = sync_styles(found_styles, repo_path, client_keys=client_keys, dry_run=dry_run, lockfile=lockfile)

    if not dry_run:
        config_manager.save_lockfile(lockfile)

    total_styles = len(found_styles)
    synced_clients = set()
    for entry in lockfile.styles.values():
        synced_clients.update(entry.clients_synced)

    prefix = "[cyan](dry run)[/] " if dry_run else ""
    console.print(
        f"\n{prefix}[green]Synced {total_styles} style(s) to {len(synced_clients)} native client(s).[/]\n"
    )

    table = Table(show_header=True, header_style="bold")
    table.add_column("Style", style="cyan")
    table.add_column("Description", overflow="fold")
    table.add_column("Clients synced", overflow="fold")
    table.add_column("Warnings", overflow="fold")

    for style in found_styles:
        entry = lockfile.styles.get(style.name)
        if entry:
            clients_str = ", ".join(entry.clients_synced) if entry.clients_synced else "[dim]none[/]"
            warnings_str = "; ".join(entry.warnings) if entry.warnings else "[dim]--[/]"
        else:
            clients_str = "[dim]none[/]"
            warnings_str = "[dim]--[/]"
        desc = style.frontmatter.description[:60] + "..." if len(style.frontmatter.description) > 60 else style.frontmatter.description
        table.add_row(style.name, desc, clients_str, warnings_str)

    console.print(table)
    console.print(
        "\n[dim]These clients support native toggling. For other clients, use 'mcpm styles apply <name>'.[/]"
    )
