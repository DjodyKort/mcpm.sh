"""Tests for skill asset subdirectory copy (modules/, reference/, etc.).

When a skill uses progressive disclosure (slim SKILL.md plus adjacent module
or reference files), those adjacent files must be transpiled alongside the
SKILL.md. Otherwise the LLM following references in SKILL.md hits missing
files in the synced output.
"""

from pathlib import Path

from mcpm.skills.parser import parse_skill_file
from mcpm.skills.transpiler import (
    SKILL_ASSET_DIRS,
    SKILL_ASSET_EXTENSIONS,
    _copy_skill_assets,
    compute_skill_hash,
    sync_skills,
)

from .conftest import SAMPLE_SKILL_MD


def _make_skill_with_assets(tmp_path, name, asset_files=None):
    """Create a skill at tmp_path/skills/<name>/ with optional asset subdirs.

    asset_files is a dict like {"modules/foo.md": "content", "reference/bar.md": "content"}.
    """
    skill_dir = tmp_path / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file = skill_dir / "SKILL.md"
    body = SAMPLE_SKILL_MD.replace("name: code-review", f"name: {name}")
    skill_file.write_text(body)
    for rel_path, content in (asset_files or {}).items():
        target = skill_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    return parse_skill_file(skill_file)


class TestCopySkillAssets:
    """Direct tests for the _copy_skill_assets helper."""

    def test010_no_subdirs_returns_empty(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "SKILL.md").write_text("# skill")
        dst = tmp_path / "dst"
        dst.mkdir()
        result = _copy_skill_assets(src, dst, output_root=tmp_path)
        assert result == []
        assert list(dst.iterdir()) == []

    def test020_modules_subdir_copied(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "SKILL.md").write_text("# skill")
        (src / "modules").mkdir()
        (src / "modules" / "a.md").write_text("module a")
        (src / "modules" / "b.md").write_text("module b")
        dst = tmp_path / "dst"
        dst.mkdir()
        result = _copy_skill_assets(src, dst, output_root=tmp_path)
        assert len(result) == 2
        assert (dst / "modules" / "a.md").read_text() == "module a"
        assert (dst / "modules" / "b.md").read_text() == "module b"

    def test030_all_whitelisted_subdirs_copied(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "SKILL.md").write_text("# skill")
        for subdir in SKILL_ASSET_DIRS:
            (src / subdir).mkdir()
            (src / subdir / "x.md").write_text(f"{subdir} content")
        dst = tmp_path / "dst"
        dst.mkdir()
        result = _copy_skill_assets(src, dst, output_root=tmp_path)
        assert len(result) == len(SKILL_ASSET_DIRS)
        for subdir in SKILL_ASSET_DIRS:
            assert (dst / subdir / "x.md").exists()

    def test040_non_whitelisted_subdir_skipped(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "SKILL.md").write_text("# skill")
        # docs/ is intentionally NOT in SKILL_ASSET_DIRS
        (src / "docs").mkdir()
        (src / "docs" / "design.md").write_text("design notes")
        (src / "modules").mkdir()
        (src / "modules" / "y.md").write_text("module y")
        dst = tmp_path / "dst"
        dst.mkdir()
        result = _copy_skill_assets(src, dst, output_root=tmp_path)
        assert len(result) == 1
        assert (dst / "modules" / "y.md").exists()
        assert not (dst / "docs").exists()

    def test050_disallowed_extension_skipped(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "SKILL.md").write_text("# skill")
        (src / "modules").mkdir()
        (src / "modules" / "a.md").write_text("ok")
        (src / "modules" / "swap.swp").write_text("editor swap, not real content")
        (src / "modules" / "ignored.pyc").write_text("compiled python")
        dst = tmp_path / "dst"
        dst.mkdir()
        result = _copy_skill_assets(src, dst, output_root=tmp_path)
        assert len(result) == 1
        assert (dst / "modules" / "a.md").exists()
        assert not (dst / "modules" / "swap.swp").exists()

    def test060_nested_subdir_files_preserved(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "SKILL.md").write_text("# skill")
        (src / "modules" / "category").mkdir(parents=True)
        (src / "modules" / "category" / "deep.md").write_text("nested")
        dst = tmp_path / "dst"
        dst.mkdir()
        result = _copy_skill_assets(src, dst, output_root=tmp_path)
        assert len(result) == 1
        assert (dst / "modules" / "category" / "deep.md").read_text() == "nested"

    def test070_returns_paths_relative_to_output_root(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "SKILL.md").write_text("# skill")
        (src / "reference").mkdir()
        (src / "reference" / "guide.md").write_text("guide")
        dst = tmp_path / "out" / "client" / "src"
        dst.mkdir(parents=True)
        output_root = tmp_path / "out"
        result = _copy_skill_assets(src, dst, output_root=output_root)
        assert result == ["client/src/reference/guide.md"]


