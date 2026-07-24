"""Build the estimator comparison table and the tradeoff-curve CSV.

Read-only: consumes the PredictionEvents produced by ``replay`` and the
estimators in ``estimators.REGISTRY``, and writes only into
``experiments/trust/results/`` (the experiment's own output dir). Nothing in
runtime state, LESSONS.md, or injection-stats.json is touched.
"""

from __future__ import annotations

import csv
import os
from typing import Dict, List

from . import evaluate as V
from .estimators import REGISTRY
from .replay import PredictionEvent

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")


def _pairs_for(estimator, events: List[PredictionEvent]):
    return [
        (estimator(ev.history, ev.ts), 1 if ev.cited else 0)
        for ev in events
    ]


def evaluate_all(events: List[PredictionEvent]) -> Dict[str, dict]:
    """Score every registered estimator over ``events``.

    Returns ``{name: {auc, ece, lift, noise_at_1pct, noise_at_5pct}}``.
    """
    results: Dict[str, dict] = {}
    for name, estimator in REGISTRY.items():
        pairs = _pairs_for(estimator, events)
        _, ece = V.calibration(pairs)
        results[name] = {
            "auc": V.roc_auc(pairs),
            "ece": ece,
            "lift": V.lift_at_decile(pairs),
            "noise_at_1pct": V.summarize(pairs, tol=0.01),
            "noise_at_5pct": V.summarize(pairs, tol=0.05),
        }
    return results


def _fmt(x: float) -> str:
    if x != x:  # nan
        return "  n/a"
    return f"{x:.4f}"


def _pct(x: float) -> str:
    if x != x:
        return "  n/a"
    return f"{x * 100:5.1f}%"


def format_table(results: Dict[str, dict]) -> str:
    """Render the estimator x metrics comparison as a fixed-width table."""
    name_w = max(len("estimator"), *(len(n) for n in results))
    header = (
        f"{'estimator':<{name_w}}  {'AUC':>7}  {'ECE':>7}  "
        f"{'lift@10%':>9}  {'noise@1%':>9}  {'noise@5%':>9}"
    )
    lines = [header, "-" * len(header)]
    # Sort by the headline operational metric (noise suppressed at <=1% loss).
    def sort_key(item):
        v = item[1]["noise_at_1pct"]
        return -(v if v == v else -1.0)

    for name, row in sorted(results.items(), key=sort_key):
        lines.append(
            f"{name:<{name_w}}  {_fmt(row['auc']):>7}  {_fmt(row['ece']):>7}  "
            f"{_fmt(row['lift']):>9}  {_pct(row['noise_at_1pct']):>9}  "
            f"{_pct(row['noise_at_5pct']):>9}"
        )
    return "\n".join(lines)


def write_tradeoff_csv(events: List[PredictionEvent], out_dir: str = RESULTS_DIR) -> str:
    """Write the full tradeoff curve for every estimator to a CSV.

    Columns: estimator, cutoff, noise_suppressed, signal_lost.
    """
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "tradeoff_curves.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["estimator", "cutoff", "noise_suppressed", "signal_lost"])
        for name, estimator in REGISTRY.items():
            pairs = _pairs_for(estimator, events)
            for row in V.tradeoff_curve(pairs):
                w.writerow([
                    name,
                    f"{row['cutoff']:.6f}",
                    f"{row['noise_suppressed']:.6f}",
                    f"{row['signal_lost']:.6f}",
                ])
    return path


def summary_lines(events: List[PredictionEvent]) -> List[str]:
    """A few descriptive facts about the replayed corpus."""
    n = len(events)
    cited = sum(1 for e in events if e.cited)
    sessions = len({e.session_id for e in events})
    lessons = len({e.lesson_id for e in events})
    rate = (cited / n) if n else 0.0
    return [
        f"prediction events : {n}",
        f"distinct sessions : {sessions}",
        f"distinct lessons  : {lessons}",
        f"cited events      : {cited}",
        f"base cite rate    : {rate * 100:.2f}%",
    ]
