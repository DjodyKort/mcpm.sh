"""Phase 1 router-and-direct-http tests.

Covers `proxy_mode` resolution and `to_client_format` branching for the
schema additions. Stdio servers stay on the legacy `mcpm run` shape until
the router (Phase 2) lands; HTTP servers resolve to `direct` so the native
client OAuth flow is preserved.
"""

import os
import tempfile

import pytest

from mcpm.clients.base import JSONClientManager
from mcpm.clients.managers.claude_desktop import ClaudeDesktopManager
from mcpm.core.schema import (
    BaseServerConfig,
    CustomServerConfig,
    RemoteServerConfig,
    STDIOServerConfig,
)


class _FakeManager(JSONClientManager):
    """Minimal concrete JSONClientManager for unit tests."""

    client_key = "fake"
    display_name = "Fake"
    download_url = ""

    def __init__(self, supports_http_mcp: bool = True):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as f:
            f.write(b"{}")
            self.config_path = f.name
        super().__init__(config_path_override=self.config_path)
        self.supports_http_mcp = supports_http_mcp

    def get_client_info(self):
        return {"name": self.display_name, "config_file": self.config_path}

    def is_client_installed(self) -> bool:
        return True


@pytest.fixture
def manager():
    m = _FakeManager()
    yield m
    if os.path.exists(m.config_path):
        os.unlink(m.config_path)


@pytest.fixture
def stdio_only_manager():
    m = _FakeManager(supports_http_mcp=False)
    yield m
    if os.path.exists(m.config_path):
        os.unlink(m.config_path)


def test010_schema_proxy_mode_default_is_auto():
    config = STDIOServerConfig(name="x", command="echo")
    assert config.proxy_mode == "auto"
    assert config.requires_session_pinning is False


def test020_schema_loads_old_servers_json_without_new_fields():
    """Pydantic v2 defaults let pre-proxy_mode servers.json round-trip."""
    raw = {"name": "old", "command": "echo", "args": ["hi"]}
    config = STDIOServerConfig.model_validate(raw)
    assert config.proxy_mode == "auto"
    assert config.requires_session_pinning is False


def test030_schema_remote_loads_old_format():
    raw = {"name": "old-remote", "url": "https://example.com/mcp"}
    config = RemoteServerConfig.model_validate(raw)
    assert config.proxy_mode == "auto"


def test040_resolve_auto_for_remote_returns_direct(manager):
    server = RemoteServerConfig(name="clickup", url="https://mcp.clickup.com/mcp")
    assert manager._resolve_proxy_mode(server) == "direct"


def test050_resolve_auto_for_stdio_returns_legacy_in_phase_one(manager):
    """Phase 1: stdio stays on legacy until router exists (Phase 2 flips this)."""
    server = STDIOServerConfig(name="x", command="echo")
    assert manager._resolve_proxy_mode(server) == "legacy"


def test060_resolve_auto_stdio_for_stdio_only_client_returns_bridge(stdio_only_manager):
    """Phase 5: stdio-only clients with stdio servers route through the bridge
    so workers are shared across clients. (Phase 1 returned legacy here.)"""
    server = STDIOServerConfig(name="x", command="echo")
    assert stdio_only_manager._resolve_proxy_mode(server) == "bridge"


def test070_resolve_auto_remote_for_stdio_only_client_returns_legacy(stdio_only_manager):
    """A client that can't speak HTTP MCP should not get the direct branch."""
    server = RemoteServerConfig(name="clickup", url="https://mcp.clickup.com/mcp")
    assert stdio_only_manager._resolve_proxy_mode(server) == "legacy"


def test080_resolve_explicit_override_wins(manager):
    server = STDIOServerConfig(name="x", command="echo", proxy_mode="direct")
    assert manager._resolve_proxy_mode(server) == "direct"


def test090_resolve_explicit_legacy_overrides_remote(manager):
    server = RemoteServerConfig(
        name="clickup",
        url="https://mcp.clickup.com/mcp",
        proxy_mode="legacy",
    )
    assert manager._resolve_proxy_mode(server) == "legacy"


def test100_to_client_format_direct_remote_writes_raw_http_url(manager):
    server = RemoteServerConfig(
        name="clickup",
        url="https://mcp.clickup.com/mcp",
        headers={"Authorization": "Bearer token"},
    )
    result = manager.to_client_format(server)
    assert result == {
        "type": "http",
        "url": "https://mcp.clickup.com/mcp",
        "headers": {"Authorization": "Bearer token"},
    }


def test110_to_client_format_direct_remote_omits_empty_headers(manager):
    server = RemoteServerConfig(name="figma", url="https://mcp.figma.com/mcp")
    result = manager.to_client_format(server)
    assert result == {"type": "http", "url": "https://mcp.figma.com/mcp"}
    assert "headers" not in result


