"""VS Code Copilot transpiler -- .github/skills/ and .github/instructions/."""

from pathlib import Path

from mcpm.skills.schema import SkillConfig, TranspileResult
from mcpm.skills.transpiler import BaseSkillTranspiler, register_transpiler


@register_transpiler
class VSCodeCopilotTranspiler(BaseSkillTranspiler):
    client_key = "vscode"
    display_name = "VS Code Copilot"

    def transpile(self, skill: SkillConfig, project_root: Path) -> TranspileResult:
        fm = skill.frontmatter
        warnings = []

        if skill.skill_type == "rule" or fm.activation == "always":
            # Rules go to .github/instructions/<name>.instructions.md
            fields = {}
            if fm.globs:
                fields["applyTo"] = fm.globs
            frontmatter = self._render_frontmatter(fields)
            content = f"{frontmatter}\n\n{skill.body}\n" if frontmatter else f"{skill.body}\n"
        else:
            # Skills go to .github/skills/<name>/SKILL.md (Agent Skills format)
            fields = {"name": fm.name, "description": f'"{fm.description}"'}
            if fm.allowed_tools:
                fields["allowed-tools"] = fm.allowed_tools
            frontmatter = self._render_frontmatter(fields)
            content = f"{frontmatter}\n\n{skill.body}\n"

            # VS Code Copilot doesn't support agent or manual activation natively
            if fm.activation in ("agent", "manual"):
                warnings.append(f"vscode: activation '{fm.activation}' downgraded to 'auto'")

        return TranspileResult(
            output_path=self.get_output_path(skill, project_root),
            content=content,
            warnings=warnings,
        )

    def get_output_path(self, skill: SkillConfig, project_root: Path) -> Path:
        fm = skill.frontmatter
        if skill.skill_type == "rule" or fm.activation == "always":
            return project_root / ".github" / "instructions" / f"{skill.name}.instructions.md"
        return project_root / ".github" / "skills" / skill.name / "SKILL.md"
