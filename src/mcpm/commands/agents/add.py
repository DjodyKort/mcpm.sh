"""Agents add command -- create a new agent from template."""

from pathlib import Path

from rich.console import Console

from mcpm.skills.agents.schema import AgentFrontmatter
from mcpm.utils.rich_click_config import click

console = Console()


@click.command(name="add")
@click.argument("name")
@click.option("--path", type=click.Path(), default=".", help="Skills repo root (default: current directory)")
@click.help_option("-h", "--help")
def add_agent(name, path):
    """Create a new agent from a template.

    NAME should be kebab-case (e.g., 'code-reviewer', 'test-writer').

    \b
        mcpm agents add code-reviewer
        mcpm agents add devops-agent
    """
    try:
        AgentFrontmatter(name=name, description="placeholder")
    except Exception as e:
        console.print(f"[red]Error: Invalid agent name '{name}': {e}[/]")
        return

    repo_path = Path(path).resolve()
    agent_dir = repo_path / "agents" / name

    if agent_dir.exists():
        console.print(f"[red]Error: Agent '{name}' already exists.[/]")
        return

    agent_dir.mkdir(parents=True, exist_ok=True)
    agent_file = agent_dir / "AGENT.md"

    template = f"""---
name: {name}
description: "TODO: Describe what this agent does and when to use it."
model: sonnet
tools: [Read, Grep, Glob]
---

TODO: Write the system prompt for this agent.

Describe its role, expertise, and how it should approach tasks.
"""
    agent_file.write_text(template, encoding="utf-8")

    console.print(f"\n[green]Agent '{name}' created at {agent_file}[/]\n")
    console.print("Edit the AGENT.md file, then run 'mcpm agents sync' to transpile to all clients.\n")
