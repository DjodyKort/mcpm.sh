"""Starlette app builder. One Mount per stdio server, one health route."""

from __future__ import annotations

import logging
import time
from typing import Iterable, Optional

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Mount, Route

from mcpm.core.schema import STDIOServerConfig
from mcpm.global_config import GlobalConfigManager
from mcpm.router.auth import RequireMcpmToken
from mcpm.router.proxy import worker_proxy_endpoint
from mcpm.router.supervisor import WorkerSupervisor

logger = logging.getLogger(__name__)


def _eligible_servers(config: GlobalConfigManager) -> Iterable[tuple[str, STDIOServerConfig]]:
    for name, server in config.list_servers().items():
        if not isinstance(server, STDIOServerConfig):
            continue
        mode = getattr(server, "proxy_mode", "auto")
        if mode in ("auto", "router"):
            yield name, server


def build_app(
    supervisor: WorkerSupervisor,
    token: str,
    config_manager: Optional[GlobalConfigManager] = None,
    started_at: Optional[float] = None,
) -> Starlette:
    """Construct the Starlette app for the running router.

    Routes are computed at startup from the current servers.json. Adding or
    removing a server requires a router restart, which the user can trigger
    with `mcpm gateway restart` (Phase 4) or by waiting for idle-shutdown.
    """
    config = config_manager or GlobalConfigManager()
    started_at = started_at or time.time()

    routes: list = []
    routed_names: list[str] = []
    for name, _server in _eligible_servers(config):
        endpoint = worker_proxy_endpoint(name, supervisor)
        routes.append(
            Mount(
                f"/{name}",
                routes=[
                    Route("/mcp", endpoint=endpoint, methods=["GET", "POST", "DELETE", "OPTIONS"]),
                    Route("/mcp/{rest:path}", endpoint=endpoint, methods=["GET", "POST", "DELETE", "OPTIONS"]),
                ],
            )
        )
        routed_names.append(name)

    async def health(_: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    async def status(_: Request) -> JSONResponse:
        return JSONResponse(
            {
                "started_at": started_at,
                "uptime_seconds": time.time() - started_at,
                "servers": routed_names,
                "active_workers": supervisor.worker_count,
            }
        )

    routes.append(Route("/_health", endpoint=health, methods=["GET"]))
    routes.append(Route("/_status", endpoint=status, methods=["GET"]))

    middleware = [Middleware(RequireMcpmToken, token=token)]

    async def on_startup() -> None:
        await supervisor.start()
        logger.info("router app started with %d routed server(s)", len(routed_names))

    async def on_shutdown() -> None:
        await supervisor.shutdown()

    return Starlette(
        routes=routes,
        middleware=middleware,
        on_startup=[on_startup],
        on_shutdown=[on_shutdown],
    )
