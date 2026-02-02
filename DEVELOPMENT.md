# Development Guide

Architecture, internals, and contributing guide for the Claude Recall system.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                       AI Agent                               │
│  (Claude Code, OpenCode, etc.)                              │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    Adapters Layer                            │
│  ┌─────────────────────┐    ┌─────────────────────┐         │
│  │   claude-code/      │    │    opencode/        │         │
│  │   - inject-hook.sh  │    │    - plugin.ts      │         │
│  │   - stop-hook.sh    │    │    - ...            │         │
│  └─────────────────────┘    └─────────────────────┘         │
└─────────────────────────────────────────────────────────────┘
                              │
           ┌──────────────────┴──────────────────┐
           ▼                                     ▼
┌─────────────────────────┐       ┌─────────────────────────┐
│  Go Performance Layer   │       │      Python Core        │
│  (fast path: ~100ms)    │       │  (slow path: ~2-3s)     │
│  ┌───────────────────┐  │       │  ┌───────────────────┐  │
│  │ Citation Extract  │  │       │  │ Full Processing   │  │
│  │ Transcript Parse  │  │       │  │ Decay/Promotion   │  │
│  │ Store Read/Write  │  │       │  │ Complex Commands  │  │
│  └───────────────────┘  │       │  └───────────────────┘  │
└─────────────────────────┘       └─────────────────────────┘
           │                                     │
           └──────────────────┬──────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     Storage Layer                            │
│  ~/.local/state/claude-recall/                               │
│  ├── LESSONS.md           # System-wide lessons              │
│  ├── debug.log            # Debug logs (XDG state)           │
│  ├── .decay-last-run      # Decay timestamp                  │
│  └── .citation-state/     # Per-session checkpoints          │
│                                                              │
│  ~/.config/claude-recall/                                    │
│  └── config.json          # User configuration (optional)    │
│                                                              │
│  $PROJECT/.claude-recall/                                    │
│  ├── LESSONS.md           # Project-specific lessons         │
│  └── HANDOFFS.md          # Active work tracking             │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    TUI / Alerting                            │
│  ┌─────────────────────┐    ┌─────────────────────┐         │
│  │   Debug TUI         │    │    Alerting         │         │
│  │   - Log viewer      │    │    - Stale handoffs │         │
│  │   - Session stats   │    │    - Latency spikes │         │
│  │   - Real-time       │    │    - Error rates    │         │
│  └─────────────────────┘    └─────────────────────┘         │
└─────────────────────────────────────────────────────────────┘
```

## Core Components

### Core Python Module

The primary implementation in Python. Located at `core/` with entry point `cli.py`.

#### Data Structures

```python
@dataclass
class Lesson:
    id: str              # L001, S001, etc.
    title: str
    content: str
    uses: int            # Total citation count
    velocity: float      # Recent activity (decays over time)
    learned: date
    last_used: date
    category: str        # pattern, correction, gotcha, preference, decision
    source: str = "human"    # human or ai
    level: str = "project"   # project or system
    promotable: bool = True  # False = never promote to system level
    lesson_type: str = ""    # constraint|informational|preference
    triggers: List[str] = [] # Keywords for matching relevance

    @property
    def tokens(self) -> int: # Estimated from title + content

@dataclass
class Handoff:
    id: str              # hf-abc1234 (hash-based for multi-agent safety)
    title: str
    status: str          # not_started, in_progress, blocked, completed
    created: date
    updated: date
    description: str = ""
    next_steps: str = ""
    phase: str = "research"      # research, planning, implementing, review
    agent: str = "user"          # explore, general-purpose, plan, review, user
    refs: List[str] = []         # file:line refs (e.g., "core/main.py:50")
    tried: List[TriedStep] = []
    checkpoint: str = ""         # Progress summary
    last_session: Optional[date] = None
    handoff: Optional[HandoffContext] = None  # Rich context
    blocked_by: List[str] = []   # IDs of blocking handoffs
    stealth: bool = False        # If True, stored in HANDOFFS_LOCAL.md
    sessions: List[str] = []     # Linked session IDs
