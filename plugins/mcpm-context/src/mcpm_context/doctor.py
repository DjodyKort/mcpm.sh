"""Health checks: drift, staleness, and cf-dev-tools tripwires.

Returns (level, message) tuples — "ok" / "warn" / "fail" — so the CLI can
render and tests can assert without parsing console output.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import List, Tuple

from .dedupe import plan_dedupe
from .layers import PERSONAL_RULE_NAME, rules_dir
from .paths import cf_install_dir, claude_home, claude_json_path, profiles_root, shims_path
from .profiles import STATE_FILE, MANAGED_HEADER
from .schema import ContextConfig

Check = Tuple[str, str]

# The only ~/.claude assets cf-dev-tools' sync writes today (claude.py:59-113).
# New files appearing in its claude/ source dir mean the org sync grew scope.
_KNOWN_CF_ASSETS = {"CLAUDE.md", "CLAUDE.uncompressed.md", "settings.json", "shell-wrapper.sh", "commands"}


def run_checks(config: ContextConfig) -> List[Check]:
    checks: List[Check] = []
    checks += _check_dupes(config)
    checks += _check_layers()
    checks += _check_settings_policy(config)
    checks += _check_profiles(config)
    checks += _check_shims(config)
    checks += _check_env()
    checks += _check_cf_drift(config)
    return checks


def _check_dupes(config: ContextConfig) -> List[Check]:
    dupes = plan_dedupe(claude_json_path(), config.dedupe)
    if dupes:
        return [("warn", f"legacy MCP duplicates present: {', '.join(dupes)} — run `mcpm context sync`")]
    return [("ok", "no legacy MCP duplicates")]


def _check_layers() -> List[Check]:
    checks: List[Check] = []
    canonical = rules_dir() / PERSONAL_RULE_NAME / "SKILL.md"
    transpiled = claude_home() / "rules" / f"{PERSONAL_RULE_NAME}.md"
    if not canonical.exists():
        checks.append(("warn", "no personal layer scaffolded — run `mcpm context init`"))
    elif not transpiled.exists():
        checks.append(("warn", f"personal layer not transpiled to {transpiled} — run `mcpm skills sync --global`"))
    else:
        checks.append(("ok", "personal layer in place (canonical + transpiled)"))
    return checks


def _check_settings_policy(config: ContextConfig) -> List[Check]:
    wanted = {"allow": config.settings.ensure_allow, "ask": config.settings.ensure_ask}
    if not any(wanted.values()):
        return []
    path = claude_home() / "settings.json"
    try:
        perms = json.loads(path.read_text()).get("permissions", {}) if path.exists() else {}
    except json.JSONDecodeError:
        return [("fail", f"{path} is not valid JSON")]
    missing = [e for key, entries in wanted.items() for e in entries if e not in perms.get(key, [])]
    if missing:
        return [("warn", f"{len(missing)} policy permission entr(y/ies) missing (cf clobber?) — run `mcpm context sync`")]
    return [("ok", "policy permission entries present in settings.json")]


def _check_profiles(config: ContextConfig) -> List[Check]:
    checks: List[Check] = []
    base_hash = _sha256(claude_home() / "settings.json")
    for name in config.profiles:
        pdir = profiles_root() / name
        if not pdir.is_dir():
            checks.append(("warn", f"profile {name!r} not generated — run `mcpm context sync`"))
            continue
        claude_md = pdir / "CLAUDE.md"
        if not claude_md.exists() or MANAGED_HEADER not in claude_md.read_text():
            checks.append(("warn", f"profile {name!r}: CLAUDE.md missing/unmanaged — run `mcpm context sync`"))
        broken = [p.name for p in pdir.iterdir() if p.is_symlink() and not p.resolve().exists()]
        if broken:
            checks.append(("warn", f"profile {name!r}: broken symlink(s): {', '.join(broken)}"))
        state = _state(pdir)
        if base_hash and state.get("settings_base_sha256") not in (None, base_hash):
            checks.append(("warn", f"profile {name!r}: settings.json stale vs ~/.claude — run `mcpm context sync`"))
        if not checks or not checks[-1][1].startswith(f"profile {name!r}"):
            checks.append(("ok", f"profile {name!r} healthy"))
    return checks


def _check_shims(config: ContextConfig) -> List[Check]:
    if not config.profiles and not config.wrap_default_claude:
        return []
    checks: List[Check] = []
    path = shims_path()
    if not path.exists():
        checks.append(("warn", "shims file missing — run `mcpm context sync`"))
        return checks
    zshrc = Path.home() / ".zshrc"
    if not zshrc.exists() or str(path) not in zshrc.read_text():
        checks.append(("warn", f"shims not sourced — add to ~/.zshrc:  source {path}"))
        return checks
    if config.wrap_default_claude:
        # Our claude()/hrclaude() overrides only win when sourced LAST.
        content = zshrc.read_text()
        ours = content.index(str(path))
        for other in ("shell-wrapper.sh", "compression-shims.zsh"):
            pos = content.find(other)
            if pos > ours:
                checks.append(("warn", f"context-shims sourced BEFORE {other} in ~/.zshrc — move our source line below it"))
                return checks
    checks.append(("ok", "shims written and sourced (last)"))
    return checks


def _check_env() -> List[Check]:
    if os.environ.get("CLAUDE_CONFIG_DIR"):
        return [("warn", "CLAUDE_CONFIG_DIR is exported globally — default `claude` now targets a profile, not ~/.claude")]
    return []


def _check_cf_drift(config: ContextConfig) -> List[Check]:
    checks: List[Check] = []
    cf = cf_install_dir()
    wrapper = cf / "claude" / "shell-wrapper.sh"
    if not cf.exists():
        return [("ok", "cf-dev-tools not installed — no coexistence constraints")]
    if wrapper.exists() and config.cf_wrapper_hash:
        if _sha256(wrapper) != config.cf_wrapper_hash:
            checks.append(("warn",
                           "cf-dev-tools shell-wrapper.sh CHANGED since baseline — re-verify its sync "
                           "still leaves rules/ and mcpServers alone, then re-baseline via `mcpm context sync`"))
        else:
            checks.append(("ok", "cf-dev-tools shell-wrapper unchanged since baseline"))
    claude_src = cf / "claude"
    if claude_src.is_dir():
        unexpected = {p.name for p in claude_src.iterdir()} - _KNOWN_CF_ASSETS
        if unexpected:
            checks.append(("warn", f"cf-dev-tools claude/ grew new assets: {', '.join(sorted(unexpected))} — its sync scope may have expanded"))
    return checks


def _sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _state(pdir: Path) -> dict:
    try:
        return json.loads((pdir / STATE_FILE).read_text())
    except (OSError, json.JSONDecodeError):
        return {}
