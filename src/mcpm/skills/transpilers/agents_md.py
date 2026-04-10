"""AGENTS.md transpiler -- generates <available_skills> XML block."""

import html
from pathlib import Path
from typing import List, Optional

from mcpm.skills.schema import SkillConfig, TranspileResult
from mcpm.skills.transpiler import BaseSkillTranspiler, inject_managed_block, register_transpiler


@register_transpiler
class AgentsMdTranspiler(BaseSkillTranspiler):
    client_key = "agents-md"
    display_name = "AGENTS.md"

    def transpile(self, skill: SkillConfig, project_root: Path) -> TranspileResult:
        # This transpiler is special -- it generates a single block for ALL skills.
        # The sync engine calls transpile_all() instead.
        # Individual transpile() returns the skill's XML line for composition.
        fm = skill.frontmatter
        desc = html.escape(fm.description)
        line = f'<skill name="{fm.name}" description="{desc}" />'
        return TranspileResult(
            output_path=self.get_output_path(skill, project_root),
            content=line,
            warnings=[],
        )

    def transpile_all(self, skills: List[SkillConfig], project_root: Path) -> TranspileResult:
        """Generate a single AGENTS.md block with all skills listed."""
        warnings = []
        lines = ["<available_skills>"]
        for skill in skills:
            desc = html.escape(skill.frontmatter.description)
            lines.append(f'<skill name="{skill.name}" description="{desc}" />')
        lines.append("</available_skills>")

        block_content = "\n".join(lines)

        agents_md_path = project_root / "AGENTS.md"
        existing = ""
        if agents_md_path.exists():
            existing = agents_md_path.read_text(encoding="utf-8")

        content = inject_managed_block(existing, block_content)

        return TranspileResult(
            output_path=agents_md_path,
            content=content,
            warnings=warnings,
        )

    def get_output_path(self, skill: SkillConfig, project_root: Path) -> Path:
        return project_root / "AGENTS.md"

    def clean(self, project_root: Path, managed_skills: Optional[List[str]] = None) -> List[Path]:
        """Remove the mcpm-managed block from AGENTS.md."""
        agents_md_path = project_root / "AGENTS.md"
        if not agents_md_path.exists():
            return []

        content = agents_md_path.read_text(encoding="utf-8")
        from mcpm.skills.transpiler import MCPM_BLOCK_END, MCPM_BLOCK_START

        start_idx = content.find(MCPM_BLOCK_START)
        end_idx = content.find(MCPM_BLOCK_END)

        if start_idx == -1 or end_idx == -1:
            return []

        before = content[:start_idx].rstrip()
        after = content[end_idx + len(MCPM_BLOCK_END) :].lstrip()
        cleaned = (before + "\n\n" + after).strip()

        if cleaned:
            agents_md_path.write_text(cleaned + "\n", encoding="utf-8")
        else:
            agents_md_path.unlink()

        return [agents_md_path]
