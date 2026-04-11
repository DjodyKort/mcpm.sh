"""Tests for styles parser."""

import pytest

from mcpm.styles.parser import discover_styles, parse_style_file

from .conftest import MINIMAL_STYLE_MD, SAMPLE_STYLE_MD


class TestParseStyleFile:
    def test_parse_full_style(self, style_file):
        style = parse_style_file(style_file)
        assert style.name == "concise-engineer"
        assert style.frontmatter.description == "Terse, bullet-point responses. No filler."
        assert style.frontmatter.keep_coding_instructions is True
        assert "bullet points" in style.body

    def test_parse_minimal_style(self, tmp_path):
        style_dir = tmp_path / "styles" / "minimal"
        style_dir.mkdir(parents=True)
        f = style_dir / "STYLE.md"
        f.write_text(MINIMAL_STYLE_MD)

        style = parse_style_file(f)
        assert style.name == "minimal"
        assert style.frontmatter.keep_coding_instructions is True  # default

    def test_parse_no_frontmatter(self, tmp_path):
        f = tmp_path / "STYLE.md"
        f.write_text("Just a body, no frontmatter.")

        with pytest.raises(ValueError, match="No YAML frontmatter"):
            parse_style_file(f)

    def test_parse_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            parse_style_file(tmp_path / "nonexistent.md")

    def test_hyphen_to_underscore_normalization(self, tmp_path):
        """Test that keep-coding-instructions (hyphenated) maps to keep_coding_instructions."""
        style_dir = tmp_path / "styles" / "test"
        style_dir.mkdir(parents=True)
        f = style_dir / "STYLE.md"
        f.write_text(SAMPLE_STYLE_MD)

        style = parse_style_file(f)
        assert style.frontmatter.keep_coding_instructions is True


class TestDiscoverStyles:
    def test_discover_single(self, styles_repo, style_file):
        styles = discover_styles(styles_repo)
        assert len(styles) == 1
        assert styles[0].name == "concise-engineer"

    def test_discover_multiple(self, two_styles):
        styles = discover_styles(two_styles)
        assert len(styles) == 2
        names = {s.name for s in styles}
        assert names == {"concise-engineer", "creative-writer"}

    def test_discover_empty(self, styles_repo):
        styles = discover_styles(styles_repo)
        assert len(styles) == 0

    def test_discover_no_styles_dir(self, tmp_path):
        styles = discover_styles(tmp_path)
        assert len(styles) == 0

    def test_discover_skips_non_dirs(self, styles_repo):
        (styles_repo / "styles" / "stray-file.txt").write_text("not a dir")
        styles = discover_styles(styles_repo)
        assert len(styles) == 0

    def test_discover_skips_missing_style_md(self, styles_repo):
        (styles_repo / "styles" / "no-file").mkdir()
        styles = discover_styles(styles_repo)
        assert len(styles) == 0
