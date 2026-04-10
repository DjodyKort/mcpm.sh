"""Tests for agent transpilers."""

import json

from mcpm.skills.agents.parser import parse_agent_file
from mcpm.skills.agents.transpilers.claude_code import ClaudeCodeAgentTranspiler
from mcpm.skills.agents.transpilers.codex_cli import CodexCliAgentTranspiler
from mcpm.skills.agents.transpilers.cursor import CursorAgentTranspiler
from mcpm.skills.agents.transpilers.gemini_cli import GeminiCliAgentTranspiler
from mcpm.skills.agents.transpilers.roo_code import RooCodeAgentTranspiler
from mcpm.skills.agents.transpilers.vscode_copilot import VSCodeCopilotAgentTranspiler

from .conftest import SAMPLE_AGENT_MD, SAMPLE_MINIMAL_AGENT_MD


def _make_agent(tmp_path, name, content):
    agent_dir = tmp_path / "agents" / name
    agent_dir.mkdir(parents=True)
    (agent_dir / "AGENT.md").write_text(content)
    return parse_agent_file(agent_dir / "AGENT.md")


class TestClaudeCodeAgent:
    def test_output_path(self, tmp_path):
        agent = _make_agent(tmp_path, "code-reviewer", SAMPLE_AGENT_MD)
        path = ClaudeCodeAgentTranspiler().get_output_path(agent, tmp_path)
        assert path == tmp_path / ".claude" / "agents" / "code-reviewer.md"

    def test_field_mapping(self, tmp_path):
        agent = _make_agent(tmp_path, "code-reviewer", SAMPLE_AGENT_MD)
        result = ClaudeCodeAgentTranspiler().transpile(agent, tmp_path)
        assert "name: code-reviewer" in result.content
        assert "model: sonnet" in result.content
        assert "tools:" in result.content
        assert "disallowedTools:" in result.content
        assert "maxTurns: 30" in result.content
        assert "mcpServers:" in result.content
        assert "skills:" in result.content
        assert "permissionMode: plan" in result.content  # readonly=true maps to plan
        assert "effort: medium" in result.content

    def test_no_warnings(self, tmp_path):
        agent = _make_agent(tmp_path, "code-reviewer", SAMPLE_AGENT_MD)
        result = ClaudeCodeAgentTranspiler().transpile(agent, tmp_path)
        assert result.warnings == []


class TestCursorAgent:
    def test_output_path(self, tmp_path):
        agent = _make_agent(tmp_path, "code-reviewer", SAMPLE_AGENT_MD)
        path = CursorAgentTranspiler().get_output_path(agent, tmp_path)
        assert path == tmp_path / ".cursor" / "agents" / "code-reviewer.md"

    def test_readonly_mapping(self, tmp_path):
        agent = _make_agent(tmp_path, "code-reviewer", SAMPLE_AGENT_MD)
        result = CursorAgentTranspiler().transpile(agent, tmp_path)
        assert "readonly: true" in result.content

    def test_unsupported_field_warnings(self, tmp_path):
        agent = _make_agent(tmp_path, "code-reviewer", SAMPLE_AGENT_MD)
        result = CursorAgentTranspiler().transpile(agent, tmp_path)
        assert any("tools" in w for w in result.warnings)
        assert any("mcp-servers" in w for w in result.warnings)


class TestCodexCliAgent:
    def test_output_path(self, tmp_path):
        agent = _make_agent(tmp_path, "code-reviewer", SAMPLE_AGENT_MD)
        path = CodexCliAgentTranspiler().get_output_path(agent, tmp_path)
        assert path == tmp_path / ".codex" / "agents" / "code-reviewer.toml"

    def test_toml_format(self, tmp_path):
        agent = _make_agent(tmp_path, "code-reviewer", SAMPLE_AGENT_MD)
        result = CodexCliAgentTranspiler().transpile(agent, tmp_path)
        assert 'name = "code-reviewer"' in result.content
        assert 'developer_instructions = """' in result.content
        assert 'model = "sonnet"' in result.content
        assert 'sandbox_mode = "sandbox"' in result.content  # readonly maps to sandbox

    def test_mcp_servers_in_toml(self, tmp_path):
        agent = _make_agent(tmp_path, "code-reviewer", SAMPLE_AGENT_MD)
        result = CodexCliAgentTranspiler().transpile(agent, tmp_path)
        assert "[mcp_servers]" in result.content


