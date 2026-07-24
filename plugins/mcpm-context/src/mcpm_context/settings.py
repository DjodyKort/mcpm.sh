"""Settings composition that survives cf-dev-tools' jq merge.

cf-dev-tools syncs team settings with `jq -s '.[0] * .[1]'`, which replaces
arrays wholesale — personal entries in permissions.allow are clobbered on every
org sync. `ensure_policy` re-unions the policy-declared entries back in
(additive only; team entries are never removed).
"""
from __future__ import annotations

import json
from pathlib import Path

from .backup import snapshot
from .schema import SettingsPolicy


def deep_merge_union(base: dict, override: dict) -> dict:
    """Recursive dict merge; lists become an ordered union (base first);
    scalars from override win."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge_union(result[key], value)
        elif key in result and isinstance(result[key], list) and isinstance(value, list):
            result[key] = result[key] + [v for v in value if v not in result[key]]
        else:
            result[key] = value
    return result


def ensure_policy(settings_path: Path, policy: SettingsPolicy, *, backup: bool = True) -> bool:
    """Union ensure_allow/ensure_ask into permissions.* of `settings_path`.

    Returns True when the file changed. Snapshots first — also a safety net for
    cf's jq-failure path, which replaces settings.json wholesale.
    """
    wanted = {"allow": policy.ensure_allow, "ask": policy.ensure_ask}
    if not any(wanted.values()):
        return False
    try:
        data = json.loads(settings_path.read_text()) if settings_path.exists() else {}
    except json.JSONDecodeError:
        return False  # never "fix" a file we can't parse — doctor surfaces it
    perms = data.setdefault("permissions", {})
    changed = False
    for key, entries in wanted.items():
        if not entries:
            continue
        current = perms.setdefault(key, [])
        missing = [e for e in entries if e not in current]
        if missing:
            current.extend(missing)
            changed = True
    if changed:
        if backup:
            snapshot(settings_path)
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(json.dumps(data, indent=2) + "\n")
    return changed


SECRETISH_MARKERS = ("SECRET", "TOKEN", "PASSWORD", "APIKEY", "API_KEY", "BEARER")


def looks_secret_bearing(entry: str) -> bool:
    """Heuristic: permission strings embedding credential assignments
    (e.g. `Bash(FOO_SECRET="..." npx:*)`) must not be propagated by policy."""
    upper = entry.upper()
    return "=" in entry and any(marker in upper for marker in SECRETISH_MARKERS)
