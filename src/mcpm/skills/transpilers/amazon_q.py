"""Amazon Q transpiler -- .amazonq/rules/<name>.md."""

from pathlib import Path

from mcpm.skills.schema import SkillConfig, TranspileResult
from mcpm.skills.transpiler import BaseSkillTranspiler, register_transpiler


@register_transpiler
class AmazonQTranspiler(BaseSkillTranspiler):
    client_key = "amazon-q"
    display_name = "Amazon Q"

    def transpile(self, skill: SkillConfig, project_root: Path) -> TranspileResult:
        fm = skill.frontmatter
        warnings = []

        # Amazon Q: plain markdown, no frontmatter, always-on only
        if fm.activation != "always":
            warnings.append(f"amazon-q: activation '{fm.activation}' downgraded to 'always' (no frontmatter support)")

        # Include metadata as comment for context
        header = f"<!-- mcpm: {fm.name} - {fm.description} -->"
        content = f"{header}\n\n{skill.body}\n"

        return TranspileResult(
            output_path=self.get_output_path(skill, project_root),
            content=content,
            warnings=warnings,
        )

    def get_output_path(self, skill: SkillConfig, project_root: Path) -> Path:
        return project_root / ".amazonq" / "rules" / f"{skill.name}.md"
