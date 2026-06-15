"""Thin wrapper around the ``claude`` binary for plugin operations.

All interactions go through subprocess with a timeout, mirroring the style of
``mcpm.utils.git`` and ``mcpm.commands.update._run_post_update``. Mutations are delegated
to ``claude plugin ...`` rather than touching Claude Code's internal cache directly.
"""

import json
import logging
import os
import shutil
import subprocess
from typing import List, Tuple

logger = logging.getLogger(__name__)

# Plugin updates clone/pull from remotes, which can be slow on large repos.
CLAUDE_TIMEOUT = 120  # seconds


def claude_bin() -> str:
    """Return the claude executable to use.

    Honors the ``MCPM_CLAUDE_BIN`` override so tests and unusual installs can point at a
    specific binary; otherwise defaults to ``claude`` on PATH.
    """
    return os.environ.get("MCPM_CLAUDE_BIN") or "claude"


def is_available() -> bool:
    """Check whether the Claude Code CLI is installed.

    Matches ``ClaudeCodeManager.is_client_installed`` -- ``shutil.which`` handles the
    Windows PATHEXT variants automatically.
    """
    override = os.environ.get("MCPM_CLAUDE_BIN")
    if override:
        return shutil.which(override) is not None or os.path.isfile(override)
    return shutil.which("claude") is not None


def _run(args: List[str], timeout: int = CLAUDE_TIMEOUT) -> Tuple[int, str, str]:
    """Run ``claude <args>`` and return ``(returncode, stdout, stderr)``.

    Never raises for the caller's sake: subprocess failures are mapped to a non-zero
    return code and an explanatory stderr string.
    """
    cmd = [claude_bin()] + args
    logger.debug("Running: %s", " ".join(cmd))
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"claude {' '.join(args)} timed out after {timeout}s"
    except FileNotFoundError:
        return 127, "", "claude not found on PATH"


def plugin_list_json() -> List[dict]:
    """Return installed plugins as parsed from ``claude plugin list --json``.

    Returns an empty list on any failure (non-zero exit, malformed JSON) so callers can
    treat "no plugins" and "could not read plugins" the same way.
    """
    rc, stdout, _ = _run(["plugin", "list", "--json"], timeout=30)
    if rc != 0:
        return []
    try:
        data = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        return []
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    # Some CLI versions may wrap the array, e.g. {"plugins": [...]}.
    if isinstance(data, dict) and isinstance(data.get("plugins"), list):
        return [item for item in data["plugins"] if isinstance(item, dict)]
    return []


def marketplace_update(name: str | None = None) -> Tuple[int, str, str]:
    """Refresh one (or all) marketplace catalogs from their remote.

    This is the "pull latest from remote" step -- it re-fetches the marketplace so newer
    plugin versions become visible before we compare/apply.
    """
    args = ["plugin", "marketplace", "update"]
    if name:
        args.append(name)
    return _run(args)


def plugin_update(plugin: str) -> Tuple[int, str, str]:
    """Update a single installed plugin to the latest version from its source."""
    return _run(["plugin", "update", plugin])
