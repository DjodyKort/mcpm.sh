"""Cursor transpiler -- .cursor/rules/<name>/RULE.md (2.2+)."""

from pathlib import Path

from mcpm.skills.schema import SkillConfig, TranspileResult
from mcpm.skills.transpiler import BaseSkillTranspiler, register_transpiler


@register_transpiler
class CursorTranspiler(BaseSkillTranspiler):
    client_key = "cursor"
    display_name = "Cursor"

    def transpile(self, skill: SkillConfig, project_root: Path) -> TranspileResult:
        fm = skill.frontmatter
        warnings = []

        fields = {}

        if fm.description:
            fields["description"] = f'"{fm.description}"'

        if fm.globs:
            fields["globs"] = fm.globs

        # Map activation modes to Cursor's model
        if fm.activation == "always":
            fields["alwaysApply"] = True
        elif fm.activation == "auto":
            # Auto: Cursor uses description + globs for auto-attach
            pass  # description and globs already set
        elif fm.activation == "agent":
            # Agent-requested mode -- no alwaysApply, no globs auto-attach
            if "globs" in fields:
                del fields["globs"]
        elif fm.activation == "manual":
            # Manual mode -- clear auto fields
            if "globs" in fields:
                del fields["globs"]

        frontmatter = self._render_frontmatter(fields)
        content = f"{frontmatter}\n\n{skill.body}\n"

        return TranspileResult(
            output_path=self.get_output_path(skill, project_root),
            content=content,
            warnings=warnings,
        )

    def get_output_path(self, skill: SkillConfig, project_root: Path) -> Path:
        # New format: .cursor/rules/<name>/RULE.md
        return project_root / ".cursor" / "rules" / skill.name / "RULE.md"
