"""Cache measurement from Claude Code transcripts (no network, synthetic fixtures)."""
from __future__ import annotations

import json

from mcpm_compression.verify import measure, partition_by_pin, schema_ok


def _session(tmp_path, name, turns, read, create):
    p = tmp_path / f"{name}.jsonl"
    with p.open("w") as fh:
        for _ in range(turns):
            fh.write(json.dumps({"message": {"usage": {
                "input_tokens": 2,
                "cache_read_input_tokens": read,
                "cache_creation_input_tokens": create,
                "output_tokens": 100,
            }}}) + "\n")
    return p


def test01_healthy_cache_passes(tmp_path):
    # Mirrors the measured baseline: reads dwarf writes.
    p = _session(tmp_path, "healthy", 10, read=19000, create=700)
    m = measure([p])
    assert m.sessions == 1 and m.turns == 10
    assert m.read_ratio > 0.96
    ok, _ = m.verdict()
    assert ok


def test02_busted_prefix_fails(tmp_path):
    """headroom#2085 shape: ~4.4x cache-write inflation drags the ratio under the floor."""
    p = _session(tmp_path, "busted", 10, read=19000, create=700 * 4.4 * 10)
    m = measure([p])
    ok, detail = m.verdict()
    assert not ok and "busted" in detail


def test03_short_sessions_are_ignored(tmp_path):
    # A 2-turn session says more about startup than about caching.
    p = _session(tmp_path, "short", 2, read=100, create=100)
    assert measure([p]).sessions == 0


def test04_no_cache_data_never_passes_silently(tmp_path):
    p = tmp_path / "empty.jsonl"
    p.write_text(json.dumps({"message": {"content": "no usage here"}}) + "\n")
    m = measure([p])
    ok, detail = m.verdict()
    assert not ok and "no cache data" in detail


def test05_partial_trailing_line_is_tolerated(tmp_path):
    # Transcripts are appended to live; the tail can be half-written.
    p = _session(tmp_path, "live", 6, read=9000, create=300)
    with p.open("a") as fh:
        fh.write('{"message": {"usage": {"cache_read')
    assert measure([p]).turns == 6


def test06_schema_ok_detects_missing_fields(tmp_path):
    good = _session(tmp_path, "good", 6, read=1, create=1)
    assert schema_ok([good])
    bad = tmp_path / "bad.jsonl"
    bad.write_text(json.dumps({"message": {"usage": {"input_tokens": 5}}}) + "\n")
    # If Claude Code stops writing cache_*, measure() would return zeros — which reads as a
    # total cache collapse rather than a missing field. Callers must skip, not report.
    assert not schema_ok([bad])


def _session_at(tmp_path, name, cwd, ts, turns=6, read=9000, create=300):
    # session_origin() reads timestamp + cwd from the first record; carry them on every turn.
    p = tmp_path / f"{name}.jsonl"
    with p.open("w") as fh:
        for _ in range(turns):
            fh.write(json.dumps({
                "timestamp": ts,
                "cwd": cwd,
                "message": {"usage": {
                    "input_tokens": 2,
                    "cache_read_input_tokens": read,
                    "cache_creation_input_tokens": create,
                    "output_tokens": 100,
                }},
            }) + "\n")
    return p


def test07_partition_by_pin_groups_proxied_by_version(tmp_path):
    launches = [
        {"ts": "2026-07-01T10:00:00+00:00", "cwd": "/work/a", "routed": True, "pin": "0.29.0"},
        {"ts": "2026-07-01T11:00:00+00:00", "cwd": "/work/b", "routed": True, "pin": "0.32.0"},
        {"ts": "2026-07-01T12:00:00+00:00", "cwd": "/work/c", "routed": False, "pin": "0.29.0"},
    ]
    a = _session_at(tmp_path, "a", "/work/a", "2026-07-01T10:00:02+00:00")
    b = _session_at(tmp_path, "b", "/work/b", "2026-07-01T11:00:02+00:00")
    _session_at(tmp_path, "c", "/work/c", "2026-07-01T12:00:02+00:00")  # plain — must not appear

    by = partition_by_pin([a, b], launches=launches)
    by_all = partition_by_pin([a, b, tmp_path / "c.jsonl"], launches=launches)
    assert by["0.29.0"] == [a] and by["0.32.0"] == [b]
    assert set(by_all) == {"0.29.0", "0.32.0"}  # routed=False (plain) is excluded


def test08_partition_by_pin_labels_missing_pin_unknown(tmp_path):
    launches = [{"ts": "2026-07-01T10:00:00+00:00", "cwd": "/w", "routed": True}]  # no pin
    s = _session_at(tmp_path, "s", "/w", "2026-07-01T10:00:03+00:00")
    by = partition_by_pin([s], launches=launches)
    assert list(by) == ["unknown"] and by["unknown"] == [s]
