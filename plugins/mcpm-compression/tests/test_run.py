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
from mcpm_compression.schema import (  # noqa: E402
    AGENT_PORT,
    CompressionConfig,
    ContextRule,
    KnobSpec,
)


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
    cfg.presets["agent"].knobs = {
        "HEADROOM_SAVINGS_PROFILE": KnobSpec(value="agent-90"),
        "HEADROOM_MODE": KnobSpec(value="token"),
    }
    save_config(cfg)
    return cfg


def _at_pin(cfg=None):
    """Pretend the installed build matches the pin, so the kill switch lets us through."""
    pin = (cfg or CompressionConfig()).provider_version.pin
    return mock.patch.object(cli_mod, "hr_version", return_value=pin)


def test04_run_headroom_dir_ensures_proxy_and_execs_with_env():
    cfg = _seed_config()
    captured = {}

    def _fake_exec(file, argv, env):
        captured["file"], captured["argv"], captured["env"] = file, argv, env

    with _at_pin(cfg), \
         mock.patch.object(cli_mod, "hr_proxy_up", return_value=(True, "ok")) as up, \
         mock.patch("mcpm_compression.cli.os.execvpe", side_effect=_fake_exec):
        res = CliRunner().invoke(cli_mod.run, ["--cwd", "/x/agent-batch/run", "--", "--version"])

    assert res.exit_code == 0, res.output
    up.assert_called_once()
    assert up.call_args[0][0] == AGENT_PORT  # agent preset → :8788
    assert captured["file"] == "claude"
    assert captured["argv"] == ["claude", "--version"]
    assert captured["env"]["ANTHROPIC_BASE_URL"] == f"http://127.0.0.1:{AGENT_PORT}"
    assert captured["env"]["HEADROOM_MODE"] == "token"


def test04b_run_refuses_to_route_when_build_drifts_from_pin():
    """C8 kill switch.

    An unverified build is how headroom#2085 turned one session into 36% of a weekly cap.
    Losing compression is cheap; losing the prompt cache is not — so drift falls back to
    plain claude rather than routing.
    """
    _seed_config()
    captured = {}
    with mock.patch.object(cli_mod, "hr_version", return_value="0.31.0"), \
         mock.patch.object(cli_mod, "hr_proxy_up") as up, \
         mock.patch("mcpm_compression.cli.os.execvpe",
                    side_effect=lambda f, a, e: captured.update(env=e, argv=a)):
        res = CliRunner().invoke(cli_mod.run, ["--cwd", "/x/agent-batch/run", "--", "--version"])

    assert res.exit_code == 0, res.output
    up.assert_not_called()                                # never started a proxy
    assert "ANTHROPIC_BASE_URL" not in captured["env"]    # never routed
    assert captured["argv"] == ["claude", "--version"]    # still launched claude


def test04d_run_records_what_it_actually_did():
    """The ledger is the only record of whether turns went through the proxy.

    Claude Code's transcript carries the billed usage but nothing about the endpoint, so if
    `run` mislabels a launch, `verify` credits headroom for turns it never touched — or
    blames it for turns it never saw.
    """
    cfg = _seed_config()
    seen = []
    with _at_pin(cfg), \
         mock.patch.object(cli_mod, "append_launch", side_effect=lambda **kw: seen.append(kw)), \
         mock.patch.object(cli_mod, "hr_proxy_up", return_value=(True, "ok")), \
         mock.patch("mcpm_compression.cli.os.execvpe"):
        CliRunner().invoke(cli_mod.run, ["--cwd", "/x/agent-batch/run", "--", "--version"])
    assert seen and seen[0]["routed"] is True
    assert seen[0]["preset"] == "agent" and seen[0]["port"] == AGENT_PORT

    # Kill switch fired → the turns did NOT go through the proxy.
    seen.clear()
    with mock.patch.object(cli_mod, "hr_version", return_value="0.31.0"), \
         mock.patch.object(cli_mod, "append_launch", side_effect=lambda **kw: seen.append(kw)), \
         mock.patch("mcpm_compression.cli.os.execvpe"):
        CliRunner().invoke(cli_mod.run, ["--cwd", "/x/agent-batch/run", "--", "--version"])
    assert seen and seen[0]["routed"] is False


def test04e_failed_proxy_launches_plain_and_is_not_credited():
    """A proxy we couldn't start is not a proxy we routed through.

    The earlier code warned and then routed anyway — pointing ANTHROPIC_BASE_URL at a dead
    port, which breaks claude outright and would have been logged as a headroom session.
    """
    cfg = _seed_config()
    seen = []
    captured = {}
    with _at_pin(cfg), \
         mock.patch.object(cli_mod, "append_launch", side_effect=lambda **kw: seen.append(kw)), \
         mock.patch.object(cli_mod, "hr_proxy_up", return_value=(False, "did not become ready")), \
         mock.patch("mcpm_compression.cli.os.execvpe",
                    side_effect=lambda f, a, e: captured.update(env=e)):
        res = CliRunner().invoke(cli_mod.run, ["--cwd", "/x/agent-batch/run", "--", "--version"])

    assert res.exit_code == 0, res.output
    assert "ANTHROPIC_BASE_URL" not in captured["env"]   # never point at a dead proxy
    assert seen and seen[0]["routed"] is False           # never credited to headroom


def test04c_force_routes_through_a_drifted_build():
    _seed_config()
    captured = {}
    with mock.patch.object(cli_mod, "hr_version", return_value="0.31.0"), \
         mock.patch.object(cli_mod, "hr_proxy_up", return_value=(True, "ok")) as up, \
         mock.patch("mcpm_compression.cli.os.execvpe",
                    side_effect=lambda f, a, e: captured.update(env=e)):
        res = CliRunner().invoke(
            cli_mod.run, ["--cwd", "/x/agent-batch/run", "--force", "--", "--version"])

    assert res.exit_code == 0, res.output
    up.assert_called_once()
    assert captured["env"]["ANTHROPIC_BASE_URL"] == f"http://127.0.0.1:{AGENT_PORT}"


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
