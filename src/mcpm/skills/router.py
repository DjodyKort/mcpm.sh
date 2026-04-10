"""Router integration -- expose skills as MCP resources via FastMCP."""

import logging
from pathlib import Path
from typing import List, Optional

from mcpm.skills.parser import discover_skills, find_skills_repo
from mcpm.skills.schema import SkillConfig

logger = logging.getLogger(__name__)


def get_skills_resource_list(repo_path: Optional[Path] = None) -> List[dict]:
    """Get a list of skills formatted as MCP resource metadata.

    Returns a list of dicts suitable for MCP resource listing:
    [{"uri": "mcpm://skills/name", "name": "...", "description": "...", "mimeType": "text/markdown"}]
    """
    if repo_path is None:
        repo_path = find_skills_repo()
    if not repo_path:
        return []

    skills = discover_skills(repo_path)
    return [
        {
            "uri": f"mcpm://skills/{skill.name}",
            "name": skill.name,
            "description": skill.frontmatter.description,
            "mimeType": "text/markdown",
            "metadata": {
                "type": skill.skill_type,
                "activation": skill.frontmatter.activation,
                "globs": skill.frontmatter.globs,
            },
        }
        for skill in skills
    ]


def get_skill_content(name: str, repo_path: Optional[Path] = None) -> Optional[str]:
    """Get the full content of a skill by name.

    Returns the SKILL.md body content, or None if not found.
    """
    if repo_path is None:
        repo_path = find_skills_repo()
    if not repo_path:
        return None

    skills = discover_skills(repo_path)
    for skill in skills:
        if skill.name == name:
            return skill.body
    return None


def register_skills_resources(fastmcp_instance, repo_path: Optional[Path] = None) -> int:
    """Register skills as MCP resources on a FastMCP instance.

    This adds two resource types:
    1. mcpm://skills/list -- JSON list of all available skills
    2. mcpm://skills/{name} -- Full instructions for a specific skill

    Args:
        fastmcp_instance: A FastMCP server instance.
        repo_path: Skills repository root.

    Returns:
        Number of skill resources registered.
    """
    import json

    if repo_path is None:
        repo_path = find_skills_repo()
    if not repo_path:
        return 0

    skills = discover_skills(repo_path)
    if not skills:
        return 0

    # Register list resource
    skills_list = get_skills_resource_list(repo_path)

    @fastmcp_instance.resource("mcpm://skills/list")
    def list_skills_resource() -> str:
        """List all available mcpm skills with metadata."""
        return json.dumps(skills_list, indent=2)

    # Register individual skill resources
    for skill in skills:

        def make_skill_resource(s: SkillConfig):
            @fastmcp_instance.resource(f"mcpm://skills/{s.name}")
            def skill_resource() -> str:
                return s.body

            skill_resource.__name__ = f"skill_{s.name.replace('-', '_')}"
            skill_resource.__doc__ = s.frontmatter.description
            return skill_resource

        make_skill_resource(skill)

    return len(skills)
