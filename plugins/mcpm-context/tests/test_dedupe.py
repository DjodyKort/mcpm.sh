from __future__ import annotations

import json
from pathlib import Path

from mcpm_context.dedupe import apply_dedupe, plan_dedupe
from mcpm_context.paths import backups_dir
from mcpm_context.schema import DedupePolicy


def test01_plan_finds_only_legacy_with_twin(claude_json):
    planned = plan_dedupe(claude_json, DedupePolicy())
    assert planned == ["context7", "playwright"]  # odoo/typst legacies absent


def test02_no_twin_means_kept(claude_json):
    data = json.loads(claude_json.read_text())
    del data["mcpServers"]["mcpm_playwright"]
    claude_json.write_text(json.dumps(data))
    assert plan_dedupe(claude_json, DedupePolicy()) == ["context7"]


def test03_apply_removes_legacy_preserves_everything_else(claude_json):
    before = json.loads(claude_json.read_text())
    removed = apply_dedupe(claude_json, DedupePolicy())
    assert removed == ["context7", "playwright"]
    after = json.loads(claude_json.read_text())
    assert "context7" not in after["mcpServers"] and "playwright" not in after["mcpServers"]
    assert after["mcpServers"]["hand-added"] == before["mcpServers"]["hand-added"]
    assert after["mcpServers"]["mcpm_context7"] == before["mcpServers"]["mcpm_context7"]
    assert after["numStartups"] == 42 and after["oauthAccount"] == before["oauthAccount"]


def test04_backup_written_before_mutation(claude_json):
    apply_dedupe(claude_json, DedupePolicy())
    backups = list(backups_dir().rglob("claude.json"))
    assert len(backups) == 1
    assert "context7" in json.loads(backups[0].read_text())["mcpServers"]  # pre-mutation state


def test05_idempotent_second_run(claude_json):
    apply_dedupe(claude_json, DedupePolicy())
    assert apply_dedupe(claude_json, DedupePolicy()) == []
    assert len(list(backups_dir().rglob("claude.json"))) == 1  # no pointless backup


def test06_disabled_policy_removes_nothing(claude_json):
    assert plan_dedupe(claude_json, DedupePolicy(enabled=False)) == []


def test07_missing_or_corrupt_file_is_noop(sandbox):
    missing = Path(sandbox / "nope.json")
    assert plan_dedupe(missing, DedupePolicy()) == []
    corrupt = Path(sandbox / "corrupt.json")
    corrupt.write_text("{oops")
    assert plan_dedupe(corrupt, DedupePolicy()) == []


def test08_without_twin_requirement_removes_all_legacy(claude_json):
    data = json.loads(claude_json.read_text())
    del data["mcpServers"]["mcpm_context7"]
    claude_json.write_text(json.dumps(data))
    policy = DedupePolicy(require_mcpm_twin=False)
    assert plan_dedupe(claude_json, policy) == ["context7", "playwright"]
