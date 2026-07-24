"""Apply / tear down the declarative context config (idempotent)."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from .config import save_config
from .dedupe import apply_dedupe
from .layers import deploy_client_locals
from .paths import cf_install_dir, claude_home, claude_json_path, profiles_root
from .profiles import generate_profile, remove_profile
from .schema import ContextConfig
from .settings import ensure_policy
from .shims import remove_shims, write_shims


@dataclass
class ApplyReport:
    actions: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def add(self, msg: str) -> None:
        self.actions.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)


def _record_cf_baseline(config: ContextConfig, report: ApplyReport) -> None:
    """Doctor tripwire baseline: hash cf-dev-tools' shell wrapper so future
    behavior changes in the org sync surface as a doctor warning, not silently."""
    wrapper = cf_install_dir() / "claude" / "shell-wrapper.sh"
    if not wrapper.exists():
        return
    digest = hashlib.sha256(wrapper.read_bytes()).hexdigest()
    if config.cf_wrapper_hash is None:
        config.cf_wrapper_hash = digest
        report.add("recorded cf-dev-tools shell-wrapper baseline")


def apply(config: ContextConfig, *, persist: bool = True) -> ApplyReport:
    """Make the world match `config`. Safe to run repeatedly."""
    report = ApplyReport()

    # 1. Dedupe cf's legacy MCP entries (main file + every profile).
    if config.dedupe.enabled:
        removed = apply_dedupe(claude_json_path(), config.dedupe)
        if removed:
            report.add(f"removed legacy MCP entries from {claude_json_path().name}: {', '.join(removed)}")

    # 2. Re-union policy-declared permission entries after any cf clobber.
    if ensure_policy(claude_home() / "settings.json", config.settings):
        report.add("re-unioned ensure_allow/ensure_ask into settings.json")

    # 2b. Client layers as project memory for sessions rooted inside client repos.
    deploy_client_locals(Path(config.clients_root).expanduser(), report)

    # 3. Profiles.
    for name, spec in config.profiles.items():
        generate_profile(name, spec, config.dedupe, report)
        removed = apply_dedupe(profiles_root() / name / ".claude.json", config.dedupe)
        if removed:
            report.add(f"deduped profile {name}: {', '.join(removed)}")
    _warn_orphans(config, report)

    # 4. Shims — also without profiles: the wrapper keeps the default `claude`
    # (codeforward mode) and `hrclaude` fresh.
    if config.profiles or config.wrap_default_claude:
        report.add(f"wrote shims: {write_shims(config.profiles, config.wrap_default_claude)}")
    elif remove_shims():
        report.add("removed shims (no profiles, wrapper disabled)")

    _record_cf_baseline(config, report)
    if persist:
        save_config(config)
        report.add(f"saved config ({len(config.profiles)} profile(s))")
    return report


def _warn_orphans(config: ContextConfig, report: ApplyReport) -> None:
    root = profiles_root()
    if not root.is_dir():
        return
    for entry in root.iterdir():
        if entry.is_dir() and entry.name not in config.profiles:
            report.warn(f"orphan profile dir {entry} (not in config) — `mcpm context profile remove {entry.name} --purge`")


def disable(*, purge_profiles: bool = False) -> ApplyReport:
    """Strip generated artifacts. Leaves ~/.claude, ~/.claude.json, layer rules,
    and context.json untouched — re-running `sync` reconverges."""
    report = ApplyReport()
    if remove_shims():
        report.add("removed shims file")
    if purge_profiles and profiles_root().is_dir():
        for entry in sorted(profiles_root().iterdir()):
            if entry.is_dir():
                remove_profile(entry.name, report)
    return report