class TestSyncSkillsAssetIntegration:
    """End-to-end: sync a skill with asset subdirs and verify output."""

    def test010_sync_writes_modules_alongside_skill(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MCPM_NON_INTERACTIVE", "true")
        repo = tmp_path / "skills-repo"
        repo.mkdir()
        (repo / "mcpm-skills.yaml").write_text("name: t\n")
        (repo / "skills").mkdir()
        skill = _make_skill_with_assets(
            repo,
            "modular-skill",
            asset_files={
                "modules/intro.md": "intro module",
                "modules/advanced.md": "advanced module",
                "reference/api.md": "api reference",
                "templates/base.md": "template content",
            },
        )

        result = sync_skills([skill], repo, client_keys=["claude-code"])

        skill_dir = repo / ".claude" / "skills" / "modular-skill"
        assert (skill_dir / "SKILL.md").exists()
        assert (skill_dir / "modules" / "intro.md").read_text() == "intro module"
        assert (skill_dir / "modules" / "advanced.md").read_text() == "advanced module"
        assert (skill_dir / "reference" / "api.md").read_text() == "api reference"
        assert (skill_dir / "templates" / "base.md").read_text() == "template content"

        # All asset files plus SKILL.md must be tracked in the lockfile entry,
        # so future syncs can clean them up if the skill is renamed.
        entry = result.lockfile.skills["modular-skill"]
        synced = entry.output_files["claude-code"]
        assert any(p.endswith("SKILL.md") for p in synced)
        assert any(p.endswith("modules/intro.md") for p in synced)
        assert any(p.endswith("reference/api.md") for p in synced)

    def test020_sync_skill_without_assets_unchanged(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MCPM_NON_INTERACTIVE", "true")
        repo = tmp_path / "skills-repo"
        repo.mkdir()
        (repo / "mcpm-skills.yaml").write_text("name: t\n")
        (repo / "skills").mkdir()
        skill = _make_skill_with_assets(repo, "plain-skill")

        result = sync_skills([skill], repo, client_keys=["claude-code"])

        skill_dir = repo / ".claude" / "skills" / "plain-skill"
        assert (skill_dir / "SKILL.md").exists()
        assert list(skill_dir.iterdir()) == [skill_dir / "SKILL.md"]
        entry = result.lockfile.skills["plain-skill"]
        assert len(entry.output_files["claude-code"]) == 1

    def test025_asset_drift_detected_in_lockfile_hash(self, tmp_path, monkeypatch):
        """Editing a module file changes the skill hash so status/diff detect
        the drift. Without asset-aware hashing, asset edits would silently
        fail to trigger a re-sync.
        """
        monkeypatch.setenv("MCPM_NON_INTERACTIVE", "true")
        repo = tmp_path / "skills-repo"
        repo.mkdir()
        (repo / "mcpm-skills.yaml").write_text("name: t\n")
        (repo / "skills").mkdir()
        skill_v1 = _make_skill_with_assets(
            repo,
            "drift-test",
            asset_files={"modules/m.md": "version one"},
        )
        hash_v1 = compute_skill_hash(skill_v1)

        # Edit the module file without touching SKILL.md
        (repo / "skills" / "drift-test" / "modules" / "m.md").write_text("version two")
        skill_v2 = parse_skill_file(repo / "skills" / "drift-test" / "SKILL.md")
        hash_v2 = compute_skill_hash(skill_v2)

        assert hash_v1 != hash_v2, (
            "asset edit must change the skill hash, otherwise drift goes undetected"
        )

    def test026_skill_md_only_change_changes_hash(self, tmp_path):
        """Sanity: editing SKILL.md still changes the hash."""
        repo = tmp_path / "skills-repo"
        repo.mkdir()
        (repo / "mcpm-skills.yaml").write_text("name: t\n")
        (repo / "skills").mkdir()
        skill_v1 = _make_skill_with_assets(repo, "skill-edit-test")
        hash_v1 = compute_skill_hash(skill_v1)

        # Modify SKILL.md
        skill_path = repo / "skills" / "skill-edit-test" / "SKILL.md"
        skill_path.write_text(skill_path.read_text() + "\nadditional content\n")
        skill_v2 = parse_skill_file(skill_path)
        hash_v2 = compute_skill_hash(skill_v2)

        assert hash_v1 != hash_v2

    def test027_unrelated_dir_does_not_affect_hash(self, tmp_path):
        """A non-whitelist subdir (e.g., docs/) is excluded from the hash so
        local notes do not trigger spurious drift.
        """
        repo = tmp_path / "skills-repo"
        repo.mkdir()
        (repo / "mcpm-skills.yaml").write_text("name: t\n")
        (repo / "skills").mkdir()
        skill_v1 = _make_skill_with_assets(repo, "unrelated-test")
        hash_v1 = compute_skill_hash(skill_v1)

        # Add a file in a non-whitelist subdir
        non_whitelist = repo / "skills" / "unrelated-test" / "docs"
        non_whitelist.mkdir()
        (non_whitelist / "design.md").write_text("local design notes")
        skill_v2 = parse_skill_file(repo / "skills" / "unrelated-test" / "SKILL.md")
        hash_v2 = compute_skill_hash(skill_v2)

        assert hash_v1 == hash_v2

    def test030_extension_filter_at_sync_level(self, tmp_path, monkeypatch):
        """A skill with mixed file types in modules/ syncs only the allowed
        extensions, ensuring binary or temp files do not leak into clients.
        """
        monkeypatch.setenv("MCPM_NON_INTERACTIVE", "true")
        repo = tmp_path / "skills-repo"
        repo.mkdir()
        (repo / "mcpm-skills.yaml").write_text("name: t\n")
        (repo / "skills").mkdir()
        skill = _make_skill_with_assets(
            repo,
            "filtered",
            asset_files={
                "modules/keep.md": "kept",
                "modules/skip.swp": "editor swap",
                "modules/skip.pyc": "compiled",
            },
        )

        sync_skills([skill], repo, client_keys=["claude-code"])

        modules_dir = repo / ".claude" / "skills" / "filtered" / "modules"
        assert (modules_dir / "keep.md").exists()
        assert not (modules_dir / "skip.swp").exists()
        assert not (modules_dir / "skip.pyc").exists()
