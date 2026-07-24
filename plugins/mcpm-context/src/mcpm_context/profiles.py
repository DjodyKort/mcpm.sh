"""Generate and reconcile CLAUDE_CONFIG_DIR profile directories.

A profile is a full stand-in for ~/.claude living at
~/.config/mcpm/claude-profiles/<name>/. Generated pieces:

- CLAUDE.md      — managed; org layer via @import (always fresh) or inline copy
- rules/         — symlink to ~/.claude/rules (inherit), absent (none), or a
                   real dir of per-layer symlinks/copies (explicit list)
- commands/, skills/, agents/ — dir symlinks into ~/.claude (share cf commands
                   and mcpm-transpiled skills without duplication)
- settings.json  — composed COPY (never a symlink: cf-dev-tools' jq merge must
                   not write through into profiles)
- .claude.json   — merged in place: identity/onboarding keys + mcpServers only;
                   everything Claude Code itself accumulates there is preserved

State (settings base hash, entries we created) is tracked in
.mcpm-context-state.json inside the profile dir so reconciliation and doctor
never have to guess what is ours.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Dict, List, Optional

from .paths import claude_home, claude_json_path, profiles_root
from .schema import DedupePolicy, ProfileSpec
from .settings import deep_merge_union

MANAGED_HEADER = "<!-- Managed by `mcpm context` — regenerate with `mcpm context sync`; do not edit. -->"
STATE_FILE = ".mcpm-context-state.json"
_IDENTITY_KEYS = ["oauthAccount", "userID"]
_ONBOARDING_KEYS = ["hasCompletedOnboarding", "lastOnboardingVersion"]
_LINK_DIRS = ["commands", "skills", "agents"]


def profile_dir(name: str) -> Path:
    return profiles_root() / name


def _sha256(path: Path) -> Optional[str]:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _load_state(pdir: Path) -> dict:
    try:
        return json.loads((pdir / STATE_FILE).read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(pdir: Path, state: dict) -> None:
    (pdir / STATE_FILE).write_text(json.dumps(state, indent=2) + "\n")


def generate_profile(name: str, spec: ProfileSpec, dedupe: DedupePolicy, report) -> Path:
    pdir = profile_dir(name)
    pdir.mkdir(parents=True, exist_ok=True)
    state = _load_state(pdir)

    _write_claude_md(pdir, spec, report)
    _reconcile_rules(pdir, spec, state, report)
    for sub in _LINK_DIRS:
        _reconcile_dir_link(pdir / sub, claude_home() / sub, getattr(spec, sub), report)
    _compose_settings(pdir, spec, state, report)
    _reconcile_claude_json(pdir, spec, dedupe, report)

    _save_state(pdir, state)
    return pdir


def remove_profile(name: str, report) -> bool:
    pdir = profile_dir(name)
    if not pdir.exists():
        return False
    shutil.rmtree(pdir)
    report.add(f"removed profile dir {pdir}")
    return True


# --- CLAUDE.md ---------------------------------------------------------------


def _write_claude_md(pdir: Path, spec: ProfileSpec, report) -> None:
    lines = [MANAGED_HEADER, ""]
    if spec.org:
        if spec.org_mode == "import":
            lines.append("@~/.claude/CLAUDE.md")
        else:
            org = claude_home() / "CLAUDE.md"
            body = org.read_text() if org.exists() else ""
            if not body:
                report.warn(f"org CLAUDE.md missing at {org} — profile gets empty org layer")
            lines.append(body)
    else:
        lines.append("<!-- org layer disabled for this profile -->")
    target = pdir / "CLAUDE.md"
    content = "\n".join(lines).rstrip() + "\n"
    if not target.exists() or target.read_text() != content:
        target.write_text(content)
        report.add(f"wrote {target}")


# --- rules -------------------------------------------------------------------


def _reconcile_rules(pdir: Path, spec: ProfileSpec, state: dict, report) -> None:
    target = pdir / "rules"
    source = claude_home() / "rules"

    if spec.rules == "inherit":
        _reconcile_dir_link(target, source, True, report)
        state.pop("rules_managed", None)
        return

    if spec.rules == "none":
        if target.is_symlink() or (target.is_dir() and _only_managed_entries(target, state)):
            _remove_path(target)
            report.add(f"removed rules from profile ({target})")
        elif target.exists():
            report.warn(f"{target} has unmanaged content; not removing (rules: none)")
        state.pop("rules_managed", None)
        return

    # Explicit layer list → real dir with per-file symlinks (or copies).
    if target.is_symlink():
        _remove_path(target)
    target.mkdir(parents=True, exist_ok=True)
    managed: List[str] = []
    for layer in spec.rules:
        src = source / f"{layer}.md"
        dst = target / f"{layer}.md"
        if not src.exists():
            report.warn(f"layer {layer!r} not found at {src} — run `mcpm skills sync --global`?")
            continue
        _place_file(src, dst, link=spec.link_rules)
        managed.append(dst.name)
    for stale in set(state.get("rules_managed", [])) - set(managed):
        _remove_path(target / stale)
        report.add(f"removed stale rule {stale} from profile")
    state["rules_managed"] = managed
    report.add(f"rules: {len(managed)} layer(s) [{'link' if spec.link_rules else 'copy'}]")


def _only_managed_entries(target: Path, state: dict) -> bool:
    managed = set(state.get("rules_managed", []))
    return all(p.name in managed for p in target.iterdir())


def _place_file(src: Path, dst: Path, *, link: bool) -> None:
    if dst.is_symlink() or dst.exists():
        _remove_path(dst)
    if link:
        dst.symlink_to(src)
    else:
        shutil.copy2(src, dst)


# --- shared dir symlinks -----------------------------------------------------


def _reconcile_dir_link(target: Path, source: Path, enabled: bool, report) -> None:
    if enabled:
        if not source.exists():
            # Normal on many machines (e.g. no ~/.claude/agents) — not a warning.
            report.add(f"skipped {target.name}/ (source {source} missing)")
            return
        if target.is_symlink():
            if target.resolve() == source.resolve():
                return
            _remove_path(target)
        elif target.exists():
            report.warn(f"{target} exists and is not a symlink; leaving it alone")
            return
        target.symlink_to(source, target_is_directory=True)
        report.add(f"linked {target.name}/ → {source}")
    else:
        if target.is_symlink():
            _remove_path(target)
            report.add(f"unlinked {target.name}/")


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


# --- settings.json -----------------------------------------------------------


def _compose_settings(pdir: Path, spec: ProfileSpec, state: dict, report) -> None:
    base_path = claude_home() / "settings.json"
    try:
        base = json.loads(base_path.read_text()) if base_path.exists() else {}
    except json.JSONDecodeError:
        base = {}
        report.warn(f"unparseable base settings at {base_path}; composing from empty")

    target = pdir / "settings.json"
    try:
        existing = json.loads(target.read_text()) if target.exists() else {}
    except json.JSONDecodeError:
        existing = {}

    # base ∪ profile-accumulated state (Claude Code writes approvals here during
    # profile sessions — keep them) ∪ policy overrides last so policy wins.
    merged = deep_merge_union(deep_merge_union(base, existing), spec.settings_overrides)
    content = json.dumps(merged, indent=2) + "\n"
    if not target.exists() or target.read_text() != content:
        target.write_text(content)
        report.add(f"composed {target}")
    state["settings_base_sha256"] = _sha256(base_path)


# --- .claude.json ------------------------------------------------------------


def _reconcile_claude_json(pdir: Path, spec: ProfileSpec, dedupe: DedupePolicy, report) -> None:
    target = pdir / ".claude.json"
    try:
        data = json.loads(target.read_text()) if target.exists() else {}
    except json.JSONDecodeError:
        data = {}
        report.warn(f"unparseable {target}; rebuilding minimal state")

    try:
        real = json.loads(claude_json_path().read_text()) if claude_json_path().exists() else {}
    except json.JSONDecodeError:
        real = {}

    for key in _ONBOARDING_KEYS + (_IDENTITY_KEYS if spec.copy_auth else []):
        if key in real:
            data[key] = real[key]

    data["mcpServers"] = _profile_servers(spec, dedupe, real, pdir, report)

    content = json.dumps(data, indent=2) + "\n"
    if not target.exists() or target.read_text() != content:
        target.write_text(content)
        report.add(f"reconciled {target} ({len(data['mcpServers'])} MCP server(s))")


def _profile_servers(spec: ProfileSpec, dedupe: DedupePolicy, real: dict, pdir: Path, report) -> Dict[str, dict]:
    if spec.servers == "none":
        return {}
    real_servers: Dict[str, dict] = real.get("mcpServers", {}) or {}
    if spec.servers == "inherit":
        # Mirror the current working set minus cf's legacy duplicates.
        return {k: v for k, v in real_servers.items() if k not in dedupe.legacy_names}

    shaped: Dict[str, dict] = {}
    for name in spec.servers:
        body = _shape_via_mcpm(name, pdir / ".claude.json")
        key = f"mcpm_{name}"
        if body is None:
            # mcpm not importable or server unknown → fall back to mirroring.
            fallback = real_servers.get(key) or real_servers.get(name)
            if fallback is None:
                report.warn(f"server {name!r} not in mcpm registry nor in {claude_json_path().name} — skipped")
                continue
            body = fallback
        shaped[key] = body
    return shaped


def _shape_via_mcpm(name: str, target_path: Path) -> Optional[dict]:
    """Shape one server entry exactly like `mcpm client sync` would (honours
    proxy_mode). Returns None when mcpm isn't importable or the server is
    unregistered — callers fall back to mirroring ~/.claude.json."""
    try:
        from mcpm.clients.managers.claude_code import ClaudeCodeManager
        from mcpm.global_config import GlobalConfigManager
    except ImportError:
        return None
    try:
        server = GlobalConfigManager().get_server(name)
        if server is None:
            return None
        return ClaudeCodeManager(config_path_override=str(target_path)).to_client_format(server)
    except Exception:
        return None
