"""
Git operations for mcpm update.

All git interactions go through subprocess with timeouts and proper error handling.
"""

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

GIT_TIMEOUT = 30  # seconds


@dataclass
class GitStatus:
    """Result of checking a git repo's update status."""

    is_dirty: bool = False
    commits_behind: int = 0
    commit_summaries: List[str] = None  # One-line summaries of commits we're behind
    current_branch: str = ""
    remote_branch: str = ""
    error: Optional[str] = None

    def __post_init__(self):
        if self.commit_summaries is None:
            self.commit_summaries = []


@dataclass
class GitResult:
    """Result of a git operation."""

    success: bool
    message: str = ""
    error: Optional[str] = None


def _run_git(repo_path: Path, args: List[str], timeout: int = GIT_TIMEOUT) -> subprocess.CompletedProcess:
    """Run a git command in the given repo path."""
    cmd = ["git", "-C", str(repo_path)] + args
    logger.debug(f"Running: {' '.join(cmd)}")
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def is_git_repo(path: Path) -> bool:
    """Check if a path is inside a git repository."""
    try:
        result = _run_git(path, ["rev-parse", "--is-inside-work-tree"], timeout=5)
        return result.returncode == 0 and result.stdout.strip() == "true"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def get_remote_url(repo_path: Path, remote: str = "origin") -> Optional[str]:
    """Get the URL of a git remote."""
    try:
        result = _run_git(repo_path, ["remote", "get-url", remote], timeout=5)
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def get_default_branch(repo_path: Path, remote: str = "origin") -> Optional[str]:
    """Get the default branch name for a remote."""
    try:
        # Try to get from remote HEAD reference
        result = _run_git(repo_path, ["symbolic-ref", f"refs/remotes/{remote}/HEAD", "--short"], timeout=5)
        if result.returncode == 0:
            # Returns e.g. "origin/main" — strip the remote prefix
            ref = result.stdout.strip()
            return ref.replace(f"{remote}/", "", 1)

        # Fallback: check current branch
        result = _run_git(repo_path, ["branch", "--show-current"], timeout=5)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def is_dirty(repo_path: Path) -> bool:
    """Check if the working tree has uncommitted changes."""
    try:
        result = _run_git(repo_path, ["status", "--porcelain"], timeout=5)
        return result.returncode != 0 or bool(result.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return True  # Assume dirty if we can't check


def fetch(repo_path: Path, remote: str = "origin") -> GitResult:
    """Fetch from remote. Returns result with error details if it fails."""
    try:
        result = _run_git(repo_path, ["fetch", remote], timeout=GIT_TIMEOUT)
        if result.returncode == 0:
            return GitResult(success=True)

        stderr = result.stderr.strip()
        # Detect common SSH auth failures
        if any(phrase in stderr.lower() for phrase in ["permission denied", "could not read from remote", "host key"]):
            return GitResult(success=False, error="SSH auth failed — is your SSH agent running?")
        return GitResult(success=False, error=f"git fetch failed: {stderr}")

    except subprocess.TimeoutExpired:
        return GitResult(success=False, error=f"git fetch timed out after {GIT_TIMEOUT}s")
    except FileNotFoundError:
        return GitResult(success=False, error="git not found on PATH")


def _get_upstream_ref(repo_path: Path) -> Optional[str]:
    """Get the current branch's upstream tracking ref (e.g. 'origin/my-branch')."""
    try:
        result = _run_git(
            repo_path,
            ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def check_status(repo_path: Path, branch: Optional[str] = None, remote: str = "origin") -> GitStatus:
    """Check how many commits behind we are from the remote.

    Compares HEAD against the current branch's upstream tracking ref.
    Falls back to ``origin/{branch}`` when no upstream is configured.
    """
    # Prefer the current branch's upstream tracking ref so that repos
    # checked out on a non-default branch compare against the right remote.
    upstream = _get_upstream_ref(repo_path)
    if upstream:
        remote_ref = upstream
    else:
        if not branch:
            branch = get_default_branch(repo_path, remote) or "main"
        remote_ref = f"{remote}/{branch}"

    # Determine current local branch name for display
    try:
        result = _run_git(repo_path, ["branch", "--show-current"], timeout=5)
        current_branch = result.stdout.strip() if result.returncode == 0 else branch or "unknown"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        current_branch = branch or "unknown"

    status = GitStatus(current_branch=current_branch, remote_branch=remote_ref)

    # Check dirty
    status.is_dirty = is_dirty(repo_path)

    # Count commits behind
    try:
        result = _run_git(repo_path, ["rev-list", "--count", f"HEAD..{remote_ref}"], timeout=5)
        if result.returncode == 0:
            status.commits_behind = int(result.stdout.strip())
        else:
            status.error = f"Could not compare with {remote_ref}: {result.stderr.strip()}"
            return status
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError) as e:
        status.error = str(e)
        return status

    # Get commit summaries if behind
    if status.commits_behind > 0:
        try:
            # Limit to the first N commits to avoid excessive overhead on very behind repos
            result = _run_git(
                repo_path,
                ["log", "--oneline", "--max-count=50", f"HEAD..{remote_ref}", "--reverse"],
                timeout=5,
            )
            if result.returncode == 0:
                status.commit_summaries = [line for line in result.stdout.strip().split("\n") if line]
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    return status


def pull_ff_only(repo_path: Path) -> GitResult:
    """Pull with --ff-only. Safe — either succeeds cleanly or fails explicitly."""
    try:
        result = _run_git(repo_path, ["pull", "--ff-only"], timeout=GIT_TIMEOUT)
        if result.returncode == 0:
            return GitResult(success=True, message=result.stdout.strip())

        stderr = result.stderr.strip()
        if "not possible to fast-forward" in stderr.lower() or "fatal: not possible" in stderr.lower():
            return GitResult(
                success=False,
                error="cannot fast-forward — local and remote have diverged",
            )
        return GitResult(success=False, error=f"git pull --ff-only failed: {stderr}")

    except subprocess.TimeoutExpired:
        return GitResult(success=False, error=f"git pull timed out after {GIT_TIMEOUT}s")
    except FileNotFoundError:
        return GitResult(success=False, error="git not found on PATH")


def pull_rebase(repo_path: Path) -> GitResult:
    """Pull with --rebase. Rewrites local commits on top of upstream."""
    try:
        result = _run_git(repo_path, ["pull", "--rebase"], timeout=GIT_TIMEOUT)
        if result.returncode == 0:
            return GitResult(success=True, message=result.stdout.strip())

        stderr = result.stderr.strip()
        # If rebase fails with conflicts, abort it to leave the repo clean
        if "conflict" in stderr.lower() or "could not apply" in stderr.lower():
            _run_git(repo_path, ["rebase", "--abort"], timeout=5)
            return GitResult(
                success=False,
                error="rebase failed due to conflicts (aborted automatically)",
            )
        return GitResult(success=False, error=f"git pull --rebase failed: {stderr}")

    except subprocess.TimeoutExpired:
        # Try to abort any in-progress rebase
        try:
            _run_git(repo_path, ["rebase", "--abort"], timeout=5)
        except Exception:
            pass
        return GitResult(success=False, error=f"git pull --rebase timed out after {GIT_TIMEOUT}s")
    except FileNotFoundError:
        return GitResult(success=False, error="git not found on PATH")


# ---- Fork-sync primitives ----
#
# These support replaying a fork's own commits onto a separate `upstream`
# remote (see mcpm.core.fork_sync). Unlike pull_rebase above, the rebase /
# cherry-pick helpers here do NOT auto-abort on conflict — the caller inspects
# conflicted_files() and decides whether to hand the conflict to a human or
# abort. Query helpers return values/None; action helpers return GitResult.


def remote_exists(repo_path: Path, remote: str) -> bool:
    """Whether ``remote`` is configured in the repo."""
    try:
        result = _run_git(repo_path, ["remote", "get-url", remote], timeout=5)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def current_branch(repo_path: Path) -> Optional[str]:
    """Current branch name, or None when detached / on error."""
    try:
        result = _run_git(repo_path, ["branch", "--show-current"], timeout=5)
        if result.returncode == 0:
            return result.stdout.strip() or None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def rev_parse(repo_path: Path, ref: str) -> Optional[str]:
    """Resolve ``ref`` to a full SHA, or None when it doesn't exist."""
    try:
        result = _run_git(repo_path, ["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], timeout=5)
        if result.returncode == 0:
            return result.stdout.strip() or None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def merge_base(repo_path: Path, ref_a: str, ref_b: str) -> Optional[str]:
    """Best common ancestor of two refs, or None."""
    try:
        result = _run_git(repo_path, ["merge-base", ref_a, ref_b], timeout=10)
        if result.returncode == 0:
            return result.stdout.strip() or None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def ahead_behind(repo_path: Path, upstream_ref: str, head_ref: str = "HEAD") -> Optional[tuple]:
    """Return ``(ahead, behind)`` of ``head_ref`` relative to ``upstream_ref``."""
    try:
        result = _run_git(
            repo_path,
            ["rev-list", "--left-right", "--count", f"{upstream_ref}...{head_ref}"],
            timeout=10,
        )
        if result.returncode == 0:
            parts = result.stdout.split()
            if len(parts) == 2:
                behind, ahead = int(parts[0]), int(parts[1])
                return ahead, behind
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        pass
    return None


def commits_by_author(repo_path: Path, rev_range: str, author_email: str) -> List[str]:
    """SHAs in ``rev_range`` authored by ``author_email``, oldest first, merges excluded."""
    try:
        result = _run_git(
            repo_path,
            ["log", "--reverse", "--no-merges", "--format=%H", f"--author={author_email}", rev_range],
            timeout=15,
        )
        if result.returncode == 0:
            return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return []


def conflicted_files(repo_path: Path) -> List[str]:
    """Paths currently in an unmerged (conflicted) state."""
    try:
        result = _run_git(repo_path, ["diff", "--name-only", "--diff-filter=U"], timeout=10)
        if result.returncode == 0:
            return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return []


def create_and_checkout_branch(repo_path: Path, name: str, start_point: str, force: bool = False) -> GitResult:
    """Create (or reset, when ``force``) ``name`` at ``start_point`` and check it out."""
    flag = "-B" if force else "-b"
    try:
        result = _run_git(repo_path, ["checkout", flag, name, start_point], timeout=GIT_TIMEOUT)
        if result.returncode == 0:
            return GitResult(success=True, message=(result.stderr.strip() or result.stdout.strip()))
        return GitResult(success=False, error=f"git checkout {flag} {name} failed: {result.stderr.strip()}")
    except subprocess.TimeoutExpired:
        return GitResult(success=False, error="git checkout timed out")
    except FileNotFoundError:
        return GitResult(success=False, error="git not found on PATH")


def checkout(repo_path: Path, ref: str) -> GitResult:
    """Check out an existing ref/branch."""
    try:
        result = _run_git(repo_path, ["checkout", ref], timeout=GIT_TIMEOUT)
        if result.returncode == 0:
            return GitResult(success=True)
        return GitResult(success=False, error=f"git checkout {ref} failed: {result.stderr.strip()}")
    except subprocess.TimeoutExpired:
        return GitResult(success=False, error="git checkout timed out")
    except FileNotFoundError:
        return GitResult(success=False, error="git not found on PATH")


def rebase_onto(repo_path: Path, onto_ref: str) -> GitResult:
    """Rebase the current branch onto ``onto_ref``. Leaves conflicts in place."""
    try:
        result = _run_git(repo_path, ["rebase", onto_ref], timeout=GIT_TIMEOUT)
        if result.returncode == 0:
            return GitResult(success=True, message=result.stdout.strip())
        return GitResult(success=False, error=(result.stderr.strip() or result.stdout.strip()))
    except subprocess.TimeoutExpired:
        return GitResult(success=False, error=f"git rebase timed out after {GIT_TIMEOUT}s")
    except FileNotFoundError:
        return GitResult(success=False, error="git not found on PATH")


def cherry_pick(repo_path: Path, shas: List[str]) -> GitResult:
    """Cherry-pick ``shas`` in order. Stops at the first conflict (no auto-abort)."""
    if not shas:
        return GitResult(success=True, message="nothing to cherry-pick")
    try:
        result = _run_git(repo_path, ["cherry-pick", *shas], timeout=GIT_TIMEOUT)
        if result.returncode == 0:
            return GitResult(success=True, message=result.stdout.strip())
        return GitResult(success=False, error=(result.stderr.strip() or result.stdout.strip()))
    except subprocess.TimeoutExpired:
        return GitResult(success=False, error=f"git cherry-pick timed out after {GIT_TIMEOUT}s")
    except FileNotFoundError:
        return GitResult(success=False, error="git not found on PATH")


def abort_rebase(repo_path: Path) -> GitResult:
    """Abort an in-progress rebase."""
    try:
        result = _run_git(repo_path, ["rebase", "--abort"], timeout=GIT_TIMEOUT)
        return GitResult(success=result.returncode == 0, error=(None if result.returncode == 0 else result.stderr.strip()))
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return GitResult(success=False, error=str(e))


def abort_cherry_pick(repo_path: Path) -> GitResult:
    """Abort an in-progress cherry-pick."""
    try:
        result = _run_git(repo_path, ["cherry-pick", "--abort"], timeout=GIT_TIMEOUT)
        return GitResult(success=result.returncode == 0, error=(None if result.returncode == 0 else result.stderr.strip()))
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return GitResult(success=False, error=str(e))
