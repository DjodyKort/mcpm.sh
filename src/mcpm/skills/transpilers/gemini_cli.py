"""Gemini CLI transpiler -- .gemini/skills/ and GEMINI.md."""

from pathlib import Path

from mcpm.skills.schema import SkillConfig, TranspileResult
from mcpm.skills.transpiler import BaseSkillTranspiler, register_transpiler


@register_transpiler
class GeminiCliTranspiler(BaseSkillTranspiler):
    client_key = "gemini-cli"
    display_name = "Gemini CLI"

    def transpile(self, skill: SkillConfig, project_root: Path) -> TranspileResult:
        fm = skill.frontmatter
        warnings = []

        if skill.skill_type == "rule" or fm.activation == "always":
            # Always-on rules: generate SKILL.md but also reference from GEMINI.md via @./path
            fields = {"name": fm.name, "description": f'"{fm.description}"'}
            frontmatter = self._render_frontmatter(fields)
            content = f"{frontmatter}\n\n{skill.body}\n"
        else:
            # Skills: generate .gemini/skills/<name>/SKILL.md (Gemini supports progressive disclosure)
            fields = {"name": fm.name, "description": f'"{fm.description}"'}
            if fm.allowed_tools:
                fields["allowed-tools"] = fm.allowed_tools
            frontmatter = self._render_frontmatter(fields)
            content = f"{frontmatter}\n\n{skill.body}\n"

            if fm.activation == "manual":
                warnings.append("gemini-cli: activation 'manual' downgraded to 'agent'")

        return TranspileResult(
            output_path=self.get_output_path(skill, project_root),
            content=content,
            warnings=warnings,
        )

    def get_output_path(self, skill: SkillConfig, project_root: Path) -> Path:
        return project_root / ".gemini" / "skills" / skill.name / "SKILL.md"
