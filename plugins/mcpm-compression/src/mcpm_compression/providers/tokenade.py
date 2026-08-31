"""Tokenade provider — hook-based token optimizer (no API proxy, no port).

Policy→runtime mapping only; every vendor CLI call lives in `tokenade_runtime`.

Unlike headroom, engagement is *global*: the hooks in Claude Code's settings.json apply
to every session, however launched. Consequences the CLI surfaces:
- per-directory context rules cannot exempt a launch (no per-process env to withhold);
- the kill switch is `disable` (hook removal), not a per-launch routing refusal;
- A/B against baseline is time-sliced (enable vs disable periods), not per-launch.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from ..provider import CompressionProvider, GeneratedFile, RuntimeSpec
from ..runtime import shim_snippet
from ..runtime.shell import SHIMS_PATH
from ..schema import CompressionConfig
from . import tokenade_runtime as tk


class TokenadeProvider(CompressionProvider):
    name = "tokenade"

    def mcp_server_config(self, config: CompressionConfig) -> Optional[dict]:
        # Deliberately none. Tokenade's MCP presence would be the mcp-proxy *wrap* of
        # existing entries, which the pilot posture keeps off (TokenadeSettings.mcp_wrap).
        return None

    def runtime_spec(self, config: CompressionConfig) -> RuntimeSpec:
        return RuntimeSpec(kind="hook")

    def activation_artifacts(self, config: CompressionConfig) -> List[GeneratedFile]:
        # The vendor owns its hooks (written by `tokenade install`, driven from engage()).
        # We only keep the launch shims so `hrclaude` keeps feeding the attribution ledger.
        return [
            GeneratedFile(
                path=SHIMS_PATH,
                content=shim_snippet(),
                mode=0o644,
                note="source from ~/.zshrc for hrclaude/hrstat (launch via the ledger)",
            ),
        ]

    def health(self, config: CompressionConfig) -> dict:
        live = tk.version()
        if not live:
            return {"ok": False, "detail": "tokenade not on PATH "
                    f"(npm install -g {config.tokenade_version.requirement()})"}
        if not tk.hooks_present():
            return {"ok": False, "version": live,
                    "detail": "binary present but hooks not installed — run "
                              "`mcpm compression enable --provider tokenade`"}
        hc = tk.healthcheck()
        return {"ok": hc.get("ok", False), "version": live,
                "detail": f"hooks live; {hc.get('detail', '')}"}

    def engage(self, config: CompressionConfig) -> Tuple[List[str], List[str]]:
        """Drive the vendor installer under the pilot posture. Returns (actions, warnings).

        Refuses on pin drift — engaging writes the *installed* build's hooks into every
        future session, so an unverified build must not be engaged silently.
        """
        actions: List[str] = []
        warnings: List[str] = []
        pin = config.tokenade_version.pin
        live = tk.version()
        if not live:
            warnings.append("tokenade not on PATH — install the pin first: "
                            "mcpm compression pin --install")
            return (actions, warnings)
        if live != pin:
            warnings.append(f"installed {live} ≠ pin {pin} — not engaging an unverified "
                            "build; fix: mcpm compression pin --install")
            return (actions, warnings)

        ok, detail = tk.vendor_install(with_claude_md=config.tokenade.claude_md)
        (actions if ok else warnings).append(f"tokenade install — {detail}")
        if not ok:
            return (actions, warnings)

        if not config.tokenade.mcp_wrap:
            ok, detail = tk.unwrap_mcps()
            (actions if ok else warnings).append(
                f"unwrapped MCP entries (policy: mcp_wrap off; hooks still fold MCP "
                f"results) — {detail}")

        ok, detail = tk.updater_off()
        (actions if ok else warnings).append(f"background self-updater off — {detail}")

        if tk.hooks_present():
            actions.append("hooks live in Claude Code settings.json (global — every "
                           "session is optimized until `disable`)")
        else:
            warnings.append("vendor install ran but no tokenade hooks found in "
                            "settings.json — inspect `tokenade install --dry-run`")
        return (actions, warnings)

    def disengage(self, config: CompressionConfig) -> Tuple[List[str], List[str]]:
        """Undo integration, keep vendor data. (`disable --teardown` does full removal.)"""
        actions: List[str] = []
        warnings: List[str] = []
        ok, detail = tk.unwrap_mcps()
        (actions if ok else warnings).append(f"unwrap MCP entries — {detail}")
        removed, backup = tk.remove_hooks()
        if removed:
            actions.append(f"removed {removed} tokenade hook entr{'y' if removed == 1 else 'ies'} "
                           f"from settings.json (backup: {backup})")
        else:
            actions.append("no tokenade hooks in settings.json")
        return (actions, warnings)
