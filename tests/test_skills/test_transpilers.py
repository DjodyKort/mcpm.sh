"""Tests for per-client skill transpilers."""

from mcpm.skills.parser import parse_skill_file
from mcpm.skills.transpiler import inject_managed_block
from mcpm.skills.transpilers.agents_md import AgentsMdTranspiler
from mcpm.skills.transpilers.claude_code import ClaudeCodeTranspiler
from mcpm.skills.transpilers.continue_dev import ContinueDevTranspiler
from mcpm.skills.transpilers.cursor import CursorTranspiler
from mcpm.skills.transpilers.jetbrains import JetBrainsTranspiler
from mcpm.skills.transpilers.vscode_copilot import VSCodeCopilotTranspiler
from mcpm.skills.transpilers.windsurf import WindsurfTranspiler

from .conftest import SAMPLE_AGENT_SKILL_MD, SAMPLE_MANUAL_SKILL_MD, SAMPLE_RULE_MD, SAMPLE_SKILL_MD


def _make_skill(tmp_path, name, content, subdir="skills"):
    """Helper to create a skill file and parse it."""
    skill_dir = tmp_path / subdir / name
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(content)
    return parse_skill_file(skill_file)


class TestClaudeCodeTranspiler:
    """Test Claude Code transpilation."""

    def test_skill_output_path(self, tmp_path):
        skill = _make_skill(tmp_path, "code-review", SAMPLE_SKILL_MD)
        transpiler = ClaudeCodeTranspiler()
        path = transpiler.get_output_path(skill, tmp_path)
        assert path == tmp_path / ".claude" / "skills" / "code-review" / "SKILL.md"

    def test_rule_output_path(self, tmp_path):
        rule = _make_skill(tmp_path, "coding-standards", SAMPLE_RULE_MD, subdir="rules")
        transpiler = ClaudeCodeTranspiler()
        path = transpiler.get_output_path(rule, tmp_path)
        assert path == tmp_path / ".claude" / "rules" / "coding-standards.md"

    def test_skill_frontmatter_mapping(self, tmp_path):
        """Test that canonical fields map to Claude Code fields correctly."""
        skill = _make_skill(tmp_path, "code-review", SAMPLE_SKILL_MD)
        transpiler = ClaudeCodeTranspiler()
        result = transpiler.transpile(skill, tmp_path)
        assert "name: code-review" in result.content
        assert "description:" in result.content
        assert "paths: src/**/*.py,src/**/*.ts" in result.content
        assert "allowed-tools: Read Write Bash(git:*)" in result.content

    def test_manual_maps_to_disable_model_invocation(self, tmp_path):
        """Test that manual activation maps to disable-model-invocation."""
        skill = _make_skill(tmp_path, "manual-invoke", SAMPLE_MANUAL_SKILL_MD)
        transpiler = ClaudeCodeTranspiler()
        result = transpiler.transpile(skill, tmp_path)
        assert "disable-model-invocation: true" in result.content

    def test_rule_no_name_description(self, tmp_path):
        """Test that rules don't include name/description in frontmatter."""
        rule = _make_skill(tmp_path, "coding-standards", SAMPLE_RULE_MD, subdir="rules")
        transpiler = ClaudeCodeTranspiler()
        result = transpiler.transpile(rule, tmp_path)
        assert "name:" not in result.content
        assert "4 spaces" in result.content


class TestCursorTranspiler:
    """Test Cursor transpilation."""

    def test_output_path(self, tmp_path):
        skill = _make_skill(tmp_path, "code-review", SAMPLE_SKILL_MD)
        transpiler = CursorTranspiler()
        path = transpiler.get_output_path(skill, tmp_path)
        assert path == tmp_path / ".cursor" / "rules" / "code-review" / "RULE.md"

    def test_always_activation(self, tmp_path):
        """Test that always activation maps to alwaysApply: true."""
        rule = _make_skill(tmp_path, "coding-standards", SAMPLE_RULE_MD, subdir="rules")
        transpiler = CursorTranspiler()
        result = transpiler.transpile(rule, tmp_path)
        assert "alwaysApply: true" in result.content

    def test_auto_activation_with_globs(self, tmp_path):
        """Test auto activation preserves description and globs."""
        skill = _make_skill(tmp_path, "code-review", SAMPLE_SKILL_MD)
        transpiler = CursorTranspiler()
        result = transpiler.transpile(skill, tmp_path)
        assert "description:" in result.content
        assert "globs:" in result.content
        assert "alwaysApply" not in result.content

    def test_agent_activation_no_globs(self, tmp_path):
        """Test agent activation removes globs (agent-requested mode)."""
        skill = _make_skill(tmp_path, "agent-only", SAMPLE_AGENT_SKILL_MD)
        transpiler = CursorTranspiler()
        result = transpiler.transpile(skill, tmp_path)
        assert "globs:" not in result.content


