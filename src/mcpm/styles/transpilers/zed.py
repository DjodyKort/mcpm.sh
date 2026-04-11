"""Zed style transpiler -- .rules file with mcpm-style managed block (Tier 2)."""

from pathlib import Path
from typing import Optional

from mcpm.skills.schema import TranspileResult
from mcpm.styles.schema import StyleConfig
from mcpm.styles.transpiler import BaseStyleTranspiler, register_style_transpiler

# Separate delimiters from skills to avoid collisions
STYLE_BLOCK_START = "<!-- mcpm-style:start -->"
STYLE_BLOCK_END = "<!-- mcpm-style:end -->"


def _inject_style_block(existing_content: str, block_content: str) -> str:
    """Inject or replace content within style-specific delimiters."""
    start_idx = existing_content.find(STYLE_BLOCK_START)
    end_idx = existing_content.find(STYLE_BLOCK_END)

    managed = f"{STYLE_BLOCK_START}\n{block_content}\n{STYLE_BLOCK_END}"

    if start_idx != -1 and end_idx != -1:
        before = existing_content[:start_idx].rstrip()
        after = existing_content[end_idx + len(STYLE_BLOCK_END) :].lstrip()
        parts = [before, managed]
        if after:
            parts.append(after)
        return "\n\n".join(parts) + "\n"
    else:
        if existing_content.strip():
            return existing_content.rstrip() + "\n\n" + managed + "\n"
        return managed + "\n"


def _remove_style_block(content: str) -> str:
    """Remove the style managed block from content."""
    start_idx = content.find(STYLE_BLOCK_START)
    end_idx = content.find(STYLE_BLOCK_END)

    if start_idx == -1 or end_idx == -1:
        return content

    before = content[:start_idx].rstrip()
    after = content[end_idx + len(STYLE_BLOCK_END) :].lstrip()
    return (before + "\n\n" + after).strip()


@register_style_transpiler
class ZedStyleTranspiler(BaseStyleTranspiler):
    client_key = "zed"
    display_name = "Zed"
    tier = 2

    def transpile(self, style: StyleConfig, project_root: Path) -> TranspileResult:
        section = f"## Output Style: {style.frontmatter.name}\n\n{style.body}"

        rules_path = project_root / ".rules"
        existing = ""
        if rules_path.exists():
            existing = rules_path.read_text(encoding="utf-8")

        content = _inject_style_block(existing, section)

        return TranspileResult(
            output_path=rules_path,
            content=content,
            warnings=[],
        )

    def get_output_path(self, style: StyleConfig, project_root: Path) -> Path:
        return project_root / ".rules"

    def clean(self, project_root: Path, managed_styles: Optional[list[str]] = None) -> list[Path]:
        """Remove the style managed block from .rules."""
        rules_path = project_root / ".rules"
        if not rules_path.exists():
            return []

        content = rules_path.read_text(encoding="utf-8")
        if STYLE_BLOCK_START not in content:
            return []

        cleaned = _remove_style_block(content)
        if cleaned:
            rules_path.write_text(cleaned + "\n", encoding="utf-8")
        else:
            rules_path.unlink()

        return [rules_path]
