"""Base style transpiler class, registry, and orchestration functions."""

import abc
import hashlib
import logging
from pathlib import Path
from typing import Dict, List, Optional, Type

from mcpm.skills.schema import LockFile, LockFileEntry, TranspileResult
from mcpm.styles.schema import StyleConfig

logger = logging.getLogger(__name__)

# Keys of transpilers that use append mode (single file for all styles)
STYLE_APPEND_MODE_TRANSPILERS = {"roomodes-style"}


class BaseStyleTranspiler(abc.ABC):
    """Abstract base class for per-client style transpilers."""

    client_key: str = ""
    display_name: str = ""
    tier: int = 2  # 1 = native toggle, 2 = apply/remove

    @abc.abstractmethod
    def transpile(self, style: StyleConfig, project_root: Path) -> TranspileResult:
        """Transpile a canonical style to this client's native format."""

    @abc.abstractmethod
    def get_output_path(self, style: StyleConfig, project_root: Path) -> Path:
        """Get the output path for a style in this client's format."""

    def transpile_all(self, styles: List[StyleConfig], project_root: Path) -> TranspileResult:
        """For append-mode transpilers: transpile all styles into a single output."""
        raise NotImplementedError(f"{self.client_key} does not support transpile_all")

    def clean(self, project_root: Path, managed_styles: Optional[List[str]] = None) -> List[Path]:
        """Remove mcpm-managed style files for this client."""
        removed = []
        if managed_styles:
            for name in managed_styles:
                dummy = StyleConfig(
                    frontmatter={"name": name, "description": "dummy"},
                    body="",
                    source_path=Path("dummy"),
                )
                path = self.get_output_path(dummy, project_root)
                if path.exists():
                    path.unlink()
                    removed.append(path)
                    parent = path.parent
                    if parent.exists() and not any(parent.iterdir()):
                        parent.rmdir()
        return removed

    def _render_frontmatter(self, fields: Dict[str, object]) -> str:
        """Render a YAML frontmatter block from a dict of fields."""
        if not fields:
            return ""
        lines = ["---"]
        for key, value in fields.items():
            if isinstance(value, bool):
                lines.append(f"{key}: {'true' if value else 'false'}")
            elif isinstance(value, list):
                if value:
                    items = ", ".join(str(v) for v in value)
                    lines.append(f"{key}: [{items}]")
            else:
                lines.append(f"{key}: {value}")
        lines.append("---")
        return "\n".join(lines)


def compute_style_hash(style: StyleConfig) -> str:
    """Compute a SHA256 hash of a style's source file content."""
    content = style.source_path.read_text(encoding="utf-8")
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


# ---- Style Transpiler Registry ----

_STYLE_TRANSPILER_REGISTRY: Dict[str, Type[BaseStyleTranspiler]] = {}
_transpilers_loaded = False


def register_style_transpiler(cls: Type[BaseStyleTranspiler]) -> Type[BaseStyleTranspiler]:
    """Decorator to register a style transpiler class."""
    _STYLE_TRANSPILER_REGISTRY[cls.client_key] = cls
    return cls


def get_style_transpiler(client_key: str) -> Optional[BaseStyleTranspiler]:
    _ensure_transpilers_loaded()
    cls = _STYLE_TRANSPILER_REGISTRY.get(client_key)
    return cls() if cls else None


def _ensure_transpilers_loaded():
    """Lazily import all transpiler modules to trigger registration."""
    global _transpilers_loaded
    if not _transpilers_loaded:
        import mcpm.styles.transpilers  # noqa: F401

        _transpilers_loaded = True


def get_all_style_transpilers() -> Dict[str, BaseStyleTranspiler]:
    _ensure_transpilers_loaded()
    return {key: cls() for key, cls in _STYLE_TRANSPILER_REGISTRY.items()}


def get_tier1_transpilers() -> Dict[str, BaseStyleTranspiler]:
    """Get only Tier 1 (native toggle) transpilers."""
    return {k: v for k, v in get_all_style_transpilers().items() if v.tier == 1}


def get_tier2_transpilers() -> Dict[str, BaseStyleTranspiler]:
    """Get only Tier 2 (apply/remove) transpilers."""
    return {k: v for k, v in get_all_style_transpilers().items() if v.tier == 2}


# ---- Orchestration Functions ----


