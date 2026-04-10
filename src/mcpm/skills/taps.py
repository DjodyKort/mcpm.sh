"""Tap system -- git-based skill repositories (Homebrew model)."""

import json
import logging
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from mcpm.skills.parser import discover_skills
from mcpm.skills.schema import SkillConfig
from mcpm.utils.platform import get_config_directory

logger = logging.getLogger(__name__)

TAPS_DIR = get_config_directory() / "taps"
TAPS_INDEX = get_config_directory() / "taps_index.json"


class TapManager:
    """Manages remote skill repository taps."""

    def __init__(self, taps_dir: Optional[Path] = None, index_path: Optional[Path] = None):
        self.taps_dir = taps_dir or TAPS_DIR
        self.index_path = index_path or TAPS_INDEX
        self.taps_dir.mkdir(parents=True, exist_ok=True)

    def _load_index(self) -> Dict[str, dict]:
        """Load the taps index."""
        if not self.index_path.exists():
            return {}
        try:
            return json.loads(self.index_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, Exception):
            return {}

    def _save_index(self, index: Dict[str, dict]) -> None:
        """Save the taps index."""
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")

    def _tap_key(self, repo: str) -> str:
        """Convert user/repo to a filesystem-safe key."""
        return repo.replace("/", "-")

    def add(self, repo: str, alias: Optional[str] = None) -> bool:
        """Register and clone a tap.

        Args:
            repo: GitHub user/repo (e.g. 'anthropics/skills').
            alias: Optional alias name for the tap.

        Returns:
            True if successful.
        """
        key = alias or self._tap_key(repo)
        index = self._load_index()

        if key in index:
            logger.warning(f"Tap '{key}' already exists")
            return False

        tap_path = self.taps_dir / key
        url = f"https://github.com/{repo}.git"

        try:
            subprocess.run(
                ["git", "clone", "--depth", "1", url, str(tap_path)],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to clone {url}: {e.stderr}")
            return False

        index[key] = {"repo": repo, "url": url, "path": str(tap_path)}
        self._save_index(index)
        return True

    def remove(self, name: str) -> bool:
        """Unregister and remove a tap."""
        index = self._load_index()
        if name not in index:
            return False

        tap_path = Path(index[name]["path"])
        if tap_path.exists():
            import shutil

            shutil.rmtree(tap_path, ignore_errors=True)

        del index[name]
        self._save_index(index)
        return True

    def update(self, name: Optional[str] = None) -> Dict[str, bool]:
        """Git pull one or all taps.

        Returns:
            Dict mapping tap names to update success status.
        """
        index = self._load_index()
        results = {}

        targets = {name: index[name]} if name and name in index else index

        for tap_name, tap_info in targets.items():
            tap_path = Path(tap_info["path"])
            if not tap_path.exists():
                results[tap_name] = False
                continue
            try:
                subprocess.run(
                    ["git", "-C", str(tap_path), "pull", "--ff-only"],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                results[tap_name] = True
            except subprocess.CalledProcessError:
                results[tap_name] = False

        return results

    def list_taps(self) -> Dict[str, dict]:
        """List all registered taps."""
        return self._load_index()

    def get_tap_path(self, name: str) -> Optional[Path]:
        """Get the local path for a tap."""
        index = self._load_index()
        if name not in index:
            return None
        return Path(index[name]["path"])

    def search(self, query: str) -> List[Dict[str, str]]:
        """Search across all taps for skills matching a query.

        Returns:
            List of dicts with 'tap', 'name', 'description' keys.
        """
        query_lower = query.lower()
        results = []

        for tap_name, tap_info in self._load_index().items():
            tap_path = Path(tap_info["path"])
            if not tap_path.exists():
                continue

            skills = discover_skills(tap_path)
            for skill in skills:
                fm = skill.frontmatter
                # Match name, description, or tags
                searchable = f"{fm.name} {fm.description} {fm.metadata.get('tags', '')}".lower()
                if query_lower in searchable:
                    results.append(
                        {
                            "tap": tap_name,
                            "name": fm.name,
                            "description": fm.description,
                            "repo": tap_info.get("repo", ""),
                        }
                    )

        return results

    def resolve_skill(self, spec: str) -> Optional[SkillConfig]:
        """Resolve a skill spec like '@user/repo/skill-name' to a SkillConfig.

        Also supports '@user/repo' (returns all skills) via resolve_skills().

        Returns:
            SkillConfig if found, None otherwise.
        """
        parts = self._parse_spec(spec)
        if not parts:
            return None

        repo, skill_name, version = parts
        tap_key = self._tap_key(repo)
        tap_path = self.taps_dir / tap_key

        if not tap_path.exists():
            # Auto-clone
            if not self.add(repo):
                return None

        skills = discover_skills(tap_path)
        for skill in skills:
            if skill.name == skill_name:
                return skill
        return None

    def resolve_skills(self, spec: str) -> List[SkillConfig]:
        """Resolve a repo spec like '@user/repo' to all its skills."""
        parts = self._parse_spec(spec)
        if not parts:
            return []

        repo, skill_name, version = parts
        tap_key = self._tap_key(repo)
        tap_path = self.taps_dir / tap_key

        if not tap_path.exists():
            if not self.add(repo):
                return []

        skills = discover_skills(tap_path)
        if skill_name:
            return [s for s in skills if s.name == skill_name]
        return skills

    @staticmethod
    def _parse_spec(spec: str) -> Optional[tuple]:
        """Parse '@user/repo[/skill][@version]' into (repo, skill_name, version).

        Returns:
            Tuple of (repo, skill_name_or_None, version_or_None), or None if invalid.
        """
        spec = spec.lstrip("@")
        version = None
        if "@" in spec:
            spec, version = spec.rsplit("@", 1)

        parts = spec.split("/")
        if len(parts) < 2:
            return None

        repo = f"{parts[0]}/{parts[1]}"
        skill_name = parts[2] if len(parts) > 2 else None
        return repo, skill_name, version
