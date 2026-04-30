"""`mcpm _worker <name>` entry point.

Bound to one server name. Owns:
  - the IPC listener at MCPM_WORKER_IPC (Unix socket)
  - the upstream stdio child via UpstreamShim
  - parent-death detection (Linux: PR_SET_PDEATHSIG; macOS/Windows: poll)
  - idle self-shutdown a bit after CHILD_IDLE_TIMEOUT so the supervisor's
    SIGTERM wins races but a leaked worker eventually dies on its own
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Optional

from mcpm.global_config import GlobalConfigManager
from mcpm.router.runtime import CHILD_IDLE_TIMEOUT
from mcpm.worker.shim import UpstreamShim, stderr_to_notification

logger = logging.getLogger(__name__)

PARENT_POLL_SECONDS = 5.0
# Self-eviction trigger: 1.5x the supervisor's threshold so the supervisor
# always wins the race in the normal case.
SELF_EVICT_FACTOR = 1.5


async def _serve(name: str) -> int:
    ipc_path = os.environ.get("MCPM_WORKER_IPC")
    if not ipc_path:
        logger.error("MCPM_WORKER_IPC not set")
        return 2

    parent_pid_str = os.environ.get("MCPM_PARENT_PID")
    parent_pid = int(parent_pid_str) if parent_pid_str and parent_pid_str.isdigit() else None

    config = GlobalConfigManager()
    server = config.get_server(name)
    if server is None:
        logger.error("server '%s' not registered", name)
        return 3
    if not hasattr(server, "command"):
        logger.error("server '%s' is not stdio", name)
        return 4

    # Build the upstream env from the saved server config + current env.
    upstream_env = {**os.environ, **(getattr(server, "env", None) or {})}
    shim = UpstreamShim(command=server.command, args=list(server.args or []), env=upstream_env)
    await shim.start()
    _set_pdeathsig()

    last_activity = time.time()

    async def handle_connection(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        nonlocal last_activity
        last_activity = time.time()
        stderr_queue: asyncio.Queue[str] = asyncio.Queue(maxsize=128)
        shim.subscribe_stderr(stderr_queue)
        try:
            session_line = await reader.readline()
            if not session_line:
                return
            session_id = session_line.rstrip(b"\n").decode("ascii", errors="ignore")
            body = await reader.read()
            body_text = body.strip()
            if not body_text:
                return
            try:
                frame = json.loads(body_text.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                logger.warning("router sent non-JSON: %s", exc)
                _write_response(writer, session_id, b"")
                return

            try:
                response, notifications = await shim.call(frame, timeout=60.0)
            except ConnectionError as exc:
                logger.error("upstream call failed: %s", exc)
                _write_response(writer, session_id, b"")
                return
            except asyncio.TimeoutError:
                logger.error("upstream call timed out")
                _write_response(writer, session_id, b"")
                return

            # Drain any stderr that came in during the call and surface as
            # MCP notifications/message before the response. Streamable
            # HTTP v1 only allows a single response frame per request, so
            # we attach notifications inline by ... TODO: wrap in batch.
            # For v1 just log them; the response itself goes back.
            for notif in notifications:
                logger.debug("notification queued: %s", notif.get("method"))
            for _ in range(stderr_queue.qsize()):
                try:
                    text = stderr_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                logger.debug("stderr: %s", stderr_to_notification(text)["params"]["data"])

            if response is None:
                _write_response(writer, session_id, b"")
            else:
                payload = json.dumps(response, separators=(",", ":")).encode("utf-8")
                _write_response(writer, session_id, payload)
        except Exception:
            logger.exception("worker connection handler crashed")
        finally:
            shim.unsubscribe_stderr(stderr_queue)
            with contextlib.suppress(Exception):
                writer.close()
                await writer.wait_closed()
            last_activity = time.time()

    # Bind the IPC socket. We unlink any stale socket first because the
    # supervisor already deletes it pre-spawn but be defensive.
    with contextlib.suppress(FileNotFoundError):
        Path(ipc_path).unlink()
    server_obj = await asyncio.start_unix_server(handle_connection, path=ipc_path)
    try:
        os.chmod(ipc_path, 0o600)
    except OSError:
        pass

    self_evict_after = CHILD_IDLE_TIMEOUT * SELF_EVICT_FACTOR
    stop_event = asyncio.Event()

    def _request_stop(*_: object) -> None:
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, _request_stop)

    async def watchdog() -> None:
        nonlocal last_activity
        while not stop_event.is_set():
            await asyncio.sleep(PARENT_POLL_SECONDS)
            if parent_pid is not None and not _pid_alive(parent_pid):
                logger.info("parent (%d) died, self-shutting down", parent_pid)
                stop_event.set()
                return
            if not shim.alive:
                logger.info("upstream child died, self-shutting down")
                stop_event.set()
                return
            if time.time() - last_activity > self_evict_after:
                logger.info("idle for %.0fs, self-shutting down", self_evict_after)
                stop_event.set()
                return

    watchdog_task = asyncio.create_task(watchdog())
    serve_task = asyncio.create_task(server_obj.serve_forever())
    stop_task = asyncio.create_task(stop_event.wait())

    done, pending = await asyncio.wait(
        {serve_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
    )
    for task in pending:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
    watchdog_task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await watchdog_task

    server_obj.close()
    with contextlib.suppress(Exception):
        await server_obj.wait_closed()
    await shim.shutdown()
    with contextlib.suppress(FileNotFoundError):
        Path(ipc_path).unlink()
    return 0


def _write_response(writer: asyncio.StreamWriter, session_id: str, body: bytes) -> None:
    writer.write(session_id.encode("ascii") + b"\n")
    if body:
        writer.write(body)
        if not body.endswith(b"\n"):
            writer.write(b"\n")
    writer.write_eof()


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


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


def main(name: Optional[str] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [worker] %(message)s")
    if name is None:
        name = os.environ.get("MCPM_WORKER_NAME") or (sys.argv[1] if len(sys.argv) > 1 else "")
    if not name:
        logger.error("worker requires a server name")
        return 2
    try:
        return asyncio.run(_serve(name))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
