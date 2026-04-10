"""AGENT.md parser -- reuses the frontmatter parser from skills."""

import logging
from pathlib import Path
from typing import List

from mcpm.skills.agents.schema import AgentConfig, AgentFrontmatter
from mcpm.skills.parser import parse_frontmatter

logger = logging.getLogger(__name__)


def parse_agent_file(path: Path) -> AgentConfig:
    """Parse a single AGENT.md file into an AgentConfig.

    Args:
        path: Path to the AGENT.md file.

    Returns:
        Parsed AgentConfig.

    Raises:
        ValueError: If the file cannot be parsed or frontmatter is invalid.
        FileNotFoundError: If the file doesn't exist.
    """
    if not path.exists():
        raise FileNotFoundError(f"Agent file not found: {path}")

    content = path.read_text(encoding="utf-8")
    fm_data, body = parse_frontmatter(content)

    if not fm_data:
        raise ValueError(f"No YAML frontmatter found in {path}")

    frontmatter = AgentFrontmatter(**fm_data)

    return AgentConfig(
        frontmatter=frontmatter,
        body=body,
        source_path=path,
    )


def discover_agents(repo_path: Path) -> List[AgentConfig]:
    """Walk the agents/ directory and parse all AGENT.md files.

    Args:
        repo_path: Root of the skills repository.

    Returns:
        List of parsed AgentConfigs.
    """
    agents: List[AgentConfig] = []

    agents_dir = repo_path / "agents"
    if not agents_dir.is_dir():
        return agents

    for agent_dir in sorted(agents_dir.iterdir()):
        if not agent_dir.is_dir():
            continue

        agent_file = agent_dir / "AGENT.md"
        if not agent_file.exists():
            logger.warning(f"Agent directory {agent_dir.name} has no AGENT.md, skipping")
            continue

        try:
            agent = parse_agent_file(agent_file)
            agents.append(agent)
        except (ValueError, Exception) as e:
            logger.warning(f"Failed to parse {agent_file}: {e}")

    return agents
