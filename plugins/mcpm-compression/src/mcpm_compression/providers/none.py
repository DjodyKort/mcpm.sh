"""none provider — compression disabled (the off switch)."""
from __future__ import annotations

from typing import List, Optional

from ..provider import CompressionProvider, GeneratedFile, RuntimeSpec
from ..schema import CompressionConfig


class NoneProvider(CompressionProvider):
    name = "none"

    def mcp_server_config(self, config: CompressionConfig) -> Optional[dict]:
        return None

    def runtime_spec(self, config: CompressionConfig) -> RuntimeSpec:
        return RuntimeSpec(kind="none")

    def activation_artifacts(self, config: CompressionConfig) -> List[GeneratedFile]:
        return []

    def health(self, config: CompressionConfig) -> dict:
        return {"ok": True, "detail": "compression disabled"}
