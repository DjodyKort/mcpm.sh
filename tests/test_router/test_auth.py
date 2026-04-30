"""Tests for the token middleware."""

from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from mcpm.router.auth import RequireMcpmToken


@pytest.fixture
def client():
    async def health(_: Request):
        return PlainTextResponse("ok")

    async def secret(_: Request):
        return JSONResponse({"data": "private"})

    app = Starlette(
        routes=[Route("/_health", health), Route("/secret", secret)],
        middleware=[Middleware(RequireMcpmToken, token="correct-token")],
    )
    return TestClient(app)


def test010_health_does_not_require_token(client):
    resp = client.get("/_health")
    assert resp.status_code == 200
    assert resp.text == "ok"


def test020_request_without_token_is_rejected(client):
    resp = client.get("/secret")
    assert resp.status_code == 401


def test030_request_with_wrong_token_is_rejected(client):
    resp = client.get("/secret", headers={"Mcp-Mcpm-Token": "nope"})
    assert resp.status_code == 401


def test040_request_with_correct_token_succeeds(client):
    resp = client.get("/secret", headers={"Mcp-Mcpm-Token": "correct-token"})
    assert resp.status_code == 200
    assert resp.json() == {"data": "private"}