class TestGeminiCliAgent:
    def test_output_path(self, tmp_path):
        agent = _make_agent(tmp_path, "code-reviewer", SAMPLE_AGENT_MD)
        path = GeminiCliAgentTranspiler().get_output_path(agent, tmp_path)
        assert path == tmp_path / ".gemini" / "agents" / "code-reviewer.md"

    def test_field_mapping(self, tmp_path):
        agent = _make_agent(tmp_path, "code-reviewer", SAMPLE_AGENT_MD)
        result = GeminiCliAgentTranspiler().transpile(agent, tmp_path)
        assert "name: code-reviewer" in result.content
        assert "model: sonnet" in result.content
        assert "tools:" in result.content
        assert "max_turns: 30" in result.content

    def test_unsupported_warnings(self, tmp_path):
        agent = _make_agent(tmp_path, "code-reviewer", SAMPLE_AGENT_MD)
        result = GeminiCliAgentTranspiler().transpile(agent, tmp_path)
        assert any("disallowed-tools" in w for w in result.warnings)


class TestVSCodeCopilotAgent:
    def test_output_path(self, tmp_path):
        agent = _make_agent(tmp_path, "code-reviewer", SAMPLE_AGENT_MD)
        path = VSCodeCopilotAgentTranspiler().get_output_path(agent, tmp_path)
        assert path == tmp_path / ".github" / "agents" / "code-reviewer.agent.md"

    def test_field_mapping(self, tmp_path):
        agent = _make_agent(tmp_path, "code-reviewer", SAMPLE_AGENT_MD)
        result = VSCodeCopilotAgentTranspiler().transpile(agent, tmp_path)
        assert "name: code-reviewer" in result.content
        assert "tools:" in result.content
        assert "mcp-servers:" in result.content


class TestRooCodeAgent:
    def test_output_path(self, tmp_path):
        agent = _make_agent(tmp_path, "code-reviewer", SAMPLE_AGENT_MD)
        assert RooCodeAgentTranspiler().get_output_path(agent, tmp_path) == tmp_path / ".roomodes"

    def test_transpile_all_json(self, tmp_path):
        agents = [
            _make_agent(tmp_path, "code-reviewer", SAMPLE_AGENT_MD),
            _make_agent(tmp_path, "simple-agent", SAMPLE_MINIMAL_AGENT_MD),
        ]
        result = RooCodeAgentTranspiler().transpile_all(agents, tmp_path)
        data = json.loads(result.content)
        assert "customModes" in data
        assert len(data["customModes"]) == 2
        slugs = {m["slug"] for m in data["customModes"]}
        assert "code-reviewer" in slugs
        assert "simple-agent" in slugs

    def test_tool_group_mapping(self, tmp_path):
        agent = _make_agent(tmp_path, "code-reviewer", SAMPLE_AGENT_MD)
        result = RooCodeAgentTranspiler().transpile(agent, tmp_path)
        data = json.loads(result.content)
        group_names = [g[0] for g in data["groups"]]
        assert "read" in group_names
        assert "command" in group_names
        # Write/Edit are disallowed, but tool group mapping only looks at allowed tools
        # So "edit" should NOT be in groups since Write/Edit are not in tools
        assert "edit" not in group_names

    def test_minimal_agent_gets_all_groups(self, tmp_path):
        agent = _make_agent(tmp_path, "simple-agent", SAMPLE_MINIMAL_AGENT_MD)
        result = RooCodeAgentTranspiler().transpile(agent, tmp_path)
        data = json.loads(result.content)
        # No tools specified = all groups enabled
        group_names = [g[0] for g in data["groups"]]
        assert "read" in group_names
        assert "edit" in group_names
        assert "command" in group_names
        assert "mcp" in group_names