class TestWindsurfTranspiler:
    """Test Windsurf transpilation."""

    def test_output_path(self, tmp_path):
        skill = _make_skill(tmp_path, "code-review", SAMPLE_SKILL_MD)
        transpiler = WindsurfTranspiler()
        path = transpiler.get_output_path(skill, tmp_path)
        assert path == tmp_path / ".windsurf" / "rules" / "code-review.md"

    def test_trigger_mapping(self, tmp_path):
        """Test activation to trigger mapping."""
        rule = _make_skill(tmp_path, "coding-standards", SAMPLE_RULE_MD, subdir="rules")
        transpiler = WindsurfTranspiler()
        result = transpiler.transpile(rule, tmp_path)
        assert "trigger: always_on" in result.content

    def test_auto_with_globs_maps_to_glob_trigger(self, tmp_path):
        """Test auto + globs maps to trigger: glob."""
        skill = _make_skill(tmp_path, "code-review", SAMPLE_SKILL_MD)
        transpiler = WindsurfTranspiler()
        result = transpiler.transpile(skill, tmp_path)
        assert "trigger: glob" in result.content

    def test_truncation_warning(self, tmp_path):
        """Test that large skills produce a truncation warning."""
        large_body = "x" * 13000
        content = f'---\nname: large-skill\ndescription: "Test large skill"\n---\n\n{large_body}'
        skill = _make_skill(tmp_path, "large-skill", content)
        transpiler = WindsurfTranspiler()
        result = transpiler.transpile(skill, tmp_path)
        assert len(result.warnings) > 0
        assert "truncated" in result.warnings[0]
        assert "[truncated" in result.content


class TestVSCodeCopilotTranspiler:
    """Test VS Code Copilot transpilation."""

    def test_skill_output_path(self, tmp_path):
        skill = _make_skill(tmp_path, "code-review", SAMPLE_SKILL_MD)
        transpiler = VSCodeCopilotTranspiler()
        path = transpiler.get_output_path(skill, tmp_path)
        assert path == tmp_path / ".github" / "skills" / "code-review" / "SKILL.md"

    def test_rule_output_path(self, tmp_path):
        rule = _make_skill(tmp_path, "coding-standards", SAMPLE_RULE_MD, subdir="rules")
        transpiler = VSCodeCopilotTranspiler()
        path = transpiler.get_output_path(rule, tmp_path)
        assert path == tmp_path / ".github" / "instructions" / "coding-standards.instructions.md"

    def test_agent_activation_warning(self, tmp_path):
        """Test that agent activation produces a downgrade warning."""
        skill = _make_skill(tmp_path, "agent-only", SAMPLE_AGENT_SKILL_MD)
        transpiler = VSCodeCopilotTranspiler()
        result = transpiler.transpile(skill, tmp_path)
        assert any("downgraded" in w for w in result.warnings)


class TestContinueDevTranspiler:
    """Test Continue.dev transpilation."""

    def test_output_path(self, tmp_path):
        skill = _make_skill(tmp_path, "code-review", SAMPLE_SKILL_MD)
        transpiler = ContinueDevTranspiler()
        path = transpiler.get_output_path(skill, tmp_path)
        assert path == tmp_path / ".continue" / "rules" / "code-review.md"

    def test_priority_mapping(self, tmp_path):
        """Test that priority field is mapped."""
        skill = _make_skill(tmp_path, "code-review", SAMPLE_SKILL_MD)
        transpiler = ContinueDevTranspiler()
        result = transpiler.transpile(skill, tmp_path)
        assert "priority: 10" in result.content

    def test_agent_downgrade_warning(self, tmp_path):
        """Test that agent activation produces a downgrade warning."""
        skill = _make_skill(tmp_path, "agent-only", SAMPLE_AGENT_SKILL_MD)
        transpiler = ContinueDevTranspiler()
        result = transpiler.transpile(skill, tmp_path)
        assert any("downgraded" in w for w in result.warnings)


