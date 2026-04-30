"""Tests for Phase 4 CLI commands: gateway, mode, bridge, client sync."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from mcpm.commands.gateway import gateway
from mcpm.commands.mode import mode_cmd
from mcpm.core.schema import RemoteServerConfig, STDIOServerConfig
from mcpm.global_config import GlobalConfigManager
from mcpm.router.runtime import RouterRuntime


@pytest.fixture
def isolated_home(tmp_path, monkeypatch) -> Path:
    home = tmp_path / "home"
    (home / ".config" / "mcpm").mkdir(parents=True)
    (home / ".cache" / "mcpm").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    return home


@pytest.fixture
def runner():
    return CliRunner()


# ----- gateway commands ---------------------------------------------------


def test010_gateway_status_when_router_not_running(runner, isolated_home):
    result = runner.invoke(gateway, ["status"])
    assert result.exit_code == 0
    assert "not running" in result.output.lower()


def test020_gateway_stop_is_noop_when_not_running(runner, isolated_home):
    result = runner.invoke(gateway, ["stop"])
    assert result.exit_code == 0
    assert "not running" in result.output.lower()


def test030_gateway_logs_errors_for_missing_server(runner, isolated_home):
    result = runner.invoke(gateway, ["logs", "nonexistent-server"])
    assert result.exit_code == 1
    assert "no log" in result.output.lower()


def test040_gateway_status_reads_state_file(runner, isolated_home):
    """A live runtime is reported. We mock _http_alive so we don't need a real router."""
    rt = RouterRuntime(pid=os.getpid(), port=12345, token="t", started_at=1000.0)
    RouterRuntime.write(rt)

    fake_status = {"servers": ["alpha"], "active_workers": 1}
    with patch("mcpm.commands.gateway._http_alive", return_value=True), \
         patch("mcpm.commands.gateway._fetch_status", return_value=fake_status), \
         patch("mcpm.commands.gateway._resolve_worker", return_value=(99999, 50_000_000)):
        result = runner.invoke(gateway, ["status"])
    assert result.exit_code == 0
    assert "running" in result.output
    assert "12345" in result.output
    assert "alpha" in result.output


def test041_gateway_doctor_when_router_not_running(runner, isolated_home):
    result = runner.invoke(gateway, ["doctor"])
    assert result.exit_code == 0
    assert "not running" in result.output.lower()


def test042_gateway_doctor_reports_healthy_servers(runner, isolated_home):
    rt = RouterRuntime(pid=os.getpid(), port=12345, token="t", started_at=0.0)
    RouterRuntime.write(rt)

    with patch("mcpm.commands.gateway._http_alive", return_value=True), \
         patch("mcpm.commands.gateway._fetch_status", return_value={"servers": ["alpha", "beta"]}), \
         patch("mcpm.commands.gateway._probe_server", return_value=(True, "ok")):
        result = runner.invoke(gateway, ["doctor"])
    assert result.exit_code == 0
    assert "alpha" in result.output
    assert "beta" in result.output
    assert "2/2" in result.output


def test043_gateway_doctor_exits_nonzero_on_probe_failure(runner, isolated_home):
    rt = RouterRuntime(pid=os.getpid(), port=12345, token="t", started_at=0.0)
    RouterRuntime.write(rt)

    def fake_probe(rt, name, *, timeout):
        return (name == "alpha"), "boom" if name != "alpha" else "ok"

    with patch("mcpm.commands.gateway._http_alive", return_value=True), \
         patch("mcpm.commands.gateway._fetch_status", return_value={"servers": ["alpha", "beta"]}), \
         patch("mcpm.commands.gateway._probe_server", side_effect=fake_probe):
        result = runner.invoke(gateway, ["doctor"])
    assert result.exit_code == 1
    assert "1/2" in result.output


# ----- mode command -------------------------------------------------------


def test050_mode_changes_proxy_mode_in_servers_json(runner, isolated_home):
    config = GlobalConfigManager(
        config_path=isolated_home / ".config" / "mcpm" / "servers.json",
        metadata_path=isolated_home / ".config" / "mcpm" / "profiles_metadata.json",
    )
    server = STDIOServerConfig(name="anna", command="anna-cli", args=[])
    config.add_server(server)

    with patch("mcpm.commands.mode.GlobalConfigManager", lambda: config):
        result = runner.invoke(mode_cmd, ["anna", "router"])
    assert result.exit_code == 0, result.output
    assert "auto → router" in result.output

    reloaded = GlobalConfigManager(
        config_path=isolated_home / ".config" / "mcpm" / "servers.json",
        metadata_path=isolated_home / ".config" / "mcpm" / "profiles_metadata.json",
    )
    persisted = reloaded.get_server("anna")
    assert persisted is not None
    assert persisted.proxy_mode == "router"


