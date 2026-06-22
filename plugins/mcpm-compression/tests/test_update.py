"""Tests for the headroom update mechanism (version tracking + `update` command)."""
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


def test01_version_tuple_orders_correctly():
    assert hr.version_tuple("0.27.0") > hr.version_tuple("0.26.0")
    assert hr.version_tuple("0.27.0") == hr.version_tuple("0.27.0")
    assert hr.version_tuple(None) == ()
    assert hr.version_tuple("garbage") == ()
    # below-contract is detectable
    assert hr.version_tuple("0.26.0") < hr.version_tuple(hr.CONTRACT_VERSION)


def test02_contract_version_is_floor():
    assert hr.version_tuple(hr.MIN_VERSION) <= hr.version_tuple(hr.CONTRACT_VERSION)


def test03_upgrade_no_uv_is_safe_noop():
    with mock.patch.object(hr, "version", return_value="0.27.0"), \
         mock.patch("mcpm_compression.providers.headroom_runtime.shutil.which", return_value=None):
        ok, detail, before, after = hr.upgrade()
    assert ok is False and "uv" in detail and before == after == "0.27.0"


def test04_update_command_upgrades_then_resnapshots():
    # Seed a config whose agent preset env is empty → update must refill it.
    cfg = CompressionConfig(provider="headroom")
    cfg.presets["agent"].env = {}
    save_config(cfg)

    fake_env = {"HEADROOM_MODE": "token", "HEADROOM_SAVINGS_PROFILE": "agent-90"}
    with mock.patch.object(cli_mod, "hr_upgrade", return_value=(True, "upgraded 0.27.0 → 0.28.0", "0.27.0", "0.28.0")), \
         mock.patch.object(cli_mod, "snapshot_profile_env", return_value=fake_env) as snap:
        res = CliRunner().invoke(cli_mod.update, [])

    assert res.exit_code == 0, res.output
    snap.assert_called()  # re-snapshotted
    assert "restart proxies" in res.output  # version changed → restart hint
    after = load_config()
    assert after.presets["agent"].env == fake_env  # config refilled from the new binary


def test05_update_aborts_cleanly_on_failed_upgrade():
    with mock.patch.object(cli_mod, "hr_upgrade", return_value=(False, "uv tool upgrade failed", "0.27.0", "0.27.0")), \
         mock.patch.object(cli_mod, "snapshot_profile_env") as snap:
        res = CliRunner().invoke(cli_mod.update, [])
    assert res.exit_code == 0, res.output  # reports, doesn't crash
    snap.assert_not_called()  # no re-snapshot when the upgrade failed
