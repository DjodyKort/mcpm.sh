"""Version parsing + range matching.

Shared by the knob gate (`KnobSpec.applies`) and the known-issues registry. Deliberately
tiny: headroom publishes plain `X.Y.Z`, so a full PEP 440 implementation would be dead
weight and another dependency on the launch path.
"""
from __future__ import annotations

from typing import Optional, Tuple

_OPS = ("<=", ">=", "==", "!=", "<", ">")  # longest-first: "<=" must beat "<"


def version_tuple(v: Optional[str]) -> Tuple[int, ...]:
    """Parse 'X.Y.Z' to a comparable tuple; () for unknown/unparseable."""
    if not v:
        return ()
    parts = v.strip().split(".")[:3]
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        return ()


def _clause_matches(version: Tuple[int, ...], clause: str) -> bool:
    clause = clause.strip()
    if not clause or clause == "*":
        return True
    for op in _OPS:
        if clause.startswith(op):
            rhs = version_tuple(clause[len(op):])
            if not rhs:
                return False
            if op == "==":
                return version == rhs
            if op == "!=":
                return version != rhs
            if op == ">=":
                return version >= rhs
            if op == "<=":
                return version <= rhs
            if op == ">":
                return version > rhs
            return version < rhs
    # Bare version means exact match.
    rhs = version_tuple(clause)
    return bool(rhs) and version == rhs


def spec_matches(version: Optional[str], spec: str) -> bool:
    """Does `version` satisfy `spec`?

    `spec` is `*` or comma-separated clauses ANDed together, e.g. ">=0.30.0,<0.32.0".
    An unknown version matches only `*` — we never guess a build into a range, because a
    wrong guess would either hide a known issue or drop a knob.
    """
    spec = (spec or "*").strip()
    if spec == "*":
        return True
    parsed = version_tuple(version)
    if not parsed:
        return False
    return all(_clause_matches(parsed, c) for c in spec.split(",") if c.strip())
