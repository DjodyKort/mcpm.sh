"""Tests for sync_styles, apply_style, remove_style orchestration."""


from mcpm.styles.parser import discover_styles
from mcpm.styles.transpiler import apply_style, remove_style, sync_styles


class TestSyncStyles:
    def test_sync_writes_tier1_only(self, styles_repo, style_file):
        styles = discover_styles(styles_repo)
        lockfile = sync_styles(styles, styles_repo)

        # Claude Code output should exist
        cc_path = styles_repo / ".claude" / "output-styles" / "concise-engineer.md"
        assert cc_path.exists()

        # Roo Code .roomodes should exist
        roomodes_path = styles_repo / ".roomodes"
        assert roomodes_path.exists()

        # Tier 2 files should NOT exist
        cursor_path = styles_repo / ".cursor" / "rules" / "mcpm-output-style" / "RULE.md"
        assert not cursor_path.exists()

        # Lockfile should have the style
        assert "concise-engineer" in lockfile.styles

    def test_sync_dry_run(self, styles_repo, style_file):
        styles = discover_styles(styles_repo)
        lockfile = sync_styles(styles, styles_repo, dry_run=True)

        # Nothing written
        cc_path = styles_repo / ".claude" / "output-styles" / "concise-engineer.md"
        assert not cc_path.exists()

        # But lockfile still populated
        assert "concise-engineer" in lockfile.styles

    def test_sync_client_filter(self, styles_repo, style_file):
        styles = discover_styles(styles_repo)
        sync_styles(styles, styles_repo, client_keys=["claude-code"])

        cc_path = styles_repo / ".claude" / "output-styles" / "concise-engineer.md"
        assert cc_path.exists()

        # Roo Code NOT synced
        roomodes_path = styles_repo / ".roomodes"
        assert not roomodes_path.exists()


class TestApplyStyle:
    def test_apply_writes_tier2(self, styles_repo, style_file):
        styles = discover_styles(styles_repo)
        lockfile = apply_style(styles[0], styles_repo)

        cursor_path = styles_repo / ".cursor" / "rules" / "mcpm-output-style" / "RULE.md"
        assert cursor_path.exists()
        assert "alwaysApply: true" in cursor_path.read_text()

        # active_styles tracked
        assert lockfile.active_styles["cursor"] == "concise-engineer"

    def test_apply_replaces_previous(self, two_styles):
        styles = discover_styles(two_styles)
        style1 = next(s for s in styles if s.name == "concise-engineer")
        style2 = next(s for s in styles if s.name == "creative-writer")

        lockfile = apply_style(style1, two_styles)
        assert lockfile.active_styles["cursor"] == "concise-engineer"

        # Apply different style - should overwrite
        lockfile = apply_style(style2, two_styles, lockfile=lockfile)
        assert lockfile.active_styles["cursor"] == "creative-writer"

        # Still only one file
        cursor_path = two_styles / ".cursor" / "rules" / "mcpm-output-style" / "RULE.md"
        content = cursor_path.read_text()
        assert "storyteller" in content

    def test_apply_client_filter(self, styles_repo, style_file):
        styles = discover_styles(styles_repo)
        lockfile = apply_style(styles[0], styles_repo, client_keys=["cursor"])

        assert "cursor" in lockfile.active_styles
        assert "windsurf" not in lockfile.active_styles


class TestRemoveStyle:
    def test_remove_deletes_files(self, styles_repo, style_file):
        styles = discover_styles(styles_repo)
        lockfile = apply_style(styles[0], styles_repo)

        cursor_path = styles_repo / ".cursor" / "rules" / "mcpm-output-style" / "RULE.md"
        assert cursor_path.exists()

        lockfile = remove_style(styles_repo, lockfile=lockfile)
        assert not cursor_path.exists()
        assert not lockfile.active_styles

    def test_remove_client_filter(self, styles_repo, style_file):
        styles = discover_styles(styles_repo)
        lockfile = apply_style(styles[0], styles_repo)

        lockfile = remove_style(styles_repo, client_keys=["cursor"], lockfile=lockfile)
        assert "cursor" not in lockfile.active_styles
        # Other clients still active
        assert "windsurf" in lockfile.active_styles

    def test_remove_noop_when_empty(self, styles_repo):
        from mcpm.skills.schema import LockFile

        lockfile = LockFile.create_now()
        lockfile = remove_style(styles_repo, lockfile=lockfile)
        assert not lockfile.active_styles

    def test_remove_zed_preserves_other_content(self, styles_repo, style_file):
        """Zed uses append-mode .rules -- remove should strip the style block, not delete the file."""
        # Write a .rules file with user content + style block
        rules_path = styles_repo / ".rules"
        rules_path.write_text("# My custom rules\n\nBe nice.\n")

        styles = discover_styles(styles_repo)
        lockfile = apply_style(styles[0], styles_repo, client_keys=["zed"])

        # .rules should have both user content and style block
        content = rules_path.read_text()
        assert "My custom rules" in content
        assert "mcpm-style:start" in content

        lockfile = remove_style(styles_repo, client_keys=["zed"], lockfile=lockfile)

        # File should still exist with user content, but style block gone
        assert rules_path.exists()
        content = rules_path.read_text()
        assert "My custom rules" in content
        assert "mcpm-style:start" not in content
