"""Skills management commands."""

from mcpm.utils.rich_click_config import click

from .add import add_skill
from .audit import audit_skills_cmd
from .bundle import bundle_skills, unbundle_skills
from .clean import clean_skills
from .diff import diff_skills
from .git_sync import git_sync_skills
from .init import init_skills
from .install import install_skill
from .lint import lint_skills_cmd
from .list import list_skills
from .search import search_skills
from .status import status_skills
from .sync import sync_skills
from .tap import tap
from .uninstall import uninstall_skill


@click.group()
@click.help_option("-h", "--help")
def skills():
    """Manage AI coding skills -- author once, sync to all clients.

    Skills are AI coding instructions (rules, templates, workflows) written in a canonical
    SKILL.md format and transpiled to every installed client's native format. Supports 15+
    clients including Claude Code, Cursor, Windsurf, VS Code Copilot, and more.

    Examples: 'mcpm skills init' to start, 'mcpm skills sync' to transpile to all clients."""
    pass


# Register all subcommands
skills.add_command(init_skills)
skills.add_command(add_skill)
skills.add_command(sync_skills)
skills.add_command(list_skills)
skills.add_command(diff_skills)
skills.add_command(lint_skills_cmd)
skills.add_command(clean_skills)
skills.add_command(status_skills)
skills.add_command(install_skill)
skills.add_command(uninstall_skill)
skills.add_command(audit_skills_cmd)
skills.add_command(tap)
skills.add_command(search_skills)
skills.add_command(bundle_skills)
skills.add_command(unbundle_skills)
skills.add_command(git_sync_skills)