def test060_mode_rejects_unknown_server(runner, isolated_home):
    config = GlobalConfigManager(
        config_path=isolated_home / ".config" / "mcpm" / "servers.json",
        metadata_path=isolated_home / ".config" / "mcpm" / "profiles_metadata.json",
    )
    with patch("mcpm.commands.mode.GlobalConfigManager", lambda: config):
        result = runner.invoke(mode_cmd, ["nope", "direct"])
    assert result.exit_code == 1
    assert "not registered" in result.output.lower()


def test070_mode_rejects_invalid_mode(runner):
    result = runner.invoke(mode_cmd, ["anna", "bogus"])
    assert result.exit_code != 0
    # click's choice validation produces "Invalid value" / "is not one of"
    assert "bogus" in result.output


def test080_mode_no_op_when_already_in_target_mode(runner, isolated_home):
    config = GlobalConfigManager(
        config_path=isolated_home / ".config" / "mcpm" / "servers.json",
        metadata_path=isolated_home / ".config" / "mcpm" / "profiles_metadata.json",
    )
    server = STDIOServerConfig(name="anna", command="x", proxy_mode="legacy")
    config.add_server(server)

    with patch("mcpm.commands.mode.GlobalConfigManager", lambda: config):
        result = runner.invoke(mode_cmd, ["anna", "legacy"])
    assert result.exit_code == 0
    assert "already in mode" in result.output.lower()


# ----- client sync planner -----------------------------------------------


def test090_client_sync_planner_marks_remote_for_rewrite(isolated_home, monkeypatch):
    """An installed-as-legacy HTTP server should be flagged for rewrite to direct."""
    from mcpm.commands.client import _plan_sync

    config = GlobalConfigManager(
        config_path=isolated_home / ".config" / "mcpm" / "servers.json",
        metadata_path=isolated_home / ".config" / "mcpm" / "profiles_metadata.json",
    )
    config.add_server(RemoteServerConfig(name="clickup", url="https://mcp.clickup.com/mcp"))
    monkeypatch.setattr("mcpm.commands.client.global_config_manager", config)

    # Build a fake client manager that has the legacy entry installed.
    from mcpm.clients.base import JSONClientManager

    class _FakeClient(JSONClientManager):
        client_key = "fake"
        display_name = "Fake"
        download_url = ""

        def get_client_info(self):
            return {"name": self.display_name, "config_file": self.config_path}

        def is_client_installed(self) -> bool:
            return True

    with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as f:
        f.write(json.dumps({
            "mcpServers": {
                "mcpm_clickup": {"command": "mcpm", "args": ["run", "clickup"]},
            }
        }).encode("utf-8"))
        path = f.name
    try:
        manager = _FakeClient(config_path_override=path)
        before, after, changed = _plan_sync(
            manager, "Fake", force_legacy=False, keep_legacy=False
        )
        assert len(changed) == 1
        assert changed[0][0] == "mcpm_clickup"
        # The new entry should be the direct HTTP shape.
        assert after["mcpm_clickup"]["type"] == "http"
        assert after["mcpm_clickup"]["url"] == "https://mcp.clickup.com/mcp"
    finally:
        os.unlink(path)


def test100_client_sync_planner_keeps_stdio_as_legacy(isolated_home, monkeypatch):
    """Phase-1 stdio-in-auto resolves to legacy, so a sync of an stdio entry
    that's already in legacy shape produces no change."""
    from mcpm.commands.client import _plan_sync

    config = GlobalConfigManager(
        config_path=isolated_home / ".config" / "mcpm" / "servers.json",
        metadata_path=isolated_home / ".config" / "mcpm" / "profiles_metadata.json",
    )
    config.add_server(STDIOServerConfig(name="anna", command="anna-cli", args=[]))
    monkeypatch.setattr("mcpm.commands.client.global_config_manager", config)

    from mcpm.clients.base import JSONClientManager

    class _FakeClient(JSONClientManager):
        client_key = "fake"
        display_name = "Fake"
        download_url = ""

        def get_client_info(self):
            return {"name": self.display_name, "config_file": self.config_path}

        def is_client_installed(self) -> bool:
            return True

    with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as f:
        f.write(json.dumps({
            "mcpServers": {"mcpm_anna": {"command": "mcpm", "args": ["run", "anna"]}}
        }).encode("utf-8"))
        path = f.name
    try:
        manager = _FakeClient(config_path_override=path)
        before, after, changed = _plan_sync(
            manager, "Fake", force_legacy=False, keep_legacy=False
        )
        assert changed == []
    finally:
        os.unlink(path)


