# Architecture Guide

Deep dive into Claude Recall's internal architecture for contributors.

## System Overview

Claude Recall is a learning system for AI coding agents that captures lessons across sessions and tracks multi-step work via handoffs. The system uses a dual-language architecture: Go for performance-critical hot paths and Python for complex logic and AI operations.

```
                           ┌─────────────────────────────────────────────────────────────────────────┐
                           │                           Claude Code Hooks                              │
                           │  ┌───────────┐ ┌──────────────┐ ┌────────┐ ┌───────────┐ ┌────────────┐ │
                           │  │  inject   │ │smart-inject  │ │  stop  │ │precompact │ │post-tooluse│ │
                           │  │ (session  │ │(first prompt │ │(after  │ │ (before   │ │(ExitPlan,  │ │
                           │  │  start)   │ │  relevance)  │ │ turn)  │ │ compact)  │ │ TodoWrite) │ │
                           │  └─────┬─────┘ └──────┬───────┘ └───┬────┘ └─────┬─────┘ └──────┬─────┘ │
                           └───────┼──────────────┼─────────────┼───────────┼──────────────┼────────┘
                                   │               │              │            │              │
                                   ▼               ▼              ▼            ▼              ▼
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                                    Shell Scripts Layer                                    │
│                              (plugins/claude-recall/hooks/scripts/)                       │
│                                                                                          │
│  • Parse JSON from Claude Code stdin                                                     │
│  • Route to Go (hot path) or Python (cold path)                                         │
│  • Handle byte-offset checkpointing for incremental parsing                             │
└──────────────────────────────────────────────────────────────────────────────────────────┘
                                   │               │
                    ┌──────────────┴───────────────┴──────────────┐
                    │                                             │
                    ▼                                             ▼
┌───────────────────────────────────┐       ┌─────────────────────────────────────────────┐
│       Go Binary (Hot Path)        │       │           Python Core (Cold Path)           │
│       go/cmd/recall-hook/         │       │                  core/                       │
│                                   │       │                                             │
│  • Citation extraction            │       │  • Lesson management (add, edit, delete)    │
│  • Transcript parsing             │       │  • Handoff tracking                         │
│  • Checkpoint management          │       │  • AI operations (Haiku scoring)            │
│  • File locking                   │       │  • Decay and promotion                      │
│  • Target: <100ms                 │       │  • Context extraction                       │
│                                   │       │  • Complex business logic                   │
│  go/internal/                     │       │                                             │
│  ├── citations/  (extraction)    │       │  • lessons.py    (LessonsMixin)             │
│  ├── transcript/ (JSONL parser)  │       │  • handoffs.py   (HandoffsMixin)            │
│  ├── lessons/    (store, decay)  │       │  • manager.py    (LessonsManager)           │
│  ├── handoffs/   (store, parser) │       │  • cli.py        (argparse entry)           │
│  ├── checkpoint/ (byte offsets)  │       │  • commands.py   (command registry)         │
│  ├── lock/       (flock wrapper) │       │  • models.py     (dataclasses)              │
│  └── config/     (env + json)    │       │  • parsing.py    (markdown format)          │
└───────────────────────────────────┘       └─────────────────────────────────────────────┘
                    │                                             │
                    └──────────────────┬──────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                                    Storage Layer                                         │
│                                                                                          │
│  Project Data (.claude-recall/)           State Data (~/.local/state/claude-recall/)    │
│  ├── LESSONS.md      (project lessons)    ├── LESSONS.md    (system lessons)            │
│  ├── HANDOFFS.md     (active handoffs)    ├── checkpoints.txt (Go byte offsets)        │
│  └── HANDOFFS_LOCAL.md (stealth mode)     ├── effectiveness.json                       │
│                                           ├── relevance-cache.json                      │
│                                           ├── decay-state.json                          │
│                                           └── transcript_offsets.json                   │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

## Performance Architecture

### Hot Path (Go)

The Go binary (`go/cmd/recall-hook`) handles performance-critical operations that run on every turn:

```
stop-hook.sh
    │
    ├─▶ Go Binary (if available)     Target: <100ms total
    │   │
    │   ├─▶ Parse JSON input         ~1ms
    │   ├─▶ Load checkpoint          ~2ms  (byte offset for session)
    │   ├─▶ Seek + parse transcript  ~5-20ms (only new content)
    │   ├─▶ Extract citations        ~1ms  (regex on assistant text)
    │   ├─▶ Update lesson files      ~10-30ms (with file locking)
    │   └─▶ Save checkpoint          ~2ms
    │
    └─▶ Fallback to Python           ~2-3 seconds (startup overhead)
