"""Tests for Phase 2 client transpilers."""

from mcpm.skills.parser import parse_skill_file
from mcpm.skills.transpilers.aider import AiderTranspiler
from mcpm.skills.transpilers.amazon_q import AmazonQTranspiler
from mcpm.skills.transpilers.cline import ClineTranspiler
from mcpm.skills.transpilers.codex_cli import CodexCliTranspiler
from mcpm.skills.transpilers.gemini_cli import GeminiCliTranspiler
from mcpm.skills.transpilers.goose import GooseTranspiler
from mcpm.skills.transpilers.roo_code import RooCodeTranspiler
from mcpm.skills.transpilers.trae import TraeTranspiler
from mcpm.skills.transpilers.zed import ZedTranspiler

from .conftest import SAMPLE_AGENT_SKILL_MD, SAMPLE_MANUAL_SKILL_MD, SAMPLE_RULE_MD, SAMPLE_SKILL_MD


def _make_skill(tmp_path, name, content, subdir="skills"):
    skill_dir = tmp_path / subdir / name
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(content)
    return parse_skill_file(skill_file)


class TestClineTranspiler:
    def test_output_path(self, tmp_path):
        skill = _make_skill(tmp_path, "code-review", SAMPLE_SKILL_MD)
        assert ClineTranspiler().get_output_path(skill, tmp_path) == tmp_path / ".clinerules" / "code-review.md"

    def test_paths_field(self, tmp_path):
        skill = _make_skill(tmp_path, "code-review", SAMPLE_SKILL_MD)
        result = ClineTranspiler().transpile(skill, tmp_path)
        assert "paths: src/**/*.py,src/**/*.ts" in result.content

    def test_agent_downgrade(self, tmp_path):
        skill = _make_skill(tmp_path, "agent-only", SAMPLE_AGENT_SKILL_MD)
        result = ClineTranspiler().transpile(skill, tmp_path)
        assert any("downgraded" in w for w in result.warnings)


class TestZedTranspiler:
    def test_output_path(self, tmp_path):
        skill = _make_skill(tmp_path, "code-review", SAMPLE_SKILL_MD)
        assert ZedTranspiler().get_output_path(skill, tmp_path) == tmp_path / ".rules"

    def test_all_modes_downgrade(self, tmp_path):
        for content in [SAMPLE_SKILL_MD, SAMPLE_AGENT_SKILL_MD, SAMPLE_MANUAL_SKILL_MD]:
            name = content.split("name: ")[1].split("\n")[0].strip()
            skill = _make_skill(tmp_path, name, content)
            result = ZedTranspiler().transpile(skill, tmp_path)
            assert any("downgraded" in w for w in result.warnings)

    def test_transpile_all(self, tmp_path):
        skill = _make_skill(tmp_path, "code-review", SAMPLE_SKILL_MD)
        rule = _make_skill(tmp_path, "coding-standards", SAMPLE_RULE_MD, subdir="rules")
        transpiler = ZedTranspiler()
        result = transpiler.transpile_all([skill, rule], tmp_path)
        assert "<!-- mcpm:start -->" in result.content
        assert "## code-review" in result.content
        assert "## coding-standards" in result.content


class TestGeminiCliTranspiler:
    def test_skill_output_path(self, tmp_path):
        skill = _make_skill(tmp_path, "code-review", SAMPLE_SKILL_MD)
        path = GeminiCliTranspiler().get_output_path(skill, tmp_path)
        assert path == tmp_path / ".gemini" / "skills" / "code-review" / "SKILL.md"

    def test_skill_frontmatter(self, tmp_path):
        skill = _make_skill(tmp_path, "code-review", SAMPLE_SKILL_MD)
        result = GeminiCliTranspiler().transpile(skill, tmp_path)
        assert "name: code-review" in result.content
        assert "description:" in result.content

    def test_manual_downgrade(self, tmp_path):
        skill = _make_skill(tmp_path, "manual-invoke", SAMPLE_MANUAL_SKILL_MD)
        result = GeminiCliTranspiler().transpile(skill, tmp_path)
        assert any("downgraded" in w for w in result.warnings)


