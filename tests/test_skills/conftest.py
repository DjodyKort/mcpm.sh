"""Shared fixtures for skills tests."""

import pytest

SAMPLE_SKILL_MD = """---
name: code-review
description: "Automated code review with style and correctness checks. Use when reviewing pull requests."
globs: "src/**/*.py,src/**/*.ts"
activation: auto
priority: 10
license: MIT
metadata:
  author: testuser
  version: "1.0.0"
  tags: "review,quality"
allowed-tools: "Read Write Bash(git:*)"
---

## Code Review Instructions

When reviewing code, check for:
1. Style consistency
2. Potential bugs
3. Test coverage

Run `scripts/check.sh` for automated checks.
"""

SAMPLE_RULE_MD = """---
name: coding-standards
description: "Enforce coding standards across all files."
activation: always
---

Always use 4 spaces for indentation.
Never use wildcard imports.
"""

SAMPLE_MINIMAL_SKILL_MD = """---
name: minimal-skill
description: "A minimal skill for testing."
---

Do the thing.
"""

SAMPLE_AGENT_SKILL_MD = """---
name: agent-only
description: "Skill that agents must explicitly choose to load."
activation: agent
globs: "*.md"
---

Agent-requested instructions here.
"""

SAMPLE_MANUAL_SKILL_MD = """---
name: manual-invoke
description: "Skill that requires manual user invocation."
activation: manual
---

Manual invocation instructions.
"""


@pytest.fixture
def skills_repo(tmp_path):
    """Create a complete skills repository for testing."""
    # Manifest
    manifest = tmp_path / "mcpm-skills.yaml"
    manifest.write_text("name: test-skills\ndescription: Test skills repo\nauthor: tester\nversion: '1.0.0'\n")

    # Skills
    skill_dir = tmp_path / "skills" / "code-review"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(SAMPLE_SKILL_MD)

    minimal_dir = tmp_path / "skills" / "minimal-skill"
    minimal_dir.mkdir(parents=True)
    (minimal_dir / "SKILL.md").write_text(SAMPLE_MINIMAL_SKILL_MD)

    agent_dir = tmp_path / "skills" / "agent-only"
    agent_dir.mkdir(parents=True)
    (agent_dir / "SKILL.md").write_text(SAMPLE_AGENT_SKILL_MD)

    manual_dir = tmp_path / "skills" / "manual-invoke"
    manual_dir.mkdir(parents=True)
    (manual_dir / "SKILL.md").write_text(SAMPLE_MANUAL_SKILL_MD)

    # Rules
    rule_dir = tmp_path / "rules" / "coding-standards"
    rule_dir.mkdir(parents=True)
    (rule_dir / "SKILL.md").write_text(SAMPLE_RULE_MD)

    # Profiles dir
    (tmp_path / "profiles").mkdir(exist_ok=True)

    return tmp_path


@pytest.fixture
def single_skill_path(tmp_path):
    """Create a single skill file for unit testing."""
    skill_dir = tmp_path / "skills" / "code-review"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(SAMPLE_SKILL_MD)
    return skill_file
