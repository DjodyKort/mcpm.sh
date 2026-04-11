"""Cline style transpiler -- .clinerules/mcpm-output-style.md (Tier 2)."""

from pathlib import Path

from mcpm.skills.schema import TranspileResult
from mcpm.styles.schema import StyleConfig
from mcpm.styles.transpiler import BaseStyleTranspiler, register_style_transpiler


@register_style_transpiler
class ClineStyleTranspiler(BaseStyleTranspiler):
    client_key = "cline"
    display_name = "Cline"
    tier = 2

    def transpile(self, style: StyleConfig, project_root: Path) -> TranspileResult:
        # Cline: plain markdown, no frontmatter for always-on rules
        content = f"{style.body}\n"

        return TranspileResult(
            output_path=self.get_output_path(style, project_root),
            content=content,
            warnings=[],
        )

    def get_output_path(self, style: StyleConfig, project_root: Path) -> Path:
        return project_root / ".clinerules" / "mcpm-output-style.md"
