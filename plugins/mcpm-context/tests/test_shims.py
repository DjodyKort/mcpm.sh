from __future__ import annotations

from mcpm_context.paths import profiles_root, shims_path
from mcpm_context.schema import ProfileSpec
from mcpm_context.shims import remove_shims, shim_snippet, write_shims


def test01_one_function_per_profile():
    snippet = shim_snippet({"bare": ProfileSpec(), "arp": ProfileSpec()})
    assert (
        f'claude-bare() {{ _mcpm_context_presync; CLAUDE_CONFIG_DIR="{profiles_root() / "bare"}" '
        'command claude "$@"; }' in snippet
    )
    assert "claude-arp()" in snippet
    assert snippet.index("claude-arp") < snippet.index("claude-bare")  # sorted


def test02_wrapper_supersets_cf_and_hrclaude():
    snippet = shim_snippet({})
    assert "_mcpm_context_presync()" in snippet
    assert 'claude() { _mcpm_context_presync; command claude "$@"; }' in snippet
    # hrclaude override is conditional on the compression shims defining it.
    assert "$+functions[hrclaude]" in snippet
    assert 'hrclaude() { _mcpm_context_presync; command mcpm compression run -- "$@"; }' in snippet
    # cf's exact sync entry points + shared throttle cache.
    assert "sync_claude_files" in snippet and "auto_update_mcp_repos" in snippet
    assert ".last_auto_sync" in snippet
    assert "mcpm context sync" in snippet


def test03_wrap_disabled_yields_dumb_profile_shims():
    snippet = shim_snippet({"bare": ProfileSpec()}, wrap_default=False)
    assert "_mcpm_context_presync" not in snippet
    assert 'claude() {' not in snippet
    assert "hrclaude" not in snippet
    assert f'claude-bare() {{ CLAUDE_CONFIG_DIR="{profiles_root() / "bare"}" command claude "$@"; }}' in snippet


def test04_write_and_remove():
    write_shims({"bare": ProfileSpec()})
    assert shims_path().exists()
    assert remove_shims()
    assert not shims_path().exists()
    assert not remove_shims()  # idempotent