```

**Key optimizations:**
- Single binary startup (~5ms) vs Python interpreter (~200ms)
- Byte-offset incremental parsing (only read new transcript content)
- Compiled regex for citation extraction
- Direct file I/O with flock() locking

**Files:**
```
go/cmd/recall-hook/
├── main.go           Entry point, command routing
└── stop.go           Stop hook implementation

go/internal/
├── citations/
│   ├── extractor.go      Regex-based [L###]/[S###] extraction
│   └── extractor_test.go
├── transcript/
│   ├── parser.go         JSONL parsing with byte offsets
│   └── parser_test.go
├── checkpoint/
│   ├── checkpoint.go     Session -> byte offset mapping
│   └── checkpoint_test.go
├── lessons/
│   ├── store.go          Lesson CRUD with file locking
│   ├── parser.go         LESSONS.md format parsing
│   ├── decay.go          Velocity/uses decay logic
│   └── *_test.go
└── lock/
    ├── filelock.go       syscall.Flock wrapper
    └── filelock_test.go
```

### Cold Path (Python)

Python handles complex operations that don't need sub-100ms latency:

```
inject-hook.sh                         smart-inject-hook.sh
    │                                      │
    ▼                                      ▼
Python CLI                             Python CLI
    │                                      │
    ├─▶ inject-combined                    └─▶ score-relevance
    │   ├─▶ List all lessons                   ├─▶ List all lessons
    │   ├─▶ Sort by weighted score             ├─▶ Build Haiku prompt
    │   ├─▶ Get active handoffs                ├─▶ Call Claude API (Haiku)
    │   └─▶ Format JSON output                 ├─▶ Parse scores
    │                                          └─▶ Cache results
    └─▶ decay (weekly, background)
        ├─▶ Apply velocity half-life
        └─▶ Decrement stale uses
```

**Files:**
```
core/
├── cli.py              argparse entry point
├── commands.py         Command registry pattern
├── manager.py          LessonsManager (combines mixins)
├── lessons.py          LessonsMixin - all lesson operations
├── handoffs.py         HandoffsMixin - handoff tracking
├── models.py           Dataclasses and constants
├── parsing.py          Markdown format serialization
├── file_lock.py        fcntl.flock context manager
├── config.py           Settings from ~/.claude/settings.json
├── debug_logger.py     Structured JSON logging
├── alerts.py           Health monitoring
├── context_extractor.py Haiku-based context extraction
└── paths.py            Path resolution helpers
```

## Data Flow

### Session Lifecycle

```
┌──────────────────────────────────────────────────────────────────────────┐
│ 1. SESSION START (inject-hook.sh)                                        │
│                                                                          │
│    Claude Code                                                           │
│        │                                                                 │
│        ▼ stdin: {"cwd": "/project", "session_id": "abc123"}             │
│    inject-hook.sh                                                        │
│        │                                                                 │
│        ├─▶ Python: inject-combined 5                                     │
│        │       ├─▶ Load project + system lessons                        │
│        │       ├─▶ Sort by (uses * 0.7 + velocity * 0.3)               │
│        │       ├─▶ Load active handoffs                                  │
│        │       └─▶ Return JSON {lessons, handoffs, todos}               │
│        │                                                                 │
│        ├─▶ Run decay if due (weekly, background)                        │
│        │                                                                 │
│        └─▶ stdout: {"hookSpecificOutput": {"additionalContext": ...}}   │
│                                                                          │
│    Context injected into Claude's system prompt                          │
└──────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────┐
│ 2. FIRST PROMPT (smart-inject-hook.sh)                                   │
│                                                                          │
│    User types first message                                              │
│        │                                                                 │
│        ▼ stdin: {"prompt": "Fix the auth bug", "cwd": ...}              │
│    smart-inject-hook.sh                                                  │
│        │                                                                 │
│        ├─▶ Check: is first prompt? (no assistant messages yet)          │
│        │                                                                 │
│        └─▶ Python: score-relevance "Fix the auth bug" --top 5           │
│                ├─▶ Check relevance cache (Jaccard similarity)            │
│                ├─▶ Cache miss: call Haiku for scoring                    │
│                ├─▶ Parse: "L001: 8\nL002: 3\n..."                        │
│                ├─▶ Cache results (7-day TTL)                             │
│                └─▶ Return top N lessons with scores                      │
│                                                                          │
│    Query-relevant lessons added to context                               │
└──────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────┐
│ 3. AFTER EACH TURN (stop-hook.sh)                                        │
│                                                                          │
│    Claude completes response                                             │
│        │                                                                 │
│        ▼ stdin: {"transcript_path": "~/.claude/.../transcript.jsonl"}   │
│    stop-hook.sh                                                          │
│        │                                                                 │
│        ├─▶ Parse transcript once (jq, cache result)                     │
│        │       • Extract assistant texts                                 │
│        │       • Extract citations [L###], [S###]                       │
│        │       • Extract AI LESSON: patterns                             │
│        │       • Extract HANDOFF: patterns                               │
│        │                                                                 │
│        ├─▶ TRY: Go binary (hot path)                                    │
│        │       ├─▶ Load checkpoint (byte offset)                        │
│        │       ├─▶ Parse only new transcript content                    │
│        │       ├─▶ Extract citations from assistant messages            │
│        │       ├─▶ Cite each lesson (update uses/velocity)              │
│        │       └─▶ Save new checkpoint                                   │
│        │                                                                 │
│        └─▶ FALLBACK: Python batch processing                            │
│                ├─▶ Process citations                                     │
│                ├─▶ Process handoff commands                              │
│                ├─▶ Sync TodoWrite to handoffs                            │
│                └─▶ Add AI-generated lessons                              │
└──────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────┐
│ 4. BEFORE COMPACTION (precompact-hook.sh)                                │
│                                                                          │
│    Auto-compact or /compact triggered                                    │
│        │                                                                 │
│        ▼ stdin: {"transcript_path": ..., "trigger": "auto"}             │
│    precompact-hook.sh                                                    │
│        │                                                                 │
│        ├─▶ Find most recent active handoff                              │
│        │                                                                 │
│        ├─▶ If no handoff: detect major work                             │
│        │       ├─▶ 4+ file edits? → auto-create handoff                 │
│        │       ├─▶ 3+ TodoWrite calls? → auto-create handoff            │
│        │       └─▶ Minor work? → save session snapshot                  │
│        │                                                                 │
│        └─▶ Python: extract-context + set-context                        │
│                ├─▶ Read transcript (tool_use, thinking blocks)          │
│                ├─▶ Call Haiku: summarize progress                        │
│                └─▶ Update handoff with structured context                │
│                                                                          │
│    Context preserved for post-compaction continuation                    │
└──────────────────────────────────────────────────────────────────────────┘
```

### Lesson Lifecycle

```
                                    ADD
                                     │
                                     ▼
    ┌─────────────────────────────────────────────────────────────┐
    │                        LESSONS.md                           │
    │                                                             │
    │  ### [L001] [*----|-----] Fix auth with absolute paths      │
    │  - **Uses**: 1 | **Velocity**: 0 | **Learned**: 2024-01-15  │
    │    | **Last**: 2024-01-15 | **Category**: correction        │
    │  > Always use absolute paths in shell hooks - relative      │
    │  > paths fail when cwd changes.                             │
    └─────────────────────────────────────────────────────────────┘
                                     │
           ┌─────────────────────────┼─────────────────────────┐
           │                         │                         │
           ▼                         ▼                         ▼
        CITE                      DECAY                    PROMOTE
           │                         │                         │
           │  Claude outputs:        │  Weekly (background):   │  At 50 uses:
           │  "Applying [L001]..."   │  velocity *= 0.5        │  L001 → S001
           │                         │  if stale: uses -= 1    │  Move to system
           ▼                         ▼                         ▼
    ┌─────────────────────────────────────────────────────────────┐
    │  ### [L001] [***--|*----] Fix auth with absolute paths      │
    │  - **Uses**: 12 | **Velocity**: 1.5 | ...                   │
    │                                                             │
    │  Uses: log-scale stars (lifetime value)                     │
    │  Velocity: decaying recency score (recent activity)         │
    │  Ranking: uses * 0.7 + velocity * 0.3                       │
    └─────────────────────────────────────────────────────────────┘
```

**Rating System:**
- **Uses** (left stars): Total citations, capped at 100. Log-scale display:
  - 1-2 = `*----`, 3-5 = `**---`, 6-12 = `***--`, 13-30 = `****-`, 31+ = `*****`
- **Velocity** (right stars): Recency score, decays 50% per week
  - Incremented by 1 on each citation
  - Floored to 0 when below 0.01

### Handoff Lifecycle

```
    ┌──────────────────────────────────────────────────────────────────────┐
    │                              CREATE                                   │
    │                                                                       │
    │  Claude outputs: "HANDOFF: Implement auth refresh"                   │
    │  Or: TodoWrite creates tasks → auto-creates handoff                  │
    │  Or: precompact-hook detects major work → auto-creates               │
    └──────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
    ┌──────────────────────────────────────────────────────────────────────┐
    │                           HANDOFFS.md                                 │
    │                                                                       │
    │  ### [hf-a1b2c3d] Implement auth refresh                             │
    │  - **Status**: in_progress | **Phase**: implementing | **Agent**: gp │
    │  - **Created**: 2024-01-15 | **Updated**: 2024-01-15                 │
    │  - **Description**: Add token refresh for expired sessions           │
    │                                                                       │
    │  **Tried**:                                                          │
    │  1. [success] Added refresh endpoint to auth.py                      │
    │  2. [fail] Tried caching tokens in memory - race condition           │
    │  3. [partial] Redis cache works but needs TTL tuning                 │
    │                                                                       │
    │  **Next**: Configure Redis TTL based on token expiry                 │
    │                                                                       │
    │  **Checkpoint**: Working on Redis integration, tests passing         │
    └──────────────────────────────────────────────────────────────────────┘
                                       │
           ┌───────────────────────────┼───────────────────────────┐
           │                           │                           │
           ▼                           ▼                           ▼
        UPDATE                     COMPLETE                    ARCHIVE
           │                           │                           │
           │  HANDOFF UPDATE:          │  HANDOFF COMPLETE         │  After 3 days
           │  tried success - ...      │  or git commit            │  or 7 days stale
           │  next: ...                │                           │
           │  checkpoint: ...          │  Extract lessons:         │
           │  phase: review            │  "Any patterns to         │
           │                           │   record?"                │
           ▼                           ▼                           ▼
    ┌─────────────────────────────────────────────────────────────────────┐
    │                       HANDOFFS_ARCHIVE.md                            │
    │                                                                       │
    │  Completed handoffs preserved for reference                          │
    │  Can extract lessons retroactively                                   │
    └─────────────────────────────────────────────────────────────────────┘
```

**Handoff Phases:**
- `research` - Investigating the problem
- `planning` - Designing the solution
- `implementing` - Writing code
- `review` - Testing and code review

**Handoff Statuses:**
- `not_started` - Created but not begun
- `in_progress` - Actively working
- `blocked` - Waiting on dependencies
- `ready_for_review` - Work complete, needs review
- `completed` - Done (triggers lesson extraction prompt)

## Storage Layer

### Markdown Files

**Format Specification (LESSONS.md):**
```markdown
# LESSONS.md - Project Level

> **Lessons System**: Cite lessons with [L###] when applying them.
> Stars accumulate with each use. At 50 uses, project lessons promote to system.
>
> **Add lessons**: `LESSON: [category:] title - content`
> **Categories**: pattern, correction, decision, gotcha, preference

## Active Lessons

### [L001] [***--|*----] Lesson Title
- **Uses**: 12 | **Velocity**: 1.5 | **Learned**: 2024-01-15 | **Last**: 2024-01-20 | **Category**: pattern
> Lesson content goes here. Can span multiple lines.
> Each line is prefixed with `> `.
```

**Format Specification (HANDOFFS.md):**
```markdown
# HANDOFFS.md - Active Work Tracking

> Track ongoing work with tried steps and next steps.
> When completed, review for lessons to extract.

## Active Handoffs

### [hf-a1b2c3d] Handoff Title
- **Status**: in_progress | **Phase**: implementing | **Agent**: general-purpose
- **Created**: 2024-01-15 | **Updated**: 2024-01-20
- **Refs**: src/auth.py:45-60 | tests/test_auth.py:20
- **Description**: What this work is about

**Tried**:
1. [success] Description of successful attempt
2. [fail] Description of failed attempt
3. [partial] Description of partially successful attempt

**Next**: What to do next

**Checkpoint**: Progress summary for session handoff
```

**Locking Strategy:**

Both Go and Python use `flock()` for file-level locking:

```
Go (go/internal/lock/filelock.go):
┌─────────────────────────────────────────┐
│  fl, err := lock.Acquire(path + ".lock")│
│  if err != nil { return err }           │
│  defer fl.Release()                     │
│  // ... read/modify/write file ...      │
└─────────────────────────────────────────┘

Python (core/file_lock.py):
┌─────────────────────────────────────────┐
│  with FileLock(file_path):              │
│      # ... read/modify/write file ...   │
└─────────────────────────────────────────┘
```

Lock files are created as `<filename>.lock` (e.g., `LESSONS.md.lock`) and are never deleted to avoid race conditions.

### State Files

Located in `~/.local/state/claude-recall/`:

| File | Purpose | Format |
|------|---------|--------|
| `LESSONS.md` | System-level lessons | Markdown |
| `checkpoints.txt` | Go byte offsets per session | `session_id offset\n` |
| `transcript_offsets.json` | Shell byte offsets | `{"session_id": offset}` |
| `decay-state.json` | Last decay timestamp | `{"last_decay": "..."}` |
| `effectiveness.json` | Citation success rates | `{"L001": {...}}` |
| `relevance-cache.json` | Haiku score cache | `{"entries": {...}}` |
| `session-handoffs.json` | Session-to-handoff mapping | `{"session_id": {...}}` |

**Checkpoint Files:**

The system uses byte offsets for incremental transcript parsing:

```
First run:                    Subsequent runs:
┌─────────────────────┐       ┌─────────────────────┐
│ Parse full file     │       │ Seek to offset      │
│ offset = 0          │       │ Parse from there    │
│ Save file size      │       │ Skip partial line   │
└─────────────────────┘       └─────────────────────┘
         │                             │
         ▼                             ▼
   checkpoints.txt              checkpoints.txt
   abc123 0                     abc123 45678
```

## Hook System

### Claude Code Hooks

Claude Recall uses four hooks provided by Claude Code:

| Hook | Trigger | Purpose | Target Latency |
|------|---------|---------|----------------|
| `SessionStart` | Session begins | Inject lessons + handoffs | <500ms |
| `UserPromptSubmit` | User sends message | Capture prompt, relevance scoring, reminders | <2s (Haiku) |
| `Stop` | Assistant turn complete | Extract citations + patterns, sync handoffs | <100ms (Go) |
| `PreCompact` | Before context compaction | Preserve session progress | <3s (Haiku) |
| `PostToolUse:ExitPlanMode` | After ExitPlanMode | Create handoff from plan | <500ms |
| `PostToolUse:TodoWrite` | After TodoWrite | Sync todos to handoffs | <500ms |

**Hook Registration (hooks/hooks.json):**
```json
{
  "hooks": {
    "SessionStart": [{
      "hooks": [
        { "type": "command", "command": "bash \"${CLAUDE_PLUGIN_ROOT}/hooks/scripts/inject-hook.sh\"", "timeout": 5000 }
      ]
    }],
    "UserPromptSubmit": [{
      "hooks": [
        { "type": "command", "command": "bash \"${CLAUDE_PLUGIN_ROOT}/hooks/scripts/capture-hook.sh\"", "timeout": 5000 },
        { "type": "command", "command": "bash \"${CLAUDE_PLUGIN_ROOT}/hooks/scripts/smart-inject-hook.sh\"", "timeout": 15000 },
        { "type": "command", "command": "bash \"${CLAUDE_PLUGIN_ROOT}/hooks/scripts/lesson-reminder-hook.sh\"", "timeout": 2000 }
      ]
    }],
    "Stop": [{
      "hooks": [
        { "type": "command", "command": "bash \"${CLAUDE_PLUGIN_ROOT}/hooks/scripts/stop-hook.sh\"", "timeout": 5000 },
        { "type": "command", "command": "bash \"${CLAUDE_PLUGIN_ROOT}/hooks/scripts/session-end-hook.sh\"", "timeout": 30000 }
      ]
    }],
    "PreCompact": [{
      "hooks": [
        { "type": "command", "command": "bash \"${CLAUDE_PLUGIN_ROOT}/hooks/scripts/precompact-hook.sh\"", "timeout": 45000 }
      ]
    }],
    "PostToolUse": [
      { "matcher": "ExitPlanMode", "hooks": [{ "type": "command", "command": "bash \"${CLAUDE_PLUGIN_ROOT}/hooks/scripts/post-exitplanmode-hook.sh\"", "timeout": 5000 }] },
      { "matcher": "TodoWrite", "hooks": [{ "type": "command", "command": "bash \"${CLAUDE_PLUGIN_ROOT}/hooks/scripts/post-todowrite-hook.sh\"", "timeout": 5000 }] }
    ]
  }
}
```

### Performance Optimizations

**1. Single jq Parse with Caching:**
```bash
# stop-hook.sh: Parse transcript ONCE, extract everything needed
TRANSCRIPT_CACHE=$(jq -s '{
    assistant_texts: [...],
    citations: [...],
    last_todowrite: ...,
    edit_count: ...,
    latest_timestamp: ...
}' "$transcript_path")

# Subsequent extractions are just jq queries on cached JSON
citations=$(echo "$TRANSCRIPT_CACHE" | jq -r '.citations[]')
```

**2. Go Binary for Citations:**
```bash
# Try Go first (fast), fall back to Python (slow)
if process_citations_go "$cwd" "$session_id" "$transcript_path"; then
    # Go processed citations in <100ms
else
    # Fallback: Python batch processing (~2s)
fi
```

**3. Byte-Offset Incremental Parsing:**
```
Transcript file:
┌─────────────────────────────────────────────┐
│ {"type":"user",...}\n                       │ ◄─── Already processed
│ {"type":"assistant",...}\n                  │      (offset 0-45678)
│ {"type":"user",...}\n                       │
├─────────────────────────────────────────────┤
│ {"type":"assistant",...}\n                  │ ◄─── New content
│ {"type":"user",...}\n                       │      (offset 45678+)
└─────────────────────────────────────────────┘

Go: r.Seek(offset, io.SeekStart) → parse only new
Shell: tail -c +$((offset + 1)) | tail -n +2
```

**4. Batch Python Operations:**
```bash
# Instead of N separate Python calls:
# python cli.py cite L001
# python cli.py cite L002
# python cli.py handoff update ...

# Single batch call:
echo "$TRANSCRIPT_CACHE" | python cli.py stop-hook-batch \
    --citations "L001,L002,L003" \
    --session-id "$session_id" \
    --ai-lessons '[...]'
```

## Testing Strategy

### Unit Tests

**Python (pytest):**
```bash
./run-tests.sh                    # All tests
./run-tests.sh tests/test_lessons_manager.py  # Specific file
./run-tests.sh -v --tb=short      # Verbose with short tracebacks
```

Key fixtures:
- `temp_lessons_base` - Isolated lessons directory
- `temp_state_dir` - Isolated state directory
- `temp_project_root` - Isolated project root

**Go:**
```bash
cd go && go test ./...            # All tests
go test ./internal/citations/...  # Specific package
go test -v -run TestExtract       # Specific test
```

### Integration Tests

**CLI subprocess tests** verify end-to-end behavior:
```python
def test_cite_command(temp_lessons_base, temp_state_dir, temp_project_root):
    env = {
        **os.environ,
        "CLAUDE_RECALL_BASE": str(temp_lessons_base),
        "CLAUDE_RECALL_STATE": str(temp_state_dir),
        "PROJECT_DIR": str(temp_project_root),
    }
    result = subprocess.run(
        [sys.executable, "core/cli.py", "cite", "L001"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
```

### Hook Tests

Shell script behavior testing:
```bash
./tests/test-stop-hook.sh         # Stop hook behavior
./tests/test-hook-guards.sh       # Recursion guards
./tests/test-velocity.sh          # Decay behavior
```

### Performance Tests

Latency thresholds enforced in Go tests:
```go
func TestStopHookLatency(t *testing.T) {
    start := time.Now()
    // ... execute stop hook ...
    elapsed := time.Since(start)
    if elapsed > 100*time.Millisecond {
        t.Errorf("Stop hook too slow: %v", elapsed)
    }
}
```

## Extension Points

### Adding a New Adapter

1. Create adapter directory: `adapters/<adapter-name>/`
2. Implement hook scripts that call `core/cli.py`
3. Register hooks with the target system
4. Add installation to `install.sh`

Example structure:
```
adapters/my-editor/
├── install.sh              # Adapter-specific installation
├── hooks/
│   ├── on-file-open.sh     # Hook implementation
│   └── on-file-save.sh
└── README.md
```

### Adding a New Command

1. Add command registration in `core/commands.py`:
```python
@command("my-command", help="Description")
class MyCommand(Command):
    @staticmethod
    def add_arguments(parser):
        parser.add_argument("arg1", help="...")

    def execute(self, args, manager):
        # Implementation
        return 0
```

2. The command is automatically available via CLI:
```bash
python core/cli.py my-command arg1
```

### Adding a New Store (Go)

1. Create package in `go/internal/<store-name>/`:
```go
package mystore

type Store struct {
    path string
}

func NewStore(path string) *Store {
    return &Store{path: path}
}

func (s *Store) Get(id string) (*Model, error) { ... }
func (s *Store) List() ([]*Model, error) { ... }
func (s *Store) Add(m *Model) error { ... }
```

2. Add file locking using `go/internal/lock`:
```go
import "github.com/pbrown/claude-recall/internal/lock"

func (s *Store) Add(m *Model) error {
    fl, err := lock.Acquire(s.path + ".lock")
    if err != nil {
        return err
    }
    defer fl.Release()
    // ... modify file ...
}
```

3. Wire into `go/cmd/recall-hook/` if needed for hot path operations.

## Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `CLAUDE_RECALL_BASE` | Installation directory | `~/.config/claude-recall` |
| `CLAUDE_RECALL_STATE` | State directory | `~/.local/state/claude-recall` |
| `PROJECT_DIR` | Project root | Git root or cwd |
| `CLAUDE_RECALL_DEBUG` | Debug level (0-3) | 0 |
| `CLAUDE_RECALL_SESSION` | Current session ID | (set by hooks) |
| `LESSONS_SCORING_ACTIVE` | Guard for recursive Haiku calls | (unset) |

Legacy aliases (deprecated):
- `RECALL_BASE` → `CLAUDE_RECALL_BASE`
- `LESSONS_BASE` → `CLAUDE_RECALL_BASE`
- `RECALL_DEBUG` → `CLAUDE_RECALL_DEBUG`
- `LESSONS_DEBUG` → `CLAUDE_RECALL_DEBUG`
