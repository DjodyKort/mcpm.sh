"""Claude Code style transpiler -- .claude/output-styles/<name>.md (Tier 1)."""

from pathlib import Path

from mcpm.skills.schema import TranspileResult
from mcpm.styles.schema import StyleConfig
from mcpm.styles.transpiler import BaseStyleTranspiler, register_style_transpiler


@register_style_transpiler
class ClaudeCodeStyleTranspiler(BaseStyleTranspiler):
    client_key = "claude-code"
    display_name = "Claude Code"
    tier = 1

    def transpile(self, style: StyleConfig, project_root: Path) -> TranspileResult:
        fm = style.frontmatter
        fields = {
            "name": fm.name,
            "description": f'"{fm.description}"',
            "keep-coding-instructions": fm.keep_coding_instructions,
        }

        frontmatter = self._render_frontmatter(fields)
        content = f"{frontmatter}\n\n{style.body}\n"

        return TranspileResult(
            output_path=self.get_output_path(style, project_root),
            content=content,
            warnings=[],
        )

    def get_output_path(self, style: StyleConfig, project_root: Path) -> Path:
        return project_root / ".claude" / "output-styles" / f"{style.name}.md"
