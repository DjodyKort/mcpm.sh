"""Tests for skills git sync configuration."""

from mcpm.skills.sync_git import SkillsSyncConfig


class TestSkillsSyncConfig:
    def test_configure_and_read(self, tmp_path):
        """Test configuring and reading sync settings."""
        config = SkillsSyncConfig(config_path=tmp_path / "sync.json")
        config.configure(repo="git@github.com:user/skills.git", branch="develop", auto_sync=True)

        assert config.get_repo() == "git@github.com:user/skills.git"
        assert config.get_branch() == "develop"
        assert config.get_auto_sync() is True
        assert config.get_local_path() is not None

    def test_defaults(self, tmp_path):
        """Test default values when not configured."""
        config = SkillsSyncConfig(config_path=tmp_path / "sync.json")
        assert config.get_repo() is None
        assert config.get_branch() == "main"
        assert config.get_auto_sync() is False
        assert config.get_local_path() is None

    def test_clear(self, tmp_path):
        """Test clearing sync configuration."""
        config = SkillsSyncConfig(config_path=tmp_path / "sync.json")
        config.configure(repo="https://github.com/user/skills.git")
        assert config.get_repo() is not None

        config.clear()
        assert config.get_repo() is None

    def test_corrupt_config(self, tmp_path):
        """Test handling of corrupt config file."""
        config_path = tmp_path / "sync.json"
        config_path.write_text("invalid json {{{")
        config = SkillsSyncConfig(config_path=config_path)
        assert config.get_repo() is None
