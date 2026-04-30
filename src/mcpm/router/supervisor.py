"""Worker subprocess supervisor: lazy spawn + idle reap."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

from mcpm.core.schema import STDIOServerConfig
from mcpm.global_config import GlobalConfigManager
from mcpm.router.runtime import CHILD_IDLE_TIMEOUT

logger = logging.getLogger(__name__)

# Logs live under the standard cache dir for `mcpm gateway tail` to find,
# but the IPC socket itself MUST live in a short path because macOS caps
# AF_UNIX socket paths at 104 bytes. Putting sockets in /tmp keeps us well
# under that limit even for long server names.
WORKER_LOG_DIR = Path.home() / ".cache" / "mcpm" / "router"


def _default_socket_dir() -> Path:
    if sys.platform == "win32":
        return Path(tempfile.gettempdir()) / "mcpm-router"
    return Path("/tmp") / f"mcpm-router-{os.geteuid()}"


WORKER_SOCKET_DIR = _default_socket_dir()
WORKER_SOCKET_TIMEOUT = 5.0
REAPER_INTERVAL_SECONDS = 30.0


@dataclass
class WorkerHandle:
    name: str
    process: subprocess.Popen
    ipc_path: Path
    log_path: Path
    last_touch: float = field(default_factory=time.time)
    spawned_at: float = field(default_factory=time.time)


class WorkerSupervisor:
    """Owns the per-server worker subprocesses and their IPC sockets.

    Spawns lazily on first request, reaps after `child_idle_timeout` of zero
    traffic, and signals all live workers on shutdown so children do not
    outlive their router parent.
    """

    def __init__(
        self,
        child_idle_timeout: float = CHILD_IDLE_TIMEOUT,
        runtime_dir: Optional[Path] = None,
        socket_dir: Optional[Path] = None,
    ) -> None:
        self.child_idle_timeout = child_idle_timeout
        self.runtime_dir = runtime_dir or WORKER_LOG_DIR
        self.runtime_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.socket_dir = socket_dir or WORKER_SOCKET_DIR
        self.socket_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.workers: Dict[str, WorkerHandle] = {}
        self.config_manager = GlobalConfigManager()
        self._lock = asyncio.Lock()
        self._reaper_task: Optional[asyncio.Task] = None
        self._shutdown = False

    # ----- Lifecycle ----------------------------------------------------

    async def start(self) -> None:
        self._reaper_task = asyncio.create_task(self._reap_idle_loop(), name="worker-reaper")

    async def shutdown(self) -> None:
        self._shutdown = True
        if self._reaper_task is not None:
            self._reaper_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reaper_task
        await asyncio.gather(
            *[self._terminate(h) for h in list(self.workers.values())],
            return_exceptions=True,
        )
        self.workers.clear()

    @property
    def worker_count(self) -> int:
        return len(self.workers)

    # ----- Public API ---------------------------------------------------

    def touch(self, name: str) -> None:
        handle = self.workers.get(name)
        if handle is not None:
            handle.last_touch = time.time()

    async def open_connection(self, name: str) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        """Connect to the worker's IPC socket, spawning it if needed.

        Each call returns a fresh connection: the router opens one per
        upstream HTTP request, writes the JSON-RPC frame, and reads the
        response. This keeps the IPC framing trivial.
        """
        handle = await self._ensure_worker(name)
        handle.last_touch = time.time()
        if sys.platform == "win32":
            raise NotImplementedError("Windows IPC fallback is Phase 6")
        reader, writer = await asyncio.open_unix_connection(str(handle.ipc_path))
        return reader, writer

    # ----- Spawn --------------------------------------------------------

    async def _ensure_worker(self, name: str) -> WorkerHandle:
        async with self._lock:
            handle = self.workers.get(name)
            if handle is not None and handle.process.poll() is None:
                return handle
            if handle is not None:
                # Stale handle: child died. Clean up before respawn.
                await self._terminate(handle)
                self.workers.pop(name, None)
            handle = await self._spawn(name)
            self.workers[name] = handle
            return handle

    async def _spawn(self, name: str) -> WorkerHandle:
        server = self.config_manager.get_server(name)
        if server is None:
            raise KeyError(f"server '{name}' is not registered in mcpm")
        if not isinstance(server, STDIOServerConfig):
            raise TypeError(f"server '{name}' is not stdio (router only proxies stdio)")

        ipc_path = self.socket_dir / f"{name}.sock"
        log_path = self.runtime_dir / f"{name}.log"
        with contextlib.suppress(FileNotFoundError):
            ipc_path.unlink()

        log_fd = os.open(str(log_path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            env = {
                **os.environ,
                "MCPM_WORKER_IPC": str(ipc_path),
                "MCPM_WORKER_NAME": name,
                "MCPM_PARENT_PID": str(os.getpid()),
                "MCPM_REQUIRES_SESSION_PINNING": "1" if server.requires_session_pinning else "0",
            }
            cmd = [shutil.which("mcpm") or "mcpm", "_worker", name]
            popen_kwargs: dict = {
                "env": env,
                "stdin": subprocess.DEVNULL,
                "stdout": log_fd,
                "stderr": log_fd,
                "close_fds": True,
            }
            if sys.platform != "win32":
                popen_kwargs["start_new_session"] = True
            process = subprocess.Popen(cmd, **popen_kwargs)
        finally:
            os.close(log_fd)

        try:
            await self._await_socket(ipc_path, WORKER_SOCKET_TIMEOUT)
        except TimeoutError:
            with contextlib.suppress(Exception):
                process.terminate()
            raise

        logger.info("spawned worker '%s' (pid=%s, ipc=%s)", name, process.pid, ipc_path)
        return WorkerHandle(name=name, process=process, ipc_path=ipc_path, log_path=log_path)

    @staticmethod
    async def _await_socket(path: Path, timeout: float) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if path.exists():
                return
            await asyncio.sleep(0.05)
        raise TimeoutError(f"worker IPC socket {path} did not appear within {timeout}s")

    # ----- Reap ---------------------------------------------------------

    async def _reap_idle_loop(self) -> None:
        try:
            while not self._shutdown:
                await asyncio.sleep(REAPER_INTERVAL_SECONDS)
                await self._reap_once()
        except asyncio.CancelledError:
            pass

    async def _reap_once(self) -> None:
        now = time.time()
        async with self._lock:
            stale = [
                h for h in self.workers.values()
                if now - h.last_touch > self.child_idle_timeout
            ]
        for handle in stale:
            logger.info(
                "evicting idle worker '%s' (idle=%.0fs)",
                handle.name, now - handle.last_touch,
            )
            await self._terminate(handle)
            self.workers.pop(handle.name, None)

    async def _terminate(self, handle: WorkerHandle) -> None:
        if handle.process.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                handle.process.terminate()
            try:
                await asyncio.wait_for(
                    asyncio.get_running_loop().run_in_executor(None, handle.process.wait),
                    timeout=5.0,
                )
            except asyncio.TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    handle.process.kill()
        with contextlib.suppress(FileNotFoundError):
            handle.ipc_path.unlink()
