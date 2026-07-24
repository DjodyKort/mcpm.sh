from __future__ import annotations

import json

from mcpm_context.paths import backups_dir
from mcpm_context.schema import SettingsPolicy
from mcpm_context.settings import deep_merge_union, ensure_policy, looks_secret_bearing


def test01_deep_merge_union_semantics():
    base = {"a": {"x": [1, 2], "y": "base"}, "keep": True}
    override = {"a": {"x": [2, 3], "y": "override"}, "new": 1}
    merged = deep_merge_union(base, override)
    assert merged["a"]["x"] == [1, 2, 3]  # ordered union, not replace
    assert merged["a"]["y"] == "override"  # scalar: override wins
    assert merged["keep"] is True and merged["new"] == 1


def test02_cf_clobber_then_ensure_policy_restores(claude_settings):
    policy = SettingsPolicy(ensure_allow=["Bash(git status)", "WebFetch(domain:docs.python.org)"])
    assert ensure_policy(claude_settings, policy)
    # Simulate cf's jq merge: allow array replaced wholesale by the team list.
    data = json.loads(claude_settings.read_text())
    data["permissions"]["allow"] = ["mcp__codeforward-odoo__get_*", "mcp__codeforward-typst__*"]
    claude_settings.write_text(json.dumps(data))
    assert ensure_policy(claude_settings, policy)  # changed again
    allow = json.loads(claude_settings.read_text())["permissions"]["allow"]
    assert "mcp__codeforward-odoo__get_*" in allow  # team entries kept
    assert "Bash(git status)" in allow and "WebFetch(domain:docs.python.org)" in allow


def test03_idempotent_no_write_when_present(claude_settings):
    policy = SettingsPolicy(ensure_allow=["Bash(git status)"])
    assert ensure_policy(claude_settings, policy)
    assert not ensure_policy(claude_settings, policy)
    assert len(list(backups_dir().rglob("settings.json"))) == 1


def test04_other_keys_untouched(claude_settings):
    ensure_policy(claude_settings, SettingsPolicy(ensure_allow=["X"], ensure_ask=["Y"]))
    data = json.loads(claude_settings.read_text())
    assert data["model"] == "claude-fable-5[1m]"
    assert data["hooks"]["Stop"][0]["hooks"][0]["command"] == "/x/hook.sh"
    assert "Y" in data["permissions"]["ask"] and "Bash(git push*)" in data["permissions"]["ask"]


def test05_empty_policy_is_noop(claude_settings):
    before = claude_settings.read_text()
    assert not ensure_policy(claude_settings, SettingsPolicy())
    assert claude_settings.read_text() == before


def test06_unparseable_settings_never_overwritten(claude_settings):
    claude_settings.write_text("{broken")
    assert not ensure_policy(claude_settings, SettingsPolicy(ensure_allow=["X"]))
    assert claude_settings.read_text() == "{broken"


def test07_missing_file_created(sandbox, claude_settings):
    claude_settings.unlink()
    assert ensure_policy(claude_settings, SettingsPolicy(ensure_allow=["X"]))
    assert json.loads(claude_settings.read_text())["permissions"]["allow"] == ["X"]


def test08_secret_detection():
    assert looks_secret_bearing('Bash(GOOGLE_CLIENT_SECRET="zzz" npx:*)')
    assert looks_secret_bearing("Bash(API_KEY=abc curl:*)")
    assert not looks_secret_bearing("Bash(git status)")
    assert not looks_secret_bearing("WebFetch(domain:api.github.com)")  # no '=' assignment
