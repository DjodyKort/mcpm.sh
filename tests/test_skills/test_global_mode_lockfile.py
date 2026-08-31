"""A global skills sync must not wipe the agents/styles lockfile sections.

sync_skills() only ever populates skills/rules -- agents, styles, and
active_styles are owned by other sync paths (agents sync, styles apply).
Starting the lockfile fresh from LockFile.create_now() and saving it
straight over the global lock would silently drop whatever those other
paths had written.
"""

from mcpm.skills.config import SkillsConfigManager
from mcpm.skills.parser import parse_skill_file
from mcpm.skills.schema import LockFile, LockFileEntry
from mcpm.skills.transpiler import sync_skills

from .conftest import SAMPLE_SKILL_MD


def test_global_skills_sync_preserves_agents_section(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    config_dir = home / ".config" / "mcpm"
    config_dir.mkdir(parents=True)
    seeded = LockFile.create_now()
    seeded.agents["code-reviewer"] = LockFileEntry(hash="sha256:deadbeef")
    seeded.styles["dracula"] = LockFileEntry(hash="sha256:cafebabe")
    seeded.active_styles["claude-code"] = "dracula"
    SkillsConfigManager(project_root=config_dir).save_lockfile(seeded)

    skill_dir = tmp_path / "skills" / "code-review"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(SAMPLE_SKILL_MD)
    skill = parse_skill_file(skill_file)

    result = sync_skills([skill], tmp_path, client_keys=["claude-code"], global_mode=True)

    assert "code-reviewer" in result.lockfile.agents
    assert "dracula" in result.lockfile.styles
    assert result.lockfile.active_styles.get("claude-code") == "dracula"
    assert "code-review" in result.lockfile.skills