def test110_client_sync_planner_force_legacy_skips_already_legacy(isolated_home, monkeypatch):
    """A `--legacy` revert is idempotent: an entry already in mcpm-run shape
    produces no change. (To exercise an actual revert, see test111.)"""
    from mcpm.commands.client import _plan_sync

    config = GlobalConfigManager(
        config_path=isolated_home / ".config" / "mcpm" / "servers.json",
        metadata_path=isolated_home / ".config" / "mcpm" / "profiles_metadata.json",
    )
    config.add_server(RemoteServerConfig(name="clickup", url="https://mcp.clickup.com/mcp"))
    monkeypatch.setattr("mcpm.commands.client.global_config_manager", config)

    from mcpm.clients.base import JSONClientManager

    class _FakeClient(JSONClientManager):
        client_key = "fake"
        display_name = "Fake"
        download_url = ""

        def get_client_info(self):
            return {"name": self.display_name, "config_file": self.config_path}

        def is_client_installed(self) -> bool:
            return True

    with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as f:
        # Pretend a previous sync has migrated this to direct HTTP.
        f.write(json.dumps({
            "mcpServers": {"mcpm_clickup": {"command": "mcpm", "args": ["run", "clickup"]}}
        }).encode("utf-8"))
        path = f.name
    try:
        manager = _FakeClient(config_path_override=path)
        _, after, changed = _plan_sync(
            manager, "Fake", force_legacy=True, keep_legacy=False
        )
        # Idempotent: nothing changes because the entry is already legacy.
        assert changed == []
        assert after["mcpm_clickup"] == {"command": "mcpm", "args": ["run", "clickup"]}
    finally:
        os.unlink(path)


def test111_client_sync_planner_force_legacy_does_not_touch_unmanaged(isolated_home, monkeypatch):
    """--legacy must only rewrite entries that we recognize as mcpm-managed.

    A handwritten ``{"command": "node", ...}`` entry is left alone.
    """
    from mcpm.commands.client import _plan_sync

    config = GlobalConfigManager(
        config_path=isolated_home / ".config" / "mcpm" / "servers.json",
        metadata_path=isolated_home / ".config" / "mcpm" / "profiles_metadata.json",
    )
    monkeypatch.setattr("mcpm.commands.client.global_config_manager", config)

    from mcpm.clients.base import JSONClientManager

    class _FakeClient(JSONClientManager):
        client_key = "fake"
        display_name = "Fake"
        download_url = ""

        def get_client_info(self):
            return {"name": self.display_name, "config_file": self.config_path}

        def is_client_installed(self) -> bool:
            return True

    with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as f:
        f.write(json.dumps({
            "mcpServers": {
                "handwritten": {"command": "node", "args": ["server.js"]},
            }
        }).encode("utf-8"))
        path = f.name
    try:
        manager = _FakeClient(config_path_override=path)
        _, after, changed = _plan_sync(
            manager, "Fake", force_legacy=True, keep_legacy=False
        )
        assert changed == []
        assert after["handwritten"] == {"command": "node", "args": ["server.js"]}
    finally:
        os.unlink(path)


def test120_client_sync_safe_writes_legacy_companion(isolated_home, monkeypatch):
    """--safe keeps a `_legacy_<name>` entry alongside the new shape."""
    from mcpm.commands.client import _plan_sync

    config = GlobalConfigManager(
        config_path=isolated_home / ".config" / "mcpm" / "servers.json",
        metadata_path=isolated_home / ".config" / "mcpm" / "profiles_metadata.json",
    )
    config.add_server(RemoteServerConfig(name="clickup", url="https://mcp.clickup.com/mcp"))
    monkeypatch.setattr("mcpm.commands.client.global_config_manager", config)

    from mcpm.clients.base import JSONClientManager

    class _FakeClient(JSONClientManager):
        client_key = "fake"
        display_name = "Fake"
        download_url = ""

        def get_client_info(self):
            return {"name": self.display_name, "config_file": self.config_path}

        def is_client_installed(self) -> bool:
            return True

    with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as f:
        f.write(json.dumps({
            "mcpServers": {"mcpm_clickup": {"command": "mcpm", "args": ["run", "clickup"]}}
        }).encode("utf-8"))
        path = f.name
    try:
        manager = _FakeClient(config_path_override=path)
        _, after, changed = _plan_sync(
            manager, "Fake", force_legacy=False, keep_legacy=True
        )
        assert "_legacy_mcpm_clickup" in after
        assert after["_legacy_mcpm_clickup"] == {"command": "mcpm", "args": ["run", "clickup"]}
        assert after["mcpm_clickup"]["type"] == "http"
        assert any("legacy" in kind for _, kind in changed)
    finally:
        os.unlink(path)
