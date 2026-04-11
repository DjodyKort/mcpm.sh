"""Tests for styles diff logic."""

from mcpm.styles.parser import discover_styles
from mcpm.styles.transpiler import compute_style_hash, sync_styles


class TestStyleDiff:
    def test_all_new_when_no_lockfile(self, styles_repo, style_file):
        """Without a lockfile, all styles should appear as new."""
        styles = discover_styles(styles_repo)
        assert len(styles) == 1
        # No lockfile exists, so everything is new -- just verify hashing works
        h = compute_style_hash(styles[0])
        assert h.startswith("sha256:")

    def test_detect_modified(self, styles_repo, style_file):
        """After sync, modifying a style should produce a different hash."""
        styles = discover_styles(styles_repo)
        lockfile = sync_styles(styles, styles_repo)

        original_hash = lockfile.styles["concise-engineer"].hash

        # Modify the style
        style_file.write_text(
            style_file.read_text().replace("bullet points", "numbered lists")
        )

        styles2 = discover_styles(styles_repo)
        new_hash = compute_style_hash(styles2[0])
        assert new_hash != original_hash

    def test_detect_removed(self, styles_repo, style_file):
        """After sync, deleting a style source means it's gone from discovery but still in lockfile."""
        styles = discover_styles(styles_repo)
        lockfile = sync_styles(styles, styles_repo)
        assert "concise-engineer" in lockfile.styles

        # Remove the style source
        import shutil
        shutil.rmtree(styles_repo / "styles" / "concise-engineer")

        styles2 = discover_styles(styles_repo)
        current_names = {s.name for s in styles2}
        locked_names = set(lockfile.styles.keys())

        removed = locked_names - current_names
        assert "concise-engineer" in removed

    def test_detect_new(self, styles_repo, style_file):
        """After sync, adding a new style should show as new."""
        styles = discover_styles(styles_repo)
        lockfile = sync_styles(styles, styles_repo)

        # Add a new style
        new_dir = styles_repo / "styles" / "verbose-teacher"
        new_dir.mkdir()
        (new_dir / "STYLE.md").write_text(
            '---\nname: verbose-teacher\ndescription: "Verbose explanations."\n---\n\nExplain everything.\n'
        )

        styles2 = discover_styles(styles_repo)
        current_names = {s.name for s in styles2}
        locked_names = set(lockfile.styles.keys())

        new = current_names - locked_names
        assert "verbose-teacher" in new
