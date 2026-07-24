# Trust-Model Backtest — Findings (2026-07-24)

Offline experiment over the historical injection→citation log to decide how a lesson
"trust" signal should work. Harness is read-only; it never touches runtime state.

## Data

- `session-log.jsonl`: 1,104 sessions, ~45.7k relevance-scored (`prompt_submit`) injections,
  848 citations.
- After per-session dedup: **15,278 prediction events**, 73 lessons, **base cite rate 3.5%**.
- Transcript relabeling: 3,437 judge records extracted from 189 surviving transcripts;
  a stratified **397-record blind panel** (98 cited + 299 uncited) was judged
  applied/not-applied by 10 parallel judges blind to the citation flag.

## Trust-formula backtest (prequential, no-lookahead; verified leak-free by review)

| estimator | AUC | ECE | noise@≤5% cites lost |
|---|---|---|---|
| **smoothed_ratio(a=1,b=1)** | **0.670** | **0.027** | **12.7%** |
| smoothed_ratio(a=2,b=1) | 0.662 | 0.042 | 10.8% |
| ema(η=0.3, warm-start 0.5) | 0.633 | 0.044 | 10.9% |
| `binary_penalty` (current live loop) | 0.544 | 0.485 | 0% |
| `always_one` (no trust) | 0.500 | 0.965 | 0% |

- **Winner: `smoothed_ratio(a=1,b=1)`** = (C+1)/(I+2), neutral 0.5 cold-start.
- Both live baselines are clearly beaten. The current `binary_penalty` (flat ×0.5 when
  injections≥5 and cite-ratio<0.2) is near-dead weight (AUC 0.54).
- **Cold-start must be a neutral prior, not 0.** Estimators that assign new lessons
  trust 0 (`ema(init=0)`, `updown`) can't suppress any noise without dropping cold-start
  citations — they collapse to 0% suppression. Only neutral-prior formulas are usable.
- Re-running with the 397 judged labels overriding citation labels leaves the ranking
  unchanged and nudges the winner up (AUC 0.670 → 0.677). **The formula is robust to the
  label.**

## Label quality (blind panel, n=397)

| | |
|---|---|
| Uncited injections judged *actually applied* (false negatives) | **4.7%** (95% CI 2.8–7.7%) |
| Uncited judged genuinely **not-applicable** (off-topic) | 93.6% |
| Cited injections judged **not** applied (ritual / false-positive) | 32.7% |
| Citation **recall** of real applications | 82.5% |

Interpretation:
1. **Absence-of-citation is a ~95%-correct negative signal**, not noise — most uncited
   injections are genuinely off-topic. Downvote-on-uncited is defensible.
2. **The citation *positive* signal is ~1/6–1/3 noise** (LESSON-DUTY ritual citations).
   (14% on full-context read, 33% on the strict blind panel whose 4,000-char truncation
   inflates it; truth is between.)
3. **The dominant quality problem is relevance, upstream of trust:** ~94% of uncited and
   ~30% of cited injections were off-topic. No trust/decay scheme fixes that — only
   injection-time relevance/file-path filtering does. That is the larger follow-on lever.

## Decision

- **v1 (this change):** wire `smoothed_ratio(a=1,b=1)` as a per-lesson precision
  multiplier on injection ranking, replacing `binary_penalty`. Neutral 0.5 cold-start,
  graduated suppression of chronically-uncited lessons, small min-injections gate for
  robustness to the ~5% silent-application noise.
- **Deferred:** (a) capturing a transcript-derived "applied" label at Stop time (better
  positive signal); (b) injection-time relevance filtering (the bigger lever).

## Reproduce

```bash
python -m experiments.trust                    # backtest on citation labels
python -m experiments.trust --labels <file>    # backtest on an override label set
python -m experiments.trust.extract_transcripts # rebuild judge records from transcripts
./run-tests.sh tests/test_trust_experiment.py  # 56 tests
```
