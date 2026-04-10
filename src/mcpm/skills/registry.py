"""Registry schema for skills -- defines the format for a future central skills registry.

This module defines the JSON schema that skills would follow in a central registry
(similar to how mcp-registry/servers/*.json works for MCP servers). This is the
schema definition for Phase 3 -- actual registry integration is deferred until
the registry infrastructure is ready.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class SkillRegistryEntry(BaseModel):
    """A skill entry in the central registry.

    Mirrors the server registry format (mcp-registry/servers/*.json) but
    adapted for skills.
    """

    # Identity
    name: str
    display_name: str
    description: str

    # Source
    repository: str  # GitHub URL
    author: str
    license: str = ""

    # Versioning
    version: str = "1.0.0"
    min_mcpm_version: Optional[str] = None

    # Classification
    categories: List[str] = []
    tags: List[str] = []

    # Skill metadata (from SKILL.md frontmatter)
    activation: str = "auto"
    globs: Optional[str] = None
    allowed_tools: Optional[str] = None

    # Dependencies
    server_dependencies: List[str] = []  # Registry names of required MCP servers
    skill_dependencies: List[str] = []  # Registry names of required skills

    # Quality signals (populated by registry)
    downloads: int = 0
    stars: int = 0

    # Client compatibility
    client_compatibility: Dict[str, str] = {}  # {"claude-code": "full", "zed": "always-only"}

    # Install info
    install_spec: str = ""  # e.g. "@anthropics/skills/code-review@1.2.0"


class SkillRegistryIndex(BaseModel):
    """Index of all skills in the registry."""

    version: int = 1
    skills: List[SkillRegistryEntry] = []

    def search(self, query: str) -> List[SkillRegistryEntry]:
        """Search skills by name, description, tags, or categories."""
        query_lower = query.lower()
        results = []
        for skill in self.skills:
            searchable = f"{skill.name} {skill.display_name} {skill.description} {' '.join(skill.tags)} {' '.join(skill.categories)}".lower()
            if query_lower in searchable:
                results.append(skill)
        return results


# JSON Schema definition (for validation of registry entries)
SKILL_REGISTRY_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["name", "display_name", "description", "repository", "author"],
    "properties": {
        "name": {
            "type": "string",
            "pattern": "^[a-z0-9]([a-z0-9-]*[a-z0-9])?$",
            "maxLength": 64,
            "description": "Skill identifier (kebab-case)",
        },
        "display_name": {"type": "string", "description": "Human-readable name"},
        "description": {"type": "string", "maxLength": 1024, "description": "What the skill does"},
        "repository": {"type": "string", "format": "uri", "description": "GitHub repository URL"},
        "author": {"type": "string"},
        "license": {"type": "string"},
        "version": {"type": "string", "pattern": "^\\d+\\.\\d+\\.\\d+"},
        "categories": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": [
                    "code-quality",
                    "testing",
                    "devops",
                    "frontend",
                    "backend",
                    "database",
                    "security",
                    "documentation",
                    "workflow",
                    "language-specific",
                    "framework-specific",
                    "general",
                ],
            },
        },
        "tags": {"type": "array", "items": {"type": "string"}},
        "activation": {"type": "string", "enum": ["always", "auto", "agent", "manual"]},
        "globs": {"type": "string"},
        "server_dependencies": {"type": "array", "items": {"type": "string"}},
        "skill_dependencies": {"type": "array", "items": {"type": "string"}},
        "install_spec": {"type": "string"},
    },
}
