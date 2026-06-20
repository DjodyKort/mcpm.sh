"""Manage the provider's MCP server PRESENCE via mcpm's own registry.

Mutations go through mcpm's GlobalConfigManager (the official API). Presence
checks read servers.json directly (a documented, stable file) so `status` works
even if internal APIs shift.
"""
from __future__ import annotations

import json
from typing import Optional

from .paths import servers_json_path


def add_mcp_server(server_kwargs: dict) -> bool:
    """Add/overwrite an MCP server entry in mcpm's canonical servers.json."""
    from mcpm.core.schema import STDIOServerConfig
    from mcpm.global_config import GlobalConfigManager

    sc = STDIOServerConfig(**server_kwargs)
    return GlobalConfigManager().add_server(sc, force=True)


def remove_mcp_server(name: str) -> bool:
    from mcpm.global_config import GlobalConfigManager

    return GlobalConfigManager().remove_server(name)


def is_present(name: str) -> bool:
    path = servers_json_path()
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text())
    except Exception:
        return False
    # servers.json is a flat {name: config} dict.
    return name in (data if isinstance(data, dict) else {})


def present_entry(name: str) -> Optional[dict]:
    path = servers_json_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except Exception:
        return None
    return data.get(name) if isinstance(data, dict) else None
