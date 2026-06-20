"""Apply / tear down the declarative compression config (idempotent)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List

from .config import save_config
from .mcp_presence import add_mcp_server, is_present, remove_mcp_server
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
    if persist:
        save_config(config)
        report.add(f"saved config (provider={config.provider})")

    provider = get_provider(config.provider)

    # 1. MCP presence (declarative; propagated later by `mcpm client sync`).
    desired = provider.mcp_server_config(config)
    if desired:
        try:
            add_mcp_server(desired)
            report.add(f"registered MCP server '{desired['name']}' in mcpm servers.json")
            report.add("run `mcpm client sync` to propagate to your clients")
        except Exception as e:  # noqa: BLE001 — surface, don't crash
            report.warn(f"MCP registration failed ({e.__class__.__name__}: {e})")
    else:
        if is_present(_MANAGED_MCP_NAME):
            try:
                remove_mcp_server(_MANAGED_MCP_NAME)
                report.add(f"removed MCP server '{_MANAGED_MCP_NAME}' (provider has none)")
            except Exception as e:  # noqa: BLE001
                report.warn(f"MCP removal failed ({e.__class__.__name__}: {e})")

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
