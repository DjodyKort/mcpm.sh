"""Claude Code plugin commands (Claude-Code-only).

Phase 1 ships the "pull latest from remote" slice: refresh marketplace catalogs and update
installed Claude Code plugins. State is read from Claude Code's on-disk JSON; every mutation
goes through the ``claude plugin`` CLI.

The group is named ``cc`` (not ``plugins``) to avoid colliding with mcpm's own Python
entry-point plugins (mcpm-mcp, mcpm-sync, ...).
"""

from mcpm.utils.rich_click_config import click

from .list import list_cc
from .update import update_cc


@click.group()
@click.help_option("-h", "--help")
def cc():
    """Manage Claude Code plugins -- update them from their remotes.

    Reads Claude Code's on-disk plugin state and drives the ``claude plugin`` CLI for any
    changes. Requires the Claude Code CLI (``claude``) to be installed.

    Examples: 'mcpm cc list' to see installed plugins and marketplaces, 'mcpm cc update'
    to refresh catalogs and update installed plugins.
    """
    pass


cc.add_command(update_cc)
cc.add_command(list_cc)
