from __future__ import annotations

import json
import sys
import types

from mcpm_context.paths import claude_home
from mcpm_context.profiles import MANAGED_HEADER, generate_profile, remove_profile
from mcpm_context.schema import DedupePolicy, ProfileSpec
from mcpm_context.sync import ApplyReport


def _gen(name, spec, claude_json=None):
    report = ApplyReport()
    pdir = generate_profile(name, spec, DedupePolicy(), report)
    return pdir, report


def _seed_home_rules():
    rules = claude_home() / "rules"
    rules.mkdir(parents=True, exist_ok=True)
    (rules / "personal.md").write_text("personal layer\n")
    (rules / "client-arp.md").write_text("client layer\n")
    return rules


def test01_org_import_mode(claude_settings):
    pdir, _ = _gen("full", ProfileSpec())
    content = (pdir / "CLAUDE.md").read_text()
    assert MANAGED_HEADER in content
    assert "@~/.claude/CLAUDE.md" in content


def test02_org_copy_mode_inlines(claude_settings):
    (claude_home() / "CLAUDE.md").write_text("# ORG CONTENT\n")
    pdir, _ = _gen("copyprof", ProfileSpec(org_mode="copy"))
    content = (pdir / "CLAUDE.md").read_text()
    assert "# ORG CONTENT" in content and "@~/.claude/CLAUDE.md" not in content


def test03_bare_profile_has_no_org(claude_settings):
    pdir, _ = _gen("bare", ProfileSpec(org=False, rules="none", servers="none"))
    content = (pdir / "CLAUDE.md").read_text()
    assert "@~/.claude/CLAUDE.md" not in content and "org layer disabled" in content
    assert not (pdir / "rules").exists()
    assert json.loads((pdir / ".claude.json").read_text())["mcpServers"] == {}


def test04_rules_inherit_symlinks_dir(claude_settings):
    _seed_home_rules()
    pdir, _ = _gen("full", ProfileSpec())
    assert (pdir / "rules").is_symlink()
    assert (pdir / "rules" / "personal.md").read_text() == "personal layer\n"


def test05_rules_explicit_list_per_file(claude_settings):
    _seed_home_rules()
    pdir, report = _gen("sel", ProfileSpec(rules=["personal"]))
    assert (pdir / "rules").is_dir() and not (pdir / "rules").is_symlink()
    assert (pdir / "rules" / "personal.md").is_symlink()
    assert not (pdir / "rules" / "client-arp.md").exists()
    # Switching selection removes the stale managed link.
    pdir, report = _gen("sel", ProfileSpec(rules=["client-arp"]))
    assert not (pdir / "rules" / "personal.md").exists()
    assert (pdir / "rules" / "client-arp.md").is_symlink()


def test06_rules_copy_fallback(claude_settings):
    _seed_home_rules()
    pdir, _ = _gen("cp", ProfileSpec(rules=["personal"], link_rules=False))
    target = pdir / "rules" / "personal.md"
    assert target.exists() and not target.is_symlink()


def test07_missing_layer_warns(claude_settings):
    _seed_home_rules()
    _, report = _gen("warns", ProfileSpec(rules=["nonexistent"]))
    assert any("nonexistent" in w for w in report.warnings)


def test08_shared_dir_links(claude_settings):
    (claude_home() / "commands").mkdir()
    (claude_home() / "skills").mkdir()
    pdir, _ = _gen("full", ProfileSpec(agents=False))
    assert (pdir / "commands").is_symlink() and (pdir / "skills").is_symlink()
    assert not (pdir / "agents").exists()  # source missing → skipped with warn


def test09_settings_composed_copy_with_overrides(claude_settings):
    pdir, _ = _gen("ovr", ProfileSpec(settings_overrides={"model": "haiku", "permissions": {"allow": ["Extra"]}}))
    data = json.loads((pdir / "settings.json").read_text())
    assert not (pdir / "settings.json").is_symlink()
    assert data["model"] == "haiku"  # override wins over base
    assert "Extra" in data["permissions"]["allow"]
    assert "mcp__codeforward-odoo__get_*" in data["permissions"]["allow"]  # base kept


