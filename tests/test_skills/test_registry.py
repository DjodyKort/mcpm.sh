"""Tests for skills registry schema."""

from mcpm.skills.registry import SkillRegistryEntry, SkillRegistryIndex


class TestSkillRegistryEntry:
    def test_minimal(self):
        """Test creating a minimal registry entry."""
        entry = SkillRegistryEntry(
            name="code-review",
            display_name="Code Review",
            description="Automated code review with style checks.",
            repository="https://github.com/user/skills",
            author="testuser",
        )
        assert entry.name == "code-review"
        assert entry.version == "1.0.0"
        assert entry.downloads == 0

    def test_full(self):
        """Test creating a fully-populated registry entry."""
        entry = SkillRegistryEntry(
            name="terraform-azure",
            display_name="Terraform Azure",
            description="Terraform best practices for Azure infrastructure.",
            repository="https://github.com/user/skills",
            author="testuser",
            license="MIT",
            version="2.1.0",
            categories=["devops"],
            tags=["terraform", "azure", "infrastructure"],
            activation="auto",
            globs="*.tf",
            server_dependencies=["filesystem"],
            skill_dependencies=["code-review"],
            install_spec="@user/skills/terraform-azure@2.1.0",
            client_compatibility={"claude-code": "full", "zed": "always-only"},
        )
        assert entry.server_dependencies == ["filesystem"]
        assert entry.client_compatibility["zed"] == "always-only"


class TestSkillRegistryIndex:
    def test_search(self):
        """Test searching the registry index."""
        index = SkillRegistryIndex(
            skills=[
                SkillRegistryEntry(
                    name="code-review",
                    display_name="Code Review",
                    description="Automated code review.",
                    repository="https://github.com/user/skills",
                    author="user",
                    tags=["quality", "review"],
                ),
                SkillRegistryEntry(
                    name="terraform",
                    display_name="Terraform",
                    description="Terraform best practices.",
                    repository="https://github.com/user/skills",
                    author="user",
                    tags=["devops", "infrastructure"],
                ),
            ]
        )

        results = index.search("review")
        assert len(results) == 1
        assert results[0].name == "code-review"

        results = index.search("terraform")
        assert len(results) == 1
        assert results[0].name == "terraform"

        results = index.search("devops")
        assert len(results) == 1

        results = index.search("nonexistent")
        assert len(results) == 0

    def test_empty_search(self):
        """Test searching an empty registry."""
        index = SkillRegistryIndex()
        results = index.search("anything")
        assert results == []
