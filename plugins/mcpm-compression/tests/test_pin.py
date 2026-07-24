"""Pin resolution + install. Sandbox the config dir before import; nothing is spawned."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest import mock

os.environ["MCPM_CONFIG_DIR"] = str(Path(tempfile.mkdtemp(prefix="mcpm-comp-pin-")))

from click.testing import CliRunner  # noqa: E402

from mcpm_compression import cli as cli_mod  # noqa: E402
from mcpm_compression.config import load_config, save_config  # noqa: E402
from mcpm_compression.providers import headroom_runtime as hr  # noqa: E402
from mcpm_compression.schema import CompressionConfig  # noqa: E402


def test01_requirement_is_exact_with_extras():
    cfg = CompressionConfig()
    cfg.provider_version.pin = "0.29.0"
    assert cfg.provider_version.requirement() == "headroom-ai[proxy,code,ml]==0.29.0"


def test02_install_shells_out_to_exact_requirement():
    """The old path ran `uv tool upgrade`, which resolves to whatever is newest that day.
    Installing must name the exact version instead."""
    fake = mock.Mock(returncode=0, stdout="", stderr="")
    with mock.patch.object(hr, "version", side_effect=["0.31.0", "0.29.0"]), \
         mock.patch("mcpm_compression.providers.headroom_runtime.shutil.which",
                    return_value="/usr/bin/uv"), \
         mock.patch("mcpm_compression.providers.headroom_runtime.subprocess.run",
                    return_value=fake) as run:
        ok, detail, before, after = hr.install("headroom-ai[proxy]==0.29.0")

    assert ok and before == "0.31.0" and after == "0.29.0"
    argv = run.call_args[0][0]
    assert argv[:3] == ["uv", "tool", "install"]
    assert argv[3] == "headroom-ai[proxy]==0.29.0"
    assert "--force" in argv          # downgrades must be allowed, not just upgrades
    assert "upgrade" not in argv      # never float


def test03_install_without_uv_is_a_safe_noop():
    with mock.patch.object(hr, "version", return_value="0.29.0"), \
         mock.patch("mcpm_compression.providers.headroom_runtime.shutil.which",
                    return_value=None):
        ok, detail, before, after = hr.install("headroom-ai==0.29.0")
    assert ok is False and "uv" in detail and before == after == "0.29.0"


def test04_pin_command_sets_and_persists():
    save_config(CompressionConfig(provider="headroom"))
    with mock.patch.object(cli_mod, "hr_version", return_value="0.31.0"):
        res = CliRunner().invoke(cli_mod.pin, ["0.30.0"])
    assert res.exit_code == 0, res.output
    assert load_config().provider_version.pin == "0.30.0"
    assert "drift" in res.output  # installed 0.31 != pin 0.30


def test04b_requirement_survives_rich_markup():
    """The extras marker reads as Rich markup.

    Printed unescaped, `headroom-ai[proxy,code,ml]==0.29.0` renders as
    `headroom-ai==0.29.0` — a requirement that installs headroom without its proxy. The
    displayed command has to be the one that works.
    """
    save_config(CompressionConfig(provider="headroom"))
    with mock.patch.object(cli_mod, "hr_version", return_value="0.29.0"):
        res = CliRunner().invoke(cli_mod.pin, [])
    assert "[proxy,code,ml]" in res.output, res.output


def test05_pin_reports_match_without_installing():
    cfg = CompressionConfig(provider="headroom")
    save_config(cfg)
    with mock.patch.object(cli_mod, "hr_version", return_value=cfg.provider_version.pin), \
         mock.patch.object(cli_mod, "hr_install") as inst:
        res = CliRunner().invoke(cli_mod.pin, [])
    assert res.exit_code == 0, res.output
    inst.assert_not_called()  # read-only unless --install


def test05b_refresh_preserves_policy_knobs_and_replaces_profile_knobs():
    """Regression: a re-snapshot must not delete our own declarations.

    Found by running `pin --install --refresh` for real: it replaced preset.knobs wholesale
    with the agent-savings output, silently dropping HEADROOM_CODE_AWARE_ENABLED=0 and
    HEADROOM_INTERCEPT_ENABLED=0 — the very declarations that fix F3. An undeclared knob is
    a knob the vendor's default owns, so dropping one resurrects the bug the pin exists to
    prevent.
    """
    from mcpm_compression.schema import CompressionPreset, KnobSpec

    cfg = CompressionConfig(provider="headroom")
    cfg.presets = {"agent": CompressionPreset(
        savings_profile="agent-90",
        knobs={
            # ours — must survive, and outrank the profile's value for the same knob
            "HEADROOM_CODE_AWARE_ENABLED": KnobSpec(value="0", source="policy"),
            # vendor's — must be replaced by the new snapshot
            "HEADROOM_MAX_ITEMS": KnobSpec(value="99", source="profile"),
            # vendor's, absent from the new profile — may be dropped
            "HEADROOM_GONE": KnobSpec(value="1", source="profile"),
        },
    )}
    new_profile = {"HEADROOM_MAX_ITEMS": "8", "HEADROOM_CODE_AWARE_ENABLED": "1"}
    with mock.patch.object(cli_mod, "snapshot_profile_env", return_value=new_profile), \
         mock.patch.object(cli_mod, "hr_version", return_value="0.29.0"), \
         mock.patch.object(cli_mod, "save_config"):
        cli_mod._refresh_snapshots(cfg)

    knobs = cfg.presets["agent"].knobs
    assert knobs["HEADROOM_CODE_AWARE_ENABLED"].value == "0"   # policy survived AND won
    assert knobs["HEADROOM_CODE_AWARE_ENABLED"].source == "policy"
    assert knobs["HEADROOM_MAX_ITEMS"].value == "8"            # profile refreshed
    assert "HEADROOM_GONE" not in knobs                        # stale profile knob dropped
    assert cfg.presets["agent"].snapshot_version == "0.29.0"


def test06_snapshot_refuses_to_invent_an_env_without_the_binary():
    """No offline fallback by design.

    A bundled constant made one preset name resolve to two runtimes depending on whether
    headroom was on PATH — the drift the pin exists to prevent.
    """
    with mock.patch.object(hr, "_headroom", return_value=None):
        try:
            hr.snapshot_profile_env("agent-90")
        except hr.HeadroomUnavailable as e:
            assert "not on PATH" in str(e)
        else:
            raise AssertionError("expected HeadroomUnavailable rather than a guessed env")