class TestCodexCliTranspiler:
    def test_output_path(self, tmp_path):
        skill = _make_skill(tmp_path, "code-review", SAMPLE_SKILL_MD)
        path = CodexCliTranspiler().get_output_path(skill, tmp_path)
        assert path == tmp_path / ".agents" / "skills" / "code-review" / "SKILL.md"

    def test_manual_downgrade(self, tmp_path):
        skill = _make_skill(tmp_path, "manual-invoke", SAMPLE_MANUAL_SKILL_MD)
        result = CodexCliTranspiler().transpile(skill, tmp_path)
        assert any("downgraded" in w for w in result.warnings)


class TestAmazonQTranspiler:
    def test_output_path(self, tmp_path):
        skill = _make_skill(tmp_path, "code-review", SAMPLE_SKILL_MD)
        path = AmazonQTranspiler().get_output_path(skill, tmp_path)
        assert path == tmp_path / ".amazonq" / "rules" / "code-review.md"

    def test_no_frontmatter(self, tmp_path):
        skill = _make_skill(tmp_path, "code-review", SAMPLE_SKILL_MD)
        result = AmazonQTranspiler().transpile(skill, tmp_path)
        assert "---" not in result.content
        assert "<!-- mcpm:" in result.content

    def test_auto_downgrade(self, tmp_path):
        skill = _make_skill(tmp_path, "code-review", SAMPLE_SKILL_MD)
        result = AmazonQTranspiler().transpile(skill, tmp_path)
        assert any("downgraded" in w for w in result.warnings)


class TestAiderTranspiler:
    def test_output_path(self, tmp_path):
        skill = _make_skill(tmp_path, "code-review", SAMPLE_SKILL_MD)
        path = AiderTranspiler().get_output_path(skill, tmp_path)
        assert path == tmp_path / ".mcpm" / "skills" / "code-review" / "SKILL.md"

    def test_plain_markdown(self, tmp_path):
        skill = _make_skill(tmp_path, "code-review", SAMPLE_SKILL_MD)
        result = AiderTranspiler().transpile(skill, tmp_path)
        assert "---" not in result.content
        assert "# code-review" in result.content


class TestTraeTranspiler:
    def test_output_path(self, tmp_path):
        skill = _make_skill(tmp_path, "code-review", SAMPLE_SKILL_MD)
        assert TraeTranspiler().get_output_path(skill, tmp_path) == tmp_path / ".trae" / "rules" / "code-review.md"

    def test_always_activation(self, tmp_path):
        rule = _make_skill(tmp_path, "coding-standards", SAMPLE_RULE_MD, subdir="rules")
        result = TraeTranspiler().transpile(rule, tmp_path)
        assert "alwaysApply: true" in result.content


class TestGooseTranspiler:
    def test_skill_output_path(self, tmp_path):
        skill = _make_skill(tmp_path, "code-review", SAMPLE_SKILL_MD)
        path = GooseTranspiler().get_output_path(skill, tmp_path)
        assert path == tmp_path / ".goose" / "skills" / "code-review" / "SKILL.md"

    def test_rule_output_path(self, tmp_path):
        rule = _make_skill(tmp_path, "coding-standards", SAMPLE_RULE_MD, subdir="rules")
        path = GooseTranspiler().get_output_path(rule, tmp_path)
        assert path == tmp_path / ".goose" / "rules" / "coding-standards.md"

    def test_manual_downgrade(self, tmp_path):
        skill = _make_skill(tmp_path, "manual-invoke", SAMPLE_MANUAL_SKILL_MD)
        result = GooseTranspiler().transpile(skill, tmp_path)
        assert any("downgraded" in w for w in result.warnings)


class TestRooCodeTranspiler:
    def test_output_path(self, tmp_path):
        skill = _make_skill(tmp_path, "code-review", SAMPLE_SKILL_MD)
        assert RooCodeTranspiler().get_output_path(skill, tmp_path) == tmp_path / ".roo" / "rules" / "code-review.md"

    def test_always_activation(self, tmp_path):
        rule = _make_skill(tmp_path, "coding-standards", SAMPLE_RULE_MD, subdir="rules")
        result = RooCodeTranspiler().transpile(rule, tmp_path)
        assert "alwaysApply: true" in result.content

    def test_manual_downgrade(self, tmp_path):
        skill = _make_skill(tmp_path, "manual-invoke", SAMPLE_MANUAL_SKILL_MD)
        result = RooCodeTranspiler().transpile(skill, tmp_path)
        assert any("downgraded" in w for w in result.warnings)
