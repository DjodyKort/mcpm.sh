"""STYLE.md parser -- reuses the frontmatter parser from skills."""

import logging
from pathlib import Path
from typing import List

from mcpm.skills.parser import parse_frontmatter
from mcpm.styles.schema import StyleConfig, StyleFrontmatter

logger = logging.getLogger(__name__)


def parse_style_file(path: Path) -> StyleConfig:
    """Parse a single STYLE.md file into a StyleConfig.

    Args:
        path: Path to the STYLE.md file.

    Returns:
        Parsed StyleConfig.

    Raises:
        ValueError: If the file cannot be parsed or frontmatter is invalid.
        FileNotFoundError: If the file doesn't exist.
    """
    if not path.exists():
        raise FileNotFoundError(f"Style file not found: {path}")

    content = path.read_text(encoding="utf-8")
    fm_data, body = parse_frontmatter(content)

    if not fm_data:
        raise ValueError(f"No YAML frontmatter found in {path}")

    frontmatter = StyleFrontmatter(**fm_data)

    return StyleConfig(
        frontmatter=frontmatter,
        body=body,
        source_path=path,
    )


def discover_styles(repo_path: Path) -> List[StyleConfig]:
    """Walk the styles/ directory and parse all STYLE.md files.

    Args:
        repo_path: Root of the skills repository.

    Returns:
        List of parsed StyleConfigs.
    """
    styles: List[StyleConfig] = []

    styles_dir = repo_path / "styles"
    if not styles_dir.is_dir():
        return styles

    for style_dir in sorted(styles_dir.iterdir()):
        if not style_dir.is_dir():
            continue

        style_file = style_dir / "STYLE.md"
        if not style_file.exists():
            logger.warning(f"Style directory {style_dir.name} has no STYLE.md, skipping")
            continue

        try:
            style = parse_style_file(style_file)
            styles.append(style)
        except (ValueError, Exception) as e:
            logger.warning(f"Failed to parse {style_file}: {e}")

    return styles
