"""Linting and best-practice checks for output styles."""

from typing import List

from mcpm.skills.lint import LintResult
from mcpm.styles.schema import StyleConfig
from mcpm.styles.transpilers.windsurf import WINDSURF_WORKSPACE_CHAR_LIMIT


def lint_style(style: StyleConfig) -> LintResult:
    """Run all lint checks on a single style."""
    result = LintResult()
    fm = style.frontmatter

    # Name must match parent directory name
    if style.source_path.parent.name != fm.name and style.source_path.name == "STYLE.md":
        result.add(
            "error",
            fm.name,
            f"Style name '{fm.name}' does not match directory name '{style.source_path.parent.name}'",
        )

    # Description quality
    if len(fm.description) < 20:
        result.add(
            "warning", fm.name, "Description is very short (<20 chars). Add detail about the tone/style."
        )

    placeholders = ("todo", "todo:", "fixme", "placeholder")
    if fm.description.lower().strip() in placeholders:
        result.add("warning", fm.name, "Description is a placeholder. Fill it in before syncing.")

    # Body checks
    if not style.body.strip():
        result.add("warning", fm.name, "Body is empty. Add style instructions.")

    if "TODO" in style.body and style.body.strip().startswith("TODO"):
        result.add("warning", fm.name, "Body starts with TODO placeholder. Replace with actual style instructions.")

    body_lines = style.body.strip().split("\n") if style.body.strip() else []
    if len(body_lines) > 200:
        result.add(
            "warning",
            fm.name,
            f"Body is {len(body_lines)} lines. Output styles should be concise -- consider trimming.",
        )

    # Windsurf character limit
    body_len = len(style.body)
    if body_len > WINDSURF_WORKSPACE_CHAR_LIMIT:
        result.add(
            "warning",
            fm.name,
            f"Body ({body_len} chars) exceeds Windsurf workspace limit ({WINDSURF_WORKSPACE_CHAR_LIMIT}). "
            "Will be truncated on Windsurf.",
        )

    return result


def lint_styles(styles: List[StyleConfig]) -> LintResult:
    """Run lint checks on a collection of styles."""
    result = LintResult()

    for style in styles:
        style_result = lint_style(style)
        result.messages.extend(style_result.messages)

    # Cross-style checks: duplicate names
    names = [s.name for s in styles]
    seen = set()
    for name in names:
        if name in seen:
            result.add("error", name, "Duplicate style name found.")
        seen.add(name)

    return result
