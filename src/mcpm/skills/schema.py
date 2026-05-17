"""Pydantic models for the skills sync system."""

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, field_validator


class SkillDependencies(BaseModel):
    """MCP server and skill dependencies for a skill."""

    servers: List[str] = []
    skills: List[str] = []


class SkillHook(BaseModel):
    """A single lifecycle hook declared by a skill.

    Skills use this to ask their host client to fire a bundled script at a
    specific lifecycle event (e.g. Claude Code's PreCompact, SessionStart).
    Per-client transpilers translate this declaration into the client's
    native config format during ``mcpm skills sync``. Clients that do not
    support lifecycle hooks ignore the field with a one-line warning.
    """

    # Path to the executable, relative to the skill's source directory.
    # Resolved to an absolute path inside the synced skill output at install
    # time by the per-client transpiler.
    command: str

    # Optional matcher (semantics depend on the client). For Claude Code:
    # passed through as the hook entry's ``matcher`` field.
    matcher: str = "*"

    # Hook type. For Claude Code today: "command" (the only supported type).
    # Future-proof for clients that distinguish e.g. "script" vs "webhook".
    type: str = "command"

    @field_validator("command")
    @classmethod
    def validate_command(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("hook command must be a non-empty path")
        # Reject absolute paths -- the path must be relative to the skill
        # source directory so the transpiler can re-root it at the synced
        # output location.
        if v.startswith("/") or v.startswith("~"):
            raise ValueError(
                "hook command must be a path relative to the skill source dir, "
                f"got absolute path: {v}"
            )
        return v


class SkillFrontmatter(BaseModel):
    """Universal frontmatter schema -- superset of Agent Skills spec + mcpm extensions."""

    # Agent Skills spec fields (required)
    name: str
    description: str

    # Agent Skills spec fields (optional)
    license: Optional[str] = None
    compatibility: Optional[str] = None
    allowed_tools: Optional[str] = None
    metadata: Dict[str, Any] = {}

    # Lifecycle hooks. Keyed by client-side event name (e.g. "PreCompact",
    # "SessionStart"). Clients that don't support lifecycle hooks ignore
    # the field with a single warning per sync. See SkillHook docstring.
    hooks: Optional[Dict[str, SkillHook]] = None

    # mcpm extension fields
    globs: Optional[str] = None
    activation: Literal["always", "auto", "agent", "manual"] = "auto"
    priority: int = 0
    dependencies: Optional[SkillDependencies] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v or len(v) > 64:
            raise ValueError("name must be 1-64 characters")
        if not re.match(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$", v):
            raise ValueError("name must be lowercase alphanumeric + hyphens, cannot start/end with hyphen")
        if "--" in v:
            raise ValueError("name must not contain consecutive hyphens")
        return v

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str) -> str:
        if not v or len(v) > 1024:
            raise ValueError("description must be 1-1024 characters")
        return v

    @field_validator("compatibility")
    @classmethod
    def validate_compatibility(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and len(v) > 500:
            raise ValueError("compatibility must be at most 500 characters")
        return v


class SkillConfig(BaseModel):
    """A fully parsed skill: frontmatter + body + source metadata."""

    frontmatter: SkillFrontmatter
    body: str
    source_path: Path
    skill_type: Literal["skill", "rule"]

    model_config = {"arbitrary_types_allowed": True}

    @property
    def name(self) -> str:
        return self.frontmatter.name

    @property
    def activation(self) -> str:
        return self.frontmatter.activation


class TranspileResult(BaseModel):
    """Result of transpiling a skill to a specific client format."""

    output_path: Path
    content: str
    warnings: List[str] = []

    model_config = {"arbitrary_types_allowed": True}


class LockFileEntry(BaseModel):
    """A single skill/rule entry in the lockfile."""

    source: str = "local"
    version: Optional[str] = None
    hash: str
    clients_synced: List[str] = []
    warnings: List[str] = []
    # Per-client list of output paths written, relative to the sync output_root
    # (project root in project mode, ~ in global mode). Used to detect and clean
    # up stale files when skills are renamed/removed between syncs.
    output_files: Dict[str, List[str]] = {}
    # Per-client list of hook identifiers (absolute command paths) installed
    # into the client's config (e.g. ~/.claude/settings.json). Tracked so a
    # later sync can remove stale entries when a skill is renamed or removed.
    hooks_installed: Dict[str, List[str]] = {}


class LockFile(BaseModel):
    """Lockfile pinning the exact state after a sync."""

    version: int = 1
    synced_at: str = ""
    # Scope of the last sync: "global" (user-level, ~/) or "project" (cwd/project).
    # Empty string preserved for backward compatibility with pre-scope lockfiles.
    scope: str = ""
    # Absolute path of the output root the lockfile describes. Lets users and
    # tooling detect a scope/path drift without having to guess from context.
    output_root: str = ""
    skills: Dict[str, LockFileEntry] = {}
    rules: Dict[str, LockFileEntry] = {}
    agents: Dict[str, LockFileEntry] = {}
    styles: Dict[str, LockFileEntry] = {}
    active_styles: Dict[str, str] = {}  # client_key -> style_name for Tier 2 tracking

    @classmethod
    def create_now(cls) -> "LockFile":
        return cls(synced_at=datetime.now(timezone.utc).isoformat())


class SkillsRepoManifest(BaseModel):
    """Repository manifest (mcpm-skills.yaml)."""

    name: str
    description: str = ""
    author: str = ""
    version: str = "1.0.0"
    license: str = ""
    default_profile: Optional[str] = None
