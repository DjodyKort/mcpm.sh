"""Skills resolve command -- triage collisions outside of a sync run."""

from pathlib import Path

from rich.console import Console

from mcpm.skills.collisions import detect_collisions, resolve_collisions, resolve_mode
from mcpm.skills.parser import discover_skills, find_skills_repo
from mcpm.skills.transpiler import APPEND_MODE_TRANSPILERS, PROJECT_ONLY_TRANSPILERS, get_all_transpilers
from mcpm.utils.rich_click_config import click

console = Console()


@click.command(name="resolve")
@click.option("--client", type=str, default=None, help="Resolve for a specific client only")
@click.option("--dry-run", is_flag=True, help="Show what would happen without moving any file")
@click.option("--path", type=click.Path(), default=None, help="Skills repo root (default: auto-detect)")
@click.option("--global", "global_mode", is_flag=True, help="Operate on user-level paths (~/) instead of project-level")
@click.option(
    "--migrate/--no-migrate",
    "migrate",
    default=None,
    help="--migrate auto-replaces colliding files (with backup), --no-migrate warns only. "
    "Default: prompt in a terminal, warn in non-interactive runs.",
)
@click.help_option("-h", "--help")
def resolve_skills(client, dry_run, path, global_mode, migrate):
    """Triage collisions between synced skills and pre-existing files.

    A collision is a file at a path the client also reads as the same skill name
    -- e.g. ~/.claude/commands/foo.md shadowing ~/.claude/skills/foo/SKILL.md.
    This command finds them all and offers to replace, keep, or diff each one.
    Replaced files are backed up under <root>/.mcpm-backups/.

    \b
        mcpm skills resolve --global
        mcpm skills resolve --global --dry-run
        mcpm skills resolve --global --migrate         # non-interactive replace-all
        mcpm skills resolve --client claude-code
    """
    start_path = Path(path).resolve() if path else None
    repo_path = find_skills_repo(start_path)
    if not repo_path:
        console.print("[red]Error: No skills repository found. Run 'mcpm skills init' first.[/]")
        return

    skills = discover_skills(repo_path)
    if not skills:
        console.print("[yellow]No skills found in repository.[/]")
        return

    transpilers = get_all_transpilers()
    if client:
        transpilers = {k: v for k, v in transpilers.items() if k == client}
    if global_mode:
        transpilers = {k: v for k, v in transpilers.items() if k not in PROJECT_ONLY_TRANSPILERS}
    # Append-mode clients overwrite a single shared file; collision detection
    # only makes sense for per-file transpilers.
    transpilers = {k: v for k, v in transpilers.items() if k not in APPEND_MODE_TRANSPILERS}

    output_root = Path.home() if global_mode else repo_path
    collisions = detect_collisions(skills, transpilers, output_root)

    if not collisions:
        console.print("[green]No collisions found.[/]")
        return

    console.print(f"[yellow]Found {len(collisions)} collision(s).[/]")
    mode = resolve_mode(migrate)
    summary = resolve_collisions(collisions, output_root, mode, console=console, dry_run=dry_run)

    replaced = len(summary.replaced)
    kept = len(summary.kept)
    if replaced:
        console.print(f"\n[green]Replaced {replaced} file(s)[/] (backed up under {output_root / '.mcpm-backups'}).")
    if kept:
        console.print(f"[yellow]Left {kept} file(s) in place.[/]")
