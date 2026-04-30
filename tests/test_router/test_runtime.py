"""Tests for RouterRuntime read/write/launch."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from mcpm.router.runtime import RouterRuntime


@pytest.fixture
def isolated_state(tmp_path, monkeypatch):
    """Redirect RouterRuntime state file paths to a tmp dir."""
    state_file = tmp_path / "router-runtime.json"
    lock_file = tmp_path / "router-runtime.lock"
    monkeypatch.setattr(RouterRuntime, "state_path", classmethod(lambda cls: state_file))
    monkeypatch.setattr(RouterRuntime, "lock_path", classmethod(lambda cls: lock_file))
    yield state_file
    for p in (state_file, lock_file):
        if p.exists():
            p.unlink()


def test010_read_returns_none_when_state_missing(isolated_state):
    assert RouterRuntime.read() is None


def test020_write_then_read_round_trips(isolated_state):
    rt = RouterRuntime(pid=os.getpid(), port=12345, token="abc", started_at=100.0)
    RouterRuntime.write(rt)
    loaded = RouterRuntime.read()
    assert loaded is not None
    assert loaded.pid == os.getpid()
    assert loaded.port == 12345
    assert loaded.token == "abc"
    assert loaded.started_at == 100.0


def test030_state_file_is_mode_600(isolated_state):
    rt = RouterRuntime(pid=1, port=1, token="t", started_at=0.0)
    RouterRuntime.write(rt)
    mode = isolated_state.stat().st_mode & 0o777
    # Skip on Windows where chmod is best-effort.
    if os.name == "posix":
        assert mode == 0o600


def test040_read_returns_none_on_corrupt_state(isolated_state):
    isolated_state.parent.mkdir(parents=True, exist_ok=True)
    isolated_state.write_text("this is not json")
    assert RouterRuntime.read() is None


def test050_unlink_removes_state_and_lock(isolated_state):
    rt = RouterRuntime(pid=1, port=1, token="t", started_at=0.0)
    RouterRuntime.write(rt)
    lock_path = RouterRuntime.lock_path()
    lock_path.touch()
    assert isolated_state.exists()
    assert lock_path.exists()
    RouterRuntime.unlink()
    assert not isolated_state.exists()
    assert not lock_path.exists()


def test060_is_alive_false_for_dead_pid(isolated_state):
    # PID 0 is reserved on Linux/macOS and never represents a live process for os.kill checks.
    rt = RouterRuntime(pid=999_999_999, port=1, token="t", started_at=0.0)
    assert RouterRuntime._is_alive(rt) is False


def test070_is_alive_false_when_pid_alive_but_port_dead(isolated_state):
    """Stale state: this Python process exists but is not serving HTTP."""
    rt = RouterRuntime(pid=os.getpid(), port=1, token="t", started_at=0.0)
    # Connect to port 1 should fail or refuse — _is_alive must catch and return False.
    assert RouterRuntime._is_alive(rt) is False


def test080_read_or_launch_reuses_when_alive(isolated_state):
    """If both _is_alive and read return positively, no _launch is called."""
    rt = RouterRuntime(pid=os.getpid(), port=12345, token="t", started_at=0.0)
    RouterRuntime.write(rt)

    with patch.object(RouterRuntime, "_is_alive", return_value=True), \
         patch.object(RouterRuntime, "_launch") as launch_mock:
        result = RouterRuntime.read_or_launch()
        assert result.port == 12345
        launch_mock.assert_not_called()


def test090_advisory_lock_serializes_concurrent_launch(isolated_state):
    """Two read_or_launch callers do not both invoke _launch."""
    import threading

    launches = []

    def fake_launch(cls):
        launches.append(1)
        rt = RouterRuntime(pid=os.getpid(), port=33333, token="t", started_at=0.0)
        cls.write(rt)
        return rt

    with patch.object(RouterRuntime, "_launch", classmethod(fake_launch)), \
         patch.object(RouterRuntime, "_is_alive", side_effect=lambda rt: rt.port == 33333):
        results: list = []

        def caller():
            results.append(RouterRuntime.read_or_launch())

        threads = [threading.Thread(target=caller) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    # All four threads got back the same runtime, but _launch ran once.
    assert len(results) == 4
    assert all(r.port == 33333 for r in results)
    assert len(launches) == 1
