"""Tests for mcpm.cc.state -- read-only Claude Code plugin state readers."""

import json

from mcpm.cc import state


def _write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


def test_claude_root_honors_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    assert state.claude_root() == tmp_path


def test_claude_root_override_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/should/not/be/used")
    assert state.claude_root(tmp_path) == tmp_path


def test_read_known_marketplaces_keyed_by_name(tmp_path):
    _write(
        tmp_path / "plugins" / "known_marketplaces.json",
        {
            "official": {
                "source": {"source": "github", "repo": "anthropics/claude-plugins-official"},
                "installLocation": str(tmp_path / "plugins" / "marketplaces" / "official"),
                "lastUpdated": "2026-06-15T09:11:09.521Z",
            }
        },
    )
    result = state.read_known_marketplaces(tmp_path)
    assert "official" in result
    assert result["official"]["source"]["repo"] == "anthropics/claude-plugins-official"


def test_read_known_marketplaces_missing_file(tmp_path):
    assert state.read_known_marketplaces(tmp_path) == {}


def test_read_known_marketplaces_malformed(tmp_path):
    path = tmp_path / "plugins" / "known_marketplaces.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ not json", encoding="utf-8")
    assert state.read_known_marketplaces(tmp_path) == {}


def test_read_blocklist_and_ids(tmp_path):
    _write(
        tmp_path / "plugins" / "blocklist.json",
        {
            "fetchedAt": "2026-04-10T06:58:44.250Z",
            "plugins": [
                {"plugin": "code-review@official", "reason": "test"},
                {"plugin": "fizz@testmkt", "reason": "security"},
            ],
        },
    )
    assert len(state.read_blocklist(tmp_path)) == 2
    assert state.blocked_plugin_ids(tmp_path) == {"code-review@official", "fizz@testmkt"}


def test_read_settings_plugins(tmp_path):
    _write(
        tmp_path / "settings.json",
        {
            "enabledPlugins": {"foo@official": True, "bar@official": False},
            "extraKnownMarketplaces": {"team": {"source": {"source": "github", "repo": "team/plugins"}}},
        },
    )
    enabled, extra = state.read_settings_plugins(tmp_path)
    assert enabled == {"foo@official": True, "bar@official": False}
    assert "team" in extra


def test_read_settings_plugins_missing(tmp_path):
    assert state.read_settings_plugins(tmp_path) == ({}, {})


def test_read_marketplace_catalog_versions(tmp_path):
    location = tmp_path / "plugins" / "marketplaces" / "official"
    _write(
        tmp_path / "plugins" / "known_marketplaces.json",
        {"official": {"source": {}, "installLocation": str(location)}},
    )
    _write(
        location / ".claude-plugin" / "marketplace.json",
        {
            "name": "official",
            "plugins": [
                {"name": "explicit", "version": "1.2.3"},
                {"name": "pinned", "source": {"sha": "bc781f96be8ce17a2972e8a9a3ef38b1ca7e8cc4"}},
                {"name": "branch", "source": {"ref": "main"}},
                {"name": "noversion", "source": {}},
            ],
        },
    )
    versions = state.read_marketplace_catalog_versions(tmp_path)
    assert versions[("official", "explicit")] == "1.2.3"
    assert versions[("official", "pinned")] == "bc781f96be8c"  # short sha
    assert versions[("official", "branch")] == "main"
    assert versions[("official", "noversion")] is None
