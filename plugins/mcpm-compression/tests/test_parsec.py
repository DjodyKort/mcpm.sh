"""parsec provider + the provider switch it forced into the seam.

Fully offline: parsec is never installed, `claude plugin` is never spawned. Every test
patches `parsec_runtime`, which is the point of that module existing.

The sandbox rules from test_apply apply here too — MCPM_CONFIG_DIR is redirected before the
package is imported, `apply` is only ever called with the mcpm touchpoints mocked, and no
test is allowed to reach the real ~/.claude or ~/.parsec.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest import mock

_TMP = Path(tempfile.mkdtemp(prefix="mcpm-parsec-test-"))
os.environ.setdefault("MCPM_CONFIG_DIR", str(_TMP))

from mcpm_compression import sync as sync_mod  # noqa: E402
from mcpm_compression.providers import get_provider  # noqa: E402
from mcpm_compression.providers import parsec_runtime as pr  # noqa: E402
from mcpm_compression.schema import CompressionConfig, ContextRule  # noqa: E402

CFG = CompressionConfig(provider="parsec", runtime="plugin")


def _state(**kw):
    """Patch the parsec_runtime probes to describe a machine state."""
    defaults = dict(plugin_installed=False, plugin_enabled=False, routed_base_url=None,
                    api_key_configured=False, version=None, present=False)
    defaults.update(kw)
    return [mock.patch.object(pr, name, return_value=val) for name, val in defaults.items()]


def _with(patches):
    for p in patches:
        p.start()
    return patches


def _stop(patches):
    for p in patches:
        p.stop()


# --- provider contract ------------------------------------------------------------

def test01_parsec_registers_no_mcp_and_writes_no_artifacts():
    """The plugin ships its own `scout` MCP server and its own wiring; a second copy of
    either is a conflict, not a convenience."""
    p = get_provider("parsec")
    assert p.mcp_server_config(CFG) is None
    assert p.activation_artifacts(CFG) == []


def test02_runtime_kind_is_plugin_with_the_port_parsec_actually_routed():
    p = get_provider("parsec")
    patches = _with(_state(routed_base_url="http://127.0.0.1:8123"))
    try:
        spec = p.runtime_spec(CFG)
    finally:
        _stop(patches)
    # "plugin", not "proxy": `compression proxy up|down` must never think it owns this one.
    assert spec.kind == "plugin"
    assert spec.port == 8123
    assert spec.env == {}


def test03_health_reports_each_stage_of_engagement():
    p = get_provider("parsec")
    for state, ok, needle in [
        ({}, False, "not installed"),
        ({"plugin_installed": True}, False, "disabled"),
        ({"plugin_installed": True, "plugin_enabled": True}, False, "no ANTHROPIC_BASE_URL"),
        ({"plugin_installed": True, "plugin_enabled": True,
          "routed_base_url": "http://127.0.0.1:8123"}, True, "routing all claude sessions"),
    ]:
        patches = _with(_state(**state))
        try:
            h = p.health(CFG)
        finally:
            _stop(patches)
        assert h["ok"] is ok, (state, h)
        assert needle in h["detail"], (state, h)


def test04_health_never_reads_the_api_key_value():
    """Presence only: the key is a secret and CLI output is not where it belongs."""
    p = get_provider("parsec")
    patches = _with(_state(plugin_installed=True, plugin_enabled=True, api_key_configured=True,
                           routed_base_url="http://127.0.0.1:8123"))
    try:
        h = p.health(CFG)
    finally:
        _stop(patches)
    assert h["api_key"] is True
    assert "psc_" not in json.dumps(h)


# --- the switch -------------------------------------------------------------------

def test05_activate_installs_then_enables_when_absent():
    p = get_provider("parsec")
    patches = _with(_state(version=pr.CONTRACT_VERSION))
    inst = mock.patch.object(pr, "install_plugin", return_value=(True, "installed"))
    en = mock.patch.object(pr, "enable_plugin", return_value=(True, "enabled"))
    try:
        with inst as inst_m, en as en_m:
            steps = p.activate(CFG)
    finally:
        _stop(patches)
    inst_m.assert_called_once()
    en_m.assert_called_once()
    assert all(ok for ok, _ in steps)
    assert any("no parsec API key" in d for _, d in steps)


def test06_activate_stops_when_the_install_fails():
    """A failed install must not be followed by an enable that silently 'succeeds'."""
    p = get_provider("parsec")
    patches = _with(_state())
    inst = mock.patch.object(pr, "install_plugin", return_value=(False, "claude CLI not on PATH"))
    en = mock.patch.object(pr, "enable_plugin", return_value=(True, "enabled"))
    try:
        with inst, en as en_m:
            steps = p.activate(CFG)
    finally:
        _stop(patches)
    en_m.assert_not_called()
    assert steps[-1][0] is False


def test07_activate_reports_version_drift_from_the_verified_contract():
    p = get_provider("parsec")
    patches = _with(_state(version="9.9.9", api_key_configured=True))
    try:
        with mock.patch.object(pr, "install_plugin", return_value=(True, "ok")), \
             mock.patch.object(pr, "enable_plugin", return_value=(True, "ok")):
            steps = p.activate(CFG)
    finally:
        _stop(patches)
    assert any(pr.CONTRACT_VERSION in d and "9.9.9" in d for _, d in steps)


def test08_deactivate_is_a_no_op_when_parsec_never_touched_this_machine():
    """The sweep asks this of every unselected provider on every apply — it has to be free."""
    p = get_provider("parsec")
    patches = _with(_state(present=False))
    try:
        with mock.patch.object(pr, "strip_routing") as strip:
            assert p.deactivate(CFG) == []
    finally:
        _stop(patches)
    strip.assert_not_called()


def test09_deactivate_strips_routing_before_disabling_the_plugin():
    """Order is load-bearing: the stale ANTHROPIC_BASE_URL outlives the plugin that served
    it, and nothing else will ever come back to clear it."""
    p = get_provider("parsec")
    calls = []
    patches = _with(_state(present=True, plugin_enabled=True))
    try:
        with mock.patch.object(pr, "strip_routing",
                               side_effect=lambda: (calls.append("strip"), (True, "ok"))[1]), \
             mock.patch.object(pr, "disable_plugin",
                               side_effect=lambda: (calls.append("disable"), (True, "ok"))[1]), \
             mock.patch.object(pr, "uninstall_data") as un:
            p.deactivate(CFG)
    finally:
        _stop(patches)
    assert calls == ["strip", "disable"]
    un.assert_not_called()  # the reversible depth never deletes ~/.parsec


def test10_teardown_removes_data_and_plugin_in_the_documented_order():
    p = get_provider("parsec")
    calls = []
    patches = _with(_state(present=True, plugin_enabled=True))

    def _rec(tag):
        return lambda: (calls.append(tag), (True, "ok"))[1]

    try:
        with mock.patch.object(pr, "strip_routing", side_effect=_rec("strip")), \
             mock.patch.object(pr, "uninstall_data", side_effect=_rec("uninstall")), \
             mock.patch.object(pr, "uninstall_plugin", side_effect=_rec("plugin-rm")), \
             mock.patch.object(pr, "disable_plugin", side_effect=_rec("disable")):
            p.deactivate(CFG, teardown=True)
    finally:
        _stop(patches)
    # The cleanup binary ships inside the plugin, so the plugin goes last.
    assert calls == ["strip", "uninstall", "plugin-rm"]


# --- the sweep in sync.apply ------------------------------------------------------

def _mocked_presence():
    return (mock.patch.object(sync_mod, "add_mcp_server", return_value=True),
            mock.patch.object(sync_mod, "push_to_clients", return_value=[]),
            mock.patch.object(sync_mod, "remove_mcp_server", return_value=True),
            mock.patch.object(sync_mod, "remove_from_clients", return_value=[]),
            mock.patch.object(sync_mod, "is_present", return_value=False))


def _apply(config):
    a, b, c, d, e = _mocked_presence()
    with a, b, c, d, e, mock.patch.object(sync_mod, "_materialize_presets", lambda *_: None):
        return sync_mod.apply(config, persist=False)


def test11_selecting_another_provider_disengages_parsec():
    """Not-configuring parsec is not the same as turning it off: its hooks fire on every
    Read and Bash while the plugin is enabled, whatever compression.json says."""
    with mock.patch.object(pr, "present", return_value=True), \
         mock.patch.object(pr, "plugin_enabled", return_value=True), \
         mock.patch.object(pr, "strip_routing", return_value=(True, "stripped")), \
         mock.patch.object(pr, "disable_plugin", return_value=(True, "disabled")) as dis:
        report = _apply(CompressionConfig(provider="none", runtime="none"))
    dis.assert_called_once()
    assert any("disable" in a for a in report.actions)


def test12_a_context_rule_naming_parsec_protects_it_from_the_sweep():
    """A directory rule that routes to parsec would be broken by an apply that turned parsec
    off — so rules protect, even though only the global provider activates."""
    cfg = CompressionConfig(provider="none", runtime="none",
                            contexts=[ContextRule(match="*/spikes/*", provider="parsec")])
    with mock.patch.object(pr, "present", return_value=True), \
         mock.patch.object(pr, "plugin_enabled", return_value=True), \
         mock.patch.object(pr, "disable_plugin", return_value=(True, "disabled")) as dis:
        _apply(cfg)
    dis.assert_not_called()


def test13_headroom_teardown_runs_only_at_the_destructive_depth():
    hp = get_provider("headroom")
    cfg = CompressionConfig(provider="none")
    assert hp.deactivate(cfg) == []
    with mock.patch("mcpm_compression.providers.headroom_runtime.mcp_uninstall",
                    return_value=(True, "removed")), \
         mock.patch("mcpm_compression.providers.headroom_runtime.unwrap",
                    return_value=(True, "unwrapped")):
        steps = hp.deactivate(cfg, teardown=True)
    assert [d.split(" — ")[0] for _, d in steps] == ["headroom mcp uninstall",
                                                     "headroom unwrap claude"]


def test14_schema_accepts_parsec_and_resolves_it_per_directory():
    cfg = CompressionConfig(provider="headroom",
                            contexts=[ContextRule(match="*/oss/*", provider="parsec")])
    assert cfg.resolved_provider("/Users/x/oss/thing") == "parsec"
    assert cfg.resolved_provider("/Users/x/work") == "headroom"
