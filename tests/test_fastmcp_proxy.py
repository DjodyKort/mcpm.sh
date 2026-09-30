"""
Test cases for FastMCP proxy integration with different server types.
"""

from unittest.mock import Mock, patch

import pytest

from mcpm.core.schema import CustomServerConfig, RemoteServerConfig, STDIOServerConfig
from mcpm.fastmcp_integration.proxy import MCPMProxyFactory, joined_instructions


class TestFastMCPProxy:
    @pytest.mark.asyncio
    async def test_proxy_stdio_server(self):
        """Test proxy configuration for STDIO server."""
        server = STDIOServerConfig(
            name="test-stdio", command="python", args=["-m", "test_server"], env={"API_KEY": "test123"}
        )

        factory = MCPMProxyFactory(instructions_probe=None)
        with patch("mcpm.fastmcp_integration.proxy.create_proxy") as mock_fastmcp:
            mock_proxy = Mock()
            mock_fastmcp.return_value = mock_proxy

            await factory.create_proxy_for_servers([server], "test")

            # Verify the proxy config
            mock_fastmcp.assert_called_once()
            config = mock_fastmcp.call_args[0][0]
            # Each backend negotiates its own protocol era: mirroring a modern
            # client's era leaves a handshake-only backend with no tools.
            assert mock_fastmcp.call_args.kwargs["mode"] == "auto"

            assert hasattr(config, "mcpServers")
            assert "test-stdio" in config.mcpServers

            server_config = config.mcpServers["test-stdio"]
            # Command should be a string with args properly quoted
            assert server_config.command == "python"
            assert server_config.args == ["-m", "test_server"]
            assert server_config.env == {"MCPM_STDIO_SERVER": "true", "API_KEY": "test123"}

    @pytest.mark.asyncio
    async def test_proxy_remote_server(self):
        """Test proxy configuration for RemoteServerConfig (HTTP/SSE)."""
        server = RemoteServerConfig(
            name="test-remote", url="https://api.example.com/mcp", headers={"Authorization": "Bearer token123"}
        )

        factory = MCPMProxyFactory(instructions_probe=None)
        with patch("mcpm.fastmcp_integration.proxy.create_proxy") as mock_fastmcp:
            mock_proxy = Mock()
            mock_fastmcp.return_value = mock_proxy

            await factory.create_proxy_for_servers([server], "test")

            # Verify the proxy config
            config = mock_fastmcp.call_args[0][0]

            assert "test-remote" in config.mcpServers
            server_config = config.mcpServers["test-remote"]
            assert server_config.url == "https://api.example.com/mcp"
            assert server_config.headers == {"Authorization": "Bearer token123"}
            # transport field is not included in our config - FastMCP handles it automatically

    @pytest.mark.asyncio
    async def test_proxy_custom_server_skipped(self):
        """Test that CustomServerConfig is skipped (not processed by proxy)."""
        custom_config = {
            "url": "wss://custom.example.com/mcp",
            "transport": "websocket",
            "custom_field": "custom_value",
        }
        server = CustomServerConfig(name="test-custom", config=custom_config)

        factory = MCPMProxyFactory(instructions_probe=None)

        # This should raise an exception since CustomServerConfig is skipped
        # and no supported servers remain for the proxy
        with pytest.raises(ValueError, match="No supported servers to proxy"):
            await factory.create_proxy_for_servers([server], "test")

    @pytest.mark.asyncio
    async def test_proxy_mixed_servers(self):
        """Test proxy configuration with mixed server types."""
        servers = [
            STDIOServerConfig(name="stdio-server", command="node", args=["server.js"]),
            RemoteServerConfig(name="http-server", url="https://api.example.com/mcp"),
            CustomServerConfig(name="custom-server", config={"special": "config"}),
        ]

        factory = MCPMProxyFactory(instructions_probe=None)
        with patch("mcpm.fastmcp_integration.proxy.create_proxy") as mock_fastmcp:
            mock_proxy = Mock()
            mock_fastmcp.return_value = mock_proxy

            await factory.create_proxy_for_servers(servers, "mixed")

            # Verify only standard servers are in the config (CustomServerConfig is skipped)
            config = mock_fastmcp.call_args[0][0]

            assert len(config.mcpServers) == 2  # Only stdio and http servers
            assert "stdio-server" in config.mcpServers
            assert "http-server" in config.mcpServers
            assert "custom-server" not in config.mcpServers  # Skipped

            # Verify each server has correct config
            assert config.mcpServers["stdio-server"].command == "node"
            assert config.mcpServers["stdio-server"].args == ["server.js"]
            assert config.mcpServers["http-server"].url == "https://api.example.com/mcp"

    @pytest.mark.asyncio
    async def test_proxy_auth_middleware_stdio_mode(self):
        """Test that auth middleware is skipped in stdio mode."""
        server = STDIOServerConfig(name="test", command="test")

        # Create factory with auth enabled
        factory = MCPMProxyFactory(auth_enabled=True, api_key="secret", instructions_probe=None)

        with patch("mcpm.fastmcp_integration.proxy.create_proxy") as mock_fastmcp:
            mock_proxy = Mock()
            mock_proxy.add_middleware = Mock()
            mock_fastmcp.return_value = mock_proxy

            # Create proxy in stdio mode (default)
            await factory.create_proxy_for_servers([server], stdio_mode=True)

            # Check that auth middleware was NOT added
            middleware_types = [type(call[0][0]).__name__ for call in mock_proxy.add_middleware.call_args_list]
            assert "MCPMAuthMiddleware" not in middleware_types

    @pytest.mark.asyncio
    async def test_proxy_auth_middleware_http_mode(self):
        """Test that auth middleware is added in HTTP mode."""
        server = RemoteServerConfig(name="test", url="http://example.com")

        # Create factory with auth enabled
        factory = MCPMProxyFactory(auth_enabled=True, api_key="secret", instructions_probe=None)

        with patch("mcpm.fastmcp_integration.proxy.create_proxy") as mock_fastmcp:
            mock_proxy = Mock()
            mock_proxy.add_middleware = Mock()
            mock_fastmcp.return_value = mock_proxy

            # Create proxy in HTTP mode
            await factory.create_proxy_for_servers([server], stdio_mode=False)

            # Check that auth middleware WAS added
            middleware_types = [type(call[0][0]).__name__ for call in mock_proxy.add_middleware.call_args_list]
            assert "MCPMAuthMiddleware" in middleware_types


