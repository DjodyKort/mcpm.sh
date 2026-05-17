"""Base transpiler class and transpiler registry."""

import abc
import hashlib
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Type

from mcpm.skills.schema import LockFile, LockFileEntry, SkillConfig, TranspileResult

logger = logging.getLogger(__name__)

# Managed block delimiters for append-mode targets
MCPM_BLOCK_START = "<!-- mcpm:start -->"
MCPM_BLOCK_END = "<!-- mcpm:end -->"

# Subdirectories within a skill source that are transpiled alongside SKILL.md.
# Lets skills use progressive disclosure: SKILL.md stays slim while module/
# reference content lives in adjacent files that the LLM reads on demand.
SKILL_ASSET_DIRS = ("modules", "reference", "templates", "examples", "assets", "scripts")
SKILL_ASSET_EXTENSIONS = (
    ".md", ".txt", ".json", ".yaml", ".yml",
    ".png", ".svg", ".jpg", ".jpeg", ".webp",
    ".sh", ".bash", ".py",
)


def _copy_skill_assets(
    src_dir: Path,
    dst_dir: Path,
    output_root: Path,
) -> List[str]:
    """Copy skill asset subdirectories alongside the transpiled SKILL.md.

    Walks the source skill directory for any of SKILL_ASSET_DIRS, copies their
    contents recursively into the per-client output directory, filtering by
    SKILL_ASSET_EXTENSIONS so binary build artifacts and IDE files do not leak
    into client paths.

    Args:
        src_dir: Source skill directory (containing the canonical SKILL.md).
        dst_dir: Destination directory (containing the per-client SKILL.md).
        output_root: Sync output root used to compute relative paths for the
            lockfile entry.

    Returns:
        List of relative paths (relative to output_root) of files written.
        Empty if no asset subdirs exist.
    """
    written: List[str] = []
    for subdir_name in SKILL_ASSET_DIRS:
        src_subdir = src_dir / subdir_name
        if not src_subdir.is_dir():
            continue
        for src_file in src_subdir.rglob("*"):
            if not src_file.is_file():
                continue
            if src_file.suffix.lower() not in SKILL_ASSET_EXTENSIONS:
                continue
            rel = src_file.relative_to(src_dir)
            dst_file = dst_dir / rel
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dst_file)
            try:
                written.append(str(dst_file.relative_to(output_root)))
            except ValueError:
                written.append(str(dst_file))
    return written


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

    def get_collision_paths(self, skill: SkillConfig, project_root: Path) -> List[Path]:
        """Other paths this client may load the same skill name from.

        Override per client to declare known surface paths that are *not* the
        primary output but where the same skill name would also resolve (e.g.
        legacy slash-command files, older flat-layout rule files). Returned
        paths are checked for existence during sync; collisions are reported
        and optionally migrated.
        """
        return []

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
    """Compute a SHA256 hash covering SKILL.md and all asset files.

    Hashes SKILL.md content plus the content of every file in the
    SKILL_ASSET_DIRS subdirectories (filtered by SKILL_ASSET_EXTENSIONS).
    Asset files are sorted by relative path so the hash is deterministic.

    Including assets lets `status` and `diff` detect drift when the user
    edits a module or reference file without touching SKILL.md. Without
    this, asset edits would silently fail to trigger a re-sync.
    """
    h = hashlib.sha256()
    src_dir = skill.source_path.parent

    # SKILL.md first, marked for clarity in the digest stream.
    h.update(b"SKILL.md\n")
    h.update(skill.source_path.read_bytes())
    h.update(b"\n---\n")

    # Asset files, in deterministic relative-path order.
    asset_files = []
    for subdir_name in SKILL_ASSET_DIRS:
        subdir = src_dir / subdir_name
        if not subdir.is_dir():
            continue
        for path in subdir.rglob("*"):
            if path.is_file() and path.suffix.lower() in SKILL_ASSET_EXTENSIONS:
                asset_files.append(path)
    asset_files.sort(key=lambda p: str(p.relative_to(src_dir)))
    for path in asset_files:
        rel = path.relative_to(src_dir)
        h.update(f"{rel}\n".encode("utf-8"))
        h.update(path.read_bytes())
        h.update(b"\n---\n")

    return "sha256:" + h.hexdigest()[:16]


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


@dataclass
class SyncResult:
    """Outcome of a ``sync_skills()`` run.

    The lockfile is the persistent record; the other fields are summaries that
    callers (CLI commands, the pull pipeline) use to report what changed.
    """

    lockfile: LockFile
    cleaned: List[Path] = field(default_factory=list)
    collision_summary: Optional["CollisionSummary"] = None  # noqa: F821 - forward ref
    output_root: Path = Path()


def _load_previous_lockfile(output_root: Path, project_root: Path, global_mode: bool) -> Optional[LockFile]:
    """Load the lockfile that the *previous* sync wrote, if any."""
    from mcpm.skills.config import SkillsConfigManager

    if global_mode:
        from mcpm.utils.platform import get_config_directory

        manager = SkillsConfigManager(project_root=get_config_directory())
    else:
        manager = SkillsConfigManager(project_root=project_root)
    return manager.load_lockfile()


