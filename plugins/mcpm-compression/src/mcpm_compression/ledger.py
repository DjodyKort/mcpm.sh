"""A record of what `run` actually launched, so `verify` can partition proxied vs plain.

Claude Code's transcripts carry the billed cache usage but nothing about the endpoint —
no base URL, no proxy marker. So a transcript alone cannot say whether its turns went
through headroom. Without that, `verify` can only report one blended number, and a blended
number cannot answer "did headroom help?".

`run` is the one place that knows: it resolved the policy, it decided whether to route, and
it exec'd claude. So it appends a line here first. `verify` then matches sessions to
launches on (cwd, start time) — the transcript's first record carries both.

Deliberately append-only JSONL: a launch is a historical fact, and a measurement you can
silently rewrite is not evidence.

Not synced. mcpm-sync carries `compression.json` (the policy) by explicit path, so this
file stays put — which is right: it describes what *this* machine launched against *this*
machine's binary. Merging several machines' launches into one bucket would silently mix
runtimes into a single number.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .paths import compression_config_path

# How long after a launch a session may start and still be attributed to it. `run` execs
# claude immediately, so the real gap is ~1-3s; 90s is slack for a cold start without
# being wide enough to swallow a separate launch in the same directory.
MATCH_WINDOW = timedelta(seconds=90)


def ledger_path() -> Path:
    return compression_config_path().parent / "compression-launches.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def norm_cwd(p: str) -> str:
    """Normalise a directory for matching, resolving symlinks.

    Both sides must agree or a session silently falls out of its bucket. On macOS `/tmp`
    is a symlink to `/private/tmp`, and `run` and Claude Code need not spell it the same
    way — `abspath` would leave them unequal and quietly drop every proxied session into
    `unattributed`, which reads as "headroom produced no data" rather than "the match
    broke".
    """
    try:
        return os.path.realpath(os.path.abspath(p or ""))
    except OSError:
        return os.path.abspath(p or "")


def append_launch(*, cwd: str, provider: str, preset: str, routed: bool,
                  port: Optional[int] = None, pin: Optional[str] = None) -> None:
    """Record one launch. Never raises — a failed write must not stop you launching claude."""
    rec = {
        "ts": _now(),
        "cwd": norm_cwd(cwd),
        "provider": provider,
        "preset": preset,
        "routed": bool(routed),
        "port": port,
        "pin": pin,
    }
    try:
        path = ledger_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as fh:
            fh.write(json.dumps(rec) + "\n")
    except OSError:
        pass


def read_launches(path: Optional[Path] = None) -> List[Dict]:
    p = path or ledger_path()
    if not p.exists():
        return []
    out: List[Dict] = []
    try:
        fh = p.open(errors="ignore")
    except OSError:
        return []
    with fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except (ValueError, TypeError):
                continue  # tolerate a torn final line
            if isinstance(rec, dict) and rec.get("ts"):
                out.append(rec)
    return out


def parse_ts(v) -> Optional[datetime]:
    """Parse an ISO timestamp to an aware datetime. Claude Code writes '...Z'."""
    if not isinstance(v, str) or not v:
        return None
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def attribute(session_start: Optional[datetime], session_cwd: Optional[str],
              launches: Iterable[Dict]) -> Optional[Dict]:
    """The launch a session belongs to, or None if it can't be attributed.

    Matches on identical cwd and a start inside MATCH_WINDOW after the launch, taking the
    latest qualifying launch. Returning None is a real answer — a session launched some
    other way (plain `claude`, an IDE, a resumed session) is *unattributed*, not "plain".
    Guessing here would quietly move sessions into whichever bucket flatters the result.
    """
    if session_start is None or not session_cwd:
        return None
    target = norm_cwd(session_cwd)
    best = None
    best_ts = None
    for rec in launches:
        if norm_cwd(rec.get("cwd") or "") != target:
            continue
        ts = parse_ts(rec.get("ts"))
        if ts is None:
            continue
        delta = session_start - ts
        if timedelta(0) <= delta <= MATCH_WINDOW and (best_ts is None or ts > best_ts):
            best, best_ts = rec, ts
    return best
