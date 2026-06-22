"""Apply / tear down the declarative compression config (idempotent)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List

from .config import save_config
from .mcp_presence import (
    add_mcp_server,
    is_present,
    push_to_clients,
    remove_from_clients,
    remove_mcp_server,
)
from .providers import get_provider
from .runtime import launchd_plist_path
from .runtime.shell import SHELL_SNIPPET_PATH
from .schema import CompressionConfig

# Artifacts this plugin may have created — always cleanup targets on switch/disable.
_MANAGED_ARTIFACTS = [SHELL_SNIPPET_PATH, launchd_plist_path]
# The only MCP server entry this plugin owns.
_MANAGED_MCP_NAME = "headroom"


@dataclass
class ApplyReport:
    actions: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def add(self, msg: str) -> None:
        self.actions.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)


def _resolved_path(p):
    return p() if callable(p) else p


def _materialize_presets(config: CompressionConfig, report: ApplyReport) -> None:
    """Fill empty preset env snapshots from headroom (config-time only, never the launch
    path). Skipped entirely when no headroom routing is configured. Falls back to the
    captured constant when headroom isn't on PATH, so config writes never fail."""
    routes_headroom = config.provider == "headroom" or any(
        (rule.provider or config.provider) == "headroom" for rule in config.contexts
    )
    if not routes_headroom:
        return
    from .providers.headroom_runtime import snapshot_profile_env

    for name, preset in config.presets.items():
        if preset.savings_profile and not preset.env:
            preset.env = snapshot_profile_env(preset.savings_profile)
            if preset.env:
                report.add(f"snapshot preset '{name}' env (headroom profile '{preset.savings_profile}')")


def _remove_managed_artifacts(report: ApplyReport) -> None:
    for p in _MANAGED_ARTIFACTS:
        path = _resolved_path(p)
        if path.exists():
            try:
                path.unlink()
                report.add(f"removed artifact {path}")
            except OSError as e:
                report.warn(f"could not remove {path}: {e}")


def apply(config: CompressionConfig, *, persist: bool = True) -> ApplyReport:
    """Make the world match `config`. Safe to run repeatedly."""
    report = ApplyReport()
    _materialize_presets(config, report)  # config-time env snapshot, before persist
    if persist:
        save_config(config)
        report.add(f"saved config (provider={config.provider})")

    provider = get_provider(config.provider)

    # 1. MCP presence — register in mcpm AND propagate to the target clients.
    #    `mcpm client sync` only reconciles entries that already exist; it never
    #    adds new ones. So we push the entry ourselves (same effect as
    #    `mcpm client edit <client> --add-server`). This is what makes the whole
    #    flow declarative: no manual ~/.claude.json edit is ever required.
    desired = provider.mcp_server_config(config)
    if desired:
        try:
            add_mcp_server(desired)
            report.add(f"registered MCP server '{desired['name']}' in mcpm servers.json")
            pushed = push_to_clients(desired["name"], config.clients)
            if pushed:
                report.add(f"propagated {_MANAGED_MCP_NAME!r} to clients: {', '.join(pushed)}")
            else:
                report.warn(f"no installed target clients to propagate to (clients={config.clients})")
        except Exception as e:  # noqa: BLE001 — surface, don't crash
            report.warn(f"MCP registration failed ({e.__class__.__name__}: {e})")
    else:
        # Provider has no MCP server (rtk-only / none): tear it down everywhere.
        try:
            if is_present(_MANAGED_MCP_NAME):
                remove_mcp_server(_MANAGED_MCP_NAME)
                report.add(f"removed MCP server '{_MANAGED_MCP_NAME}' from mcpm servers.json")
            removed = remove_from_clients(_MANAGED_MCP_NAME)  # all clients
            if removed:
                report.add(f"removed {_MANAGED_MCP_NAME!r} from clients: {', '.join(removed)}")
        except Exception as e:  # noqa: BLE001
            report.warn(f"MCP teardown failed ({e.__class__.__name__}: {e})")

    # 2. Activation artifacts. Clear stale ones first, then write the current set.
    _remove_managed_artifacts(report)
    for art in provider.activation_artifacts(config):
        art.path.parent.mkdir(parents=True, exist_ok=True)
        art.path.write_text(art.content)
        os.chmod(art.path, art.mode)
        report.add(f"wrote {art.path}" + (f"  ({art.note})" if art.note else ""))

    return report


def disable() -> ApplyReport:
    """Tear down: provider=none, remove MCP entry + artifacts."""
    return apply(CompressionConfig(provider="none", runtime="none"))
