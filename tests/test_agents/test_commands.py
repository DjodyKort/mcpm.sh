"""Tests for agents CLI commands."""

import json

import pytest
from click.testing import CliRunner

from mcpm.commands.agents import agents
from mcpm.skills.config import SkillsConfigManager
from mcpm.skills.schema import LockFile, LockFileEntry


@pytest.fixture
def runner():
    return CliRunner()


class TestAddCommand:
    def test_add_agent(self, runner, tmp_path):
        (tmp_path / "agents").mkdir()
        result = runner.invoke(agents, ["add", "my-agent", "--path", str(tmp_path)])
        assert result.exit_code == 0
        assert "created" in result.output.lower()
        assert (tmp_path / "agents" / "my-agent" / "AGENT.md").exists()

    def test_add_invalid_name(self, runner, tmp_path):
        result = runner.invoke(agents, ["add", "Invalid-Name", "--path", str(tmp_path)])
        assert "invalid" in result.output.lower() or "error" in result.output.lower()

    def test_add_duplicate(self, runner, tmp_path):
        (tmp_path / "agents" / "existing").mkdir(parents=True)
        result = runner.invoke(agents, ["add", "existing", "--path", str(tmp_path)])
        assert "already exists" in result.output.lower()


class TestListCommand:
    def test_list_agents(self, runner, agents_repo):
        result = runner.invoke(agents, ["ls", "--path", str(agents_repo)])
        assert result.exit_code == 0
        assert "code-reviewer" in result.output
        assert "simple-agent" in result.output

    def test_list_empty(self, runner, tmp_path):
        result = runner.invoke(agents, ["ls", "--path", str(tmp_path)])
        assert "no agents" in result.output.lower() or "no skills" in result.output.lower()


class TestSyncCommand:
    def test_sync_dry_run(self, runner, agents_repo):
        result = runner.invoke(agents, ["sync", "--dry-run", "--path", str(agents_repo)])
        assert result.exit_code == 0
        assert "dry run" in result.output.lower()

    def test_sync_creates_files(self, runner, agents_repo):
        result = runner.invoke(agents, ["sync", "--path", str(agents_repo)])
        assert result.exit_code == 0
        assert "synced" in result.output.lower()
        # Check Claude Code output
        assert (agents_repo / ".claude" / "agents" / "code-reviewer.md").exists()
        # Check Cursor output
        assert (agents_repo / ".cursor" / "agents" / "code-reviewer.md").exists()
        # Check Codex TOML output
        assert (agents_repo / ".codex" / "agents" / "code-reviewer.toml").exists()
        # Check Copilot .agent.md output
        assert (agents_repo / ".github" / "agents" / "code-reviewer.agent.md").exists()
        # Check Roo Code .roomodes output
        assert (agents_repo / ".roomodes").exists()

    def test_sync_specific_client(self, runner, agents_repo):
        result = runner.invoke(agents, ["sync", "--client", "claude-code", "--path", str(agents_repo)])
        assert result.exit_code == 0
        assert (agents_repo / ".claude" / "agents" / "code-reviewer.md").exists()
        assert not (agents_repo / ".cursor" / "agents" / "code-reviewer.md").exists()

    def test_codex_toml_content(self, runner, agents_repo):
        runner.invoke(agents, ["sync", "--client", "codex-cli", "--path", str(agents_repo)])
        toml_file = agents_repo / ".codex" / "agents" / "code-reviewer.toml"
        content = toml_file.read_text()
        assert 'name = "code-reviewer"' in content
        assert 'developer_instructions = """' in content

    def test_sync_global_writes_to_home(self, runner, agents_repo, tmp_path, monkeypatch):
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        monkeypatch.setenv("HOME", str(home_dir))
        result = runner.invoke(agents, ["sync", "--global", "--path", str(agents_repo)])
        assert result.exit_code == 0
        assert (home_dir / ".claude" / "agents" / "code-reviewer.md").exists()

    def test_sync_global_skips_project_only(self, runner, agents_repo, tmp_path, monkeypatch):
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        monkeypatch.setenv("HOME", str(home_dir))
        result = runner.invoke(agents, ["sync", "--global", "--path", str(agents_repo)])
        assert result.exit_code == 0
        assert not (home_dir / ".github").exists()
        assert not (home_dir / ".roomodes").exists()

    def test_sync_global_lockfile_location(self, runner, agents_repo, tmp_path, monkeypatch):
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        monkeypatch.setenv("HOME", str(home_dir))
        result = runner.invoke(agents, ["sync", "--global", "--path", str(agents_repo)])
        assert result.exit_code == 0
        lock_path = home_dir / ".config" / "mcpm" / "mcpm-skills.lock"
        assert lock_path.exists()
        data = json.loads(lock_path.read_text(encoding="utf-8"))
        assert "code-reviewer" in data["agents"]
        assert "simple-agent" in data["agents"]

    def test_sync_global_preserves_skills_section(self, runner, agents_repo, tmp_path, monkeypatch):
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        monkeypatch.setenv("HOME", str(home_dir))

        config_dir = home_dir / ".config" / "mcpm"
        config_dir.mkdir(parents=True)
        seeded = LockFile.create_now()
        seeded.skills["some-skill"] = LockFileEntry(hash="sha256:deadbeef")
        SkillsConfigManager(project_root=config_dir).save_lockfile(seeded)

        result = runner.invoke(agents, ["sync", "--global", "--path", str(agents_repo)])
        assert result.exit_code == 0

        data = json.loads((config_dir / "mcpm-skills.lock").read_text(encoding="utf-8"))
        assert "some-skill" in data["skills"]
        assert "code-reviewer" in data["agents"]


class TestCleanCommand:
    def test_clean_removes_files(self, runner, agents_repo):
        runner.invoke(agents, ["sync", "--path", str(agents_repo)])
        assert (agents_repo / ".claude" / "agents" / "code-reviewer.md").exists()
        assert (agents_repo / ".roomodes").exists()

        result = runner.invoke(agents, ["clean", "--path", str(agents_repo)])
        assert result.exit_code == 0
        assert "cleaned" in result.output.lower()
        assert not (agents_repo / ".claude" / "agents" / "code-reviewer.md").exists()
        assert not (agents_repo / ".cursor" / "agents" / "code-reviewer.md").exists()
        assert not (agents_repo / ".codex" / "agents" / "code-reviewer.toml").exists()
        assert not (agents_repo / ".github" / "agents" / "code-reviewer.agent.md").exists()

    def test_clean_no_lockfile(self, runner, tmp_path):
        result = runner.invoke(agents, ["clean", "--path", str(tmp_path)])
        assert result.exit_code == 0
        assert "no lockfile" in result.output.lower()


class TestLintCommand:
    def test_lint_valid(self, runner, agents_repo):
        result = runner.invoke(agents, ["lint", "--path", str(agents_repo)])
        assert result.exit_code == 0

    def test_lint_invalid(self, runner, tmp_path):
        # Need a skills repo marker for find_skills_repo to work
        (tmp_path / "skills").mkdir()
        agent_dir = tmp_path / "agents" / "bad-agent"
        agent_dir.mkdir(parents=True)
        (agent_dir / "AGENT.md").write_text('---\nname: wrong-name\ndescription: "Mismatch."\n---\n')
        result = runner.invoke(agents, ["lint", "--path", str(tmp_path)])
        assert "does not match" in result.output
