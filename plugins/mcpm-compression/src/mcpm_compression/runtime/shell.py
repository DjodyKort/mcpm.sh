"""Generate a sourceable shell snippet that activates compression for a shell.

This is the portable activation path: source it from ~/.zshrc (or let the
hrclaude wrapper rely on the same env). It cannot inject env vars into an
already-running `claude` process — that's the documented hard boundary.
"""
from __future__ import annotations

from typing import Dict

from mcpm_compression.paths import config_dir

SHELL_SNIPPET_PATH = config_dir() / "compression-env.sh"


def shell_env_snippet(env: Dict[str, str]) -> str:
    lines = [
        "# Managed by `mcpm compression` — do not edit by hand.",
        "# Source from ~/.zshrc to route this shell's AI clients through the compressor.",
    ]
    for k, v in env.items():
        lines.append(f'export {k}="{v}"')
    return "\n".join(lines) + "\n"
