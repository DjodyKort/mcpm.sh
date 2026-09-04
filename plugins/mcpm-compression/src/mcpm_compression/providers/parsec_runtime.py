"""The single seam to parsec (Dasein Labs) and the `claude plugin` surface.

Every parsec CLI touchpoint lives here, so a parsec version bump touches one file — the
same rule `headroom_runtime` follows.

Parsec is not shaped like headroom, and the difference drives every decision below. It is a
**Claude Code plugin** carrying its own proxy, hooks, MCP server and session agent, and it
wires itself in *globally*: `parsec setup` writes `ANTHROPIC_BASE_URL` and a managed
`statusLine` into `~/.claude/settings.json`, so every `claude` session is routed — not only
the ones launched through a wrapper. headroom routes per launch. That is why the two are
mutually exclusive rather than composable (ARCHITECTURE.md, "Two engines, one endpoint").

Three consequences are encoded here:

- **State is read, never spawned.** Install state is in
  `~/.claude/plugins/installed_plugins.json`, on/off in `settings.json → enabledPlugins`,
  routing in `settings.json → env.ANTHROPIC_BASE_URL`. `apply()` runs on unrelated edits,
  so "is parsec active?" has to be a file read.
- **Off has two depths.** `claude plugin disable` is cheap and instantly reversible;
  `parsec uninstall` deletes `~/.parsec` (models, ledger, logs). Only `--teardown` reaches
  the second, and the measured savings ledger dies with it.
- **Routing is stripped before the plugin is disabled.** The `ANTHROPIC_BASE_URL` parsec
  wrote outlives the plugin that served it, and a settings.json pointing at a proxy nothing
  will start again breaks every `claude` session — compression or not. Order matters.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import urllib.request
from pathlib import Path
from typing import Optional, Tuple

PLUGIN_NAME = "parsec"
MARKETPLACE = "parsec-marketplace"
MARKETPLACE_URL = "https://github.com/daseinlabs/plugins"
PLUGIN_ID = f"{PLUGIN_NAME}@{MARKETPLACE}"

# The parsec build this adapter was verified against. Unlike headroom's pin this is not
# installed by us — parsec self-updates through the Claude Code marketplace — so it is a
# *contract marker*, reported on drift rather than enforced. Bumping it means re-reading
# the plugin manifest, hooks and skills for a changed integration surface.
CONTRACT_VERSION = "0.2.8"


def parsec_home() -> Path:
    return Path.home() / ".parsec"


def parsec_bin() -> Optional[str]:
    """The parsec binary: its stable install path first, then PATH.

    The installer guarantees `~/.parsec/bin/parsec` — the path its own skills and hooks
    probe — while a claude-only install may leave nothing on PATH at all.
    """
    stable = parsec_home() / "bin" / "parsec"
    if stable.is_file() and os.access(stable, os.X_OK):
        return str(stable)
    return shutil.which("parsec")


def claude_bin() -> Optional[str]:
    return shutil.which("claude")


def claude_settings_path() -> Path:
    return Path.home() / ".claude" / "settings.json"


def installed_plugins_path() -> Path:
    return Path.home() / ".claude" / "plugins" / "installed_plugins.json"


def _read_json(path: Path) -> dict:
    """Parse a JSON file, or `{}` for anything that isn't readable JSON.

    A malformed `settings.json` must not take the compression CLI down with it: every
    caller here is a diagnostic, and "unknown" degrades better than a traceback.
    """
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def plugin_installed() -> bool:
    plugins = _read_json(installed_plugins_path()).get("plugins") or {}
    return any(str(k).startswith(f"{PLUGIN_NAME}@") for k in plugins)


def plugin_enabled() -> bool:
    enabled = _read_json(claude_settings_path()).get("enabledPlugins") or {}
    return any(str(k).startswith(f"{PLUGIN_NAME}@") and v for k, v in enabled.items())


def routed_base_url() -> Optional[str]:
    """The `ANTHROPIC_BASE_URL` in `~/.claude/settings.json`, if any.

    This is the fact that matters most about parsec: while it is set, *every* claude
    session is routed through a local proxy, including ones started outside `mcpm
    compression run`. Ownership is not provable from the file — parsec writes the key but
    a user could have written the same key by hand — so callers report it, never assume it.
    """
    env = _read_json(claude_settings_path()).get("env") or {}
    url = env.get("ANTHROPIC_BASE_URL")
    return str(url) if url else None


def api_key_configured() -> bool:
    """Whether a `psc_…` key is in play — presence only, never the value.

    The key turns on dashboard reporting, which is the point at which measured savings
    leave the machine. Reading it here to display it would put a secret in CLI output and
    in this process's memory for no gain.
    """
    if os.environ.get("PARSEC_API_KEY"):
        return True
    return (parsec_home() / "credentials.json").exists()


def present() -> bool:
    """Has parsec touched this machine at all?

    The sweep in `sync.apply` asks this about every provider that is *not* selected, on
    every apply. It must therefore stay two `stat` calls — never a subprocess.
    """
    return parsec_home().exists() or plugin_installed()


def _run(exe: Optional[str], args: list, timeout: int = 120) -> Tuple[bool, str]:
    if not exe:
        return (False, "not on PATH")
    try:
        res = subprocess.run([exe, *args], capture_output=True, timeout=timeout, text=True)
    except (OSError, subprocess.SubprocessError) as e:
        return (False, f"{e.__class__.__name__}: {e}")
    out = ((res.stdout or "") + (res.stderr or "")).strip()
    return (res.returncode == 0, out or f"exit {res.returncode}")


def version() -> Optional[str]:
    ok, out = _run(parsec_bin(), ["--version"], timeout=10)
    if not ok:
        return None
    m = re.search(r"(\d+\.\d+\.\d+)", out)
    return m.group(1) if m else None


def proxy_health(base_url: str) -> dict:
    """`GET <base>/health` — the probe parsec's own uninstall path uses to prove a listener
    is its own before asking it to stop."""
    try:
        with urllib.request.urlopen(base_url.rstrip("/") + "/health", timeout=3) as r:
            body = json.loads(r.read().decode())
        return {"ok": True, "detail": f"proxy healthy at {base_url}", "body": body}
    except Exception as e:  # noqa: BLE001 — any failure means "not reachable", uniformly
        return {"ok": False, "detail": f"no proxy answering at {base_url} ({e.__class__.__name__})"}


# --- activation -------------------------------------------------------------------

def install_plugin() -> Tuple[bool, str]:
    """Add the marketplace and install the plugin (both idempotent-ish, per its installer).

    Deliberately *not* the `curl … | bash` one-liner. That script also offers to intercept
    Claude Desktop's TLS with mitmproxy and trust a CA in the System keychain — a sudo-level
    change to the whole machine that has nothing to do with routing Claude Code, and that
    mcpm has no business making on the user's behalf.
    """
    claude = claude_bin()
    if not claude:
        return (False, "claude CLI not on PATH — cannot install the parsec plugin")
    _run(claude, ["plugin", "marketplace", "add", MARKETPLACE_URL])  # tolerated: already added
    return _run(claude, ["plugin", "install", PLUGIN_ID])


def enable_plugin() -> Tuple[bool, str]:
    return _run(claude_bin(), ["plugin", "enable", PLUGIN_ID], timeout=60)


def disable_plugin() -> Tuple[bool, str]:
    return _run(claude_bin(), ["plugin", "disable", PLUGIN_ID], timeout=60)


def uninstall_plugin() -> Tuple[bool, str]:
    return _run(claude_bin(), ["plugin", "uninstall", PLUGIN_ID])


def strip_routing() -> Tuple[bool, str]:
    """`parsec disable` — drop the managed keys parsec wrote into `~/.claude/settings.json`.

    Must run while the binary still exists and *before* the plugin is disabled or removed:
    Claude Code has no plugin-uninstall lifecycle hook, so nothing else will ever come back
    to clear a stale `ANTHROPIC_BASE_URL`.
    """
    return _run(parsec_bin(), ["disable"], timeout=60)


def uninstall_data() -> Tuple[bool, str]:
    """`parsec uninstall` — strip managed keys, stop the proxy, delete `~/.parsec`.

    Destructive: the measured-savings ledger lives in there and is the only evidence of
    whether parsec paid for itself. Teardown-only.
    """
    return _run(parsec_bin(), ["uninstall"], timeout=120)
