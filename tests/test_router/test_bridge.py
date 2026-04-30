"""Tests for the `mcpm bridge` stdio shim.

We don't spin up a real router here. The bridge's job is to translate
stdin lines to HTTP requests against the runtime URL and translate
responses back to stdout. We mock the HTTP transport with httpx's
MockTransport so we can assert framing without subprocess churn.
"""

from __future__ import annotations

import io
import json
import sys
from unittest.mock import patch

import httpx
import pytest

from mcpm.commands import bridge as bridge_module
from mcpm.router.runtime import RouterRuntime


def _fake_runtime() -> RouterRuntime:
    return RouterRuntime(pid=1234, port=9999, token="t-token", started_at=0.0)


@pytest.mark.asyncio
async def test010_bridge_pumps_request_and_writes_response(monkeypatch):
    """Single JSON-RPC request → POST → JSON response → stdout."""
    captured_requests: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        captured_requests.append(req)
        body = json.loads(req.content)
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": body["id"], "result": {"echo": True}},
            headers={"Content-Type": "application/json"},
        )

    transport = httpx.MockTransport(handler)
    fake_in = io.StringIO('{"jsonrpc":"2.0","id":42,"method":"ping"}\n')
    fake_out = io.StringIO()

    monkeypatch.setattr(RouterRuntime, "read_or_launch", classmethod(lambda cls: _fake_runtime()))
    monkeypatch.setattr(sys, "stdin", fake_in)
    monkeypatch.setattr(sys, "stdout", fake_out)

    real_async_client = httpx.AsyncClient

    def make_client(**kw):
        return real_async_client(transport=transport, **{k: v for k, v in kw.items() if k != "transport"})

    with patch("mcpm.commands.bridge.httpx.AsyncClient", make_client):
        rc = await bridge_module._pump("echo-test")

    assert rc == 0
    assert len(captured_requests) == 1
    req = captured_requests[0]
    assert req.method == "POST"
    assert req.url.path == "/echo-test/mcp"
    assert req.headers["Mcp-Mcpm-Token"] == "t-token"
    body = fake_out.getvalue()
    parsed = json.loads(body.strip())
    assert parsed == {"jsonrpc": "2.0", "id": 42, "result": {"echo": True}}


@pytest.mark.asyncio
async def test020_bridge_handles_sse_response(monkeypatch):
    """Streamable-HTTP SSE responses unfold into newline-separated JSON frames."""

    sse_body = (
        b"event: message\n"
        b'data: {"jsonrpc":"2.0","id":1,"result":{"part":"a"}}\n\n'
        b"event: message\n"
        b'data: {"jsonrpc":"2.0","method":"notifications/x"}\n\n'
    )

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=sse_body,
            headers={"Content-Type": "text/event-stream"},
        )

    transport = httpx.MockTransport(handler)
    fake_in = io.StringIO('{"jsonrpc":"2.0","id":1,"method":"ping"}\n')
    fake_out = io.StringIO()

    monkeypatch.setattr(RouterRuntime, "read_or_launch", classmethod(lambda cls: _fake_runtime()))
    monkeypatch.setattr(sys, "stdin", fake_in)
    monkeypatch.setattr(sys, "stdout", fake_out)

    real_async_client = httpx.AsyncClient

    def make_client(**kw):
        return real_async_client(transport=transport, **{k: v for k, v in kw.items() if k != "transport"})

    with patch("mcpm.commands.bridge.httpx.AsyncClient", make_client):
        rc = await bridge_module._pump("anything")

    assert rc == 0
    lines = [line for line in fake_out.getvalue().splitlines() if line]
    assert len(lines) == 2
    assert json.loads(lines[0])["result"] == {"part": "a"}
    assert json.loads(lines[1])["method"] == "notifications/x"


@pytest.mark.asyncio
async def test030_bridge_persists_session_id_across_calls(monkeypatch):
    """First response sets `Mcp-Session-Id`; subsequent calls echo it."""
    seen_session_ids: list[str | None] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen_session_ids.append(req.headers.get("Mcp-Session-Id"))
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": 1, "result": {}},
            headers={"Content-Type": "application/json", "Mcp-Session-Id": "sess-abc"},
        )

    transport = httpx.MockTransport(handler)
    fake_in = io.StringIO(
        '{"jsonrpc":"2.0","id":1,"method":"a"}\n'
        '{"jsonrpc":"2.0","id":2,"method":"b"}\n'
    )
    fake_out = io.StringIO()

    monkeypatch.setattr(RouterRuntime, "read_or_launch", classmethod(lambda cls: _fake_runtime()))
    monkeypatch.setattr(sys, "stdin", fake_in)
    monkeypatch.setattr(sys, "stdout", fake_out)

    real_async_client = httpx.AsyncClient

    def make_client(**kw):
        return real_async_client(transport=transport, **{k: v for k, v in kw.items() if k != "transport"})

    with patch("mcpm.commands.bridge.httpx.AsyncClient", make_client):
        await bridge_module._pump("any")

    assert seen_session_ids == [None, "sess-abc"]


@pytest.mark.asyncio
async def test040_bridge_drops_frame_on_request_error(monkeypatch):
    """A network error shouldn't crash the bridge; it logs and continues."""
    call_count = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise httpx.ConnectError("boom")
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": 2, "result": {}},
            headers={"Content-Type": "application/json"},
        )

    transport = httpx.MockTransport(handler)
    fake_in = io.StringIO(
        '{"jsonrpc":"2.0","id":1,"method":"first"}\n'
        '{"jsonrpc":"2.0","id":2,"method":"second"}\n'
    )
    fake_out = io.StringIO()

    monkeypatch.setattr(RouterRuntime, "read_or_launch", classmethod(lambda cls: _fake_runtime()))
    monkeypatch.setattr(sys, "stdin", fake_in)
    monkeypatch.setattr(sys, "stdout", fake_out)

    real_async_client = httpx.AsyncClient

    def make_client(**kw):
        return real_async_client(transport=transport, **{k: v for k, v in kw.items() if k != "transport"})

    with patch("mcpm.commands.bridge.httpx.AsyncClient", make_client):
        rc = await bridge_module._pump("any")

    assert rc == 0
    # Only the second request produced output.
    assert call_count["n"] == 2
    out_lines = [line for line in fake_out.getvalue().splitlines() if line]
    assert len(out_lines) == 1
    assert json.loads(out_lines[0])["id"] == 2
