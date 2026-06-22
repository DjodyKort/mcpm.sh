"""Provider-contract tests (no mcpm core, no network needed)."""
from __future__ import annotations

from mcpm_compression.providers import get_provider, provider_names
from mcpm_compression.schema import CompressionConfig, ContextRule


def test01_registry_has_three_providers():
    assert set(provider_names()) == {"headroom", "rtk-only", "none"}


def test02_headroom_mcp_and_runtime():
    p = get_provider("headroom")
    cfg = CompressionConfig(provider="headroom")
    cfg.presets["interactive"].port = 9000  # port is now an attribute of the active preset
    mcp = p.mcp_server_config(cfg)
    assert mcp["command"] == "headroom" and mcp["args"] == ["mcp", "serve"]
    assert mcp["proxy_mode"] == "direct"
    rt = p.runtime_spec(cfg)
    assert rt.kind == "proxy" and rt.port == 9000
    assert rt.env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:9000"
    assert rt.env["ENABLE_TOOL_SEARCH"] == "true"
    assert rt.env["HEADROOM_TELEMETRY"] == "off"


def test03_headroom_generates_env_snippet_and_shim():
    # Phase 3+5: no hand-rolled plist — a 0o600 env snippet + a 0o644 shell shim.
    p = get_provider("headroom")
    arts = p.activation_artifacts(CompressionConfig(provider="headroom"))
    by_name = {a.path.name: a for a in arts}
    assert set(by_name) == {"compression-env.sh", "compression-shims.zsh"}

    snippet = by_name["compression-env.sh"]
    assert snippet.mode == 0o600
    assert 'ANTHROPIC_BASE_URL="http://127.0.0.1:8787"' in snippet.content
    assert 'HEADROOM_MODE="cache"' in snippet.content

    shim = by_name["compression-shims.zsh"]
    assert shim.mode == 0o644  # sourced, non-secret
    assert "hrclaude() { mcpm compression run -- " in shim.content
    assert "hrup()" in shim.content and "hrdown()" in shim.content


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


def test06_resolved_provider_matches_context_then_default():
    cfg = CompressionConfig(
        provider="headroom",
        contexts=[
            ContextRule(match="*/clients/*", provider="none"),
            ContextRule(match="*/oss/*", provider="rtk-only"),
        ],
    )
    assert cfg.resolved_provider("/Users/x/work/clients/acme") == "none"
    assert cfg.resolved_provider("/Users/x/oss/foo") == "rtk-only"
    assert cfg.resolved_provider("/Users/x/personal") == "headroom"  # falls back to default
