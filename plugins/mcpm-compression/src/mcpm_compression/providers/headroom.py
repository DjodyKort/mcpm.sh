"""Headroom provider — proxy (compresses everything) + MCP retrieve/stats tools."""
from __future__ import annotations

import json
import shutil
import urllib.request
from typing import List, Optional

from ..provider import CompressionProvider, GeneratedFile, RuntimeSpec
from ..runtime import launchd_plist, launchd_plist_path, shell_env_snippet
from ..runtime.shell import SHELL_SNIPPET_PATH
from ..schema import CompressionConfig


class HeadroomProvider(CompressionProvider):
    name = "headroom"

    def _env(self, config: CompressionConfig) -> dict:
        # ENABLE_TOOL_SEARCH: without it, a custom ANTHROPIC_BASE_URL makes Claude
        # Code eager-load every tool schema and balloon context (headroom #746).
        return {
            "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{config.port}",
            "ENABLE_TOOL_SEARCH": "true",
            "HEADROOM_TELEMETRY": config.telemetry,
        }

    def mcp_server_config(self, config: CompressionConfig) -> Optional[dict]:
        return {
            "name": "headroom",
            "command": "headroom",
            "args": ["mcp", "serve"],
            "proxy_mode": "direct",
        }

    def runtime_spec(self, config: CompressionConfig) -> RuntimeSpec:
        return RuntimeSpec(kind="proxy", port=config.port, env=self._env(config))

    def activation_artifacts(self, config: CompressionConfig) -> List[GeneratedFile]:
        env = self._env(config)
        proxy_bin = shutil.which("headroom") or "headroom"
        plist = launchd_plist(
            program_args=[proxy_bin, "proxy", "--port", str(config.port)],
            env={"HEADROOM_TELEMETRY": config.telemetry},
        )
        return [
            GeneratedFile(
                path=SHELL_SNIPPET_PATH,
                content=shell_env_snippet(env),
                mode=0o600,
                note="source from ~/.zshrc to compress this shell's AI clients",
            ),
            GeneratedFile(
                path=launchd_plist_path(),
                content=plist,
                mode=0o644,
                note="launchctl load -w <path> to keep the proxy always warm",
            ),
        ]

    def health(self, config: CompressionConfig) -> dict:
        url = f"http://127.0.0.1:{config.port}/health"
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                body = json.loads(r.read().decode())
            status = body.get("status", "?")
            return {"ok": bool(body.get("ready")), "detail": f"proxy {status} on :{config.port}",
                    "version": body.get("version"), "port": config.port}
        except Exception as e:
            return {"ok": False, "detail": f"proxy not reachable on :{config.port} ({e.__class__.__name__})",
                    "port": config.port}