class TestBackendInstructions:
    """FastMCP.as_proxy drops a backend's instructions; the factory passes them on."""

    @staticmethod
    def _probe(answers):
        asked = []

        async def probe(name, config):
            asked.append(name)
            return answers.get(name)

        return probe, asked

    @pytest.mark.asyncio
    async def test_a_single_server_keeps_its_instructions_verbatim(self):
        probe, _ = self._probe({"odh": "Use odoo_psql instead of psql."})
        factory = MCPMProxyFactory(instructions_probe=probe)
        proxy = await factory.create_proxy_for_servers([STDIOServerConfig(name="odh", command="odh-mcp")], "odh")
        assert proxy.instructions == "Use odoo_psql instead of psql."

    @pytest.mark.asyncio
    async def test_a_profile_joins_each_server_under_its_name(self):
        probe, _ = self._probe({"a": "Tools for A.", "c": "Tools for C."})
        servers = [STDIOServerConfig(name=name, command=name) for name in ("a", "b", "c")]
        proxy = await MCPMProxyFactory(instructions_probe=probe).create_proxy_for_servers(servers, "p")
        assert proxy.instructions == "## a\nTools for A.\n\n## c\nTools for C."

    @pytest.mark.asyncio
    async def test_a_remote_server_is_not_probed(self):
        probe, asked = self._probe({})
        servers = [
            STDIOServerConfig(name="local", command="local"),
            RemoteServerConfig(name="remote", url="https://example.com/mcp"),
        ]
        await MCPMProxyFactory(instructions_probe=probe).create_proxy_for_servers(servers, "p")
        assert asked == ["local"]

    def test_no_instructions_anywhere_leave_none(self):
        assert joined_instructions({"a": None}) is None
        assert joined_instructions({"a": None, "b": ""}) is None
