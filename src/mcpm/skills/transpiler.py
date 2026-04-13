"""Base transpiler class and transpiler registry."""

import abc
import hashlib
import logging
from pathlib import Path
from typing import Dict, List, Optional, Type

from mcpm.skills.schema import LockFile, LockFileEntry, SkillConfig, TranspileResult

logger = logging.getLogger(__name__)

# Managed block delimiters for append-mode targets
MCPM_BLOCK_START = "<!-- mcpm:start -->"
MCPM_BLOCK_END = "<!-- mcpm:end -->"


class BaseSkillTranspiler(abc.ABC):
    """Abstract base class for per-client skill transpilers."""

    client_key: str = ""
    display_name: str = ""

    @abc.abstractmethod
    def transpile(self, skill: SkillConfig, project_root: Path) -> TranspileResult:
        """Transpile a canonical skill to this client's native format.

        Args:
            skill: Parsed canonical SkillConfig.
            project_root: Root directory of the project.

        Returns:
            TranspileResult with output path, content, and any warnings.
        """

    @abc.abstractmethod
    def get_output_path(self, skill: SkillConfig, project_root: Path) -> Path:
        """Get the output path for a skill in this client's format."""

    def clean(self, project_root: Path, managed_skills: Optional[List[str]] = None) -> List[Path]:
        """Remove mcpm-managed skill files for this client.

        Default implementation: remove files at expected output paths.
        Override for append-mode clients (Zed, Aider, etc.).

        Args:
            project_root: Root directory of the project.
            managed_skills: List of skill names to clean. If None, discovers from filesystem.

        Returns:
            List of paths that were removed.
        """
        removed = []
        if managed_skills:
            for name in managed_skills:
                # Create a minimal skill config just to get the path
                from mcpm.skills.schema import SkillConfig, SkillFrontmatter

                dummy = SkillConfig(
                    frontmatter=SkillFrontmatter(name=name, description="dummy"),
                    body="",
                    source_path=Path("dummy"),
                    skill_type="skill",
                )
                path = self.get_output_path(dummy, project_root)
                if path.exists():
                    path.unlink()
                    removed.append(path)
                    # Clean empty parent dirs
                    parent = path.parent
                    if parent.exists() and not any(parent.iterdir()):
                        parent.rmdir()
        return removed

    def _render_frontmatter(self, fields: Dict[str, str]) -> str:
        """Render a YAML frontmatter block from a dict of fields."""
        if not fields:
            return ""
        lines = ["---"]
        for key, value in fields.items():
            if isinstance(value, bool):
                lines.append(f"{key}: {'true' if value else 'false'}")
            else:
                lines.append(f"{key}: {value}")
        lines.append("---")
        return "\n".join(lines)


def inject_managed_block(existing_content: str, block_content: str) -> str:
    """Inject or replace content within <!-- mcpm:start/end --> delimiters.

    If the delimiters exist, replace the content between them.
    If not, append the block at the end.
    """
    start_idx = existing_content.find(MCPM_BLOCK_START)
    end_idx = existing_content.find(MCPM_BLOCK_END)

    managed = f"{MCPM_BLOCK_START}\n{block_content}\n{MCPM_BLOCK_END}"

    if start_idx != -1 and end_idx != -1:
        # Replace existing block
        before = existing_content[:start_idx].rstrip()
        after = existing_content[end_idx + len(MCPM_BLOCK_END) :].lstrip()
        parts = [before, managed]
        if after:
            parts.append(after)
        return "\n\n".join(parts) + "\n"
    else:
        # Append
        if existing_content.strip():
            return existing_content.rstrip() + "\n\n" + managed + "\n"
        return managed + "\n"


def compute_skill_hash(skill: SkillConfig) -> str:
    """Compute a SHA256 hash of a skill's source file content."""
    content = skill.source_path.read_text(encoding="utf-8")
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


# ---- Transpiler Registry ----

_TRANSPILER_REGISTRY: Dict[str, Type[BaseSkillTranspiler]] = {}


def register_transpiler(transpiler_class: Type[BaseSkillTranspiler]) -> Type[BaseSkillTranspiler]:
    """Decorator to register a transpiler class."""
    _TRANSPILER_REGISTRY[transpiler_class.client_key] = transpiler_class
    return transpiler_class


def get_transpiler(client_key: str) -> Optional[BaseSkillTranspiler]:
    """Get a transpiler instance for a client key."""
    cls = _TRANSPILER_REGISTRY.get(client_key)
    return cls() if cls else None


