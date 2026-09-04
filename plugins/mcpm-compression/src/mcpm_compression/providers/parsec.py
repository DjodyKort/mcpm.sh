"""parsec provider — a Claude Code plugin that compresses at the hook + proxy layer.

Policy→runtime mapping only; every parsec/`claude plugin` call lives in `parsec_runtime`.

Parsec is the first provider that is not a thing mcpm starts. It is a Claude Code plugin
carrying its own proxy, hooks, MCP server (`scout`) and session agent, whose lifecycle
belongs to Claude Code. So this provider generates no artifacts and registers no MCP entry;
what it owns is the *switch* — installed, enabled, and routing — and reporting the truth
about what that switch is currently doing.

Three properties of parsec that this provider deliberately surfaces rather than hides:

- It routes **globally**. Its `ANTHROPIC_BASE_URL` lands in `~/.claude/settings.json`, so
  plain `claude` is routed too. headroom only ever routes a launch it wrapped. Selecting
  headroom while parsec's plugin is still enabled means the *hooks* keep firing on every
  Read and Bash regardless — which is why `apply()` disables non-selected providers instead
  of merely not-configuring them.
- It replaces the session agent (`settings.json → "agent": "parsec:code"`), so it changes
  how the model is told to work, not just how many tokens it is sent.
- Its scoring path is a **network service on every tier but Enterprise** — Pro sends chunk
  text and structural features, the free tier sends tokens unstored — so this is not
  something a price change can switch off. That is a policy question for the user, not a
  default this plugin can make quietly, so `health` reports whether a key is configured and
  never touches its value.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from ..provider import CompressionProvider, GeneratedFile, RuntimeSpec
from ..schema import CompressionConfig
from . import parsec_runtime as pr


class ParsecProvider(CompressionProvider):
    name = "parsec"

    def mcp_server_config(self, config: CompressionConfig) -> Optional[dict]:
        # The plugin ships its own `.mcp.json` (`scout`: repo_map/file_outline/find_symbol).
        # Registering a second copy through mcpm would give Claude Code two servers for one
        # binary and two sets of the same tools.
        return None

    def runtime_spec(self, config: CompressionConfig) -> RuntimeSpec:
        # No env: parsec's routing is a settings.json key it writes itself, not something a
        # launch wrapper can hand it. `port` is read back from that key so callers can see
        # the real one rather than a number we invented.
        return RuntimeSpec(kind="plugin", port=_routed_port() or 0, env={})

    def activation_artifacts(self, config: CompressionConfig) -> List[GeneratedFile]:
        # Nothing to generate: parsec owns its own wiring, and a second writer of the same
        # settings.json keys is how two tools end up fighting over one endpoint.
        return []

    def health(self, config: CompressionConfig) -> dict:
        installed, enabled = pr.plugin_installed(), pr.plugin_enabled()
        routed = pr.routed_base_url()
        v = pr.version()
        if not installed:
            detail = "plugin not installed — `mcpm compression enable --provider parsec`"
        elif not enabled:
            detail = f"plugin installed but disabled ({pr.PLUGIN_ID})"
        elif not routed:
            detail = "plugin enabled; no ANTHROPIC_BASE_URL in ~/.claude/settings.json yet " \
                     "(parsec writes it on its next session start)"
        else:
            detail = f"routing all claude sessions via {routed}"
        return {
            "ok": bool(installed and enabled and routed),
            "detail": detail,
            "version": v,
            "installed": installed,
            "enabled": enabled,
            "routed": routed,
            "api_key": pr.api_key_configured(),
            "proxy": pr.proxy_health(routed) if routed else None,
        }

    # --- the switch ---------------------------------------------------------------

    def activate(self, config: CompressionConfig) -> List[Tuple[bool, str]]:
        steps: List[Tuple[bool, str]] = []
        if not pr.plugin_installed():
            steps.append(_step("install parsec plugin", pr.install_plugin()))
            if not steps[-1][0]:
                return steps
        steps.append(_step(f"enable {pr.PLUGIN_ID}", pr.enable_plugin()))
        v = pr.version()
        if v and v != pr.CONTRACT_VERSION:
            # Reported, never enforced: parsec self-updates through the marketplace, so we
            # cannot hold a pin the way we hold headroom's. Drift still means the manifest,
            # hooks and skills this provider was written against may have moved.
            steps.append((True, (f"parsec {v} ≠ verified contract {pr.CONTRACT_VERSION} — "
                                 "re-check the plugin's hooks/manifest before trusting this wiring")))
        if not pr.api_key_configured():
            steps.append((True, ("no parsec API key configured — local savings ledger only, "
                                 "nothing reported to their dashboard (set one with /parsec:key)")))
        steps.append((True, ("restart claude to pick up routing — parsec writes "
                             "ANTHROPIC_BASE_URL into ~/.claude/settings.json on session start")))
        return steps

    def deactivate(self, config: CompressionConfig, *, teardown: bool = False) -> List[Tuple[bool, str]]:
        if not pr.present():
            return []
        steps = [_step("parsec disable (strip managed settings.json keys)", pr.strip_routing())]
        if teardown:
            # Order is load-bearing: the cleanup binary ships *inside* the plugin, so once
            # the plugin is gone nothing is left to strip routing or stop the proxy.
            steps.append(_step("parsec uninstall (stop proxy, delete ~/.parsec data)",
                               pr.uninstall_data()))
            steps.append(_step(f"claude plugin uninstall {pr.PLUGIN_ID}", pr.uninstall_plugin()))
        elif pr.plugin_enabled():
            steps.append(_step(f"claude plugin disable {pr.PLUGIN_ID}", pr.disable_plugin()))
        return steps


def _routed_port() -> Optional[int]:
    url = pr.routed_base_url()
    if not url:
        return None
    try:
        return int(url.rsplit(":", 1)[1].split("/")[0])
    except (IndexError, ValueError):
        return None


def _step(label: str, result: Tuple[bool, str]) -> Tuple[bool, str]:
    ok, detail = result
    return (ok, f"{label} — {detail}")
