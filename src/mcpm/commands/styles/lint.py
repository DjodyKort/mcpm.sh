"""Styles lint command -- validate and check best practices."""

from pathlib import Path

from rich.console import Console

from mcpm.skills.parser import find_skills_repo
from mcpm.styles.lint import lint_styles
from mcpm.styles.parser import discover_styles
from mcpm.utils.rich_click_config import click

console = Console()


@click.command(name="lint")
@click.option("--path", type=click.Path(), default=None, help="Skills repo root (default: auto-detect)")
@click.help_option("-h", "--help")
def lint_styles_cmd(path):
    """Validate output styles and check for best-practice issues.

    Checks name/directory match, description quality, body length, and
    per-client constraints (Windsurf char limits).

    \b
        mcpm styles lint
    """
    start_path = Path(path).resolve() if path else None
    repo_path = find_skills_repo(start_path)
    if not repo_path:
        console.print("[yellow]No skills repository found.[/]")
        return

    styles = discover_styles(repo_path)
    if not styles:
        console.print("[yellow]No styles found to lint.[/]")
        return

    result = lint_styles(styles)

    if not result.messages:
        console.print(f"[green]All {len(styles)} style(s) passed lint checks.[/]")
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
