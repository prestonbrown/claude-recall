# Trust-Model Backtest Harness — Design

**Date:** 2026-07-23
**Status:** Approved (solo maintainer, building in `main`)

## Problem

Claude Recall injects lessons it thinks are relevant. We want a feedback loop:
a lesson that gets **cited** after injection is confirmed relevant (upvote); a lesson
**injected-but-ignored** is a false positive (downvote). We want this signal to
influence future injection ranking.

We do **not** know the right way to compute/weight that signal. Rather than guess a
formula and ship it, we build a harness to **experiment first**: replay the historical
injection→citation log through several candidate "trust" formulas and measure which one
best predicts citations. The winner gets wired into the live ranker later, as a
separate change.

## Decisions (locked)

1. **Separate axis.** `trust` is a persisted precision signal (0..1), distinct from
   velocity/time-decay. It multiplies into the ranking score; it does not fold into
   velocity. No cross-axis weight to tune — time-decay stays exactly as it is.
2. **Downvote scope: relevance-scored injections only.** Only `prompt_submit` (BM25
   match) and SubagentStop (relevance match) injections count toward trust. SessionStart
   top-by-stars injections are **exempt** — they are duty reminders, not relevance
   claims. This keeps the denominator meaningful (base cite rate is ~1.9%; counting
   SessionStart would collapse the corpus toward the floor).
3. **Experiment before committing.** Build a backtest harness, not a final formula.
4. **Placement:** Python, standalone, under `experiments/trust/`. Pure offline analysis,
   reads `session-log.jsonl` **read-only**. The Go runtime, `LESSONS.md`, and
   `injection-stats.json` are **not touched**.
5. **Data source:** backtest the ~4 months already logged (1,111 sessions, 848
   citations). Forward shadow-logging is deferred unless the backtest is inconclusive.

## Data (as of 2026-07-23, system state log)

`~/.local/state/claude-recall/session-log.jsonl`, 55,398 events:

| Event | Count | Notes |
|---|---|---|
| injection | 53,026 | 45,726 `hook:prompt_submit`, 7,300 `hook:session_start` |
| citation | 848 | 100% carry a `session` |
| session_start | 1,533 | |
| dismiss | 1 | |
| distinct sessions | 1,111 | |

**Base cite rate ≈ 1.9%** of relevance-scored injections. Severe class imbalance —
evaluation must be imbalance-aware (accuracy is useless).

**Join quirk:** 15.6% of injections have empty `session` — almost entirely
`session_start` (which we exempt anyway). Relevance-scored `prompt_submit` injections
carry a session ~98% of the time. Injections with empty session are **dropped** from
the backtest.

Event shapes:
```json
{"ts":"...","type":"injection","session":"<id|empty>","lesson":"L066","score":10,"query":"...","hook":"prompt_submit","project":"..."}
{"ts":"...","type":"citation","session":"<id>","lesson":"L060","project":"..."}
```

## Architecture

Four small, independently-testable modules plus a CLI entry.

```
experiments/trust/
  __init__.py
  replay.py      # log file -> ordered stream of prediction events
  estimators.py  # candidate trust formulas (pure functions)
  evaluate.py    # metrics: calibration/ECE, ROC-AUC, operational tradeoff curve
  report.py      # comparison table + CSV, stdout
  __main__.py    # `python -m experiments.trust --log <path>`
tests/test_trust_experiment.py
```

### 1. `replay.py` — prequential labeling (no lookahead)

Responsibility: turn the raw log into a chronological stream of
`PredictionEvent(lesson_id, session_id, ts, cited: bool)`, one per
**(session, relevance-injected lesson)** pair, plus a running per-lesson **history**
of prior outcomes that estimators consume.

- Parse JSONL. Keep `injection` events with `hook == "prompt_submit"` and a non-empty
  `session`; keep all `citation` events.
- Group by `session`. Within a session, a lesson is counted **once** regardless of how
  many times it was injected (dedup per session). Label `cited = True` iff a citation
  for that lesson exists in the same session.
  - Guard: only credit a citation whose `ts >=` the lesson's first injection ts in that
    session (a citation cannot be caused by a later injection).
