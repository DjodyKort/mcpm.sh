"""Roo Code transpiler -- .roo/rules/<name>.md."""

from pathlib import Path

from mcpm.skills.schema import SkillConfig, TranspileResult
from mcpm.skills.transpiler import BaseSkillTranspiler, register_transpiler


@register_transpiler
class RooCodeTranspiler(BaseSkillTranspiler):
    client_key = "roo-code"
    display_name = "Roo Code"

    def transpile(self, skill: SkillConfig, project_root: Path) -> TranspileResult:
        fm = skill.frontmatter
        warnings = []

        fields = {}
        if fm.description:
            fields["description"] = f'"{fm.description}"'
        if fm.globs:
            fields["globs"] = fm.globs

        # Roo Code supports always, auto, and agent modes
        if fm.activation == "manual":
            warnings.append("roo-code: activation 'manual' downgraded to 'agent'")

        if fm.activation == "always":
            fields["alwaysApply"] = True

        frontmatter = self._render_frontmatter(fields)
        content = f"{frontmatter}\n\n{skill.body}\n"

        return TranspileResult(
            output_path=self.get_output_path(skill, project_root),
            content=content,
            warnings=warnings,
        )

    def get_output_path(self, skill: SkillConfig, project_root: Path) -> Path:
        return project_root / ".roo" / "rules" / f"{skill.name}.md"
