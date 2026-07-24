"""Declarative config schema for the context layer.

mcpm owns the *policy* here (layers, profiles, dedupe, settings-union); the org
tool cf-dev-tools keeps owning ~/.claude/CLAUDE.md and its team settings keys.
Persists to ~/.config/mcpm/context.json and is carried in the mcpm-sync bundle.
"""
from __future__ import annotations

import re
from typing import Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator

OrgMode = Literal["import", "copy"]
# "inherit" = mirror ~/.claude equivalents; "none" = empty; list = explicit selection.
RulesSpec = Union[Literal["inherit", "none"], List[str]]
ServersSpec = Union[Literal["inherit", "none"], List[str]]

# cf-dev-tools' MANAGED_MCP_SERVERS (cfdevtools/config.py) — the entries its
# `sync-claude` may (re-)add to ~/.claude.json under these exact names.
CF_LEGACY_SERVER_NAMES = ["context7", "playwright", "codeforward-odoo", "codeforward-typst"]

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


class ProfileSpec(BaseModel):
    """One CLAUDE_CONFIG_DIR profile, generated under ~/.config/mcpm/claude-profiles/<name>/."""

    org: bool = True
    # import = `@~/.claude/CLAUDE.md` line (always fresh, one-time approval dialog);
    # copy = inline the org content at sync time (no dialogs, fresh until next sync).
    org_mode: OrgMode = "import"
    rules: RulesSpec = "inherit"
    commands: bool = True
    skills: bool = True
    agents: bool = True
    servers: ServersSpec = "inherit"
    settings_overrides: Dict = Field(default_factory=dict)
    copy_auth: bool = True
    # Symlink rule files into the profile; False = copy (fallback when the
    # client doesn't discover rules through symlinks).
    link_rules: bool = True


class DedupePolicy(BaseModel):
    enabled: bool = True
    legacy_names: List[str] = Field(default_factory=lambda: list(CF_LEGACY_SERVER_NAMES))
    # Only remove a legacy entry when its mcpm_<name> twin exists in the same
    # file — never orphan a capability.
    require_mcpm_twin: bool = True


class SettingsPolicy(BaseModel):
    """Entries re-unioned into ~/.claude/settings.json permissions.* after every
    cf-dev-tools sync (its jq merge replaces arrays wholesale)."""

    ensure_allow: List[str] = Field(default_factory=list)
    ensure_ask: List[str] = Field(default_factory=list)


class ContextConfig(BaseModel):
    """The user-facing policy. Persisted to ~/.config/mcpm/context.json."""

    profiles: Dict[str, ProfileSpec] = Field(default_factory=dict)
    # Shims replace the default `claude()` (and `hrclaude()` when present) with a
    # superset of cf-dev-tools' wrapper: org sync + `mcpm context sync` in one
    # throttle, so union-restores land in the same beat as cf's clobber.
    wrap_default_claude: bool = True
    dedupe: DedupePolicy = Field(default_factory=DedupePolicy)
    settings: SettingsPolicy = Field(default_factory=SettingsPolicy)
    clients_root: str = "~/Documents/GitHub/OdooDevHeaven/clients"
    # Doctor tripwire baseline: sha256 of cf-dev-tools' claude/shell-wrapper.sh.
    # A change means cf's sync behavior may have shifted — re-verify assumptions.
    cf_wrapper_hash: Optional[str] = None

    @field_validator("profiles")
    @classmethod
    def _shell_safe_names(cls, v: Dict[str, ProfileSpec]) -> Dict[str, ProfileSpec]:
        for name in v:
            if not _NAME_RE.match(name):
                raise ValueError(
                    f"profile name {name!r} must match [a-z0-9][a-z0-9-]* (it becomes a shell function)"
                )
        return v
