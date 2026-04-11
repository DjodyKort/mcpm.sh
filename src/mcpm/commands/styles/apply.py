"""Apply an output style to Tier 2 (non-native) clients."""

from pathlib import Path

from rich.console import Console
from rich.table import Table

from mcpm.skills.config import SkillsConfigManager
from mcpm.skills.parser import find_skills_repo
from mcpm.styles.parser import discover_styles
from mcpm.styles.transpiler import apply_style, get_tier1_transpilers
from mcpm.utils.rich_click_config import click

console = Console()


@click.command(name="apply")
@click.argument("name")
@click.option("--client", type=str, default=None, help="Apply to a specific client only")
@click.option("--dry-run", is_flag=True, help="Show what would change without writing files")
@click.option("--path", type=click.Path(), default=None, help="Skills repo root (default: auto-detect)")
@click.help_option("-h", "--help")
def apply_style_cmd(name, client, dry_run, path):
    """Apply an output style to non-native clients as an always-on rule.

    Only one style can be active per client. Applying a new style replaces
    the previous one. Use 'mcpm styles remove' to deactivate.

    \b
        mcpm styles apply concise-engineer
        mcpm styles apply verbose-teacher --client cursor
        mcpm styles apply concise-engineer --dry-run
    """
    start_path = Path(path).resolve() if path else None
    repo_path = find_skills_repo(start_path)
    if not repo_path:
        console.print("[red]Error: No skills repository found. Run 'mcpm skills init' first.[/]")
        return

    found_styles = discover_styles(repo_path)
    target_style = next((s for s in found_styles if s.name == name), None)
    if not target_style:
        available = ", ".join(s.name for s in found_styles) if found_styles else "none"
        console.print(f"[red]Style '{name}' not found. Available: {available}[/]")
        return

    # Warn if targeting a Tier 1 client
    tier1_keys = set(get_tier1_transpilers().keys())
    if client and client in tier1_keys:
        console.print(
            f"[yellow]Note: '{client}' supports native style toggling. "
            f"Use 'mcpm styles sync' instead and toggle in the client UI.[/]\n"
        )

    client_keys = [client] if client else None

    if dry_run:
        console.print("[cyan]Dry run -- no files will be written.[/]\n")

    config_manager = SkillsConfigManager(project_root=repo_path)
    lockfile = config_manager.load_lockfile()

    # Report what's being replaced
    if lockfile and lockfile.active_styles:
        replaced = {k: v for k, v in lockfile.active_styles.items() if v != name}
        if client_keys:
            replaced = {k: v for k, v in replaced.items() if k in client_keys}
        if replaced:
            for ck, old_name in replaced.items():
                console.print(f"[dim]Replacing active style '{old_name}' on {ck}[/]")

    lockfile = apply_style(target_style, repo_path, client_keys=client_keys, dry_run=dry_run, lockfile=lockfile)

    if not dry_run:
        config_manager.save_lockfile(lockfile)

    prefix = "[cyan](dry run)[/] " if dry_run else ""
    active_count = sum(1 for v in lockfile.active_styles.values() if v == name)
    console.print(f"\n{prefix}[green]Applied style '{name}' to {active_count} client(s).[/]\n")

    table = Table(show_header=True, header_style="bold")
    table.add_column("Client", style="cyan")
    table.add_column("Active style")

    for ck, sn in sorted(lockfile.active_styles.items()):
        style_marker = f"[green]{sn}[/]" if sn == name else sn
        table.add_row(ck, style_marker)

    console.print(table)
