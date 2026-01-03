# Coding Agent Lessons (Recall)

A dynamic learning and work tracking system for AI coding agents. Tracks patterns, corrections, and gotchas across sessions while helping manage ongoing work with handoffs tracking.

Works with **Claude Code**, **OpenCode**, and other AI coding tools.

## Features

### Lessons System
- **Two-tier architecture**: Project lessons (`[L###]`) and system lessons (`[S###]`)
- **Smart injection**: First prompt triggers Haiku-based relevance scoring for context-aware lessons
- **Dual-dimension rating**: `[uses|velocity]` shows both total usage and recent activity
- **Automatic promotion**: 50+ uses promotes project lessons to system level
- **Velocity decay**: Lessons lose momentum when not used, stay relevant
- **AI-generated lessons**: Agent can propose lessons (marked with robot emoji)
- **Token tracking**: Warns when context injection is heavy (>2000 tokens)

### Handoffs System (formerly "Approaches")
- **TodoWrite sync**: Use TodoWrite naturally - todos auto-sync to HANDOFFS.md for persistence
- **Work tracking**: Track ongoing tasks with tried steps and next steps
- **Phases**: `research` → `planning` → `implementing` → `review`
- **Session continuity**: Handoffs restore as TodoWrite suggestions on next session
- **Completion workflow**: Extract lessons when finishing work
- **Command patterns**: Uses `APPROACH:`, `APPROACH UPDATE`, `APPROACH COMPLETE` for backward compatibility

## Quick Install

```bash
# Clone and install
git clone https://github.com/prestonbrown/coding-agent-lessons.git
cd coding-agent-lessons
./install.sh

# Or install for specific tools:
./install.sh --claude    # Claude Code only
./install.sh --opencode  # OpenCode only
```

## Usage

### Adding Lessons

Type directly in your coding agent session:

```
LESSON: Always use spdlog - Never use printf or cout for logging
LESSON: pattern: XML event_cb - Use XML event_cb not lv_obj_add_event_cb()
SYSTEM LESSON: preference: Git commits - Use simple double-quoted strings
```

Format: `LESSON: [category:] title - content`

**Categories:** `pattern`, `correction`, `decision`, `gotcha`, `preference`

### Tracking Handoffs

For multi-step work, **just use TodoWrite** - it auto-syncs to HANDOFFS.md:

```
[Agent uses TodoWrite naturally]
→ stop-hook captures todos to HANDOFFS.md
→ Next session: inject-hook restores as continuation prompt
```

Your todos map to handoff fields:
- `completed` todos → `tried` entries (success)
- `in_progress` todo → checkpoint (current focus)
- `pending` todos → next steps

**Manual handoff commands** (for explicit control):

```
APPROACH: Implement WebSocket reconnection
APPROACH UPDATE A001: tried fail - Simple setTimeout retry races with disconnect
APPROACH UPDATE A001: tried success - Event-based with AbortController
APPROACH COMPLETE A001
```

### Plan Mode Integration

When entering plan mode, create a tracked handoff:

```
PLAN MODE: Implement user authentication
```

This creates a handoff with `phase=research` and `agent=plan`.

### Viewing & Managing

Use the `/lessons` slash command:

```
/lessons                        # List all lessons
/lessons search <term>          # Search by keyword
/lessons category gotcha        # Filter by category
/lessons stale                  # Show lessons uncited 60+ days
/lessons edit L005 "New text"   # Edit a lesson's content
/lessons delete L003            # Delete a lesson
```

## How It Works

### Lessons Lifecycle

1. **Session Start**: Top 3 lessons by stars + approaches injected as context
2. **First Prompt**: Smart injection scores all lessons against query via Haiku, injects most relevant
3. **Citation**: Agent cites `[L001]` when applying → uses/velocity increase
4. **Decay**: Weekly decay reduces velocity; stale lessons lose uses
5. **Promotion**: 50+ uses → project lesson promotes to system level

### Rating System

```
[*----|-----]  1 use, no velocity (new)
[**---|+----]  3 uses, some recent activity
[****-|**---]  15 uses, moderate velocity
[*****|*****]  31+ uses, high velocity (very active)
```

