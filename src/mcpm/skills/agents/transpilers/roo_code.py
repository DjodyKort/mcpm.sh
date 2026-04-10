"""Roo Code agent transpiler -- .roomodes (JSON, append-mode)."""

import json
from pathlib import Path
from typing import List, Optional

from mcpm.skills.agents.schema import AgentConfig
from mcpm.skills.agents.transpiler import BaseAgentTranspiler, register_agent_transpiler
from mcpm.skills.schema import TranspileResult

# Map canonical tool names to Roo Code tool permission groups
_TOOL_GROUP_MAP = {
    "Read": "read",
    "Glob": "read",
    "Grep": "read",
    "Write": "edit",
    "Edit": "edit",
    "Bash": "command",
    "Browser": "browser",
}


def _tools_to_groups(tools: List[str]) -> List[dict]:
    """Convert canonical tool names to Roo Code permission groups."""
    group_set = set()
    for tool in tools:
        group = _TOOL_GROUP_MAP.get(tool)
        if group:
            group_set.add(group)

    groups = []
    for group_name in sorted(group_set):
        entry = [group_name, {"fileRegex": ".*"}] if group_name == "edit" else [group_name, {}]
        groups.append(entry)

    return groups


@register_agent_transpiler
class RooCodeAgentTranspiler(BaseAgentTranspiler):
    client_key = "roomodes"
    display_name = "Roo Code"

    def transpile(self, agent: AgentConfig, project_root: Path) -> TranspileResult:
        fm = agent.frontmatter
        warnings = []

        mode = {
            "slug": fm.name,
            "name": fm.name.replace("-", " ").title(),
            "roleDefinition": fm.description,
            "customInstructions": agent.body,
        }

        if fm.tools:
            mode["groups"] = _tools_to_groups(fm.tools)
        else:
            # Default: all groups enabled
            mode["groups"] = [["read", {}], ["edit", {"fileRegex": ".*"}], ["command", {}], ["mcp", {}]]

        if fm.model:
            warnings.append("roomodes: 'model' not directly supported, included in customInstructions")

        return TranspileResult(
            output_path=self.get_output_path(agent, project_root),
            content=json.dumps(mode, indent=2),
            warnings=warnings,
        )

    def transpile_all(self, agents: List[AgentConfig], project_root: Path) -> TranspileResult:
        """Generate a single .roomodes JSON file with all agents as custom modes."""
        warnings = []
        modes = []

        for agent in agents:
            result = self.transpile(agent, project_root)
            modes.append(json.loads(result.content))
            warnings.extend(result.warnings)

        content = json.dumps({"customModes": modes}, indent=2) + "\n"

        return TranspileResult(
            output_path=project_root / ".roomodes",
            content=content,
            warnings=warnings,
        )

    def get_output_path(self, agent: AgentConfig, project_root: Path) -> Path:
        return project_root / ".roomodes"

    def clean(self, project_root: Path, managed_agents: Optional[List[str]] = None) -> List[Path]:
        """Remove the .roomodes file."""
        path = project_root / ".roomodes"
        if path.exists():
            path.unlink()
            return [path]
        return []
