"""Launch ledger + proxied/plain partitioning (no network, synthetic transcripts)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from mcpm_compression.ledger import attribute, parse_ts
from mcpm_compression.verify import compare, measure, partition, session_origin

T0 = datetime(2026, 7, 15, 12, 0, 0, tzinfo=timezone.utc)


def _launch(ts, cwd, routed=True):
    return {"ts": ts.isoformat(), "cwd": cwd, "routed": routed,
            "provider": "headroom", "preset": "interactive"}


def _session(tmp_path, name, start, cwd, turns=8, read=9000, create=300):
    p = tmp_path / f"{name}.jsonl"
    with p.open("w") as fh:
        fh.write(json.dumps({"type": "mode", "timestamp": start.isoformat().replace("+00:00", "Z"),
                             "cwd": cwd, "sessionId": name}) + "\n")
        for _ in range(turns):
            fh.write(json.dumps({
                "timestamp": start.isoformat().replace("+00:00", "Z"), "cwd": cwd,
                "message": {"usage": {"cache_read_input_tokens": read,
                                      "cache_creation_input_tokens": create,
                                      "input_tokens": 2, "output_tokens": 50}}}) + "\n")
    return p


def test01_session_origin_reads_first_timestamp_and_cwd(tmp_path):
    p = _session(tmp_path, "s", T0, "/work/repo")
    start, cwd = session_origin(p)
    assert start == T0 and cwd == "/work/repo"


def test02_session_started_just_after_a_launch_is_attributed(tmp_path):
    launches = [_launch(T0, "/work/repo")]
    start = T0 + timedelta(seconds=3)
    assert attribute(start, "/work/repo", launches)["routed"] is True


def test03_different_cwd_never_matches():
    launches = [_launch(T0, "/work/repo")]
    assert attribute(T0 + timedelta(seconds=3), "/work/other", launches) is None


def test04_outside_the_window_never_matches():
    launches = [_launch(T0, "/work/repo")]
    assert attribute(T0 + timedelta(minutes=30), "/work/repo", launches) is None
    # A session that started BEFORE the launch cannot belong to it.
    assert attribute(T0 - timedelta(seconds=5), "/work/repo", launches) is None


def test05_partition_splits_three_ways(tmp_path):
    launches = [
        _launch(T0, "/work/proxied", routed=True),
        _launch(T0, "/work/plain", routed=False),   # run decided not to route
    ]
    a = _session(tmp_path, "a", T0 + timedelta(seconds=2), "/work/proxied")
    b = _session(tmp_path, "b", T0 + timedelta(seconds=2), "/work/plain")
    c = _session(tmp_path, "c", T0, "/work/never-launched-via-run")

    out = partition([a, b, c], launches=launches)
    assert out["proxied"] == [a]
    assert out["plain"] == [b]
    assert out["unattributed"] == [c]


def test06_unattributed_is_never_folded_into_plain(tmp_path):
    """Sessions predating the ledger are the honest baseline, not a control group.

    Counting them as `plain` would silently manufacture a control that never existed, and
    the whole point of partitioning is that the comparison is real.
    """
    s = _session(tmp_path, "old", T0, "/work/repo")
    out = partition([s], launches=[])
    assert out["unattributed"] == [s] and out["plain"] == []


def test07_compare_reports_read_ratio_delta_in_points(tmp_path):
    good = measure([_session(tmp_path, "g", T0, "/w", read=9700, create=300)])
    bad = measure([_session(tmp_path, "b", T0, "/w", read=8000, create=2000)])
    delta = compare(good, bad)          # good -> bad, ratio falls
    assert delta is not None and delta < -10
    assert compare(good, measure([])) is None   # no data -> no claim


def test08_symlinked_cwd_still_matches(tmp_path):
    """`/tmp` vs `/private/tmp` must not split a session out of its bucket.

    run resolves cwd via os.getcwd() (symlinks resolved); Claude Code need not spell it the
    same way. Matching on abspath would leave them unequal and drop every proxied session
    into `unattributed` — indistinguishable from headroom producing no data at all.
    """
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)

    # ledger recorded the resolved path; the transcript reports the symlinked one
    launches = [_launch(T0, str(real))]
    assert attribute(T0 + timedelta(seconds=2), str(link), launches) is not None
    # ...and the reverse
    launches = [_launch(T0, str(link))]
    assert attribute(T0 + timedelta(seconds=2), str(real), launches) is not None


def test09_parse_ts_handles_claude_code_z_suffix():
    assert parse_ts("2026-07-15T12:00:00.000Z") == datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
    assert parse_ts("") is None and parse_ts(None) is None and parse_ts("nonsense") is None
