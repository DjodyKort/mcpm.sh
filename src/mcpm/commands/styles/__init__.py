"""Output styles management commands."""

from mcpm.utils.rich_click_config import click

from .add import add_style
from .apply import apply_style_cmd
from .clean import clean_styles
from .diff import diff_styles
from .lint import lint_styles_cmd
from .list import list_styles
from .remove import remove_style_cmd
from .status import status_styles
from .sync import sync_styles_cmd


@click.group()
@click.help_option("-h", "--help")
def styles():
    """Manage output styles -- define once, sync to all clients.

    Output styles control HOW an AI responds (tone, verbosity, persona). Write a
    STYLE.md once and sync it to clients that support native style toggling (Claude
    Code, Roo Code). For other clients, use 'apply' to inject as an always-on rule.

    Examples: 'mcpm styles add concise' to create, 'mcpm styles sync' to push to
    native clients, 'mcpm styles apply concise' to inject into other clients."""
    pass


styles.add_command(add_style)
styles.add_command(sync_styles_cmd)
styles.add_command(apply_style_cmd)
styles.add_command(remove_style_cmd)
styles.add_command(list_styles)
styles.add_command(diff_styles)
styles.add_command(lint_styles_cmd)
styles.add_command(status_styles)
styles.add_command(clean_styles)
