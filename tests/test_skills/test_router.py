"""Tests for router skills resource exposure."""

from mcpm.skills.router import get_skill_content, get_skills_resource_list

from .conftest import SAMPLE_RULE_MD, SAMPLE_SKILL_MD


def _setup_repo(tmp_path):
    """Create a minimal skills repo."""
    (tmp_path / "mcpm-skills.yaml").write_text("name: test\n")
    skill_dir = tmp_path / "skills" / "code-review"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(SAMPLE_SKILL_MD)
    rule_dir = tmp_path / "rules" / "coding-standards"
    rule_dir.mkdir(parents=True)
    (rule_dir / "SKILL.md").write_text(SAMPLE_RULE_MD)
    return tmp_path


class TestSkillsResourceList:
    def test_returns_resources(self, tmp_path):
        """Test that skill resources are listed correctly."""
        repo = _setup_repo(tmp_path)
        resources = get_skills_resource_list(repo)
        assert len(resources) == 2
        names = {r["name"] for r in resources}
        assert "code-review" in names
        assert "coding-standards" in names

    def test_resource_format(self, tmp_path):
        """Test that each resource has the expected fields."""
        repo = _setup_repo(tmp_path)
        resources = get_skills_resource_list(repo)
        for r in resources:
            assert "uri" in r
            assert r["uri"].startswith("mcpm://skills/")
            assert "name" in r
            assert "description" in r
            assert "mimeType" in r
            assert r["mimeType"] == "text/markdown"
            assert "metadata" in r

    def test_empty_repo(self, tmp_path):
        """Test with no skills."""
        resources = get_skills_resource_list(tmp_path)
        assert resources == []


class TestGetSkillContent:
    def test_returns_content(self, tmp_path):
        """Test getting skill body content."""
        repo = _setup_repo(tmp_path)
        content = get_skill_content("code-review", repo)
        assert content is not None
        assert "Code Review Instructions" in content

    def test_not_found(self, tmp_path):
        """Test getting nonexistent skill."""
        repo = _setup_repo(tmp_path)
        assert get_skill_content("nonexistent", repo) is None

    def test_no_repo(self, tmp_path):
        """Test with no repo path."""
        assert get_skill_content("anything", tmp_path) is None
