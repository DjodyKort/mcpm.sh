"""HTTP <-> worker IPC pump.

The router terminates Streamable HTTP and forwards the JSON-RPC payload
to the named worker over its Unix-domain IPC socket. This module is
deliberately thin: framing is one-frame-in/one-frame-out per IPC connection,
and Mcp-Session-Id is propagated via a single preamble line so workers
can do per-session pinning when configured.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Callable

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from mcpm.router.supervisor import WorkerSupervisor

logger = logging.getLogger(__name__)

# Cap inbound payloads so a stray client cannot DoS the router by streaming
# unbounded bytes. MCP messages are small (kilobytes); 4 MiB is generous.
MAX_REQUEST_BYTES = 4 * 1024 * 1024
WORKER_RESPONSE_TIMEOUT = 60.0


def worker_proxy_endpoint(name: str, supervisor: WorkerSupervisor) -> Callable:
    """Build a Starlette ASGI handler bound to one server name."""

    async def handle(request: Request) -> Response:
        if request.method == "GET":
            # Streamable HTTP GET = open SSE channel for server-pushed
            # notifications. Phase 3 v1 only handles request/response so a
            # GET advertising "no streaming" is sufficient for clients to
            # fall back to POST-only.
            return Response(status_code=405, headers={"Allow": "POST"})
        if request.method == "DELETE":
            # MCP Streamable HTTP "session terminate" — no-op for v1 since
            # the router does not pin sessions yet.
            return Response(status_code=204)
        if request.method != "POST":
            return Response(status_code=405, headers={"Allow": "POST"})

        body = await request.body()
        if len(body) > MAX_REQUEST_BYTES:
            return JSONResponse(
                {"error": "request payload too large"}, status_code=413
            )
        if not body:
            return JSONResponse({"error": "empty request body"}, status_code=400)

        session_id = request.headers.get("Mcp-Session-Id", "")
        try:
            response_bytes, response_session_id = await _forward(
                supervisor, name, session_id, body
            )
        except KeyError:
            return JSONResponse(
                {"error": f"server '{name}' is not registered in mcpm"},
                status_code=404,
            )
        except TypeError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except asyncio.TimeoutError:
            return JSONResponse(
                {"error": f"upstream worker for '{name}' did not respond in time"},
                status_code=504,
            )
        except (ConnectionError, OSError) as exc:
            logger.warning("worker connection failed for %s: %s", name, exc)
            return JSONResponse(
                {"error": f"worker for '{name}' is unavailable"}, status_code=502
            )

        if not response_bytes:
            # Pure notification (no response from upstream) — Streamable HTTP
            # spec: 202 Accepted with empty body.
            headers: dict = {}
            if response_session_id:
                headers["Mcp-Session-Id"] = response_session_id
            return Response(status_code=202, headers=headers)

        # Validate JSON before returning so a corrupt frame surfaces as 502
        # rather than a confusing client-side parse failure.
        try:
            json.loads(response_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return JSONResponse(
                {"error": "worker emitted non-JSON response"}, status_code=502
            )

        headers = {"Content-Type": "application/json"}
        if response_session_id:
            headers["Mcp-Session-Id"] = response_session_id
        return Response(content=response_bytes, headers=headers)

    return handle


async def _forward(
    supervisor: WorkerSupervisor,
    name: str,
    session_id: str,
    body: bytes,
) -> tuple[bytes, str]:
    """Open one IPC connection, write request frame, read response frame.

    IPC framing (request):  ``<session_id>\\n<body>\\n``
    IPC framing (response): ``<session_id>\\n<body>\\n``

    A blank session_id line means "no pinning". An empty body line means
    "this was a notification, no response".
    """
    reader, writer = await supervisor.open_connection(name)
    try:
        writer.write(session_id.encode("ascii") + b"\n")
        writer.write(body)
        if not body.endswith(b"\n"):
            writer.write(b"\n")
        writer.write_eof()
        await writer.drain()

        # Worker writes its response framing back. First line is the
        # session id (possibly newly minted), then the JSON body, then EOF.
        response_session_line = await asyncio.wait_for(
            reader.readline(), timeout=WORKER_RESPONSE_TIMEOUT
        )
        response_session_id = response_session_line.rstrip(b"\n").decode("ascii", errors="ignore")
        response_body = await asyncio.wait_for(
            reader.read(), timeout=WORKER_RESPONSE_TIMEOUT
        )
        return response_body.rstrip(b"\n"), response_session_id
    finally:
        with contextlib.suppress(Exception):
            writer.close()
            await writer.wait_closed()
