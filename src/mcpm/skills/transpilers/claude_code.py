"""Claude Code transpiler -- .claude/skills/ and .claude/rules/."""

import json
from pathlib import Path
from typing import List

from mcpm.skills.schema import SkillConfig, TranspileResult
from mcpm.skills.transpiler import BaseSkillTranspiler, register_transpiler


@register_transpiler
class ClaudeCodeTranspiler(BaseSkillTranspiler):
    client_key = "claude-code"
    display_name = "Claude Code"

    def transpile(self, skill: SkillConfig, project_root: Path) -> TranspileResult:
        fm = skill.frontmatter
        warnings = []

        if skill.skill_type == "rule":
            # Rules go to .claude/rules/<name>.md with optional frontmatter
            fields = {}
            if fm.globs:
                fields["paths"] = fm.globs
            frontmatter = self._render_frontmatter(fields)
            content = f"{frontmatter}\n\n{skill.body}\n" if frontmatter else f"{skill.body}\n"
        else:
            # Skills go to .claude/skills/<name>/SKILL.md
            fields = {"name": fm.name, "description": f'"{fm.description}"'}
            if fm.globs:
                fields["paths"] = fm.globs
            if fm.allowed_tools:
                fields["allowed-tools"] = fm.allowed_tools
            if fm.activation == "manual":
                fields["disable-model-invocation"] = True

            frontmatter = self._render_frontmatter(fields)
            content = f"{frontmatter}\n\n{skill.body}\n"

        return TranspileResult(
            output_path=self.get_output_path(skill, project_root),
            content=content,
            warnings=warnings,
        )

    def get_output_path(self, skill: SkillConfig, project_root: Path) -> Path:
        if skill.skill_type == "rule":
            return project_root / ".claude" / "rules" / f"{skill.name}.md"
        return project_root / ".claude" / "skills" / skill.name / "SKILL.md"

    def get_collision_paths(self, skill: SkillConfig, project_root: Path) -> List[Path]:
        # Claude Code resolves the same name across skills/, commands/ and
        # agents/ surfaces. A hand-written slash command or agent with the
        # same name shadows the synced skill, so flag it for the user.
        return [
            project_root / ".claude" / "commands" / f"{skill.name}.md",
            project_root / ".claude" / "agents" / f"{skill.name}.md",
        ]

    # --- Lifecycle hooks ----------------------------------------------------
    #
    # Claude Code reads hook entries from ``~/.claude/settings.json`` under
    # ``.hooks.<EventName>``. Each entry has the shape:
    #     {"matcher": "*", "hooks": [{"type": "command", "command": "<path>"}]}
    # Multiple entries per event are allowed; we identify our additions by
    # the absolute command path (which embeds the skill name in its segments,
    # so cross-skill collisions are not possible).

    def _settings_path(self, output_root: Path) -> Path:
        return output_root / ".claude" / "settings.json"

    def _load_settings(self, output_root: Path) -> dict:
        path = self._settings_path(output_root)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            # Treat an unreadable settings.json as empty rather than crashing
            # mid-sync; the user will see other warnings on this client.
            return {}

    def _write_settings(self, output_root: Path, settings: dict) -> None:
        path = self._settings_path(output_root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(settings, indent=2) + "\n")

    def install_hooks(self, skill: SkillConfig, output_root: Path) -> List[str]:
        hooks = skill.frontmatter.hooks
        if not hooks:
            return []

        settings = self._load_settings(output_root)
        settings.setdefault("hooks", {})

        skill_dir = output_root / ".claude" / "skills" / skill.name
        installed: List[str] = []

        for event, hook in hooks.items():
            # Resolve the hook command to its absolute path under the synced
            # skill output. The asset-copy pass has already placed the file
            # there; we just point Claude Code at it.
            cmd = str((skill_dir / hook.command).resolve())

            existing_entries = settings["hooks"].setdefault(event, [])

            # Idempotent: add a new entry only when no existing entry already
            # registers this exact command path. Pre-existing entries for
            # unrelated commands are preserved.
            already_registered = any(
                any(h.get("command") == cmd for h in entry.get("hooks", []))
                for entry in existing_entries
            )
            if not already_registered:
                existing_entries.append({
                    "matcher": hook.matcher,
                    "hooks": [{"type": hook.type, "command": cmd}],
                })

            # Ensure the target script has the executable bit (skill assets
            # are copied with shutil.copy2 which preserves mode, but a skill
            # author may forget to chmod the canonical -- be defensive).
            target = Path(cmd)
            if target.exists():
                mode = target.stat().st_mode
                if mode & 0o111 == 0:
                    target.chmod(mode | 0o755)

            installed.append(cmd)

        self._write_settings(output_root, settings)
        return installed

    def uninstall_hooks(self, output_root: Path, hook_ids: List[str]) -> List[str]:
        if not hook_ids:
            return []

        settings = self._load_settings(output_root)
        hooks_section = settings.get("hooks")
        if not hooks_section:
            return []

        hook_id_set = set(hook_ids)
        removed: List[str] = []

        for event in list(hooks_section.keys()):
            kept_entries = []
            for entry in hooks_section[event]:
                filtered = []
                for h in entry.get("hooks", []):
                    if h.get("command") in hook_id_set:
                        removed.append(h["command"])
                    else:
                        filtered.append(h)
                if filtered:
                    entry["hooks"] = filtered
                    kept_entries.append(entry)
                # entry dropped entirely when its hooks list is now empty
            if kept_entries:
                hooks_section[event] = kept_entries
            else:
                del hooks_section[event]

        # Drop an empty top-level "hooks" key so settings.json stays tidy
        if not hooks_section:
            settings.pop("hooks", None)

        self._write_settings(output_root, settings)
        return removed
