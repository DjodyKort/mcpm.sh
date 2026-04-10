"""Skills lint command -- validate and check best practices."""

from pathlib import Path

from rich.console import Console

from mcpm.skills.lint import lint_skills
from mcpm.skills.parser import discover_skills, find_skills_repo
from mcpm.utils.rich_click_config import click

console = Console()


@click.command(name="lint")
@click.option("--path", type=click.Path(), default=None, help="Skills repo root (default: auto-detect)")
@click.help_option("-h", "--help")
def lint_skills_cmd(path):
    """Validate skills and check for best-practice issues.

    Checks frontmatter validity, per-client constraints (Windsurf char limits),
    description quality, and cross-skill conflicts.

    \b
        mcpm skills lint
    """
    start_path = Path(path).resolve() if path else None
    repo_path = find_skills_repo(start_path)
    if not repo_path:
        console.print("[yellow]No skills repository found.[/]")
        return

    skills = discover_skills(repo_path)
    if not skills:
        console.print("[yellow]No skills found to lint.[/]")
        return

    result = lint_skills(skills)

    if not result.messages:
        console.print(f"[green]All {len(skills)} skill(s) passed lint checks.[/]")
        return

    for msg in result.messages:
        if msg.level == "error":
            icon = "[red]E[/]"
        elif msg.level == "warning":
            icon = "[yellow]W[/]"
        else:
            icon = "[dim]I[/]"
        console.print(f"  {icon} [cyan]{msg.skill_name}[/]: {msg.message}")

    console.print()
    errors = len(result.errors)
    warnings = len(result.warnings)
    infos = len(result.messages) - errors - warnings

    parts = []
    if errors:
        parts.append(f"[red]{errors} error(s)[/]")
    if warnings:
        parts.append(f"[yellow]{warnings} warning(s)[/]")
    if infos:
        parts.append(f"[dim]{infos} info(s)[/]")
    console.print("  " + ", ".join(parts))

    if result.has_errors:
        raise SystemExit(1)
