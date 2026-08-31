"""The single seam to the tokenade binary/runtime.

Every tokenade CLI touchpoint lives here, mirroring `headroom_runtime` — a version bump
or removal touches one file. Tokenade integrates fundamentally differently from headroom:
no API proxy, no port. `tokenade install` writes Claude Code hooks into settings.json
(tool-output folding sits *after* the cached prefix, so the prompt-cache prefix is never
rewritten) and wraps MCP client entries in `tokenade mcp-proxy`. We drive the vendor's
own install/uninstall/unwrap commands rather than reimplementing them; the one exception
is hook *removal* (`remove_hooks`), because the vendor's only removal path (`uninstall`)
also wipes ~/.tokenade data — too destructive for a plain `disable`.

Pinning: `==tokenade_version.pin` via `npm install -g @tokenade/cli@<pin>`. The vendor
also ships a 24h background self-updater; `updater_off` disables it at engage time —
an auto-updating binary is the track-latest failure with extra steps.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import urllib.request
from pathlib import Path
from typing import List, Optional, Tuple


class TokenadeUnavailable(RuntimeError):
    """The pinned tokenade build isn't callable."""


def _tokenade() -> Optional[str]:
    return shutil.which("tokenade")


def _run(args: List[str], timeout: int = 60) -> Tuple[bool, str]:
    """Run a tokenade subcommand; return (ok, detail). stdin is closed so the vendor's
    interactive prompts (rtk migration, CLAUDE.md append) take their defaults instead of
    hanging a non-interactive engage."""
    exe = _tokenade()
    if not exe:
        return (False, "tokenade not on PATH")
    try:
        res = subprocess.run([exe, *args], capture_output=True, timeout=timeout,
                             text=True, stdin=subprocess.DEVNULL)
        detail = (res.stdout or res.stderr or "").strip().splitlines()
        return (res.returncode == 0, detail[-1] if detail else "ok")
    except Exception as e:  # noqa: BLE001 — adapter boundary; surface, don't crash
        return (False, f"{e.__class__.__name__}: {e}")


def version() -> Optional[str]:
    """Diagnostic: installed `tokenade --version` (for the pin drift check)."""
    exe = _tokenade()
    if not exe:
        return None
    try:
        res = subprocess.run([exe, "--version"], capture_output=True, timeout=5, text=True)
        m = re.search(r"(\d+\.\d+\.\d+)", (res.stdout or "") + (res.stderr or ""))
        return m.group(1) if m else None
    except Exception:
        return None


def latest_version(package: str = "@tokenade/cli") -> Optional[str]:
    """The newest published version, from the npm registry (dist-tags.latest).

    Resolved *before* installing so the exact-pin invariant holds: we record and install
    `@<version>`, never a floating tag. None when the registry is unreachable, so the
    caller fails loud rather than guessing.
    """
    url = f"https://registry.npmjs.org/{package.replace('/', '%2f')}"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            v = (json.loads(r.read().decode()).get("dist-tags") or {}).get("latest")
        return str(v) if v else None
    except Exception:
        return None


def install(requirement: str) -> Tuple[bool, str, Optional[str], Optional[str]]:
    """Install an exact tokenade requirement (e.g. '@tokenade/cli@1.0.1').

    Returns (ok, detail, before, after). The platform binary arrives via npm
    optionalDependencies at the same version, so the CLI pin pins the engine too.
    """
    before = version()
    if not shutil.which("npm"):
        return (False, "npm not on PATH — install tokenade manually", before, before)
    try:
        res = subprocess.run(["npm", "install", "-g", requirement],
                             capture_output=True, timeout=600, text=True)
    except Exception as e:
        return (False, f"install failed ({e.__class__.__name__}: {e})", before, before)
    after = version()
    if res.returncode != 0:
        tail = (res.stderr or res.stdout or "").strip().splitlines()
        return (False, tail[-1] if tail else "npm install failed", before, after)
    if before == after:
        return (True, f"already at {after}", before, after)
    return (True, f"{before or 'none'} → {after}", before, after)


