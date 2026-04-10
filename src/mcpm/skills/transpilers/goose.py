"""Goose transpiler -- .goose/skills/<name>/SKILL.md."""

from pathlib import Path

from mcpm.skills.schema import SkillConfig, TranspileResult
from mcpm.skills.transpiler import BaseSkillTranspiler, register_transpiler


@register_transpiler
class GooseTranspiler(BaseSkillTranspiler):
    client_key = "goose-cli"
    display_name = "Goose"

    def transpile(self, skill: SkillConfig, project_root: Path) -> TranspileResult:
        fm = skill.frontmatter
        warnings = []

        # Goose supports always, auto (progressive disclosure), and agent modes
        fields = {"name": fm.name, "description": f'"{fm.description}"'}
        if fm.allowed_tools:
            fields["allowed-tools"] = fm.allowed_tools

        if fm.activation == "manual":
            warnings.append("goose-cli: activation 'manual' downgraded to 'agent'")

        frontmatter = self._render_frontmatter(fields)
        content = f"{frontmatter}\n\n{skill.body}\n"

        output_path = self.get_output_path(skill, project_root)
        if skill.skill_type == "rule":
            output_path = project_root / ".goose" / "rules" / f"{skill.name}.md"

        return TranspileResult(
            output_path=output_path,
            content=content,
            warnings=warnings,
        )

    def get_output_path(self, skill: SkillConfig, project_root: Path) -> Path:
        if skill.skill_type == "rule":
            return project_root / ".goose" / "rules" / f"{skill.name}.md"
        return project_root / ".goose" / "skills" / skill.name / "SKILL.md"
