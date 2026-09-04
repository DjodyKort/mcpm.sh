"""Declarative config schema for the compression layer.

mcpm owns the *policy* here (provider + mode + savings preset + per-context routing);
headroom owns the runtime. The whole thing persists to ~/.config/mcpm/compression.json
and is carried in the mcpm-sync bundle, so policy syncs across machines.
"""
from __future__ import annotations

import fnmatch
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field

ProviderName = Literal["headroom", "rtk-only", "parsec", "none"]
# "plugin" = the engine is a Claude Code plugin: it carries its own proxy, hooks and MCP
# server, and Claude Code — not mcpm — owns its lifecycle. Distinct from "proxy" precisely
# so `compression proxy up|down` cannot mistake it for something it can start or stop.
RuntimeKind = Literal["proxy", "hook", "plugin", "none"]
CompressionMode = Literal["cache", "token"]

DEFAULT_PORT = 8787
# Default port for the opt-in agent proxy, so a token-mode agent proxy can run
# alongside the cache-mode interactive proxy (mode is cold-start per process).
AGENT_PORT = 8788

# The headroom version we build and verify against. Exact, never a floor: upstream ships
# ~2 releases/week and 0.30 started seeding a default persona into any unset knob, so a
# floating constraint silently rewrites the runtime. 0.29.0 predates that seeding and
# carries the cross-request cache-contamination fix (headroom#1473).
DEFAULT_PIN = "0.29.0"


class ProviderVersion(BaseModel):
    """The exact provider build this policy was written against.

    `pin` is an exact version — the uv constraint is `==pin`, never `>=`. Bumping it is a
    reviewed act (`mcpm compression update --to X --accept`), never a side effect.
    """

    package: str = "headroom-ai"
    pin: str = DEFAULT_PIN
    extras: List[str] = Field(default_factory=lambda: ["proxy", "code", "ml"])

    def requirement(self) -> str:
        extras = f"[{','.join(self.extras)}]" if self.extras else ""
        return f"{self.package}{extras}=={self.pin}"


KnobSource = Literal["profile", "policy"]


class KnobSpec(BaseModel):
    """One declared `HEADROOM_*` value, optionally restricted to a version range.

    `applies` is *authored* intent ("only mean this from 0.31 on"); the default `*` means
    "emit on every pin". It is deliberately NOT the same thing as whether the pinned binary
    reads the knob — that is measured (`headroom_capability`) and only ever reported, never
    used to drop a knob from the emit path. Emitting a knob a build ignores is inert;
    dropping one it reads would silently change behaviour.

    `source` says who owns the value:

    - `profile` — captured from `headroom agent-savings`. A re-snapshot replaces it.
    - `policy`  — *our* declaration (e.g. code_aware off). A re-snapshot must preserve it,
      and it wins over any profile value for the same knob.

    The default is `policy` because that is the fail-safe direction: failing to refresh a
    value is recoverable, silently deleting a declaration is not. A re-snapshot that drops
    a `policy` knob hands it straight back to the vendor's default — which is the whole
    failure this schema exists to prevent.
    """

    value: str
    applies: str = "*"
    source: KnobSource = "policy"


class CompressionPreset(BaseModel):
    """A named bundle of headroom knobs.

    `knobs` is a config-time *snapshot* of the `HEADROOM_*` bundle (seeded from
    `headroom agent-savings <savings_profile>`), so the launch path reads config only and
    never shells out. `mode` is authoritative and layered last.

    Every knob mcpm cares about is declared explicitly, including the offs. headroom seeds
    its own persona defaults into anything left unset (`setdefault` semantics), so an
    undeclared knob is a knob the vendor owns — and silently re-owns on upgrade.

    Presets meant to run *simultaneously* per-context (e.g. agent vs interactive) need
    distinct `port`s — a single proxy process is one mode, fixed at cold-start.
    """

    mode: CompressionMode = "cache"
    savings_profile: Optional[str] = None
    knobs: Dict[str, KnobSpec] = Field(default_factory=dict)
    # Which headroom version produced `knobs`. None = never snapshotted (doctor warns).
    snapshot_version: Optional[str] = None
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
    # The exact provider build this policy targets.
    provider_version: ProviderVersion = Field(default_factory=ProviderVersion)
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
