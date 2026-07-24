"""Sandbox every filesystem seam per test — the plugin must never touch the
real ~/.claude, ~/.claude.json, ~/.config/mcpm, or ~/.cache during tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch):
    claude_home = tmp_path / "claude-home"
    claude_home.mkdir()
    monkeypatch.setenv("MCPM_CONFIG_DIR", str(tmp_path / "mcpm-config"))
    monkeypatch.setenv("MCPM_CONTEXT_CLAUDE_HOME", str(claude_home))
    monkeypatch.setenv("MCPM_CONTEXT_CLAUDE_JSON", str(tmp_path / "claude.json"))
    monkeypatch.setenv("MCPM_CONTEXT_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MCPM_CONTEXT_CF_DIR", str(tmp_path / "cf-dev-tools"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    return tmp_path


@pytest.fixture
def claude_json(sandbox):
    """A ~/.claude.json with cf legacy + mcpm twins + foreign entries."""
    path = sandbox / "claude.json"
    path.write_text(json.dumps({
        "oauthAccount": {"emailAddress": "test@example.com"},
        "userID": "abc123",
        "hasCompletedOnboarding": True,
        "lastOnboardingVersion": "2.1.41",
        "numStartups": 42,
        "mcpServers": {
            "context7": {"type": "stdio", "command": "npx", "args": ["-y", "@upstash/context7-mcp"]},
            "playwright": {"type": "stdio", "command": "npx", "args": ["-y", "@playwright/mcp"]},
            "mcpm_context7": {"command": "mcpm", "args": ["run", "context7"]},
            "mcpm_playwright": {"command": "mcpm", "args": ["run", "playwright"]},
            "mcpm_odh": {"command": "mcpm", "args": ["run", "odh"]},
            "hand-added": {"command": "my-own-server"},
        },
    }, indent=2))
    return path


@pytest.fixture
def claude_settings(sandbox):
    """A ~/.claude/settings.json shaped like the live one (team + user keys)."""
    path = Path(sandbox / "claude-home" / "settings.json")
    path.write_text(json.dumps({
        "attribution": {"commit": "", "pr": ""},
        "permissions": {
            "allow": ["mcp__codeforward-odoo__get_*", "mcp__codeforward-typst__*"],
            "ask": ["Bash(git push*)"],
        },
        "model": "claude-fable-5[1m]",
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "/x/hook.sh"}]}]},
    }, indent=2))
    return path