```

#### Key Functions

| Function | Description |
|----------|-------------|
| `add(category, title, content)` | Add project lesson |
| `add_system(category, title, content)` | Add system lesson |
| `add_ai(category, title, content)` | Add AI-proposed lesson (🤖 marker) |
| `cite(lesson_id)` | Increment uses and velocity |
| `edit(lesson_id, new_content)` | Update lesson content |
| `delete(lesson_id)` | Remove a lesson |
| `inject(count)` | Generate top N lessons for context |
| `decay(days)` | Reduce velocity for stale lessons |
| `promote(lesson_id)` | Move project lesson to system |
| `handoff_add(title, phase, agent)` | Create new handoff |
| `handoff_update(id, **kwargs)` | Update handoff fields |
| `handoff_complete(id)` | Mark complete, prompt for lessons |
| `handoff_inject()` | Generate handoff context |

#### Rating System

The dual-dimension rating shows both total usage and recent activity:

```
[*----|-----]  1 use, no velocity (new lesson)
[**---|+----]  3 uses, some recent activity
[****-|**---]  15 uses, moderate velocity
[*****|*****]  31+ uses, high velocity (very active)
```

**Left side (uses)**: Logarithmic scale of total citations
- 1 star: 1-2 uses
- 2 stars: 3-5 uses
- 3 stars: 6-12 uses
- 4 stars: 13-30 uses
- 5 stars: 31+ uses

**Right side (velocity)**: Recent activity that decays over time
- Increases by 1.0 on each citation
- Decays by `VELOCITY_DECAY_FACTOR` (0.5) - 50% half-life per cycle
- Values below `VELOCITY_EPSILON` (0.01) round to zero

#### Token Tracking

Each lesson estimates its token count:

```python
tokens = len(title + content) // 4  # Rough estimate
```

During injection, total tokens are summed and warnings shown:

| Level | Tokens | Action |
|-------|--------|--------|
| Light | <1000 | Normal injection |
| Medium | 1000-2000 | Show token count |
| Heavy | >2000 | Warning + suggestions |

### Go Performance Layer (go/)

High-performance citation processing for the hot path:
- `go/cmd/recall-hook/` - CLI for stop hook
- `go/internal/stores/` - Lesson/handoff stores
- `go/internal/transcript/` - Transcript parsing

The Go binary handles citation extraction and processing in ~100ms vs ~2-3s for Python.

**When Go is used:**
- Citation extraction from transcripts
- Store reads/writes for lessons and handoffs
- Quick validation and parsing

**When Python is used:**
- Decay calculations and promotion logic
- Complex commands (relevance scoring, etc.)
- Fallback when Go binary unavailable

### Debug TUI (core/tui/)

Real-time monitoring with `claude-recall watch`:
- Log viewer with filtering
- Session tracking
- Stats aggregation

### Alerting System (core/alerts.py)

System health monitoring:
- Stale handoff detection
- Latency spike alerts
- Error rate monitoring

### File Locking

The `FileLock` class provides safe concurrent access:

```python
class FileLock:
    def __init__(self, path: str):
        self.path = path
        self.lock_file = None

    def __enter__(self):
        self.lock_file = open(f"{self.path}.lock", 'w')
        fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.lock_file:
            fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_UN)
            self.lock_file.close()
            # Note: Lock file NOT deleted to avoid race conditions
        return False
```

Usage:
```python
with FileLock(lessons_file):
    lessons = parse_lessons(lessons_file)
    lessons.append(new_lesson)
    write_lessons(lessons_file, lessons)
