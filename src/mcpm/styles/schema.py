"""Pydantic models for the output styles sync system."""

import re
from pathlib import Path
from typing import Any, Dict

from pydantic import BaseModel, field_validator


class StyleFrontmatter(BaseModel):
    """Universal style frontmatter schema."""

    # Required
    name: str
    description: str

    # Style-specific
    keep_coding_instructions: bool = True

    # Metadata
    metadata: Dict[str, Any] = {}

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


class StyleConfig(BaseModel):
    """A fully parsed style: frontmatter + body (style instructions) + source path."""

    frontmatter: StyleFrontmatter
    body: str
    source_path: Path

    model_config = {"arbitrary_types_allowed": True}

    @property
    def name(self) -> str:
        return self.frontmatter.name