Left side: Total uses (logarithmic scale)
Right side: Recent velocity (decays over time)

### Handoffs Lifecycle

**Via TodoWrite (recommended)**:
1. **Use TodoWrite**: Agent uses TodoWrite naturally with reminders
2. **Auto-sync**: stop-hook captures final todo state to APPROACHES.md
3. **Restore**: Next session, inject-hook formats approach as TodoWrite continuation

**Via manual commands**:
1. **Create**: `APPROACH: title` or `PLAN MODE: title`
2. **Track**: Update status, phase, tried approaches, next steps
3. **Complete**: `APPROACH COMPLETE A001` triggers lesson extraction prompt
4. **Archive**: Completed approaches move to archive, recent ones stay visible

### Phase Detection

The system can infer phases from tool usage:

| Tools Used | Inferred Phase |
|------------|----------------|
| Read, Grep, Glob | research |
| Write to .md, AskUserQuestion | planning |
| Edit, Write to code files | implementing |
| Bash (test/build commands) | review |

## File Locations

```
~/.config/coding-agent-lessons/
├── LESSONS.md                  # System lessons (apply everywhere)
├── lessons-manager.sh          # Bash CLI (legacy)
├── .decay-last-run             # Decay timestamp
└── .citation-state/            # Per-session checkpoints

<project>/.coding-agent-lessons/
├── LESSONS.md                  # Project-specific lessons
└── APPROACHES.md               # Active work tracking
```

### Core Implementation

```
coding-agent-lessons/
├── core/
│   ├── cli.py                  # Python CLI entry point (primary)
│   ├── debug_logger.py         # JSON debug logging
│   └── lessons-manager.sh      # Bash wrapper (calls Python)
├── adapters/
│   ├── claude-code/
│   │   ├── inject-hook.sh      # SessionStart - injects top lessons + approaches
│   │   ├── smart-inject-hook.sh # UserPromptSubmit - relevance-scored lessons
│   │   ├── stop-hook.sh        # Stop - tracks citations/patterns
│   │   ├── session-end-hook.sh # Stop - captures handoff context on session end
│   │   └── precompact-hook.sh  # PreCompact - captures handoff context before compaction
│   └── opencode/
│       └── ...
└── tests/
    ├── test_lessons_manager.py # 400+ lesson & handoff tests
    ├── test_handoffs.py        # Handoff tests
    └── test_debug_logger.py    # Debug logger tests
```

## CLI Reference

### Python Manager (Primary)

```bash
# Set environment
export PROJECT_DIR=/path/to/project
export LESSONS_BASE=~/.config/coding-agent-lessons

# Lessons
python3 core/lessons_manager.py add pattern "Title" "Content"
python3 core/lessons_manager.py add-system gotcha "Title" "Content"
python3 core/lessons_manager.py add-ai pattern "Title" "Content"  # AI-generated
python3 core/lessons_manager.py cite L001
python3 core/lessons_manager.py edit L005 "New content"
python3 core/lessons_manager.py delete L003
python3 core/lessons_manager.py list [--scope project|system] [--category X]
python3 core/lessons_manager.py search "keyword"
python3 core/lessons_manager.py inject 5  # Top 5 by stars for context
python3 core/lessons_manager.py score-relevance "query" --top 5  # Top 5 by relevance
python3 core/lessons_manager.py decay 30  # Decay lessons unused 30+ days

# Approaches
python3 core/lessons_manager.py approach add "Title" [--phase X] [--agent Y]
python3 core/lessons_manager.py approach update A001 --status in_progress
python3 core/lessons_manager.py approach update A001 --phase implementing
python3 core/lessons_manager.py approach update A001 --tried fail "Description"
python3 core/lessons_manager.py approach update A001 --next "Next steps"
python3 core/lessons_manager.py approach complete A001
python3 core/lessons_manager.py approach archive A001
python3 core/lessons_manager.py approach list [--status X]
python3 core/lessons_manager.py approach inject  # For context
python3 core/lessons_manager.py approach sync-todos '<json>'  # Sync TodoWrite to approach
python3 core/lessons_manager.py approach inject-todos  # Format for TodoWrite continuation
```

