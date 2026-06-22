"""Generate a sourceable shell snippet that activates compression for a shell.

This is the portable activation path: source it from ~/.zshrc (or let the
hrclaude wrapper rely on the same env). It cannot inject env vars into an
already-running `claude` process — that's the documented hard boundary.
"""
from __future__ import annotations

from typing import Dict

from mcpm_compression.paths import config_dir

SHELL_SNIPPET_PATH = config_dir() / "compression-env.sh"
SHIMS_PATH = config_dir() / "compression-shims.zsh"


def shell_env_snippet(env: Dict[str, str]) -> str:
    lines = [
        "# Managed by `mcpm compression` — do not edit by hand.",
        "# Source from ~/.zshrc to route this shell's AI clients through the compressor.",
    ]
    for k, v in env.items():
        lines.append(f'export {k}="{v}"')
    return "\n".join(lines) + "\n"


def shim_snippet() -> str:
    """Thin shell wrappers over `mcpm compression …`.

    All launch/lifecycle logic lives in Python; these are just short names.
    Replaces the hand-maintained ~/.config/headroom-aliases.zsh. A/B is now
    preset-driven (`mcpm compression use agent|interactive` + `proxy restart`).
    """
    return (
        "# Managed by `mcpm compression` — do not edit by hand.\n"
        "# Source from ~/.zshrc:  source ~/.config/mcpm/compression-shims.zsh\n"
        "# (replaces the old hand-maintained ~/.config/headroom-aliases.zsh)\n"
        "hrclaude() { mcpm compression run -- \"$@\"; }   # launch claude under the per-dir policy\n"
        "hrup()     { mcpm compression proxy up; }        # start the active-preset proxy\n"
        "hrdown()   { mcpm compression proxy down; }      # stop it\n"
        "hrrestart(){ mcpm compression proxy restart; }   # restart (apply a mode change)\n"
        "hrstat()   { mcpm compression status; }\n"
        "hrperf()   { headroom perf \"$@\"; }              # savings report (headroom passthrough)\n"
        "hrdash()   { open \"http://127.0.0.1:8787/dashboard\" 2>/dev/null || headroom perf; }\n"
    )
