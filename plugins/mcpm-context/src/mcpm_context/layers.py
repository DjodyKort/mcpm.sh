"""Scaffold context layers as rules in the canonical skills repo.

Layers ARE mcpm rules: `rules/<name>/SKILL.md` with `activation: always`
(optionally `globs:` for path-scoping) — the existing skills pipeline
transpiles them to `~/.claude/rules/<name>.md` on `mcpm skills sync --global`,
and both git publish (skills_git_push) and the encrypted machine-sync bundle
already carry the rules/ dir. This module only scaffolds; it never overwrites
an existing SKILL.md body.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import yaml

from .paths import skills_repo_path

PERSONAL_RULE_NAME = "personal"

_PERSONAL_TEMPLATE = """\
---
name: personal
description: "Personal always-on layer on top of the org CLAUDE.md"
activation: always
---

## Personal preferences

<!-- Your personal layer. Survives cf-dev-tools syncs (it never touches rules/).
     Keep it additive to the org CLAUDE.md — rules load after user memory. -->
"""

_CLIENT_TEMPLATE = """\
---
name: client-{slug}
description: "Client context: {display}"
activation: always
globs: "{globs}"
---

## {display} — client context

<!-- Project knowledge for this client that doesn't belong in the repo's own
     CLAUDE.md: contacts, conventions, environment quirks, gotchas. -->
"""


@dataclass
class Layer:
    name: str
    path: Path
    globs: List[str]
    description: str = ""


def rules_dir() -> Path:
    return skills_repo_path() / "rules"


def scaffold_personal_rule() -> Optional[Path]:
    """Create rules/personal/SKILL.md; None when it already exists."""
    target = rules_dir() / PERSONAL_RULE_NAME / "SKILL.md"
    if target.exists():
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_PERSONAL_TEMPLATE)
    return target


def _slug(name: str) -> str:
    """Skill names allow only lowercase alphanumerics + single hyphens; client
    dir names may contain underscores (e.g. v18_arp) — slug the rule name,
    keep the raw name in the glob."""
    slug = re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9-]", "-", name.lower())).strip("-")
    return slug or "client"


def scaffold_client_rule(name: str, glob: Optional[str] = None, clients_root: str = "") -> Optional[Path]:
    """Create rules/client-<slug>/SKILL.md with a path-scoped glob; None when present.

    Default glob matches anywhere under a clients/<name> dir, which covers both
    the clients tree and worktrees checked out elsewhere under the same name.
    """
    target = rules_dir() / f"client-{_slug(name)}" / "SKILL.md"
    if target.exists():
        return None
    # mcpm's SkillFrontmatter.globs is a comma-separated STRING (Cursor convention).
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_CLIENT_TEMPLATE.format(
        slug=_slug(name), display=name, globs=glob or f"**/clients/{name}/**",
    ))
    return target


def list_layers() -> List[Layer]:
    """Parse rules/*/SKILL.md frontmatter (name, globs, description)."""
    layers: List[Layer] = []
    base = rules_dir()
    if not base.is_dir():
        return layers
    for rule_dir in sorted(base.iterdir()):
        skill_md = rule_dir / "SKILL.md"
        if not rule_dir.is_dir() or not skill_md.exists():
            continue
        fm = _parse_frontmatter(skill_md)
        raw_globs = fm.get("globs") or ""
        globs = [g.strip() for g in raw_globs.split(",") if g.strip()] if isinstance(raw_globs, str) else list(raw_globs)
        layers.append(
            Layer(
                name=str(fm.get("name", rule_dir.name)),
                path=skill_md,
                globs=globs,
                description=str(fm.get("description", "")),
            )
        )
    return layers


MANAGED_LOCAL_HEADER = (
    "<!-- Managed by `mcpm context` — edit the canonical layer "
    "(skills_repo/rules/client-*/SKILL.md); `mcpm context sync` regenerates. -->"
)


def deploy_client_locals(clients_root: Path, report) -> None:
    """Deploy client layers as CLAUDE.local.md into their client repos.

    Rules with `paths:` globs match project-relative file paths, so they only
    activate for sessions rooted ABOVE the client dir (e.g. the ODH root).
    Sessions rooted INSIDE a client repo need project memory instead —
    CLAUDE.local.md is the native personal, uncommitted variant. Body-only
    (frontmatter stripped), ignored via .git/info/exclude (local, never
    committed). Existing unmanaged files are left alone.
    """
    if not clients_root.is_dir():
        return
    client_layers = {layer.name: layer for layer in list_layers() if layer.name.startswith("client-")}
    for child in sorted(clients_root.iterdir()):
        layer = client_layers.get(f"client-{_slug(child.name)}") if child.is_dir() else None
        if layer is None:
            continue
        target = child / "CLAUDE.local.md"
        content = f"{MANAGED_LOCAL_HEADER}\n\n{_body_of(layer.path).strip()}\n"
        if target.exists() and MANAGED_LOCAL_HEADER not in target.read_text():
            report.warn(f"{target} exists and is not managed — leaving it alone")
            continue
        if not target.exists() or target.read_text() != content:
            target.write_text(content)
            report.add(f"deployed {target}")
        _ensure_local_exclude(child, report)


def _ensure_local_exclude(repo: Path, report) -> None:
    git_dir = repo / ".git"
    if not git_dir.is_dir():  # absent, or a worktree pointer file — skip
        return
    exclude = git_dir / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    lines = exclude.read_text().splitlines() if exclude.exists() else []
    if "CLAUDE.local.md" not in lines:
        exclude.write_text("\n".join(lines + ["CLAUDE.local.md"]) + "\n")
        report.add(f"added CLAUDE.local.md to {repo.name}/.git/info/exclude")


def _body_of(path: Path) -> str:
    text = path.read_text()
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[2]
    return text


def _parse_frontmatter(path: Path) -> dict:
    try:
        text = path.read_text()
        if not text.startswith("---"):
            return {}
        parts = text.split("---", 2)
        if len(parts) < 3:
            return {}
        return yaml.safe_load(parts[1]) or {}
    except Exception:
        return {}
