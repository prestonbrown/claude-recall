# Claude-Recall Observability & Reporting

**Date:** 2026-03-25
**Status:** Draft
**Plugin:** claude-recall v1.1.0
**Repo:** `/home/pbrown/Code/claude-recall/`

## Problem

The lessons system operates behind the scenes. Injections fire on every `UserPromptSubmit`, citations are counted in the `Stop` hook, velocity decays weekly — but the user has no visibility into whether the system is working well. Questions like "are the right lessons being surfaced?", "which lessons are noisy?", and "is precision improving over time?" are unanswerable without manually reading `LESSONS.md` and guessing.

The existing `debuglog.go` writes injection events to `recall.log` as JSONL, but nothing analyzes that data. Citations are tracked per-lesson (Uses/Velocity) but never correlated back to what was injected.

## Goals

1. **Visibility** — see what the system is doing, on demand
2. **Precision tracking** — know which lessons hit vs miss
3. **Tuning levers** — narrow noisy lessons with trigger keywords
4. **Feedback loop** — let users signal when injections are noise
5. **Trend reporting** — track whether precision improves over time

## Non-Goals

- Auto-dampening or auto-deletion (future work, after patterns emerge)
- Real-time injection annotation (too noisy in the prompt stream)
- Cloud sync or remote dashboards

## Design

### 1. Session Event Log (`session-log.jsonl`)

**Location:** `~/.local/state/claude-recall/session-log.jsonl`

Append-only structured log capturing every injection and citation event. This is the foundation for all reporting.

#### Event Types

```jsonl
{"ts":"2026-03-25T10:23:01Z","type":"injection","session":"abc123","lesson":"L059","score":8,"query":"crash in lv_event_mark_deleted","hook":"prompt_submit","project":"/home/user/myproject"}
{"ts":"2026-03-25T10:23:45Z","type":"citation","session":"abc123","lesson":"L059","project":"/home/user/myproject"}
{"ts":"2026-03-25T10:24:00Z","type":"dismiss","session":"abc123","lesson":"L031","project":"/home/user/myproject"}
{"ts":"2026-03-25T10:00:00Z","type":"session_start","session":"abc123","project":"/home/user/myproject","lessons":["L031","L060","L064","L071","L009"]}
```

