"""Tests for skill lifecycle hooks (feat/skill-lifecycle-hooks)."""

import json
import os
from pathlib import Path

import pytest

from mcpm.skills.parser import parse_skill_file
from mcpm.skills.schema import LockFileEntry, SkillConfig, SkillFrontmatter, SkillHook
from mcpm.skills.transpiler import BaseSkillTranspiler, sync_skills
from mcpm.skills.transpilers.claude_code import ClaudeCodeTranspiler

from .conftest import SAMPLE_SKILL_MD


SKILL_WITH_HOOK_MD = """---
name: with-hook
description: A skill that declares a PreCompact hook.
activation: agent
hooks:
  PreCompact:
    command: scripts/precompact.sh
    matcher: "*"
---

# With Hook

A skill that uses a lifecycle hook to run a script before context compaction.
"""


def _write_skill_with_hook(tmp_path: Path, name: str = "with-hook", *, script_content: str = "#!/bin/bash\necho hi\n") -> Path:
    """Synthesise a SKILL.md plus a scripts/precompact.sh that lives where the hook points."""
    skill_dir = tmp_path / "skills" / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "scripts").mkdir()
    script = skill_dir / "scripts" / "precompact.sh"
    script.write_text(script_content)
    os.chmod(script, 0o755)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(SKILL_WITH_HOOK_MD.replace("name: with-hook", f"name: {name}"))
    return skill_file


# --- Schema / parser ---------------------------------------------------------


class TestHookSchema:
    """SkillHook + frontmatter parsing."""

    def test010_hook_minimal_constructs(self):
        h = SkillHook(command="scripts/foo.sh")
        assert h.command == "scripts/foo.sh"
        assert h.matcher == "*"
        assert h.type == "command"

    def test011_hook_explicit_fields(self):
        h = SkillHook(command="scripts/foo.sh", matcher="src/**/*.py", type="command")
        assert h.matcher == "src/**/*.py"
        assert h.type == "command"

    def test012_hook_rejects_empty_command(self):
        with pytest.raises(ValueError):
            SkillHook(command="")
        with pytest.raises(ValueError):
            SkillHook(command="   ")

    def test013_hook_rejects_absolute_command_path(self):
        with pytest.raises(ValueError):
            SkillHook(command="/etc/passwd")
        with pytest.raises(ValueError):
            SkillHook(command="~/.bashrc")

    def test020_frontmatter_parses_hooks_block(self):
        fm = SkillFrontmatter(
            name="x",
            description="y",
            hooks={"PreCompact": {"command": "scripts/foo.sh"}},
        )
        assert fm.hooks is not None
        assert "PreCompact" in fm.hooks
        assert fm.hooks["PreCompact"].command == "scripts/foo.sh"

    def test021_frontmatter_hooks_default_none(self):
        fm = SkillFrontmatter(name="x", description="y")
        assert fm.hooks is None


class TestParserHookValidation:
    """parse_skill_file validates hook targets at parse time."""

    def test010_parses_skill_with_existing_hook(self, tmp_path):
        skill_file = _write_skill_with_hook(tmp_path)
        skill = parse_skill_file(skill_file)
        assert skill.frontmatter.hooks is not None
        assert "PreCompact" in skill.frontmatter.hooks

    def test020_rejects_missing_hook_command(self, tmp_path):
        skill_dir = tmp_path / "skills" / "broken"
        skill_dir.mkdir(parents=True)
        # Note: scripts/precompact.sh does NOT exist
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(SKILL_WITH_HOOK_MD.replace("name: with-hook", "name: broken"))
        with pytest.raises(ValueError, match="not found"):
            parse_skill_file(skill_file)

    def test021_rejects_hook_command_outside_skill_dir(self, tmp_path):
        skill_dir = tmp_path / "skills" / "escape"
        skill_dir.mkdir(parents=True)
        skill_file = skill_dir / "SKILL.md"
        # Try to point at a file via parent traversal
        escape_md = SKILL_WITH_HOOK_MD.replace("name: with-hook", "name: escape").replace(
            "scripts/precompact.sh", "../../etc/passwd"
        )
        skill_file.write_text(escape_md)
        with pytest.raises(ValueError, match="stay inside the skill directory"):
            parse_skill_file(skill_file)


# --- Base transpiler default behaviour --------------------------------------


