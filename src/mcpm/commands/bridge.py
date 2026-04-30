"""`mcpm bridge <server>` — stdio shim for clients that don't speak HTTP MCP.

Reads JSON-RPC frames from stdin, POSTs each to the local router, writes the
response to stdout. Handles both plain JSON and Streamable-HTTP SSE responses
so clients see one MCP frame per stdout line.
"""

from __future__ import annotations

import asyncio
import logging
import sys

import httpx

from mcpm.router.runtime import RouterRuntime
from mcpm.utils.rich_click_config import click

logger = logging.getLogger(__name__)


@click.command(name="bridge", context_settings=dict(help_option_names=["-h", "--help"]))
@click.argument("server_name")
def bridge_cmd(server_name: str):
    """Stdio shim that pumps JSON-RPC stdin <-> router HTTP.

    Used by stdio-only client managers (older Claude Desktop, embedded
    extensions). Each client config entry looks like:

        {"command": "mcpm", "args": ["bridge", "<server-name>"]}
    """
    # Bridge errors must NOT contaminate stdout (which carries the MCP
    # protocol). Direct logging to stderr.
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr, format="%(message)s")
    sys.exit(asyncio.run(_pump(server_name)))


async def _pump(server_name: str) -> int:
    rt = RouterRuntime.read_or_launch()
    url = f"http://127.0.0.1:{rt.port}/{server_name}/mcp"
    base_headers = {
        "Mcp-Mcpm-Token": rt.token,
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    session_id: str | None = None

    async with httpx.AsyncClient(timeout=None) as client:
        loop = asyncio.get_running_loop()
        while True:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                return 0
            line = line.strip()
            if not line:
                continue

            req_headers = dict(base_headers)
            if session_id:
                req_headers["Mcp-Session-Id"] = session_id

            try:
                async with client.stream(
                    "POST", url, content=line.encode("utf-8"), headers=req_headers
                ) as resp:
                    new_session = resp.headers.get("Mcp-Session-Id")
                    if new_session:
                        session_id = new_session

                    content_type = resp.headers.get("Content-Type", "")
                    if content_type.startswith("text/event-stream"):
                        async for sse_line in resp.aiter_lines():
                            if sse_line.startswith("data: "):
                                sys.stdout.write(sse_line[6:] + "\n")
                                sys.stdout.flush()
                    else:
                        body = await resp.aread()
                        if body:
                            sys.stdout.write(body.decode("utf-8") + "\n")
                            sys.stdout.flush()
                    if resp.status_code >= 400:
                        logger.warning(
                            "router returned %s for %s", resp.status_code, server_name
                        )
            except httpx.RequestError as exc:
                logger.error("bridge request failed: %s", exc)
                # Don't exit: clients may retry. Drop the frame and continue.
                continue