**Fields:**
- `ts` — RFC3339 timestamp
- `type` — `injection`, `citation`, `dismiss`, `session_start`
- `session` — session ID (for grouping)
- `lesson` — lesson ID (L### or S###); array for `session_start`
- `score` — BM25 relevance score at injection time (injections only)
- `query` — full query text that triggered injection (injections only; see §Query Storage)
- `hook` — `session_start` or `prompt_submit` (injections only)
- `project` — project directory

**Retention:** 90 days, pruned opportunistically during the weekly decay cycle. If Claude Code isn't used for a period, old entries remain on disk until the next session triggers pruning.

#### Query Storage Decision

**Decision: Store full query text.**

Rationale: Trigger suggestions (§4) require analyzing which queries led to citations vs noise. Without query text, the most valuable reporting feature — auto-suggested triggers — is impossible. The data is stored locally on the user's machine in the same state directory as other claude-recall data, under the same filesystem permissions. Users who process sensitive data in prompts already have that data in Claude Code's own transcript files.

The query field is only written for `injection` events from the `prompt_submit` hook (not `session_start` injections, which have no query). Queries are never transmitted off-device.

#### Integration Points

**Smart-inject hook** — `go/cmd/recall-hook/inject.go` `runInject()` and the `score-local` path in `go/cmd/recall/app.go` `runScoreLocal()`:
After scoring and dedup filtering, emit one `injection` event per lesson actually injected. The BM25 score and query text are already available in the scoring pipeline — pass them through to the event log writer.

**Stop hook** — `go/cmd/recall-hook/stopall.go` `runStopAll()` → calls `executeStop()` in `stop.go`:
After `citations.ExtractFromMessages(messages)` returns extracted citations and `store.Cite(id)` processes them, emit one `citation` event per unique citation to the session log. The session ID and project dir are already available from `stopInput`.

**Session start** — `go/cmd/recall-hook/inject.go` `runInjectCombined()`:
Emit a single `session_start` event listing the top-N lesson IDs injected. Already logged to `recall.log` via `debuglog.LogInjection()` — add a parallel write to `session-log.jsonl`.

### 2. Precision Score

**Definition:** `precision = citations / injections` per lesson, computed from `session-log.jsonl`.

Not stored in `LESSONS.md` — it's a derived metric computed on demand from the event log. This avoids LESSONS.md churn and keeps the source of truth clean.

**Interpretation:**
| Precision | Meaning |
|-----------|---------|
| >0.5 | Well-targeted — injected when relevant |
| 0.2–0.5 | Acceptable — some noise |
| <0.2 | Noisy — injected often, rarely useful |
| 0.0 | Pure noise — never cited despite injections |
| N/A | Never injected (only cited organically, or new) |

**Time windows:** Precision computed over configurable windows (7d, 30d, all-time) for trend analysis.

**Edge cases:**
- Lesson never injected → excluded from precision reports (show as "N/A — organic citations only")
- Lesson injected once, cited once → 100% precision but low confidence; show injection count alongside precision so user can judge significance
- Lesson with 0 injections and 0 citations → omitted from reports entirely

### 3. `/recall stats` Command

New slash command (implemented as `commands/stats.md`) with three modes, each progressively deeper. The slash command invokes `recall stats` CLI with appropriate flags.

#### Session mode (default): `/recall stats`

```
📊 This Session
  Injections: 8 (5 unique lessons)
  Citations:  2
  Precision:  25.0%

  Hits:  [L074] Generation counter (score 9, cited ✓)
         [L068] Cancel animations (score 7, cited ✓)
  Noise: [L059] Deletion strategies (score 8, injected 3x, never cited)
         [L031] XML no recompile (score 6, injected 2x, never cited)
         [L055] LVGL pad_all (score 10, never cited)
```

**Data source:** Filter `session-log.jsonl` to current session ID. Cross-reference injections vs citations.

**Session ID:** Passed via environment or stdin from the slash command context. If unavailable, show the most recent session.

#### Lesson mode: `/recall stats L059`

```
📊 Lesson L059: LVGL object deletion strategies
  Rating: [**---|****-]  Uses: 5  Velocity: 2.5

  Injection History (30d):
    Injected: 47 times across 22 sessions
    Cited:    5 times
    Dismissed: 2 times
    Precision: 10.2%

  Top triggering queries (by BM25 score):
    "safe_delete vs deferred" → score 9, cited ✓
    "how to delete widget" → score 8, cited ✓
    "crash in lv_event_mark_deleted" → score 8, cited ✓
    "improve lessons system" → score 7, NOT cited ✗
    "brainstorm improvements" → score 6, NOT cited ✗

  Suggestion: Add triggers to narrow matching.
    Current triggers: (none)
    Suggested: safe_delete, delete_deferred, lv_obj_delete, deletion_strategy
```

**Data source:** Filter session-log to lesson ID, group by query text, compute per-query hit rate.

**Trigger suggestions algorithm:** Compare queries that led to citations (positive) vs queries that led to ignored injections (negative):
1. Tokenize all positive queries and all negative queries using the existing `scoring.Tokenize()` function
2. Compute term frequency in positive set and negative set
3. Score each term: `score = freq_positive / (freq_positive + freq_negative)` — terms that appear mostly in positive queries score high
4. Filter: term must appear in at least 2 positive queries (minimum support)
5. Return top 5 terms by score
6. If fewer than 5 positive queries exist, skip suggestion (insufficient data)

This is simple frequency ratio, not full TF-IDF — keeps implementation straightforward and is sufficient for the use case.

#### Trend mode: `/recall stats --weekly`

```
📊 Weekly Report (2026-W13)
  Sessions: 34
  Injections: 142 (avg 4.2/session)
  Citations: 38
  Overall precision: 26.8%

  ▲ Improving:  L074 precision 60% → 80% (+20pp)
  ▼ Declining:  L031 precision 15% → 8% (-7pp)
  🏆 Top performers: L074 (80%), L071 (67%), L009 (55%)
  ⚠ Noise offenders: L059 (11%), L055 (5%), L031 (8%)
  💤 Stale (0 citations, 30d): L021, L046, L051, L053

  vs Last Week:
    Precision: 22.4% → 26.8% (+4.4pp)
    Avg injections/session: 5.1 → 4.2 (-0.9)
```

**Data source:** Aggregate session-log over ISO week boundaries. Compare current vs previous week.

**Scope:** Project-scoped by default (filter events by current project directory). System lessons (S###) are included if they were injected in the current project. Add `--all` flag to aggregate across all projects.

**Stale detection:** Uses the existing `models.Lesson.IsStale()` method (default 60 days) cross-referenced with event log data (0 citations in the event log window).

### 4. Trigger Keywords for Noise Reduction

The `Triggers []string` field already exists on the `Lesson` model and is already parsed/serialized by `lessons/parser.go`. It is currently unused by BM25 scoring.

#### BM25 Scorer Change

In `scoring/bm25.go`, `NewBM25Scorer()` (line 62-70, tokenization loop):
- When tokenizing a lesson, if `lesson.Triggers` is non-empty, **append the trigger terms to the tokenized title + content**. Each trigger term is tokenized through the same `Tokenize()` pipeline.
- Trigger terms are appended **3x** (triple-weighted) so they dominate BM25 term frequency without completely replacing the natural content tokens. This means a lesson with triggers still matches its content terms, but trigger matches score proportionally higher.
- Lessons without triggers are unchanged (backward compatible).

**Why append, not replace:** Replacing content with triggers breaks BM25's IDF statistics. Document frequency counts are computed across all lessons — if some lessons have 3 tokens (triggers only) and others have 200 tokens (full content), the IDF weighting becomes unfairly biased. Appending preserves the statistical properties while boosting trigger relevance.

#### Adding Triggers

Two paths:
1. **Manual:** `recall edit L059 --triggers "safe_delete,delete_deferred,lv_obj_delete"` — the parser already handles the `**Triggers**:` field in LESSONS.md
2. **Suggested:** `/recall stats L059` computes suggested triggers from citation-positive queries (see §3 trigger suggestions algorithm) and displays them. User copies desired triggers into an edit command.

#### LESSONS.md Format

Already supported by the parser (`lessons/parser.go` lines 107-113):
```markdown
### [L059] [**---|****-] LVGL object deletion strategies
- **Uses**: 5 | **Velocity**: 2.5 | ... | **Triggers**: safe_delete, delete_deferred, lv_obj_delete
```

### 5. Dismiss Command

Explicit user signal that an injected lesson was noise for the current context.

#### Implementation: `/recall dismiss L059`

This is a **slash command** (defined in `commands/dismiss.md`) that invokes `recall dismiss <ID>` CLI. The slash command reads the lesson ID from the argument, confirms the dismissal to the user, and the CLI logs the event.

- Logs a `dismiss` event to `session-log.jsonl`
- Counts as a negative signal for precision calculation
- Does NOT remove the lesson or prevent future injection (informational only, per design principle)
- Outputs confirmation: "Dismissed [L059] for this session. This won't prevent future injections but helps track noise."

#### Precision Calculation with Dismissals

```
precision = citations / (injections + dismissals)
```

Dismissals increase the denominator, lowering precision. A dismiss counts the same as an injection-without-citation — the explicit signal's value is in the *data quality* (we know for certain it was noise), not in extra weighting. This keeps the formula simple and interpretable.

If future analysis shows passive non-citations are too noisy a signal (e.g., Claude applied the lesson without citing it), we can revisit weighting. For now, simplicity wins.

### 6. Weekly Digest Report

Auto-generated report with two trigger mechanisms:

**Location:** `~/.local/state/claude-recall/reports/weekly-YYYY-WW.md`

**Primary trigger (session-start):** Session start hook checks `~/.local/state/claude-recall/.digest-last-run`. If 7+ days elapsed, generate report from session-log data. Runs in the background, does not block session start.

**Alternative trigger (RemoteTrigger):** Claude Code's `RemoteTrigger` API supports persistent cron-scheduled triggers that survive across sessions. A `/recall schedule-digest` command could create a weekly remote trigger that generates the digest on a fixed cadence (e.g., Monday 9am) regardless of session activity. The trigger would invoke `recall digest --generate` via the remote trigger prompt.

**View command:** `/recall digest` — displays the latest weekly report (slash command defined in `commands/digest.md`).

**Contents:** Same as `/recall stats --weekly` output, written to file for async review.

### 7. Implementation Plan

#### Phase 1: Event Log + Session Stats (foundation)

1. **New package:** `go/internal/eventlog/` — `eventlog.go` with `Append()`, `Read()`, `Prune()` for `session-log.jsonl`
2. **Hook integration — injections:** In `go/cmd/recall-hook/inject.go` `runInjectCombined()`, after formatting lessons, call `eventlog.Append()` for each injected lesson with session ID and project dir. In the `score-local` / `smart-inject` path, pass BM25 scores and query text through to the event log.
3. **Hook integration — citations:** In `go/cmd/recall-hook/stop.go` `executeStop()`, after `store.Cite(id)` succeeds, call `eventlog.Append()` with a citation event.
4. **New CLI command:** `recall stats` (session mode only) — reads session-log, filters by session ID, outputs hit/noise report.
5. **New slash command:** `commands/stats.md` to expose `/recall stats`
6. **Pruning:** In `lessons/decay.go`, after running velocity decay, call `eventlog.Prune(retentionDays)` to remove entries older than 90 days.

#### Phase 2: Precision + Lesson Stats

7. **Precision computation:** `go/internal/eventlog/precision.go` — `PrecisionByLesson(window)` aggregates injection/citation/dismiss counts by lesson ID over a time window, returns precision scores.
8. **Lesson mode:** `recall stats --lesson L059` — reads session-log, filters by lesson ID, shows injection history + triggering queries + trigger suggestions.
9. **Trend mode:** `recall stats --weekly` — aggregates by ISO week, compares current vs previous, shows risers/fallers/noise/stale.

#### Phase 3: Trigger Keywords + Noise Reduction

10. **BM25 trigger support:** Modify `scoring/bm25.go` `NewBM25Scorer()` to append triple-weighted trigger terms during tokenization.
11. **Trigger suggestions:** Implement frequency-ratio algorithm in `eventlog/precision.go` (see §3 algorithm spec).
12. **Edit command:** Verify `recall edit L059 --triggers "..."` works with existing parser. Add `--triggers` flag if not already present.

#### Phase 4: Feedback + Digest

13. **Dismiss command:** `recall dismiss L059` CLI command + `commands/dismiss.md` slash command → appends dismiss event to session-log.
14. **Weekly digest:** Add `recall digest` CLI command with `--generate` flag. Session-start hook checks `.digest-last-run` and generates `reports/weekly-YYYY-WW.md` if 7+ days elapsed.
15. **Digest slash command:** `commands/digest.md` — displays latest digest file.
16. **RemoteTrigger integration (optional):** `commands/schedule-digest.md` slash command that creates a persistent `RemoteTrigger` with a weekly cron schedule to run `recall digest --generate`.

## File Changes

| File | Change |
|------|--------|
| `go/internal/eventlog/eventlog.go` | **New** — event log append/read/prune |
| `go/internal/eventlog/precision.go` | **New** — precision computation + trigger suggestions |
| `go/internal/scoring/bm25.go` | Modify — append triple-weighted trigger terms during tokenization |
| `go/cmd/recall/app.go` | Add `stats`, `dismiss`, `digest` commands |
| `go/cmd/recall-hook/inject.go` | Emit injection events to session-log from `runInjectCombined()` |
| `go/cmd/recall-hook/stop.go` | Emit citation events to session-log from `executeStop()` |
| `go/cmd/recall-hook/stopall.go` | Pass through to `stop.go` changes |
| `hooks/scripts/smart-inject-hook.sh` | Pass query text + scores to Go binary for event logging |
| `go/internal/lessons/decay.go` | Add `eventlog.Prune()` call after velocity decay |
| `commands/stats.md` | **New** — `/recall stats` slash command |
| `commands/dismiss.md` | **New** — `/recall dismiss` slash command |
| `commands/digest.md` | **New** — `/recall digest` slash command |
| `config.json` | Add `eventLogEnabled` (default: true), `eventLogRetentionDays` (default: 90), `digestEnabled` (default: true) |

## Config Defaults

```json
{
  "eventLogEnabled": true,
  "eventLogRetentionDays": 90,
  "digestEnabled": true
}
```

- `eventLogEnabled` — master switch for session-log writing. If false, no events are logged but existing log data is preserved (not pruned).
- `eventLogRetentionDays` — events older than this are pruned during decay. 0 means no pruning (infinite retention). Default 90 days balances disk usage with trend analysis depth.
- `digestEnabled` — whether to auto-generate weekly digests at session start. If false, `/recall digest` still works on existing reports.
