"""Generate the sourceable shims (compression-shims style).

Two jobs:

1. **Freshness wrapper** (`wrap_default_claude`, default on): replace the
   default `claude()` — and `hrclaude()` when the compression shims define it —
   with a superset of cf-dev-tools' own wrapper: the org sync (their exact
   python call, their throttle cache) followed immediately by
   `mcpm context sync`, so union-restores and profile refreshes land in the
   same beat as cf's clobber. Requires the source line in ~/.zshrc to come
   AFTER cf's shell-wrapper.sh and compression-shims.zsh (doctor checks this).

2. **Profile shims**: one `claude-<profile>()` per profile. Env-prefix form
   (no export leak) and `command claude` so nested wrappers can't recurse.
"""
from __future__ import annotations

from typing import Dict

from .paths import profiles_root, shims_path
from .schema import ProfileSpec

_HEADER = (
    "# Managed by `mcpm context` — do not edit by hand.\n"
    "# Source from ~/.zshrc AFTER cf's shell-wrapper.sh and compression-shims.zsh:\n"
    "#   source ~/.config/mcpm/context-shims.zsh\n"
)

# cf's shell-wrapper.sh equivalent (same python entry points, same throttle
# cache) + our context sync. The doctor's cf-wrapper hash tripwire guards this
# copied contract; the upstream post-sync-hook proposal removes the need for it.
_PRESYNC = """\
_mcpm_context_presync() {
    local now; now=$(date +%s)
    local interval="${CLAUDE_SYNC_INTERVAL:-14400}"
    local cf_dir="${HOME}/.local/share/cf-dev-tools"
    local cf_cache="${HOME}/.claude/.last_auto_sync"
    local cf_ran=0
    if [[ -d "${cf_dir}/.git" && -x "${cf_dir}/.venv/bin/python" ]]; then
        local last=0
        [[ -f "$cf_cache" ]] && last=$(cat "$cf_cache" 2>/dev/null || echo 0)
        if (( now - last >= interval )); then
            git -C "$cf_dir" pull --quiet 2>/dev/null
            "${cf_dir}/.venv/bin/python" -c 'import sys; sys.path.insert(0, sys.argv[1]); from cfdevtools.claude import sync_claude_files, auto_update_mcp_repos; sync_claude_files(); auto_update_mcp_repos()' "$cf_dir" 2>/dev/null
            echo "$now" > "$cf_cache"
            cf_ran=1
        fi
    fi
    local ctx_cache="${HOME}/.cache/mcpm/context/.last_auto_sync"
    local ctx_last=0
    [[ -f "$ctx_cache" ]] && ctx_last=$(cat "$ctx_cache" 2>/dev/null || echo 0)
    if (( cf_ran )) || (( now - ctx_last >= interval )); then
        command mcpm context sync >/dev/null 2>&1
        mkdir -p "$(dirname "$ctx_cache")" 2>/dev/null
        echo "$now" > "$ctx_cache"
    fi
}

# Default claude = codeforward mode (org CLAUDE.md + personal/client layers).
claude() { _mcpm_context_presync; command claude "$@"; }

# hrclaude launches the claude BINARY via `mcpm compression run` (it never hits
# shell functions), so give daily hrclaude use the same freshness path.
if (( $+functions[hrclaude] )); then
    hrclaude() { _mcpm_context_presync; command mcpm compression run -- "$@"; }
fi
"""


def shim_snippet(profiles: Dict[str, ProfileSpec], wrap_default: bool = True) -> str:
    lines = [_HEADER]
    if wrap_default:
        lines.append(_PRESYNC)
    presync = "_mcpm_context_presync; " if wrap_default else ""
    for name in sorted(profiles):
        pdir = profiles_root() / name
        lines.append(f'claude-{name}() {{ {presync}CLAUDE_CONFIG_DIR="{pdir}" command claude "$@"; }}')
    return "\n".join(lines) + "\n"


def write_shims(profiles: Dict[str, ProfileSpec], wrap_default: bool = True) -> str:
    path = shims_path()
    path.write_text(shim_snippet(profiles, wrap_default))
    return str(path)


def remove_shims() -> bool:
    path = shims_path()
    if path.exists():
        path.unlink()
        return True
    return False
