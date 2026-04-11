"""Stress tests for the output styles system -- edge cases and multi-client scenarios."""

import json

from mcpm.styles.parser import discover_styles, parse_style_file
from mcpm.styles.transpiler import apply_style, get_all_style_transpilers, remove_style, sync_styles


class TestStyleParserEdgeCases:
    def test_unicode_style_body(self, styles_repo):
        style_dir = styles_repo / "styles" / "japanese"
        style_dir.mkdir(parents=True)
        (style_dir / "STYLE.md").write_text(
            '---\nname: japanese\ndescription: "日本語スタイル"\n---\n\n日本語で答えてください。\n',
            encoding="utf-8",
        )
        style = parse_style_file(style_dir / "STYLE.md")
        assert style.name == "japanese"
        assert "日本語" in style.body

    def test_very_long_body(self, styles_repo):
        style_dir = styles_repo / "styles" / "verbose"
        style_dir.mkdir(parents=True)
        long_body = "- Point number {i}\n" * 5000
        (style_dir / "STYLE.md").write_text(
            f'---\nname: verbose\ndescription: "A very verbose style for testing."\n---\n\n{long_body}'
        )
        style = parse_style_file(style_dir / "STYLE.md")
        assert len(style.body.split("\n")) > 4000

    def test_special_chars_in_description(self, styles_repo):
        style_dir = styles_repo / "styles" / "special"
        style_dir.mkdir(parents=True)
        (style_dir / "STYLE.md").write_text(
            '---\nname: special\ndescription: "Style with \\"quotes\\" and $pecial ch@rs!"\n---\n\nBody.\n'
        )
        style = parse_style_file(style_dir / "STYLE.md")
        assert "quotes" in style.frontmatter.description

    def test_many_styles_discovery(self, styles_repo):
        """Discover 50 styles."""
        for i in range(50):
            d = styles_repo / "styles" / f"style-{i:03d}"
            d.mkdir(parents=True)
            (d / "STYLE.md").write_text(
                f'---\nname: style-{i:03d}\ndescription: "Style number {i} for stress testing."\n---\n\nBe style {i}.\n'
            )
        styles = discover_styles(styles_repo)
        assert len(styles) == 50


