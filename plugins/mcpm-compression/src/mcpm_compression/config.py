"""Load/save the declarative CompressionConfig."""
from __future__ import annotations

import json

from .paths import compression_config_path
from .schema import CompressionConfig


def load_config() -> CompressionConfig:
    path = compression_config_path()
    if not path.exists():
        return CompressionConfig()
    try:
        return CompressionConfig.model_validate_json(path.read_text())
    except Exception:
        # Corrupt/old config → fall back to disabled rather than crash the CLI.
        return CompressionConfig()


def save_config(config: CompressionConfig) -> None:
    path = compression_config_path()
    path.write_text(json.dumps(config.model_dump(), indent=2) + "\n")
