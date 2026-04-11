"""VS Code Copilot style transpiler -- .github/instructions/mcpm-output-style.instructions.md (Tier 2)."""

from pathlib import Path

from mcpm.skills.schema import TranspileResult
from mcpm.styles.schema import StyleConfig
from mcpm.styles.transpiler import BaseStyleTranspiler, register_style_transpiler


@register_style_transpiler
class VSCodeCopilotStyleTranspiler(BaseStyleTranspiler):
    client_key = "vscode-copilot"
    display_name = "VS Code Copilot"
    tier = 2

    def transpile(self, style: StyleConfig, project_root: Path) -> TranspileResult:
        # VS Code Copilot: no frontmatter, plain markdown
        content = f"{style.body}\n"

        return TranspileResult(
            output_path=self.get_output_path(style, project_root),
            content=content,
            warnings=[],
        )

    def get_output_path(self, style: StyleConfig, project_root: Path) -> Path:
        return project_root / ".github" / "instructions" / "mcpm-output-style.instructions.md"
