"""Agents audit command -- security scanning."""

from pathlib import Path

from rich.console import Console

from mcpm.skills.agents.parser import discover_agents
from mcpm.skills.audit import audit_skills
from mcpm.skills.parser import find_skills_repo
from mcpm.utils.rich_click_config import click

console = Console()


@click.command(name="audit")
@click.option("--path", type=click.Path(), default=None, help="Skills repo root (default: auto-detect)")
@click.help_option("-h", "--help")
def audit_agents_cmd(path):
    """Security scan agents for prompt injection and suspicious patterns.

    Checks for prompt injection attempts, data exfiltration patterns,
    dangerous commands, and excessive permission requests.

    \b
        mcpm agents audit
    """
    start_path = Path(path).resolve() if path else None
    repo_path = find_skills_repo(start_path)
    if not repo_path:
        console.print("[yellow]No skills repository found.[/]")
        return

    agents = discover_agents(repo_path)
    if not agents:
        console.print("[yellow]No agents found to audit.[/]")
        return

    # audit_skills works on any object with .frontmatter.name and .body
    result = audit_skills(agents)

    if not result.findings:
        console.print(f"[green]All {len(agents)} agent(s) passed security audit.[/]")
        return

    for finding in result.findings:
        if finding.severity == "high":
            icon = "[red bold]HIGH[/]"
        elif finding.severity == "medium":
            icon = "[yellow]MED [/]"
        else:
            icon = "[dim]LOW [/]"

        line_info = f" (line {finding.line})" if finding.line else ""
        console.print(f"  {icon} [cyan]{finding.skill_name}[/]{line_info}: {finding.message}")

    console.print()
    high = len(result.high)
    med = len([f for f in result.findings if f.severity == "medium"])
    low = len([f for f in result.findings if f.severity == "low"])

    parts = []
    if high:
        parts.append(f"[red]{high} high[/]")
    if med:
        parts.append(f"[yellow]{med} medium[/]")
    if low:
        parts.append(f"[dim]{low} low[/]")
    console.print("  " + ", ".join(parts))

    if result.has_high_severity:
        raise SystemExit(1)
