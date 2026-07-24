"""Load/save the declarative CompressionConfig."""
from __future__ import annotations

import json
from typing import List, Tuple

from .migrate import migrate_raw
from .paths import compression_config_path
from .schema import CompressionConfig


def load_config_verbose() -> Tuple[CompressionConfig, List[str]]:
    """Load the policy, migrating the on-disk shape. Returns (config, migration notes).

    Migration is write-on-read: the normalised shape is persisted immediately, so it runs
    once rather than re-deriving (and re-announcing) itself on every command. A failed
    write is not fatal — the in-memory config is still correct, and the next writer will
    persist it.
    """
    path = compression_config_path()
    if not path.exists():
        return CompressionConfig(), []
    try:
        raw = json.loads(path.read_text())
    except Exception:
        # Corrupt config → disabled rather than crashing the CLI.
        return CompressionConfig(), []
    try:
        migrated, notes = migrate_raw(raw)
        config = CompressionConfig.model_validate(migrated)
    except Exception:
        return CompressionConfig(), []
    if notes:
        try:
            save_config(config)
        except OSError:
            pass
    return config, notes


def load_config() -> CompressionConfig:
    return load_config_verbose()[0]


def save_config(config: CompressionConfig) -> None:
    path = compression_config_path()
    path.write_text(json.dumps(config.model_dump(), indent=2) + "\n")
