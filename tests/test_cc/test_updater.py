"""Tests for mcpm.cc.updater -- check/apply logic (no network, no real claude)."""

from mcpm.cc import updater


def _patch_state(monkeypatch, *, installed, catalog=None, enabled=None, blocked=None, refresh=(0, "", "")):
    """Wire updater's collaborators to fixtures."""
    monkeypatch.setattr(updater.claude_cli, "plugin_list_json", lambda: installed)
    monkeypatch.setattr(updater.claude_cli, "marketplace_update", lambda name=None: refresh)
    monkeypatch.setattr(updater.state, "read_marketplace_catalog_versions", lambda: catalog or {})
    monkeypatch.setattr(updater.state, "read_settings_plugins", lambda: (enabled or {}, {}))
    monkeypatch.setattr(updater.state, "blocked_plugin_ids", lambda: set(blocked or []))


def test_check_detects_newer_version(monkeypatch):
    _patch_state(
        monkeypatch,
        installed=[{"name": "foo", "marketplace": "official", "version": "1.0.0"}],
        catalog={("official", "foo"): "2.0.0"},
    )
    result = updater.check_plugin_updates()
    assert result.refresh_error is None
    (check,) = result.checks
    assert check.can_update is True
    assert check.summary == "1.0.0 -> 2.0.0"
    assert check.plugin_id == "foo@official"


def test_check_up_to_date(monkeypatch):
    _patch_state(
        monkeypatch,
        installed=[{"name": "foo", "marketplace": "official", "version": "2.0.0"}],
        catalog={("official", "foo"): "2.0.0"},
    )
    (check,) = updater.check_plugin_updates().checks
    assert check.can_update is False
    assert check.summary == "up to date"


def test_check_version_unknown(monkeypatch):
    _patch_state(
        monkeypatch,
        installed=[{"name": "foo", "marketplace": "official"}],
        catalog={},
    )
    (check,) = updater.check_plugin_updates().checks
    assert check.can_update is False
    assert check.summary == "version unknown"


def test_check_enabled_and_blocked_flags(monkeypatch):
    _patch_state(
        monkeypatch,
        installed=[{"name": "foo", "marketplace": "official", "version": "1"}],
        catalog={("official", "foo"): "2"},
        enabled={"foo@official": False},
        blocked={"foo@official"},
    )
    (check,) = updater.check_plugin_updates().checks
    assert check.enabled is False
    assert check.blocked is True


def test_check_filters_by_plugin_and_marketplace(monkeypatch):
    installed = [
        {"name": "foo", "marketplace": "official", "version": "1"},
        {"name": "bar", "marketplace": "other", "version": "1"},
    ]
    _patch_state(monkeypatch, installed=installed)
    assert [c.name for c in updater.check_plugin_updates(plugin="foo").checks] == ["foo"]
    assert [c.name for c in updater.check_plugin_updates(marketplace="other").checks] == ["bar"]


def test_check_captures_refresh_error(monkeypatch):
    _patch_state(monkeypatch, installed=[], refresh=(1, "", "network down"))
    result = updater.check_plugin_updates(refresh=True)
    assert result.refresh_error == "network down"


def test_check_skips_refresh_when_disabled(monkeypatch):
    calls = []
    monkeypatch.setattr(updater.claude_cli, "plugin_list_json", lambda: [])
    monkeypatch.setattr(updater.claude_cli, "marketplace_update", lambda name=None: calls.append(name) or (0, "", ""))
    monkeypatch.setattr(updater.state, "read_marketplace_catalog_versions", lambda: {})
    monkeypatch.setattr(updater.state, "read_settings_plugins", lambda: ({}, {}))
    monkeypatch.setattr(updater.state, "blocked_plugin_ids", lambda: set())
    updater.check_plugin_updates(refresh=False)
    assert calls == []


def test_apply_success_requires_restart(monkeypatch):
    monkeypatch.setattr(updater.claude_cli, "plugin_update", lambda p: (0, "Updated foo to 2.0.0", ""))
    outcome = updater.apply_plugin_update("foo@official")
    assert outcome.updated is True
    assert outcome.restart_required is True
    assert outcome.error is None


def test_apply_noop_no_restart(monkeypatch):
    monkeypatch.setattr(updater.claude_cli, "plugin_update", lambda p: (0, "Plugin is already up to date", ""))
    outcome = updater.apply_plugin_update("foo@official")
    assert outcome.updated is False
    assert outcome.restart_required is False


def test_apply_failure_sets_error(monkeypatch):
    monkeypatch.setattr(updater.claude_cli, "plugin_update", lambda p: (1, "", "no such plugin"))
    outcome = updater.apply_plugin_update("ghost@official")
    assert outcome.updated is False
    assert outcome.error == "no such plugin"
