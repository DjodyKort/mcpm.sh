"""Tests for the fragile seam: sync.apply orchestration + mcp_presence client writes.

These run WITHOUT mcpm core installed and WITHOUT touching real artifacts:
- MCPM_CONFIG_DIR is redirected to a temp dir BEFORE importing the package, so
  save_config() and the shell snippet land in the sandbox.
- sync._MANAGED_ARTIFACTS is overridden to drop the real ~/Library launchd plist,
  so artifact cleanup can never unlink the user's actual plist.
- The mcpm touchpoints are faked (real mcpm is not a dependency of this plugin venv).
"""
from __future__ import annotations

import os
import sys
import tempfile
import types
from pathlib import Path
from unittest import mock

# --- sandbox the config dir BEFORE importing the package (paths bind at import) ---
_TMP = Path(tempfile.mkdtemp(prefix="mcpm-comp-test-"))
os.environ["MCPM_CONFIG_DIR"] = str(_TMP)

from mcpm_compression import sync as sync_mod  # noqa: E402
from mcpm_compression.config import load_config  # noqa: E402
from mcpm_compression.provider import GeneratedFile, RuntimeSpec  # noqa: E402
from mcpm_compression.schema import CompressionConfig, ContextRule  # noqa: E402

# Never let artifact cleanup touch the real launchd plist under ~/Library.
_SNIPPET = _TMP / "compression-env.sh"
sync_mod._MANAGED_ARTIFACTS = [_SNIPPET]


class _FakeProvider:
    """Stands in for a CompressionProvider so apply()'s orchestration is exercised
    independently of headroom/the filesystem."""

    def __init__(self, name, artifacts, mcp=None):
        self.name = name
        self._artifacts = artifacts
        self._mcp = mcp

    def mcp_server_config(self, config):
        return self._mcp

    def activation_artifacts(self, config):
        return self._artifacts

    def runtime_spec(self, config):
        return RuntimeSpec(kind="proxy")

    def health(self, config):
        return {"ok": True, "detail": ""}


def _headroom_like():
    art = GeneratedFile(path=_SNIPPET, content="# test\n", mode=0o600)
    return _FakeProvider(
        "headroom", [art],
        mcp={"name": "headroom", "command": "headroom", "args": ["mcp", "serve"], "proxy_mode": "direct"},
    )


def _patch_presence():
    """Patch the mcpm-touching helpers imported into sync; return the mock bundle."""
    return (
        mock.patch.object(sync_mod, "add_mcp_server", return_value=True),
        mock.patch.object(sync_mod, "push_to_clients", return_value=["claude-code"]),
        mock.patch.object(sync_mod, "remove_mcp_server", return_value=True),
        mock.patch.object(sync_mod, "remove_from_clients", return_value=["claude-code"]),
    )


def test01_apply_registers_mcp_and_writes_artifacts():
    cfg = CompressionConfig(provider="headroom", runtime="proxy", clients=["claude-code"])
    add, push, _rm, _rmc = _patch_presence()
    with mock.patch.object(sync_mod, "get_provider", return_value=_headroom_like()), \
         mock.patch.object(sync_mod, "is_present", return_value=False), \
         add as add_m, push as push_m, _rm, _rmc:
        report = sync_mod.apply(cfg)
    assert _SNIPPET.exists()
    add_m.assert_called_once()
    push_m.assert_called_once()
    assert any("registered MCP" in a for a in report.actions)
    assert any("propagated" in a for a in report.actions)
    assert load_config().provider == "headroom"  # persisted


def test02_apply_is_idempotent():
    cfg = CompressionConfig(provider="headroom", runtime="proxy", clients=["claude-code"])
    add, push, _rm, _rmc = _patch_presence()
    with mock.patch.object(sync_mod, "get_provider", return_value=_headroom_like()), \
         mock.patch.object(sync_mod, "is_present", return_value=False), \
         add, push, _rm, _rmc:
        sync_mod.apply(cfg)
        report2 = sync_mod.apply(cfg)  # second run must not error and must reconverge
    assert _SNIPPET.exists()
    assert not report2.warnings


def test03_none_provider_tears_down_mcp():
    cfg = CompressionConfig(provider="none", runtime="none")
    add, push, rm, rmc = _patch_presence()
    with mock.patch.object(sync_mod, "get_provider", return_value=_FakeProvider("none", [], mcp=None)), \
         mock.patch.object(sync_mod, "is_present", return_value=True), \
         add, push, rm as rm_m, rmc as rmc_m:
        report = sync_mod.apply(cfg)
    rm_m.assert_called_once()
    rmc_m.assert_called_once()
    assert not _SNIPPET.exists()  # stale artifact removed
    assert any("removed" in a for a in report.actions)


