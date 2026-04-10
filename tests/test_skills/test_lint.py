"""Tests for skills linting."""

from mcpm.skills.lint import lint_skill, lint_skills
from mcpm.skills.parser import parse_skill_file

from .conftest import SAMPLE_SKILL_MD


def _make_skill_config(tmp_path, name, content, subdir="skills"):
    """Helper to create and parse a skill."""
    skill_dir = tmp_path / subdir / name
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(content)
    return parse_skill_file(skill_file)


class TestLintSkill:
    """Test individual skill linting."""

    def test_valid_skill_passes(self, tmp_path):
        """Test that a well-formed skill passes lint."""
        skill = _make_skill_config(tmp_path, "code-review", SAMPLE_SKILL_MD)
        result = lint_skill(skill)
        assert not result.has_errors

    def test_short_description_warning(self, tmp_path):
        """Test warning for very short description."""
        content = '---\nname: short-desc\ndescription: "Too short"\n---\n\nBody.'
        skill = _make_skill_config(tmp_path, "short-desc", content)
        result = lint_skill(skill)
        warnings = [m for m in result.warnings if "short" in m.message.lower()]
        assert len(warnings) > 0

    def test_placeholder_description_warning(self, tmp_path):
        """Test warning for placeholder description."""
        content = '---\nname: placeholder\ndescription: "TODO"\n---\n\nBody.'
        skill = _make_skill_config(tmp_path, "placeholder", content)
        result = lint_skill(skill)
        warnings = [m for m in result.messages if "placeholder" in m.message.lower()]
        assert len(warnings) > 0

    def test_empty_body_warning(self, tmp_path):
        """Test warning for empty body."""
        content = '---\nname: empty-body\ndescription: "A skill with no instructions at all."\n---\n'
        skill = _make_skill_config(tmp_path, "empty-body", content)
        result = lint_skill(skill)
        warnings = [m for m in result.warnings if "empty" in m.message.lower()]
        assert len(warnings) > 0

    def test_long_body_warning(self, tmp_path):
        """Test warning for body exceeding 500 lines."""
        body = "\n".join([f"Line {i}" for i in range(501)])
        content = f'---\nname: long-body\ndescription: "A skill with a very long body for testing."\n---\n\n{body}'
        skill = _make_skill_config(tmp_path, "long-body", content)
        result = lint_skill(skill)
        warnings = [m for m in result.warnings if "500" in m.message]
        assert len(warnings) > 0

    def test_windsurf_char_limit_warning(self, tmp_path):
        """Test warning for body exceeding Windsurf char limit."""
        body = "x" * 13000
        content = f'---\nname: big-skill\ndescription: "A big skill exceeding windsurf limits."\n---\n\n{body}'
        skill = _make_skill_config(tmp_path, "big-skill", content)
        result = lint_skill(skill)
        warnings = [m for m in result.warnings if "windsurf" in m.message.lower()]
        assert len(warnings) > 0

    def test_name_directory_mismatch_error(self, tmp_path):
        """Test error when name doesn't match directory."""
        content = '---\nname: wrong-name\ndescription: "Name mismatch test."\n---\n\nBody.'
        skill = _make_skill_config(tmp_path, "actual-name", content)
        result = lint_skill(skill)
        errors = [m for m in result.errors if "does not match" in m.message]
        assert len(errors) > 0

    def test_always_with_globs_info(self, tmp_path):
        """Test info when always activation has globs."""
        content = '---\nname: always-globs\ndescription: "Always activation but has globs set."\nactivation: always\nglobs: "*.py"\n---\n\nBody.'
        skill = _make_skill_config(tmp_path, "always-globs", content, subdir="rules")
        result = lint_skill(skill)
        infos = [m for m in result.messages if "ignored" in m.message.lower()]
        assert len(infos) > 0

    def test_broad_glob_info(self, tmp_path):
        """Test info for overly broad glob pattern."""
        content = '---\nname: broad-glob\ndescription: "Skill with broad glob matching all files."\nglobs: "**/*"\n---\n\nBody.'
        skill = _make_skill_config(tmp_path, "broad-glob", content)
        result = lint_skill(skill)
        infos = [m for m in result.messages if "**/*" in m.message]
        assert len(infos) > 0


class TestLintSkills:
    """Test cross-skill linting."""

    def test_duplicate_names(self, tmp_path):
        """Test error for duplicate skill names."""
        content = '---\nname: dupe\ndescription: "Duplicate test skill."\n---\n\nBody.'
        skill1 = _make_skill_config(tmp_path, "dupe", content, subdir="skills")
        # Create a second copy with same name
        skill2_dir = tmp_path / "rules" / "dupe"
        skill2_dir.mkdir(parents=True)
        (skill2_dir / "SKILL.md").write_text(content)
        skill2 = parse_skill_file(skill2_dir / "SKILL.md")

        result = lint_skills([skill1, skill2])
        errors = [m for m in result.errors if "Duplicate" in m.message]
        assert len(errors) > 0

    def test_overlapping_globs_warning(self, tmp_path):
        """Test warning for skills with identical globs and activation."""
        content1 = (
            '---\nname: skill-a\ndescription: "First skill with shared globs."\nglobs: "src/**/*.py"\n---\n\nBody A.'
        )
        content2 = (
            '---\nname: skill-b\ndescription: "Second skill with shared globs."\nglobs: "src/**/*.py"\n---\n\nBody B.'
        )
        skill1 = _make_skill_config(tmp_path, "skill-a", content1)
        skill2 = _make_skill_config(tmp_path, "skill-b", content2)
        result = lint_skills([skill1, skill2])
        warnings = [m for m in result.warnings if "conflicts" in m.message.lower() or "identical" in m.message.lower()]
        assert len(warnings) > 0