def vendor_install(agent: str = "claude-code", with_claude_md: bool = False) -> Tuple[bool, str]:
    """Engage: drive the vendor's own installer for one agent (idempotent per vendor).

    The CLAUDE.md block is opt-in (`with_claude_md`) because ~/.claude/CLAUDE.md is
    sync-generated on our machines — see TokenadeSettings.
    """
    args = ["install", "--only", agent]
    if with_claude_md:
        args.append("--with-claude-md")
    return _run(args, timeout=120)


def vendor_uninstall() -> Tuple[bool, str]:
    """Teardown: the vendor's full removal (undoes integration + wipes ~/.tokenade)."""
    return _run(["uninstall"], timeout=120)


def unwrap_mcps() -> Tuple[bool, str]:
    """Restore wrapped MCP client entries to their original form (vendor, idempotent)."""
    return _run(["unwrap-mcps"], timeout=60)


def updater_off() -> Tuple[bool, str]:
    """Disable the 24h background self-updater (sentinel at ~/.tokenade/auto-update-off)."""
    return _run(["upgrade", "--off"], timeout=30)


def updater_disabled() -> bool:
    return (Path.home() / ".tokenade" / "auto-update-off").exists()


def healthcheck() -> dict:
    """Diagnostic: `tokenade healthcheck --json` → {ok, detail, checks}."""
    exe = _tokenade()
    if not exe:
        return {"ok": False, "detail": "tokenade not on PATH"}
    try:
        res = subprocess.run([exe, "healthcheck", "--json"], capture_output=True,
                             timeout=30, text=True)
        checks = json.loads(res.stdout).get("checks", [])
    except Exception as e:
        return {"ok": False, "detail": f"healthcheck failed ({e.__class__.__name__})"}
    bad = [c for c in checks if c.get("status") not in ("ok", "info")]
    detail = ("; ".join(c.get("message", c.get("id", "?")) for c in bad)
              if bad else f"{len(checks)} checks ok")
    return {"ok": not bad, "detail": detail, "checks": checks}


def settings_path() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")) / "settings.json"


def _load_settings(path: Optional[Path] = None) -> Optional[dict]:
    p = path or settings_path()
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def _is_tokenade_hook(hook: dict) -> bool:
    return "tokenade" in str(hook.get("command", ""))


def hooks_present(path: Optional[Path] = None) -> bool:
    """Are tokenade's hooks live in Claude Code's settings? Local read, hot-path safe.

    This is the truthful 'engaged' signal for the launch ledger: hooks are global, so a
    session is optimized iff the hooks are present at launch — regardless of policy.
    """
    settings = _load_settings(path)
    if not settings:
        return False
    for groups in (settings.get("hooks") or {}).values():
        for group in groups or []:
            if any(_is_tokenade_hook(h) for h in group.get("hooks") or []):
                return True
    return False


def remove_hooks(path: Optional[Path] = None) -> Tuple[int, Optional[Path]]:
    """Strip tokenade's hook entries from settings.json; everything else is untouched.

    Backs the file up first (settings.json.tokenade-bak). Returns (removed, backup_path).
    This exists because the vendor's only removal command also wipes ~/.tokenade data —
    disproportionate for `disable`, which must stay cheap enough to be the kill switch.
    """
    p = path or settings_path()
    settings = _load_settings(p)
    if not settings:
        return (0, None)
    hooks = settings.get("hooks") or {}
    removed = 0
    for event in list(hooks):
        kept_groups = []
        for group in hooks[event] or []:
            entries = group.get("hooks") or []
            kept = [h for h in entries if not _is_tokenade_hook(h)]
            removed += len(entries) - len(kept)
            if kept or not entries:
                group["hooks"] = kept
                kept_groups.append(group)
        if kept_groups:
            hooks[event] = kept_groups
        else:
            del hooks[event]
    if not removed:
        return (0, None)
    backup = p.with_name(p.name + ".tokenade-bak")
    backup.write_text(p.read_text())
    p.write_text(json.dumps(settings, indent=2) + "\n")
    return (removed, backup)
