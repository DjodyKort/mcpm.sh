"""Zed transpiler -- single .rules file (append mode)."""

from pathlib import Path
from typing import List, Optional

from mcpm.skills.schema import SkillConfig, TranspileResult
from mcpm.skills.transpiler import BaseSkillTranspiler, inject_managed_block, register_transpiler


@register_transpiler
class ZedTranspiler(BaseSkillTranspiler):
    client_key = "zed"
    display_name = "Zed"

    def transpile(self, skill: SkillConfig, project_root: Path) -> TranspileResult:
        fm = skill.frontmatter
        warnings = []

        # Zed only supports always-on. All modes downgrade.
        if fm.activation != "always":
            warnings.append(f"zed: activation '{fm.activation}' downgraded to 'always' (single .rules file)")

        # Single skill contribution: header + body
        section = f"## {fm.name}\n\n{skill.body}"

        return TranspileResult(
            output_path=self.get_output_path(skill, project_root),
            content=section,
            warnings=warnings,
        )

    def transpile_all(self, skills: List[SkillConfig], project_root: Path) -> TranspileResult:
        """Concatenate all skills into a single .rules file within managed block."""
        warnings = []
        sections = []

        for skill in skills:
            result = self.transpile(skill, project_root)
            sections.append(result.content)
            warnings.extend(result.warnings)

        block_content = "\n\n---\n\n".join(sections)

        rules_path = project_root / ".rules"
        existing = ""
        if rules_path.exists():
            existing = rules_path.read_text(encoding="utf-8")

        content = inject_managed_block(existing, block_content)

        return TranspileResult(
            output_path=rules_path,
            content=content,
            warnings=warnings,
        )

    def get_output_path(self, skill: SkillConfig, project_root: Path) -> Path:
        return project_root / ".rules"

    def clean(self, project_root: Path, managed_skills: Optional[List[str]] = None) -> List[Path]:
        """Remove the mcpm-managed block from .rules."""
        rules_path = project_root / ".rules"
        if not rules_path.exists():
            return []

        content = rules_path.read_text(encoding="utf-8")
        from mcpm.skills.transpiler import MCPM_BLOCK_END, MCPM_BLOCK_START

        start_idx = content.find(MCPM_BLOCK_START)
        end_idx = content.find(MCPM_BLOCK_END)

        if start_idx == -1 or end_idx == -1:
            return []

        before = content[:start_idx].rstrip()
        after = content[end_idx + len(MCPM_BLOCK_END) :].lstrip()
        cleaned = (before + "\n\n" + after).strip()

        if cleaned:
            rules_path.write_text(cleaned + "\n", encoding="utf-8")
        else:
            rules_path.unlink()

        return [rules_path]
