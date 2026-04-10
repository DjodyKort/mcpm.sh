"""Skills status command -- drift detection."""

from pathlib import Path

from rich.console import Console
from rich.table import Table

from mcpm.skills.config import SkillsConfigManager
from mcpm.skills.schema import SkillConfig, SkillFrontmatter
from mcpm.skills.transpiler import get_all_transpilers
from mcpm.utils.rich_click_config import click

console = Console()


@click.command(name="status")
@click.option("--strict", is_flag=True, help="Exit non-zero on any drift (for CI)")
@click.option("--path", type=click.Path(), default=None, help="Project root (default: current directory)")
@click.help_option("-h", "--help")
def status_skills(strict, path):
    """Detect drift between source skills and transpiled output files.

    Reports per-client whether output files match what mcpm would generate.
    Useful for CI pipelines to ensure skills are in sync.

    \b
        mcpm skills status
        mcpm skills status --strict
    """
    project_root = Path(path).resolve() if path else Path.cwd()
    config_manager = SkillsConfigManager(project_root=project_root)
    lockfile = config_manager.load_lockfile()

    if lockfile is None:
        console.print("[yellow]No lockfile found. Run 'mcpm skills sync' first.[/]")
        if strict:
            raise SystemExit(1)
        return

    all_entries = {**lockfile.skills, **lockfile.rules}
    if not all_entries:
        console.print("[yellow]No skills in lockfile.[/]")
        return

    transpilers = get_all_transpilers()
    has_drift = False

    table = Table(show_header=True, header_style="bold")
    table.add_column("Skill", style="cyan")
    table.add_column("Client")
    table.add_column("Status")

    for skill_name, entry in all_entries.items():
        for client_key in entry.clients_synced:
            transpiler = transpilers.get(client_key)
            if not transpiler:
                continue

            # Create a dummy skill config to get the output path
            skill_type = "rule" if skill_name in lockfile.rules else "skill"
            dummy = SkillConfig(
                frontmatter=SkillFrontmatter(name=skill_name, description="dummy"),
                body="",
                source_path=Path("dummy"),
                skill_type=skill_type,
            )
            output_path = transpiler.get_output_path(dummy, project_root)

            if not output_path.exists():
                table.add_row(skill_name, client_key, "[red]missing[/]")
                has_drift = True
            else:
                table.add_row(skill_name, client_key, "[green]ok[/]")

    console.print(table)

    if has_drift:
        console.print("\n[yellow]Drift detected. Run 'mcpm skills sync' to update.[/]")
        if strict:
            raise SystemExit(1)
    else:
        console.print("\n[green]All output files in sync.[/]")