def test120_to_client_format_direct_stdio_writes_raw_command(manager):
    server = STDIOServerConfig(
        name="local",
        command="my-server",
        args=["--flag"],
        env={"FOO": "bar"},
        proxy_mode="direct",
    )
    result = manager.to_client_format(server)
    assert result == {
        "command": "my-server",
        "args": ["--flag"],
        "env": {"FOO": "bar"},
    }


def test130_to_client_format_legacy_emits_mcpm_run_wrapper(manager):
    """`legacy` mode is the v1/v2 escape hatch: `{command: mcpm, args: [run, X]}`."""
    server = STDIOServerConfig(name="local", command="my-server", args=["--flag"])
    result = manager.to_client_format(server)
    assert result == {"command": "mcpm", "args": ["run", "local"]}


def test131_to_client_format_explicit_legacy_remote_emits_mcpm_run(manager):
    """Even an HTTP server forced into legacy uses the mcpm run wrapper."""
    server = RemoteServerConfig(
        name="clickup", url="https://mcp.clickup.com/mcp", proxy_mode="legacy"
    )
    result = manager.to_client_format(server)
    assert result == {"command": "mcpm", "args": ["run", "clickup"]}


def test132_to_client_format_bridge_emits_mcpm_bridge(manager):
    server = STDIOServerConfig(
        name="anna", command="anna-cli", args=[], proxy_mode="bridge"
    )
    result = manager.to_client_format(server)
    assert result == {"command": "mcpm", "args": ["bridge", "anna"]}


def test133_resolve_stdio_server_on_stdio_only_client_returns_bridge(stdio_only_manager):
    """Phase 5: stdio-only clients with stdio servers prefer bridge over legacy."""
    server = STDIOServerConfig(name="anna", command="anna-cli")
    assert stdio_only_manager._resolve_proxy_mode(server) == "bridge"


def test134_resolve_remote_on_stdio_only_client_returns_legacy(stdio_only_manager):
    """Stdio-only client + Remote: bridge can't proxy outbound HTTP, so we
    keep legacy. Client-specific overrides (e.g. Claude Desktop's mcp-proxy)
    intercept before this resolver runs."""
    server = RemoteServerConfig(name="clickup", url="https://mcp.clickup.com/mcp")
    assert stdio_only_manager._resolve_proxy_mode(server) == "legacy"


def test140_to_client_format_strips_internal_fields_from_custom(manager):
    """Custom configs go through to_dict; mcpm-internal fields must not leak."""
    server = CustomServerConfig(name="weird", config={"some": "client-specific"})
    result = manager.to_client_format(server)
    assert "name" not in result
    assert "profile_tags" not in result
    assert "proxy_mode" not in result
    assert "requires_session_pinning" not in result


def test150_claude_desktop_keeps_mcp_proxy_shim_for_remote():
    """Claude Desktop's existing override wraps HTTP servers via mcp-proxy.

    The new proxy_mode plumbing must not change that legacy behavior in
    Phase 1 (recent Claude Desktop builds support HTTP, but flipping that
    default is out of Phase 1's scope).
    """
    with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as f:
        f.write(b"{}")
        path = f.name
    try:
        manager = ClaudeDesktopManager(config_path_override=path)
        server = RemoteServerConfig(name="clickup", url="https://mcp.clickup.com/mcp")
        result = manager.to_client_format(server)
        assert result["command"] == "uvx"
        assert "mcp-proxy" in result["args"]
        assert "type" not in result
    finally:
        os.unlink(path)


def test160_base_config_to_dict_round_trips_proxy_mode():
    """servers.json round-trip must persist proxy_mode + pinning if set."""
    server = STDIOServerConfig(
        name="x",
        command="echo",
        proxy_mode="direct",
        requires_session_pinning=True,
    )
    raw = server.to_dict()
    assert raw["proxy_mode"] == "direct"
    assert raw["requires_session_pinning"] is True

    rehydrated = STDIOServerConfig.model_validate(raw)
    assert rehydrated.proxy_mode == "direct"
    assert rehydrated.requires_session_pinning is True


def test170_proxy_mode_literal_rejects_unknown_value():
    with pytest.raises(Exception):
        STDIOServerConfig(name="x", command="echo", proxy_mode="bogus")  # type: ignore[arg-type]


def test180_base_server_config_proxy_mode_field_visible():
    """Sanity: mypy won't help here so make sure the attr exists at runtime."""
    fields = BaseServerConfig.model_fields
    assert "proxy_mode" in fields
    assert "requires_session_pinning" in fields
