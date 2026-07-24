"""Load/save the declarative ContextConfig."""
from __future__ import annotations

import json

from .paths import context_config_path
from .schema import ContextConfig


def load_config() -> ContextConfig:
    path = context_config_path()
    if not path.exists():
        return ContextConfig()
    try:
        return ContextConfig.model_validate_json(path.read_text())
    except Exception:
        # Corrupt/old config → fall back to defaults rather than crash the CLI.
        return ContextConfig()


def save_config(config: ContextConfig) -> None:
    path = context_config_path()
    path.write_text(json.dumps(config.model_dump(), indent=2) + "\n")
