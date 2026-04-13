"""SKILL.md parser -- YAML frontmatter + Markdown body."""

import logging
import re
from pathlib import Path
from typing import List, Optional

from ruamel.yaml import YAML

from mcpm.skills.schema import SkillConfig, SkillFrontmatter

logger = logging.getLogger(__name__)

yaml = YAML()
yaml.preserve_quotes = True

# Frontmatter delimiter pattern: starts with ---, ends with ---
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)---\s*\n?(.*)", re.DOTALL)


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """Split SKILL.md content into frontmatter dict and body string.

    Returns:
        Tuple of (frontmatter_dict, body_string). If no frontmatter found,
        returns ({}, full_content).
    """
    match = _FRONTMATTER_RE.match(content)
    if not match:
        return {}, content

    yaml_str = match.group(1)
    body = match.group(2).strip()

    from io import StringIO

    data = yaml.load(StringIO(yaml_str))
    if data is None:
        data = {}

    # Convert ruamel types to plain dicts/lists
    result = {}
    for key, value in data.items():
        # Normalize key: YAML allows hyphens, Pydantic uses underscores
        normalized_key = str(key).replace("-", "_")
        result[normalized_key] = _to_plain(value)

    return result, body


def _to_plain(obj):
    """Convert ruamel.yaml types to plain Python types."""
    if hasattr(obj, "items"):
        return {str(k): _to_plain(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_plain(item) for item in obj]
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        return obj
    return str(obj) if obj is not None else None


def parse_skill_file(path: Path) -> SkillConfig:
    """Parse a single SKILL.md file into a SkillConfig.

    Args:
        path: Path to the SKILL.md file.

    Returns:
        Parsed SkillConfig.

    Raises:
        ValueError: If the file cannot be parsed or frontmatter is invalid.
        FileNotFoundError: If the file doesn't exist.
    """
    if not path.exists():
        raise FileNotFoundError(f"Skill file not found: {path}")

    content = path.read_text(encoding="utf-8")
    fm_data, body = parse_frontmatter(content)

    if not fm_data:
        raise ValueError(f"No YAML frontmatter found in {path}")

    frontmatter = SkillFrontmatter(**fm_data)

    # Determine skill type from directory structure or activation mode
    skill_type = _infer_skill_type(path, frontmatter)

    return SkillConfig(
        frontmatter=frontmatter,
        body=body,
        source_path=path,
        skill_type=skill_type,
    )


def _infer_skill_type(path: Path, frontmatter: SkillFrontmatter) -> str:
    """Infer whether this is a 'skill' or 'rule' based on path and activation mode."""
    # Check if it's under a rules/ directory
    parts = path.parts
    for part in parts:
        if part == "rules":
            return "rule"

    # Fall back to activation mode
    if frontmatter.activation == "always":
        return "rule"
    return "skill"


def discover_skills(repo_path: Path) -> List[SkillConfig]:
    """Walk a skills repository and parse all SKILL.md files.

    Looks in both skills/ and rules/ directories.

    Args:
        repo_path: Root of the skills repository.

    Returns:
        List of parsed SkillConfigs.
    """
    skills: List[SkillConfig] = []

    for search_dir in ["skills", "rules"]:
        dir_path = repo_path / search_dir
        if not dir_path.is_dir():
            continue

        for skill_dir in sorted(dir_path.iterdir()):
            if not skill_dir.is_dir():
                continue

            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                logger.warning(f"Skill directory {skill_dir.name} has no SKILL.md, skipping")
                continue

            try:
                skill = parse_skill_file(skill_file)
                skills.append(skill)
            except (ValueError, Exception) as e:
                logger.warning(f"Failed to parse {skill_file}: {e}")

    return skills


def find_skills_repo(start_path: Optional[Path] = None) -> Optional[Path]:
    """Find the skills repository root by looking for mcpm-skills.yaml or skills/ directory.

    Searches from start_path upward. Falls back to the git-sync clone path
    if configured and no local repo is found.

    Args:
        start_path: Starting directory (defaults to cwd).

    Returns:
        Path to the skills repo root, or None if not found.
    """
    if start_path is None:
        start_path = Path.cwd()

    current = start_path.resolve()
    for _ in range(20):  # safety limit
        if (current / "mcpm-skills.yaml").exists():
            return current
        if (current / "skills").is_dir() or (current / "rules").is_dir() or (current / "agents").is_dir() or (current / "styles").is_dir():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent

    # Fallback: check git-sync clone path (reads config directly, no plugin import)
    try:
        from mcpm.utils.platform import get_config_directory

        sync_config_path = get_config_directory() / "skills_sync.json"
        if sync_config_path.exists():
            import json

            data = json.loads(sync_config_path.read_text(encoding="utf-8"))
            local_path = data.get("local_path")
            if local_path:
                p = Path(local_path)
                if p.exists():
                    return p
    except Exception:
        pass

    return None
