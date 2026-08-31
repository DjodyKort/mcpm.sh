"""Tokenade provider tests. Sandbox the config dir before import; mock every vendor
call so nothing is spawned and no real settings.json is touched."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest import mock

os.environ["MCPM_CONFIG_DIR"] = str(Path(tempfile.mkdtemp(prefix="mcpm-comp-tk-")))

from click.testing import CliRunner  # noqa: E402

from mcpm_compression import cli as cli_mod  # noqa: E402
from mcpm_compression.config import save_config  # noqa: E402
from mcpm_compression.providers import (  # noqa: E402
    get_provider,
    provider_names,
    tokenade_runtime as tk,
)
from mcpm_compression.providers.tokenade import TokenadeProvider  # noqa: E402
from mcpm_compression.schema import (  # noqa: E402
    TOKENADE_DEFAULT_PIN,
    CompressionConfig,
)


# ---- schema / registry ----

def test01_registry_knows_tokenade_as_hook_provider():
    assert "tokenade" in provider_names()
    provider = get_provider("tokenade")
    cfg = CompressionConfig(provider="tokenade")
    assert provider.runtime_spec(cfg).kind == "hook"
    assert provider.mcp_server_config(cfg) is None  # mcp_wrap off is the pilot posture


def test02_tokenade_pin_is_an_exact_npm_requirement():
    cfg = CompressionConfig()
    pv = cfg.pin_for("tokenade")
    assert pv.ecosystem == "npm"
    assert pv.requirement() == f"@tokenade/cli@{TOKENADE_DEFAULT_PIN}"
    # The headroom pin is untouched by the new field — old configs must mean the same.
    assert cfg.pin_for("headroom").requirement().startswith("headroom-ai[")
    assert cfg.pin_for("none") is None


# ---- hooks detection / removal (the disable path must be surgical) ----

def _settings(tmp_path: Path) -> Path:
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({
        "model": "opusplan",
        "hooks": {
            "PreToolUse": [
                {"matcher": "Bash", "hooks": [{"type": "command", "command": "rtk hook claude"}]},
                {"matcher": "Bash", "hooks": [
                    {"type": "command", "command": "/opt/x/tokenade hook bash-rewrite"}]},
            ],
            "PostToolUse": [
                {"hooks": [{"type": "command", "command": "/opt/x/tokenade hook fold"}]},
                {"hooks": [{"type": "command", "command": "/apps/switchboard-hook.sh"}]},
            ],
            "SessionStart": [
                {"hooks": [{"type": "command", "command": "/opt/x/tokenade hook session"}]},
            ],
        },
    }, indent=2))
    return p


def test03_hooks_present_detects_tokenade_entries(tmp_path):
    p = _settings(tmp_path)
    assert tk.hooks_present(p)
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"hooks": {}}))
    assert not tk.hooks_present(empty)
    assert not tk.hooks_present(tmp_path / "missing.json")


def test04_remove_hooks_strips_only_tokenade_and_backs_up(tmp_path):
    """Disable is the kill switch: it must remove every tokenade hook and NOTHING else —
    rtk, switchboard, and unrelated settings keys survive byte-for-byte in value."""
    p = _settings(tmp_path)
    removed, backup = tk.remove_hooks(p)
    assert removed == 3
    assert backup and backup.exists()

    after = json.loads(p.read_text())
    assert after["model"] == "opusplan"
    flat = [h["command"] for groups in after["hooks"].values()
            for g in groups for h in g["hooks"]]
    assert "rtk hook claude" in flat and "/apps/switchboard-hook.sh" in flat
    assert not any("tokenade" in c for c in flat)
    assert "SessionStart" not in after["hooks"]  # emptied event keys are dropped

    # Idempotent: a second pass finds nothing and takes no new backup.
    assert tk.remove_hooks(p) == (0, None)


# ---- engage posture ----

def test05_engage_unwraps_mcps_when_policy_says_off():
    cfg = CompressionConfig(provider="tokenade")
    assert cfg.tokenade.mcp_wrap is False  # the conservative default IS the pilot
    with mock.patch.object(tk, "version", return_value=TOKENADE_DEFAULT_PIN), \
         mock.patch.object(tk, "vendor_install", return_value=(True, "ok")) as vi, \
         mock.patch.object(tk, "unwrap_mcps", return_value=(True, "restored 16")) as uw, \
         mock.patch.object(tk, "updater_off", return_value=(True, "off")) as upd, \
         mock.patch.object(tk, "hooks_present", return_value=True):
        _, warnings = TokenadeProvider().engage(cfg)
    assert not warnings
    vi.assert_called_once_with(with_claude_md=False)
    uw.assert_called_once()   # mcpm keeps owning the MCP entries
    upd.assert_called_once()  # the 24h self-updater is track-latest with extra steps


def test05b_engage_refuses_a_drifted_build():
    """Same stance as the proxy kill switch: an unverified build is never engaged —
    but here refusal happens at engage time, because hooks cannot be refused per-launch."""
    cfg = CompressionConfig(provider="tokenade")
    with mock.patch.object(tk, "version", return_value="9.9.9"), \
         mock.patch.object(tk, "vendor_install") as vi:
        _, warnings = TokenadeProvider().engage(cfg)
    vi.assert_not_called()
    assert any("≠ pin" in w for w in warnings)


# ---- run: attribution reflects reality, not policy ----

def test06_run_tokenade_records_live_pin_and_no_base_url():
    save_config(CompressionConfig(provider="tokenade"))
    seen, captured = [], {}
    with mock.patch.object(cli_mod, "tk_version", return_value=TOKENADE_DEFAULT_PIN), \
         mock.patch.object(cli_mod, "tk_hooks_present", return_value=True), \
         mock.patch.object(cli_mod, "append_launch", side_effect=lambda **kw: seen.append(kw)), \
         mock.patch.dict(os.environ, {"ANTHROPIC_BASE_URL": "http://127.0.0.1:8787"}), \
         mock.patch("mcpm_compression.cli.os.execvpe",
                    side_effect=lambda f, a, e: captured.update(argv=a, env=e)):
        res = CliRunner().invoke(cli_mod.run, ["--cwd", "/w", "--", "--version"])
    assert res.exit_code == 0, res.output
    assert captured["argv"] == ["claude", "--version"]
    # A stale proxy URL must never survive into a hook-provider launch.
    assert "ANTHROPIC_BASE_URL" not in captured["env"]
    assert seen and seen[0]["routed"] is True
    assert seen[0]["provider"] == "tokenade" and seen[0]["pin"] == TOKENADE_DEFAULT_PIN
    assert seen[0]["port"] is None


def test06b_run_tokenade_not_engaged_is_not_credited():
    """Binary absent or hooks missing → the session is plain, and the ledger must say so,
    or `verify` blames tokenade for sessions it never touched."""
    save_config(CompressionConfig(provider="tokenade"))
    seen = []
    with mock.patch.object(cli_mod, "tk_version", return_value=None), \
         mock.patch.object(cli_mod, "tk_hooks_present", return_value=False), \
         mock.patch.object(cli_mod, "append_launch", side_effect=lambda **kw: seen.append(kw)), \
         mock.patch("mcpm_compression.cli.os.execvpe"):
        res = CliRunner().invoke(cli_mod.run, ["--cwd", "/w", "--", "-p", "hi"])
    assert res.exit_code == 0, res.output
    assert seen and seen[0]["routed"] is False


def test06c_run_tokenade_drifted_build_warns_but_stays_truthful():
    """Hooks are global — a drifted build still optimizes the session. Recording
    routed=False would flatter the pin; recording the *live* version is the truth."""
    save_config(CompressionConfig(provider="tokenade"))
    seen = []
    with mock.patch.object(cli_mod, "tk_version", return_value="9.9.9"), \
         mock.patch.object(cli_mod, "tk_hooks_present", return_value=True), \
         mock.patch.object(cli_mod, "append_launch", side_effect=lambda **kw: seen.append(kw)), \
         mock.patch("mcpm_compression.cli.os.execvpe"):
        res = CliRunner().invoke(cli_mod.run, ["--cwd", "/w", "--", "-p", "hi"])
    assert res.exit_code == 0, res.output
    assert seen and seen[0]["routed"] is True and seen[0]["pin"] == "9.9.9"
    assert "≠ pin" in res.output


# ---- disable: the kill switch disengages leftover hooks ----

def test07_disable_disengages_tokenade():
    save_config(CompressionConfig(provider="tokenade"))
    with mock.patch.object(cli_mod, "tk_hooks_present", return_value=True), \
         mock.patch.object(tk, "unwrap_mcps", return_value=(True, "ok")), \
         mock.patch.object(tk, "remove_hooks", return_value=(3, Path("/b"))) as rm:
        res = CliRunner().invoke(cli_mod.disable, [])
    assert res.exit_code == 0, res.output
    rm.assert_called_once()


def test07b_disable_removes_leftover_hooks_even_under_other_provider():
    """Policy drifted to none but hooks stayed behind → disable still cleans them up;
    otherwise 'compression off' is a lie for every session."""
    save_config(CompressionConfig(provider="none"))
    with mock.patch.object(cli_mod, "tk_hooks_present", return_value=True), \
         mock.patch.object(tk, "unwrap_mcps", return_value=(True, "ok")), \
         mock.patch.object(tk, "remove_hooks", return_value=(2, Path("/b"))) as rm:
        res = CliRunner().invoke(cli_mod.disable, [])
    assert res.exit_code == 0, res.output
    rm.assert_called_once()
