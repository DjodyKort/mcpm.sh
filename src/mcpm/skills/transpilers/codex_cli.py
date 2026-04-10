"""Codex CLI transpiler -- .agents/skills/<name>/SKILL.md."""

from pathlib import Path

from mcpm.skills.schema import SkillConfig, TranspileResult
from mcpm.skills.transpiler import BaseSkillTranspiler, register_transpiler


@register_transpiler
class CodexCliTranspiler(BaseSkillTranspiler):
    client_key = "codex-cli"
    display_name = "Codex CLI"

    def transpile(self, skill: SkillConfig, project_root: Path) -> TranspileResult:
        fm = skill.frontmatter
        warnings = []

        # Codex supports skills via .agents/skills/<name>/SKILL.md
        # and rules via AGENTS.md (handled by agents_md transpiler)
        fields = {"name": fm.name, "description": f'"{fm.description}"'}
        if fm.allowed_tools:
            fields["allowed-tools"] = fm.allowed_tools

        if fm.activation == "manual":
            warnings.append("codex-cli: activation 'manual' downgraded to 'agent'")

        frontmatter = self._render_frontmatter(fields)
        content = f"{frontmatter}\n\n{skill.body}\n"

        return TranspileResult(
            output_path=self.get_output_path(skill, project_root),
            content=content,
            warnings=warnings,
        )

    def get_output_path(self, skill: SkillConfig, project_root: Path) -> Path:
        return project_root / ".agents" / "skills" / skill.name / "SKILL.md"
