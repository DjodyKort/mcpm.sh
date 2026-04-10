"""Tests for skills CLI commands."""

import pytest
from click.testing import CliRunner

from mcpm.commands.skills import skills
from mcpm.skills.config import SkillsConfigManager


@pytest.fixture
def runner():
    return CliRunner()


class TestInitCommand:
    """Test mcpm skills init."""

    def test_init_creates_repo(self, runner, tmp_path):
        """Test that init creates the expected directory structure."""
        result = runner.invoke(skills, ["init", "--path", str(tmp_path), "--name", "test"])
        assert result.exit_code == 0
        assert "initialized" in result.output.lower()
        assert (tmp_path / "mcpm-skills.yaml").exists()
        assert (tmp_path / "skills").is_dir()
        assert (tmp_path / "rules").is_dir()

    def test_init_existing_repo(self, runner, tmp_path):
        """Test that init warns if repo already exists."""
        (tmp_path / "mcpm-skills.yaml").write_text("name: existing\n")
        result = runner.invoke(skills, ["init", "--path", str(tmp_path)])
        assert "already exists" in result.output.lower()


class TestAddCommand:
    """Test mcpm skills add."""

    def test_add_skill(self, runner, tmp_path):
        """Test creating a new skill."""
        # Init repo first
        SkillsConfigManager(project_root=tmp_path).init_repo()

        result = runner.invoke(skills, ["add", "my-skill", "--path", str(tmp_path)])
        assert result.exit_code == 0
        assert "created" in result.output.lower()
        assert (tmp_path / "skills" / "my-skill" / "SKILL.md").exists()

    def test_add_rule(self, runner, tmp_path):
        """Test creating a new rule."""
        SkillsConfigManager(project_root=tmp_path).init_repo()

        result = runner.invoke(skills, ["add", "my-rule", "--type", "rule", "--path", str(tmp_path)])
        assert result.exit_code == 0
        assert (tmp_path / "rules" / "my-rule" / "SKILL.md").exists()

    def test_add_invalid_name(self, runner, tmp_path):
        """Test that invalid names are rejected."""
        SkillsConfigManager(project_root=tmp_path).init_repo()

        result = runner.invoke(skills, ["add", "Invalid-Name", "--path", str(tmp_path)])
        assert "invalid" in result.output.lower() or "error" in result.output.lower()

    def test_add_duplicate(self, runner, tmp_path):
        """Test that duplicate skill names are rejected."""
        SkillsConfigManager(project_root=tmp_path).init_repo()
        (tmp_path / "skills" / "existing").mkdir(parents=True)

        result = runner.invoke(skills, ["add", "existing", "--path", str(tmp_path)])
        assert "already exists" in result.output.lower()


class TestListCommand:
    """Test mcpm skills ls."""

    def test_list_skills(self, runner, skills_repo):
        """Test listing all skills."""
        result = runner.invoke(skills, ["ls", "--path", str(skills_repo)])
        assert result.exit_code == 0
        assert "code-review" in result.output
        assert "coding-standards" in result.output

    def test_list_empty(self, runner, tmp_path):
        """Test listing when no repo found."""
        result = runner.invoke(skills, ["ls", "--path", str(tmp_path)])
        assert "no skills" in result.output.lower() or "not found" in result.output.lower()


