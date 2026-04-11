"""Tests for style transpilers -- output paths and content format."""

import json
from pathlib import Path

import pytest

from mcpm.styles.parser import parse_style_file
from mcpm.styles.transpiler import get_all_style_transpilers, get_tier1_transpilers, get_tier2_transpilers

from .conftest import SAMPLE_STYLE_MD


@pytest.fixture
def style(tmp_path):
    style_dir = tmp_path / "styles" / "concise-engineer"
    style_dir.mkdir(parents=True)
    f = style_dir / "STYLE.md"
    f.write_text(SAMPLE_STYLE_MD)
    return parse_style_file(f)


class TestTranspilerRegistry:
    def test_all_transpilers_loaded(self):
        t = get_all_style_transpilers()
        assert len(t) == 15

    def test_tier1_count(self):
        assert len(get_tier1_transpilers()) == 2

    def test_tier2_count(self):
        assert len(get_tier2_transpilers()) == 13

    def test_tier1_keys(self):
        keys = set(get_tier1_transpilers().keys())
        assert keys == {"claude-code", "roomodes-style"}

    def test_tier2_keys(self):
        keys = set(get_tier2_transpilers().keys())
        expected = {
            "cursor", "windsurf", "vscode-copilot", "gemini-cli", "codex-cli",
            "continue", "jetbrains", "cline", "zed", "amazon-q", "aider", "trae", "goose",
        }
        assert keys == expected


class TestClaudeCodeStyleTranspiler:
    def test_output_path(self, style, tmp_path):
        t = get_tier1_transpilers()["claude-code"]
        path = t.get_output_path(style, tmp_path)
        assert path == tmp_path / ".claude" / "output-styles" / "concise-engineer.md"

    def test_transpile_content(self, style, tmp_path):
        t = get_tier1_transpilers()["claude-code"]
        result = t.transpile(style, tmp_path)
        assert "name: concise-engineer" in result.content
        assert "keep-coding-instructions: true" in result.content
        assert "bullet points" in result.content


class TestRooCodeStyleTranspiler:
    def test_output_path(self, style, tmp_path):
        t = get_tier1_transpilers()["roomodes-style"]
        path = t.get_output_path(style, tmp_path)
        assert path == tmp_path / ".roomodes"

    def test_transpile_single(self, style, tmp_path):
        t = get_tier1_transpilers()["roomodes-style"]
        result = t.transpile(style, tmp_path)
        mode = json.loads(result.content)
        assert mode["slug"] == "style-concise-engineer"
        assert mode["name"] == "Concise Engineer"
        assert "bullet points" in mode["customInstructions"]

    def test_transpile_all_merges_with_agents(self, style, tmp_path):
        """Verify that transpile_all preserves existing non-style modes."""
        # Write existing .roomodes with an agent mode
        existing = {
            "customModes": [
                {"slug": "my-agent", "name": "Agent", "roleDefinition": "test", "customInstructions": "test"}
            ]
        }
        roomodes_path = tmp_path / ".roomodes"
        roomodes_path.write_text(json.dumps(existing))

        t = get_tier1_transpilers()["roomodes-style"]
        result = t.transpile_all([style], tmp_path)
        data = json.loads(result.content)

        slugs = [m["slug"] for m in data["customModes"]]
        assert "my-agent" in slugs  # preserved
        assert "style-concise-engineer" in slugs  # added

    def test_transpile_all_replaces_old_styles(self, style, tmp_path):
        """Verify that old style- modes are replaced, not duplicated."""
        existing = {
            "customModes": [
                {"slug": "style-old", "name": "Old", "roleDefinition": "old", "customInstructions": "old"},
                {"slug": "my-agent", "name": "Agent", "roleDefinition": "test", "customInstructions": "test"},
            ]
        }
        roomodes_path = tmp_path / ".roomodes"
        roomodes_path.write_text(json.dumps(existing))

        t = get_tier1_transpilers()["roomodes-style"]
        result = t.transpile_all([style], tmp_path)
        data = json.loads(result.content)

        slugs = [m["slug"] for m in data["customModes"]]
        assert "style-old" not in slugs  # removed
        assert "style-concise-engineer" in slugs  # added
        assert "my-agent" in slugs  # preserved

    def test_clean_only_removes_styles(self, tmp_path):
        data = {
            "customModes": [
                {"slug": "style-test", "name": "Test"},
                {"slug": "my-agent", "name": "Agent"},
            ]
        }
        roomodes_path = tmp_path / ".roomodes"
        roomodes_path.write_text(json.dumps(data))

        t = get_tier1_transpilers()["roomodes-style"]
        t.clean(tmp_path)

        result = json.loads(roomodes_path.read_text())
        slugs = [m["slug"] for m in result["customModes"]]
        assert "style-test" not in slugs
        assert "my-agent" in slugs


class TestTier2OutputPaths:
    """Verify all Tier 2 transpilers write to expected fixed paths."""

    EXPECTED_PATHS = {
        "cursor": ".cursor/rules/mcpm-output-style/RULE.md",
        "windsurf": ".windsurf/rules/mcpm-output-style.md",
        "vscode-copilot": ".github/instructions/mcpm-output-style.instructions.md",
        "gemini-cli": ".gemini/skills/mcpm-output-style/SKILL.md",
        "codex-cli": ".agents/skills/mcpm-output-style/SKILL.md",
        "continue": ".continue/rules/mcpm-output-style.md",
        "jetbrains": ".aiassistant/rules/mcpm-output-style.md",
        "cline": ".clinerules/mcpm-output-style.md",
        "zed": ".rules",
        "amazon-q": ".amazonq/rules/mcpm-output-style.md",
        "aider": ".mcpm/skills/mcpm-output-style/SKILL.md",
        "trae": ".trae/rules/mcpm-output-style.md",
        "goose": ".goose/rules/mcpm-output-style.md",
    }

    @pytest.mark.parametrize("client_key,expected_suffix", list(EXPECTED_PATHS.items()))
    def test_output_path(self, client_key, expected_suffix, style, tmp_path):
        t = get_tier2_transpilers()[client_key]
        path = t.get_output_path(style, tmp_path)
        assert path == tmp_path / Path(expected_suffix)
