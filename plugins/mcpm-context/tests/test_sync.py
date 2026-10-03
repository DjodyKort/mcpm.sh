from __future__ import annotations

import json
import os
from pathlib import Path

from mcpm_context.config import load_config
from mcpm_context.doctor import run_checks
from mcpm_context.paths import claude_home, profiles_root, shims_path
from mcpm_context.schema import ContextConfig, ProfileSpec, SettingsPolicy
from mcpm_context.sync import apply, disable


def _full_config():
    return ContextConfig(
        profiles={"bare": ProfileSpec(org=False, rules="none", servers="none")},
        settings=SettingsPolicy(ensure_allow=["Bash(git status)"]),
    )


def test01_apply_orchestrates_everything(claude_json, claude_settings):
    report = apply(_full_config())
    assert not report.warnings
    # dedupe ran
    assert "context7" not in json.loads(claude_json.read_text())["mcpServers"]
    # settings union ran
    assert "Bash(git status)" in json.loads(claude_settings.read_text())["permissions"]["allow"]
    # profile generated + shims written + config persisted
    assert (profiles_root() / "bare" / "CLAUDE.md").exists()
    assert "claude-bare()" in shims_path().read_text()
    assert load_config().profiles["bare"].org is False


def test02_apply_idempotent(claude_json, claude_settings):
    apply(_full_config())
    report2 = apply(_full_config())
    assert not report2.warnings
    # second run: no re-dedupe, no settings rewrite reported
    assert not any("legacy" in a for a in report2.actions)
    assert not any("re-unioned" in a for a in report2.actions)


def test03_orphan_profile_dir_warned(claude_json, claude_settings):
    (profiles_root() / "stray").mkdir(parents=True)
    report = apply(_full_config())
    assert any("orphan" in w and "stray" in w for w in report.warnings)


def test04_shims_follow_profiles_and_wrap_flag(claude_json, claude_settings):
    apply(_full_config())
    assert shims_path().exists()
    # No profiles but wrapper on (default) → wrapper-only shims stay.
    apply(ContextConfig(settings=SettingsPolicy(ensure_allow=["Bash(git status)"])))
    content = shims_path().read_text()
    assert "mcpm_context_presync" in content and "claude-" not in content.replace("claude-code", "")
    # Wrapper off + no profiles → shims removed.
    report = apply(ContextConfig(wrap_default_claude=False))
    assert any("removed shims" in a for a in report.actions)
    assert not shims_path().exists()


def test05_disable_strips_only_generated(claude_json, claude_settings):
    apply(_full_config())
    home_before = sorted(p.name for p in claude_home().iterdir())
    json_before = claude_json.read_text()
    disable(purge_profiles=True)
    assert not shims_path().exists()
    assert not (profiles_root() / "bare").exists()
    # untouched: ~/.claude contents and ~/.claude.json
    assert sorted(p.name for p in claude_home().iterdir()) == home_before
    assert claude_json.read_text() == json_before
    # re-apply reconverges
    apply(_full_config())
    assert (profiles_root() / "bare").exists() and shims_path().exists()


def test06_cf_baseline_recorded_once(claude_json, claude_settings, sandbox):
    cf_wrapper = Path(os.environ["MCPM_CONTEXT_CF_DIR"]) / "claude" / "shell-wrapper.sh"
    cf_wrapper.parent.mkdir(parents=True)
    cf_wrapper.write_text("claude() { command claude \"$@\"; }\n")
    apply(_full_config())
    baseline = load_config().cf_wrapper_hash
    assert baseline
    apply(load_config())
    assert load_config().cf_wrapper_hash == baseline  # not re-recorded


def test07_doctor_flags_cf_wrapper_drift(claude_json, claude_settings, sandbox):
    cf_wrapper = Path(os.environ["MCPM_CONTEXT_CF_DIR"]) / "claude" / "shell-wrapper.sh"
    cf_wrapper.parent.mkdir(parents=True)
    cf_wrapper.write_text("v1\n")
    apply(_full_config())
    checks = run_checks(load_config())
    assert any(level == "ok" and "unchanged" in msg for level, msg in checks)
    cf_wrapper.write_text("v2 — changed behavior\n")
    checks = run_checks(load_config())
    assert any(level == "warn" and "CHANGED" in msg for level, msg in checks)


def test08_doctor_flags_new_cf_assets(claude_json, claude_settings):
    cf_claude = Path(os.environ["MCPM_CONTEXT_CF_DIR"]) / "claude"
    cf_claude.mkdir(parents=True)
    (cf_claude / "CLAUDE.md").write_text("org\n")
    (cf_claude / "rules").mkdir()  # cf suddenly ships rules → scope expansion
    checks = run_checks(load_config())
    assert any(level == "warn" and "rules" in msg for level, msg in checks)


def test09_doctor_flags_dupes_and_stale_settings(claude_json, claude_settings):
    config = _full_config()
    apply(config)
    # cf re-adds a legacy duplicate
    data = json.loads(claude_json.read_text())
    data["mcpServers"]["context7"] = {"command": "npx"}
    claude_json.write_text(json.dumps(data))
    # base settings change → profile settings stale
    data = json.loads(claude_settings.read_text())
    data["model"] = "something-new"
    claude_settings.write_text(json.dumps(data))
    checks = run_checks(load_config())
    assert any("legacy MCP duplicates" in msg for level, msg in checks if level == "warn")
    assert any("stale" in msg for level, msg in checks if level == "warn")


def test10_doctor_flags_global_config_dir_export(claude_json, claude_settings, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/tmp/somewhere")
    checks = run_checks(_full_config())
    assert any("exported globally" in msg for level, msg in checks if level == "warn")
