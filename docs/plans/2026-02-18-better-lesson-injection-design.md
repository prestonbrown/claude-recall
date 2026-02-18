# Better Lesson Injection

## Problem

1. **Haiku scoring is dead** - Claude Code uses OAuth internally, never exports `ANTHROPIC_API_KEY` to hook environment. Relevance scoring silently exits on every session.
2. **Single injection point** - Lessons only inject at session start (top N by stars) and first prompt (relevance-scored, but never fires per #1).
3. **Handoffs are dead weight** - Never worked reliably, currently disabled. Code in hooks adds complexity and processing time for no value.

## Design

### 1. Local BM25 Scoring (replaces Haiku)

Replace the Haiku API call with local BM25 text retrieval scoring.

- **Corpus**: All lesson titles + content, tokenized
- **Query**: User prompt or subagent output
- **Implementation**: Pure Python BM25 in `core/scoring.py` (no external deps). Standard BM25 with k1=1.5, b=0.75.
- **Go fast path**: New `score-local` command in Go binary that calls Python or reimplements BM25 natively
- **Performance target**: <50ms for ~100 lessons
- **Haiku fallback**: If `ANTHROPIC_API_KEY` is set, optionally use Haiku for higher quality. Config flag `useHaikuScoring: true` to opt in. Default: local only.

Tokenization: lowercase, split on whitespace/punctuation, strip common stop words (the, a, is, etc.). No stemming needed for this corpus size.

### 2. Multi-Point Lesson Injection

#### UserPromptSubmit (every substantive prompt)

Currently restricted to first prompt only. Remove that restriction.

- Skip prompts < 20 chars (greetings, "yes", "no")
- Score prompt against lesson corpus via BM25
- Inject top 3-5 scoring lessons with score above threshold
- Deduplicate against lessons already injected this session (track in state file)

#### SubagentStop (new)

After subagents complete work, inject relevant lessons before the main agent acts on results.

- Hook receives subagent output in event data
- Score subagent output against lesson corpus
- Inject top 3 relevant lessons
- Same deduplication logic

#### SessionStart (unchanged)

- Top N lessons by star rating (no query to score against)
- No handoff injection (removed)

### 3. Remove Handoffs from Hooks

Strip all handoff processing from the hook pipeline:

- **stop-hook.sh**: Remove handoff pattern parsing (HANDOFF:, HANDOFF UPDATE, HANDOFF COMPLETE, PLAN MODE:)
- **stop-hook Go**: Remove handoff processing from `stop-all` command
- **inject-hook.sh**: Remove handoff injection from SessionStart output
- **session-end-hook.sh**: Remove session snapshot logic (was for handoff recovery)
- **post-todowrite-hook.sh**: Remove entirely (only synced todos to handoffs)
- **post-exitplanmode-hook.sh**: Remove entirely (only handled plan-to-handoff)
- **hooks-config.json**: Remove PostToolUse hooks for TodoWrite and ExitPlanMode
- **PreCompact hook**: Remove if it only served handoffs

Keep `core/handoffs.py` and CLI commands intact - they're inert without hooks and can be removed in a follow-up.

### 4. Session Deduplication

Track which lessons have been injected this session to avoid repeating them:

- State file: `~/.local/state/claude-recall/session-injections-{session_id}.json`
- Contains set of lesson IDs already injected
- Cleared on SessionStart
- Before injecting, filter out already-seen lessons
- Fallback: if a lesson was injected <5 prompts ago, skip it

## What Stays the Same

- Lesson storage format (LESSONS.md), star ratings, decay
- Citation tracking in stop hook ([L001], [S001] parsing)
- `LESSON:` capture from user prompts (capture-hook.sh)
- lesson-reminder-hook.sh (periodic high-star lesson reminders)
- All CLI commands (`recall add`, `recall cite`, `recall list`, etc.)
- OpenCode adapter (separate injection path)

## File Impact Summary

| Action | Files |
|--------|-------|
| New | `core/scoring.py`, `go/internal/scoring/bm25.go` |
| Modify | `smart-inject-hook.sh`, `stop-hook.sh`, `inject-hook.sh`, `hooks-config.json`, Go `stop-all` command |
| Remove | `post-todowrite-hook.sh`, `post-exitplanmode-hook.sh`, `session-end-hook.sh` (if handoff-only) |
| Add hook | SubagentStop hook script |
