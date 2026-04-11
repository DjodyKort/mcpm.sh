"""Roo Code style transpiler -- .roomodes custom modes with style- prefix (Tier 1, append-mode)."""

import json
from pathlib import Path
from typing import List, Optional

from mcpm.skills.schema import TranspileResult
from mcpm.styles.schema import StyleConfig
from mcpm.styles.transpiler import BaseStyleTranspiler, register_style_transpiler

STYLE_SLUG_PREFIX = "style-"


@register_style_transpiler
class RooCodeStyleTranspiler(BaseStyleTranspiler):
    client_key = "roomodes-style"
    display_name = "Roo Code"
    tier = 1

    def transpile(self, style: StyleConfig, project_root: Path) -> TranspileResult:
        fm = style.frontmatter

        mode = {
            "slug": f"{STYLE_SLUG_PREFIX}{fm.name}",
            "name": fm.name.replace("-", " ").title(),
            "roleDefinition": fm.description,
            "customInstructions": style.body,
            "groups": [["read", {}], ["edit", {"fileRegex": ".*"}], ["command", {}], ["mcp", {}]],
        }

        return TranspileResult(
            output_path=self.get_output_path(style, project_root),
            content=json.dumps(mode, indent=2),
            warnings=[],
        )

    def transpile_all(self, styles: List[StyleConfig], project_root: Path) -> TranspileResult:
        """Generate .roomodes JSON merging style modes with existing agent/user modes."""
        warnings = []
        new_modes = []

        for style in styles:
            result = self.transpile(style, project_root)
            new_modes.append(json.loads(result.content))
            warnings.extend(result.warnings)

        # Read existing .roomodes and preserve non-style modes
        roomodes_path = project_root / ".roomodes"
        existing_modes = []
        if roomodes_path.exists():
            try:
                data = json.loads(roomodes_path.read_text(encoding="utf-8"))
                for mode in data.get("customModes", []):
                    slug = mode.get("slug", "")
                    if not slug.startswith(STYLE_SLUG_PREFIX):
                        existing_modes.append(mode)
            except (json.JSONDecodeError, Exception):
                pass

        merged = existing_modes + new_modes
        content = json.dumps({"customModes": merged}, indent=2) + "\n"

        return TranspileResult(
            output_path=roomodes_path,
            content=content,
            warnings=warnings,
        )

    def get_output_path(self, style: StyleConfig, project_root: Path) -> Path:
        return project_root / ".roomodes"

    def clean(self, project_root: Path, managed_styles: Optional[List[str]] = None) -> List[Path]:
        """Remove only style- prefixed modes from .roomodes, preserve the rest."""
        roomodes_path = project_root / ".roomodes"
        if not roomodes_path.exists():
            return []

        try:
            data = json.loads(roomodes_path.read_text(encoding="utf-8"))
            modes = data.get("customModes", [])
            filtered = [m for m in modes if not m.get("slug", "").startswith(STYLE_SLUG_PREFIX)]

            if filtered:
                data["customModes"] = filtered
                roomodes_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            elif not modes:
                # File had no modes at all, leave it alone
                return []
            else:
                # Only style modes existed, remove the file
                roomodes_path.unlink()

            return [roomodes_path]
        except (json.JSONDecodeError, Exception):
            return []
