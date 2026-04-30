"""`mcpm _router` entry point. Reads env, runs uvicorn, manages state file.

This is invoked by `RouterRuntime._launch` as a detached subprocess. It:

  1. Reads MCPM_ROUTER_PORT and MCPM_ROUTER_TOKEN from env (must both be set).
  2. Builds the Starlette app with the supervisor wired in.
  3. Writes the state file so callers polling `RouterRuntime.read_or_launch`
     can verify liveness and connect.
  4. Runs uvicorn until SIGTERM, idle-shutdown, or parent death.
  5. Removes the state file on exit so the next invocation gets a clean slate.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import sys
import threading
import time
from typing import Optional

import uvicorn

from mcpm.router.app import build_app
from mcpm.router.runtime import ROUTER_IDLE_TIMEOUT, RouterRuntime
from mcpm.router.supervisor import WorkerSupervisor

logger = logging.getLogger(__name__)

# How often the idle-watchdog checks whether the router should exit.
IDLE_WATCHDOG_INTERVAL = 30.0
# How often we check whether the parent process (the caller that launched us)
# has died on macOS / Windows where PR_SET_PDEATHSIG is not available.
PARENT_WATCHDOG_INTERVAL = 5.0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [router] %(message)s")

    port_str = os.environ.get("MCPM_ROUTER_PORT")
    token = os.environ.get("MCPM_ROUTER_TOKEN")
    if not port_str or not token:
        logger.error("MCPM_ROUTER_PORT and MCPM_ROUTER_TOKEN must be set")
        return 2
    port = int(port_str)

    parent_pid_str = os.environ.get("MCPM_ROUTER_PARENT_PID")
    parent_pid = int(parent_pid_str) if parent_pid_str and parent_pid_str.isdigit() else None

    supervisor = WorkerSupervisor()
    started_at = time.time()
    app = build_app(supervisor, token=token, started_at=started_at)

    runtime = RouterRuntime(pid=os.getpid(), port=port, token=token, started_at=started_at)
    RouterRuntime.write(runtime)

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
        timeout_keep_alive=15,
    )
    server = uvicorn.Server(config)

    # Idle and parent-death watchdogs run in a side thread so they don't
    # depend on the asyncio loop being healthy.
    stop_event = threading.Event()
    watchdog = threading.Thread(
        target=_watchdog,
        args=(server, supervisor, parent_pid, started_at, stop_event),
        daemon=True,
        name="router-watchdog",
    )
    watchdog.start()

    # Linux: ask the kernel to send us SIGTERM if our parent dies. Best
    # effort, ignored on platforms without prctl.
    _set_pdeathsig()

    exit_code = 0
    try:
        server.run()
    except KeyboardInterrupt:
        exit_code = 130
    except Exception as exc:
        logger.exception("router crashed: %s", exc)
        exit_code = 1
    finally:
        stop_event.set()
        with contextlib.suppress(Exception):
            asyncio.run(supervisor.shutdown())
        RouterRuntime.unlink()
    return exit_code


def _set_pdeathsig() -> None:
    if sys.platform != "linux":
        return
    try:
        import ctypes

        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        PR_SET_PDEATHSIG = 1
        libc.prctl(PR_SET_PDEATHSIG, signal.SIGTERM, 0, 0, 0)
    except Exception as exc:
        logger.debug("could not set PR_SET_PDEATHSIG: %s", exc)


def _watchdog(
    server: uvicorn.Server,
    supervisor: WorkerSupervisor,
    parent_pid: Optional[int],
    started_at: float,
    stop_event: threading.Event,
) -> None:
    """Trigger graceful shutdown when idle, or when parent dies."""
    last_active = started_at
    while not stop_event.wait(min(IDLE_WATCHDOG_INTERVAL, PARENT_WATCHDOG_INTERVAL)):
        # Parent-death detection (best-effort cross-platform).
        if parent_pid is not None and not _pid_alive(parent_pid):
            logger.info("parent process (%d) gone, shutting down", parent_pid)
            server.should_exit = True
            return
        # Idle eviction: only triggers when there are no active workers.
        # Any worker keeps the router alive past the idle timeout because
        # its `last_touch` is bumped on every request.
        if supervisor.worker_count == 0:
            if time.time() - last_active > ROUTER_IDLE_TIMEOUT:
                logger.info("router idle for %.0fs, self-shutting down", ROUTER_IDLE_TIMEOUT)
                server.should_exit = True
                return
        else:
            last_active = time.time()


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # Process exists but we can't signal it.
    except OSError:
        return False
    return True


if __name__ == "__main__":
    sys.exit(main())
