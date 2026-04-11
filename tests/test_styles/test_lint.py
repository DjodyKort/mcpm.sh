"""Tests for styles lint."""

from mcpm.styles.lint import lint_style, lint_styles
from mcpm.styles.parser import discover_styles, parse_style_file


class TestLintStyle:
    def test_valid_style_no_issues(self, style_file):
        style = parse_style_file(style_file)
        result = lint_style(style)
        # The sample style has a good description and body
        assert not result.has_errors

    def test_short_description(self, styles_repo):
        style_dir = styles_repo / "styles" / "bad"
        style_dir.mkdir(parents=True)
        (style_dir / "STYLE.md").write_text(
            '---\nname: bad\ndescription: "Short."\n---\n\nSome body.\n'
        )
        style = parse_style_file(style_dir / "STYLE.md")
        result = lint_style(style)
        assert any("very short" in m.message for m in result.warnings)

    def test_placeholder_description(self, styles_repo):
        style_dir = styles_repo / "styles" / "placeholder"
        style_dir.mkdir(parents=True)
        (style_dir / "STYLE.md").write_text(
            '---\nname: placeholder\ndescription: "TODO"\n---\n\nSome body.\n'
        )
        style = parse_style_file(style_dir / "STYLE.md")
        result = lint_style(style)
        assert any("placeholder" in m.message for m in result.warnings)

    def test_empty_body(self, styles_repo):
        style_dir = styles_repo / "styles" / "empty"
        style_dir.mkdir(parents=True)
        (style_dir / "STYLE.md").write_text(
            '---\nname: empty\ndescription: "A style with an empty body for testing."\n---\n\n'
        )
        style = parse_style_file(style_dir / "STYLE.md")
        result = lint_style(style)
        assert any("empty" in m.message.lower() for m in result.warnings)

    def test_name_dir_mismatch(self, styles_repo):
        style_dir = styles_repo / "styles" / "wrong-dir"
        style_dir.mkdir(parents=True)
        (style_dir / "STYLE.md").write_text(
            '---\nname: correct-name\ndescription: "A mismatched style name test."\n---\n\nBody.\n'
        )
        style = parse_style_file(style_dir / "STYLE.md")
        result = lint_style(style)
        assert result.has_errors
        assert any("does not match directory" in m.message for m in result.errors)


class TestLintStyles:
    def test_duplicate_names(self, styles_repo):
        """Two styles with the same name should error."""
        from pathlib import Path

        from mcpm.styles.schema import StyleConfig, StyleFrontmatter

        fm = StyleFrontmatter(name="dupe", description="A duplicate style for testing.")
        styles = [
            StyleConfig(frontmatter=fm, body="body1", source_path=Path("a/STYLE.md")),
            StyleConfig(frontmatter=fm, body="body2", source_path=Path("b/STYLE.md")),
        ]
        result = lint_styles(styles)
        assert result.has_errors
        assert any("Duplicate" in m.message for m in result.errors)

    def test_collection_lint(self, two_styles):
        styles = discover_styles(two_styles)
        result = lint_styles(styles)
        # Both sample styles are well-formed
        assert not result.has_errors
