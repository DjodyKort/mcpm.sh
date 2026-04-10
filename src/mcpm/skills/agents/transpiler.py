"""Base agent transpiler class and registry."""

import abc
import hashlib
import logging
from pathlib import Path
from typing import Dict, List, Optional, Type

from mcpm.skills.agents.schema import AgentConfig
from mcpm.skills.schema import LockFile, LockFileEntry, TranspileResult

logger = logging.getLogger(__name__)

# Keys of transpilers that use append mode (single file for all agents)
AGENT_APPEND_MODE_TRANSPILERS = {"roomodes"}


class BaseAgentTranspiler(abc.ABC):
    """Abstract base class for per-client agent transpilers."""

    client_key: str = ""
    display_name: str = ""

    @abc.abstractmethod
    def transpile(self, agent: AgentConfig, project_root: Path) -> TranspileResult:
        """Transpile a canonical agent to this client's native format."""

    @abc.abstractmethod
    def get_output_path(self, agent: AgentConfig, project_root: Path) -> Path:
        """Get the output path for an agent in this client's format."""

    def clean(self, project_root: Path, managed_agents: Optional[List[str]] = None) -> List[Path]:
        """Remove mcpm-managed agent files for this client."""
        removed = []
        if managed_agents:
            from mcpm.skills.agents.schema import AgentConfig, AgentFrontmatter

            for name in managed_agents:
                dummy = AgentConfig(
                    frontmatter=AgentFrontmatter(name=name, description="dummy"),
                    body="",
                    source_path=Path("dummy"),
                )
                path = self.get_output_path(dummy, project_root)
                if path.exists():
                    path.unlink()
                    removed.append(path)
                    parent = path.parent
                    if parent.exists() and not any(parent.iterdir()):
                        parent.rmdir()
        return removed

    def _render_frontmatter(self, fields: Dict[str, object]) -> str:
        """Render a YAML frontmatter block from a dict of fields."""
        if not fields:
            return ""
        lines = ["---"]
        for key, value in fields.items():
            if isinstance(value, bool):
                lines.append(f"{key}: {'true' if value else 'false'}")
            elif isinstance(value, list):
                if value:
                    items = ", ".join(str(v) for v in value)
                    lines.append(f"{key}: [{items}]")
            else:
                lines.append(f"{key}: {value}")
        lines.append("---")
        return "\n".join(lines)


def compute_agent_hash(agent: AgentConfig) -> str:
    """Compute a SHA256 hash of an agent's source file content."""
    content = agent.source_path.read_text(encoding="utf-8")
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


# ---- Agent Transpiler Registry ----

_AGENT_TRANSPILER_REGISTRY: Dict[str, Type[BaseAgentTranspiler]] = {}
_transpilers_loaded = False


def register_agent_transpiler(cls: Type[BaseAgentTranspiler]) -> Type[BaseAgentTranspiler]:
    """Decorator to register an agent transpiler class."""
    _AGENT_TRANSPILER_REGISTRY[cls.client_key] = cls
    return cls


def get_agent_transpiler(client_key: str) -> Optional[BaseAgentTranspiler]:
    cls = _AGENT_TRANSPILER_REGISTRY.get(client_key)
    return cls() if cls else None


def _ensure_transpilers_loaded():
    """Lazily import all transpiler modules to trigger registration."""
    global _transpilers_loaded
    if not _transpilers_loaded:
        import mcpm.skills.agents.transpilers  # noqa: F401

        _transpilers_loaded = True


def get_all_agent_transpilers() -> Dict[str, BaseAgentTranspiler]:
    _ensure_transpilers_loaded()
    return {key: cls() for key, cls in _AGENT_TRANSPILER_REGISTRY.items()}


def sync_agents(
    agents: List[AgentConfig],
    project_root: Path,
    client_keys: Optional[List[str]] = None,
    dry_run: bool = False,
    lockfile: Optional[LockFile] = None,
) -> LockFile:
    """Transpile all agents to target clients and write output files."""
    if lockfile is None:
        lockfile = LockFile.create_now()

    transpilers = get_all_agent_transpilers()
    if client_keys:
        transpilers = {k: v for k, v in transpilers.items() if k in client_keys}

    per_file = {k: v for k, v in transpilers.items() if k not in AGENT_APPEND_MODE_TRANSPILERS}
    append = {k: v for k, v in transpilers.items() if k in AGENT_APPEND_MODE_TRANSPILERS}

    for agent in agents:
        entry = LockFileEntry(
            source="local",
            version=agent.frontmatter.metadata.get("version"),
            hash=compute_agent_hash(agent),
        )

        for client_key, transpiler in per_file.items():
            try:
                result = transpiler.transpile(agent, project_root)
                entry.clients_synced.append(client_key)
                entry.warnings.extend(result.warnings)
                if not dry_run:
                    result.output_path.parent.mkdir(parents=True, exist_ok=True)
                    result.output_path.write_text(result.content, encoding="utf-8")
            except Exception as e:
                logger.warning(f"Failed to transpile agent {agent.name} for {client_key}: {e}")
                entry.warnings.append(f"{client_key}: transpilation failed: {e}")

        lockfile.agents[agent.name] = entry

    # Append-mode transpilers
    for client_key, transpiler in append.items():
        try:
            if hasattr(transpiler, "transpile_all"):
                result = transpiler.transpile_all(agents, project_root)
                for agent in agents:
                    if agent.name in lockfile.agents:
                        lockfile.agents[agent.name].clients_synced.append(client_key)
                        lockfile.agents[agent.name].warnings.extend(result.warnings)
                if not dry_run:
                    result.output_path.parent.mkdir(parents=True, exist_ok=True)
                    result.output_path.write_text(result.content, encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to transpile_all agents for {client_key}: {e}")

    return lockfile
