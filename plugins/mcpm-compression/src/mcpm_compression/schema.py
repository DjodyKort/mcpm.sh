"""Declarative config schema for the compression layer.

mcpm owns the *policy* here (provider + mode + savings preset + per-context routing);
headroom owns the runtime. The whole thing persists to ~/.config/mcpm/compression.json
and is carried in the mcpm-sync bundle, so policy syncs across machines.
"""
from __future__ import annotations

import fnmatch
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field

ProviderName = Literal["headroom", "rtk-only", "none"]
RuntimeKind = Literal["proxy", "hook", "none"]
CompressionMode = Literal["cache", "token"]

DEFAULT_PORT = 8787
# Default port for the opt-in agent proxy, so a token-mode agent proxy can run
# alongside the cache-mode interactive proxy (mode is cold-start per process).
AGENT_PORT = 8788


class CompressionPreset(BaseModel):
    """A named bundle of headroom knobs.

    `env` is a config-time *snapshot* of the `HEADROOM_*` bundle (seeded from
    `headroom agent-savings <savings_profile>`), so the launch path reads config only
    and never shells out. `mode` is authoritative and layered last over `env`.

    Presets meant to run *simultaneously* per-context (e.g. agent vs interactive) need
    distinct `port`s — a single proxy process is one mode, fixed at cold-start.
    """

    mode: CompressionMode = "cache"
    savings_profile: Optional[str] = None
    env: Dict[str, str] = Field(default_factory=dict)
    intercept_tool_results: bool = False  # headroom --intercept-tool-results (Read outliner)
    code_aware: bool = False
    port: int = DEFAULT_PORT


def _default_presets() -> Dict[str, CompressionPreset]:
    """Built-in presets.

    - interactive: the proven cache-mode default (preserves the prompt-cache prefix).
    - agent: token + agent-90 on a separate port — opt-in 2nd proxy for batch/agent
      launches that share no prefix. Read-outliner OFF (an A/B hypothesis, not a verdict).
    - balanced: headroom's mid profile (token, lighter compression).
    """
    return {
        "interactive": CompressionPreset(mode="cache", port=DEFAULT_PORT),
        "agent": CompressionPreset(mode="token", savings_profile="agent-90", port=AGENT_PORT),
        "balanced": CompressionPreset(mode="token", savings_profile="balanced", port=DEFAULT_PORT),
    }


class ContextRule(BaseModel):
    """Override the active provider and/or preset when the launch cwd matches `match`.

    `match` is an fnmatch glob tested against the absolute launch cwd — e.g.
    "*/clients/*" → provider "none" (no compression on sensitive repos), or
    "*/agent-batch/*" → preset "agent". First matching rule wins. `provider`/`preset`
    fall back to the global values when omitted.
    """

    match: str
    provider: Optional[ProviderName] = None
    preset: Optional[str] = None


class CompressionConfig(BaseModel):
    """The user-facing policy. Persisted to ~/.config/mcpm/compression.json."""

    provider: ProviderName = "none"
    # Resolved from the provider when omitted; explicit override allowed.
    runtime: RuntimeKind = "none"
    scope: List[str] = Field(default_factory=lambda: ["default"])
    # mcpm ClientRegistry keys to propagate MCP presence to (e.g. "claude-code").
    clients: List[str] = Field(default_factory=lambda: ["claude-code"])
    # Per-directory overrides, evaluated top-to-bottom; first match wins.
    contexts: List[ContextRule] = Field(default_factory=list)
    # Named compression presets + which one is active by default.
    presets: Dict[str, CompressionPreset] = Field(default_factory=_default_presets)
    active_preset: str = "interactive"
    options: Dict[str, Any] = Field(default_factory=dict)

    @property
    def port(self) -> int:
        # Legacy global port. New code prefers the active preset's port.
        return int(self.options.get("port", DEFAULT_PORT))

    @property
    def telemetry(self) -> str:
        # Privacy default: off (honours the user's secret-hygiene rules).
        return str(self.options.get("telemetry", "off"))

    def preset_for(self, name: Optional[str] = None) -> CompressionPreset:
        """The named preset, the active one, or a safe default — never raises."""
        key = name or self.active_preset
        return self.presets.get(key) or self.presets.get("interactive") or CompressionPreset()

    def resolve(self, cwd: str) -> Tuple[ProviderName, str]:
        """Active (provider, preset_name) for a launch cwd: first matching context, else default."""
        for rule in self.contexts:
            if fnmatch.fnmatch(cwd, rule.match):
                return (rule.provider or self.provider, rule.preset or self.active_preset)
        return (self.provider, self.active_preset)

    def resolved_provider(self, cwd: str) -> ProviderName:
        """Back-compat: just the provider for a launch cwd."""
        return self.resolve(cwd)[0]
