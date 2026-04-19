"""Pure functions for checking and applying MCP server updates.

Extracted from ``mcpm.commands.update`` so both the Click command and
programmatic callers (e.g. ``mcpm-mcp`` tools) share one implementation.
Nothing here touches stdout, Rich, or prompts -- results come back as
dataclasses for the caller to render.

Three source kinds are supported:

* ``GitSource``     -- ``git pull --ff-only`` (or ``--rebase``) + optional
                       post-update shell command.
* ``GithubReleaseSource`` -- download latest release asset + unpack.
* ``NpxSource`` / ``UvxSource`` / ``RemoteSource`` -- out-of-band; these
  either self-update at runtime (npx/uvx) or have no meaningful update
  concept (http remote). ``check_server_update`` still returns a status
  so callers can render a consistent table.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from mcpm.core.source import (
    GithubReleaseSource,
    GitSource,
    NpxSource,
    RemoteSource,
    SourceMetadata,
    UnknownSource,
    UvxSource,
)
from mcpm.utils import git as git_utils

logger = logging.getLogger(__name__)

POST_UPDATE_TIMEOUT = 120


# ---- Check ----


@dataclass
class UpdateCheck:
    """Result of checking a single server for updates."""

    name: str
    source_kind: str
    can_update: bool = False
    # Human-readable summary, e.g. "3 commits behind origin/main" or "v1 -> v2".
    summary: Optional[str] = None
    # For git sources
    commits_behind: int = 0
    current_branch: Optional[str] = None
    remote_branch: Optional[str] = None
    is_dirty: bool = False
    # For release sources
    current_version: Optional[str] = None
    latest_version: Optional[str] = None
    # Any reason the check was skipped / failed.
    error: Optional[str] = None


def check_server_update(
    name: str,
    source: SourceMetadata,
    include_prerelease: bool = False,
) -> UpdateCheck:
    """Check one server's update status without applying anything."""
    kind = source.type
    result = UpdateCheck(name=name, source_kind=kind)

    if isinstance(source, GitSource):
        path = Path(source.path)
        if not path.exists():
            result.error = f"path not found: {source.path}"
            return result
        if git_utils.is_dirty(path):
            result.is_dirty = True
            result.error = "uncommitted changes"
            return result
        fetch = git_utils.fetch(path)
        if not fetch.success:
            result.error = fetch.error
            return result
        status = git_utils.check_status(path, branch=source.branch)
        result.current_branch = status.current_branch
        result.remote_branch = status.remote_branch
        result.commits_behind = status.commits_behind
        if status.error:
            result.error = status.error
            return result
        if status.commits_behind > 0:
            result.can_update = True
            plural = "s" if status.commits_behind != 1 else ""
            result.summary = f"{status.commits_behind} commit{plural} behind {status.remote_branch}"
        else:
            result.summary = "up to date"
        return result

    if isinstance(source, GithubReleaseSource):
        from mcpm.utils import github_release as release_utils

        check = release_utils.check_for_update(
            repo=source.repo,
            current_version=source.current_version,
            asset_pattern=source.asset_pattern,
            include_prerelease=include_prerelease,
        )
        result.current_version = source.current_version
        result.latest_version = check.latest_version
        if check.error:
            result.error = check.error
            return result
        if check.update_available:
            result.can_update = True
            result.summary = f"{source.current_version or 'unknown'} -> {check.latest_version}"
        else:
            result.summary = "up to date"
        return result

    if isinstance(source, (NpxSource, UvxSource)):
        result.summary = f"auto-updates via {kind}"
        return result

    if isinstance(source, RemoteSource):
        result.summary = "remote HTTP server (no update concept)"
        return result

    if isinstance(source, UnknownSource):
        result.error = source.reason or "unknown source"
        return result

    result.error = f"unsupported source type {kind!r}"
    return result


# ---- Apply ----


@dataclass
class UpdateApply:
    """Outcome of applying an update to a single server."""

    name: str
    source_kind: str
    updated: bool
    message: str = ""
    error: Optional[str] = None
    from_version: Optional[str] = None
    to_version: Optional[str] = None
    post_update_ok: bool = True
    post_update_stderr: str = ""


def apply_server_update(
    name: str,
    source: SourceMetadata,
    rebase: bool = False,
    include_prerelease: bool = False,
) -> UpdateApply:
    """Apply an available update to a single server.

    For git sources, post_update (if configured) runs after the pull and its
    exit code is reported via ``post_update_ok``.
    """
    kind = source.type

    if isinstance(source, GitSource):
        path = Path(source.path)
        if not path.exists():
            return UpdateApply(name=name, source_kind=kind, updated=False,
                               error=f"path not found: {source.path}")
        if git_utils.is_dirty(path):
            return UpdateApply(name=name, source_kind=kind, updated=False,
                               error="uncommitted changes")
        pull = git_utils.pull_rebase(path) if rebase else git_utils.pull_ff_only(path)
        if not pull.success:
            return UpdateApply(name=name, source_kind=kind, updated=False, error=pull.error)
        res = UpdateApply(name=name, source_kind=kind, updated=True,
                          message=pull.message or "pulled")
        if source.post_update:
            ok, stderr = _run_post_update(source.post_update, path)
            res.post_update_ok = ok
            if not ok:
                res.post_update_stderr = stderr[:500]
        return res

    if isinstance(source, GithubReleaseSource):
        from mcpm.utils import github_release as release_utils

        check = release_utils.check_for_update(
            repo=source.repo,
            current_version=source.current_version,
            asset_pattern=source.asset_pattern,
            include_prerelease=include_prerelease,
        )
        if check.error:
            return UpdateApply(name=name, source_kind=kind, updated=False, error=check.error)
        if not check.update_available:
            return UpdateApply(name=name, source_kind=kind, updated=False,
                               message="already up to date",
                               from_version=source.current_version,
                               to_version=check.latest_version)
        outcome = release_utils.apply_update(source.path, source.repo, check)
        if outcome.success:
            return UpdateApply(
                name=name,
                source_kind=kind,
                updated=True,
                message=outcome.message,
                from_version=source.current_version,
                to_version=outcome.new_version,
            )
        return UpdateApply(name=name, source_kind=kind, updated=False, error=outcome.error)

    if isinstance(source, (NpxSource, UvxSource)):
        return UpdateApply(name=name, source_kind=kind, updated=False,
                           message="self-updates at runtime; nothing to apply")

    if isinstance(source, RemoteSource):
        return UpdateApply(name=name, source_kind=kind, updated=False,
                           message="remote server; no update applicable")

    return UpdateApply(name=name, source_kind=kind, updated=False,
                       error=f"unsupported source type {kind!r}")


# ---- helpers ----


def _run_post_update(command: str, cwd: Path) -> tuple[bool, str]:
    """Run a post-update shell command. Returns (ok, stderr)."""
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=POST_UPDATE_TIMEOUT,
        )
        if result.returncode == 0:
            return True, ""
        return False, result.stderr or ""
    except subprocess.TimeoutExpired:
        return False, f"timed out after {POST_UPDATE_TIMEOUT}s"
    except Exception as e:  # noqa: BLE001
        return False, str(e)
