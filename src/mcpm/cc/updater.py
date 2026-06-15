"""Check for and apply Claude Code plugin updates.

Mirrors the shape of :mod:`mcpm.core.updater` (the MCP-server updater): dataclass results
and a strict **never-raises** convention -- all failures are returned in ``.error`` rather
than thrown, so callers can render them in a table.

Update-availability detection is best-effort. ``claude plugin list --json`` and the
marketplace catalog do not always expose comparable versions; when they don't, a plugin is
reported as "unknown" and the user can update it explicitly (``claude plugin update`` is
idempotent).
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from mcpm.cc import claude_cli, state

logger = logging.getLogger(__name__)


# ---- Check ----


@dataclass
class CcUpdateCheck:
    """Result of checking a single installed plugin for updates."""

    name: str
    marketplace: Optional[str] = None
    can_update: bool = False
    # Human-readable summary, e.g. "v1 -> v2", "up to date", or "version unknown".
    summary: Optional[str] = None
    current_version: Optional[str] = None
    latest_version: Optional[str] = None
    enabled: bool = True
    blocked: bool = False
    error: Optional[str] = None

    @property
    def plugin_id(self) -> str:
        """The ``plugin@marketplace`` identifier used by the ``claude`` CLI."""
        return f"{self.name}@{self.marketplace}" if self.marketplace else self.name


@dataclass
class CcCheckResult:
    """Outcome of a check pass: per-plugin checks plus any catalog-refresh error."""

    checks: List[CcUpdateCheck] = field(default_factory=list)
    refresh_error: Optional[str] = None


def _installed_fields(entry: dict) -> tuple:
    """Extract ``(name, marketplace, version, enabled)`` from a list entry, tolerantly.

    ``claude plugin list --json`` field names vary across CLI versions, so each is looked
    up under a few likely aliases and defaults to ``None``/``True`` when absent.
    """
    name = entry.get("name") or entry.get("plugin") or entry.get("id")
    marketplace = entry.get("marketplace") or entry.get("marketplaceName") or entry.get("source")
    version = entry.get("version") or entry.get("installedVersion")
    enabled = entry.get("enabled")
    return (
        name,
        marketplace if isinstance(marketplace, str) else None,
        str(version) if version is not None else None,
        True if enabled is None else bool(enabled),
    )


def check_plugin_updates(
    plugin: Optional[str] = None,
    marketplace: Optional[str] = None,
    refresh: bool = True,
) -> CcCheckResult:
    """Check installed plugins for available updates.

    Args:
        plugin: Restrict to a single plugin name (matches the ``name`` field).
        marketplace: Restrict to plugins from one marketplace, and scope the catalog
            refresh to it.
        refresh: When True, run ``claude plugin marketplace update`` first (the
            "pull latest from remote" step).
    """
    result = CcCheckResult()

    if refresh:
        rc, _out, err = claude_cli.marketplace_update(marketplace)
        if rc != 0:
            result.refresh_error = err.strip() or f"marketplace update exited {rc}"

    catalog_versions = state.read_marketplace_catalog_versions()
    enabled_map, _extra = state.read_settings_plugins()
    blocked = state.blocked_plugin_ids()

    for entry in claude_cli.plugin_list_json():
        name, mkt, current, enabled = _installed_fields(entry)
        if not name:
            continue
        if plugin and name != plugin:
            continue
        if marketplace and mkt != marketplace:
            continue

        check = CcUpdateCheck(name=name, marketplace=mkt, current_version=current)
        # enabledPlugins (keyed "name@marketplace") is authoritative over the list flag.
        check.enabled = enabled_map.get(check.plugin_id, enabled)
        check.blocked = check.plugin_id in blocked

        latest = catalog_versions.get((mkt, name)) if mkt else None
        check.latest_version = latest

        if current and latest:
            if current != latest:
                check.can_update = True
                check.summary = f"{current} -> {latest}"
            else:
                check.summary = "up to date"
        else:
            # Not enough info to compare; apply is idempotent so the user can still update.
            check.summary = "version unknown"

        result.checks.append(check)

    return result


# ---- Apply ----


@dataclass
class CcUpdateApply:
    """Result of applying an update to a single plugin."""

    name: str
    updated: bool
    message: str = ""
    error: Optional[str] = None
    restart_required: bool = False


def apply_plugin_update(plugin: str) -> CcUpdateApply:
    """Update one plugin via ``claude plugin update <plugin>``.

    ``plugin`` may be a bare name or ``name@marketplace``. Never raises.
    """
    rc, stdout, stderr = claude_cli.plugin_update(plugin)
    out = (stdout or "").strip()
    err = (stderr or "").strip()
    combined = f"{out}\n{err}".lower()

    if rc != 0:
        return CcUpdateApply(name=plugin, updated=False, message=out, error=err or f"exited {rc}")

    # A successful, no-op update (already current) needs no restart.
    no_op = any(phrase in combined for phrase in ("up to date", "already", "no update"))
    updated = not no_op
    return CcUpdateApply(
        name=plugin,
        updated=updated,
        message=out or "updated",
        restart_required=updated,
    )
