"""Styles diff command -- show changes since last sync."""

from pathlib import Path

from rich.console import Console

from mcpm.skills.config import SkillsConfigManager
from mcpm.skills.parser import find_skills_repo
from mcpm.styles.parser import discover_styles
from mcpm.styles.transpiler import compute_style_hash
from mcpm.utils.rich_click_config import click

console = Console()


@click.command(name="diff")
@click.option("--path", type=click.Path(), default=None, help="Skills repo root (default: auto-detect)")
@click.help_option("-h", "--help")
def diff_styles(path):
    """Show what has changed since last sync.

    Compares current style files against the lockfile to detect new, modified, or deleted styles.

    \b
        mcpm styles diff
    """
    start_path = Path(path).resolve() if path else None
    repo_path = find_skills_repo(start_path)
    if not repo_path:
        console.print("[yellow]No skills repository found.[/]")
        return

    config_manager = SkillsConfigManager(project_root=repo_path)
    lockfile = config_manager.load_lockfile()

    styles = discover_styles(repo_path)
    current_names = {s.name for s in styles}

    if lockfile is None:
        console.print("[yellow]No lockfile found. All styles are new.[/]\n")
        for style in styles:
            console.print(f"  [green]+ {style.name}[/]")
        return

    locked_names = set(lockfile.styles.keys())
    locked_entries = lockfile.styles

    new_styles = current_names - locked_names
    removed_styles = locked_names - current_names
    common_styles = current_names & locked_names

    modified_styles = set()
    for style in styles:
        if style.name in common_styles:
            current_hash = compute_style_hash(style)
            locked_hash = locked_entries[style.name].hash
            if current_hash != locked_hash:
                modified_styles.add(style.name)

    unchanged = common_styles - modified_styles

    if not new_styles and not removed_styles and not modified_styles:
        console.print("[green]No changes since last sync.[/]")
        return

    console.print()
    for name in sorted(new_styles):
        console.print(f"  [green]+ {name}[/] (new)")
    for name in sorted(modified_styles):
        console.print(f"  [yellow]~ {name}[/] (modified)")
    for name in sorted(removed_styles):
        console.print(f"  [red]- {name}[/] (removed)")
    if unchanged:
        console.print(f"  [dim]{len(unchanged)} unchanged[/]")
    console.print()
