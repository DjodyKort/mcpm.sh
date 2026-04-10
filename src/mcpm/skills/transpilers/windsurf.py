"""Windsurf transpiler -- .windsurf/rules/<name>.md."""

from pathlib import Path

from mcpm.skills.schema import SkillConfig, TranspileResult
from mcpm.skills.transpiler import BaseSkillTranspiler, register_transpiler

# Windsurf constraints
WINDSURF_GLOBAL_CHAR_LIMIT = 6000
WINDSURF_WORKSPACE_CHAR_LIMIT = 12000


@register_transpiler
class WindsurfTranspiler(BaseSkillTranspiler):
    client_key = "windsurf"
    display_name = "Windsurf"

    def transpile(self, skill: SkillConfig, project_root: Path) -> TranspileResult:
        fm = skill.frontmatter
        warnings = []

        fields = {}

        if fm.description:
            fields["description"] = f'"{fm.description}"'

        if fm.globs:
            fields["globs"] = fm.globs

        # Map activation to Windsurf trigger enum
        trigger_map = {
            "always": "always_on",
            "auto": "glob" if fm.globs else "model_decision",
            "agent": "model_decision",
            "manual": "manual",
        }
        fields["trigger"] = trigger_map[fm.activation]

        frontmatter = self._render_frontmatter(fields)
        content = f"{frontmatter}\n\n{skill.body}\n"

        # Check character limits (workspace rules = 12K per file)
        if len(content) > WINDSURF_WORKSPACE_CHAR_LIMIT:
            truncated_body = skill.body[: WINDSURF_WORKSPACE_CHAR_LIMIT - len(frontmatter) - 100]
            truncated_body += "\n\n[truncated -- see full skill at source]"
            content = f"{frontmatter}\n\n{truncated_body}\n"
            warnings.append(
                f"windsurf: body truncated from {len(skill.body)} to fit {WINDSURF_WORKSPACE_CHAR_LIMIT} char limit"
            )

        return TranspileResult(
            output_path=self.get_output_path(skill, project_root),
            content=content,
            warnings=warnings,
        )

    def get_output_path(self, skill: SkillConfig, project_root: Path) -> Path:
        return project_root / ".windsurf" / "rules" / f"{skill.name}.md"