class TestSyncCommand:
    """Test mcpm skills sync."""

    def test_sync_dry_run(self, runner, skills_repo):
        """Test sync with dry-run flag."""
        result = runner.invoke(skills, ["sync", "--dry-run", "--path", str(skills_repo)])
        assert result.exit_code == 0
        assert "dry run" in result.output.lower()
        # Lockfile should NOT be created on dry-run
        assert not (skills_repo / "mcpm-skills.lock").exists()

    def test_sync_creates_files(self, runner, skills_repo):
        """Test that sync creates output files."""
        result = runner.invoke(skills, ["sync", "--path", str(skills_repo)])
        assert result.exit_code == 0
        assert "synced" in result.output.lower()

        # Check lockfile was created
        assert (skills_repo / "mcpm-skills.lock").exists()

        # Check at least some output files were created
        assert (skills_repo / ".claude" / "skills" / "code-review" / "SKILL.md").exists()
        assert (skills_repo / ".cursor" / "rules" / "code-review" / "RULE.md").exists()
        assert (skills_repo / "AGENTS.md").exists()

    def test_sync_specific_client(self, runner, skills_repo):
        """Test syncing to a specific client."""
        result = runner.invoke(skills, ["sync", "--client", "claude-code", "--path", str(skills_repo)])
        assert result.exit_code == 0
        assert (skills_repo / ".claude" / "skills" / "code-review" / "SKILL.md").exists()
        # Other clients should NOT have files
        assert not (skills_repo / ".cursor" / "rules" / "code-review" / "RULE.md").exists()

    def test_sync_agents_md(self, runner, skills_repo):
        """Test that AGENTS.md is generated with available_skills."""
        runner.invoke(skills, ["sync", "--path", str(skills_repo)])
        agents_md = (skills_repo / "AGENTS.md").read_text()
        assert "<available_skills>" in agents_md
        assert "code-review" in agents_md
        assert "<!-- mcpm:start -->" in agents_md

    def test_sync_zed_concatenates_all_skills(self, runner, skills_repo):
        """Test that Zed .rules file contains ALL skills concatenated, not just the last one."""
        runner.invoke(skills, ["sync", "--path", str(skills_repo)])
        rules_file = skills_repo / ".rules"
        assert rules_file.exists()
        content = rules_file.read_text()
        # Should contain managed block with multiple skills
        assert "<!-- mcpm:start -->" in content
        assert "<!-- mcpm:end -->" in content
        # Should contain at least 2 different skills (not just the last one written)
        assert "## code-review" in content
        assert "## coding-standards" in content

    def test_sync_bundle_roundtrip(self, runner, skills_repo, tmp_path):
        """Test creating a bundle, extracting it, and syncing from the extracted repo."""
        # Bundle
        bundle_path = tmp_path / "test.zip"
        result = runner.invoke(skills, ["bundle", "--path", str(skills_repo), "--output", str(bundle_path)])
        assert result.exit_code == 0
        assert bundle_path.exists()

        # Extract
        target = tmp_path / "extracted"
        target.mkdir()
        result = runner.invoke(skills, ["unbundle", str(bundle_path), "--path", str(target)])
        assert result.exit_code == 0
        assert (target / "skills" / "code-review" / "SKILL.md").exists()

        # Sync from extracted
        result = runner.invoke(skills, ["sync", "--client", "claude-code", "--path", str(target)])
        assert result.exit_code == 0
        assert (target / ".claude" / "skills" / "code-review" / "SKILL.md").exists()


class TestLintCommand:
    """Test mcpm skills lint."""

    def test_lint_valid(self, runner, skills_repo):
        """Test linting valid skills."""
        result = runner.invoke(skills, ["lint", "--path", str(skills_repo)])
        # Should not have errors (exit code 0 or just warnings/infos)
        # Note: may have info/warnings but no errors
        assert result.exit_code == 0 or "error" not in result.output.lower()

    def test_lint_invalid(self, runner, tmp_path):
        """Test linting a skill with issues."""
        skill_dir = tmp_path / "skills" / "bad-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text('---\nname: wrong-name\ndescription: "x"\n---\n')

        result = runner.invoke(skills, ["lint", "--path", str(tmp_path)])
        assert "does not match" in result.output


class TestDiffCommand:
    """Test mcpm skills diff."""

    def test_diff_no_lockfile(self, runner, skills_repo):
        """Test diff when no lockfile exists (all new)."""
        result = runner.invoke(skills, ["diff", "--path", str(skills_repo)])
        assert "new" in result.output.lower() or "no lockfile" in result.output.lower()

    def test_diff_no_changes(self, runner, skills_repo):
        """Test diff after a fresh sync (no changes)."""
        # First sync
        runner.invoke(skills, ["sync", "--path", str(skills_repo)])
        # Then diff
        result = runner.invoke(skills, ["diff", "--path", str(skills_repo)])
        assert "no changes" in result.output.lower()


class TestCleanCommand:
    """Test mcpm skills clean."""

    def test_clean_after_sync(self, runner, skills_repo):
        """Test cleaning files after a sync."""
        # Sync first
        runner.invoke(skills, ["sync", "--path", str(skills_repo)])
        assert (skills_repo / ".claude" / "skills" / "code-review" / "SKILL.md").exists()

        # Clean
        result = runner.invoke(skills, ["clean", "--path", str(skills_repo)])
        assert result.exit_code == 0
        assert "cleaned" in result.output.lower() or "removed" in result.output.lower()

    def test_clean_no_lockfile(self, runner, tmp_path):
        """Test cleaning when no lockfile exists."""
        result = runner.invoke(skills, ["clean", "--path", str(tmp_path)])
        assert "no lockfile" in result.output.lower() or "nothing" in result.output.lower()


class TestStatusCommand:
    """Test mcpm skills status."""

    def test_status_after_sync(self, runner, skills_repo):
        """Test status after a clean sync."""
        runner.invoke(skills, ["sync", "--path", str(skills_repo)])
        result = runner.invoke(skills, ["status", "--path", str(skills_repo)])
        assert result.exit_code == 0
        assert "ok" in result.output.lower() or "sync" in result.output.lower()

    def test_status_no_lockfile(self, runner, tmp_path):
        """Test status when no lockfile exists."""
        result = runner.invoke(skills, ["status", "--path", str(tmp_path)])
        assert "no lockfile" in result.output.lower()

    def test_status_strict_no_lockfile(self, runner, tmp_path):
        """Test that --strict exits non-zero when no lockfile."""
        result = runner.invoke(skills, ["status", "--strict", "--path", str(tmp_path)])
        assert result.exit_code != 0
