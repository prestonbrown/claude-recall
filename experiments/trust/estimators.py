"""Candidate trust formulas.

Each estimator is a pure function ``trust(history, now_ts) -> float`` in
``[0, 1]`` of a lesson's *prior* history only. Parameterized families return a
configured closure; concrete presets are registered by name in ``REGISTRY`` so
``report.py`` can iterate every candidate and adding one is a single line.

``now_ts`` is passed for time-aware variants; the v1 estimators are all
count/sequence based and ignore it, but the signature is uniform so the
evaluation loop is agnostic.
"""

from __future__ import annotations

from typing import Callable

from .replay import LessonHistory

Estimator = Callable[[LessonHistory, int], float]


def _clamp01(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def always_one(history: LessonHistory, now_ts: int) -> float:
    """Constant 1.0 -- the current live behavior (no trust signal)."""
    return 1.0


def binary_penalty(history: LessonHistory, now_ts: int) -> float:
    """Replicates today's Go ``ShouldPenalize`` baseline.

    0.5 when a lesson has been injected at least 5 times and cited in under 20%
    of them, else 1.0. The ``< 0.2`` is strict: exactly 20% is NOT penalized.
    """
    if history.injections >= 5 and history.cite_ratio < 0.2:
        return 0.5
    return 1.0


def smoothed_ratio(alpha: float, beta: float) -> Estimator:
    """Beta-smoothed cite rate: ``(C + alpha) / (I + alpha + beta)``.

    With no history this returns the prior mean ``alpha / (alpha + beta)``.
    """
    denom_prior = alpha + beta

    def _trust(history: LessonHistory, now_ts: int) -> float:
        return _clamp01(
            (history.cites + alpha) / (history.injections + denom_prior)
        )

    return _trust


def ema(eta: float, init: float = 0.0) -> Estimator:
    """Online exponential moving average of hits.

    ``t <- (1 - eta) * t + eta * hit`` folded over prior outcomes in order,
    starting from ``init``. Empty history returns ``init``.
    """

    def _trust(history: LessonHistory, now_ts: int) -> float:
        t = init
        for _, hit in history.outcomes:
            t = (1.0 - eta) * t + eta * hit
        return _clamp01(t)

    return _trust


def updown(u: float, d: float, floor: float, init: float) -> Estimator:
    """Additive up/down score: ``+u`` on a cite, ``-d`` on an ignore.

    Clamped to ``[floor, 1]`` after every step. Empty history returns ``init``.
    """

    def _trust(history: LessonHistory, now_ts: int) -> float:
        t = init
        for _, hit in history.outcomes:
            t = t + u if hit else t - d
            if t < floor:
                t = floor
            elif t > 1.0:
                t = 1.0
        return _clamp01(t)

    return _trust


# Concrete presets. Names embed their parameters so the report and CSV are
# self-documenting; adding a candidate is one line here.
REGISTRY: "dict[str, Estimator]" = {
    "always_one": always_one,
    "binary_penalty": binary_penalty,
    "smoothed_ratio(a=2,b=1)": smoothed_ratio(2, 1),
    "smoothed_ratio(a=1,b=1)": smoothed_ratio(1, 1),
    "ema(eta=0.3)": ema(0.3, init=0.0),
    "ema(eta=0.5)": ema(0.5, init=0.0),
    "ema(eta=0.3,init=0.5)": ema(0.3, init=0.5),
    "updown(u=.2,d=.05,floor=0,init=1)": updown(u=0.2, d=0.05, floor=0.0, init=1.0),
    "updown(u=.1,d=.02,floor=.1,init=.5)": updown(u=0.1, d=0.02, floor=0.1, init=0.5),
}
