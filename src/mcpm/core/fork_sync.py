"""Sync a git-backed server checkout with a separate ``upstream`` remote.

``apply_server_update`` (updater.py) pulls a checkout's own ``origin``. A fork,
though, tracks a second remote (the original project, conventionally
``upstream``) and needs its own commits replayed on top of it. That multi-remote
"sync my fork" is out of scope for a plain pull, so it lives here.

The replay happens on a fresh ``<branch>-synced-<date>`` work branch, leaving the
original branch untouched as a backup, and — unlike ``pull_rebase`` — conflicts
are handed back to the caller (with the conflicted paths and how to continue)
instead of being auto-aborted, so a human or agent can resolve them and finish
the rebase/cherry-pick by hand. Nothing here pushes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from mcpm.core.source import GitSource, SourceMetadata
from mcpm.core.updater import _run_post_update
from mcpm.utils import git as git_utils

VALID_MODES = ("rebase", "onto-author")


@dataclass
class ForkSyncResult:
    """Outcome of a fork-sync attempt.

    ``status`` is one of ``success`` (replay clean), ``conflict`` (stopped mid
    rebase/cherry-pick, work branch left in place for manual resolution), or
    ``error`` (a precondition failed; the checkout is left on its original
    branch).
    """

    name: str
    mode: str
    status: str
    upstream_ref: Optional[str] = None
    original_branch: Optional[str] = None
    work_branch: Optional[str] = None
    replayed_commits: List[str] = field(default_factory=list)
    conflicted_files: List[str] = field(default_factory=list)
    ahead: Optional[int] = None
    behind: Optional[int] = None
    post_update_ok: Optional[bool] = None
    post_update_stderr: str = ""
    message: str = ""
    error: Optional[str] = None


def _timestamp(explicit: Optional[str]) -> str:
    return explicit or datetime.now(timezone.utc).strftime("%Y%m%d")


def fork_sync(
    name: str,
    source: SourceMetadata,
    *,
    upstream_remote: str = "upstream",
    upstream_branch: str = "main",
    mode: str = "rebase",
    author_email: Optional[str] = None,
    target_branch: Optional[str] = None,
    run_post_update: bool = False,
    timestamp: Optional[str] = None,
) -> ForkSyncResult:
    """Replay a fork's commits onto ``upstream_remote/upstream_branch``.

    ``rebase`` rebases the current branch's commits; ``onto-author`` starts from
    the upstream ref and cherry-picks only commits authored by ``author_email``
    since the merge base (use when the branch has upstream commits mixed in).
    The result lands on a new branch; the original branch is never modified and
    nothing is pushed.
    """
    res = ForkSyncResult(name=name, mode=mode, status="error")

    if mode not in VALID_MODES:
        res.error = f"mode must be one of {VALID_MODES}, got {mode!r}"
        return res
    if not isinstance(source, GitSource):
        res.error = f"server {name!r} is not git-backed (source type {source.type!r})"
        return res
    if mode == "onto-author" and not author_email:
        res.error = "onto-author mode requires author_email"
        return res

    path = Path(source.path)
    if not path.exists() or not git_utils.is_git_repo(path):
        res.error = f"not a git repository: {source.path}"
        return res
    if not git_utils.remote_exists(path, upstream_remote):
        res.error = f"remote {upstream_remote!r} not configured in {source.path}"
        return res
    if git_utils.is_dirty(path):
        res.error = "working tree has uncommitted changes; commit or stash first"
        return res

    original = git_utils.current_branch(path)
    res.original_branch = original
    upstream_ref = f"{upstream_remote}/{upstream_branch}"
    res.upstream_ref = upstream_ref

    fetch = git_utils.fetch(path, remote=upstream_remote)
    if not fetch.success:
        res.error = fetch.error
        return res
    if git_utils.rev_parse(path, upstream_ref) is None:
        res.error = f"{upstream_ref} not found after fetch (wrong branch name?)"
        return res

    head_sha = git_utils.rev_parse(path, "HEAD")
    if head_sha is None:
        res.error = "could not resolve HEAD"
        return res

    work_branch = target_branch or f"{original or 'detached'}-synced-{_timestamp(timestamp)}"
    res.work_branch = work_branch

    if mode == "rebase":
        created = git_utils.create_and_checkout_branch(path, work_branch, head_sha, force=True)
        if not created.success:
            res.error = created.error
            return res
        op = git_utils.rebase_onto(path, upstream_ref)
        abort = git_utils.abort_rebase
        continue_cmd = "git rebase --continue"
    else:  # onto-author
        base = git_utils.merge_base(path, "HEAD", upstream_ref)
        if not base:
            res.error = f"no merge base between HEAD and {upstream_ref}"
            return res
        shas = git_utils.commits_by_author(path, f"{base}..{head_sha}", author_email)
        res.replayed_commits = shas
        created = git_utils.create_and_checkout_branch(path, work_branch, upstream_ref, force=True)
        if not created.success:
            res.error = created.error
            return res
        op = git_utils.cherry_pick(path, shas)
        abort = git_utils.abort_cherry_pick
        continue_cmd = "git cherry-pick --continue"

    if not op.success:
        conflicts = git_utils.conflicted_files(path)
        if conflicts:
            res.status = "conflict"
            res.conflicted_files = conflicts
            res.message = (
                f"{mode} stopped on conflicts in {len(conflicts)} file(s) on branch "
                f"{work_branch!r}. Resolve them, `git add`, then `{continue_cmd}`; or "
                f"abort and restore with `git checkout {original}`."
            )
            return res
        # Not a conflict — a hard failure. Abort and restore the original branch.
        abort(path)
        if original:
            git_utils.checkout(path, original)
        res.error = op.error
        return res

    ab = git_utils.ahead_behind(path, upstream_ref, "HEAD")
    if ab is not None:
        res.ahead, res.behind = ab
    res.status = "success"
    res.message = f"{mode} completed on branch {work_branch!r}; original branch {original!r} untouched"

    if run_post_update and source.post_update:
        ok, stderr = _run_post_update(source.post_update, path)
        res.post_update_ok = ok
        if not ok:
            res.post_update_stderr = stderr[:500]

    return res
