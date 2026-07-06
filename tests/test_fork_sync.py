"""Tests for mcpm.core.fork_sync — replaying a fork's commits onto upstream.

Hermetic: builds real local git repos under tmp_path (upstream + a clone), so
fetches happen over a filesystem path and never touch the network.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from mcpm.core.fork_sync import fork_sync
from mcpm.core.source import GitSource, NpxSource

MINE = "me@test.dev"
OTHER = "other@test.dev"
UP = "up@test.dev"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {r.stderr}")
    return r


def _commit(repo: Path, rel: str, content: str, msg: str, email: str = MINE, name: str = "Dev") -> None:
    (repo / rel).write_text(content)
    _git(repo, "add", "-A")
    _git(repo, "-c", f"user.name={name}", "-c", f"user.email={email}", "commit", "-m", msg)


@pytest.fixture
def fork_and_upstream(tmp_path: Path) -> tuple[Path, Path]:
    """A fork (clone) with its own commits + an upstream that has advanced.

    upstream/main: U1 (base), U2 (added after divergence).
    fork/main:     U1, mine1 (MINE), other (OTHER), mine2 (MINE).
    fork has an `upstream` remote pointing at the upstream repo.
    """
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    _git(upstream, "init", "-b", "main")
    _commit(upstream, "base.txt", "base\n", "U1 base", email=UP, name="Up")

    fork = tmp_path / "fork"
    subprocess.run(["git", "clone", str(upstream), str(fork)], capture_output=True, text=True, check=True)
    _commit(fork, "mine1.txt", "mine1\n", "F mine1", email=MINE)
    _commit(fork, "other.txt", "other\n", "F other", email=OTHER, name="Other")
    _commit(fork, "mine2.txt", "mine2\n", "F mine2", email=MINE)

    _commit(upstream, "upnew.txt", "upnew\n", "U2 new", email=UP, name="Up")

    _git(fork, "remote", "add", "upstream", str(upstream))
    return fork, upstream


def test_onto_author_replays_only_matching_author(fork_and_upstream):
    fork, _ = fork_and_upstream
    res = fork_sync("s", GitSource(path=str(fork)), mode="onto-author", author_email=MINE, timestamp="test")

    assert res.status == "success", res.error
    assert res.work_branch == "main-synced-test"
    assert len(res.replayed_commits) == 2
    assert (res.ahead, res.behind) == (2, 0)
    # my commits landed, the upstream commit is present, the other author's is not
    assert (fork / "mine1.txt").exists()
    assert (fork / "mine2.txt").exists()
    assert (fork / "upnew.txt").exists()
    assert not (fork / "other.txt").exists()


def test_rebase_replays_all_branch_commits(fork_and_upstream):
    fork, _ = fork_and_upstream
    res = fork_sync("s", GitSource(path=str(fork)), mode="rebase", timestamp="test")

    assert res.status == "success", res.error
    assert (res.ahead, res.behind) == (3, 0)
    assert (fork / "other.txt").exists()  # rebase keeps every branch commit
    assert (fork / "upnew.txt").exists()


def test_original_branch_is_left_untouched(fork_and_upstream):
    fork, _ = fork_and_upstream
    before = _git(fork, "rev-parse", "main").stdout.strip()
    fork_sync("s", GitSource(path=str(fork)), mode="onto-author", author_email=MINE, timestamp="test")
    after = _git(fork, "rev-parse", "main").stdout.strip()
    assert before == after


def test_conflict_is_handed_back(tmp_path: Path):
    upstream = tmp_path / "up"
    upstream.mkdir()
    _git(upstream, "init", "-b", "main")
    _commit(upstream, "shared.txt", "base\n", "U1", email=UP, name="Up")

    fork = tmp_path / "fork"
    subprocess.run(["git", "clone", str(upstream), str(fork)], capture_output=True, text=True, check=True)
    _commit(fork, "shared.txt", "fork change\n", "F edits shared", email=MINE)

    _commit(upstream, "shared.txt", "upstream change\n", "U2 edits shared", email=UP, name="Up")
    _git(fork, "remote", "add", "upstream", str(upstream))

    res = fork_sync("s", GitSource(path=str(fork)), mode="onto-author", author_email=MINE, timestamp="test")
    assert res.status == "conflict"
    assert "shared.txt" in res.conflicted_files
    assert "continue" in res.message


def test_non_git_source_errors():
    res = fork_sync("s", NpxSource(package="x"), mode="rebase")
    assert res.status == "error"
    assert "not git-backed" in res.error


def test_missing_upstream_remote_errors(tmp_path: Path):
    repo = tmp_path / "solo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _commit(repo, "a.txt", "a\n", "c1")
    res = fork_sync("s", GitSource(path=str(repo)), mode="rebase")
    assert res.status == "error"
    assert "upstream" in res.error


def test_dirty_tree_errors(fork_and_upstream):
    fork, _ = fork_and_upstream
    (fork / "scratch.txt").write_text("uncommitted\n")
    _git(fork, "add", "-A")
    res = fork_sync("s", GitSource(path=str(fork)), mode="rebase")
    assert res.status == "error"
    assert "uncommitted" in res.error


def test_onto_author_requires_email(fork_and_upstream):
    fork, _ = fork_and_upstream
    res = fork_sync("s", GitSource(path=str(fork)), mode="onto-author")
    assert res.status == "error"
    assert "author_email" in res.error


def test_invalid_mode_errors(fork_and_upstream):
    fork, _ = fork_and_upstream
    res = fork_sync("s", GitSource(path=str(fork)), mode="bogus")
    assert res.status == "error"


def test_post_update_runs_after_clean_replay(fork_and_upstream):
    fork, _ = fork_and_upstream
    src = GitSource(path=str(fork), post_update="echo built > built.marker")
    res = fork_sync("s", src, mode="onto-author", author_email=MINE, run_post_update=True, timestamp="t2")
    assert res.status == "success", res.error
    assert res.post_update_ok is True
    assert (fork / "built.marker").exists()
