"""Declarative config schema for the compression layer."""
from __future__ import annotations

from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field

ProviderName = Literal["headroom", "rtk-only", "none"]
RuntimeKind = Literal["proxy", "hook", "none"]

DEFAULT_PORT = 8787


class CompressionConfig(BaseModel):
    """The user-facing swap knob. Persisted to ~/.config/mcpm/compression.json."""

    provider: ProviderName = "none"
    # Resolved from the provider when omitted; explicit override allowed.
    runtime: RuntimeKind = "none"
    scope: List[str] = Field(default_factory=lambda: ["default"])
    options: Dict[str, Any] = Field(default_factory=dict)

    @property
    def port(self) -> int:
        return int(self.options.get("port", DEFAULT_PORT))

    @property
    def telemetry(self) -> str:
        # Privacy default: off (honours the user's secret-hygiene rules).
        return str(self.options.get("telemetry", "off"))
