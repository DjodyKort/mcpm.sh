"""Continue.dev transpiler -- .continue/rules/<name>.md."""

from pathlib import Path

from mcpm.skills.schema import SkillConfig, TranspileResult
from mcpm.skills.transpiler import BaseSkillTranspiler, register_transpiler


@register_transpiler
class ContinueDevTranspiler(BaseSkillTranspiler):
    client_key = "continue"
    display_name = "Continue.dev"

    def transpile(self, skill: SkillConfig, project_root: Path) -> TranspileResult:
        fm = skill.frontmatter
        warnings = []

        fields = {}

        if fm.description:
            fields["description"] = f'"{fm.description}"'

        if fm.globs:
            fields["globs"] = fm.globs

        if fm.priority != 0:
            fields["priority"] = str(fm.priority)

        # Map activation to Continue's model
        if fm.activation == "always":
            fields["alwaysApply"] = True
        elif fm.activation in ("agent", "manual"):
            # Continue doesn't support agent/manual -- downgrade to auto
            warnings.append(f"continue: activation '{fm.activation}' downgraded to 'auto'")

        frontmatter = self._render_frontmatter(fields)
        content = f"{frontmatter}\n\n{skill.body}\n"

        return TranspileResult(
            output_path=self.get_output_path(skill, project_root),
            content=content,
            warnings=warnings,
        )

    def get_output_path(self, skill: SkillConfig, project_root: Path) -> Path:
        return project_root / ".continue" / "rules" / f"{skill.name}.md"
