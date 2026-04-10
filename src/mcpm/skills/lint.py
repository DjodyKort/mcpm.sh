"""Linting and best-practice checks for skills."""

from dataclasses import dataclass, field
from typing import List

from mcpm.skills.schema import SkillConfig
from mcpm.skills.transpilers.windsurf import WINDSURF_WORKSPACE_CHAR_LIMIT


@dataclass
class LintMessage:
    """A single lint finding."""

    level: str  # "error", "warning", "info"
    skill_name: str
    message: str


@dataclass
class LintResult:
    """Aggregate lint results for a collection of skills."""

    messages: List[LintMessage] = field(default_factory=list)

    @property
    def errors(self) -> List[LintMessage]:
        return [m for m in self.messages if m.level == "error"]

    @property
    def warnings(self) -> List[LintMessage]:
        return [m for m in self.messages if m.level == "warning"]

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0

    def add(self, level: str, skill_name: str, message: str) -> None:
        self.messages.append(LintMessage(level=level, skill_name=skill_name, message=message))


def lint_skill(skill: SkillConfig) -> LintResult:
    """Run all lint checks on a single skill."""
    result = LintResult()
    fm = skill.frontmatter

    # ---- Schema validation (already done by Pydantic, but double-check edge cases) ----

    # Name must match parent directory name
    if skill.source_path.parent.name != fm.name and skill.source_path.name == "SKILL.md":
        result.add(
            "error",
            fm.name,
            f"Skill name '{fm.name}' does not match directory name '{skill.source_path.parent.name}'",
        )

    # ---- Best-practice checks ----

    # Description quality
    if len(fm.description) < 20:
        result.add(
            "warning", fm.name, "Description is very short (<20 chars). Add detail about when to use this skill."
        )

    if fm.description.lower() in ("todo", "todo:", "fixme", "placeholder"):
        result.add("warning", fm.name, "Description is a placeholder. Fill it in before syncing.")

    # Check for "when to use" guidance in description
    when_keywords = ["when", "use for", "use when", "use this", "for handling", "for working"]
    has_when_guidance = any(kw in fm.description.lower() for kw in when_keywords)
    if not has_when_guidance and len(fm.description) < 100:
        result.add(
            "info", fm.name, "Description lacks 'when to use' guidance. Consider adding context for agent discovery."
        )

    # Body length
    body_lines = skill.body.strip().split("\n") if skill.body.strip() else []
    if len(body_lines) > 500:
        result.add(
            "warning",
            fm.name,
            f"Body is {len(body_lines)} lines (Agent Skills spec recommends <500). Consider moving detail to references/.",
        )

    if not skill.body.strip():
        result.add("warning", fm.name, "Body is empty. Add instructions for the agent.")

    # ---- Per-client constraint checks ----

    # Windsurf character limit
    body_len = len(skill.body)
    if body_len > WINDSURF_WORKSPACE_CHAR_LIMIT:
        result.add(
            "warning",
            fm.name,
            f"Body ({body_len} chars) exceeds Windsurf workspace limit ({WINDSURF_WORKSPACE_CHAR_LIMIT}). "
            "Will be truncated during sync.",
        )

    # Globs validation
    if fm.globs:
        for pattern in fm.globs.split(","):
            pattern = pattern.strip()
            if not pattern:
                result.add("warning", fm.name, "Empty glob pattern found in globs field.")
            elif pattern == "**/*":
                result.add("info", fm.name, "Glob '**/*' matches all files. Consider being more specific.")

    # Activation + globs mismatch
    if fm.activation == "always" and fm.globs:
        result.add(
            "info",
            fm.name,
            "Skill has activation 'always' with globs set. Globs are ignored when activation is 'always'.",
        )

    return result


def lint_skills(skills: List[SkillConfig]) -> LintResult:
    """Run lint checks on a collection of skills."""
    result = LintResult()

    for skill in skills:
        skill_result = lint_skill(skill)
        result.messages.extend(skill_result.messages)

    # ---- Cross-skill checks ----

    # Check for duplicate names
    names = [s.name for s in skills]
    seen = set()
    for name in names:
        if name in seen:
            result.add("error", name, "Duplicate skill name found.")
        seen.add(name)

    # Check for overlapping globs with same activation
    glob_skills = [(s.name, s.frontmatter.globs, s.frontmatter.activation) for s in skills if s.frontmatter.globs]
    for i, (name_a, globs_a, act_a) in enumerate(glob_skills):
        for name_b, globs_b, act_b in glob_skills[i + 1 :]:
            if act_a == act_b and globs_a == globs_b:
                result.add(
                    "warning",
                    name_a,
                    f"Has identical globs and activation as '{name_b}'. May cause conflicts.",
                )

    return result
