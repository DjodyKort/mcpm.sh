"""Skills bundle command -- create portable packages."""

from pathlib import Path

from rich.console import Console

from mcpm.skills.bundle import create_bundle, extract_bundle
from mcpm.skills.parser import find_skills_repo
from mcpm.utils.rich_click_config import click

console = Console()


@click.command(name="bundle")
@click.option("--output", type=click.Path(), default=None, help="Output zip path")
@click.option("--path", type=click.Path(), default=None, help="Skills repo root (default: auto-detect)")
@click.option("--skills", type=str, default=None, help="Comma-separated skill names to include (default: all)")
@click.help_option("-h", "--help")
def bundle_skills(output, path, skills):
    """Create a portable zip bundle of skills.

    Bundles skills, rules, server configs, and manifest into a single
    file for offline sharing or air-gapped environments.

    \b
        mcpm skills bundle
        mcpm skills bundle --output my-skills.zip
        mcpm skills bundle --skills code-review,terraform
    """
    start_path = Path(path).resolve() if path else None
    repo_path = find_skills_repo(start_path)
    if not repo_path:
        console.print("[red]Error: No skills repository found.[/]")
        return

    output_path = Path(output).resolve() if output else None
    skill_names = [s.strip() for s in skills.split(",")] if skills else None

    try:
        result_path = create_bundle(repo_path, output_path=output_path, skill_names=skill_names)
        size_kb = result_path.stat().st_size / 1024
        console.print(f"\n[green]Bundle created: {result_path} ({size_kb:.1f} KB)[/]")
    except ValueError as e:
        console.print(f"[red]Error: {e}[/]")


@click.command(name="unbundle")
@click.argument("bundle_path", type=click.Path(exists=True))
@click.option("--path", type=click.Path(), default=".", help="Target directory (default: current directory)")
@click.help_option("-h", "--help")
def unbundle_skills(bundle_path, path):
    """Extract a skills bundle into a repository.

    \b
        mcpm skills unbundle my-skills.zip
        mcpm skills unbundle my-skills.zip --path ./target
    """
    target = Path(path).resolve()

    try:
        names = extract_bundle(Path(bundle_path), target)
        console.print(f"\n[green]Extracted {len(names)} skill(s): {', '.join(names)}[/]")
        console.print("Run 'mcpm skills sync' to transpile to clients.\n")
    except ValueError as e:
        console.print(f"[red]Error: {e}[/]")
