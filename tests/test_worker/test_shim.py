"""Tests for the UpstreamShim id-rewriting multiplex."""

from __future__ import annotations

import asyncio
import os
import sys

import pytest
import pytest_asyncio

from mcpm.worker.shim import UpstreamShim, stderr_to_notification

# A tiny stdio JSON-RPC echo server we drive as the upstream "child".
ECHO_SCRIPT = r"""
import json, sys, time
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    msg = json.loads(line)
    if msg.get("method") == "slow":
        time.sleep(0.2)
    if "id" in msg:
        resp = {"jsonrpc": "2.0", "id": msg["id"], "result": {"echo": msg.get("params")}}
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()
    if msg.get("method") == "notify":
        notif = {"jsonrpc": "2.0", "method": "notifications/x", "params": {"hi": True}}
        sys.stdout.write(json.dumps(notif) + "\n")
        sys.stdout.flush()
    if msg.get("method") == "stderr":
        sys.stderr.write("oh no\n")
        sys.stderr.flush()
"""


@pytest_asyncio.fixture
async def shim(tmp_path):
    script = tmp_path / "echo.py"
    script.write_text(ECHO_SCRIPT)
    s = UpstreamShim(command=sys.executable, args=[str(script)], env=dict(os.environ))
    await s.start()
    yield s
    await s.shutdown()


@pytest.mark.asyncio
async def test010_call_round_trips_request(shim):
    resp, notifs = await shim.call(
        {"jsonrpc": "2.0", "id": "client-id-1", "method": "ping", "params": {"x": 1}}
    )
    assert resp is not None
    # The shim must restore the client's original id, not leak the rewritten one.
    assert resp["id"] == "client-id-1"
    assert resp["result"] == {"echo": {"x": 1}}


@pytest.mark.asyncio
async def test020_id_rewriting_avoids_collisions(shim):
    """Two concurrent calls with the same client id resolve to the right futures."""
    a = shim.call({"jsonrpc": "2.0", "id": "shared", "method": "slow", "params": {"v": "a"}})
    b = shim.call({"jsonrpc": "2.0", "id": "shared", "method": "ping", "params": {"v": "b"}})
    res_a, res_b = await asyncio.gather(a, b)
    assert res_a[0]["id"] == "shared"
    assert res_b[0]["id"] == "shared"
    # Each got its own params back.
    assert res_a[0]["result"] == {"echo": {"v": "a"}}
    assert res_b[0]["result"] == {"echo": {"v": "b"}}


@pytest.mark.asyncio
async def test030_notification_returns_none(shim):
    resp, notifs = await shim.call(
        {"jsonrpc": "2.0", "method": "notifications/initialized"}
    )
    assert resp is None


@pytest.mark.asyncio
async def test040_concurrent_calls_share_one_child(shim):
    """All calls go to the same upstream pid: that's the multiplex property."""
    pid = shim.process.pid
    await asyncio.gather(*[
        shim.call({"jsonrpc": "2.0", "id": i, "method": "ping"}) for i in range(10)
    ])
    assert shim.process.pid == pid


@pytest.mark.asyncio
async def test050_orphan_response_does_not_crash(shim):
    """If the upstream emits a response with an unknown id, it's ignored."""
    # Manually inject a fake frame as if it came from the child.
    shim._dispatch({"jsonrpc": "2.0", "id": "no-such-id", "result": {}})
    # The shim is still healthy.
    resp, _ = await shim.call({"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert resp["id"] == 1


@pytest.mark.asyncio
async def test060_call_after_shutdown_raises(shim):
    await shim.shutdown()
    with pytest.raises(ConnectionError):
        await shim.call({"jsonrpc": "2.0", "id": 1, "method": "ping"})


def test070_stderr_to_notification_shape():
    notif = stderr_to_notification("upstream warning text")
    assert notif["jsonrpc"] == "2.0"
    assert notif["method"] == "notifications/message"
    assert notif["params"]["data"] == "upstream warning text"
