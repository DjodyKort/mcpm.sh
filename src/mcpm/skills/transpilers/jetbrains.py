"""JetBrains AI transpiler -- .aiassistant/rules/<name>.md."""

from pathlib import Path

from mcpm.skills.schema import SkillConfig, TranspileResult
from mcpm.skills.transpiler import BaseSkillTranspiler, register_transpiler


@register_transpiler
class JetBrainsTranspiler(BaseSkillTranspiler):
    client_key = "jetbrains"
    display_name = "JetBrains AI"

    def transpile(self, skill: SkillConfig, project_root: Path) -> TranspileResult:
        fm = skill.frontmatter
        warnings = []

        # JetBrains AI supports all four activation modes natively.
        # However, the metadata is managed via IDE UI, not frontmatter.
        # We output plain markdown with an mcpm comment header for context.
        header_lines = [f"<!-- mcpm: name={fm.name}, activation={fm.activation}"]
        if fm.globs:
            header_lines[0] += f", globs={fm.globs}"
        if fm.description:
            header_lines[0] += f' -->\n<!-- mcpm: description="{fm.description}"'
        header_lines[0] += " -->"

        content = "\n".join(header_lines) + "\n\n" + skill.body + "\n"

        return TranspileResult(
            output_path=self.get_output_path(skill, project_root),
            content=content,
            warnings=warnings,
        )

    def get_output_path(self, skill: SkillConfig, project_root: Path) -> Path:
        return project_root / ".aiassistant" / "rules" / f"{skill.name}.md"
