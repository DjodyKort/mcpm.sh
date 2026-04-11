"""JetBrains AI style transpiler -- .aiassistant/rules/mcpm-output-style.md (Tier 2)."""

from pathlib import Path

from mcpm.skills.schema import TranspileResult
from mcpm.styles.schema import StyleConfig
from mcpm.styles.transpiler import BaseStyleTranspiler, register_style_transpiler


@register_style_transpiler
class JetBrainsStyleTranspiler(BaseStyleTranspiler):
    client_key = "jetbrains"
    display_name = "JetBrains AI"
    tier = 2

    def transpile(self, style: StyleConfig, project_root: Path) -> TranspileResult:
        fm = style.frontmatter
        header = f'<!-- mcpm: name=mcpm-output-style, activation=always -->\n<!-- mcpm: description="Output style: {fm.description}" -->'
        content = f"{header}\n\n{style.body}\n"

        return TranspileResult(
            output_path=self.get_output_path(style, project_root),
            content=content,
            warnings=[],
        )

    def get_output_path(self, style: StyleConfig, project_root: Path) -> Path:
        return project_root / ".aiassistant" / "rules" / "mcpm-output-style.md"