```

### Decay System

Lessons can become stale. The decay system addresses this:

**How it works:**
- Runs automatically once per week (triggered by inject-hook)
- Only decays if coding sessions occurred since last decay
- Vacation mode: If no sessions, lessons are preserved
- Reduces velocity by `VELOCITY_DECAY_FACTOR` (0.7)
- Lessons not cited in 30+ days lose 1 use (min 1)

**Files:**
- `.decay-last-run`: Unix timestamp of last decay
- Checkpoint file modification times indicate session activity

### Handoffs System

Handoffs track multi-step work with rich metadata:

**Phases:**
| Phase | Description |
|-------|-------------|
| `research` | Reading, searching, understanding codebase |
| `planning` | Creating plan, designing solution |
| `implementing` | Writing code |
| `review` | Checking work, running tests |

**Agents:**
| Agent | Description |
|-------|-------------|
| `explore` | Codebase exploration |
| `general-purpose` | Implementation work |
| `plan` | Design/planning |
| `review` | Code review |
| `user` | Direct user work (default) |

**Visibility Rules:**
```python
HANDOFF_MAX_COMPLETED = 3   # Keep last N completed
HANDOFF_MAX_AGE_DAYS = 7    # Or within N days
```

Completed handoffs remain visible if they match EITHER criterion.

## Adapters

### Claude Code Adapter

Two shell scripts hook into Claude Code's event system:

**inject-hook.sh** (SessionStart):
- Calls `lessons_manager.py inject` for top lessons
- Calls `lessons_manager.py handoff inject` for active handoffs
- Adds "LESSON DUTY" and "HANDOFF TRACKING" reminders
- Triggers weekly decay check in background

**stop-hook.sh** (Stop):
- Parses assistant output for patterns:
  - `LESSON: category: title - content`
  - `AI LESSON: category: title - content`
  - `HANDOFF: title`
  - `PLAN MODE: title`
  - `HANDOFF UPDATE hf-xxx: field value`
  - `HANDOFF COMPLETE hf-xxx`
  - `[L###]: Applied...` (citations)
- Uses incremental checkpointing
- Cleans orphaned checkpoints opportunistically

**Security measures:**
- Command injection protection: `--` before user input
- ReDoS protection: Lines >1000 chars skipped
- Input sanitization: Length limits, character filtering

### OpenCode Adapter

A TypeScript plugin that hooks into OpenCode events:

**plugin.ts**:
- `session.created`: Injects lessons context
- `session.idle`: Tracks citations
- `message.updated`: Captures `LESSON:` commands

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CLAUDE_RECALL_BASE` | `~/.config/claude-recall` | System lessons location (preferred) |
| `RECALL_BASE` | - | Legacy alias |
| `LESSONS_BASE` | - | Legacy alias |
| `CLAUDE_RECALL_STATE` | `~/.local/state/claude-recall` | Debug logs location |
| `PROJECT_DIR` | Current directory | Project root |
| `CLAUDE_RECALL_DEBUG` | `0` | Debug level (0-3) |

## Markdown Format

### Lessons File (LESSONS.md)

```markdown
# Project Lessons

### [L001] [**---|+----] pattern: Always validate JSON
- **Uses**: 5 | **Velocity**: 1.2 | **Tokens**: 45 | **Learned**: 2025-12-28 | **Last**: 2025-12-29 | **Source**: user
- Parse JSON in try/except block, never assume valid input

### [L002] [*----|-----] gotcha: Race condition in async handlers
- **Uses**: 1 | **Velocity**: 0.0 | **Tokens**: 62 | **Learned**: 2025-12-29 | **Last**: 2025-12-29 | **Source**: ai 🤖
- Use locks or queues when multiple handlers modify shared state
```

### Handoffs File (HANDOFFS.md)

```markdown
# Active Handoffs

### [hf-abc1234] Implementing WebSocket reconnection
- **Status**: in_progress | **Phase**: implementing | **Agent**: general-purpose
- **Created**: 2025-12-28 | **Updated**: 2025-12-29
- **Files**: src/websocket.ts, src/connection-manager.ts
- **Description**: Add automatic reconnection with exponential backoff

**Code**:
```typescript
export async function reconnect(delay: number = 1000): Promise<void> {
  await sleep(delay);
  return connect({ retry: true });
}
```

**Tried**:
1. [fail] Simple setTimeout retry - races with manual disconnect
2. [success] Event-based with AbortController

**Next**: Write integration tests

---

# Completed Handoffs

### [hf-def5678] Initial setup
- **Status**: completed | **Phase**: review | **Agent**: user
- **Created**: 2025-12-27 | **Updated**: 2025-12-27
- ...
```

## Development Workflow

### Making Changes

1. **Edit core logic**: Modify `core/lessons_manager.py`
2. **Edit hooks**: Modify files in `adapters/claude-code/`
3. **Run tests**: `python3 -m pytest tests/ -v`
4. **Install hooks**: `./install.sh`

### Code Style

**Python:**
- Type hints for all function signatures
- Docstrings for public functions
- Use dataclasses for structured data
- `black` for formatting (if available)

**Shell:**
- `set -euo pipefail` for safety
- `local` for all function variables
- Quote all variable expansions: `"$var"`
- Use `[[ ]]` for conditionals
- `--` before user input to prevent option injection

### Testing

```bash
# Run all tests (1900+ tests)
./run-tests.sh

# Run specific test file
python3 -m pytest tests/test_lessons_manager.py -v
python3 -m pytest tests/test_handoffs.py -v
python3 -m pytest tests/test_debug_logger.py -v

# Run specific test
python3 -m pytest tests/test_handoffs.py::TestPhaseDetectionFromTools -v
```

See [docs/TESTING.md](docs/TESTING.md) for detailed testing guide.

## Debugging

### Enable Debug Output

For hooks, temporarily add:
```bash
exec 2>/tmp/lessons-debug.log
set -x
```

### Inspect State

```bash
# View lessons
python3 core/lessons_manager.py list

# View handoffs
python3 core/lessons_manager.py handoff list

# Test injection
python3 core/lessons_manager.py inject 5

# Check decay state
cat ~/.config/claude-recall/.decay-last-run
```

### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| Citations not tracked | Checkpoint too new | Delete session checkpoint |
| Decay not running | No sessions detected | Check checkpoint files |
| Hook not triggering | Not installed | Run `./install.sh` |
| Import error | Missing dependency | `pip install` required packages |

## Contributing

### Adding a New Feature

1. Update dataclass if new fields needed
2. Add parsing/formatting in markdown functions
3. Add CLI command if user-facing
4. Write tests (aim for 90%+ coverage)
5. Update hook patterns if new commands
6. Update documentation

### Adding a New Adapter

1. Create `adapters/<tool-name>/` directory
2. Implement hook scripts or plugins
3. Call Python manager via subprocess
4. Handle patterns from assistant output
5. Add tests
6. Document in DEPLOYMENT.md

## Constants Reference

```python
# Velocity decay
VELOCITY_DECAY_FACTOR = 0.5   # 50% half-life per decay cycle
VELOCITY_EPSILON = 0.01       # Values below round to zero

# Handoff visibility
HANDOFF_MAX_COMPLETED = 3    # Keep last N completed handoffs
HANDOFF_MAX_AGE_DAYS = 7     # Or within N days

# Token thresholds
TOKEN_HEAVY_THRESHOLD = 2000  # Warn when injection exceeds this

# Input limits (security)
MAX_LINE_LENGTH = 1000        # Skip lines longer than this (ReDoS protection)
MAX_TITLE_LENGTH = 200        # Truncate titles
MAX_CONTENT_LENGTH = 1000     # Truncate content
```
