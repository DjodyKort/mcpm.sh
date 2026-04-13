"""Git sync integration -- pull skills repo and sync on new machines."""

import json
import logging
from pathlib import Path
from typing import Optional

from mcpm.skills.config import SkillsConfigManager
from mcpm.skills.parser import discover_skills
from mcpm.skills.transpiler import sync_skills
from mcpm.utils.platform import get_config_directory

logger = logging.getLogger(__name__)

SKILLS_SYNC_CONFIG_PATH = get_config_directory() / "skills_sync.json"


class SkillsSyncConfig:
    """Persistent configuration for skills git sync."""

    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or SKILLS_SYNC_CONFIG_PATH

    def _load(self) -> dict:
        if not self.config_path.exists():
            return {}
        try:
            return json.loads(self.config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, Exception):
            return {}

    def _save(self, data: dict) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def get_repo(self) -> Optional[str]:
        """Get the configured skills repo URL."""
        return self._load().get("repo")

    def get_branch(self) -> str:
        """Get the configured branch (default: main)."""
        return self._load().get("branch", "main")

    def get_local_path(self) -> Optional[Path]:
        """Get the local clone path for the skills repo."""
        path = self._load().get("local_path")
        return Path(path) if path else None

    def get_auto_sync(self) -> bool:
        """Get whether auto-sync is enabled."""
        return self._load().get("auto_sync", False)

    def configure(self, repo: str, branch: str = "main", auto_sync: bool = False) -> Path:
        """Configure the skills sync repo.

        Args:
            repo: Git URL (SSH or HTTPS).
            branch: Branch name.
            auto_sync: Whether to auto-sync on mcpm sync.

        Returns:
            Local path where the repo will be cloned.
        """
        local_path = get_config_directory() / "skills_repo"
        data = {
            "repo": repo,
            "branch": branch,
            "auto_sync": auto_sync,
            "local_path": str(local_path),
        }
        self._save(data)
        return local_path

    def clear(self) -> None:
        """Remove sync configuration."""
        if self.config_path.exists():
            self.config_path.unlink()


def clone_skills_repo(repo_url: str, local_path: Path, branch: str = "main") -> bool:
    """Clone a skills repo to a local path.

    Args:
        repo_url: Git URL (SSH or HTTPS).
        local_path: Where to clone.
        branch: Branch to check out.

    Returns:
        True if successful.
    """
    import subprocess

    if local_path.exists():
        logger.info(f"Skills repo already exists at {local_path}, pulling instead")
        return pull_skills_repo(local_path)

    try:
        subprocess.run(
            ["git", "clone", "--branch", branch, "--depth", "1", repo_url, str(local_path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        logger.error(f"Failed to clone skills repo: {e}")
        return False


def pull_skills_repo(local_path: Path) -> bool:
    """Pull latest changes for a skills repo.

    Uses fast-forward-only to avoid merge conflicts.

    Returns:
        True if successful.
    """
    import subprocess

    try:
        subprocess.run(
            ["git", "-C", str(local_path), "pull", "--ff-only"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        logger.error(f"Failed to pull skills repo: {e}")
        return False


def full_sync(project_root: Optional[Path] = None, client_keys: Optional[list] = None) -> dict:
    """Full sync: pull skills repo, discover skills, transpile to clients.

    This is the top-level function called by `mcpm sync` integration.

    Args:
        project_root: Override project root (defaults to configured local_path).
        client_keys: Specific clients to target.

    Returns:
        Dict with sync results: {'pulled': bool, 'skills_count': int, 'lockfile': LockFile or None}
    """
    config = SkillsSyncConfig()
    repo_url = config.get_repo()

    result = {"pulled": False, "skills_count": 0, "lockfile": None}

    if not repo_url and not project_root:
        return result

    local_path = project_root or config.get_local_path()
    if not local_path:
        return result

    # Clone or pull
    if repo_url:
        if not local_path.exists():
            result["pulled"] = clone_skills_repo(repo_url, local_path, config.get_branch())
        else:
            result["pulled"] = pull_skills_repo(local_path)

    # Discover and sync
    skills = discover_skills(local_path)
    result["skills_count"] = len(skills)

    if skills:
        # git-sync always uses global mode since its purpose is cross-machine
        # sync to user-level locations
        lockfile = sync_skills(skills, local_path, client_keys=client_keys, global_mode=True)
        result["lockfile"] = lockfile

        # Save lockfile
        skills_config = SkillsConfigManager(project_root=local_path)
        skills_config.save_lockfile(lockfile)

    return result
