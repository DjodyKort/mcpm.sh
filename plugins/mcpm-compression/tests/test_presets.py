"""Preset model + policy→env mapping tests (no live headroom, no network)."""
from __future__ import annotations

import json
from pathlib import Path

from mcpm_compression.providers import get_provider
from mcpm_compression.providers import headroom_runtime as hr
from mcpm_compression.schema import (
    AGENT_PORT,
    DEFAULT_PORT,
    CompressionConfig,
    CompressionPreset,
    ContextRule,
)

_FIXTURES = Path(__file__).parent / "fixtures"


def test01_default_presets_present():
    cfg = CompressionConfig()
    assert set(cfg.presets) >= {"interactive", "agent", "balanced"}
    assert cfg.active_preset == "interactive"
    assert cfg.presets["interactive"].mode == "cache"
    agent = cfg.presets["agent"]
    assert agent.mode == "token" and agent.savings_profile == "agent-90"
    assert agent.port == AGENT_PORT  # separate port → can run alongside interactive
    assert agent.intercept_tool_results is False  # A/B knob defaults OFF


def test02_resolve_returns_provider_and_preset():
    cfg = CompressionConfig(
        provider="headroom",
        active_preset="interactive",
        contexts=[
            ContextRule(match="*/clients/*", provider="none"),
            ContextRule(match="*/agent-batch/*", preset="agent"),
        ],
    )
    assert cfg.resolve("/Users/x/clients/acme") == ("none", "interactive")  # provider override, preset default
    assert cfg.resolve("/Users/x/agent-batch/run") == ("headroom", "agent")  # preset override, provider default
    assert cfg.resolve("/Users/x/personal") == ("headroom", "interactive")  # both default
    # back-compat shim
    assert cfg.resolved_provider("/Users/x/clients/acme") == "none"


def test03_env_for_preset_layers_mode_and_base_url():
    cfg = CompressionConfig(provider="headroom", telemetry="off")
    hp = get_provider("headroom")
    agent = CompressionPreset(mode="token", savings_profile="agent-90",
                              env=dict(hr._FALLBACK_PROFILE_ENV["agent-90"]),
                              intercept_tool_results=True, port=AGENT_PORT)
    env = hp.env_for_preset(cfg, agent)
    assert env["ANTHROPIC_BASE_URL"] == f"http://127.0.0.1:{AGENT_PORT}"
    assert env["ENABLE_TOOL_SEARCH"] == "true"
    assert env["HEADROOM_MODE"] == "token"           # preset.mode authoritative
    assert env["HEADROOM_SAVINGS_PROFILE"] == "agent-90"   # from the snapshot
    assert env["HEADROOM_INTERCEPT_ENABLED"] == "1"  # read-outliner on
    assert env["HEADROOM_TELEMETRY"] == "off"


def test04_preset_mode_overrides_snapshot_mode():
    # A cache preset that (oddly) seeds a token profile still launches in cache.
    cfg = CompressionConfig(provider="headroom")
    hp = get_provider("headroom")
    p = CompressionPreset(mode="cache", env={"HEADROOM_MODE": "token"})
    assert hp.env_for_preset(cfg, p)["HEADROOM_MODE"] == "cache"


def test05_fallback_constant_matches_captured_fixtures():
    # The runtime fallback must stay in lock-step with the captured 0.26.0 contract.
    for profile in ("agent-90", "balanced"):
        fixture = json.loads((_FIXTURES / f"agent_savings_{profile}.json").read_text())
        assert hr._FALLBACK_PROFILE_ENV[profile] == fixture


def test06_snapshot_profile_env_falls_back_without_binary(monkeypatch=None):
    # When headroom isn't on PATH, snapshot returns the captured constant.
    import mcpm_compression.providers.headroom_runtime as mod
    orig = mod._headroom
    mod._headroom = lambda: None
    try:
        assert mod.snapshot_profile_env("agent-90") == mod._FALLBACK_PROFILE_ENV["agent-90"]
        assert mod.snapshot_profile_env("nonexistent") == {}
    finally:
        mod._headroom = orig


def test07_interactive_preset_has_no_savings_env():
    # cache-mode interactive needs no agent-savings snapshot.
    cfg = CompressionConfig(provider="headroom")
    hp = get_provider("headroom")
    env = hp.env_for_preset(cfg, cfg.preset_for("interactive"))
    assert env["HEADROOM_MODE"] == "cache"
    assert env["ANTHROPIC_BASE_URL"] == f"http://127.0.0.1:{DEFAULT_PORT}"
    assert "HEADROOM_SAVINGS_PROFILE" not in env
