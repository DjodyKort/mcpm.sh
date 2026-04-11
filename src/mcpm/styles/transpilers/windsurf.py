"""Windsurf style transpiler -- .windsurf/rules/mcpm-output-style.md (Tier 2)."""

from pathlib import Path

from mcpm.skills.schema import TranspileResult
from mcpm.styles.schema import StyleConfig
from mcpm.styles.transpiler import BaseStyleTranspiler, register_style_transpiler

WINDSURF_WORKSPACE_CHAR_LIMIT = 12000


@register_style_transpiler
class WindsurfStyleTranspiler(BaseStyleTranspiler):
    client_key = "windsurf"
    display_name = "Windsurf"
    tier = 2

    def transpile(self, style: StyleConfig, project_root: Path) -> TranspileResult:
        fm = style.frontmatter
        warnings = []

        fields = {
            "description": f'"Output style: {fm.description}"',
            "trigger": "always_on",
        }
        frontmatter = self._render_frontmatter(fields)
        content = f"{frontmatter}\n\n{style.body}\n"

        if len(content) > WINDSURF_WORKSPACE_CHAR_LIMIT:
            truncated_body = style.body[: WINDSURF_WORKSPACE_CHAR_LIMIT - len(frontmatter) - 100]
            truncated_body += "\n\n[truncated -- see full style at source]"
            content = f"{frontmatter}\n\n{truncated_body}\n"
            warnings.append(
                f"windsurf: style body truncated from {len(style.body)} to fit {WINDSURF_WORKSPACE_CHAR_LIMIT} char limit"
            )

        return TranspileResult(
            output_path=self.get_output_path(style, project_root),
            content=content,
            warnings=warnings,
        )

    def get_output_path(self, style: StyleConfig, project_root: Path) -> Path:
        return project_root / ".windsurf" / "rules" / "mcpm-output-style.md"
