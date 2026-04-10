"""Tests for SKILL.md parser."""

import pytest

from mcpm.skills.parser import discover_skills, find_skills_repo, parse_frontmatter, parse_skill_file

from .conftest import SAMPLE_MINIMAL_SKILL_MD, SAMPLE_RULE_MD, SAMPLE_SKILL_MD


class TestParseFrontmatter:
    """Test raw frontmatter parsing."""

    def test_basic_frontmatter(self):
        """Test parsing basic YAML frontmatter."""
        content = '---\nname: test\ndescription: "A test"\n---\n\nBody here.'
        fm, body = parse_frontmatter(content)
        assert fm["name"] == "test"
        assert fm["description"] == "A test"
        assert body == "Body here."

    def test_no_frontmatter(self):
        """Test content with no frontmatter."""
        content = "Just some markdown without frontmatter."
        fm, body = parse_frontmatter(content)
        assert fm == {}
        assert body == content

    def test_hyphenated_keys_normalized(self):
        """Test that hyphenated YAML keys are normalized to underscores."""
        content = '---\nname: test\ndescription: "Test"\nallowed-tools: "Read Write"\n---\n\nBody.'
        fm, body = parse_frontmatter(content)
        assert "allowed_tools" in fm
        assert fm["allowed_tools"] == "Read Write"

    def test_complex_frontmatter(self):
        """Test parsing the full sample SKILL.md."""
        fm, body = parse_frontmatter(SAMPLE_SKILL_MD)
        assert fm["name"] == "code-review"
        assert fm["activation"] == "auto"
        assert fm["priority"] == 10
        assert fm["globs"] == "src/**/*.py,src/**/*.ts"
        assert "metadata" in fm
        assert fm["metadata"]["author"] == "testuser"
        assert "Code Review Instructions" in body

    def test_empty_frontmatter(self):
        """Test empty frontmatter block."""
        content = "---\n---\n\nBody."
        fm, body = parse_frontmatter(content)
        assert fm == {}
        assert body == "Body."

    def test_multiline_body(self):
        """Test that multiline body is preserved."""
        content = '---\nname: test\ndescription: "T"\n---\n\nLine 1\n\nLine 2\n\nLine 3'
        fm, body = parse_frontmatter(content)
        assert "Line 1" in body
        assert "Line 3" in body


class TestParseSkillFile:
    """Test full skill file parsing."""

    def test_parse_skill(self, single_skill_path):
        """Test parsing a complete skill file."""
        skill = parse_skill_file(single_skill_path)
        assert skill.frontmatter.name == "code-review"
        assert skill.frontmatter.activation == "auto"
        assert skill.frontmatter.globs == "src/**/*.py,src/**/*.ts"
        assert skill.frontmatter.priority == 10
        assert "Code Review Instructions" in skill.body
        assert skill.skill_type == "skill"

    def test_parse_rule(self, tmp_path):
        """Test parsing a rule file (under rules/ directory)."""
        rule_dir = tmp_path / "rules" / "coding-standards"
        rule_dir.mkdir(parents=True)
        rule_file = rule_dir / "SKILL.md"
        rule_file.write_text(SAMPLE_RULE_MD)

        skill = parse_skill_file(rule_file)
        assert skill.frontmatter.name == "coding-standards"
        assert skill.frontmatter.activation == "always"
        assert skill.skill_type == "rule"

    def test_parse_minimal(self, tmp_path):
        """Test parsing a minimal skill file."""
        skill_dir = tmp_path / "skills" / "minimal-skill"
        skill_dir.mkdir(parents=True)
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(SAMPLE_MINIMAL_SKILL_MD)

        skill = parse_skill_file(skill_file)
        assert skill.frontmatter.name == "minimal-skill"
        assert skill.frontmatter.activation == "auto"

    def test_parse_nonexistent_file(self, tmp_path):
        """Test that parsing a nonexistent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            parse_skill_file(tmp_path / "nonexistent.md")

    def test_parse_no_frontmatter(self, tmp_path):
        """Test that parsing a file without frontmatter raises ValueError."""
        skill_file = tmp_path / "SKILL.md"
        skill_file.write_text("Just markdown, no frontmatter.")
        with pytest.raises(ValueError, match="No YAML frontmatter"):
            parse_skill_file(skill_file)


class TestDiscoverSkills:
    """Test skill discovery from repository."""

    def test_discover_all(self, skills_repo):
        """Test discovering all skills in a repo."""
        skills = discover_skills(skills_repo)
        names = {s.name for s in skills}
        assert "code-review" in names
        assert "minimal-skill" in names
        assert "agent-only" in names
        assert "manual-invoke" in names
        assert "coding-standards" in names
        assert len(skills) == 5

    def test_discover_empty_repo(self, tmp_path):
        """Test discovering skills in an empty repo."""
        (tmp_path / "skills").mkdir()
        skills = discover_skills(tmp_path)
        assert skills == []

    def test_discover_no_dirs(self, tmp_path):
        """Test discovering skills when no skills/rules dirs exist."""
        skills = discover_skills(tmp_path)
        assert skills == []

    def test_discover_skips_dirs_without_skill_md(self, tmp_path):
        """Test that directories without SKILL.md are skipped."""
        (tmp_path / "skills" / "empty-dir").mkdir(parents=True)
        skills = discover_skills(tmp_path)
        assert skills == []


class TestFindSkillsRepo:
    """Test skills repo discovery."""

    def test_find_by_manifest(self, tmp_path):
        """Test finding repo by mcpm-skills.yaml."""
        (tmp_path / "mcpm-skills.yaml").write_text("name: test\n")
        result = find_skills_repo(tmp_path)
        assert result == tmp_path

    def test_find_by_skills_dir(self, tmp_path):
        """Test finding repo by skills/ directory."""
        (tmp_path / "skills").mkdir()
        result = find_skills_repo(tmp_path)
        assert result == tmp_path

    def test_find_from_subdirectory(self, tmp_path):
        """Test finding repo from a subdirectory."""
        (tmp_path / "mcpm-skills.yaml").write_text("name: test\n")
        subdir = tmp_path / "skills" / "test"
        subdir.mkdir(parents=True)
        result = find_skills_repo(subdir)
        assert result == tmp_path

    def test_not_found(self, tmp_path):
        """Test that None is returned when no repo found."""
        empty = tmp_path / "empty"
        empty.mkdir()
        result = find_skills_repo(empty)
        assert result is None
