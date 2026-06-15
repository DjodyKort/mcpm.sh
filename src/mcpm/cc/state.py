"""Read-only readers for Claude Code's on-disk plugin state.

These functions NEVER write. Mutations go through the ``claude plugin`` CLI
(:mod:`mcpm.cc.claude_cli`). The reads here are for status/diff rendering and for the
update check.

Note: ``ClaudeCodeManager`` hardcodes ``~/.claude.json`` (MCP servers) and does not honor
``CLAUDE_CONFIG_DIR``. Plugin state lives under the ``~/.claude`` *directory*, which this
module resolves itself (and which does respect ``CLAUDE_CONFIG_DIR``, like Claude Code).
"""

import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def claude_root(root: Optional[Path] = None) -> Path:
    """Resolve the ``~/.claude`` directory.

    Honors ``CLAUDE_CONFIG_DIR`` (as Claude Code itself does); ``root`` overrides
    everything for testability.
    """
    if root is not None:
        return Path(root)
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude").expanduser()


def _read_json(path: Path):
    """Read + parse a JSON file, tolerating missing files and malformed content.

    Mirrors the defensive read idiom in ``skills/transpilers/claude_code.py``: a missing
    or corrupt file yields ``None`` rather than raising.
    """
    try:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        logger.debug("Could not read %s: %s", path, exc)
        return None


def read_known_marketplaces(root: Optional[Path] = None) -> Dict[str, dict]:
    """Return ``~/.claude/plugins/known_marketplaces.json`` as an object keyed by name.

    Shape per entry: ``{"source": {...}, "installLocation": "...", "lastUpdated": "..."}``.
    Returns ``{}`` when the file is missing or unreadable.
    """
    data = _read_json(claude_root(root) / "plugins" / "known_marketplaces.json")
    if isinstance(data, dict):
        return {k: v for k, v in data.items() if isinstance(v, dict)}
    return {}


def read_blocklist(root: Optional[Path] = None) -> List[dict]:
    """Return the blocked-plugin entries from ``~/.claude/plugins/blocklist.json``.

    The file shape is ``{"fetchedAt": "...", "plugins": [{"plugin": "...", ...}]}``.
    Returns ``[]`` when missing/unreadable.
    """
    data = _read_json(claude_root(root) / "plugins" / "blocklist.json")
    if isinstance(data, dict) and isinstance(data.get("plugins"), list):
        return [item for item in data["plugins"] if isinstance(item, dict)]
    return []


def blocked_plugin_ids(root: Optional[Path] = None) -> set:
    """Return the set of ``plugin@marketplace`` identifiers that are blocklisted."""
    return {entry.get("plugin") for entry in read_blocklist(root) if entry.get("plugin")}


def read_settings_plugins(root: Optional[Path] = None) -> Tuple[Dict[str, bool], Dict[str, dict]]:
    """Return ``(enabledPlugins, extraKnownMarketplaces)`` from ``~/.claude/settings.json``.

    Both default to ``{}`` when the file or keys are absent.
    """
    data = _read_json(claude_root(root) / "settings.json")
    if not isinstance(data, dict):
        return {}, {}
    enabled = data.get("enabledPlugins")
    extra = data.get("extraKnownMarketplaces")
    return (
        enabled if isinstance(enabled, dict) else {},
        extra if isinstance(extra, dict) else {},
    )


def _entry_version(entry: dict) -> Optional[str]:
    """Best-effort "version" for a marketplace catalog plugin entry.

    Resolution order matches Claude Code's own (plugin.json wins at install time, but the
    catalog only exposes the marketplace entry): explicit ``version`` -> pinned ``sha``
    (short) -> ``ref`` (branch/tag). Returns ``None`` when nothing identifies a version.
    """
    if entry.get("version"):
        return str(entry["version"])
    source = entry.get("source")
    if isinstance(source, dict):
        if source.get("sha"):
            return str(source["sha"])[:12]
        if source.get("ref"):
            return str(source["ref"])
    return None


def read_marketplace_catalog_versions(root: Optional[Path] = None) -> Dict[Tuple[str, str], Optional[str]]:
    """Map ``(marketplace_name, plugin_name)`` -> catalog version string (best effort).

    Reads each known marketplace's ``.claude-plugin/marketplace.json`` from its
    ``installLocation``. Marketplaces with no readable catalog are skipped.
    """
    versions: Dict[Tuple[str, str], Optional[str]] = {}
    for mkt_name, meta in read_known_marketplaces(root).items():
        location = meta.get("installLocation")
        if not location:
            continue
        catalog = _read_json(Path(location) / ".claude-plugin" / "marketplace.json")
        if not isinstance(catalog, dict):
            continue
        for entry in catalog.get("plugins") or []:
            if not isinstance(entry, dict):
                continue
            pname = entry.get("name")
            if pname:
                versions[(mkt_name, pname)] = _entry_version(entry)
    return versions
