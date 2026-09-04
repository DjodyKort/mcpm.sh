"""Headroom provider — maps compression *policy* (presets) to the headroom runtime.

All actual headroom CLI/HTTP calls live in `headroom_runtime` (the swappable seam);
this module is the thin policy→env mapping.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from ..provider import CompressionProvider, GeneratedFile, RuntimeSpec
from ..runtime import shell_env_snippet, shim_snippet
from ..runtime.shell import SHELL_SNIPPET_PATH, SHIMS_PATH
from ..schema import CompressionConfig, CompressionPreset
from ..versions import spec_matches
from .headroom_runtime import proxy_health


class HeadroomProvider(CompressionProvider):
    name = "headroom"

    def env_for_preset(self, config: CompressionConfig, preset: CompressionPreset) -> Dict[str, str]:
        """Build the launch env for a preset, against the pinned headroom build.

        Every declared knob whose `applies` range covers the pin is emitted with its literal
        value — including the offs. headroom seeds its own persona defaults into any knob it
        finds unset, so "declared false" must mean an explicit `0`, never an absent key:
        absence hands the knob back to the vendor.

        A knob is dropped only when its authored `applies` range excludes the pin. It is
        never dropped because the binary might not read it — emitting an unread knob is
        inert, while dropping a read one would silently change behaviour.
        """
        pin = config.provider_version.pin
        env: Dict[str, str] = {
            name: k.value for name, k in preset.knobs.items() if spec_matches(pin, k.applies)
        }
        env["ANTHROPIC_BASE_URL"] = f"http://127.0.0.1:{preset.port}"
        # ENABLE_TOOL_SEARCH: without it, a custom ANTHROPIC_BASE_URL makes Claude Code
        # eager-load every tool schema and balloon context (headroom #746). This is Claude
        # Code's own switch, not headroom's HEADROOM_TOOL_SEARCH.
        env["ENABLE_TOOL_SEARCH"] = "true"
        # mcpm owns mode and telemetry outright; they win over any snapshot value.
        env["HEADROOM_MODE"] = preset.mode
        env["HEADROOM_TELEMETRY"] = config.telemetry
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

    def deactivate(self, config: CompressionConfig, *, teardown: bool = False) -> List[Tuple[bool, str]]:
        """Non-teardown disengage is already done: no artifacts, no MCP entry, nothing routed.

        headroom only ever sees traffic a launch handed it, so removing the env snippet and
        the MCP registration (both in `apply`) is the whole of turning it off. `--teardown`
        additionally runs headroom's own documented removal.
        """
        if not teardown:
            return []
        from .headroom_runtime import mcp_uninstall, unwrap

        return [
            (ok, f"headroom mcp uninstall — {detail}") for ok, detail in [mcp_uninstall()]
        ] + [
            (ok, f"headroom unwrap claude — {detail}") for ok, detail in [unwrap("claude")]
        ]

    def health(self, config: CompressionConfig) -> dict:
        return proxy_health(config.preset_for().port)
