"""Per-client skill transpiler implementations.

All transpiler modules are imported here to trigger @register_transpiler registration.
"""

from mcpm.skills.transpilers import (  # noqa: F401
    agents_md,
    aider,
    amazon_q,
    claude_code,
    cline,
    codex_cli,
    continue_dev,
    cursor,
    gemini_cli,
    goose,
    jetbrains,
    roo_code,
    trae,
    windsurf,
    zed,
)
