"""Measure real prompt-cache behaviour from Claude Code's own transcripts.

Why this exists: headroom's cache safety cannot be established by reading its source or
its changelog. 0.31.0's proxy is *written* to preserve the prefix (append-only replay,
full passthrough when replay isn't provable) and still shipped with headroom#2085 — a
measured 4.4x cache-write inflation under Claude Code. The only thing that settles it is
provider-billed usage.

Claude Code writes that usage into its session JSONL: `cache_read_input_tokens` and
`cache_creation_input_tokens` are what Anthropic actually billed for the bytes actually
sent. That makes it ground truth, free, and drawn from real work — the same evidence
#2085 was built on. We never read headroom's own /stats or dashboard: its savings
accounting was wrong in four distinct ways across 0.28-0.31 (cached requests priced at
$0 (#1429), disagreeing dashboard denominators (#1653), cache-write premiums not
subtracted from net savings (#1800), cache-mode history dropped entirely).

The headline metric is the read ratio: read / (read + create). A cache that is working
reads far more than it writes; a busted prefix converts cheap reads (0.1x) into expensive
writes (1.25x), so the ratio falls even as raw token counts look fine.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional  # noqa: F401 — Dict/List used in annotations

# Sessions below this many billed turns say more about startup than about caching.
MIN_TURNS = 5

# Thresholds. Defaults are derived from the measured headroom-off baseline on this
# machine (96.5% read ratio, 27.6x read:write over 203 sessions / 72k turns). A proxy
# that cannot hold these is costing more than it saves, whatever it reports.
FAIL_READ_RATIO = 0.90
FAIL_READ_WRITE = 15.0


@dataclass
class Metrics:
    sessions: int = 0
    turns: int = 0
    cache_read: int = 0
    cache_create: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    per_session: List[float] = field(default_factory=list)

    @property
    def read_ratio(self) -> Optional[float]:
        total = self.cache_read + self.cache_create
        return (self.cache_read / total) if total else None

    @property
    def read_write(self) -> Optional[float]:
        return (self.cache_read / self.cache_create) if self.cache_create else None

    def verdict(self) -> tuple[bool, str]:
        """Pass/fail against the thresholds. Unknown data never passes silently."""
        if self.read_ratio is None:
            return (False, "no cache data in the sampled sessions")
        if self.read_ratio < FAIL_READ_RATIO:
            return (False, f"read ratio {self.read_ratio:.1%} < {FAIL_READ_RATIO:.0%} "
                           f"— prefix is being busted")
        if self.read_write is not None and self.read_write < FAIL_READ_WRITE:
            return (False, f"read:write {self.read_write:.1f}x < {FAIL_READ_WRITE:.0f}x "
                           f"— too much cache re-creation")
        return (True, f"read ratio {self.read_ratio:.1%}, read:write "
                      f"{self.read_write:.1f}x" if self.read_write else "ok")


def transcript_root() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")) / "projects"


def iter_transcripts(root: Optional[Path] = None) -> Iterable[Path]:
    root = root or transcript_root()
    if not root.is_dir():
        return []
    return sorted(root.glob("*/*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)


def _records(path: Path) -> Iterable[Dict]:
    """Yield each parsed record. Tolerates partial lines — transcripts are appended to
    live, so the tail can be a half-written record."""
    try:
        fh = path.open(errors="ignore")
    except OSError:
        return
    with fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except (ValueError, TypeError):
                continue
            if isinstance(rec, dict):
                yield rec


def _usage_blocks(path: Path) -> Iterable[Dict]:
    """Yield each turn's billed usage block."""
    for rec in _records(path):
        usage = (rec.get("message") or {}).get("usage")
        if isinstance(usage, dict):
            yield usage


def session_origin(path: Path) -> tuple:
    """(start, cwd) from the session's first record — the launch identity `verify` matches
    against the ledger. Returns (None, None) when the transcript doesn't carry them."""
    from .ledger import parse_ts

    for rec in _records(path):
        ts = parse_ts(rec.get("timestamp"))
        cwd = rec.get("cwd")
        if ts and cwd:
            return (ts, cwd)
    return (None, None)


def measure(paths: Iterable[Path], min_turns: int = MIN_TURNS) -> Metrics:
    """Aggregate billed cache usage across sessions."""
    m = Metrics()
    for path in paths:
        rd = cw = inp = out = turns = 0
        for u in _usage_blocks(path):
            rd += u.get("cache_read_input_tokens") or 0
            cw += u.get("cache_creation_input_tokens") or 0
            inp += u.get("input_tokens") or 0
            out += u.get("output_tokens") or 0
            turns += 1
        if turns < min_turns or (rd + cw) == 0:
            continue
        m.sessions += 1
        m.turns += turns
        m.cache_read += rd
        m.cache_create += cw
        m.input_tokens += inp
        m.output_tokens += out
        m.per_session.append(rd / (rd + cw))
    return m


def partition(paths: Iterable[Path], launches: Optional[List[Dict]] = None) -> Dict[str, List[Path]]:
    """Split sessions into `proxied` / `plain` / `unattributed` using the launch ledger.

    - **proxied**: matched a launch that actually routed through the proxy.
    - **plain**: matched a launch that deliberately did *not* route (provider `none`, a
      context rule, or the kill switch refusing a drifted build). A true control group —
      same tooling, same person, no proxy.
    - **unattributed**: no matching launch. Everything predating the ledger lands here, as
      does any session started outside `run`. Kept as its own bucket rather than folded
      into `plain`: it is the honest baseline, but it is not a controlled control.
    """
    from .ledger import attribute, read_launches

    recs = read_launches() if launches is None else launches
    out: Dict[str, List[Path]] = {"proxied": [], "plain": [], "unattributed": []}
    for p in paths:
        start, cwd = session_origin(p)
        match = attribute(start, cwd, recs)
        if match is None:
            out["unattributed"].append(p)
        elif match.get("routed"):
            out["proxied"].append(p)
        else:
            out["plain"].append(p)
    return out


def compare(a: Metrics, b: Metrics) -> Optional[float]:
    """Percentage-point change in read ratio, b relative to a. None if either is empty."""
    if a.read_ratio is None or b.read_ratio is None:
        return None
    return (b.read_ratio - a.read_ratio) * 100


def schema_ok(paths: Iterable[Path]) -> bool:
    """Do transcripts still carry the fields we depend on?

    Claude Code's format is not a contract we control. If it moves, `measure` would return
    zeros — which would read as a catastrophic cache failure rather than a missing field.
    Callers use this to skip loudly instead of reporting a confidently wrong number.
    """
    for path in paths:
        for u in _usage_blocks(path):
            return "cache_read_input_tokens" in u or "cache_creation_input_tokens" in u
    return False
