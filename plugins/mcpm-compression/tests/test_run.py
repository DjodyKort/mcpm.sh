"""Launch (`run`) + proxy-lifecycle tests. Sandbox the config dir before import;
mock subprocess/execvpe so nothing is actually spawned."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest import mock

os.environ["MCPM_CONFIG_DIR"] = str(Path(tempfile.mkdtemp(prefix="mcpm-comp-run-")))

from click.testing import CliRunner  # noqa: E402

from mcpm_compression import cli as cli_mod  # noqa: E402
from mcpm_compression.config import save_config  # noqa: E402
from mcpm_compression.providers import headroom_runtime as hr  # noqa: E402
from mcpm_compression.schema import AGENT_PORT, CompressionConfig, ContextRule  # noqa: E402


# ---- adapter: proxy_up / proxy_down ----

def test01_proxy_up_reuses_healthy_proxy():
    with mock.patch.object(hr, "proxy_health", return_value={"ok": True}), \
         mock.patch("mcpm_compression.providers.headroom_runtime.subprocess.Popen") as popen:
        ok, detail = hr.proxy_up(8787, {"HEADROOM_MODE": "cache"})
    assert ok and "reusing" in detail
    popen.assert_not_called()  # never spawn when one is already healthy


def test02_proxy_up_spawns_then_polls_ready():
    health = mock.Mock(side_effect=[{"ok": False}, {"ok": True}])  # down, then ready
    with mock.patch.object(hr, "proxy_health", health), \
         mock.patch.object(hr, "_headroom", return_value="/usr/bin/headroom"), \
         mock.patch("mcpm_compression.providers.headroom_runtime.time.sleep"), \
         mock.patch("mcpm_compression.providers.headroom_runtime.subprocess.Popen") as popen:
        ok, detail = hr.proxy_up(8788, {"HEADROOM_MODE": "token"})
    assert ok and ":8788" in detail
    popen.assert_called_once()
    argv = popen.call_args[0][0]
    assert argv[:2] == ["/usr/bin/headroom", "proxy"]
    assert "--port" in argv and "8788" in argv and "token" in argv


def test03_proxy_down_kills_health_pid():
    with mock.patch.object(hr, "proxy_health", return_value={"ok": True, "config": {"pid": 4242}}), \
         mock.patch("mcpm_compression.providers.headroom_runtime.os.kill") as kill:
        ok, detail = hr.proxy_down(8787)
    assert ok and "4242" in detail
    kill.assert_called_once_with(4242, hr.signal.SIGTERM)


# ---- CLI: run ----

def _seed_config():
    cfg = CompressionConfig(
        provider="headroom", active_preset="interactive",
        contexts=[ContextRule(match="*/agent-batch/*", preset="agent")],
    )
    cfg.presets["agent"].env = dict(hr._FALLBACK_PROFILE_ENV["agent-90"])
    save_config(cfg)
    return cfg


def test04_run_headroom_dir_ensures_proxy_and_execs_with_env():
    _seed_config()
    captured = {}

    def _fake_exec(file, argv, env):
        captured["file"], captured["argv"], captured["env"] = file, argv, env

    with mock.patch.object(cli_mod, "hr_proxy_up", return_value=(True, "ok")) as up, \
         mock.patch("mcpm_compression.cli.os.execvpe", side_effect=_fake_exec):
        res = CliRunner().invoke(cli_mod.run, ["--cwd", "/x/agent-batch/run", "--", "--version"])

    assert res.exit_code == 0, res.output
    up.assert_called_once()
    assert up.call_args[0][0] == AGENT_PORT  # agent preset → :8788
    assert captured["file"] == "claude"
    assert captured["argv"] == ["claude", "--version"]
    assert captured["env"]["ANTHROPIC_BASE_URL"] == f"http://127.0.0.1:{AGENT_PORT}"
    assert captured["env"]["HEADROOM_MODE"] == "token"


def test05_run_none_provider_goes_direct_no_proxy():
    cfg = CompressionConfig(provider="headroom", active_preset="interactive",
                            contexts=[ContextRule(match="*/clients/*", provider="none")])
    save_config(cfg)
    captured = {}
    with mock.patch.object(cli_mod, "hr_proxy_up") as up, \
         mock.patch("mcpm_compression.cli.os.execvpe",
                    side_effect=lambda f, a, e: captured.update(env=e)):
        # pre-seed a stale base-url to prove run clears it for a `none` dir
        with mock.patch.dict(os.environ, {"ANTHROPIC_BASE_URL": "http://127.0.0.1:8787"}):
            res = CliRunner().invoke(cli_mod.run, ["--cwd", "/x/clients/acme", "--", "-p", "hi"])
    assert res.exit_code == 0, res.output
    up.assert_not_called()
    assert "ANTHROPIC_BASE_URL" not in captured["env"]


def test06_proxy_up_cmd_reports_active_port():
    _seed_config()  # active = interactive → :8787
    with mock.patch.object(cli_mod, "hr_proxy_up", return_value=(True, "started")) as up:
        res = CliRunner().invoke(cli_mod.proxy, ["up"])
    assert res.exit_code == 0, res.output
    assert up.call_args[0][0] == 8787
