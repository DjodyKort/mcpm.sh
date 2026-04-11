"""Gemini CLI style transpiler -- .gemini/skills/mcpm-output-style/SKILL.md (Tier 2)."""

from pathlib import Path

from mcpm.skills.schema import TranspileResult
from mcpm.styles.schema import StyleConfig
from mcpm.styles.transpiler import BaseStyleTranspiler, register_style_transpiler


@register_style_transpiler
class GeminiCliStyleTranspiler(BaseStyleTranspiler):
    client_key = "gemini-cli"
    display_name = "Gemini CLI"
    tier = 2

    def transpile(self, style: StyleConfig, project_root: Path) -> TranspileResult:
        fm = style.frontmatter
        fields = {
            "name": "mcpm-output-style",
            "description": f'"Output style: {fm.description}"',
        }
        frontmatter = self._render_frontmatter(fields)
        content = f"{frontmatter}\n\n{style.body}\n"

        return TranspileResult(
            output_path=self.get_output_path(style, project_root),
            content=content,
            warnings=[],
        )

    def get_output_path(self, style: StyleConfig, project_root: Path) -> Path:
        return project_root / ".gemini" / "skills" / "mcpm-output-style" / "SKILL.md"
