"""Cache measurement from Claude Code transcripts (no network, synthetic fixtures)."""
from __future__ import annotations

import json

from mcpm_compression.verify import measure, schema_ok


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
