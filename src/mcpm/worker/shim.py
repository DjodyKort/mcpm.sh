"""JSON-RPC framing + id-rewriting multiplex shim.

The worker keeps one upstream stdio child alive across many concurrent
router connections. It rewrites every inbound request's ``id`` to a
worker-unique value before forwarding to the child, then maps the response
back to the original id. Notifications (no ``id``) are broadcast to all
currently-active subscribers.

This is intentionally not built on FastMCP-as-proxy because that defaults
to per-session stdio children, which would defeat the boot-once-share
goal. We use the raw JSON-RPC framing the MCP spec defines.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import json
import logging
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class UpstreamShim:
    """Owns the upstream stdio child and dispatches responses back."""

    def __init__(self, command: str, args: list[str], env: Dict[str, str]) -> None:
        self.command = command
        self.args = args
        self.env = env
        self.process: Optional[asyncio.subprocess.Process] = None
        self._id_counter = itertools.count(1)
        self._pending: Dict[str, asyncio.Future[Dict[str, Any]]] = {}
        self._notification_subscribers: set[asyncio.Queue[Dict[str, Any]]] = set()
        self._stderr_subscribers: set[asyncio.Queue[str]] = set()
        self._reader_task: Optional[asyncio.Task] = None
        self._stderr_task: Optional[asyncio.Task] = None
        self._write_lock = asyncio.Lock()
        self._closed = asyncio.Event()

    async def start(self) -> None:
        self.process = await asyncio.create_subprocess_exec(
            self.command,
            *self.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self.env,
        )
        self._reader_task = asyncio.create_task(self._read_loop(), name="upstream-stdout")
        self._stderr_task = asyncio.create_task(self._stderr_loop(), name="upstream-stderr")

    async def shutdown(self) -> None:
        self._closed.set()
        if self.process is not None and self.process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    self.process.kill()
        for task in (self._reader_task, self._stderr_task):
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        # Cancel any still-pending requests with a synthetic error.
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(ConnectionError("upstream child exited"))
        self._pending.clear()

    @property
    def alive(self) -> bool:
        return self.process is not None and self.process.returncode is None

    # ----- Public dispatch ----------------------------------------------

    async def call(
        self, frame: Dict[str, Any], timeout: float = 60.0
    ) -> Tuple[Optional[Dict[str, Any]], list[Dict[str, Any]]]:
        """Forward one JSON-RPC frame to the upstream child.

        Returns ``(response, queued_notifications)``. ``response`` is None
        for notifications (no ``id`` field). ``queued_notifications`` is
        any server-to-client notification messages observed on the child's
        stdout while waiting for the response, in arrival order.
        """
        if self.process is None or not self.alive:
            raise ConnectionError("upstream child is not running")

        notif_queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        self._notification_subscribers.add(notif_queue)
        try:
            if "id" not in frame:
                # Notification: write and forget. Drain any already-queued
                # notifications so the caller can pass them through.
                await self._write_frame(frame)
                return None, _drain(notif_queue)

            original_id = frame["id"]
            new_id = f"mcpm-{next(self._id_counter)}"
            rewritten = dict(frame)
            rewritten["id"] = new_id

            loop = asyncio.get_running_loop()
            fut: asyncio.Future[Dict[str, Any]] = loop.create_future()
            self._pending[new_id] = fut
            try:
                await self._write_frame(rewritten)
                response = await asyncio.wait_for(fut, timeout=timeout)
            finally:
                self._pending.pop(new_id, None)

            response["id"] = original_id
            return response, _drain(notif_queue)
        finally:
            self._notification_subscribers.discard(notif_queue)

    def subscribe_stderr(self, queue: asyncio.Queue[str]) -> None:
        self._stderr_subscribers.add(queue)

    def unsubscribe_stderr(self, queue: asyncio.Queue[str]) -> None:
        self._stderr_subscribers.discard(queue)

    # ----- Internals ----------------------------------------------------

    async def _write_frame(self, frame: Dict[str, Any]) -> None:
        assert self.process is not None and self.process.stdin is not None
        encoded = (json.dumps(frame, separators=(",", ":")) + "\n").encode("utf-8")
        async with self._write_lock:
            self.process.stdin.write(encoded)
            await self.process.stdin.drain()

    async def _read_loop(self) -> None:
        assert self.process is not None and self.process.stdout is not None
        try:
            while not self._closed.is_set():
                line = await self.process.stdout.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    frame = json.loads(line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    logger.warning("upstream emitted non-JSON line: %r (%s)", line[:200], exc)
                    continue
                self._dispatch(frame)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("upstream stdout reader crashed")

    def _dispatch(self, frame: Dict[str, Any]) -> None:
        frame_id = frame.get("id")
        if frame_id is not None:
            fut = self._pending.get(frame_id)
            if fut is not None and not fut.done():
                fut.set_result(frame)
                return
            logger.debug("orphan response with id=%r", frame_id)
            return
        # Notification: fan out to all subscribers.
        for q in list(self._notification_subscribers):
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(frame)

    async def _stderr_loop(self) -> None:
        assert self.process is not None and self.process.stderr is not None
        try:
            while not self._closed.is_set():
                line = await self.process.stderr.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip("\n")
                # Tee to log (the worker spawned us with stderr=log_fd via
                # the supervisor, so anything we print here also lands in
                # ~/.cache/mcpm/router/<name>.log automatically). Forward
                # to subscribers as `notifications/message` so connected
                # MCP clients see warnings inline.
                logger.warning("[upstream] %s", text)
                for q in list(self._stderr_subscribers):
                    with contextlib.suppress(asyncio.QueueFull):
                        q.put_nowait(text)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("upstream stderr reader crashed")


def _drain(q: asyncio.Queue) -> list:
    items: list = []
    while True:
        try:
            items.append(q.get_nowait())
        except asyncio.QueueEmpty:
            return items


def stderr_to_notification(text: str) -> Dict[str, Any]:
    """Wrap one stderr line as an MCP `notifications/message` frame."""
    return {
        "jsonrpc": "2.0",
        "method": "notifications/message",
        "params": {"level": "warning", "data": text},
    }