def sync_styles(
    styles: List[StyleConfig],
    project_root: Path,
    client_keys: Optional[List[str]] = None,
    dry_run: bool = False,
    lockfile: Optional[LockFile] = None,
) -> LockFile:
    """Transpile all styles to Tier 1 clients and write output files.

    Tier 1 clients support native style toggling -- all styles are written
    and the user picks one in the client UI.
    """
    if lockfile is None:
        lockfile = LockFile.create_now()

    transpilers = get_tier1_transpilers()
    if client_keys:
        transpilers = {k: v for k, v in transpilers.items() if k in client_keys}

    per_file = {k: v for k, v in transpilers.items() if k not in STYLE_APPEND_MODE_TRANSPILERS}
    append = {k: v for k, v in transpilers.items() if k in STYLE_APPEND_MODE_TRANSPILERS}

    for style in styles:
        entry = LockFileEntry(
            source="local",
            version=style.frontmatter.metadata.get("version"),
            hash=compute_style_hash(style),
        )

        for client_key, transpiler in per_file.items():
            try:
                result = transpiler.transpile(style, project_root)
                entry.clients_synced.append(client_key)
                entry.warnings.extend(result.warnings)
                if not dry_run:
                    result.output_path.parent.mkdir(parents=True, exist_ok=True)
                    result.output_path.write_text(result.content, encoding="utf-8")
            except Exception as e:
                logger.warning(f"Failed to transpile style {style.name} for {client_key}: {e}")
                entry.warnings.append(f"{client_key}: transpilation failed: {e}")

        lockfile.styles[style.name] = entry

    # Append-mode transpilers
    for client_key, transpiler in append.items():
        try:
            if hasattr(transpiler, "transpile_all"):
                result = transpiler.transpile_all(styles, project_root)
                for style in styles:
                    if style.name in lockfile.styles:
                        lockfile.styles[style.name].clients_synced.append(client_key)
                        lockfile.styles[style.name].warnings.extend(result.warnings)
                if not dry_run:
                    result.output_path.parent.mkdir(parents=True, exist_ok=True)
                    result.output_path.write_text(result.content, encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to transpile_all styles for {client_key}: {e}")

    return lockfile


def apply_style(
    style: StyleConfig,
    project_root: Path,
    client_keys: Optional[List[str]] = None,
    dry_run: bool = False,
    lockfile: Optional[LockFile] = None,
) -> LockFile:
    """Apply a single style to Tier 2 clients.

    Tier 2 clients don't have native style toggling -- the style is injected
    as an always-on rule. Only one style can be active per client.
    """
    if lockfile is None:
        lockfile = LockFile.create_now()

    transpilers = get_tier2_transpilers()
    if client_keys:
        transpilers = {k: v for k, v in transpilers.items() if k in client_keys}

    entry = lockfile.styles.get(style.name)
    if entry is None:
        entry = LockFileEntry(
            source="local",
            version=style.frontmatter.metadata.get("version"),
            hash=compute_style_hash(style),
        )

    for client_key, transpiler in transpilers.items():
        try:
            result = transpiler.transpile(style, project_root)
            if client_key not in entry.clients_synced:
                entry.clients_synced.append(client_key)
            entry.warnings.extend(result.warnings)
            if not dry_run:
                result.output_path.parent.mkdir(parents=True, exist_ok=True)
                result.output_path.write_text(result.content, encoding="utf-8")
            lockfile.active_styles[client_key] = style.name
        except Exception as e:
            logger.warning(f"Failed to apply style {style.name} to {client_key}: {e}")
            entry.warnings.append(f"{client_key}: apply failed: {e}")

    lockfile.styles[style.name] = entry
    return lockfile


def remove_style(
    project_root: Path,
    client_keys: Optional[List[str]] = None,
    dry_run: bool = False,
    lockfile: Optional[LockFile] = None,
) -> LockFile:
    """Remove the active style from Tier 2 clients.

    Deletes the mcpm-output-style files and clears active_styles tracking.
    """
    if lockfile is None:
        lockfile = LockFile.create_now()

    transpilers = get_tier2_transpilers()
    if client_keys:
        transpilers = {k: v for k, v in transpilers.items() if k in client_keys}

    removed_from = []
    for client_key, transpiler in transpilers.items():
        if client_key not in lockfile.active_styles:
            continue
        try:
            active_name = lockfile.active_styles[client_key]
            if not dry_run:
                # Use the transpiler's clean method for append-mode clients (e.g. Zed)
                # which need managed-block removal rather than file deletion
                if hasattr(transpiler, "clean") and client_key == "zed":
                    transpiler.clean(project_root)
                else:
                    dummy = StyleConfig(
                        frontmatter={"name": "mcpm-output-style", "description": "dummy"},
                        body="",
                        source_path=Path("dummy"),
                    )
                    path = transpiler.get_output_path(dummy, project_root)
                    if path.exists():
                        path.unlink()
                        parent = path.parent
                        if parent.exists() and not any(parent.iterdir()):
                            parent.rmdir()
            del lockfile.active_styles[client_key]
            removed_from.append((client_key, active_name))
        except Exception as e:
            logger.warning(f"Failed to remove style from {client_key}: {e}")

    return lockfile
