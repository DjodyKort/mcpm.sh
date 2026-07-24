"""What the pinned headroom build can actually be told, and what it's actually running.

Two independent questions, two sources — and neither is the changelog:

- **Can it be told?** `read_knobs()` scans the installed package for genuine env lookups.
  Static, config-time, diagnostic only. This is how we learned the read-surface grows
  114 (0.27) -> 137 (0.29) -> 147 (0.31), and that `HEADROOM_PROTECT_READS` is 0.31-only.
- **What is it running?** `effective_config()` reads `GET /health` -> `config`, a
  documented-stable surface that reports the settings actually in force in a live proxy.

The scan alone cannot answer the second question, which is the one that matters: a knob can
be readable and still not be what the proxy ended up with. Conversely `/health` needs a
running proxy. So doctor uses the scan for `inert` (we declare it, the build never reads it)
and `/health` for `unsealed` (the build is running a posture value we never declared).

Neither is ever allowed to drop a knob from the emit path — emitting a knob a build ignores
is inert, dropping one it reads would silently change behaviour.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Optional, Set

# A genuine env lookup, not a mere mention. Docstrings and --help text name knobs the build
# never reads (headroom's own CLI help still says code-aware is "Default: disabled" on a
# build where it isn't), so matching bare string literals would over-report by ~30%.
_READ = re.compile(
    r'(?:os\.environ(?:\.get)?\(|getenv\(|_get_env_bool\(|_get_env_int\(|_get_env_float\('
    r'|_env_bool\(|_env_str\(|environ\[)\s*["\'](HEADROOM_[A-Z0-9_]+)["\']'
)

# `/health.config` key -> the env knob that sets it. This is the *sealable surface*: the
# settings headroom itself reports as its compression posture. Deliberately not all ~137
# readable knobs — most are infrastructure (proxy token, build version, upstream URLs) and
# have nothing to do with how much of your context gets rewritten.
POSTURE: Dict[str, str] = {
    "compress_system_messages": "HEADROOM_COMPRESS_SYSTEM_MESSAGES",
    "compress_user_messages": "HEADROOM_COMPRESS_USER_MESSAGES",
    "max_items_after_crush": "HEADROOM_MAX_ITEMS",
    "min_tokens_to_crush": "HEADROOM_MIN_TOKENS",
    "savings_profile": "HEADROOM_SAVINGS_PROFILE",
    "accuracy_guard": "HEADROOM_ACCURACY_GUARD",
    "protect_recent": "HEADROOM_PROTECT_RECENT",
    "protect_analysis_context": "HEADROOM_PROTECT_ANALYSIS_CONTEXT",
    "smart_crusher_with_compaction": "HEADROOM_SMART_CRUSHER_COMPACTION",
    "target_ratio": "HEADROOM_TARGET_RATIO",
    # NB: /health reports `force_kompress`, but the env var that sets it is
    # HEADROOM_FORCE_KOMPRESS_ALL — *not* the HEADROOM_FORCE_KOMPRESS that headroom's own
    # `agent-savings` emits. See _KNOWN_INERT.
    "force_kompress": "HEADROOM_FORCE_KOMPRESS_ALL",
}

# Knobs headroom's own `agent-savings` prints for you to export, but never reads back.
# `agent-savings` exists to emit an env bundle, so exporting its output verbatim silently
# fails to apply these — a vendor bug our snapshot faithfully reproduced. Verified against
# the 0.29.0 wheel; `_refresh_snapshots` keeps them (they are harmless) and doctor names
# them so the real knob can be declared as policy instead.
_KNOWN_INERT: Dict[str, Optional[str]] = {
    "HEADROOM_FORCE_KOMPRESS": "HEADROOM_FORCE_KOMPRESS_ALL",
    "HEADROOM_SAVINGS_TARGET": None,
}


def package_root() -> Optional[Path]:
    """Locate the installed headroom package (the pinned build's own source)."""
    try:
        import headroom  # noqa: F401 — import only to resolve its path
    except Exception:
        return _root_via_path()
    try:
        import headroom
        p = Path(headroom.__file__).parent
        return p if p.is_dir() else None
    except Exception:
        return None


def _root_via_path() -> Optional[Path]:
    """headroom is a uv tool, so it is normally NOT importable from mcpm's interpreter.
    Resolve its site-packages from the binary on PATH instead."""
    import shutil

    exe = shutil.which("headroom")
    if not exe:
        return None
    # ~/.local/bin/headroom -> ~/.local/share/uv/tools/headroom-ai/lib/python*/site-packages/headroom
    real = Path(exe).resolve()
    for base in (real.parent.parent, *real.parents):
        for lib in base.glob("lib/python*/site-packages/headroom"):
            if lib.is_dir():
                return lib
    return None


def read_knobs(root: Optional[Path] = None) -> Set[str]:
    """Every HEADROOM_* knob the installed build genuinely reads from env."""
    root = root or package_root()
    if not root or not root.is_dir():
        return set()
    found: Set[str] = set()
    for f in root.rglob("*.py"):
        try:
            found |= set(_READ.findall(f.read_text(errors="ignore")))
        except OSError:
            continue
    return found


def inert_for(knobs, root: Optional[Path] = None) -> Dict[str, Optional[str]]:
    """Declared knobs the pinned build never reads -> the knob that would work instead.

    Returns {} when the build can't be located, rather than declaring everything inert —
    an empty scan must never be read as "nothing works".
    """
    read = read_knobs(root)
    if not read:
        return {}
    return {k: _KNOWN_INERT.get(k) for k in knobs if k not in read}


def effective_config(port: int) -> Dict:
    """`GET /health` -> `config`: what a live proxy is actually running."""
    from .providers.headroom_runtime import proxy_health

    return proxy_health(port).get("config") or {}


def as_env_value(v) -> Optional[str]:
    """Render a `/health.config` value as the env string that would reproduce it.

    Returns None when the setting cannot be expressed as env. `None` in `/health.config`
    means *unset* — headroom's own internal default — and unset is a distinct state from
    any literal we could export: `HEADROOM_PROTECT_RECENT=""` is not the same as never
    setting it. Such settings are unsealable by construction; they are recorded and
    reported, never faked.
    """
    if v is None:
        return None
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, float, str)):
        return str(v)
    return None


def unsealed_for(knobs, port: int) -> Dict[str, object]:
    """Posture settings a live proxy holds that our policy never declared.

    These are the knobs the vendor is deciding for you. On a 0.30+ build they arrive as a
    bundled persona (`DEFAULT_PROFILE="coding"` seeds 19 at once); on 0.29 there is no
    seeding, so they fall to ordinary per-knob defaults — quieter, but still not yours.
    """
    config = effective_config(port)
    if not config:
        return {}
    declared = set(knobs)
    return {
        env_knob: config.get(cfg_key)
        for cfg_key, env_knob in POSTURE.items()
        if env_knob not in declared and cfg_key in config
    }


def split_unsealed(unsealed: Dict[str, object]) -> tuple[Dict[str, str], Dict[str, object]]:
    """Partition unsealed posture into (declarable, unset).

    - **declarable**: the proxy holds a concrete value we could pin as policy. Actionable.
    - **unset**: `None` — headroom's internal default, not expressible as env. Not
      actionable; it is stable only because the build is pinned, so it belongs in the lock
      and in a bump diff rather than in a warning that can never be cleared.
    """
    declarable: Dict[str, str] = {}
    unset: Dict[str, object] = {}
    for knob, raw in unsealed.items():
        rendered = as_env_value(raw)
        if rendered is None:
            unset[knob] = raw
        else:
            declarable[knob] = rendered
    return declarable, unset
