"""Write-on-read migration of `compression.json` to the sealed/pinned schema.

The config is live on several machines and rides the mcpm-sync bundle, so the old shape
must keep loading. Migration is idempotent and runs inside `load_config()`.

The interesting step is `code_aware`/`intercept_tool_results`: they used to be layered
onto the env *only when true*, so a `false` could never turn off a knob the vendor's
snapshot had already set to `1`. Migrating them into explicit knob values is what fixes
that (F3) for configs already on disk.
"""
from __future__ import annotations

from typing import Any, Dict, List

# Old bespoke flag → the knob it always should have been.
_FLAG_KNOBS = {
    "code_aware": "HEADROOM_CODE_AWARE_ENABLED",
    "intercept_tool_results": "HEADROOM_INTERCEPT_ENABLED",
}


def migrate_raw(raw: Dict[str, Any]) -> tuple[Dict[str, Any], List[str]]:
    """Bring a parsed config dict up to the current schema.

    Returns (migrated, notes). Never raises on a partial/odd config — an unreadable
    fragment is left alone for the model validator to reject loudly.
    """
    notes: List[str] = []
    if not isinstance(raw, dict):
        return raw, notes

    presets = raw.get("presets")
    if isinstance(presets, dict):
        for name, preset in presets.items():
            if not isinstance(preset, dict):
                continue
            notes += _migrate_preset(name, preset)

    if "provider_version" not in raw:
        # Seeded at the schema default (the pin we build against). Recorded explicitly so
        # the pin is visible in the file rather than implied by plugin version.
        raw["provider_version"] = {}
        notes.append("seeded provider_version (exact pin; was an unpinned '>=' install)")

    return raw, notes


def _migrate_preset(name: str, preset: Dict[str, Any]) -> List[str]:
    notes: List[str] = []
    knobs: Dict[str, Any] = preset.get("knobs") or {}

    # 1. flat env snapshot -> knob map. These came from `headroom agent-savings`, so they
    #    are the vendor's values and a re-snapshot is entitled to replace them.
    env = preset.pop("env", None)
    if isinstance(env, dict) and env:
        for k, v in env.items():
            knobs.setdefault(k, {"value": str(v), "applies": "*", "source": "profile"})
        notes.append(f"preset '{name}': migrated {len(env)} env keys -> knobs")

    # 2. bespoke flags -> explicit knob values (this is the F3 fix on disk). These are OUR
    #    declarations, not the vendor's, so they are policy-sourced: a re-snapshot must
    #    keep them, and they outrank any profile value for the same knob.
    for flag, knob in _FLAG_KNOBS.items():
        if flag not in preset:
            continue
        val = preset.pop(flag)
        if not isinstance(val, bool):
            continue
        explicit = "1" if val else "0"
        prior = knobs.get(knob, {}).get("value")
        knobs[knob] = {"value": explicit, "applies": "*", "source": "policy"}
        if prior is not None and prior != explicit:
            notes.append(
                f"preset '{name}': {flag}={val} now declared explicitly as {knob}={explicit} "
                f"(snapshot had {knob}={prior} — the declared value was being ignored)"
            )
        else:
            notes.append(f"preset '{name}': {flag}={val} -> {knob}={explicit}")

    if knobs:
        preset["knobs"] = knobs
    # Provenance is unknown for anything migrated: the old schema never recorded which
    # headroom build produced the snapshot. Leave None so doctor says so out loud rather
    # than inventing a version.
    preset.setdefault("snapshot_version", None)
    return notes
