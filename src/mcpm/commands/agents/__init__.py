"""Agent management commands (local operations only)."""

from mcpm.utils.rich_click_config import click

from .add import add_agent
from .audit import audit_agents_cmd
from .clean import clean_agents
from .diff import diff_agents
from .lint import lint_agents_cmd
from .list import list_agents
from .status import status_agents
from .sync import sync_agents_cmd
from .uninstall import uninstall_agent


@click.group()
@click.help_option("-h", "--help")
def agents():
    """Manage AI coding agents -- define once, sync to all clients.

    Agents are reusable AI personas with tool restrictions, model selection,
    MCP server dependencies, and custom system prompts. Write an AGENT.md once
    and transpile it to Claude Code, Cursor, Codex CLI, Gemini CLI, VS Code
    Copilot, and Roo Code.

    Examples: 'mcpm agents add reviewer' to create, 'mcpm agents sync' to transpile."""
    pass


agents.add_command(add_agent)
agents.add_command(sync_agents_cmd)
agents.add_command(list_agents)
agents.add_command(lint_agents_cmd)
agents.add_command(diff_agents)
agents.add_command(clean_agents)
agents.add_command(status_agents)
agents.add_command(audit_agents_cmd)
agents.add_command(uninstall_agent)