_transpilers_loaded = False


def _ensure_transpilers_loaded():
    """Lazily import all transpiler modules to trigger registration."""
    global _transpilers_loaded
    if not _transpilers_loaded:
        import mcpm.skills.transpilers  # noqa: F401

        _transpilers_loaded = True


def get_all_transpilers() -> Dict[str, BaseSkillTranspiler]:
    """Get instances of all registered transpilers."""
    _ensure_transpilers_loaded()
    return {key: cls() for key, cls in _TRANSPILER_REGISTRY.items()}


# Keys of transpilers that use append mode (single file for all skills)
APPEND_MODE_TRANSPILERS = {"zed", "agents-md"}

# Transpilers that only make sense at project level (file paths relative to project root)
PROJECT_ONLY_TRANSPILERS = {"vscode-copilot", "zed", "agents-md"}


def sync_skills(
    skills: List[SkillConfig],
    project_root: Path,
    client_keys: Optional[List[str]] = None,
    dry_run: bool = False,
    global_mode: bool = False,
) -> LockFile:
    """Transpile all skills to target clients and write output files.

    Args:
        skills: List of parsed SkillConfigs.
        project_root: Root directory of the project (used for discovery).
        client_keys: Specific clients to target. None = all registered.
        dry_run: If True, compute results without writing files.
        global_mode: If True, write to user-level paths (~/) instead of project-level.

    Returns:
        LockFile recording the sync state.
    """
    lockfile = LockFile.create_now()
    transpilers = get_all_transpilers()

    # In global mode, write to home directory and skip project-only transpilers
    output_root = Path.home() if global_mode else project_root

    if client_keys:
        transpilers = {k: v for k, v in transpilers.items() if k in client_keys}

    if global_mode:
        skipped = {k for k in transpilers if k in PROJECT_ONLY_TRANSPILERS}
        if skipped:
            logger.info(f"Global mode: skipping project-only transpilers: {', '.join(skipped)}")
        transpilers = {k: v for k, v in transpilers.items() if k not in PROJECT_ONLY_TRANSPILERS}

    # Separate append-mode transpilers (need all skills at once) from per-file transpilers
    per_file_transpilers = {k: v for k, v in transpilers.items() if k not in APPEND_MODE_TRANSPILERS}
    append_transpilers = {k: v for k, v in transpilers.items() if k in APPEND_MODE_TRANSPILERS}

    # Per-file transpilers: one output file per skill per client
    for skill in skills:
        entry = LockFileEntry(
            source="local",
            version=skill.frontmatter.metadata.get("version"),
            hash=compute_skill_hash(skill),
        )

        for client_key, transpiler in per_file_transpilers.items():
            try:
                result = transpiler.transpile(skill, output_root)
                entry.clients_synced.append(client_key)
                entry.warnings.extend(result.warnings)

                if not dry_run:
                    result.output_path.parent.mkdir(parents=True, exist_ok=True)
                    result.output_path.write_text(result.content, encoding="utf-8")
            except Exception as e:
                logger.warning(f"Failed to transpile {skill.name} for {client_key}: {e}")
                entry.warnings.append(f"{client_key}: transpilation failed: {e}")

        if skill.skill_type == "rule":
            lockfile.rules[skill.name] = entry
        else:
            lockfile.skills[skill.name] = entry

    # Append-mode transpilers: one output file for ALL skills combined
    for client_key, transpiler in append_transpilers.items():
        try:
            if hasattr(transpiler, "transpile_all"):
                result = transpiler.transpile_all(skills, output_root)
            else:
                continue

            # Record in lockfile for each skill
            for skill in skills:
                entry_key = skill.name
                target = lockfile.rules if skill.skill_type == "rule" else lockfile.skills
                if entry_key not in target:
                    # Create entry if it wasn't created by per-file transpilers
                    target[entry_key] = LockFileEntry(
                        source="local",
                        version=skill.frontmatter.metadata.get("version"),
                        hash=compute_skill_hash(skill),
                    )
                target[entry_key].clients_synced.append(client_key)
                target[entry_key].warnings.extend(result.warnings)

            if not dry_run and result.content:
                result.output_path.parent.mkdir(parents=True, exist_ok=True)
                result.output_path.write_text(result.content, encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to transpile_all for {client_key}: {e}")

    return lockfile
