"""The compression-provider seam (the swap point).

Kept deliberately minimal: there is effectively one real provider today
(headroom, with rtk bundled inside it). Expect to refactor this interface when a
genuinely independent second provider appears — do not over-generalise now.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

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

    # Shared helper: list artifact paths without rendering content (for disable/status).
    def artifact_paths(self, config: CompressionConfig) -> List[Path]:
        return [a.path for a in self.activation_artifacts(config)]