class TestSyncStress:
    def test_sync_many_styles_to_tier1(self, styles_repo):
        """Sync 10 styles to Tier 1 clients."""
        for i in range(10):
            d = styles_repo / "styles" / f"style-{i}"
            d.mkdir(parents=True)
            (d / "STYLE.md").write_text(
                f'---\nname: style-{i}\ndescription: "Test style {i} for sync stress testing."\n---\n\nBe style {i}.\n'
            )
        styles = discover_styles(styles_repo)
        lockfile = sync_styles(styles, styles_repo)

        # All 10 should be synced
        assert len(lockfile.styles) == 10

        # Claude Code should have 10 files
        for i in range(10):
            path = styles_repo / ".claude" / "output-styles" / f"style-{i}.md"
            assert path.exists(), f"Missing {path}"

        # Roo Code should have 10 modes in .roomodes
        roomodes = json.loads((styles_repo / ".roomodes").read_text())
        style_modes = [m for m in roomodes["customModes"] if m["slug"].startswith("style-")]
        assert len(style_modes) == 10

    def test_apply_then_apply_different_overwrites(self, styles_repo):
        """Apply style A, then style B -- B should replace A everywhere."""
        for name in ["style-a", "style-b"]:
            d = styles_repo / "styles" / name
            d.mkdir(parents=True)
            (d / "STYLE.md").write_text(
                f'---\nname: {name}\ndescription: "Test {name} for overwrite testing."\n---\n\nBe {name}.\n'
            )
        styles = discover_styles(styles_repo)
        style_a = next(s for s in styles if s.name == "style-a")
        style_b = next(s for s in styles if s.name == "style-b")

        lockfile = apply_style(style_a, styles_repo)
        assert all(v == "style-a" for v in lockfile.active_styles.values())

        # Check Cursor has style-a content
        cursor_path = styles_repo / ".cursor" / "rules" / "mcpm-output-style" / "RULE.md"
        assert "style-a" in cursor_path.read_text()

        # Now apply style-b
        lockfile = apply_style(style_b, styles_repo, lockfile=lockfile)
        assert all(v == "style-b" for v in lockfile.active_styles.values())

        # Cursor now has style-b
        assert "style-b" in cursor_path.read_text()
        assert "style-a" not in cursor_path.read_text()

    def test_apply_remove_apply_cycle(self, styles_repo, style_file):
        """Apply -> remove -> apply cycle should work cleanly."""
        styles = discover_styles(styles_repo)
        style = styles[0]

        # Apply
        lockfile = apply_style(style, styles_repo)
        cursor_path = styles_repo / ".cursor" / "rules" / "mcpm-output-style" / "RULE.md"
        assert cursor_path.exists()

        # Remove
        lockfile = remove_style(styles_repo, lockfile=lockfile)
        assert not cursor_path.exists()
        assert not lockfile.active_styles

        # Apply again
        lockfile = apply_style(style, styles_repo, lockfile=lockfile)
        assert cursor_path.exists()
        assert lockfile.active_styles["cursor"] == style.name

    def test_sync_and_apply_coexist(self, styles_repo, style_file):
        """Tier 1 sync and Tier 2 apply should not interfere."""
        styles = discover_styles(styles_repo)

        # Sync to Tier 1
        lockfile = sync_styles(styles, styles_repo)
        cc_path = styles_repo / ".claude" / "output-styles" / "concise-engineer.md"
        assert cc_path.exists()

        # Apply to Tier 2
        lockfile = apply_style(styles[0], styles_repo, lockfile=lockfile)
        cursor_path = styles_repo / ".cursor" / "rules" / "mcpm-output-style" / "RULE.md"
        assert cursor_path.exists()

        # Both should coexist
        assert cc_path.exists()
        assert cursor_path.exists()

    def test_all_tier2_transpilers_produce_output(self, styles_repo, style_file):
        """Every Tier 2 transpiler should write a file on apply."""
        styles = discover_styles(styles_repo)
        apply_style(styles[0], styles_repo)

        transpilers = get_all_style_transpilers()
        tier2 = {k: v for k, v in transpilers.items() if v.tier == 2}

        for client_key, transpiler in tier2.items():
            path = transpiler.get_output_path(styles[0], styles_repo)
            if client_key == "zed":
                # Zed is append-mode -- check .rules exists and has content
                assert path.exists(), "Zed .rules not created"
                assert "mcpm-style:start" in path.read_text()
            else:
                assert path.exists(), f"{client_key}: output not created at {path}"

    def test_roo_code_styles_and_agents_coexist(self, styles_repo, style_file):
        """Styles in .roomodes should not clobber agent modes."""
        # Write existing .roomodes with agent modes
        roomodes_path = styles_repo / ".roomodes"
        existing = {
            "customModes": [
                {"slug": "code-reviewer", "name": "Code Reviewer",
                 "roleDefinition": "Reviews code", "customInstructions": "Be thorough"},
            ]
        }
        roomodes_path.write_text(json.dumps(existing))

        # Sync styles
        styles = discover_styles(styles_repo)
        sync_styles(styles, styles_repo)

        # Both should be present
        data = json.loads(roomodes_path.read_text())
        slugs = [m["slug"] for m in data["customModes"]]
        assert "code-reviewer" in slugs  # agent preserved
        assert "style-concise-engineer" in slugs  # style added

    def test_clean_removes_all_style_files(self, styles_repo, style_file):
        """Clean should remove every file from every client."""
        styles = discover_styles(styles_repo)
        sync_styles(styles, styles_repo)
        apply_style(styles[0], styles_repo)

        # Verify files exist
        assert (styles_repo / ".claude" / "output-styles" / "concise-engineer.md").exists()
        assert (styles_repo / ".cursor" / "rules" / "mcpm-output-style" / "RULE.md").exists()

        # Clean all
        transpilers = get_all_style_transpilers()
        for client_key, transpiler in transpilers.items():
            transpiler.clean(styles_repo, managed_styles=["concise-engineer"])

        # Tier 2 files should be gone
        assert not (styles_repo / ".cursor" / "rules" / "mcpm-output-style" / "RULE.md").exists()
        assert not (styles_repo / ".windsurf" / "rules" / "mcpm-output-style.md").exists()