- Order sessions chronologically by first-injection ts.
- **Prequential walk:** iterate sessions in order; for each relevance-injected lesson,
  emit its `PredictionEvent` *before* folding this session's outcome into that lesson's
  history. This mirrors how the live system would have scored it as data streamed in —
  no formula ever sees the outcome it is being asked to predict.

The history object per lesson exposes what estimators need: ordered list of prior
outcomes (0/1) with timestamps, plus cumulative injection/cite counts.

### 2. `estimators.py` — candidate formulas (pure)

Each estimator is `trust(history, now_ts) -> float in [0,1]`, a pure function of a
lesson's **prior** history only. v1 set:

- `always_one` — constant 1.0. Baseline = current live behavior (no trust).
- `binary_penalty` — replicates today's `ShouldPenalize`: `0.5` if
  `injections >= 5 and cite_ratio < 0.2` else `1.0`. Baseline = today's feedback loop.
- `smoothed_ratio(alpha, beta)` — `(C+alpha)/(I+alpha+beta)` over cumulative counts.
  Ship 2–3 priors (e.g. optimistic `alpha=2,beta=1`; neutral `alpha=1,beta=1`).
- `ema(eta)` — online EMA of hit/miss: `t <- (1-eta)*t + eta*hit`. Ship 2–3 rates.
- `updown(u, d, floor, init)` — `+u` on cite, `-d` on ignore, clamped `[floor, 1]`.
  Ship 1–2 settings.

Registry: a dict of `name -> callable` so `report.py` iterates all of them and adding a
candidate is one line.

### 3. `evaluate.py` — imbalance-aware metrics

Given, per estimator, a list of `(trust, label)`:

- **Calibration / ECE** — bin trust into deciles; report mean predicted trust vs
  empirical cite rate per bin, and Expected Calibration Error.
- **ROC-AUC + lift** — trust as a citation predictor. AUC summarizes ranking quality
  under imbalance; lift@decile shows concentration of citations in high-trust events.
- **Operational tradeoff curve** — the decision metric. Sweep a suppression cutoff `c`:
  an injection with `trust < c` would be down-ranked/suppressed. Report, across `c`:
  - `noise_suppressed` = fraction of **uncited** injections suppressed (noise removed),
  - `signal_lost` = fraction of **cited** injections suppressed (citations we'd lose).
  Summarize each estimator by "% uncited suppressed at ≤1% citations lost" and
  "…at ≤5% citations lost" — the headline numbers for picking a winner.

### 4. `report.py` / `__main__.py`

- `python -m experiments.trust --log <path>` (default:
  `$CLAUDE_RECALL_STATE/session-log.jsonl`).
- Prints a comparison table (estimator × {AUC, ECE, %noise@1%, %noise@5%}), writes a CSV
  of the tradeoff curve to `experiments/trust/results/`. Read-only w.r.t. all state.

## Testing (test-first — write these before the modules)

`tests/test_trust_experiment.py`:

- **replay labeling** — synthetic log: lesson injected in S1 then cited in S1 → labeled
  cited; injected in S2 never cited → labeled uncited; citation with `ts` before its
  injection → not credited; lesson injected 3× in one session → one event; empty-session
  injection → dropped; `session_start` injection → excluded.
- **no-lookahead** — the event emitted for session N reflects only outcomes from
  sessions `< N`; a lesson's very first prediction sees empty history.
- **estimators** — hand-computed values: `smoothed_ratio` on a known `(C,I)`;
  `ema` after a known hit/miss sequence; `updown` clamping at floor and 1;
  `binary_penalty` boundary at exactly 5 injections / 0.2 ratio.
- **metrics** — perfect-separation input → AUC = 1.0; random labels → AUC ≈ 0.5;
  a known calibration table → known ECE; operational curve monotonic in `c`.

Run via `./run-tests.sh tests/test_trust_experiment.py`. Pure stdlib (json, math,
bisect); no new deps.

## Out of scope (separate follow-up)

Wiring the winning formula into the Go ranker (`go/internal/feedback` +
`ApplyPenalties`, or a new `trust` field). Designed only after the backtest names a
winner. Forward shadow-logging, likewise deferred.

## Success criteria

Running `python -m experiments.trust` over the real log prints a comparison in which
each candidate is scored against the `always_one` and `binary_penalty` baselines, and we
can point to one formula that suppresses the most uncited injections while losing ≤ a
tolerable fraction of real citations.
