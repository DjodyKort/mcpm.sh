"""Agents sync command -- transpile to all installed clients."""

from pathlib import Path

from rich.console import Console
from rich.table import Table

from mcpm.skills.agents.parser import discover_agents
from mcpm.skills.agents.transpiler import sync_agents
from mcpm.skills.config import SkillsConfigManager
from mcpm.skills.parser import find_skills_repo
from mcpm.utils.rich_click_config import click

console = Console()


@click.command(name="sync")
@click.option("--client", type=str, default=None, help="Sync to a specific client only")
@click.option("--dry-run", is_flag=True, help="Show what would change without writing files")
@click.option("--path", type=click.Path(), default=None, help="Skills repo root (default: auto-detect)")
@click.help_option("-h", "--help")
def sync_agents_cmd(client, dry_run, path):
    """Transpile canonical agents to all installed client formats.

    Reads AGENT.md files from the agents/ directory and renders them to each
    client's native agent format.

    \b
        mcpm agents sync
        mcpm agents sync --client claude-code
        mcpm agents sync --dry-run
    """
    start_path = Path(path).resolve() if path else None
    repo_path = find_skills_repo(start_path)
    if not repo_path:
        console.print("[red]Error: No skills repository found. Run 'mcpm skills init' first.[/]")
        return

    found_agents = discover_agents(repo_path)
    if not found_agents:
        console.print("[yellow]No agents found in repository.[/]")
        return

    client_keys = [client] if client else None

    if dry_run:
        console.print("[cyan]Dry run -- no files will be written.[/]\n")

    # Load existing lockfile to extend
    config_manager = SkillsConfigManager(project_root=repo_path)
    lockfile = config_manager.load_lockfile()

    lockfile = sync_agents(found_agents, repo_path, client_keys=client_keys, dry_run=dry_run, lockfile=lockfile)

    if not dry_run:
        config_manager.save_lockfile(lockfile)

    total_agents = len(lockfile.agents)
    total_clients = len(set(c for e in lockfile.agents.values() for c in e.clients_synced))

    prefix = "[cyan](dry run)[/] " if dry_run else ""
    console.print(f"\n{prefix}[green]Synced {total_agents} agent(s) to {total_clients} client(s).[/]\n")

    table = Table(show_header=True, header_style="bold")
    table.add_column("Agent", style="cyan")
    table.add_column("Model")
    table.add_column("Clients synced", overflow="fold")
    table.add_column("Warnings", overflow="fold")

    for name, entry in lockfile.agents.items():
        agent = next((a for a in found_agents if a.name == name), None)
        model = agent.frontmatter.model or "[dim]default[/]" if agent else "--"
        clients_str = ", ".join(entry.clients_synced) if entry.clients_synced else "[dim]none[/]"
        warnings_str = "; ".join(entry.warnings) if entry.warnings else "[dim]--[/]"
        table.add_row(name, model, clients_str, warnings_str)

    console.print(table)
