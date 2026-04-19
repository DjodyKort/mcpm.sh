"""Tests for collision detection, resolution, and stale-file cleanup."""

import json
import os
from pathlib import Path

import pytest

from mcpm.skills.collisions import (
    BACKUP_DIR_NAME,
    BACKUP_INDEX_NAME,
    Collision,
    backup_and_remove,
    detect_collisions,
    render_diff,
    resolve_collisions,
    resolve_mode,
)
from mcpm.skills.parser import parse_skill_file
from mcpm.skills.transpiler import sync_skills
from mcpm.skills.transpilers.claude_code import ClaudeCodeTranspiler

from .conftest import SAMPLE_SKILL_MD


def _make_skill(tmp_path, name, content=SAMPLE_SKILL_MD, subdir="skills"):
    skill_dir = tmp_path / subdir / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file = skill_dir / "SKILL.md"
    # Override the name field so each test can use unique names
    body = content.replace("name: code-review", f"name: {name}")
    skill_file.write_text(body)
    return parse_skill_file(skill_file)


class TestResolveMode:
    def test_migrate_true(self):
        assert resolve_mode(migrate=True) == "auto-replace"

    def test_migrate_false(self):
        assert resolve_mode(migrate=False) == "warn-only"

    def test_force_non_interactive(self):
        assert resolve_mode(migrate=None, force_non_interactive=True) == "warn-only"

    def test_env_non_interactive(self, monkeypatch):
        monkeypatch.setenv("MCPM_NON_INTERACTIVE", "true")
        assert resolve_mode(migrate=None) == "warn-only"

    def test_no_tty_falls_back_to_warn(self, monkeypatch):
        # In pytest stdin/stdout aren't TTYs, so default mode is warn-only.
        monkeypatch.delenv("MCPM_NON_INTERACTIVE", raising=False)
        assert resolve_mode(migrate=None) == "warn-only"


class TestClaudeCodeCollisionPaths:
    def test_skill_collision_paths(self, tmp_path):
        skill = _make_skill(tmp_path, "gdocs-new-document")
        transpiler = ClaudeCodeTranspiler()
        paths = transpiler.get_collision_paths(skill, tmp_path)
        assert tmp_path / ".claude" / "commands" / "gdocs-new-document.md" in paths
        assert tmp_path / ".claude" / "agents" / "gdocs-new-document.md" in paths


class TestDetectCollisions:
    def test_finds_existing_command_file(self, tmp_path):
        skill = _make_skill(tmp_path, "gdocs-new-document")
        # Pre-create the colliding command file
        commands_dir = tmp_path / ".claude" / "commands"
        commands_dir.mkdir(parents=True)
        collision_file = commands_dir / "gdocs-new-document.md"
        collision_file.write_text("--- old hand-written slash command ---\n")

        transpilers = {"claude-code": ClaudeCodeTranspiler()}
        collisions = detect_collisions([skill], transpilers, tmp_path)

        assert len(collisions) == 1
        assert collisions[0].skill_name == "gdocs-new-document"
        assert collisions[0].client_key == "claude-code"
        assert collisions[0].collision_path == collision_file

    def test_no_collisions_when_no_files(self, tmp_path):
        skill = _make_skill(tmp_path, "code-review")
        transpilers = {"claude-code": ClaudeCodeTranspiler()}
        assert detect_collisions([skill], transpilers, tmp_path) == []


class TestBackupAndRemove:
    def test_moves_file_and_writes_index(self, tmp_path):
        commands_dir = tmp_path / ".claude" / "commands"
        commands_dir.mkdir(parents=True)
        original = commands_dir / "foo.md"
        original.write_text("hand-written content\n")

        collision = Collision(
            skill_name="foo",
            client_key="claude-code",
            synced_path=tmp_path / ".claude" / "skills" / "foo" / "SKILL.md",
            synced_content="synced content\n",
            collision_path=original,
        )
        backup_path = backup_and_remove(collision, tmp_path)

        assert not original.exists()
        assert backup_path.exists()
        assert backup_path.read_text() == "hand-written content\n"
        assert BACKUP_DIR_NAME in str(backup_path)

        index_path = tmp_path / BACKUP_DIR_NAME / BACKUP_INDEX_NAME
        assert index_path.exists()
        data = json.loads(index_path.read_text())
        assert len(data["backups"]) == 1
        assert data["backups"][0]["skill_name"] == "foo"
        assert data["backups"][0]["original_path"] == str(original)


class TestResolveCollisions:
    def _make_collision(self, tmp_path, name="foo", existing_content="old\n"):
        commands_dir = tmp_path / ".claude" / "commands"
        commands_dir.mkdir(parents=True, exist_ok=True)
        original = commands_dir / f"{name}.md"
        original.write_text(existing_content)
        return Collision(
            skill_name=name,
            client_key="claude-code",
            synced_path=tmp_path / ".claude" / "skills" / name / "SKILL.md",
            synced_content="new\n",
            collision_path=original,
        )

    def test_warn_only_keeps_files(self, tmp_path):
        c = self._make_collision(tmp_path)
        summary = resolve_collisions([c], tmp_path, mode="warn-only")
        assert c.collision_path.exists()
        assert len(summary.kept) == 1
        assert len(summary.replaced) == 0

    def test_auto_replace_moves_files(self, tmp_path):
        c = self._make_collision(tmp_path)
        summary = resolve_collisions([c], tmp_path, mode="auto-replace")
        assert not c.collision_path.exists()
        assert len(summary.replaced) == 1
        assert summary.replaced[0].backup_path is not None
        assert summary.replaced[0].backup_path.exists()

    def test_auto_replace_dry_run_keeps_files(self, tmp_path):
        c = self._make_collision(tmp_path)
        summary = resolve_collisions([c], tmp_path, mode="auto-replace", dry_run=True)
        assert c.collision_path.exists()
        assert summary.resolutions[0].action == "skipped-dry-run"


