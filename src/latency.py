"""Latency instrumentation and summary statistics.

Authorization latency is measured independently of tool execution (manuscript
section IV.E.4): the evaluator times only the call into an authorization engine.
Percentiles are computed with ``numpy.percentile`` using linear interpolation,
which matches the default percentile definition of the analysis stack used for
the reported statistics.
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable

import numpy as np

__all__ = [
    "Clock",
    "LatencyStats",
    "ns_to_ms",
    "summarize_latencies",
    "timed",
]

#: Monotonic nanosecond clock, injectable so that tests can be deterministic.
Clock = Callable[[], int]


def ns_to_ms(nanoseconds: int | float) -> float:
    """Convert nanoseconds to milliseconds."""
    return float(nanoseconds) / 1_000_000.0


@contextmanager
def timed(sink: list[float], *, clock: Clock = time.perf_counter_ns) -> Iterator[None]:
    """Append the wall-clock duration of the wrapped block to ``sink`` (in ms).

    ``time.perf_counter_ns`` is used because it is monotonic, which keeps the
    measurement meaningful even if the system clock is adjusted mid-run.
    """
    start = clock()
    try:
        yield
    finally:
        sink.append(ns_to_ms(clock() - start))


@dataclass(frozen=True, slots=True)
class LatencyStats:
    """Summary of a latency sample in milliseconds."""

    n: int
    mean_ms: float
    median_ms: float
    p95_ms: float
    p99_ms: float
    min_ms: float
    max_ms: float

    def as_dict(self) -> dict[str, float | int]:
        return {
            "n": self.n,
            "mean_ms": self.mean_ms,
            "median_ms": self.median_ms,
            "p95_ms": self.p95_ms,
            "p99_ms": self.p99_ms,
            "min_ms": self.min_ms,
            "max_ms": self.max_ms,
        }


def summarize_latencies(samples: Iterable[float]) -> LatencyStats:
    """Summarize latency samples (milliseconds) into the reported percentiles."""
    values = np.asarray([float(sample) for sample in samples], dtype=float)
    if values.size == 0:
        raise ValueError("at least one latency sample is required")
    if np.any(values < 0):
        raise ValueError("latency samples must be non-negative")
    return LatencyStats(
        n=int(values.size),
        mean_ms=float(np.mean(values)),
        median_ms=float(np.median(values)),
        p95_ms=float(np.percentile(values, 95)),
        p99_ms=float(np.percentile(values, 99)),
        min_ms=float(np.min(values)),
        max_ms=float(np.max(values)),
    )