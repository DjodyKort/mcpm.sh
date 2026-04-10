"""Skills config manager -- lockfile I/O, skill discovery, hash computation."""

import hashlib
import json
import logging
from pathlib import Path
from typing import Optional

from ruamel.yaml import YAML

from mcpm.skills.schema import LockFile, SkillsRepoManifest

logger = logging.getLogger(__name__)

yaml = YAML()
yaml.preserve_quotes = True

LOCKFILE_NAME = "mcpm-skills.lock"
MANIFEST_NAME = "mcpm-skills.yaml"


class SkillsConfigManager:
    """Manages skills repository state: lockfile, manifest, and discovery."""

    def __init__(self, project_root: Optional[Path] = None):
        self.project_root = project_root or Path.cwd()

    @property
    def lockfile_path(self) -> Path:
        return self.project_root / LOCKFILE_NAME

    @property
    def manifest_path(self) -> Path:
        return self.project_root / MANIFEST_NAME

    # ---- Lockfile ----

    def load_lockfile(self) -> Optional[LockFile]:
        """Load the lockfile from disk. Returns None if not found."""
        if not self.lockfile_path.exists():
            return None
        try:
            data = json.loads(self.lockfile_path.read_text(encoding="utf-8"))
            return LockFile(**data)
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"Failed to load lockfile: {e}")
            return None

    def save_lockfile(self, lockfile: LockFile) -> None:
        """Write the lockfile to disk."""
        self.lockfile_path.write_text(
            json.dumps(lockfile.model_dump(), indent=2),
            encoding="utf-8",
        )

    # ---- Manifest ----

    def load_manifest(self) -> Optional[SkillsRepoManifest]:
        """Load the repo manifest (mcpm-skills.yaml)."""
        if not self.manifest_path.exists():
            return None
        try:
            from io import StringIO

            data = yaml.load(StringIO(self.manifest_path.read_text(encoding="utf-8")))
            if data is None:
                return None
            return SkillsRepoManifest(**{str(k): v for k, v in data.items()})
        except Exception as e:
            logger.warning(f"Failed to load manifest: {e}")
            return None

    def save_manifest(self, manifest: SkillsRepoManifest) -> None:
        """Write the repo manifest to disk."""
        from io import StringIO

        data = manifest.model_dump(exclude_none=True)
        stream = StringIO()
        yaml.dump(data, stream)
        self.manifest_path.write_text(stream.getvalue(), encoding="utf-8")

    # ---- Scaffolding ----

    def init_repo(self, name: str = "my-skills") -> Path:
        """Scaffold a new skills repository.

        Creates:
            mcpm-skills.yaml
            skills/
            rules/
            profiles/

        Returns:
            Path to the created repo root.
        """
        self.project_root.mkdir(parents=True, exist_ok=True)

        # Create directories
        (self.project_root / "skills").mkdir(exist_ok=True)
        (self.project_root / "rules").mkdir(exist_ok=True)
        (self.project_root / "agents").mkdir(exist_ok=True)
        (self.project_root / "profiles").mkdir(exist_ok=True)

        # Create manifest
        manifest = SkillsRepoManifest(name=name)
        self.save_manifest(manifest)

        return self.project_root

    def scaffold_skill(self, name: str, skill_type: str = "skill") -> Path:
        """Create a new skill directory with a template SKILL.md.

        Args:
            name: Skill name (kebab-case).
            skill_type: "skill" or "rule".

        Returns:
            Path to the created SKILL.md.
        """
        base_dir = "rules" if skill_type == "rule" else "skills"
        skill_dir = self.project_root / base_dir / name
        skill_dir.mkdir(parents=True, exist_ok=True)

        skill_file = skill_dir / "SKILL.md"

        activation = "always" if skill_type == "rule" else "auto"
        template = f"""---
name: {name}
description: "TODO: Describe what this {skill_type} does and when to use it."
activation: {activation}
---

TODO: Add {skill_type} instructions here.
"""
        skill_file.write_text(template, encoding="utf-8")
        return skill_file

    # ---- Drift Detection ----

    def compute_output_hash(self, path: Path) -> Optional[str]:
        """Compute SHA256 hash of an output file for drift detection."""
        if not path.exists():
            return None
        content = path.read_text(encoding="utf-8")
        return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

    def has_skills_repo(self) -> bool:
        """Check if the current directory looks like a skills repo."""
        return self.manifest_path.exists() or (self.project_root / "skills").is_dir()
