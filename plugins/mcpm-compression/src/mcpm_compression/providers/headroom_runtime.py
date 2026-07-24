"""The single seam to the headroom binary/runtime.

Every headroom CLI/HTTP touchpoint lives here so a version bump or a provider swap
touches one file (see ARCHITECTURE.md). The launch hot-path never calls into here —
these are config-time (snapshot) and diagnostic (health/version) operations only.

We pin exactly (`==provider_version.pin`), never a floor. headroom ships ~2 releases/week
and 0.30 began seeding a default persona into any unset knob, so a floating constraint
rewrites the runtime without touching the config. `mcpm compression update --to X --accept`
is the only path that moves the pin.

There is deliberately no offline fallback for the profile snapshot. A bundled constant
means one preset name resolves to two different runtimes depending on whether the binary
is on PATH — exactly the drift this module exists to prevent. With an exact pin, a missing
binary is a condition worth surfacing, not papering over.
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


class HeadroomUnavailable(RuntimeError):
    """The pinned headroom build isn't callable, so no truthful snapshot is possible."""


def _headroom() -> Optional[str]:
    return shutil.which("headroom")


def snapshot_profile_env(profile: str) -> Dict[str, str]:
    """Config-time: resolve a savings profile to its HEADROOM_* env bundle.

    Runs `headroom agent-savings --profile <p> --format json` against the installed build.
    Raises rather than guessing: a snapshot is a factual claim about one specific binary,
    and inventing one is how the config came to describe a version nobody was running.
    """
    exe = _headroom()
    if not exe:
        raise HeadroomUnavailable(
            "headroom is not on PATH — cannot snapshot profile env. "
            "Install the pinned build: mcpm compression pin --install"
        )
    try:
        res = subprocess.run(
            [exe, "agent-savings", "--profile", profile, "--format", "json"],
            capture_output=True, timeout=10, text=True,
        )
    except Exception as e:
        raise HeadroomUnavailable(f"headroom agent-savings failed ({e.__class__.__name__}: {e})")
    if res.returncode != 0 or not res.stdout.strip():
        tail = (res.stderr or res.stdout or "").strip().splitlines()
        raise HeadroomUnavailable(
            f"headroom agent-savings --profile {profile}: {tail[-1] if tail else '(no output)'}"
        )
    return {str(k): str(v) for k, v in json.loads(res.stdout).items()}


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
    """Diagnostic: installed `headroom --version` (for the pin drift check)."""
    exe = _headroom()
    if not exe:
        return None
    try:
        res = subprocess.run([exe, "--version"], capture_output=True, timeout=5, text=True)
        m = re.search(r"(\d+\.\d+\.\d+)", (res.stdout or "") + (res.stderr or ""))
        return m.group(1) if m else None
    except Exception:
        return None


def latest_version(package: str = "headroom-ai") -> Optional[str]:
    """The newest published version of `package`, straight from the PyPI JSON API.

    Resolving the target *before* installing keeps the exact-pin invariant intact: we still
    record and install `==<version>`, never a floating constraint. Returns None if PyPI is
    unreachable or the payload is unshaped, so the caller can fail loud rather than guess.
    """
    url = f"https://pypi.org/pypi/{package}/json"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            v = json.loads(r.read().decode()).get("info", {}).get("version")
        return str(v) if v else None
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


def version_tuple(v: Optional[str]) -> tuple:
    """Back-compat re-export; canonical parser lives in `versions`."""
    from ..versions import version_tuple as _vt

    return _vt(v)


def install(requirement: str) -> Tuple[bool, str, Optional[str], Optional[str]]:
    """Install an exact headroom requirement (e.g. 'headroom-ai[proxy]==0.29.0').

    Replaces the old `upgrade()`, which shelled out to `uv tool upgrade` and therefore
    resolved to whatever was newest that day. Returns (ok, detail, before, after).
    """
    before = version()
    if not shutil.which("uv"):
        return (False, "uv not on PATH — install headroom manually", before, before)
    try:
        res = subprocess.run(
            ["uv", "tool", "install", requirement, "--force"],
            capture_output=True, timeout=600, text=True,
        )
    except Exception as e:
        return (False, f"install failed ({e.__class__.__name__}: {e})", before, before)
    after = version()
    if res.returncode != 0:
        tail = (res.stderr or res.stdout or "").strip().splitlines()
        return (False, tail[-1] if tail else "uv tool install failed", before, after)
    if before == after:
        return (True, f"already at {after}", before, after)
    return (True, f"{before or 'none'} → {after}", before, after)


def mcp_uninstall() -> tuple:
    """Strip path: remove headroom's own MCP registration (documented, idempotent)."""
    return _run(["mcp", "uninstall"])


def unwrap(client: str = "claude") -> tuple:
    """Strip path: ledger-backed reversal of `headroom wrap` for a client."""
    return _run(["unwrap", client])
