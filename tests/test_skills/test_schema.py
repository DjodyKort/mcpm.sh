"""Tests for skills schema validation."""

import pytest
from pydantic import ValidationError

from mcpm.skills.schema import LockFile, LockFileEntry, SkillDependencies, SkillFrontmatter, SkillsRepoManifest


class TestSkillFrontmatter:
    """Test SkillFrontmatter validation."""

    def test_valid_minimal(self):
        """Test minimal valid frontmatter."""
        fm = SkillFrontmatter(name="test-skill", description="A test skill.")
        assert fm.name == "test-skill"
        assert fm.activation == "auto"
        assert fm.priority == 0
        assert fm.globs is None

    def test_valid_full(self):
        """Test fully-populated frontmatter."""
        fm = SkillFrontmatter(
            name="code-review",
            description="Review code for bugs and style issues.",
            license="MIT",
            compatibility="Requires Python 3.11+",
            allowed_tools="Read Write Bash(git:*)",
            metadata={"author": "user", "version": "1.0.0"},
            globs="src/**/*.py",
            activation="agent",
            priority=100,
            dependencies=SkillDependencies(servers=["github"], skills=["base-review"]),
        )
        assert fm.name == "code-review"
        assert fm.activation == "agent"
        assert fm.dependencies.servers == ["github"]

    def test_invalid_name_uppercase(self):
        """Test that uppercase names are rejected."""
        with pytest.raises(ValidationError, match="lowercase"):
            SkillFrontmatter(name="Code-Review", description="Test")

    def test_invalid_name_consecutive_hyphens(self):
        """Test that consecutive hyphens are rejected."""
        with pytest.raises(ValidationError, match="consecutive hyphens"):
            SkillFrontmatter(name="code--review", description="Test")

    def test_invalid_name_starts_with_hyphen(self):
        """Test that names starting with hyphen are rejected."""
        with pytest.raises(ValidationError, match="start/end"):
            SkillFrontmatter(name="-code", description="Test")

    def test_invalid_name_ends_with_hyphen(self):
        """Test that names ending with hyphen are rejected."""
        with pytest.raises(ValidationError, match="start/end"):
            SkillFrontmatter(name="code-", description="Test")

    def test_invalid_name_too_long(self):
        """Test that names over 64 chars are rejected."""
        with pytest.raises(ValidationError, match="1-64"):
            SkillFrontmatter(name="a" * 65, description="Test")

    def test_invalid_name_empty(self):
        """Test that empty names are rejected."""
        with pytest.raises(ValidationError, match="1-64"):
            SkillFrontmatter(name="", description="Test")

    def test_invalid_description_empty(self):
        """Test that empty descriptions are rejected."""
        with pytest.raises(ValidationError, match="1-1024"):
            SkillFrontmatter(name="test", description="")

    def test_invalid_description_too_long(self):
        """Test that descriptions over 1024 chars are rejected."""
        with pytest.raises(ValidationError, match="1-1024"):
            SkillFrontmatter(name="test", description="x" * 1025)

    def test_invalid_compatibility_too_long(self):
        """Test that compatibility over 500 chars is rejected."""
        with pytest.raises(ValidationError, match="500"):
            SkillFrontmatter(name="test", description="Test", compatibility="x" * 501)

    def test_valid_activation_modes(self):
        """Test all valid activation modes."""
        for mode in ["always", "auto", "agent", "manual"]:
            fm = SkillFrontmatter(name="test", description="Test", activation=mode)
            assert fm.activation == mode

    def test_invalid_activation_mode(self):
        """Test that invalid activation modes are rejected."""
        with pytest.raises(ValidationError):
            SkillFrontmatter(name="test", description="Test", activation="invalid")

    def test_single_char_name(self):
        """Test single character name is valid."""
        fm = SkillFrontmatter(name="a", description="Test")
        assert fm.name == "a"

    def test_numeric_name(self):
        """Test purely numeric name is valid."""
        fm = SkillFrontmatter(name="123", description="Test")
        assert fm.name == "123"


class TestLockFile:
    """Test LockFile model."""

    def test_create_now(self):
        """Test creating a lockfile with current timestamp."""
        lf = LockFile.create_now()
        assert lf.version == 1
        assert lf.synced_at != ""
        assert lf.skills == {}
        assert lf.rules == {}

    def test_with_entries(self):
        """Test lockfile with skill and rule entries."""
        lf = LockFile(
            synced_at="2026-04-04T12:00:00Z",
            skills={
                "code-review": LockFileEntry(
                    hash="sha256:abc123",
                    clients_synced=["claude-code", "cursor"],
                )
            },
            rules={
                "coding-standards": LockFileEntry(
                    hash="sha256:def456",
                    clients_synced=["claude-code"],
                )
            },
        )
        assert "code-review" in lf.skills
        assert lf.skills["code-review"].clients_synced == ["claude-code", "cursor"]

    def test_serialization_roundtrip(self):
        """Test that lockfile serializes and deserializes correctly."""
        lf = LockFile.create_now()
        lf.skills["test"] = LockFileEntry(hash="sha256:abc", clients_synced=["cursor"])
        data = lf.model_dump()
        lf2 = LockFile(**data)
        assert lf2.skills["test"].hash == "sha256:abc"


class TestSkillsRepoManifest:
    """Test SkillsRepoManifest model."""

    def test_minimal(self):
        """Test minimal manifest."""
        m = SkillsRepoManifest(name="my-skills")
        assert m.name == "my-skills"
        assert m.version == "1.0.0"

    def test_full(self):
        """Test fully-populated manifest."""
        m = SkillsRepoManifest(
            name="my-skills",
            description="My skills collection",
            author="testuser",
            version="2.0.0",
            license="MIT",
            default_profile="work",
        )
        assert m.default_profile == "work"
