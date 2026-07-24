"""Shared filesystem locations.

Everything is a function (re-read per call) so tests can redirect via env vars
without import-order tricks:

- MCPM_CONFIG_DIR          → mcpm config dir (shared convention with mcpm core)
- MCPM_CONTEXT_CLAUDE_HOME → stand-in for ~/.claude
- MCPM_CONTEXT_CLAUDE_JSON → stand-in for ~/.claude.json
- MCPM_CONTEXT_CACHE_DIR   → stand-in for ~/.cache/mcpm/context
"""
from __future__ import annotations

import os
from pathlib import Path


def config_dir() -> Path:
    env = os.environ.get("MCPM_CONFIG_DIR")
    base = Path(env) if env else Path.home() / ".config" / "mcpm"
    base.mkdir(parents=True, exist_ok=True)
    return base


def context_config_path() -> Path:
    return config_dir() / "context.json"


def claude_home() -> Path:
    env = os.environ.get("MCPM_CONTEXT_CLAUDE_HOME")
    return Path(env) if env else Path.home() / ".claude"


def claude_json_path() -> Path:
    env = os.environ.get("MCPM_CONTEXT_CLAUDE_JSON")
    return Path(env) if env else Path.home() / ".claude.json"


def profiles_root() -> Path:
    return config_dir() / "claude-profiles"


def shims_path() -> Path:
    return config_dir() / "context-shims.zsh"


def cache_dir() -> Path:
    env = os.environ.get("MCPM_CONTEXT_CACHE_DIR")
    base = Path(env) if env else Path.home() / ".cache" / "mcpm" / "context"
    base.mkdir(parents=True, exist_ok=True)
    return base


def backups_dir() -> Path:
    d = cache_dir() / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def skills_repo_path() -> Path:
    """Canonical skills repo (layers live in its rules/ dir).

    Resolved from skills_sync.json's local_path — the same clone the skills
    pipeline transpiles from — so layers ride the existing sync/publish flow.
    """
    sync_cfg = config_dir() / "skills_sync.json"
    if sync_cfg.exists():
        try:
            import json

            local = json.loads(sync_cfg.read_text()).get("local_path")
            if local:
                return Path(local).expanduser()
        except Exception:
            pass
    return config_dir() / "skills_repo"


def cf_install_dir() -> Path:
    env = os.environ.get("MCPM_CONTEXT_CF_DIR")
    return Path(env) if env else Path.home() / ".local" / "share" / "cf-dev-tools"
