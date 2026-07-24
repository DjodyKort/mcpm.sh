"""Preset model + policy→env rendering (no live headroom, no network)."""
from __future__ import annotations

from mcpm_compression.providers import get_provider
from mcpm_compression.schema import (
    AGENT_PORT,
    DEFAULT_PIN,
    DEFAULT_PORT,
    CompressionConfig,
    CompressionPreset,
    ContextRule,
    KnobSpec,
)


def test01_default_presets_present():
    cfg = CompressionConfig()
    assert set(cfg.presets) >= {"interactive", "agent", "balanced"}
    assert cfg.active_preset == "interactive"
    assert cfg.presets["interactive"].mode == "cache"
    agent = cfg.presets["agent"]
    assert agent.mode == "token" and agent.savings_profile == "agent-90"
    assert agent.port == AGENT_PORT  # separate port → can run alongside interactive


def test02_resolve_returns_provider_and_preset():
    cfg = CompressionConfig(
        provider="headroom",
        active_preset="interactive",
        contexts=[
            ContextRule(match="*/clients/*", provider="none"),
            ContextRule(match="*/agent-batch/*", preset="agent"),
        ],
    )
    assert cfg.resolve("/Users/x/clients/acme") == ("none", "interactive")
    assert cfg.resolve("/Users/x/agent-batch/run") == ("headroom", "agent")
    assert cfg.resolve("/Users/x/personal") == ("headroom", "interactive")
    assert cfg.resolved_provider("/Users/x/clients/acme") == "none"


def test03_env_for_preset_layers_mode_and_base_url():
    cfg = CompressionConfig(provider="headroom", telemetry="off")
    hp = get_provider("headroom")
    agent = CompressionPreset(
        mode="token", savings_profile="agent-90", port=AGENT_PORT,
        knobs={"HEADROOM_SAVINGS_PROFILE": KnobSpec(value="agent-90"),
               "HEADROOM_MODE": KnobSpec(value="token")},
    )
    env = hp.env_for_preset(cfg, agent)
    assert env["ANTHROPIC_BASE_URL"] == f"http://127.0.0.1:{AGENT_PORT}"
    assert env["ENABLE_TOOL_SEARCH"] == "true"
    assert env["HEADROOM_MODE"] == "token"
    assert env["HEADROOM_SAVINGS_PROFILE"] == "agent-90"
    assert env["HEADROOM_TELEMETRY"] == "off"


def test04_preset_mode_overrides_snapshot_mode():
    # A cache preset that (oddly) seeds a token profile still launches in cache.
    cfg = CompressionConfig(provider="headroom")
    hp = get_provider("headroom")
    p = CompressionPreset(mode="cache", knobs={"HEADROOM_MODE": KnobSpec(value="token")})
    assert hp.env_for_preset(cfg, p)["HEADROOM_MODE"] == "cache"


def test05_declared_off_knob_is_emitted_explicitly():
    """F3 regression.

    The old code layered HEADROOM_CODE_AWARE_ENABLED only when code_aware was true, so a
    declared `false` could never turn off a knob the vendor's snapshot had set to "1" —
    and from 0.30 headroom seeds a default into any knob left unset. "Off" must therefore
    be an explicit "0" on the wire, never an absent key.
    """
    cfg = CompressionConfig(provider="headroom")
    hp = get_provider("headroom")
    p = CompressionPreset(knobs={"HEADROOM_CODE_AWARE_ENABLED": KnobSpec(value="0")})
    env = hp.env_for_preset(cfg, p)
    assert env["HEADROOM_CODE_AWARE_ENABLED"] == "0"


def test06_knobs_are_gated_by_the_pin():
    """A knob restricted to >=0.31 must not be emitted on a 0.29 pin.

    Measured: 0.29 never reads HEADROOM_PROTECT_READS, so declaring it there would claim a
    read-safety property the build does not honour.
    """
    hp = get_provider("headroom")
    p = CompressionPreset(knobs={
        "HEADROOM_PROTECT_READS": KnobSpec(value="1", applies=">=0.31.0"),
        "HEADROOM_MODE": KnobSpec(value="cache"),
    })
    on_29 = hp.env_for_preset(CompressionConfig(provider="headroom"), p)  # pin defaults to 0.29
    assert "HEADROOM_PROTECT_READS" not in on_29

    cfg31 = CompressionConfig(provider="headroom")
    cfg31.provider_version.pin = "0.31.0"
    assert hp.env_for_preset(cfg31, p)["HEADROOM_PROTECT_READS"] == "1"


def test07_interactive_preset_has_no_savings_env():
    cfg = CompressionConfig(provider="headroom")
    hp = get_provider("headroom")
    env = hp.env_for_preset(cfg, cfg.preset_for("interactive"))
    assert env["HEADROOM_MODE"] == "cache"
    assert env["ANTHROPIC_BASE_URL"] == f"http://127.0.0.1:{DEFAULT_PORT}"
    assert "HEADROOM_SAVINGS_PROFILE" not in env


def test08_pin_is_exact_never_a_floor():
    pv = CompressionConfig().provider_version
    assert pv.pin == DEFAULT_PIN
    req = pv.requirement()
    assert "==" in req and ">=" not in req
    assert req.startswith("headroom-ai[")