class TestBaseTranspilerInstallHooks:
    """Default install_hooks() implementation: warn + no-op."""

    class _DummyTranspiler(BaseSkillTranspiler):
        client_key = "dummy-no-hooks"
        display_name = "Dummy"

        def transpile(self, skill, project_root):
            from mcpm.skills.schema import TranspileResult
            return TranspileResult(output_path=project_root / "dummy.md", content="x")

        def get_output_path(self, skill, project_root):
            return project_root / "dummy.md"

    def test010_install_hooks_empty_when_no_hooks_declared(self, tmp_path):
        skill = SkillConfig(
            frontmatter=SkillFrontmatter(name="x", description="y"),
            body="",
            source_path=tmp_path / "SKILL.md",
            skill_type="skill",
        )
        result = self._DummyTranspiler().install_hooks(skill, tmp_path)
        assert result == []

    def test020_install_hooks_warns_when_unsupported(self, tmp_path, caplog):
        skill = SkillConfig(
            frontmatter=SkillFrontmatter(
                name="x",
                description="y",
                hooks={"PreCompact": SkillHook(command="scripts/foo.sh")},
            ),
            body="",
            source_path=tmp_path / "SKILL.md",
            skill_type="skill",
        )
        import logging
        with caplog.at_level(logging.WARNING, logger="mcpm.skills.transpiler"):
            result = self._DummyTranspiler().install_hooks(skill, tmp_path)
        assert result == []
        assert any("dummy-no-hooks" in r.message and "does not support hooks" in r.message
                   for r in caplog.records)

    def test030_uninstall_hooks_default_is_noop(self, tmp_path):
        result = self._DummyTranspiler().uninstall_hooks(tmp_path, ["/abs/path/to/something"])
        assert result == []


# --- Claude Code transpiler hook install / uninstall ------------------------


class TestClaudeCodeHookInstall:
    """ClaudeCodeTranspiler.install_hooks writes settings.json correctly."""

    def _skill_with_hook(self, tmp_path: Path, name: str = "with-hook") -> SkillConfig:
        """Build a real SkillConfig and place its target script inside the synced
        skill output dir so the transpiler resolves a real file."""
        skill_file = _write_skill_with_hook(tmp_path, name=name)
        skill = parse_skill_file(skill_file)
        # Pre-place the script at the synced location so chmod target exists
        synced_script = tmp_path / ".claude" / "skills" / name / "scripts" / "precompact.sh"
        synced_script.parent.mkdir(parents=True)
        synced_script.write_text("#!/bin/bash\necho hi\n")
        os.chmod(synced_script, 0o755)
        return skill

    def test010_install_writes_settings_json(self, tmp_path):
        skill = self._skill_with_hook(tmp_path)
        installed = ClaudeCodeTranspiler().install_hooks(skill, tmp_path)
        assert len(installed) == 1
        assert installed[0].endswith(".claude/skills/with-hook/scripts/precompact.sh")

        settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
        assert "hooks" in settings
        assert "PreCompact" in settings["hooks"]
        entries = settings["hooks"]["PreCompact"]
        assert len(entries) == 1
        assert entries[0]["matcher"] == "*"
        assert entries[0]["hooks"][0]["type"] == "command"
        assert entries[0]["hooks"][0]["command"] == installed[0]

    def test020_install_is_idempotent(self, tmp_path):
        skill = self._skill_with_hook(tmp_path)
        t = ClaudeCodeTranspiler()
        t.install_hooks(skill, tmp_path)
        t.install_hooks(skill, tmp_path)
        t.install_hooks(skill, tmp_path)
        settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
        assert len(settings["hooks"]["PreCompact"]) == 1

    def test030_install_preserves_pre_existing_unrelated_hook(self, tmp_path):
        # User has a manually-added hook entry that mcpm did NOT create
        settings_path = tmp_path / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        existing_cmd = "/usr/local/bin/manual-pre-compact"
        settings_path.write_text(json.dumps({
            "hooks": {
                "PreCompact": [
                    {"matcher": "*", "hooks": [{"type": "command", "command": existing_cmd}]}
                ]
            }
        }))

        skill = self._skill_with_hook(tmp_path)
        ClaudeCodeTranspiler().install_hooks(skill, tmp_path)
        settings = json.loads(settings_path.read_text())
        all_cmds = [h["command"]
                    for entry in settings["hooks"]["PreCompact"]
                    for h in entry["hooks"]]
        assert existing_cmd in all_cmds
        assert any(c.endswith("/precompact.sh") for c in all_cmds)

    def test040_install_chmods_target_script(self, tmp_path):
        skill = self._skill_with_hook(tmp_path)
        # Strip exec bit from the synced target to verify chmod restores it
        synced_script = tmp_path / ".claude" / "skills" / "with-hook" / "scripts" / "precompact.sh"
        os.chmod(synced_script, 0o644)
        assert os.stat(synced_script).st_mode & 0o111 == 0
        ClaudeCodeTranspiler().install_hooks(skill, tmp_path)
        assert os.stat(synced_script).st_mode & 0o111 != 0


