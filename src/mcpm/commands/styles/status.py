"""Show output style sync status per client."""

from pathlib import Path

from rich.console import Console
from rich.table import Table

from mcpm.skills.config import SkillsConfigManager
from mcpm.skills.parser import find_skills_repo
from mcpm.styles.transpiler import get_tier1_transpilers, get_tier2_transpilers
from mcpm.utils.rich_click_config import click

console = Console()


@click.command(name="status")
@click.option("--path", type=click.Path(), default=None, help="Skills repo root (default: auto-detect)")
@click.help_option("-h", "--help")
def status_styles(path):
    """Show per-client output style status.

    Tier 1 (native toggle): shows all synced styles.
    Tier 2 (apply/remove): shows which style is currently active.

    \b
        mcpm styles status
    """
    start_path = Path(path).resolve() if path else None
    repo_path = find_skills_repo(start_path)
    if not repo_path:
        console.print("[red]Error: No skills repository found. Run 'mcpm skills init' first.[/]")
        return

    config_manager = SkillsConfigManager(project_root=repo_path)
    lockfile = config_manager.load_lockfile()

    if not lockfile:
        console.print("[yellow]No lockfile found. Run 'mcpm styles sync' first.[/]")
        return

    # Tier 1 status
    tier1 = get_tier1_transpilers()
    if tier1:
        console.print("[bold]Tier 1 -- Native toggle (all styles available):[/]\n")
        table = Table(show_header=True, header_style="bold")
        table.add_column("Client", style="cyan")
        table.add_column("Styles synced", overflow="fold")

        for ck, transpiler in tier1.items():
            synced = [name for name, entry in lockfile.styles.items() if ck in entry.clients_synced]
            synced_str = ", ".join(synced) if synced else "[dim]none[/]"
            table.add_row(transpiler.display_name, synced_str)

        console.print(table)

    # Tier 2 status
    tier2 = get_tier2_transpilers()
    if tier2:
        console.print("\n[bold]Tier 2 -- Apply/Remove (one active style):[/]\n")
        table = Table(show_header=True, header_style="bold")
        table.add_column("Client", style="cyan")
        table.add_column("Active style")

        for ck, transpiler in tier2.items():
            active = lockfile.active_styles.get(ck)
            active_str = f"[green]{active}[/]" if active else "[dim]none[/]"
            table.add_row(transpiler.display_name, active_str)

        console.print(table)
