#!/usr/bin/env python3
"""
sentinel.py — make "I looked and found nothing" impossible to confuse with "I could not look."

Built by Sophia, 2026-10-06, out of the instrument-failure catalogue
(PR-020, *The Instrument That Lies*). The core finding it encodes:

    An instrument rarely fails by returning a WRONG answer.
    It fails by returning a CONFIDENT, GREEN, WELL-FORMED answer
    about a thing it is not in fact observing.

Three primitives:

    Observed(v, src)   — a value that was actually read from its source
    Absent(src)        — the source was reached and did not yield it
    Unobservable(src)  — the source could NOT be reached

    `Absent` and `Unobservable` must NEVER render identically, and neither
    may be scored as a zero. A guard that turns "no data" into a tidy 0.000
    is a fabricated measurement wearing a number.

    Provenanced(text, spans) — text whose statements carry per-span origin,
    so a pruned/compressed span can be reported as LOST rather than silently
    omitted. This is the check the CLM paper (arXiv 2609.37725) does not have:
    a model that edits its own context returns exit 0, and "I removed it" and
    "I never had it" leave an identical, well-formed file.

Run: python3 sentinel.py --selftest
"""
from __future__ import annotations
import sys, json, re
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional


# ─────────────────────────────────────────────────────────────────────────────
# 1. THREE-STATE VALUES  (law 1: zero-matched and source-unavailable never share an output)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Observed:
    """The source was reached and yielded this value."""
    value: Any
    source: str
    def __repr__(self): return f"Observed({self.value!r}, <- {self.source})"

@dataclass(frozen=True)
class Absent:
    """The source was reached, and it does not contain the thing."""
    source: str
    def __repr__(self): return f"Absent(<- {self.source})"

@dataclass(frozen=True)
class Unobservable:
    """The source could NOT be reached. NOT the same as Absent."""
    source: str
    why: str = ""
    def __repr__(self): return f"Unobservable(<- {self.source}: {self.why})"


class FabricatedMeasurement(Exception):
    """Raised when a value that was never observed is about to be scored as data."""


def score(v, *, what: str = "value") -> float:
    """Score a value — and REFUSE to score one that was not observed (law 4).

    A division guard (`max(1, len(x))`) that turns 'no data' into a clean 0.000
    is not defensive programming; it is a fabricated measurement wearing a number.
    The gate goes BEFORE the arithmetic.
    """
    if isinstance(v, Observed):
        return float(v.value)
    if isinstance(v, (Absent, Unobservable)):
        raise FabricatedMeasurement(
            f"refusing to score {what}: {v!r} is not a measurement. "
            f"Return 'I COULD NOT MEASURE' instead of a figure."
        )
    raise FabricatedMeasurement(f"refusing to score {what}: bare {v!r} carries no provenance")


# ─────────────────────────────────────────────────────────────────────────────
# 2. THE MIRROR CHECK  (law 2: a check must be able to express the failure it exists to catch)
# ─────────────────────────────────────────────────────────────────────────────

def check(observed, expected: Iterable, *, name: str = "check") -> str:
    """A check that can go RED, and can say WHICH failure it saw.

    Three outcomes, and 'I did not look' is one of them:
        PASS   — observed matches expected
        FAIL   — observed mismatches expected
        UNKNOWN— the thing was not observable; this is NOT a pass
    """
    obs = list(observed)
    exp = list(expected)
    if not obs:
        return f"{name}: UNKNOWN — nothing was observed (this is not a pass)"
    if len(obs) != len(exp):
        return f"{name}: UNKNOWN — observed {len(obs)} items, expected {len(exp)}"
    if obs == exp:
        return f"{name}: PASS"
    return f"{name}: FAIL — {obs!r} != {exp!r}"


# ─────────────────────────────────────────────────────────────────────────────
# 3. PROVENANCE-TRACKED CONTEXT  (the check CLM lacks: a pruned span can be REPORTED, not silent)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Span:
    text: str
    origin: str          # "observed:<source>"  or  "asserted"  (never verified against its source)
    step: int = 0
    pruned_at: Optional[int] = None
    def observed(self) -> bool:
        return self.origin.startswith("observed:")

@dataclass
class Provenanced:
    """Context as a list of spans, each carrying its own origin.

    A compaction step may remove a span. What is FORBIDDEN is removing it
    silently: an unverified (asserted) span that is dropped must be REPORTABLE,
    because its absence may matter at a later step and its loss is invisible
    in the resulting (well-formed) file.
    """
    spans: list = field(default_factory=list)
    log: list = field(default_factory=list)

    def add(self, text: str, origin: str, step: int = 0):
        self.spans.append(Span(text, origin, step))

    def prune(self, match: str, step: int) -> list:
        """Remove spans whose text contains `match`. Returns the LOST report.

        The report is the whole point. A prune that returns nothing is the
        failure mode this exists to prevent.
        """
        lost, kept = [], []
        for s in self.spans:
            if match in s.text:
                s.pruned_at = step
                lost.append(s)
                if not s.observed():
                    self.log.append(
                        f"LOST: {s.text[:60]!r} (asserted, never verified; pruned at step {step})"
                    )
            else:
                kept.append(s)
        self.spans = kept
        return lost

    def render(self) -> str:
        """The well-formed file — which on its own tells you nothing was lost."""
        return "\n".join(s.text for s in self.spans)

    def report(self) -> str:
        return "\n".join(self.log) if self.log else "(no unverified loss recorded)"


# ─────────────────────────────────────────────────────────────────────────────
# SELF-TEST — and it must be able to go RED. Delete a guard and it fails.
# ─────────────────────────────────────────────────────────────────────────────

def _selftest() -> int:
    failures = []

    # law 1 / 4: emptiness must not score, and absence != unobservable
    try:
        score(Absent("/var/log/x"), what="log lines")
        failures.append("score() accepted Absent — it must refuse")
    except FabricatedMeasurement:
        pass
    try:
        score(Unobservable("192.168.0.44", "host down"), what="device")
        failures.append("score() accepted Unobservable — it must refuse")
    except FabricatedMeasurement:
        pass
    assert score(Observed(3, "counter")) == 3.0

    # law 1: the two non-values must not print the same
    assert repr(Absent("x")) != repr(Unobservable("x", "down")), \
        "Absent and Unobservable render identically — law 1 violated"

    # law 2: the check must go red, and unknown is not a pass
    assert check([1, 2], [1, 2]) == "t: PASS" or "PASS" in check([1, 2], [1, 2])
    assert "FAIL" in check([1, 9], [1, 2])
    assert "UNKNOWN" in check([], [1, 2]), "an empty observation must not pass"
    assert "UNKNOWN" in check([1], [1, 2]), "a length mismatch must not pass"

    # the CLM gap: a pruned ASSERTED span must be reportable, not silent
    ctx = Provenanced()
    ctx.add("tool returned 12 rows", "observed:sql", step=1)
    ctx.add("the warehouse has 18 seal codes", "asserted", step=3)
    lost = ctx.prune("18 seal codes", step=40)
    assert lost, "prune removed nothing — test is not exercising the path"
    assert "LOST" in ctx.report(), \
        "an unverified pruned span was dropped SILENTLY — this is the CLM failure mode"
    assert "18 seal codes" not in ctx.render(), "prune did not actually remove the span"

    if failures:
        for f in failures:
            print("  RED:", f)
        print("SELFTEST: FAIL (%d)" % len(failures))
        return 1
    print("SELFTEST: PASS — three-state values, a check that can go red, and loss that is reported")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    print(__doc__)