def test10_profile_accumulated_settings_survive_resync(claude_settings):
    pdir, _ = _gen("acc", ProfileSpec())
    data = json.loads((pdir / "settings.json").read_text())
    data["permissions"]["allow"].append("Bash(user approved this in-session)")
    (pdir / "settings.json").write_text(json.dumps(data))
    pdir, _ = _gen("acc", ProfileSpec())
    allow = json.loads((pdir / "settings.json").read_text())["permissions"]["allow"]
    assert "Bash(user approved this in-session)" in allow


def test11_claude_json_bootstrap_identity_and_inherit(claude_json, claude_settings):
    pdir, _ = _gen("full", ProfileSpec())
    data = json.loads((pdir / ".claude.json").read_text())
    assert data["oauthAccount"]["emailAddress"] == "test@example.com"
    assert data["hasCompletedOnboarding"] is True
    servers = data["mcpServers"]
    assert "mcpm_context7" in servers and "mcpm_odh" in servers and "hand-added" in servers
    assert "context7" not in servers and "playwright" not in servers  # legacy filtered


def test12_no_copy_auth_skips_identity(claude_json, claude_settings):
    pdir, _ = _gen("anon", ProfileSpec(copy_auth=False))
    data = json.loads((pdir / ".claude.json").read_text())
    assert "oauthAccount" not in data and "userID" not in data
    assert data["hasCompletedOnboarding"] is True  # onboarding always copied


def test13_claude_json_state_preserved_on_resync(claude_json, claude_settings):
    pdir, _ = _gen("full", ProfileSpec())
    data = json.loads((pdir / ".claude.json").read_text())
    data["numStartups"] = 7  # Claude Code accumulates its own state here
    (pdir / ".claude.json").write_text(json.dumps(data))
    pdir, _ = _gen("full", ProfileSpec())
    assert json.loads((pdir / ".claude.json").read_text())["numStartups"] == 7


def test14_servers_list_via_fake_mcpm(claude_json, claude_settings):
    gc = types.ModuleType("mcpm.global_config")
    mgr_mod = types.ModuleType("mcpm.clients.managers.claude_code")

    class GlobalConfigManager:
        def get_server(self, name):
            return types.SimpleNamespace(name=name) if name == "odh" else None

    class ClaudeCodeManager:
        def __init__(self, config_path_override=None):
            pass

        def to_client_format(self, server):
            return {"command": "mcpm", "args": ["run", server.name]}

    gc.GlobalConfigManager = GlobalConfigManager
    mgr_mod.ClaudeCodeManager = ClaudeCodeManager
    fakes = {
        "mcpm": types.ModuleType("mcpm"),
        "mcpm.global_config": gc,
        "mcpm.clients": types.ModuleType("mcpm.clients"),
        "mcpm.clients.managers": types.ModuleType("mcpm.clients.managers"),
        "mcpm.clients.managers.claude_code": mgr_mod,
    }
    old = {k: sys.modules.get(k) for k in fakes}
    sys.modules.update(fakes)
    try:
        pdir, report = _gen("sel", ProfileSpec(servers=["odh", "context7", "ghost"]))
    finally:
        for k, v in old.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
    servers = json.loads((pdir / ".claude.json").read_text())["mcpServers"]
    assert servers["mcpm_odh"] == {"command": "mcpm", "args": ["run", "odh"]}  # shaped via mcpm
    assert "mcpm_context7" in servers  # unknown to fake registry → mirrored fallback
    assert not any("ghost" in k for k in servers)  # nowhere to be found → skipped
    assert any("ghost" in w for w in report.warnings)


def test15_remove_profile(claude_settings):
    pdir, report = _gen("gone", ProfileSpec())
    assert pdir.exists()
    assert remove_profile("gone", report)
    assert not pdir.exists()
    assert not remove_profile("gone", report)  # second call: nothing to do
