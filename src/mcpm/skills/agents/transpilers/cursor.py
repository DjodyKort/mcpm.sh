"""Cursor agent transpiler -- .cursor/agents/<name>.md."""

from pathlib import Path

from mcpm.skills.agents.schema import AgentConfig
from mcpm.skills.agents.transpiler import BaseAgentTranspiler, register_agent_transpiler
from mcpm.skills.schema import TranspileResult


@register_agent_transpiler
class CursorAgentTranspiler(BaseAgentTranspiler):
    client_key = "cursor"
    display_name = "Cursor"

    def transpile(self, agent: AgentConfig, project_root: Path) -> TranspileResult:
        fm = agent.frontmatter
        warnings = []

        fields = {"name": fm.name, "description": f'"{fm.description}"'}

        if fm.model:
            fields["model"] = fm.model
        if fm.readonly:
            fields["readonly"] = True

        # Cursor doesn't support these natively
        if fm.tools:
            warnings.append("cursor: 'tools' field not supported, dropped")
        if fm.mcp_servers:
            warnings.append("cursor: 'mcp-servers' field not supported, dropped")
        if fm.max_turns:
            warnings.append("cursor: 'max-turns' field not supported, dropped")

        frontmatter = self._render_frontmatter(fields)
        content = f"{frontmatter}\n\n{agent.body}\n"

        return TranspileResult(
            output_path=self.get_output_path(agent, project_root), content=content, warnings=warnings
        )

    def get_output_path(self, agent: AgentConfig, project_root: Path) -> Path:
        return project_root / ".cursor" / "agents" / f"{agent.name}.md"
