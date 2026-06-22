"""Activation-artifact generators + legacy launchd cleanup identifiers."""
from .launchd import LAUNCHD_LABEL, launchd_plist_path
from .shell import SHELL_SNIPPET_PATH, shell_env_snippet

__all__ = [
    "LAUNCHD_LABEL",
    "launchd_plist_path",
    "SHELL_SNIPPET_PATH",
    "shell_env_snippet",
]
