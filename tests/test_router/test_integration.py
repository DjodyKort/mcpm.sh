"""End-to-end test: HTTP request through router → IPC → worker → upstream child.

The worker is a real subprocess (`mcpm _worker echo-test`) that re-reads
the global config from disk, so this test isolates HOME to a tmp dir and
writes a synthetic `servers.json` there. Both the in-process router and
the spawned worker then see the same isolated config.

Skipped on Windows where the Unix-socket IPC path is not used.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from mcpm.core.schema import STDIOServerConfig
from mcpm.router.app import build_app
from mcpm.router.supervisor import WorkerSupervisor

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="Unix sockets only on POSIX")


ECHO_SCRIPT = r"""
import json, sys
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    msg = json.loads(line)
    if "id" in msg:
        resp = {"jsonrpc": "2.0", "id": msg["id"], "result": {"echo": msg.get("params", {})}}
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()
"""


@pytest.fixture
def isolated_home(tmp_path, monkeypatch) -> Path:
    """Point HOME at a tmp dir so GlobalConfigManager (in this process AND in
    the spawned worker subprocess) reads from an isolated ~/.config/mcpm."""
    home = tmp_path / "home"
    (home / ".config" / "mcpm").mkdir(parents=True)
    (home / ".cache" / "mcpm").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    return home


@pytest.fixture
def echo_server(tmp_path, isolated_home) -> STDIOServerConfig:
    """Write a real servers.json with our echo server registered."""
    script = tmp_path / "echo.py"
    script.write_text(ECHO_SCRIPT)
    server = STDIOServerConfig(
        name="echo-test",
        command=sys.executable,
        args=[str(script)],
    )
    servers_json = isolated_home / ".config" / "mcpm" / "servers.json"
    servers_json.write_text(json.dumps({"echo-test": server.to_dict()}))
    return server


@pytest.fixture
def runtime_dir(isolated_home) -> Path:
    d = isolated_home / ".cache" / "mcpm" / "router"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture
def socket_dir(tmp_path) -> Path:
    """A short-path socket dir. Real prod uses /tmp/mcpm-router-<uid>; tests
    drop into /tmp/mcpm-test-<pid> so multiple test runs don't collide."""
    import os

    d = Path("/tmp") / f"mcpm-test-{os.getpid()}"
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    yield d
    # Best-effort cleanup.
    import shutil

    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def app_and_supervisor(echo_server, runtime_dir, socket_dir):
    """Build a router app + supervisor reading from the isolated HOME."""
    from mcpm.global_config import GlobalConfigManager

    config = GlobalConfigManager(
        config_path=Path.home() / ".config" / "mcpm" / "servers.json",
        metadata_path=Path.home() / ".config" / "mcpm" / "profiles_metadata.json",
    )
    supervisor = WorkerSupervisor(
        child_idle_timeout=300,
        runtime_dir=runtime_dir,
        socket_dir=socket_dir,
    )
    supervisor.config_manager = config
    app = build_app(supervisor, token="t-token", config_manager=config)
    yield app, supervisor


def _ensure_mcpm_on_path() -> bool:
    """The supervisor spawns `mcpm _worker`; that requires the CLI on PATH."""
    try:
        result = subprocess.run(["mcpm", "--help"], capture_output=True, timeout=5)
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def test010_health_endpoint_responds(app_and_supervisor):
    from starlette.testclient import TestClient

    app, _ = app_and_supervisor
    with TestClient(app) as client:
        resp = client.get("/_health")
        assert resp.status_code == 200
        assert resp.text == "ok"


def test020_status_endpoint_requires_token(app_and_supervisor):
    from starlette.testclient import TestClient

    app, _ = app_and_supervisor
    with TestClient(app) as client:
        # No token: rejected.
        resp = client.get("/_status")
        assert resp.status_code == 401
        # With token: visible.
        resp = client.get("/_status", headers={"Mcp-Mcpm-Token": "t-token"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["servers"] == ["echo-test"]


def test030_proxy_endpoint_rejects_get(app_and_supervisor):
    from starlette.testclient import TestClient

    app, _ = app_and_supervisor
    with TestClient(app) as client:
        resp = client.get("/echo-test/mcp", headers={"Mcp-Mcpm-Token": "t-token"})
        assert resp.status_code == 405


def test040_proxy_endpoint_rejects_unknown_token(app_and_supervisor):
    from starlette.testclient import TestClient

    app, _ = app_and_supervisor
    with TestClient(app) as client:
        resp = client.post(
            "/echo-test/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        )
        assert resp.status_code == 401


@pytest.mark.skipif(not _ensure_mcpm_on_path(), reason="mcpm CLI not on PATH")
def test050_proxy_endpoint_round_trips_through_real_worker(app_and_supervisor):
    """The big one: HTTP POST → router → spawned worker → echo child → response."""
    from starlette.testclient import TestClient

    app, supervisor = app_and_supervisor
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/echo-test/mcp",
                headers={"Mcp-Mcpm-Token": "t-token"},
                json={"jsonrpc": "2.0", "id": "abc", "method": "ping", "params": {"n": 7}},
            )
            assert resp.status_code == 200, resp.text
            payload = resp.json()
            assert payload["id"] == "abc"
            assert payload["result"] == {"echo": {"n": 7}}
            # One worker spawned, one alive.
            assert supervisor.worker_count == 1
    finally:
        # Tear down the spawned worker.
        import asyncio

        asyncio.run(supervisor.shutdown())
