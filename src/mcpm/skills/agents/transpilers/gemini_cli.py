"""Gemini CLI agent transpiler -- .gemini/agents/<name>.md."""

from pathlib import Path

from mcpm.skills.agents.schema import AgentConfig
from mcpm.skills.agents.transpiler import BaseAgentTranspiler, register_agent_transpiler
from mcpm.skills.schema import TranspileResult


@register_agent_transpiler
class GeminiCliAgentTranspiler(BaseAgentTranspiler):
    client_key = "gemini-cli"
    display_name = "Gemini CLI"

    def transpile(self, agent: AgentConfig, project_root: Path) -> TranspileResult:
        fm = agent.frontmatter
        warnings = []

        fields = {"name": fm.name, "description": f'"{fm.description}"'}

        if fm.model:
            fields["model"] = fm.model
        if fm.tools:
            fields["tools"] = fm.tools
        if fm.max_turns:
            fields["max_turns"] = str(fm.max_turns)
        if fm.mcp_servers:
            fields["mcpServers"] = fm.mcp_servers

        if fm.disallowed_tools:
            warnings.append("gemini-cli: 'disallowed-tools' not supported, dropped")
        if fm.permission_mode:
            warnings.append("gemini-cli: 'permission-mode' not supported, dropped")

        frontmatter = self._render_frontmatter(fields)
        content = f"{frontmatter}\n\n{agent.body}\n"

        return TranspileResult(
            output_path=self.get_output_path(agent, project_root), content=content, warnings=warnings
        )

    def get_output_path(self, agent: AgentConfig, project_root: Path) -> Path:
        return project_root / ".gemini" / "agents" / f"{agent.name}.md"
