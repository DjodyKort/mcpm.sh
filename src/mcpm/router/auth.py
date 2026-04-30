"""Token middleware. Required on every endpoint except `/_health`."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

TOKEN_HEADER = "Mcp-Mcpm-Token"
PUBLIC_PATHS = {"/_health"}


class RequireMcpmToken(BaseHTTPMiddleware):
    """Reject any request lacking the per-router-session bearer token.

    The token rotates on every router launch (see `RouterRuntime._launch`),
    so a leaked token expires the moment the router restarts. Only the
    /_health endpoint is exempt so liveness probes don't need credentials.
    """

    def __init__(self, app, token: str) -> None:
        super().__init__(app)
        self._token = token

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)
        provided = request.headers.get(TOKEN_HEADER, "")
        if provided != self._token:
            return JSONResponse(
                {"error": "missing or invalid Mcp-Mcpm-Token header"},
                status_code=401,
            )
        return await call_next(request)
