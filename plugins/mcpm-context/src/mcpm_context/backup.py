"""Timestamped file snapshots under ~/.cache/mcpm/context/backups/."""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from .paths import backups_dir


def snapshot(path: Path) -> Path | None:
    """Copy `path` into a timestamped backup dir; None when it doesn't exist."""
    if not path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest_dir = backups_dir() / stamp
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / path.name
    if dest.exists():  # same second, same basename → suffix
        dest = dest_dir / f"{path.stem}-{len(list(dest_dir.iterdir()))}{path.suffix}"
    shutil.copy2(path, dest)
    return dest
