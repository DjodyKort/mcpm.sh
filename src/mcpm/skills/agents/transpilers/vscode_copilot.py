"""VS Code Copilot agent transpiler -- .github/agents/<name>.agent.md."""

from pathlib import Path

from mcpm.skills.agents.schema import AgentConfig
from mcpm.skills.agents.transpiler import BaseAgentTranspiler, register_agent_transpiler
from mcpm.skills.schema import TranspileResult


@register_agent_transpiler
class VSCodeCopilotAgentTranspiler(BaseAgentTranspiler):
    client_key = "vscode"
    display_name = "VS Code Copilot"

    def transpile(self, agent: AgentConfig, project_root: Path) -> TranspileResult:
        fm = agent.frontmatter
        warnings = []

        fields = {"name": fm.name, "description": f'"{fm.description}"'}

        if fm.model:
            fields["model"] = fm.model
        if fm.tools:
            fields["tools"] = fm.tools
        if fm.mcp_servers:
            # Copilot uses mcp-servers as an object, but we output a reference list
            fields["mcp-servers"] = fm.mcp_servers

        if fm.disallowed_tools:
            warnings.append("vscode: 'disallowed-tools' not supported, dropped")
        if fm.max_turns:
            warnings.append("vscode: 'max-turns' not supported, dropped")
        if fm.permission_mode:
            warnings.append("vscode: 'permission-mode' not supported, dropped")

        frontmatter = self._render_frontmatter(fields)
        content = f"{frontmatter}\n\n{agent.body}\n"

        return TranspileResult(
            output_path=self.get_output_path(agent, project_root), content=content, warnings=warnings
        )

    def get_output_path(self, agent: AgentConfig, project_root: Path) -> Path:
        return project_root / ".github" / "agents" / f"{agent.name}.agent.md"
