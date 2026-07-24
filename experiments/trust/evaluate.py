"""Imbalance-aware metrics for scoring an estimator's predictions.

Every function takes ``pairs``: a list of ``(trust, label)`` where ``trust`` is
an estimator's output in ``[0, 1]`` and ``label`` is 1 (cited) or 0 (uncited).
Base cite rate is ~1.9%, so accuracy is useless; we use ranking (ROC-AUC),
calibration (ECE), and an operational suppression tradeoff instead.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

Pair = Tuple[float, int]


def roc_auc(pairs: List[Pair]) -> float:
    """ROC-AUC via the rank-sum (Mann-Whitney) identity, tie-safe.

    Returns ``nan`` if either class is empty. 1.0 = perfect ranking, 0.5 =
    random, 0.0 = perfectly inverted.
    """
    n_pos = sum(1 for _, y in pairs if y)
    n_neg = len(pairs) - n_pos
    if n_pos == 0 or n_neg == 0:
        return float("nan")

    # Rank ascending by trust; ties share the average of their positions.
    order = sorted(pairs, key=lambda p: p[0])
    ranks = [0.0] * len(order)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and order[j + 1][0] == order[i][0]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0  # positions i..j -> 1-based average
        for k in range(i, j + 1):
            ranks[k] = avg_rank
        i = j + 1

    sum_ranks_pos = sum(r for r, (_, y) in zip(ranks, order) if y)
    return (sum_ranks_pos - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def calibration(pairs: List[Pair], bins: int = 10) -> Tuple[List[dict], float]:
    """Reliability bins + Expected Calibration Error.

    Trust is bucketed into ``bins`` equal-width bins over ``[0, 1]``. For each
    non-empty bin we report mean predicted trust vs empirical cite rate; ECE is
    the count-weighted mean absolute gap.
    """
    buckets: List[List[Pair]] = [[] for _ in range(bins)]
    for trust, label in pairs:
        idx = int(trust * bins)
        if idx >= bins:
            idx = bins - 1
        elif idx < 0:
            idx = 0
        buckets[idx].append((trust, label))

    n = len(pairs)
    rows: List[dict] = []
    ece = 0.0
    for b, bucket in enumerate(buckets):
        if not bucket:
            continue
        count = len(bucket)
        mean_pred = sum(t for t, _ in bucket) / count
        empirical = sum(y for _, y in bucket) / count
        rows.append({
            "bin": b,
            "count": count,
            "mean_pred": mean_pred,
            "empirical": empirical,
        })
        ece += (count / n) * abs(mean_pred - empirical)

    return rows, ece


def lift_at_decile(pairs: List[Pair]) -> float:
    """Lift of the top-trust decile: top-decile cite rate / overall cite rate.

    A value of N means the highest-trust 10% of injections are N times as
    likely to be cited as a random injection.
    """
    n = len(pairs)
    if n == 0:
        return float("nan")
    overall = sum(y for _, y in pairs) / n
    if overall == 0:
        return float("nan")
    k = max(1, n // 10)
    top = sorted(pairs, key=lambda p: p[0], reverse=True)[:k]
    top_rate = sum(y for _, y in top) / k
    return top_rate / overall


def tradeoff_curve(pairs: List[Pair]) -> List[dict]:
    """Operational suppression tradeoff, swept over cutoff ``c``.

    An injection with ``trust < c`` would be suppressed/down-ranked. For each
    ``c`` we report:
      * ``noise_suppressed`` = fraction of UNCITED injections suppressed,
      * ``signal_lost``      = fraction of CITED injections suppressed.
    Both are non-decreasing in ``c``. Cutoffs are the distinct trust values plus
    a sentinel above the maximum (full suppression).
    """
    cited = [t for t, y in pairs if y]
    uncited = [t for t, y in pairs if not y]
    n_cited = len(cited)
    n_uncited = len(uncited)
    if not pairs:
        return []

    cutoffs = sorted({t for t, _ in pairs})
    cutoffs.append(max(cutoffs) + 1.0)  # ensure the max-trust point is reachable

    rows: List[dict] = []
    for c in cutoffs:
        noise = (sum(1 for t in uncited if t < c) / n_uncited) if n_uncited else 0.0
        signal = (sum(1 for t in cited if t < c) / n_cited) if n_cited else 0.0
        rows.append({
            "cutoff": c,
            "noise_suppressed": noise,
            "signal_lost": signal,
        })
    return rows


def summarize(pairs: List[Pair], tol: float) -> float:
    """Max fraction of uncited injections suppressible while losing <= ``tol``
    of citations.

    Because both curves are monotonic in ``c``, this is the largest
    ``noise_suppressed`` among cutoffs whose ``signal_lost`` is within ``tol``.
    Returns ``nan`` if there are no uncited injections to suppress.
    """
    if not any(y == 0 for _, y in pairs):
        return float("nan")
    best = 0.0
    for row in tradeoff_curve(pairs):
        if row["signal_lost"] <= tol + 1e-9:
            if row["noise_suppressed"] > best:
                best = row["noise_suppressed"]
    return best
