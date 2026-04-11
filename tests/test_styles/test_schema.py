"""Tests for styles schema validation."""

from pathlib import Path

import pytest

from mcpm.styles.schema import StyleConfig, StyleFrontmatter


class TestStyleFrontmatter:
    def test_valid_name(self):
        fm = StyleFrontmatter(name="concise-engineer", description="A concise style.")
        assert fm.name == "concise-engineer"

    def test_name_too_long(self):
        with pytest.raises(ValueError, match="1-64 characters"):
            StyleFrontmatter(name="a" * 65, description="test")

    def test_name_empty(self):
        with pytest.raises(ValueError, match="1-64 characters"):
            StyleFrontmatter(name="", description="test")

    def test_name_invalid_chars(self):
        with pytest.raises(ValueError, match="lowercase alphanumeric"):
            StyleFrontmatter(name="UPPER_CASE", description="test")

    def test_name_consecutive_hyphens(self):
        with pytest.raises(ValueError, match="consecutive hyphens"):
            StyleFrontmatter(name="bad--name", description="test")

    def test_name_starts_with_hyphen(self):
        with pytest.raises(ValueError, match="cannot start/end"):
            StyleFrontmatter(name="-bad", description="test")

    def test_description_too_long(self):
        with pytest.raises(ValueError, match="1-1024 characters"):
            StyleFrontmatter(name="test", description="a" * 1025)

    def test_description_empty(self):
        with pytest.raises(ValueError, match="1-1024 characters"):
            StyleFrontmatter(name="test", description="")

    def test_keep_coding_instructions_default_true(self):
        fm = StyleFrontmatter(name="test", description="test")
        assert fm.keep_coding_instructions is True

    def test_keep_coding_instructions_false(self):
        fm = StyleFrontmatter(name="test", description="test", keep_coding_instructions=False)
        assert fm.keep_coding_instructions is False

    def test_metadata_default_empty(self):
        fm = StyleFrontmatter(name="test", description="test")
        assert fm.metadata == {}


class TestStyleConfig:
    def test_name_property(self):
        fm = StyleFrontmatter(name="my-style", description="test")
        config = StyleConfig(frontmatter=fm, body="body", source_path=Path("test.md"))
        assert config.name == "my-style"
