"""Shared filesystem locations (kept in one place for consistency)."""
from __future__ import annotations

import os
from pathlib import Path


def config_dir() -> Path:
    """mcpm's config dir — honours MCPM_CONFIG_DIR, else ~/.config/mcpm."""
    env = os.environ.get("MCPM_CONFIG_DIR")
    base = Path(env) if env else Path.home() / ".config" / "mcpm"
    base.mkdir(parents=True, exist_ok=True)
    return base


def compression_config_path() -> Path:
    return config_dir() / "compression.json"


def servers_json_path() -> Path:
    return config_dir() / "servers.json"
