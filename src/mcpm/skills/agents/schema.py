"""Pydantic models for the agent management system."""

import re
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, field_validator


class AgentFrontmatter(BaseModel):
    """Universal agent frontmatter -- superset of all client agent schemas."""

    # Required
    name: str
    description: str

    # Model and capabilities
    model: Optional[str] = None
    tools: List[str] = []
    disallowed_tools: List[str] = []
    max_turns: Optional[int] = None

    # Dependencies
    mcp_servers: List[str] = []
    skills: List[str] = []

    # Behavioral
    permission_mode: Optional[Literal["default", "plan", "full-auto"]] = None
    readonly: bool = False
    effort: Optional[str] = None

    # Display
    color: Optional[str] = None

    # Metadata
    metadata: Dict[str, Any] = {}
    license: Optional[str] = None

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


class AgentConfig(BaseModel):
    """A fully parsed agent: frontmatter + body (system prompt) + source path."""

    frontmatter: AgentFrontmatter
    body: str
    source_path: Path

    model_config = {"arbitrary_types_allowed": True}

    @property
    def name(self) -> str:
        return self.frontmatter.name
