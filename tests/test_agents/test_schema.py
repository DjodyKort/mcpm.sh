"""Tests for agent schema validation."""

import pytest
from pydantic import ValidationError

from mcpm.skills.agents.schema import AgentFrontmatter


class TestAgentFrontmatter:
    def test_valid_minimal(self):
        fm = AgentFrontmatter(name="test-agent", description="A test agent.")
        assert fm.name == "test-agent"
        assert fm.model is None
        assert fm.tools == []
        assert fm.readonly is False

    def test_valid_full(self):
        fm = AgentFrontmatter(
            name="code-reviewer",
            description="Reviews code for bugs.",
            model="sonnet",
            tools=["Read", "Grep"],
            disallowed_tools=["Write"],
            max_turns=30,
            mcp_servers=["github"],
            skills=["code-review"],
            permission_mode="plan",
            readonly=True,
            effort="medium",
            color="blue",
        )
        assert fm.model == "sonnet"
        assert fm.tools == ["Read", "Grep"]
        assert fm.mcp_servers == ["github"]

    def test_invalid_name_uppercase(self):
        with pytest.raises(ValidationError, match="lowercase"):
            AgentFrontmatter(name="Code-Reviewer", description="Test")

    def test_invalid_name_consecutive_hyphens(self):
        with pytest.raises(ValidationError, match="consecutive"):
            AgentFrontmatter(name="code--reviewer", description="Test")

    def test_invalid_description_empty(self):
        with pytest.raises(ValidationError, match="1-1024"):
            AgentFrontmatter(name="test", description="")

    def test_valid_permission_modes(self):
        for mode in ["default", "plan", "full-auto"]:
            fm = AgentFrontmatter(name="test", description="Test", permission_mode=mode)
            assert fm.permission_mode == mode

    def test_invalid_permission_mode(self):
        with pytest.raises(ValidationError):
            AgentFrontmatter(name="test", description="Test", permission_mode="invalid")
