# Injection Precision Improvements

**Date**: 2026-03-31
**Status**: Approved
**Motivation**: Long sessions in unrelated domains (e.g., USB scanner debugging) get injected with irrelevant lessons (e.g., "design tokens") because BM25 only scores against query text, and all lessons have equal injection eagerness regardless of citation history.

## Feature 1: File-Path Context in BM25 Scoring

### Goal

Augment the BM25 query with file-path tokens from the session so domain-irrelevant lessons score lower naturally.

### Data Flow

```
Turn 1 (smart-inject-hook):
  1. Read session-files-{session_id}.json → empty/missing
  2. Fallback: run `git diff --name-only` + `git status --porcelain` (~20ms)
  3. Extract path segments: "src/system/usb.c" → ["src", "system", "usb"]
  4. Append to BM25 query: "{user prompt} src system usb"
  5. Score with augmented query

Turn 1 (stop-hook, after response):
  6. Parse transcript tool_use blocks for file_path fields
  7. Write unique paths to session-files-{session_id}.json

Turn 2+ (smart-inject-hook):
  8. Read session-files-{session_id}.json → has paths from prior turns
  9. Extract path segments, append to query, score

Turn 2+ (stop-hook):
  10. Incremental parse (from checkpoint), merge new paths into file
```

### Path Segment Extraction

- Split on `/`, drop common prefixes (`.`, `home`, `users`, project root)
- Drop file extensions (`.c`, `.py`, `.go`, `.sh`)
- Keep directory names and file stems: `src/api/handlers/auth.go` → `["src", "api", "handlers", "auth"]`
- Deduplicate, cap at ~20 tokens to avoid drowning the actual query
- Path tokens appended once (not repeated) — BM25 naturally gives them proportional weight alongside prompt tokens

### Session File Format

Location: `~/.local/state/claude-recall/session-files-{session_id}.json`

```json
{
  "paths": ["src/system/usb.c", "src/api/input.c", "docs/scanner.md"],
  "updated": "2026-03-31T10:30:00Z"
}
```

Cleanup: Deleted on next `SessionStart` (alongside session-dedup files).

### Changes Required

| Component | File | Change |
|-----------|------|--------|
| Go transcript parser | `go/internal/transcript/parser.go` | Extract `file_path` from `tool_use` input blocks |
| Go stop hook | `go/cmd/recall-hook/stopall.go` | Write session-files JSON after citation extraction |
| Smart-inject hook | `plugins/claude-recall/hooks/scripts/smart-inject-hook.sh` | Read session-files, run git fallback, extract path tokens, append to query string before calling score-local |
| Inject hook | `plugins/claude-recall/hooks/scripts/inject-hook.sh` | Clear session-files on SessionStart |

### One-Turn Lag

File-path context lags by one turn (stop hook runs after response, smart-inject reads on next prompt). First prompt of a session uses git diff/status as seed. This is acceptable — noise accumulates over time, not on the first prompt.

---

## Feature 2: Negative Feedback Loop

### Goal

Lessons injected repeatedly without citation get a score penalty, reducing their injection frequency over time.

### State Files

| Scope | Location |
|-------|----------|
| Project (`L###`) | `.claude-recall/injection-stats.json` |
| System (`S###`) | `~/.local/state/claude-recall/injection-stats.json` |

```json
{
  "L001": {"injections": 12, "citations": 8},
  "L008": {"injections": 7, "citations": 0},
  "S003": {"injections": 15, "citations": 3}
}
```

### Counter Updates

- **Injection increment**: In smart-inject-hook, after a lesson passes BM25 scoring and session dedup (actually shown to agent). SessionStart injections do NOT count — those are top-by-stars, not relevance-scored.
- **Citation increment**: In stop-hook, when `[L###]`/`[S###]` pattern found in response. Piggybacks on existing citation tracking.

### Penalty Calculation

Applied after BM25 scoring, before final ranking:

```
if injections >= 5 and (citations / injections) < 0.2:
    score *= 0.5
```

### Configuration

In `config.json`:

```json
{
  "feedbackMinInjections": 5,
  "feedbackMaxCiteRatio": 0.2,
  "feedbackPenalty": 0.5
}
```

### Observability

Logged at debug level 2:
```json
{"event": "feedback_penalty", "lesson_id": "L008", "injections": 7, "citations": 0, "penalty": 0.5}
```

### Scope Routing

- `L###` lessons → project `injection-stats.json`
- `S###` lessons → system `injection-stats.json`

### Reset Mechanisms

- `/recall dismiss` zeroes out injection-stats for that lesson
- Editing a lesson's content resets its counters (content changed, old stats are stale)
- No automatic decay — counters accumulate. If a lesson gets cited eventually, the ratio improves naturally.

### Edge Cases

- New lessons: 0/0 → no penalty possible until 5+ injections
- 5 injections / 1 citation = 0.2 → exactly at threshold, no penalty
- Penalized at 7/0 then cited twice → 7/2 = 0.29 → penalty lifts

---

## Interaction Between Features

Features are **independent signals** that stack:

1. File-path tokens augment the BM25 query → domain-irrelevant lessons score lower
2. Negative feedback applies a multiplier after BM25 → chronically uncited lessons score even lower

They don't know about each other. Feature 1 handles domain mismatches (UI lesson in a systems session). Feature 2 handles universally low-value lessons (never cited even in the right context).

Future consideration: per-file-path-cluster feedback (Feature 2 tracks inject:cite ratio per domain). Not needed for v1 — if Feature 1 stops injecting a lesson in irrelevant contexts, the global ratio naturally improves.

---

## Testing Strategy

- **Unit tests**: Path segment extraction, penalty calculation, injection-stats read/write
- **Integration tests**: Full flow — inject with file context, verify scoring changes; inject N times without citation, verify penalty applies
- **Manual validation**: Run in helixscreen project, verify UI lessons don't appear during systems work
