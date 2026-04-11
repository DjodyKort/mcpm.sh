"""Amazon Q style transpiler -- .amazonq/rules/mcpm-output-style.md (Tier 2)."""

from pathlib import Path

from mcpm.skills.schema import TranspileResult
from mcpm.styles.schema import StyleConfig
from mcpm.styles.transpiler import BaseStyleTranspiler, register_style_transpiler


@register_style_transpiler
class AmazonQStyleTranspiler(BaseStyleTranspiler):
    client_key = "amazon-q"
    display_name = "Amazon Q"
    tier = 2

    def transpile(self, style: StyleConfig, project_root: Path) -> TranspileResult:
        fm = style.frontmatter
        header = f"<!-- mcpm: mcpm-output-style - Output style: {fm.description} -->"
        content = f"{header}\n\n{style.body}\n"

        return TranspileResult(
            output_path=self.get_output_path(style, project_root),
            content=content,
            warnings=[],
        )

    def get_output_path(self, style: StyleConfig, project_root: Path) -> Path:
        return project_root / ".amazonq" / "rules" / "mcpm-output-style.md"
