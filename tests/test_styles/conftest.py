"""Shared fixtures for styles tests."""

from pathlib import Path

import pytest

SAMPLE_STYLE_MD = """\
---
name: concise-engineer
description: "Terse, bullet-point responses. No filler."
keep-coding-instructions: true
---

- Answer in bullet points
- Skip preamble and summaries
- Code over prose
"""

SAMPLE_STYLE_NO_KEEP = """\
---
name: creative-writer
description: "Expressive and narrative responses."
keep-coding-instructions: false
---

Write like a storyteller. Use metaphors and vivid language.
"""

MINIMAL_STYLE_MD = """\
---
name: minimal
description: "Minimal style."
---

Be minimal.
"""


@pytest.fixture
def styles_repo(tmp_path: Path) -> Path:
    """Create a minimal styles repository."""
    (tmp_path / "mcpm-skills.yaml").write_text("name: test-styles\n")
    (tmp_path / "styles").mkdir()
    return tmp_path


@pytest.fixture
def style_file(styles_repo: Path) -> Path:
    """Create a single sample style."""
    style_dir = styles_repo / "styles" / "concise-engineer"
    style_dir.mkdir(parents=True)
    style_file = style_dir / "STYLE.md"
    style_file.write_text(SAMPLE_STYLE_MD)
    return style_file


@pytest.fixture
def two_styles(styles_repo: Path) -> Path:
    """Create two sample styles for testing."""
    for name, content in [("concise-engineer", SAMPLE_STYLE_MD), ("creative-writer", SAMPLE_STYLE_NO_KEEP)]:
        style_dir = styles_repo / "styles" / name
        style_dir.mkdir(parents=True)
        (style_dir / "STYLE.md").write_text(content)
    return styles_repo
