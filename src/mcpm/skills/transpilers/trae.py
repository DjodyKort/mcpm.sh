"""Trae transpiler -- .trae/rules/<name>.md."""

from pathlib import Path

from mcpm.skills.schema import SkillConfig, TranspileResult
from mcpm.skills.transpiler import BaseSkillTranspiler, register_transpiler


@register_transpiler
class TraeTranspiler(BaseSkillTranspiler):
    client_key = "trae"
    display_name = "Trae"

    def transpile(self, skill: SkillConfig, project_root: Path) -> TranspileResult:
        fm = skill.frontmatter
        warnings = []

        fields = {}
        if fm.description:
            fields["description"] = f'"{fm.description}"'
        if fm.globs:
            fields["globs"] = fm.globs

        # Trae supports always and auto (via globs). Agent/manual downgrade.
        if fm.activation in ("agent", "manual"):
            warnings.append(f"trae: activation '{fm.activation}' downgraded to 'auto'")

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
        return project_root / ".trae" / "rules" / f"{skill.name}.md"
