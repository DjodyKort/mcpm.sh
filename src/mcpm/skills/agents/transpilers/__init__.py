"""Per-client agent transpiler implementations.

All transpiler modules are imported here to trigger @register_agent_transpiler registration.
"""

from mcpm.skills.agents.transpilers import (  # noqa: F401
    claude_code,
    codex_cli,
    cursor,
    gemini_cli,
    roo_code,
    vscode_copilot,
)
