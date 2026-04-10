"""Tests for agent linting."""

from mcpm.skills.agents.lint import lint_agent, lint_agents
from mcpm.skills.agents.parser import parse_agent_file

from .conftest import SAMPLE_AGENT_MD


def _make_agent(tmp_path, name, content):
    agent_dir = tmp_path / "agents" / name
    agent_dir.mkdir(parents=True)
    (agent_dir / "AGENT.md").write_text(content)
    return parse_agent_file(agent_dir / "AGENT.md")


class TestLintAgent:
    def test_valid_agent_passes(self, tmp_path):
        agent = _make_agent(tmp_path, "code-reviewer", SAMPLE_AGENT_MD)
        result = lint_agent(agent)
        assert not result.has_errors

    def test_short_description(self, tmp_path):
        content = '---\nname: short\ndescription: "Too short"\n---\n\nBody.'
        agent = _make_agent(tmp_path, "short", content)
        result = lint_agent(agent)
        assert any("short" in m.message.lower() for m in result.warnings)

    def test_empty_body(self, tmp_path):
        content = '---\nname: empty-body\ndescription: "An agent with empty body."\n---\n'
        agent = _make_agent(tmp_path, "empty-body", content)
        result = lint_agent(agent)
        assert any("empty" in m.message.lower() for m in result.warnings)

    def test_tool_conflict(self, tmp_path):
        content = '---\nname: conflict\ndescription: "Agent with tool conflicts."\ntools: [Read, Write]\ndisallowed-tools: [Write]\n---\n\nBody.'
        agent = _make_agent(tmp_path, "conflict", content)
        result = lint_agent(agent)
        assert result.has_errors
        assert any("both allowed and disallowed" in m.message for m in result.errors)

    def test_readonly_fullauto_conflict(self, tmp_path):
        content = '---\nname: conflict2\ndescription: "Conflicting readonly and full-auto."\npermission-mode: full-auto\nreadonly: true\n---\n\nBody.'
        agent = _make_agent(tmp_path, "conflict2", content)
        result = lint_agent(agent)
        assert any("conflicts" in m.message.lower() for m in result.warnings)

    def test_name_directory_mismatch(self, tmp_path):
        content = '---\nname: wrong-name\ndescription: "Name mismatch."\n---\n\nBody.'
        agent = _make_agent(tmp_path, "actual-name", content)
        result = lint_agent(agent)
        assert result.has_errors

    def test_max_turns_out_of_range(self, tmp_path):
        content = '---\nname: big-turns\ndescription: "Agent with huge max turns."\nmax-turns: 999\n---\n\nBody.'
        agent = _make_agent(tmp_path, "big-turns", content)
        result = lint_agent(agent)
        assert any("range" in m.message.lower() for m in result.warnings)


class TestLintAgents:
    def test_duplicate_names(self, tmp_path):
        content = '---\nname: dupe\ndescription: "Duplicate agent."\n---\n\nBody.'
        a1 = _make_agent(tmp_path, "dupe", content)
        a2_dir = tmp_path / "agents" / "dupe2"
        a2_dir.mkdir(parents=True)
        (a2_dir / "AGENT.md").write_text(content)
        a2 = parse_agent_file(a2_dir / "AGENT.md")
        result = lint_agents([a1, a2])
        assert any("Duplicate" in m.message for m in result.errors)
