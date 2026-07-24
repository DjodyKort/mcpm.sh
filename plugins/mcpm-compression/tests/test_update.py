"""`update` — deliberate pin bump with auto-detect. Sandbox the config dir; nothing spawns."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest import mock

os.environ["MCPM_CONFIG_DIR"] = str(Path(tempfile.mkdtemp(prefix="mcpm-comp-upd-")))

from click.testing import CliRunner  # noqa: E402

from mcpm_compression import cli as cli_mod  # noqa: E402
from mcpm_compression.config import load_config, save_config  # noqa: E402
from mcpm_compression.providers import headroom_runtime as hr  # noqa: E402
from mcpm_compression.schema import CompressionConfig  # noqa: E402


def test01_latest_version_reads_pypi_info_version():
    payload = b'{"info": {"version": "0.31.0"}, "releases": {}}'
    ctx = mock.MagicMock()
    ctx.__enter__.return_value.read.return_value = payload
    with mock.patch("mcpm_compression.providers.headroom_runtime.urllib.request.urlopen",
                    return_value=ctx):
        assert hr.latest_version("headroom-ai") == "0.31.0"


def test02_latest_version_returns_none_when_unreachable():
    with mock.patch("mcpm_compression.providers.headroom_runtime.urllib.request.urlopen",
                    side_effect=OSError("offline")):
        assert hr.latest_version() is None


def test03_bare_update_previews_latest_without_touching_config():
    save_config(CompressionConfig(provider="headroom"))
    with mock.patch.object(cli_mod, "hr_latest", return_value="0.31.0"), \
         mock.patch.object(cli_mod, "hr_install") as inst:
        res = CliRunner().invoke(cli_mod.update, [])
    assert res.exit_code == 0, res.output
    assert "0.31.0" in res.output and "preview only" in res.output
    inst.assert_not_called()
    assert load_config().provider_version.pin != "0.31.0"  # preview must not move the pin


def test04_accept_moves_pin_installs_and_refreshes():
    save_config(CompressionConfig(provider="headroom"))
    with mock.patch.object(cli_mod, "hr_latest", return_value="0.31.0"), \
         mock.patch.object(cli_mod, "hr_install",
                           return_value=(True, "0.29.0 → 0.31.0", "0.29.0", "0.31.0")) as inst, \
         mock.patch.object(cli_mod, "_refresh_snapshots") as refresh:
        res = CliRunner().invoke(cli_mod.update, ["--latest", "--accept"])
    assert res.exit_code == 0, res.output
    assert load_config().provider_version.pin == "0.31.0"
    assert inst.call_args[0][0] == "headroom-ai[proxy,code,ml]==0.31.0"  # exact, with extras
    refresh.assert_called_once()
    assert "proxy restart" in res.output  # version moved → restart reminder


def test05_to_names_an_exact_version_and_skips_pypi():
    save_config(CompressionConfig(provider="headroom"))
    with mock.patch.object(cli_mod, "hr_latest") as latest, \
         mock.patch.object(cli_mod, "hr_install",
                           return_value=(True, "ok", "0.29.0", "0.30.0")), \
         mock.patch.object(cli_mod, "_refresh_snapshots"):
        res = CliRunner().invoke(cli_mod.update, ["--to", "0.30.0", "--accept"])
    assert res.exit_code == 0, res.output
    latest.assert_not_called()  # explicit target never hits the network
    assert load_config().provider_version.pin == "0.30.0"


def test06_to_and_latest_together_is_rejected():
    save_config(CompressionConfig(provider="headroom"))
    res = CliRunner().invoke(cli_mod.update, ["--to", "0.30.0", "--latest"])
    assert res.exit_code == 2
    assert "not both" in res.output


def test07_unresolvable_latest_fails_loud():
    save_config(CompressionConfig(provider="headroom"))
    with mock.patch.object(cli_mod, "hr_latest", return_value=None):
        res = CliRunner().invoke(cli_mod.update, ["--latest", "--accept"])
    assert res.exit_code == 1
    assert "could not resolve" in res.output


def test08_unparseable_target_is_rejected_before_install():
    save_config(CompressionConfig(provider="headroom"))
    with mock.patch.object(cli_mod, "hr_install") as inst:
        res = CliRunner().invoke(cli_mod.update, ["--to", "garbage", "--accept"])
    assert res.exit_code == 2
    inst.assert_not_called()


def test09_failed_install_aborts_and_does_not_report_restart():
    save_config(CompressionConfig(provider="headroom"))
    with mock.patch.object(cli_mod, "hr_latest", return_value="0.31.0"), \
         mock.patch.object(cli_mod, "hr_install",
                           return_value=(False, "uv tool install failed", "0.29.0", "0.29.0")), \
         mock.patch.object(cli_mod, "_refresh_snapshots") as refresh:
        res = CliRunner().invoke(cli_mod.update, ["--latest", "--accept"])
    assert res.exit_code == 1
    refresh.assert_not_called()
    assert "proxy restart" not in res.output