class TestClaudeCodeHookUninstall:
    """ClaudeCodeTranspiler.uninstall_hooks removes only matching entries."""

    def _install_and_get_id(self, tmp_path: Path):
        skill_file = _write_skill_with_hook(tmp_path)
        skill = parse_skill_file(skill_file)
        synced_script = tmp_path / ".claude" / "skills" / "with-hook" / "scripts" / "precompact.sh"
        synced_script.parent.mkdir(parents=True)
        synced_script.write_text("#!/bin/bash\n")
        os.chmod(synced_script, 0o755)
        ids = ClaudeCodeTranspiler().install_hooks(skill, tmp_path)
        return tmp_path, ids

    def test010_uninstall_removes_matching_entry(self, tmp_path):
        root, ids = self._install_and_get_id(tmp_path)
        removed = ClaudeCodeTranspiler().uninstall_hooks(root, ids)
        assert removed == ids
        settings = json.loads((root / ".claude" / "settings.json").read_text())
        # Either the hooks section is gone, or PreCompact is gone
        assert "hooks" not in settings or "PreCompact" not in settings.get("hooks", {})

    def test020_uninstall_removes_event_when_last_entry_gone(self, tmp_path):
        root, ids = self._install_and_get_id(tmp_path)
        ClaudeCodeTranspiler().uninstall_hooks(root, ids)
        settings = json.loads((root / ".claude" / "settings.json").read_text())
        # whole top-level "hooks" should be gone since we cleaned the only event
        assert "hooks" not in settings

    def test030_uninstall_leaves_unrelated_entries_intact(self, tmp_path):
        root, ids = self._install_and_get_id(tmp_path)
        # Add another unrelated hook entry
        settings_path = root / ".claude" / "settings.json"
        settings = json.loads(settings_path.read_text())
        unrelated = "/usr/local/bin/unrelated"
        settings["hooks"]["PreCompact"].append({
            "matcher": "*",
            "hooks": [{"type": "command", "command": unrelated}],
        })
        settings_path.write_text(json.dumps(settings))

        ClaudeCodeTranspiler().uninstall_hooks(root, ids)
        result = json.loads(settings_path.read_text())
        all_cmds = [h["command"]
                    for entry in result["hooks"]["PreCompact"]
                    for h in entry["hooks"]]
        assert unrelated in all_cmds
        assert not any(c.endswith("/precompact.sh") for c in all_cmds)

    def test040_uninstall_on_missing_settings_is_noop(self, tmp_path):
        # No settings.json at all
        result = ClaudeCodeTranspiler().uninstall_hooks(tmp_path, ["/some/abs/path.sh"])
        assert result == []

    def test050_uninstall_with_empty_id_list_is_noop(self, tmp_path):
        _ = self._install_and_get_id(tmp_path)
        result = ClaudeCodeTranspiler().uninstall_hooks(tmp_path, [])
        assert result == []


# --- Lockfile entry + end-to-end via sync_skills ----------------------------


class TestLockFileEntryHooks:
    def test010_entry_default_is_empty_dict(self):
        e = LockFileEntry(hash="sha256:abc")
        assert e.hooks_installed == {}

    def test020_entry_round_trips_through_pydantic(self):
        e = LockFileEntry(hash="sha256:abc", hooks_installed={"claude-code": ["/abs/path.sh"]})
        assert e.hooks_installed == {"claude-code": ["/abs/path.sh"]}


class TestSyncSkillsHooksIntegration:
    """End-to-end: sync a skill with hooks and verify lockfile + settings.json."""

    def test010_sync_records_hooks_in_lockfile_and_writes_settings(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MCPM_NON_INTERACTIVE", "true")
        repo = tmp_path / "skills-repo"
        repo.mkdir()
        (repo / "mcpm-skills.yaml").write_text("name: t\n")
        skill_file = _write_skill_with_hook(repo, name="hooked")
        skill = parse_skill_file(skill_file)

        result = sync_skills([skill], repo, client_keys=["claude-code"])

        entry = result.lockfile.skills["hooked"]
        assert "claude-code" in entry.hooks_installed
        assert len(entry.hooks_installed["claude-code"]) == 1

        settings = json.loads((repo / ".claude" / "settings.json").read_text())
        assert "PreCompact" in settings["hooks"]
