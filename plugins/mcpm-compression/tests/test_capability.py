"""Capability scan + posture sealing (no live headroom, no network)."""
from __future__ import annotations

from unittest import mock

from mcpm_compression import capability as cap
from mcpm_compression.schema import KnobSpec


def test01_scan_counts_only_genuine_env_reads(tmp_path):
    """A knob named in help text or a docstring is not a knob the build reads.

    headroom's own CLI help still advertises code-aware as "Default: disabled" on builds
    where it isn't, so matching bare string literals over-reports badly.
    """
    (tmp_path / "m.py").write_text(
        'HELP = "Set HEADROOM_MENTIONED_ONLY=1 to enable."\n'
        '# HEADROOM_IN_A_COMMENT\n'
        'a = os.environ.get("HEADROOM_READ_A", "")\n'
        'b = _get_env_bool("HEADROOM_READ_B", True)\n'
        'c = os.environ["HEADROOM_READ_C"]\n'
    )
    assert cap.read_knobs(tmp_path) == {"HEADROOM_READ_A", "HEADROOM_READ_B", "HEADROOM_READ_C"}


def test02_inert_maps_the_vendors_own_broken_knob(tmp_path):
    """headroom's `agent-savings` emits HEADROOM_FORCE_KOMPRESS but reads
    HEADROOM_FORCE_KOMPRESS_ALL, so exporting its output verbatim silently does nothing."""
    (tmp_path / "m.py").write_text('x = os.environ.get("HEADROOM_FORCE_KOMPRESS_ALL", "")\n')
    inert = cap.inert_for({"HEADROOM_FORCE_KOMPRESS": KnobSpec(value="1")}, tmp_path)
    assert inert == {"HEADROOM_FORCE_KOMPRESS": "HEADROOM_FORCE_KOMPRESS_ALL"}


def test03_unlocatable_build_reports_nothing_inert(tmp_path):
    """An empty scan must never read as 'nothing works' — that would flag every declared
    knob as inert and send you deleting a correct policy."""
    assert cap.inert_for({"HEADROOM_ANYTHING": KnobSpec(value="1")}, tmp_path / "nope") == {}


def test04_env_rendering_refuses_to_invent_a_value_for_unset():
    # `None` in /health.config means unset — a distinct state from any literal. Exporting
    # HEADROOM_PROTECT_RECENT="" is not the same as never setting it.
    assert cap.as_env_value(None) is None
    assert cap.as_env_value(False) == "0"
    assert cap.as_env_value(True) == "1"
    assert cap.as_env_value(50) == "50"
    assert cap.as_env_value("strict") == "strict"


def test05_unsealed_splits_declarable_from_unsealable():
    live = {
        "compress_user_messages": False,   # declarable → policy can pin it
        "max_items_after_crush": 50,       # declarable
        "accuracy_guard": None,            # unset → unsealable
        "protect_recent": None,            # unset → unsealable
    }
    with mock.patch.object(cap, "effective_config", return_value=live):
        unsealed = cap.unsealed_for({}, 8787)
    declarable, unset = cap.split_unsealed(unsealed)
    assert declarable == {"HEADROOM_COMPRESS_USER_MESSAGES": "0", "HEADROOM_MAX_ITEMS": "50"}
    assert set(unset) == {"HEADROOM_ACCURACY_GUARD", "HEADROOM_PROTECT_RECENT"}


def test06_declared_knobs_are_not_reported_unsealed():
    live = {"compress_user_messages": False, "max_items_after_crush": 50}
    declared = {"HEADROOM_COMPRESS_USER_MESSAGES": KnobSpec(value="0", source="policy")}
    with mock.patch.object(cap, "effective_config", return_value=live):
        unsealed = cap.unsealed_for(declared, 8787)
    assert "HEADROOM_COMPRESS_USER_MESSAGES" not in unsealed
    assert "HEADROOM_MAX_ITEMS" in unsealed


def test07_no_proxy_means_no_claim_about_the_posture():
    # /health is the only truthful source for what a build actually runs; with no proxy we
    # report nothing rather than guessing from the config file.
    with mock.patch.object(cap, "effective_config", return_value={}):
        assert cap.unsealed_for({}, 8787) == {}