## Hook Patterns

The stop-hook recognizes these patterns in assistant output:

### Lesson Patterns
```
LESSON: title - content                    # Add project lesson
LESSON: category: title - content          # Add with category
AI LESSON: category: title - content       # AI-proposed lesson
```

### Approach Patterns
```
APPROACH: <title>                              # Start tracking
PLAN MODE: <title>                             # Start with phase=research, agent=plan
APPROACH UPDATE A###: status <status>          # in_progress|blocked|completed
APPROACH UPDATE A###: phase <phase>            # research|planning|implementing|review
APPROACH UPDATE A###: agent <agent>            # explore|general-purpose|plan|review|user
APPROACH UPDATE A###: tried <outcome> - <desc> # success|fail|partial
APPROACH UPDATE A###: next <text>              # Set next steps
APPROACH COMPLETE A###                         # Mark complete
```

### Citation Pattern
```
[L001]: Applied the lesson...              # Increments uses and velocity
[S002]: Following system lesson...         # Works for system lessons too
```

## Configuration

### Environment Variables

```bash
LESSONS_BASE=~/.config/coding-agent-lessons  # System lessons location
PROJECT_DIR=/path/to/project                  # Project root
LESSONS_DEBUG=0|1|2|3                         # Debug logging level (see below)
```

### Debug Logging

Enable structured JSON logging to analyze system behavior:

```bash
# Enable info-level logging
export LESSONS_DEBUG=1

# Levels:
#   0 = disabled (default)
#   1 = info: session start, citations, lesson adds, decay, approach lifecycle
#   2 = debug: includes injection details, token calculations
#   3 = trace: includes file I/O timing, lock waits
```

Logs are written to `~/.config/coding-agent-lessons/debug.log` in JSON lines format:

```bash
# View in real-time
tail -f ~/.config/coding-agent-lessons/debug.log | jq .

# Filter by event type
cat debug.log | jq 'select(.event == "citation")'

# Analyze citation patterns
cat debug.log | jq -r 'select(.event == "citation") | .lesson_id' | sort | uniq -c
```

Log files rotate automatically at 50MB (keeps 3 files).

### Claude Code Settings

In `~/.claude/settings.json`:
```json
{
  "lessonsSystem": {
    "enabled": true,
    "remindEvery": 12
  },
  "hooks": {
    "SessionStart": [{"hooks": [{"type": "command", "command": "bash ~/.claude/hooks/inject-hook.sh"}]}],
    "UserPromptSubmit": [{"hooks": [
      {"type": "command", "command": "bash ~/.claude/hooks/capture-hook.sh"},
      {"type": "command", "command": "bash ~/.claude/hooks/smart-inject-hook.sh", "timeout": 15000}
    ]}],
    "Stop": [{"hooks": [{"type": "command", "command": "bash ~/.claude/hooks/stop-hook.sh"}]}]
  }
}
```

- `lessonsSystem.enabled`: Enable/disable the lessons system
- `lessonsSystem.remindEvery`: Show high-priority lesson reminders every N prompts (default: 12)

## Agent Behavior

When working with you, the agent will:

1. **CITE** lessons when applying: *"Applying [L001]: using XML event_cb..."*
2. **PROPOSE** lessons when corrected or discovering patterns
3. **TRACK** approaches for multi-step work
4. **UPDATE** phase and status as work progresses
5. **EXTRACT** lessons when completing approaches

## Testing

```bash
# Run all tests (280 tests)
python3 -m pytest tests/ -v

# Run specific test files
python3 -m pytest tests/test_lessons_manager.py -v  # Lesson tests
python3 -m pytest tests/test_handoffs.py -v         # Handoff tests
python3 -m pytest tests/test_debug_logger.py -v     # Debug logger tests
```

See [docs/TESTING.md](docs/TESTING.md) for detailed testing guide.

## Documentation

- [DEVELOPMENT.md](DEVELOPMENT.md) - Architecture and contributing
- [docs/TESTING.md](docs/TESTING.md) - Test framework
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) - Installation and hooks

## License

MIT License - see [LICENSE](LICENSE)
