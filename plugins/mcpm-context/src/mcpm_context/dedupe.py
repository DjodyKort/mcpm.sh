"""Remove cf-dev-tools' legacy MCP entries from a Claude Code config file.

cf-dev-tools registers `context7`/`playwright` (and, interactively,
`codeforward-odoo`/`codeforward-typst`) under their bare names in
~/.claude.json via `claude mcp add`. mcpm manages the same servers as
`mcpm_<name>` entries, so the bare ones are dead duplicates. Only the manual
`cf-dev-tools sync-claude` path re-adds them (the 4-hourly auto-sync never
touches mcpServers), so a re-run of `mcpm context sync` after an org sync is
enough to reconverge.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List

from .backup import snapshot
from .schema import DedupePolicy


def plan_dedupe(claude_json: Path, policy: DedupePolicy) -> List[str]:
    """Legacy entry names that would be removed. Pure — no writes."""
    if not policy.enabled or not claude_json.exists():
        return []
    try:
        servers = json.loads(claude_json.read_text()).get("mcpServers", {})
    except (json.JSONDecodeError, OSError):
        return []
    return [
        name
        for name in policy.legacy_names
        if name in servers and (not policy.require_mcpm_twin or f"mcpm_{name}" in servers)
    ]


def apply_dedupe(claude_json: Path, policy: DedupePolicy, *, backup: bool = True) -> List[str]:
    """Remove planned legacy entries, preserving every other key byte-for-byte
    semantically (full JSON round-trip; only mcpServers.<legacy> keys change)."""
    removed = plan_dedupe(claude_json, policy)
    if not removed:
        return []
    if backup:
        snapshot(claude_json)
    data = json.loads(claude_json.read_text())
    for name in removed:
        data["mcpServers"].pop(name, None)
    claude_json.write_text(json.dumps(data, indent=2) + "\n")
    return removed
