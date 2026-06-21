"""Declarative config schema for the compression layer."""
from __future__ import annotations

import fnmatch
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field

ProviderName = Literal["headroom", "rtk-only", "none"]
RuntimeKind = Literal["proxy", "hook", "none"]

DEFAULT_PORT = 8787


class ContextRule(BaseModel):
    """Override the active provider when the launch directory matches `match`.

    `match` is an fnmatch glob tested against the absolute launch cwd — e.g.
    "*/clients/*" → provider "none" (no compression on sensitive repos), or
    "*/oss/*" → "rtk-only". First matching rule wins.
    """

    match: str
    provider: ProviderName


class CompressionConfig(BaseModel):
    """The user-facing swap knob. Persisted to ~/.config/mcpm/compression.json."""

    provider: ProviderName = "none"
    # Resolved from the provider when omitted; explicit override allowed.
    runtime: RuntimeKind = "none"
    scope: List[str] = Field(default_factory=lambda: ["default"])
    # mcpm ClientRegistry keys to propagate MCP presence to (e.g. "claude-code",
    # "cursor"). Only the proxy-wrapped clients need it; default to Claude Code.
    clients: List[str] = Field(default_factory=lambda: ["claude-code"])
    # Per-directory provider overrides, evaluated top-to-bottom; first match wins.
    contexts: List[ContextRule] = Field(default_factory=list)
    options: Dict[str, Any] = Field(default_factory=dict)

    @property
    def port(self) -> int:
        return int(self.options.get("port", DEFAULT_PORT))

    @property
    def telemetry(self) -> str:
        # Privacy default: off (honours the user's secret-hygiene rules).
        return str(self.options.get("telemetry", "off"))

    def resolved_provider(self, cwd: str) -> ProviderName:
        """Active provider for a launch cwd: first matching context, else default."""
        for rule in self.contexts:
            if fnmatch.fnmatch(cwd, rule.match):
                return rule.provider
        return self.provider
