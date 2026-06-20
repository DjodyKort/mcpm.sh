"""rtk-only provider — Bash/CLI-output compression via rtk's hook, no proxy.

A "degenerate" provider: lighter and zero-key-handling (no API proxy), for
contexts where you don't want a credential-handling proxy (e.g. sensitive
client repos). rtk has no MCP server; its hook is installed by `rtk init`.
"""
from __future__ import annotations

import shutil
from typing import List, Optional

from ..provider import CompressionProvider, GeneratedFile, RuntimeSpec
from ..schema import CompressionConfig


class RtkOnlyProvider(CompressionProvider):
    name = "rtk-only"

    def mcp_server_config(self, config: CompressionConfig) -> Optional[dict]:
        return None  # rtk is a Bash hook, not an MCP server.

    def runtime_spec(self, config: CompressionConfig) -> RuntimeSpec:
        return RuntimeSpec(kind="hook", port=0, env={})

    def activation_artifacts(self, config: CompressionConfig) -> List[GeneratedFile]:
        # rtk's hook is owned by rtk itself (`rtk init -g`); nothing to generate.
        return []

    def health(self, config: CompressionConfig) -> dict:
        rtk = shutil.which("rtk")
        return {"ok": rtk is not None,
                "detail": f"rtk binary {'found at ' + rtk if rtk else 'NOT on PATH (brew install rtk)'}"}
