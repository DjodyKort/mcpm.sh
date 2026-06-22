"""The single seam to the headroom binary/runtime.

Every headroom CLI/HTTP touchpoint lives here so a version bump or a provider swap
touches one file (see ARCHITECTURE.md). The launch hot-path never calls into here —
these are config-time (snapshot) and diagnostic (health/version) operations only.

Contract is pinned to headroom 0.26.0. Undocumented commands (`agent-savings`) fall
back to a captured constant; `tests/fixtures/` asserts the constant matches the binary.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# The headroom version this adapter's contract was captured against.
PINNED_VERSION = "0.26.0"

# Captured from `headroom agent-savings --profile <p> --format json` on 0.26.0.
# Used when the (undocumented) command is unavailable. Kept in lock-step with
# tests/fixtures/agent_savings_*.json (test asserts equality).
_FALLBACK_PROFILE_ENV: Dict[str, Dict[str, str]] = {
    "agent-90": {
        "HEADROOM_ACCURACY_GUARD": "strict",
        "HEADROOM_COMPRESS_SYSTEM_MESSAGES": "1",
        "HEADROOM_COMPRESS_USER_MESSAGES": "1",
        "HEADROOM_FORCE_KOMPRESS": "1",
        "HEADROOM_MAX_ITEMS": "8",
        "HEADROOM_MIN_TOKENS": "120",
        "HEADROOM_MODE": "token",
        "HEADROOM_PROTECT_ANALYSIS_CONTEXT": "1",
        "HEADROOM_PROTECT_RECENT": "2",
        "HEADROOM_SAVINGS_PROFILE": "agent-90",
        "HEADROOM_SAVINGS_TARGET": "0.90",
        "HEADROOM_SMART_CRUSHER_COMPACTION": "0",
        "HEADROOM_TARGET_RATIO": "0.10",
    },
    "balanced": {
        "HEADROOM_ACCURACY_GUARD": "strict",
        "HEADROOM_COMPRESS_SYSTEM_MESSAGES": "0",
        "HEADROOM_COMPRESS_USER_MESSAGES": "0",
        "HEADROOM_FORCE_KOMPRESS": "0",
        "HEADROOM_MAX_ITEMS": "15",
        "HEADROOM_MIN_TOKENS": "250",
        "HEADROOM_MODE": "token",
        "HEADROOM_PROTECT_ANALYSIS_CONTEXT": "1",
        "HEADROOM_PROTECT_RECENT": "4",
        "HEADROOM_SAVINGS_PROFILE": "balanced",
        "HEADROOM_SAVINGS_TARGET": "0.70",
        "HEADROOM_SMART_CRUSHER_COMPACTION": "1",
        "HEADROOM_TARGET_RATIO": "0.30",
    },
}


def _headroom() -> Optional[str]:
    return shutil.which("headroom")


def snapshot_profile_env(profile: str) -> Dict[str, str]:
    """Config-time: resolve a savings profile to its HEADROOM_* env bundle.

    Prefers the live binary (`headroom agent-savings`); falls back to the captured
    constant so config writes still work when headroom isn't on PATH. Returns {} for
    an unknown profile with no fallback.
    """
    exe = _headroom()
    if exe:
        try:
            res = subprocess.run(
                [exe, "agent-savings", "--profile", profile, "--format", "json"],
                capture_output=True, timeout=10, text=True,
            )
            if res.returncode == 0 and res.stdout.strip():
                data = json.loads(res.stdout)
                return {str(k): str(v) for k, v in data.items()}
        except Exception:
            pass
    return dict(_FALLBACK_PROFILE_ENV.get(profile, {}))


def proxy_health(port: int) -> dict:
    """Diagnostic: GET /health on a proxy port (documented-stable endpoint)."""
    url = f"http://127.0.0.1:{port}/health"
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            body = json.loads(r.read().decode())
        return {
            "ok": bool(body.get("ready")),
            "detail": f"proxy {body.get('status', '?')} on :{port}",
            "version": body.get("version"),
            "config": body.get("config") or {},
            "port": port,
        }
    except Exception as e:
        return {"ok": False, "detail": f"proxy not reachable on :{port} ({e.__class__.__name__})", "port": port}


def _logs_dir() -> Path:
    d = Path.home() / ".headroom" / "logs"
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(Path.home() / ".headroom", 0o700)  # privacy: debug dumps live here
    except OSError:
        pass
    return d


def proxy_up(port: int, env: Dict[str, str], wait: int = 30) -> Tuple[bool, str]:
    """Ensure a headroom proxy is listening on `port` with `env`.

    Reuses an already-healthy proxy (mode is cold-start, so a running proxy is kept
    as-is). Otherwise spawns a detached `headroom proxy` (same pattern as mcpm's
    RouterRuntime) and polls /health until ready. `env` carries HEADROOM_MODE etc.
    """
    health = proxy_health(port)
    if health.get("ok"):
        return (True, f"reusing proxy on :{port}")
    exe = _headroom()
    if not exe:
        return (False, "headroom not on PATH")
    mode = env.get("HEADROOM_MODE", "cache")
    log = _logs_dir() / f"proxy.{port}.out"
    try:
        with open(log, "ab", 0) as out:
            subprocess.Popen(
                [exe, "proxy", "--port", str(port), "--mode", mode],
                env={**os.environ, **env},
                stdin=subprocess.DEVNULL, stdout=out, stderr=out,
                start_new_session=True, close_fds=True,
            )
    except Exception as e:
        return (False, f"spawn failed ({e.__class__.__name__}: {e})")
    for _ in range(wait):
        time.sleep(1)
        if proxy_health(port).get("ok"):
            return (True, f"started proxy on :{port} (mode={mode})")
    return (False, f"proxy on :{port} did not become ready in {wait}s (check {log})")


def proxy_down(port: int) -> Tuple[bool, str]:
    """Stop the proxy on `port`. Prefer the pid from /health; fall back to lsof."""
    pid = (proxy_health(port).get("config") or {}).get("pid")
    pids: List[int] = [int(pid)] if pid else []
    if not pids:
        try:
            res = subprocess.run(["lsof", "-nP", "-tiTCP:%d" % port, "-sTCP:LISTEN"],
                                 capture_output=True, timeout=5, text=True)
            pids = [int(x) for x in res.stdout.split()]
        except Exception:
            pids = []
    if not pids:
        return (False, f"no proxy listening on :{port}")
    stopped = []
    for p in pids:
        try:
            os.kill(p, signal.SIGTERM)
            stopped.append(p)
        except OSError:
            pass
    return (bool(stopped), f"stopped proxy on :{port} ({', '.join(map(str, stopped))})"
            if stopped else f"could not stop pid(s) {pids}")


def version() -> Optional[str]:
    """Diagnostic: installed `headroom --version` (for the doctor drift check)."""
    exe = _headroom()
    if not exe:
        return None
    try:
        res = subprocess.run([exe, "--version"], capture_output=True, timeout=5, text=True)
        m = re.search(r"(\d+\.\d+\.\d+)", (res.stdout or "") + (res.stderr or ""))
        return m.group(1) if m else None
    except Exception:
        return None


def _run(args: list, timeout: int = 30) -> tuple:
    """Run a headroom subcommand; return (ok, detail). No-op (ok=False) if headroom absent."""
    exe = _headroom()
    if not exe:
        return (False, "headroom not on PATH")
    try:
        res = subprocess.run([exe, *args], capture_output=True, timeout=timeout, text=True)
        detail = (res.stdout or res.stderr or "").strip().splitlines()
        return (res.returncode == 0, detail[-1] if detail else "ok")
    except Exception as e:
        return (False, f"{e.__class__.__name__}: {e}")


def mcp_uninstall() -> tuple:
    """Strip path: remove headroom's own MCP registration (documented, idempotent)."""
    return _run(["mcp", "uninstall"])


def unwrap(client: str = "claude") -> tuple:
    """Strip path: ledger-backed reversal of `headroom wrap` for a client."""
    return _run(["unwrap", client])
