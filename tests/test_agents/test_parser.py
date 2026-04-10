"""Tests for AGENT.md parser."""

import pytest

from mcpm.skills.agents.parser import discover_agents, parse_agent_file

from .conftest import SAMPLE_AGENT_MD, SAMPLE_MINIMAL_AGENT_MD


class TestParseAgentFile:
    def test_parse_full(self, tmp_path):
        agent_dir = tmp_path / "agents" / "code-reviewer"
        agent_dir.mkdir(parents=True)
        (agent_dir / "AGENT.md").write_text(SAMPLE_AGENT_MD)

        agent = parse_agent_file(agent_dir / "AGENT.md")
        assert agent.frontmatter.name == "code-reviewer"
        assert agent.frontmatter.model == "sonnet"
        assert "Read" in agent.frontmatter.tools
        assert agent.frontmatter.readonly is True
        assert "code review specialist" in agent.body

    def test_parse_minimal(self, tmp_path):
        agent_dir = tmp_path / "agents" / "simple-agent"
        agent_dir.mkdir(parents=True)
        (agent_dir / "AGENT.md").write_text(SAMPLE_MINIMAL_AGENT_MD)

        agent = parse_agent_file(agent_dir / "AGENT.md")
        assert agent.frontmatter.name == "simple-agent"
        assert agent.frontmatter.model is None
        assert agent.frontmatter.tools == []

    def test_nonexistent_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            parse_agent_file(tmp_path / "missing.md")

    def test_no_frontmatter(self, tmp_path):
        f = tmp_path / "AGENT.md"
        f.write_text("Just text, no frontmatter.")
        with pytest.raises(ValueError, match="No YAML frontmatter"):
            parse_agent_file(f)


class TestDiscoverAgents:
    def test_discover_all(self, agents_repo):
        found = discover_agents(agents_repo)
        names = {a.name for a in found}
        assert "code-reviewer" in names
        assert "simple-agent" in names
        assert "auto-agent" in names
        assert len(found) == 3

    def test_discover_empty(self, tmp_path):
        (tmp_path / "agents").mkdir()
        assert discover_agents(tmp_path) == []

    def test_discover_no_dir(self, tmp_path):
        assert discover_agents(tmp_path) == []

    def test_skips_missing_agent_md(self, tmp_path):
        (tmp_path / "agents" / "empty-dir").mkdir(parents=True)
        assert discover_agents(tmp_path) == []
