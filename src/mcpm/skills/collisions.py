"""Collision detection and resolution for synced skills.

A "collision" is a pre-existing file at a path the user's client also reads as a
skill, but that mcpm did not write — for example, a hand-written
``~/.claude/commands/foo.md`` slash command that shadows the synced
``~/.claude/skills/foo/SKILL.md``. Resolution is interactive in a TTY and
warn-only otherwise.
"""

from __future__ import annotations

import difflib
import json
import logging
import os
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Literal, Optional

from typing import TYPE_CHECKING

from rich.console import Console

from mcpm.skills.schema import SkillConfig

if TYPE_CHECKING:
    from mcpm.skills.transpiler import BaseSkillTranspiler

logger = logging.getLogger(__name__)

BACKUP_DIR_NAME = ".mcpm-backups"
BACKUP_INDEX_NAME = "INDEX.json"

# Resolution mode resolved from CLI flags + environment.
ResolutionMode = Literal["interactive", "auto-replace", "warn-only"]


@dataclass
class Collision:
    """A pre-existing file that shadows a synced skill."""

    skill_name: str
    client_key: str
    synced_path: Path
    synced_content: str
    collision_path: Path


@dataclass
class CollisionResolution:
    """Result of resolving a collision."""

    collision: Collision
    action: Literal["replaced", "kept", "skipped-dry-run"]
    backup_path: Optional[Path] = None


@dataclass
class CollisionSummary:
    """Aggregate result of resolving a batch of collisions."""

    resolutions: List[CollisionResolution] = field(default_factory=list)

    @property
    def replaced(self) -> List[CollisionResolution]:
        return [r for r in self.resolutions if r.action == "replaced"]

    @property
    def kept(self) -> List[CollisionResolution]:
        return [r for r in self.resolutions if r.action == "kept"]


def resolve_mode(
    migrate: Optional[bool] = None,
    *,
    force_non_interactive: bool = False,
) -> ResolutionMode:
    """Pick the resolution mode given CLI flags and environment.

    Args:
        migrate: True for ``--migrate``, False for ``--no-migrate``, None for default.
        force_non_interactive: Override TTY detection (used in tests).

    Precedence:
        ``--migrate`` → auto-replace (regardless of TTY).
        ``--no-migrate`` → warn-only.
        Else: interactive if TTY and ``MCPM_NON_INTERACTIVE`` unset, else warn-only.
    """
    if migrate is True:
        return "auto-replace"
    if migrate is False:
        return "warn-only"

    if force_non_interactive:
        return "warn-only"
    if os.environ.get("MCPM_NON_INTERACTIVE", "").lower() in ("1", "true", "yes"):
        return "warn-only"
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return "warn-only"
    return "interactive"


def detect_collisions(
    skills: List[SkillConfig],
    transpilers: Dict[str, "BaseSkillTranspiler"],
    output_root: Path,
) -> List[Collision]:  # noqa: F821  -- BaseSkillTranspiler is TYPE_CHECKING only
    """Find all pre-existing files that shadow a synced skill name.

    Each transpiler's ``get_collision_paths()`` is consulted per skill. Only paths
    that already exist on disk are reported.
    """
    collisions: List[Collision] = []
    for skill in skills:
        for client_key, transpiler in transpilers.items():
            try:
                synced_path = transpiler.get_output_path(skill, output_root)
            except Exception:
                continue
            try:
                candidate_paths = transpiler.get_collision_paths(skill, output_root)
            except Exception as e:
                logger.debug(f"{client_key}: get_collision_paths failed for {skill.name}: {e}")
                continue
            for collision_path in candidate_paths:
                if not collision_path.exists() or collision_path == synced_path:
                    continue
                synced_content = ""
                if synced_path.exists():
                    try:
                        synced_content = synced_path.read_text(encoding="utf-8")
                    except OSError:
                        pass
                collisions.append(
                    Collision(
                        skill_name=skill.name,
                        client_key=client_key,
                        synced_path=synced_path,
                        synced_content=synced_content,
                        collision_path=collision_path,
                    )
                )
    return collisions


def render_diff(collision: Collision) -> str:
    """Unified diff between the colliding file and the synced output."""
    try:
        existing = collision.collision_path.read_text(encoding="utf-8").splitlines(keepends=True)
    except OSError as e:
        return f"(failed to read {collision.collision_path}: {e})\n"
    synced = collision.synced_content.splitlines(keepends=True)
    diff = difflib.unified_diff(
        existing,
        synced,
        fromfile=str(collision.collision_path),
        tofile=str(collision.synced_path),
        n=3,
    )
    return "".join(diff) or "(files are identical)\n"


