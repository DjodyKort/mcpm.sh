"""Claude Code agent transpiler -- .claude/agents/<name>.md."""

from pathlib import Path

from mcpm.skills.agents.schema import AgentConfig
from mcpm.skills.agents.transpiler import BaseAgentTranspiler, register_agent_transpiler
from mcpm.skills.schema import TranspileResult


@register_agent_transpiler
class ClaudeCodeAgentTranspiler(BaseAgentTranspiler):
    client_key = "claude-code"
    display_name = "Claude Code"

    def transpile(self, agent: AgentConfig, project_root: Path) -> TranspileResult:
        fm = agent.frontmatter
        fields = {"name": fm.name, "description": f'"{fm.description}"'}

        if fm.model:
            fields["model"] = fm.model
        if fm.tools:
            fields["tools"] = fm.tools
        if fm.disallowed_tools:
            fields["disallowedTools"] = fm.disallowed_tools
        if fm.max_turns:
            fields["maxTurns"] = str(fm.max_turns)
        if fm.mcp_servers:
            fields["mcpServers"] = fm.mcp_servers
        if fm.skills:
            fields["skills"] = fm.skills
        if fm.permission_mode:
            fields["permissionMode"] = fm.permission_mode
        elif fm.readonly:
            fields["permissionMode"] = "plan"
        if fm.effort:
            fields["effort"] = fm.effort
        if fm.color:
            fields["color"] = fm.color

        frontmatter = self._render_frontmatter(fields)
        content = f"{frontmatter}\n\n{agent.body}\n"

        return TranspileResult(output_path=self.get_output_path(agent, project_root), content=content, warnings=[])

    def get_output_path(self, agent: AgentConfig, project_root: Path) -> Path:
        return project_root / ".claude" / "agents" / f"{agent.name}.md"
