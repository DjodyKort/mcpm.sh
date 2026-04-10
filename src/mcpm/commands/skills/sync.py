"""Skills sync command -- transpile to all installed clients."""

from pathlib import Path

from rich.console import Console
from rich.table import Table

from mcpm.skills.config import SkillsConfigManager
from mcpm.skills.parser import discover_skills, find_skills_repo
from mcpm.skills.transpiler import sync_skills as do_sync
from mcpm.utils.rich_click_config import click

console = Console()


@click.command(name="sync")
@click.option("--client", type=str, default=None, help="Sync to a specific client only")
@click.option("--dry-run", is_flag=True, help="Show what would change without writing files")
@click.option("--path", type=click.Path(), default=None, help="Skills repo root (default: auto-detect)")
@click.help_option("-h", "--help")
def sync_skills(client, dry_run, path):
    """Transpile canonical skills to all installed client formats.

    Reads SKILL.md files from the skills repository, renders them to each client's
    native instruction format, and writes the output files. Updates the lockfile.

    Append-mode clients (Zed, AGENTS.md) get all skills concatenated into a single
    managed block. Per-file clients get one output file per skill.

    \b
        mcpm skills sync
        mcpm skills sync --client claude-code
        mcpm skills sync --dry-run
    """
    # Find skills repo
    start_path = Path(path).resolve() if path else None
    repo_path = find_skills_repo(start_path)
    if not repo_path:
        console.print("[red]Error: No skills repository found. Run 'mcpm skills init' first.[/]")
        return

    # Discover skills
    skills = discover_skills(repo_path)
    if not skills:
        console.print("[yellow]No skills found in repository.[/]")
        return

    # Determine target clients
    client_keys = [client] if client else None

    if dry_run:
        console.print("[cyan]Dry run -- no files will be written.[/]\n")

    # Run sync (handles both per-file and append-mode transpilers)
    lockfile = do_sync(skills, repo_path, client_keys=client_keys, dry_run=dry_run)

    # Save lockfile
    if not dry_run:
        config_manager = SkillsConfigManager(project_root=repo_path)
        config_manager.save_lockfile(lockfile)

    # Report results
    all_entries = {**lockfile.skills, **lockfile.rules}
    total_skills = len(all_entries)
    total_clients = len(set(c for e in all_entries.values() for c in e.clients_synced))

    prefix = "[cyan](dry run)[/] " if dry_run else ""
    console.print(f"\n{prefix}[green]Synced {total_skills} skill(s) to {total_clients} client(s).[/]\n")

    # Show details table
    table = Table(show_header=True, header_style="bold")
    table.add_column("Skill", style="cyan")
    table.add_column("Type")
    table.add_column("Clients synced", overflow="fold")
    table.add_column("Warnings", overflow="fold")

    for name, entry in all_entries.items():
        skill_type = "rule" if name in lockfile.rules else "skill"
        clients_str = ", ".join(entry.clients_synced) if entry.clients_synced else "[dim]none[/]"
        warnings_str = "; ".join(entry.warnings) if entry.warnings else "[dim]--[/]"
        table.add_row(name, skill_type, clients_str, warnings_str)

    console.print(table)

    # Check if append-mode transpilers produced output
    has_agents_md = any("agents-md" in e.clients_synced for e in all_entries.values())
    has_zed = any("zed" in e.clients_synced for e in all_entries.values())
    if has_agents_md:
        console.print(f"\n{prefix}Updated AGENTS.md with <available_skills> block.")
    if has_zed:
        console.print(f"{prefix}Updated .rules with concatenated skills for Zed.")
