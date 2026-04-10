"""Skills install command -- install from remote GitHub repositories."""

import shutil
from pathlib import Path

from rich.console import Console

from mcpm.skills.audit import audit_skills
from mcpm.skills.taps import TapManager
from mcpm.utils.rich_click_config import click

console = Console()


@click.command(name="install")
@click.argument("spec")
@click.option("--path", type=click.Path(), default=".", help="Target skills repo (default: current directory)")
@click.option("--no-audit", is_flag=True, help="Skip security audit")
@click.help_option("-h", "--help")
def install_skill(spec, path, no_audit):
    """Install skills from a remote GitHub repository.

    SPEC format: @user/repo[/skill-name][@version]

    \b
        mcpm skills install @anthropics/skills
        mcpm skills install @anthropics/skills/code-review
        mcpm skills install @anthropics/skills/code-review@1.2.0
    """
    tap_manager = TapManager()
    target_root = Path(path).resolve()

    console.print(f"[cyan]Resolving {spec}...[/]")

    # Resolve skills from remote
    skills = tap_manager.resolve_skills(spec)
    if not skills:
        console.print(f"[red]Error: No skills found for '{spec}'[/]")
        return

    console.print(f"Found {len(skills)} skill(s)")

    # Security audit
    if not no_audit:
        audit_result = audit_skills(skills)
        if audit_result.has_high_severity:
            console.print("\n[red bold]Security audit found high-severity issues:[/]\n")
            for finding in audit_result.high:
                console.print(f"  [red]HIGH[/] {finding.skill_name}: {finding.message}")
            console.print("\n[yellow]Use --no-audit to skip security checks (not recommended).[/]")
            return
        elif audit_result.findings:
            console.print(f"\n[yellow]Audit: {len(audit_result.findings)} finding(s) (none high severity)[/]")

    # Copy skills to target repo
    installed = 0
    for skill in skills:
        dest_dir = "rules" if skill.skill_type == "rule" else "skills"
        dest_path = target_root / dest_dir / skill.name
        source_dir = skill.source_path.parent

        if dest_path.exists():
            console.print(f"  [yellow]Skipping {skill.name} (already exists)[/]")
            continue

        dest_path.mkdir(parents=True, exist_ok=True)

        # Copy the entire skill directory
        for item in source_dir.iterdir():
            dest_item = dest_path / item.name
            if item.is_dir():
                shutil.copytree(item, dest_item)
            else:
                shutil.copy2(item, dest_item)

        console.print(f"  [green]Installed {skill.name}[/] ({skill.skill_type})")
        installed += 1

    # Check for server dependencies
    for skill in skills:
        servers_json = skill.source_path.parent / "servers.json"
        if servers_json.exists():
            console.print(f"\n[cyan]{skill.name} declares MCP server dependencies.[/]")
            console.print(f"  Run 'mcpm install' for the servers listed in {skill.name}/servers.json")

    if installed:
        console.print(f"\n[green]Installed {installed} skill(s). Run 'mcpm skills sync' to transpile to clients.[/]")
    else:
        console.print("[yellow]No new skills installed.[/]")