class TestJetBrainsTranspiler:
    """Test JetBrains AI transpilation."""

    def test_output_path(self, tmp_path):
        skill = _make_skill(tmp_path, "code-review", SAMPLE_SKILL_MD)
        transpiler = JetBrainsTranspiler()
        path = transpiler.get_output_path(skill, tmp_path)
        assert path == tmp_path / ".aiassistant" / "rules" / "code-review.md"

    def test_metadata_comment(self, tmp_path):
        """Test that metadata is stored as HTML comment."""
        skill = _make_skill(tmp_path, "code-review", SAMPLE_SKILL_MD)
        transpiler = JetBrainsTranspiler()
        result = transpiler.transpile(skill, tmp_path)
        assert "<!-- mcpm:" in result.content
        assert "activation=auto" in result.content

    def test_no_warnings_any_mode(self, tmp_path):
        """Test that JetBrains produces no downgrade warnings."""
        for content in [SAMPLE_SKILL_MD, SAMPLE_RULE_MD, SAMPLE_AGENT_SKILL_MD, SAMPLE_MANUAL_SKILL_MD]:
            name = content.split("name: ")[1].split("\n")[0].strip()
            subdir = "rules" if "always" in content else "skills"
            skill = _make_skill(tmp_path, name, content, subdir=subdir)
            transpiler = JetBrainsTranspiler()
            result = transpiler.transpile(skill, tmp_path)
            assert result.warnings == [], f"Unexpected warnings for {name}: {result.warnings}"


class TestAgentsMdTranspiler:
    """Test AGENTS.md generation."""

    def test_transpile_all(self, tmp_path):
        """Test generating available_skills block for multiple skills."""
        from mcpm.skills.parser import discover_skills

        # Set up skills
        for name, content in [
            ("code-review", SAMPLE_SKILL_MD),
            ("minimal-skill", '---\nname: minimal-skill\ndescription: "Minimal."\n---\n\nBody.'),
        ]:
            _make_skill(tmp_path, name, content)

        skills = discover_skills(tmp_path)
        transpiler = AgentsMdTranspiler()
        result = transpiler.transpile_all(skills, tmp_path)

        assert "<available_skills>" in result.content
        assert "</available_skills>" in result.content
        assert 'name="code-review"' in result.content
        assert "<!-- mcpm:start -->" in result.content
        assert "<!-- mcpm:end -->" in result.content

    def test_preserves_existing_content(self, tmp_path):
        """Test that existing AGENTS.md content is preserved."""
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text("# My Project\n\nExisting content here.\n")

        skill = _make_skill(tmp_path, "code-review", SAMPLE_SKILL_MD)
        transpiler = AgentsMdTranspiler()
        result = transpiler.transpile_all([skill], tmp_path)

        assert "Existing content here." in result.content
        assert "<available_skills>" in result.content

    def test_replaces_existing_block(self, tmp_path):
        """Test that existing mcpm block is replaced."""
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text("# Project\n\n<!-- mcpm:start -->\nold content\n<!-- mcpm:end -->\n\nAfter block.\n")

        skill = _make_skill(tmp_path, "code-review", SAMPLE_SKILL_MD)
        transpiler = AgentsMdTranspiler()
        result = transpiler.transpile_all([skill], tmp_path)

        assert "old content" not in result.content
        assert "code-review" in result.content
        assert "After block." in result.content


class TestInjectManagedBlock:
    """Test the managed block injection utility."""

    def test_inject_into_empty(self):
        """Test injecting into empty content."""
        result = inject_managed_block("", "block content")
        assert "<!-- mcpm:start -->" in result
        assert "block content" in result
        assert "<!-- mcpm:end -->" in result

    def test_inject_append(self):
        """Test appending to existing content."""
        result = inject_managed_block("Existing text.", "new block")
        assert "Existing text." in result
        assert "new block" in result

    def test_inject_replace(self):
        """Test replacing existing managed block."""
        existing = "Before.\n\n<!-- mcpm:start -->\nold\n<!-- mcpm:end -->\n\nAfter."
        result = inject_managed_block(existing, "new")
        assert "old" not in result
        assert "new" in result
        assert "Before." in result
        assert "After." in result
