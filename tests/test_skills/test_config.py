"""Tests for SkillsConfigManager."""

from mcpm.skills.config import SkillsConfigManager
from mcpm.skills.schema import LockFile, LockFileEntry


class TestSkillsConfigManager:
    """Test skills config management."""

    def test_init_repo(self, tmp_path):
        """Test scaffolding a new skills repository."""
        manager = SkillsConfigManager(project_root=tmp_path)
        manager.init_repo(name="test-skills")

        assert (tmp_path / "mcpm-skills.yaml").exists()
        assert (tmp_path / "skills").is_dir()
        assert (tmp_path / "rules").is_dir()
        assert (tmp_path / "profiles").is_dir()

    def test_init_repo_creates_manifest(self, tmp_path):
        """Test that manifest has correct content."""
        manager = SkillsConfigManager(project_root=tmp_path)
        manager.init_repo(name="my-project")

        manifest = manager.load_manifest()
        assert manifest is not None
        assert manifest.name == "my-project"

    def test_has_skills_repo_true(self, tmp_path):
        """Test detecting a skills repo."""
        manager = SkillsConfigManager(project_root=tmp_path)
        manager.init_repo()
        assert manager.has_skills_repo() is True

    def test_has_skills_repo_false(self, tmp_path):
        """Test detecting absence of skills repo."""
        manager = SkillsConfigManager(project_root=tmp_path)
        assert manager.has_skills_repo() is False

    def test_scaffold_skill(self, tmp_path):
        """Test creating a new skill from template."""
        manager = SkillsConfigManager(project_root=tmp_path)
        manager.init_repo()

        skill_path = manager.scaffold_skill("code-review")
        assert skill_path.exists()
        content = skill_path.read_text()
        assert "name: code-review" in content
        assert "activation: auto" in content

    def test_scaffold_rule(self, tmp_path):
        """Test creating a new rule from template."""
        manager = SkillsConfigManager(project_root=tmp_path)
        manager.init_repo()

        rule_path = manager.scaffold_skill("my-rule", skill_type="rule")
        assert rule_path.exists()
        assert "rules" in str(rule_path)
        content = rule_path.read_text()
        assert "activation: always" in content

    def test_lockfile_roundtrip(self, tmp_path):
        """Test saving and loading a lockfile."""
        manager = SkillsConfigManager(project_root=tmp_path)

        lockfile = LockFile.create_now()
        lockfile.skills["test"] = LockFileEntry(
            hash="sha256:abc123",
            clients_synced=["claude-code", "cursor"],
            warnings=["cursor: test warning"],
        )
        lockfile.rules["rule1"] = LockFileEntry(hash="sha256:def456")

        manager.save_lockfile(lockfile)
        assert manager.lockfile_path.exists()

        loaded = manager.load_lockfile()
        assert loaded is not None
        assert "test" in loaded.skills
        assert loaded.skills["test"].hash == "sha256:abc123"
        assert loaded.skills["test"].clients_synced == ["claude-code", "cursor"]
        assert "rule1" in loaded.rules

    def test_lockfile_not_found(self, tmp_path):
        """Test loading lockfile when it doesn't exist."""
        manager = SkillsConfigManager(project_root=tmp_path)
        assert manager.load_lockfile() is None

    def test_lockfile_corrupt(self, tmp_path):
        """Test loading a corrupt lockfile returns None."""
        manager = SkillsConfigManager(project_root=tmp_path)
        manager.lockfile_path.write_text("not valid json {{{")
        assert manager.load_lockfile() is None

    def test_compute_output_hash(self, tmp_path):
        """Test computing hash of an output file."""
        manager = SkillsConfigManager(project_root=tmp_path)
        test_file = tmp_path / "test.md"
        test_file.write_text("hello world")

        hash1 = manager.compute_output_hash(test_file)
        assert hash1 is not None
        assert hash1.startswith("sha256:")

        # Same content = same hash
        hash2 = manager.compute_output_hash(test_file)
        assert hash1 == hash2

        # Different content = different hash
        test_file.write_text("different")
        hash3 = manager.compute_output_hash(test_file)
        assert hash3 != hash1

    def test_compute_output_hash_missing_file(self, tmp_path):
        """Test computing hash of a nonexistent file returns None."""
        manager = SkillsConfigManager(project_root=tmp_path)
        assert manager.compute_output_hash(tmp_path / "missing.md") is None
