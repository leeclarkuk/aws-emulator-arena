"""Pure scoring helpers. No network, no boto3."""

from __future__ import annotations

import math
from typing import Iterable

OUTCOMES = ("pass", "not_implemented", "divergent", "blocked")

# Outcomes that count toward the fidelity denominator. A blocked step never
# reached the emulator, so it is shown and then left out of the score.
SCORED = ("pass", "not_implemented", "divergent")


def percentile(values: Iterable[float], p: float) -> float | None:
    xs = sorted(values)
    if not xs:
        return None
    if len(xs) == 1:
        return float(xs[0])
    rank = (len(xs) - 1) * (p / 100)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return float(xs[low])
    weight = rank - low
    return float(xs[low] * (1 - weight) + xs[high] * weight)


def counts(outcomes: Iterable[str]) -> dict[str, int]:
    tally = {name: 0 for name in OUTCOMES}
    for outcome in outcomes:
        if outcome not in tally:
            raise ValueError(f"unknown outcome {outcome!r}")
        tally[outcome] += 1
    return tally


def fidelity(tally: dict[str, int]) -> float | None:
    scored = sum(tally.get(name, 0) for name in SCORED)
    if scored == 0:
        return None
    return tally.get("pass", 0) / scored


def latency_stats(samples: Iterable[float]) -> dict[str, float | int | None]:
    xs = [float(v) for v in samples]
    if not xs:
        return {"n": 0, "min": None, "mean": None, "p50": None, "p95": None, "max": None}
    return {
        "n": len(xs),
        "min": min(xs),
        "mean": sum(xs) / len(xs),
        "p50": percentile(xs, 50),
        "p95": percentile(xs, 95),
        "max": max(xs),
    }


def round_ms(value: float | None, digits: int = 2):
    if value is None:
        return None
    return round(float(value), digits)
