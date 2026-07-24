"""Migration of the pre-pin config shape (no live headroom, no network)."""
from __future__ import annotations

from mcpm_compression.migrate import migrate_raw
from mcpm_compression.schema import CompressionConfig
from mcpm_compression.versions import spec_matches


def _old_config() -> dict:
    """The shape actually on disk before this change: flat `env`, bespoke flags, no pin."""
    return {
        "provider": "headroom",
        "runtime": "proxy",
        "presets": {
            "agent": {
                "mode": "token",
                "savings_profile": "agent-90",
                "env": {"HEADROOM_MODE": "token", "HEADROOM_CODE_AWARE_ENABLED": "1"},
                "intercept_tool_results": False,
                "code_aware": False,
                "port": 8788,
            }
        },
        "active_preset": "agent",
    }


def test01_flat_env_becomes_profile_sourced_knobs():
    migrated, _ = migrate_raw(_old_config())
    knobs = migrated["presets"]["agent"]["knobs"]
    # Snapshot values came from `headroom agent-savings`, so a re-snapshot may replace them.
    assert knobs["HEADROOM_MODE"] == {"value": "token", "applies": "*", "source": "profile"}
    assert "env" not in migrated["presets"]["agent"]


def test02_declared_false_flag_becomes_explicit_zero():
    """The F3 fix on disk.

    The old config declared code_aware=False while its snapshot carried
    HEADROOM_CODE_AWARE_ENABLED=1 — and the renderer only layered the knob when the flag
    was true, so the declared value was silently ignored. Migration must resolve that in
    favour of the declaration.
    """
    migrated, notes = migrate_raw(_old_config())
    knobs = migrated["presets"]["agent"]["knobs"]
    assert knobs["HEADROOM_CODE_AWARE_ENABLED"]["value"] == "0"
    # policy-sourced: this is our declaration, so a re-snapshot must not drop it.
    assert knobs["HEADROOM_CODE_AWARE_ENABLED"]["source"] == "policy"
    assert any("was being ignored" in n for n in notes)


def test03_migration_is_idempotent():
    once, _ = migrate_raw(_old_config())
    twice, _ = migrate_raw(dict(once))
    assert once == twice


def test04_migrated_config_validates_and_pins():
    migrated, _ = migrate_raw(_old_config())
    cfg = CompressionConfig.model_validate(migrated)
    assert "==" in cfg.provider_version.requirement()
    # Provenance is unknown for anything migrated — the old schema never recorded it.
    # Doctor must be able to say so rather than invent a version.
    assert cfg.presets["agent"].snapshot_version is None


def test05_empty_and_odd_configs_survive():
    assert migrate_raw({})[0] == {"provider_version": {}}
    assert migrate_raw({"presets": {"x": "not-a-dict"}})[0]["presets"]["x"] == "not-a-dict"


def test06_version_ranges():
    assert spec_matches("0.31.0", ">=0.30.0,<0.32.0")
    assert not spec_matches("0.29.0", ">=0.30.0,<0.32.0")
    assert not spec_matches("0.32.0", ">=0.30.0,<0.32.0")
    assert spec_matches("0.29.0", "*")
    assert spec_matches("0.29.0", "==0.29.0")
    # An unknown build matches only `*` — guessing would either hide a known issue or
    # drop a knob.
    assert spec_matches(None, "*")
    assert not spec_matches(None, ">=0.30.0")
