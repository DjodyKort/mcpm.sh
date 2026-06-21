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


# ---------------------------------------------------------------------------
# Client-side presence. mcpm writes managed entries under a `mcpm_` prefix and
# `mcpm client sync` only RECONCILES entries that already exist — it never adds
# new ones. So the plugin pushes the entry itself (same effect as
# `mcpm client edit <client> --add-server <name>`), which is what makes
# `mcpm compression enable` end-to-end with zero manual ~/.claude.json edits.
# ---------------------------------------------------------------------------

_MCPM_PREFIX = "mcpm_"


def _prefixed(name: str) -> str:
    return f"{_MCPM_PREFIX}{name}"


def _target_client_managers(clients: Optional[list] = None):
    """Yield (client_key, manager) for installed clients (optionally filtered)."""
    from mcpm.clients.client_registry import ClientRegistry

    installed = {k for k, ok in ClientRegistry.detect_installed_clients().items() if ok}
    wanted = (set(clients) & installed) if clients else installed
    for client_key in sorted(wanted):
        mgr = ClientRegistry.get_client_manager(client_key)
        if mgr is not None:
            yield client_key, mgr


def push_to_clients(name: str, clients: Optional[list] = None) -> list:
    """Write `mcpm_<name>` into each target client's config.

    Body comes from `to_client_format(registered)` so it honours the server's
    resolved proxy_mode (a `direct` stdio server yields the raw command, not a
    double-wrapped `mcpm run`). Returns the client keys that were written.
    """
    from mcpm.global_config import GlobalConfigManager

    registered = GlobalConfigManager().get_server(name)
    pushed = []
    for client_key, mgr in _target_client_managers(clients):
        if registered is None:
            body = {"command": "mcpm", "args": ["run", name]}
        else:
            body = mgr.to_client_format(registered)
        config = mgr._load_config()
        section = getattr(mgr, "configure_key_name", "mcpServers")
        config.setdefault(section, {})[_prefixed(name)] = body
        if mgr._save_config(config):
            pushed.append(client_key)
    return pushed


def remove_from_clients(name: str, clients: Optional[list] = None) -> list:
    """Strip `mcpm_<name>` from each target client's config (default: all)."""
    removed = []
    for client_key, mgr in _target_client_managers(clients):
        config = mgr._load_config()
        section = getattr(mgr, "configure_key_name", "mcpServers")
        servers = config.get(section, {})
        if _prefixed(name) in servers:
            del servers[_prefixed(name)]
            if mgr._save_config(config):
                removed.append(client_key)
    return removed


def in_client(name: str, clients: Optional[list] = None) -> list:
    """Return target clients whose config currently has `mcpm_<name>`."""
    present = []
    for client_key, mgr in _target_client_managers(clients):
        section = getattr(mgr, "configure_key_name", "mcpServers")
        if _prefixed(name) in (mgr._load_config().get(section, {}) or {}):
            present.append(client_key)
    return present