class TestRenderDiff:
    def test_diff_shows_changes(self, tmp_path):
        commands_dir = tmp_path / ".claude" / "commands"
        commands_dir.mkdir(parents=True)
        original = commands_dir / "foo.md"
        original.write_text("alpha\nbeta\n")
        c = Collision(
            skill_name="foo",
            client_key="claude-code",
            synced_path=tmp_path / "synced",
            synced_content="alpha\ngamma\n",
            collision_path=original,
        )
        diff = render_diff(c)
        assert "-beta" in diff
        assert "+gamma" in diff


class TestSyncSkillsCleanup:
    """End-to-end: sync a skill, rename it, sync again -- old file is removed."""

    def test_rename_cleans_up_old_output(self, tmp_path, monkeypatch):
        # Force non-interactive to avoid prompting in tests.
        monkeypatch.setenv("MCPM_NON_INTERACTIVE", "true")

        repo = tmp_path / "skills-repo"
        repo.mkdir()
        (repo / "mcpm-skills.yaml").write_text("name: t\n")
        (repo / "skills").mkdir()
        original = _make_skill(repo, "foo")

        # First sync: writes ~/.claude/skills/foo/SKILL.md (under repo root in
        # project mode).
        result1 = sync_skills([original], repo, client_keys=["claude-code"])
        from mcpm.skills.config import SkillsConfigManager

        SkillsConfigManager(project_root=repo).save_lockfile(result1.lockfile)
        foo_path = repo / ".claude" / "skills" / "foo" / "SKILL.md"
        assert foo_path.exists()

        # Rename: foo -> bar. Build a new skill in a fresh dir.
        bar = _make_skill(repo, "bar")

        # Second sync: should remove foo and write bar.
        result2 = sync_skills([bar], repo, client_keys=["claude-code"])
        SkillsConfigManager(project_root=repo).save_lockfile(result2.lockfile)

        bar_path = repo / ".claude" / "skills" / "bar" / "SKILL.md"
        assert bar_path.exists(), "new skill should be written"
        assert not foo_path.exists(), "renamed skill's old output should be cleaned up"
        assert any(p == foo_path for p in result2.cleaned)


class TestSyncSkillsCollisionWarnOnly:
    def test_collision_recorded_in_lockfile_warnings(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MCPM_NON_INTERACTIVE", "true")

        repo = tmp_path / "skills-repo"
        repo.mkdir()
        (repo / "mcpm-skills.yaml").write_text("name: t\n")
        (repo / "skills").mkdir()
        skill = _make_skill(repo, "gdocs-new-document")

        # Pre-create a colliding command file under the same project root
        # (since project_root acts as output_root in non-global mode).
        commands_dir = repo / ".claude" / "commands"
        commands_dir.mkdir(parents=True)
        (commands_dir / "gdocs-new-document.md").write_text("old slash command\n")

        result = sync_skills([skill], repo, client_keys=["claude-code"])
        assert (commands_dir / "gdocs-new-document.md").exists(), "warn-only must not delete"

        entry = result.lockfile.skills["gdocs-new-document"]
        assert any("shadowed by existing file" in w for w in entry.warnings)


class TestSyncSkillsCollisionMigrate:
    def test_migrate_replaces_with_backup(self, tmp_path, monkeypatch):
        # --migrate=True overrides any TTY/env detection.
        repo = tmp_path / "skills-repo"
        repo.mkdir()
        (repo / "mcpm-skills.yaml").write_text("name: t\n")
        (repo / "skills").mkdir()
        skill = _make_skill(repo, "gdocs-new-document")

        commands_dir = repo / ".claude" / "commands"
        commands_dir.mkdir(parents=True)
        original = commands_dir / "gdocs-new-document.md"
        original.write_text("old slash command\n")

        result = sync_skills(
            [skill], repo, client_keys=["claude-code"], migrate=True
        )

        assert not original.exists(), "migrate should remove the colliding file"
        backup_index = repo / BACKUP_DIR_NAME / BACKUP_INDEX_NAME
        assert backup_index.exists()
        data = json.loads(backup_index.read_text())
        assert data["backups"][0]["skill_name"] == "gdocs-new-document"
        assert len(result.collision_summary.replaced) == 1


class TestLockfileBackwardCompat:
    def test_old_lockfile_without_output_files_loads(self, tmp_path):
        """An old lockfile (pre-output_files) should load and write cleanly."""
        from mcpm.skills.config import SkillsConfigManager
        from mcpm.skills.schema import LockFile, LockFileEntry

        legacy = {
            "version": 1,
            "synced_at": "2026-04-01T00:00:00+00:00",
            "skills": {
                "foo": {
                    "source": "local",
                    "version": "1.0",
                    "hash": "sha256:abc",
                    "clients_synced": ["claude-code"],
                    "warnings": [],
                    # NOTE: no output_files key
                }
            },
            "rules": {},
            "agents": {},
            "styles": {},
        }
        path = tmp_path / "mcpm-skills.lock"
        path.write_text(json.dumps(legacy))

        manager = SkillsConfigManager(project_root=tmp_path)
        loaded = manager.load_lockfile()
        assert loaded is not None
        assert loaded.skills["foo"].output_files == {}
        # And re-save round-trips fine.
        manager.save_lockfile(loaded)
        re = manager.load_lockfile()
        assert re.skills["foo"].hash == "sha256:abc"