def test04_apply_surfaces_mcp_failure_as_warning_not_crash():
    cfg = CompressionConfig(provider="headroom", runtime="proxy", clients=["claude-code"])
    with mock.patch.object(sync_mod, "get_provider", return_value=_headroom_like()), \
         mock.patch.object(sync_mod, "add_mcp_server", side_effect=RuntimeError("boom")):
        report = sync_mod.apply(cfg)  # must not raise
    assert any("MCP registration failed" in w for w in report.warnings)


# --- mcp_presence client writes, with a faked mcpm in sys.modules ---

def _install_fake_mcpm(saved: dict):
    mcpm = types.ModuleType("mcpm")
    gc = types.ModuleType("mcpm.global_config")
    core = types.ModuleType("mcpm.core")
    core_schema = types.ModuleType("mcpm.core.schema")
    clients_pkg = types.ModuleType("mcpm.clients")
    cr_mod = types.ModuleType("mcpm.clients.client_registry")

    class STDIOServerConfig:
        def __init__(self, **kw):
            self.__dict__.update(kw)
            self.name = kw["name"]

    class GlobalConfigManager:
        _store: dict = {}

        def add_server(self, sc, force=False):
            type(self)._store[sc.name] = sc
            return True

        def remove_server(self, name):
            return type(self)._store.pop(name, None) is not None

        def get_server(self, name):
            return type(self)._store.get(name)

    class _FakeMgr:
        configure_key_name = "mcpServers"

        def __init__(self, key):
            self.key = key
            self._cfg = saved.setdefault(key, {})

        def to_client_format(self, server):
            return {"command": "headroom", "args": ["mcp", "serve"]}

        def _load_config(self):
            return self._cfg

        def _save_config(self, cfg):
            saved[self.key] = cfg
            return True

    class ClientRegistry:
        @staticmethod
        def detect_installed_clients():
            return {"claude-code": True, "cursor": False}

        @staticmethod
        def get_client_manager(key):
            return _FakeMgr(key)

    gc.GlobalConfigManager = GlobalConfigManager
    core_schema.STDIOServerConfig = STDIOServerConfig
    cr_mod.ClientRegistry = ClientRegistry
    sys.modules.update({
        "mcpm": mcpm,
        "mcpm.global_config": gc,
        "mcpm.core": core,
        "mcpm.core.schema": core_schema,
        "mcpm.clients": clients_pkg,
        "mcpm.clients.client_registry": cr_mod,
    })
    return GlobalConfigManager


def test05_push_and_remove_clients_use_mcpm_prefix():
    from mcpm_compression import mcp_presence as mp
    saved: dict = {}
    GCM = _install_fake_mcpm(saved)
    GCM().add_server(types.SimpleNamespace(name="headroom"))  # so get_server returns truthy

    pushed = mp.push_to_clients("headroom", ["claude-code"])
    assert pushed == ["claude-code"]
    assert "mcpm_headroom" in saved["claude-code"]["mcpServers"]
    # only installed clients are targeted (cursor is detected-but-not-installed)
    assert "cursor" not in saved

    assert mp.in_client("headroom", ["claude-code"]) == ["claude-code"]

    removed = mp.remove_from_clients("headroom", ["claude-code"])
    assert removed == ["claude-code"]
    assert "mcpm_headroom" not in saved["claude-code"]["mcpServers"]


def test06_enable_preserves_existing_contexts_and_options():
    """M1 regression: `enable` must load-merge, not rebuild from scratch."""
    from click.testing import CliRunner
    from mcpm_compression import cli as cli_mod
    from mcpm_compression.config import save_config

    seed = CompressionConfig(
        provider="none",
        clients=["claude-code", "cursor"],
        contexts=[ContextRule(match="*/clients/*", provider="none")],
        options={"port": 9001, "telemetry": "off"},
    )
    save_config(seed)

    def _stub_apply(config, persist=True):
        if persist:
            save_config(config)
        return sync_mod.ApplyReport()

    # Stub apply so the test exercises only enable's load-merge + persist (no real mcpm).
    with mock.patch.object(cli_mod, "apply", side_effect=_stub_apply):
        res = CliRunner().invoke(cli_mod.compression, ["enable", "--provider", "headroom"])

    assert res.exit_code == 0, res.output
    after = load_config()
    assert after.provider == "headroom"          # changed
    assert after.runtime == "proxy"              # inferred from provider
    assert [c.match for c in after.contexts] == ["*/clients/*"]   # preserved (the bug)
    assert after.clients == ["claude-code", "cursor"]             # preserved
    assert after.options["port"] == 9001         # preserved (no --port passed)
