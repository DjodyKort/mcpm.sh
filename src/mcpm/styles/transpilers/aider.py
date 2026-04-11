"""Aider style transpiler -- .mcpm/skills/mcpm-output-style/SKILL.md (Tier 2)."""

from pathlib import Path

from mcpm.skills.schema import TranspileResult
from mcpm.styles.schema import StyleConfig
from mcpm.styles.transpiler import BaseStyleTranspiler, register_style_transpiler


@register_style_transpiler
class AiderStyleTranspiler(BaseStyleTranspiler):
    client_key = "aider"
    display_name = "Aider"
    tier = 2

    def transpile(self, style: StyleConfig, project_root: Path) -> TranspileResult:
        # Aider: plain markdown with heading, no frontmatter
        content = f"# Output Style: {style.frontmatter.name}\n\n{style.body}\n"

        return TranspileResult(
            output_path=self.get_output_path(style, project_root),
            content=content,
            warnings=[],
        )

    def get_output_path(self, style: StyleConfig, project_root: Path) -> Path:
        return project_root / ".mcpm" / "skills" / "mcpm-output-style" / "SKILL.md"
