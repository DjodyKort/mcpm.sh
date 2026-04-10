"""Shared fixtures for agent tests."""

import pytest

SAMPLE_AGENT_MD = """---
name: code-reviewer
description: "Reviews code for bugs, style issues, and security vulnerabilities."
model: sonnet
tools: [Read, Grep, Glob, Bash]
disallowed-tools: [Write, Edit]
max-turns: 30
mcp-servers: [github]
skills: [code-review]
readonly: true
effort: medium
metadata:
  author: testuser
  version: "1.0.0"
---

You are a code review specialist. Review code for correctness, security, and style.
"""

SAMPLE_MINIMAL_AGENT_MD = """---
name: simple-agent
description: "A simple agent for testing."
---

Do the thing.
"""

SAMPLE_FULL_AUTO_AGENT_MD = """---
name: auto-agent
description: "Agent with full-auto permissions for autonomous work."
model: opus
tools: [Read, Write, Edit, Bash, Grep, Glob]
permission-mode: full-auto
max-turns: 100
---

You have full autonomy. Complete the task independently.
"""


@pytest.fixture
def agents_repo(tmp_path):
    """Create a skills repo with agents for testing."""
    (tmp_path / "mcpm-skills.yaml").write_text("name: test-repo\n")
    (tmp_path / "skills").mkdir()
    (tmp_path / "rules").mkdir()
    (tmp_path / "agents").mkdir()

    agent_dir = tmp_path / "agents" / "code-reviewer"
    agent_dir.mkdir()
    (agent_dir / "AGENT.md").write_text(SAMPLE_AGENT_MD)

    simple_dir = tmp_path / "agents" / "simple-agent"
    simple_dir.mkdir()
    (simple_dir / "AGENT.md").write_text(SAMPLE_MINIMAL_AGENT_MD)

    auto_dir = tmp_path / "agents" / "auto-agent"
    auto_dir.mkdir()
    (auto_dir / "AGENT.md").write_text(SAMPLE_FULL_AUTO_AGENT_MD)

    return tmp_path
