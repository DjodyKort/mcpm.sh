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
from .providers import get_provider, provider_names
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
    """Fill empty preset knob snapshots from the pinned headroom build (config-time only,
    never the launch path). Skipped entirely when no headroom routing is configured.

    Only fills what is empty — an existing snapshot is never silently rewritten here, since
    `apply` runs on unrelated edits. Re-snapshotting is an explicit act (`presets --refresh`)
    so a knob change always has a diff and a decision behind it.
    """
    routes_headroom = config.provider == "headroom" or any(
        (rule.provider or config.provider) == "headroom" for rule in config.contexts
    )
    if not routes_headroom:
        return
    from .providers.headroom_runtime import HeadroomUnavailable, snapshot_profile_env, version
    from .schema import KnobSpec

    for name, preset in config.presets.items():
        if not preset.savings_profile or preset.knobs:
            continue
        try:
            env = snapshot_profile_env(preset.savings_profile)
        except HeadroomUnavailable as e:
            # No fallback constant by design: guessing is what let one preset name mean two
            # different runtimes depending on whether the binary was on PATH.
            report.warn(f"preset '{name}': {e}")
            continue
        preset.knobs = {k: KnobSpec(value=v, source="profile") for k, v in env.items()}
        preset.snapshot_version = version()
        report.add(f"snapshot preset '{name}' knobs from headroom {preset.snapshot_version} "
                   f"(profile '{preset.savings_profile}')")


def _remove_managed_artifacts(report: ApplyReport) -> None:
    for p in _MANAGED_ARTIFACTS:
        path = _resolved_path(p)
        if path.exists():
            try:
                path.unlink()
                report.add(f"removed artifact {path}")
            except OSError as e:
                report.warn(f"could not remove {path}: {e}")


def _selected(config: CompressionConfig) -> set:
    """Providers this policy can route to: the global one plus any named by a context rule.

    A context rule counts as selection for the *sweep* but not for activation. Turning a
    provider off because one directory rule mentions it would break that rule; installing a
    Claude Code plugin because one directory rule mentions it is a machine-wide side effect
    no per-directory setting should have. So rules protect, and only the global provider
    engages.
    """
    return {config.provider} | {r.provider for r in config.contexts if r.provider}


def _switch_providers(config: CompressionConfig, report: ApplyReport, *, teardown: bool) -> None:
    """Engage the selected provider and disengage every provider that isn't selected.

    The sweep exists because parsec engages itself: its hooks run on every Read and Bash
    from the moment its plugin is enabled, whatever `compression.json` says. Without this,
    `set-provider headroom` would leave parsec's hooks firing underneath headroom's proxy
    and neither number would mean anything. Providers that cannot self-engage inherit a
    no-op `deactivate`, so this is free for them.
    """
    keep = _selected(config)
    for ok, detail in get_provider(config.provider).activate(config):
        (report.add if ok else report.warn)(detail)
    for name in provider_names():
        if name in keep:
            continue
        for ok, detail in get_provider(name).deactivate(config, teardown=teardown):
            (report.add if ok else report.warn)(detail)


def apply(config: CompressionConfig, *, persist: bool = True, teardown: bool = False) -> ApplyReport:
    """Make the world match `config`. Safe to run repeatedly.

    `teardown` is the destructive depth for the providers being switched off (their own
    data, not just our wiring). Only `disable --teardown` sets it.
    """
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

    # 3. Providers that run themselves: engage the selected one, disengage the rest.
    _switch_providers(config, report, teardown=teardown)

    return report


def disable(*, teardown: bool = False) -> ApplyReport:
    """Tear down: provider=none, remove MCP entry + artifacts.

    `teardown` additionally runs each provider's own removal (headroom's `mcp uninstall` +
    `unwrap`, parsec's `uninstall` + plugin removal).
    """
    return apply(CompressionConfig(provider="none", runtime="none"), teardown=teardown)
