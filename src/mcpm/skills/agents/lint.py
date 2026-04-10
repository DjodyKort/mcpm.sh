"""Linting and best-practice checks for agents."""

from dataclasses import dataclass, field
from typing import List

from mcpm.skills.agents.schema import AgentConfig

VALID_MODELS = {"sonnet", "opus", "haiku", "inherit"}


@dataclass
class AgentLintMessage:
    level: str
    agent_name: str
    message: str


@dataclass
class AgentLintResult:
    messages: List[AgentLintMessage] = field(default_factory=list)

    @property
    def errors(self) -> List[AgentLintMessage]:
        return [m for m in self.messages if m.level == "error"]

    @property
    def warnings(self) -> List[AgentLintMessage]:
        return [m for m in self.messages if m.level == "warning"]

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0

    def add(self, level: str, agent_name: str, message: str) -> None:
        self.messages.append(AgentLintMessage(level=level, agent_name=agent_name, message=message))


def lint_agent(agent: AgentConfig) -> AgentLintResult:
    """Run lint checks on a single agent."""
    result = AgentLintResult()
    fm = agent.frontmatter

    # Name must match directory
    if agent.source_path.parent.name != fm.name and agent.source_path.name == "AGENT.md":
        result.add(
            "error", fm.name, f"Agent name '{fm.name}' does not match directory name '{agent.source_path.parent.name}'"
        )

    # Description quality
    if len(fm.description) < 20:
        result.add("warning", fm.name, "Description is very short (<20 chars).")

    # Empty body
    if not agent.body.strip():
        result.add("warning", fm.name, "Body (system prompt) is empty.")

    # Model validation
    if fm.model and fm.model not in VALID_MODELS and not fm.model.startswith("claude-"):
        result.add("info", fm.name, f"Model '{fm.model}' is not a standard shorthand (sonnet/opus/haiku/inherit).")

    # Tool conflicts
    if fm.tools and fm.disallowed_tools:
        overlap = set(fm.tools) & set(fm.disallowed_tools)
        if overlap:
            result.add("error", fm.name, f"Tools in both allowed and disallowed: {', '.join(overlap)}")

    # Permission mode + readonly conflict
    if fm.permission_mode == "full-auto" and fm.readonly:
        result.add("warning", fm.name, "readonly=true conflicts with permission-mode=full-auto.")

    # Max turns range
    if fm.max_turns is not None and (fm.max_turns < 1 or fm.max_turns > 200):
        result.add("warning", fm.name, f"max-turns={fm.max_turns} is outside typical range (1-200).")

    return result


def lint_agents(agents: List[AgentConfig]) -> AgentLintResult:
    """Run lint checks on a collection of agents."""
    result = AgentLintResult()

    for agent in agents:
        agent_result = lint_agent(agent)
        result.messages.extend(agent_result.messages)

    # Duplicate names
    names = [a.name for a in agents]
    seen = set()
    for name in names:
        if name in seen:
            result.add("error", name, "Duplicate agent name found.")
        seen.add(name)

    return result
