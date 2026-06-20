"""Provider-contract tests (no mcpm core, no network needed)."""
from __future__ import annotations

from mcpm_compression.providers import get_provider, provider_names
from mcpm_compression.schema import CompressionConfig


def test01_registry_has_three_providers():
    assert set(provider_names()) == {"headroom", "rtk-only", "none"}


def test02_headroom_mcp_and_runtime():
    p = get_provider("headroom")
    cfg = CompressionConfig(provider="headroom", options={"port": 9000})
    mcp = p.mcp_server_config(cfg)
    assert mcp["command"] == "headroom" and mcp["args"] == ["mcp", "serve"]
    assert mcp["proxy_mode"] == "direct"
    rt = p.runtime_spec(cfg)
    assert rt.kind == "proxy" and rt.port == 9000
    assert rt.env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:9000"
    assert rt.env["ENABLE_TOOL_SEARCH"] == "true"
    assert rt.env["HEADROOM_TELEMETRY"] == "off"


def test03_headroom_generates_two_artifacts():
    p = get_provider("headroom")
    arts = p.activation_artifacts(CompressionConfig(provider="headroom"))
    assert len(arts) == 2
    assert any(a.path.name.endswith(".plist") for a in arts)
    assert any(a.path.name == "compression-env.sh" for a in arts)
    # plist must contain the proxy invocation
    plist = next(a for a in arts if a.path.name.endswith(".plist"))
    assert "proxy" in plist.content and "8787" in plist.content


def test04_rtk_only_has_no_mcp_no_artifacts():
    p = get_provider("rtk-only")
    cfg = CompressionConfig(provider="rtk-only")
    assert p.mcp_server_config(cfg) is None
    assert p.activation_artifacts(cfg) == []
    assert p.runtime_spec(cfg).kind == "hook"


def test05_none_is_inert():
    p = get_provider("none")
    cfg = CompressionConfig(provider="none")
    assert p.mcp_server_config(cfg) is None
    assert p.activation_artifacts(cfg) == []
    assert p.health(cfg)["ok"] is True
