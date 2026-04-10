"""Aider transpiler -- .mcpm/skills/<name>/SKILL.md via read: config."""

from pathlib import Path

from mcpm.skills.schema import SkillConfig, TranspileResult
from mcpm.skills.transpiler import BaseSkillTranspiler, register_transpiler


@register_transpiler
class AiderTranspiler(BaseSkillTranspiler):
    client_key = "aider"
    display_name = "Aider"

    def transpile(self, skill: SkillConfig, project_root: Path) -> TranspileResult:
        fm = skill.frontmatter
        warnings = []

        # Aider: always-on only. Skills stored at .mcpm/skills/<name>/SKILL.md
        # and referenced via `read:` in .aider.conf.yml
        if fm.activation != "always":
            warnings.append(f"aider: activation '{fm.activation}' downgraded to 'always'")

        # Plain markdown -- Aider doesn't parse frontmatter
        content = f"# {fm.name}\n\n{skill.body}\n"

        return TranspileResult(
            output_path=self.get_output_path(skill, project_root),
            content=content,
            warnings=warnings,
        )

    def get_output_path(self, skill: SkillConfig, project_root: Path) -> Path:
        return project_root / ".mcpm" / "skills" / skill.name / "SKILL.md"
