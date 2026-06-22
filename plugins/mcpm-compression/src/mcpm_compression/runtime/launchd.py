"""Legacy launchd plist location.

We no longer *generate* a hand-rolled plist — proxy lifecycle is on-demand via the
shell wrapper (and, if you want always-on, headroom's own `headroom install`). These
identifiers remain only so `disable`/`sync` can clean up a plist left by an older
version (see ARCHITECTURE.md). Removing this file's plist renderer is intentional.
"""
from __future__ import annotations

from pathlib import Path

LAUNCHD_LABEL = "sh.mcpm.compression.proxy"


def launchd_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"
