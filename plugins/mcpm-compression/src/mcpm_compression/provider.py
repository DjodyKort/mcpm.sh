"""The compression-provider seam (the swap point).

Originally minimal by design, with a note to refactor "when a genuinely independent second
provider appears". parsec is that provider, and it moved the interface exactly once: a
provider can now be *switched*, not merely configured.

The reason is that parsec engages itself. headroom, rtk-only and none are inert until
something routes to them — describing them (artifacts + MCP presence) is the same as
activating them. parsec is a Claude Code plugin whose hooks fire on every Read and Bash the
moment it is installed, no matter what `compression.json` says. So "provider = headroom"
can only be true if the others are actually turned off, which is a verb, not a document.

Hence `activate` / `deactivate`, non-abstract and no-ops by default: only a provider that
can engage itself needs to implement them, and nothing else changes.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .schema import CompressionConfig


@dataclass
class GeneratedFile:
    """An activation artifact the plugin writes to disk (idempotently)."""

    path: Path
    content: str
    mode: int = 0o600
    note: str = ""


@dataclass
class RuntimeSpec:
    """How the provider's engine runs."""

    kind: str  # "proxy" | "hook" | "none"
    port: int = 0
    env: Dict[str, str] = field(default_factory=dict)


class CompressionProvider(abc.ABC):
    """A context-compression backend mcpm can wire into AI clients."""

    name: str

    @abc.abstractmethod
    def mcp_server_config(self, config: CompressionConfig) -> Optional[dict]:
        """mcpm STDIOServerConfig kwargs for this provider's MCP server, or None.

        Returned dict is fed to ``STDIOServerConfig(**kwargs)``; managing its
        presence across clients is mcpm's job (servers.json + client sync).
        """

    @abc.abstractmethod
    def runtime_spec(self, config: CompressionConfig) -> RuntimeSpec:
        """Describe the runtime engine (proxy daemon / hook / none)."""

    @abc.abstractmethod
    def activation_artifacts(self, config: CompressionConfig) -> List[GeneratedFile]:
        """Generated files that wire the engine in (launchd plist, shell snippet).

        This is where the non-declarative proxy/env reality is made reproducible:
        we emit artifacts; a one-time manual load/login remains the user's step.
        """

    @abc.abstractmethod
    def health(self, config: CompressionConfig) -> dict:
        """Liveness/﻿stats probe: ``{"ok": bool, "detail": str, ...}``."""

    def activate(self, config: CompressionConfig) -> List[Tuple[bool, str]]:
        """Engage a provider that runs itself (install/enable). Returns (ok, detail) steps.

        Default no-op: a provider whose whole footprint is artifacts + MCP presence is
        already fully activated by `apply` writing them.
        """
        return []

    def deactivate(self, config: CompressionConfig, *, teardown: bool = False) -> List[Tuple[bool, str]]:
        """Disengage this provider — called on every provider that is *not* selected.

        `teardown=False` must be cheap, reversible and safe to run when the provider was
        never installed; `teardown=True` may destroy the provider's own data and is only
        ever reached through `disable --teardown`.
        """
        return []

    # Shared helper: list artifact paths without rendering content (for disable/status).
    def artifact_paths(self, config: CompressionConfig) -> List[Path]:
        return [a.path for a in self.activation_artifacts(config)]
