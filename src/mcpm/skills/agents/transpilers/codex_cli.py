"""Codex CLI agent transpiler -- .codex/agents/<name>.toml (TOML output)."""

from pathlib import Path

from mcpm.skills.agents.schema import AgentConfig
from mcpm.skills.agents.transpiler import BaseAgentTranspiler, register_agent_transpiler
from mcpm.skills.schema import TranspileResult

# Map canonical permission modes to Codex sandbox modes
_SANDBOX_MAP = {
    "default": "lenient",
    "plan": "sandbox",
    "full-auto": "full-auto",
}


@register_agent_transpiler
class CodexCliAgentTranspiler(BaseAgentTranspiler):
    client_key = "codex-cli"
    display_name = "Codex CLI"

    def transpile(self, agent: AgentConfig, project_root: Path) -> TranspileResult:
        fm = agent.frontmatter
        warnings = []

        lines = []
        lines.append(f'name = "{fm.name}"')
        lines.append(f'description = "{fm.description}"')

        # Body goes into developer_instructions as a multi-line TOML string
        escaped_body = agent.body.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')
        lines.append(f'developer_instructions = """\n{escaped_body}\n"""')

        if fm.model:
            lines.append(f'model = "{fm.model}"')

        if fm.effort:
            lines.append(f'model_reasoning_effort = "{fm.effort}"')

        sandbox = _SANDBOX_MAP.get(fm.permission_mode, "lenient") if fm.permission_mode else None
        if fm.readonly:
            sandbox = "sandbox"
        if sandbox:
            lines.append(f'sandbox_mode = "{sandbox}"')

        if fm.mcp_servers:
            lines.append("")
            lines.append("[mcp_servers]")
            for server in fm.mcp_servers:
                lines.append(f'[mcp_servers."{server}"]')
                lines.append(f"# Configure via mcpm: mcpm install {server}")

        if fm.tools:
            warnings.append("codex-cli: 'tools' field not supported in agent TOML, dropped")

        content = "\n".join(lines) + "\n"

        return TranspileResult(
            output_path=self.get_output_path(agent, project_root), content=content, warnings=warnings
        )

    def get_output_path(self, agent: AgentConfig, project_root: Path) -> Path:
        return project_root / ".codex" / "agents" / f"{agent.name}.toml"
