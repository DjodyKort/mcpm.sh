"""Router runtime state file + self-launch (gpg-agent pattern)."""

from __future__ import annotations

import contextlib
import logging
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Default idle timeouts (overridable via env or future gateway.json).
ROUTER_IDLE_TIMEOUT = float(os.environ.get("MCPM_ROUTER_IDLE_TIMEOUT", "1800"))  # 30 min
CHILD_IDLE_TIMEOUT = float(os.environ.get("MCPM_CHILD_IDLE_TIMEOUT", "900"))  # 15 min

LAUNCH_TIMEOUT_SECONDS = 5.0
HEALTH_TIMEOUT_SECONDS = 0.5


class RouterRuntime(BaseModel):
    """The persisted state of a running router process."""

    pid: int
    port: int
    token: str
    started_at: float

    # ----- Paths --------------------------------------------------------

    @classmethod
    def state_path(cls) -> Path:
        return Path.home() / ".config" / "mcpm" / "router-runtime.json"

    @classmethod
    def lock_path(cls) -> Path:
        return cls.state_path().with_suffix(".lock")

    # ----- Read/launch --------------------------------------------------

    @classmethod
    def read(cls) -> Optional["RouterRuntime"]:
        path = cls.state_path()
        if not path.exists():
            return None
        try:
            return cls.model_validate_json(path.read_text())
        except Exception as exc:
            logger.debug("router state file unreadable: %s", exc)
            return None

    @classmethod
    def read_or_launch(cls) -> "RouterRuntime":
        existing = cls.read()
        if existing is not None and cls._is_alive(existing):
            return existing
        return cls._launch_locked()

    @classmethod
    def write(cls, runtime: "RouterRuntime") -> None:
        """Atomically write the state file with mode 0600."""
        path = cls.state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(runtime.model_dump_json())
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            # Windows is best-effort here.
            pass
        os.replace(tmp, path)

    @classmethod
    def unlink(cls) -> None:
        for p in (cls.state_path(), cls.lock_path()):
            with contextlib.suppress(FileNotFoundError):
                p.unlink()

    # ----- Liveness check -----------------------------------------------

    @staticmethod
    def _is_alive(rt: "RouterRuntime") -> bool:
        # Cheap PID check first.
        try:
            os.kill(rt.pid, 0)
        except (ProcessLookupError, PermissionError):
            return False
        except OSError:
            return False
        # Then verify the HTTP layer is actually serving (a stale state file
        # whose PID was reused by an unrelated process must not look healthy).
        try:
            r = httpx.get(
                f"http://127.0.0.1:{rt.port}/_health",
                headers={"Mcp-Mcpm-Token": rt.token},
                timeout=HEALTH_TIMEOUT_SECONDS,
            )
            return r.status_code == 200 and r.text.strip().startswith("ok")
        except httpx.RequestError:
            return False

    # ----- Self-launch (gpg-agent pattern) ------------------------------

    @classmethod
    def _launch_locked(cls) -> "RouterRuntime":
        """Acquire an advisory lock so concurrent callers do not double-spawn."""
        lock_path = cls.lock_path()
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            cls._acquire_lock(lock_fd)
            # Double-check inside the lock: another caller may have just spawned.
            existing = cls.read()
            if existing is not None and cls._is_alive(existing):
                return existing
            return cls._launch()
        finally:
            cls._release_lock(lock_fd)
            os.close(lock_fd)

    @staticmethod
    def _acquire_lock(fd: int) -> None:
        if sys.platform == "win32":
            import msvcrt

            # Block up to 5s for the lock.
            for _ in range(50):
                try:
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    return
                except OSError:
                    time.sleep(0.1)
            raise TimeoutError("could not acquire router launch lock")
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX)

    @staticmethod
    def _release_lock(fd: int) -> None:
        if sys.platform == "win32":
            import msvcrt

            with contextlib.suppress(OSError):
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            with contextlib.suppress(OSError):
                fcntl.flock(fd, fcntl.LOCK_UN)

    @classmethod
    def _launch(cls) -> "RouterRuntime":
        # Pre-bind a kernel-assigned port to avoid races between launch and
        # bind. We pass the chosen port through env to the child.
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()

        token = secrets.token_urlsafe(32)
        cls.state_path().parent.mkdir(parents=True, exist_ok=True)

        env = {
            **os.environ,
            "MCPM_ROUTER_PORT": str(port),
            "MCPM_ROUTER_TOKEN": token,
            "MCPM_ROUTER_PARENT_PID": str(os.getpid()),
        }

        cmd = ["mcpm", "_router"]
        if sys.platform == "win32":
            DETACHED_PROCESS = 0x00000008
            CREATE_NEW_PROCESS_GROUP = 0x00000200
            flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
            subprocess.Popen(
                cmd,
                env=env,
                creationflags=flags,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
        else:
            subprocess.Popen(
                cmd,
                env=env,
                start_new_session=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )

        # The child writes the state file once it is ready to serve. Poll.
        deadline = time.time() + LAUNCH_TIMEOUT_SECONDS
        while time.time() < deadline:
            rt = cls.read()
            if rt is not None and cls._is_alive(rt):
                return rt
            time.sleep(0.05)
        raise RuntimeError(f"router failed to start within {LAUNCH_TIMEOUT_SECONDS}s")
