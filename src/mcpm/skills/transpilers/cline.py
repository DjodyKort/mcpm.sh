"""Cline transpiler -- .clinerules/<name>.md."""

from pathlib import Path

from mcpm.skills.schema import SkillConfig, TranspileResult
from mcpm.skills.transpiler import BaseSkillTranspiler, register_transpiler


@register_transpiler
class ClineTranspiler(BaseSkillTranspiler):
    client_key = "cline"
    display_name = "Cline"

    def transpile(self, skill: SkillConfig, project_root: Path) -> TranspileResult:
        fm = skill.frontmatter
        warnings = []

        fields = {}
        if fm.globs:
            fields["paths"] = fm.globs

        # Cline supports always (no frontmatter) and auto (via paths).
        # Agent/manual downgrade to auto if globs set, else always.
        if fm.activation in ("agent", "manual"):
            if fm.globs:
                warnings.append(f"cline: activation '{fm.activation}' downgraded to 'auto' (paths-based)")
            else:
                warnings.append(f"cline: activation '{fm.activation}' downgraded to 'always'")

        frontmatter = self._render_frontmatter(fields)
        content = f"{frontmatter}\n\n{skill.body}\n" if frontmatter else f"{skill.body}\n"

        return TranspileResult(
            output_path=self.get_output_path(skill, project_root),
            content=content,
            warnings=warnings,
        )

    def get_output_path(self, skill: SkillConfig, project_root: Path) -> Path:
        return project_root / ".clinerules" / f"{skill.name}.md"
