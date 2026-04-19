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


class LockFile(BaseModel):
    """Lockfile pinning the exact state after a sync."""

    version: int = 1
    synced_at: str = ""
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
