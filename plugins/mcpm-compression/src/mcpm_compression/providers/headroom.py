"""Headroom provider — maps compression *policy* (presets) to the headroom runtime.

All actual headroom CLI/HTTP calls live in `headroom_runtime` (the swappable seam);
this module is the thin policy→env mapping.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from ..provider import CompressionProvider, GeneratedFile, RuntimeSpec
from ..runtime import shell_env_snippet, shim_snippet
from ..runtime.shell import SHELL_SNIPPET_PATH, SHIMS_PATH
from ..schema import CompressionConfig, CompressionPreset
from .headroom_runtime import proxy_health


class HeadroomProvider(CompressionProvider):
    name = "headroom"

    def env_for_preset(self, config: CompressionConfig, preset: CompressionPreset) -> Dict[str, str]:
        """Build the launch env for a preset: its HEADROOM_* snapshot plus the knobs
        mcpm owns. `preset.mode` is authoritative (overrides any mode in the snapshot)."""
        env: Dict[str, str] = dict(preset.env)
        env["ANTHROPIC_BASE_URL"] = f"http://127.0.0.1:{preset.port}"
        # ENABLE_TOOL_SEARCH: without it, a custom ANTHROPIC_BASE_URL makes Claude Code
        # eager-load every tool schema and balloon context (headroom #746).
        env["ENABLE_TOOL_SEARCH"] = "true"
        env["HEADROOM_MODE"] = preset.mode
        env["HEADROOM_TELEMETRY"] = config.telemetry
        if preset.intercept_tool_results:
            env["HEADROOM_INTERCEPT_ENABLED"] = "1"
        if preset.code_aware:
            env["HEADROOM_CODE_AWARE_ENABLED"] = "true"
        return env

    def mcp_server_config(self, config: CompressionConfig) -> Optional[dict]:
        return {
            "name": "headroom",
            "command": "headroom",
            "args": ["mcp", "serve"],
            "proxy_mode": "direct",
        }

    def runtime_spec(self, config: CompressionConfig) -> RuntimeSpec:
        preset = config.preset_for()
        return RuntimeSpec(kind="proxy", port=preset.port, env=self.env_for_preset(config, preset))

    def activation_artifacts(self, config: CompressionConfig) -> List[GeneratedFile]:
        # Only the sourceable shell snippet for the active preset. Proxy lifecycle is
        # on-demand via the wrapper (no hand-rolled launchd plist); the wrapper reads
        # the per-cwd env from `mcpm compression env`.
        env = self.env_for_preset(config, config.preset_for())
        return [
            GeneratedFile(
                path=SHELL_SNIPPET_PATH,
                content=shell_env_snippet(env),
                mode=0o600,
                note="source from ~/.zshrc to route this shell's AI clients (active preset)",
            ),
            GeneratedFile(
                path=SHIMS_PATH,
                content=shim_snippet(),
                mode=0o644,
                note="source from ~/.zshrc for hrclaude/hrup/hrdown/hrstat (replaces headroom-aliases.zsh)",
            ),
        ]

    def health(self, config: CompressionConfig) -> dict:
        return proxy_health(config.preset_for().port)