def _collect_stale_files(
    previous: LockFile,
    new_lockfile: LockFile,
    output_root: Path,
) -> List[Path]:
    """Return absolute paths to files written by a prior sync that are no longer current.

    A file is stale if it was recorded in the previous lockfile under a skill
    name that does not appear in the new lockfile (rename or delete upstream).
    Append-mode transpilers manage their own files and are not tracked here.
    """
    stale: List[Path] = []
    for bucket in ("skills", "rules"):
        prev_entries: Dict[str, LockFileEntry] = getattr(previous, bucket)
        new_entries: Dict[str, LockFileEntry] = getattr(new_lockfile, bucket)
        for name, entry in prev_entries.items():
            if name in new_entries:
                continue
            for _client, rel_paths in (entry.output_files or {}).items():
                for rel in rel_paths:
                    stale.append(output_root / rel)
    return stale


def _delete_stale(stale: List[Path]) -> List[Path]:
    """Delete stale files and prune now-empty parent directories."""
    deleted: List[Path] = []
    for path in stale:
        if not path.exists():
            continue
        try:
            path.unlink()
            deleted.append(path)
        except OSError as e:
            logger.warning(f"Failed to remove stale file {path}: {e}")
            continue
        parent = path.parent
        # Prune up to two empty parent dirs (e.g. .claude/skills/foo/)
        for _ in range(2):
            if parent.exists() and parent.is_dir() and not any(parent.iterdir()):
                try:
                    parent.rmdir()
                    parent = parent.parent
                except OSError:
                    break
            else:
                break
    return deleted


def sync_skills(
    skills: List[SkillConfig],
    project_root: Path,
    client_keys: Optional[List[str]] = None,
    dry_run: bool = False,
    global_mode: bool = False,
    migrate: Optional[bool] = None,
    console: Optional["Console"] = None,  # noqa: F821 - forward ref
) -> SyncResult:
    """Transpile all skills to target clients and write output files.

    Args:
        skills: List of parsed SkillConfigs.
        project_root: Root directory of the project (used for discovery).
        client_keys: Specific clients to target. None = all registered.
        dry_run: If True, compute results without writing files.
        global_mode: If True, write to user-level paths (~/) instead of project-level.
        migrate: True for ``--migrate`` (auto-replace colliding files), False for
            ``--no-migrate`` (warn-only), None to auto-detect from TTY.
        console: Optional Rich Console for collision prompts. Defaults to a new one.

    Returns:
        SyncResult with the new lockfile, removed stale files, and collision summary.
    """
    from mcpm.skills.collisions import detect_collisions, resolve_collisions, resolve_mode

    lockfile = LockFile.create_now()
    transpilers = get_all_transpilers()

    # In global mode, write to home directory and skip project-only transpilers
    output_root = Path.home() if global_mode else project_root
    lockfile.scope = "global" if global_mode else "project"
    lockfile.output_root = str(output_root)

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

                # Record the path so a later sync can clean it up if the skill
                # is renamed or removed upstream. Stored relative to output_root
                # so the lockfile is portable across machines.
                try:
                    rel = result.output_path.relative_to(output_root)
                    entry.output_files.setdefault(client_key, []).append(str(rel))
                except ValueError:
                    entry.output_files.setdefault(client_key, []).append(str(result.output_path))

                # Progressive-disclosure asset subdirectories (modules/,
                # reference/, templates/, examples/, assets/) are copied
                # alongside the transpiled SKILL.md. Only meaningful for
                # skill-style outputs where the per-client output lives in a
                # per-skill directory; rules and flat-layout outputs do not
                # have a sibling directory to populate.
                if (
                    not dry_run
                    and skill.skill_type == "skill"
                    and result.output_path.name == "SKILL.md"
                ):
                    asset_files = _copy_skill_assets(
                        src_dir=skill.source_path.parent,
                        dst_dir=result.output_path.parent,
                        output_root=output_root,
                    )
                    if asset_files:
                        entry.output_files.setdefault(client_key, []).extend(asset_files)
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

    # Stale-file cleanup: anything the previous lockfile recorded but that the
    # new sync did not produce has been renamed or removed upstream.
    cleaned: List[Path] = []
    previous = _load_previous_lockfile(output_root, project_root, global_mode)
    if previous is not None:
        stale = _collect_stale_files(previous, lockfile, output_root)
        if stale and not dry_run:
            cleaned = _delete_stale(stale)
        elif stale and dry_run:
            cleaned = stale  # Report what *would* be removed.

    # Collision detection: surface pre-existing files at known shadow paths.
    collisions = detect_collisions(skills, per_file_transpilers, output_root)
    mode = resolve_mode(migrate)
    summary = resolve_collisions(collisions, output_root, mode, console=console, dry_run=dry_run)

    # Record any collision warnings on the relevant lockfile entries.
    for resolution in summary.kept:
        c = resolution.collision
        target = lockfile.rules if c.skill_name in lockfile.rules else lockfile.skills
        entry = target.get(c.skill_name)
        if entry is not None:
            entry.warnings.append(
                f"{c.client_key}: shadowed by existing file at {c.collision_path}"
            )

    return SyncResult(
        lockfile=lockfile,
        cleaned=cleaned,
        collision_summary=summary,
        output_root=output_root,
    )