def _backup_root(output_root: Path) -> Path:
    return output_root / BACKUP_DIR_NAME


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def backup_and_remove(collision: Collision, output_root: Path) -> Path:
    """Move the colliding file into ``<output_root>/.mcpm-backups/`` and update INDEX.json.

    Returns the backup path. The original is removed only after the move succeeds.
    """
    backup_root = _backup_root(output_root)
    try:
        rel = collision.collision_path.relative_to(output_root)
    except ValueError:
        # Collision path is outside output_root — fall back to absolute layout
        # under the backup root using the path as a tail component.
        rel = Path(*collision.collision_path.parts[1:]) if collision.collision_path.is_absolute() else collision.collision_path

    timestamp = _timestamp()
    backup_path = backup_root / rel.with_name(rel.name + f".{timestamp}")
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(collision.collision_path), str(backup_path))

    _append_index(
        backup_root,
        {
            "timestamp": timestamp,
            "skill_name": collision.skill_name,
            "client_key": collision.client_key,
            "original_path": str(collision.collision_path),
            "backup_path": str(backup_path),
            "synced_path": str(collision.synced_path),
            "reason": "collision-with-synced-skill",
        },
    )
    return backup_path


def _append_index(backup_root: Path, entry: dict) -> None:
    index_path = backup_root / BACKUP_INDEX_NAME
    if index_path.exists():
        try:
            data = json.loads(index_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {"backups": []}
    else:
        data = {"backups": []}
    data.setdefault("backups", []).append(entry)
    index_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def resolve_collisions(
    collisions: List[Collision],
    output_root: Path,
    mode: ResolutionMode,
    *,
    console: Optional[Console] = None,
    dry_run: bool = False,
) -> CollisionSummary:
    """Resolve a batch of collisions according to ``mode``.

    Interactive mode prompts the user per collision with [R]eplace / [K]eep /
    [D]iff / [A]ll-replace / [S]kip-all. Auto-replace and warn-only never prompt.
    """
    summary = CollisionSummary()
    if not collisions:
        return summary

    console = console or Console()

    if mode == "warn-only":
        for c in collisions:
            console.print(
                f"  [yellow]![/] collision: [cyan]{c.skill_name}[/] ({c.client_key}) — "
                f"existing file at [dim]{c.collision_path}[/] shadows synced skill"
            )
            summary.resolutions.append(CollisionResolution(collision=c, action="kept"))
        return summary

    if mode == "auto-replace":
        for c in collisions:
            if dry_run:
                console.print(
                    f"  [cyan](dry run)[/] would replace [dim]{c.collision_path}[/] (skill: {c.skill_name})"
                )
                summary.resolutions.append(CollisionResolution(collision=c, action="skipped-dry-run"))
                continue
            backup_path = backup_and_remove(c, output_root)
            console.print(
                f"  [green]Replaced[/] [dim]{c.collision_path}[/] → backup at [dim]{backup_path}[/]"
            )
            summary.resolutions.append(
                CollisionResolution(collision=c, action="replaced", backup_path=backup_path)
            )
        return summary

    # Interactive
    apply_to_all: Optional[Literal["replace", "keep"]] = None
    for c in collisions:
        action = apply_to_all
        while action is None:
            console.print(
                f"\n[bold]Collision[/] for skill [cyan]{c.skill_name}[/] in client "
                f"[cyan]{c.client_key}[/]:"
            )
            console.print(f"  Synced:    [dim]{c.synced_path}[/]")
            console.print(f"  Existing:  [dim]{c.collision_path}[/]")
            choice = _prompt_choice(console)
            if choice == "d":
                console.print("\n" + render_diff(c))
                continue
            if choice == "r":
                action = "replace"
            elif choice == "k":
                action = "keep"
            elif choice == "a":
                action = "replace"
                apply_to_all = "replace"
            elif choice == "s":
                action = "keep"
                apply_to_all = "keep"

        if action == "replace":
            if dry_run:
                console.print(
                    f"  [cyan](dry run)[/] would replace [dim]{c.collision_path}[/]"
                )
                summary.resolutions.append(CollisionResolution(collision=c, action="skipped-dry-run"))
            else:
                backup_path = backup_and_remove(c, output_root)
                console.print(
                    f"  [green]Replaced[/] → backup at [dim]{backup_path}[/]"
                )
                summary.resolutions.append(
                    CollisionResolution(collision=c, action="replaced", backup_path=backup_path)
                )
        else:
            console.print(f"  [yellow]Kept[/] [dim]{c.collision_path}[/]")
            summary.resolutions.append(CollisionResolution(collision=c, action="kept"))

    return summary


def _prompt_choice(console: Console) -> str:
    """Prompt for one of R/K/D/A/S; loop until valid."""
    valid = {"r", "k", "d", "a", "s"}
    while True:
        console.print(
            "  [bold]\\[R][/]eplace  [bold]\\[K][/]eep  [bold]\\[D][/]iff  "
            "[bold]\\[A][/]ll-replace  [bold]\\[S][/]kip-all"
        )
        try:
            answer = input("  > ").strip().lower()
        except EOFError:
            return "k"
        if answer in valid:
            return answer
        console.print(f"  [red]Invalid choice '{answer}'. Pick one of R/K/D/A/S.[/]")
