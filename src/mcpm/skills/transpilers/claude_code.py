"""Claude Code transpiler -- .claude/skills/ and .claude/rules/."""

from pathlib import Path

from mcpm.skills.schema import SkillConfig, TranspileResult
from mcpm.skills.transpiler import BaseSkillTranspiler, register_transpiler


@register_transpiler
class ClaudeCodeTranspiler(BaseSkillTranspiler):
    client_key = "claude-code"
    display_name = "Claude Code"

    def transpile(self, skill: SkillConfig, project_root: Path) -> TranspileResult:
        fm = skill.frontmatter
        warnings = []

        if skill.skill_type == "rule":
            # Rules go to .claude/rules/<name>.md with optional frontmatter
            fields = {}
            if fm.globs:
                fields["paths"] = fm.globs
            frontmatter = self._render_frontmatter(fields)
            content = f"{frontmatter}\n\n{skill.body}\n" if frontmatter else f"{skill.body}\n"
        else:
            # Skills go to .claude/skills/<name>/SKILL.md
            fields = {"name": fm.name, "description": f'"{fm.description}"'}
            if fm.globs:
                fields["paths"] = fm.globs
            if fm.allowed_tools:
                fields["allowed-tools"] = fm.allowed_tools
            if fm.activation == "manual":
                fields["disable-model-invocation"] = True

            frontmatter = self._render_frontmatter(fields)
            content = f"{frontmatter}\n\n{skill.body}\n"

        return TranspileResult(
            output_path=self.get_output_path(skill, project_root),
            content=content,
            warnings=warnings,
        )

    def get_output_path(self, skill: SkillConfig, project_root: Path) -> Path:
        if skill.skill_type == "rule":
            return project_root / ".claude" / "rules" / f"{skill.name}.md"
        return project_root / ".claude" / "skills" / skill.name / "SKILL.md"
