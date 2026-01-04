# Claude Recall

[![Version](https://img.shields.io/badge/version-0.9.0-blue.svg)](https://github.com/prestonbrown/claude-recall)

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

### Handoffs System
- **TodoWrite sync**: Use TodoWrite naturally - todos auto-sync to HANDOFFS.md for persistence
- **Work tracking**: Track ongoing tasks with tried steps and next steps
- **Phases**: `research` → `planning` → `implementing` → `review`
- **Session continuity**: Handoffs restore as TodoWrite suggestions on next session
- **Completion workflow**: Extract lessons when finishing work
- **Command patterns**: `HANDOFF:`, `HANDOFF UPDATE`, `HANDOFF COMPLETE`

## Quick Install

```bash
# Clone and install
git clone https://github.com/prestonbrown/claude-recall.git
cd claude-recall
./install.sh

# Or install for specific tools:
./install.sh --claude    # Claude Code only
./install.sh --opencode  # OpenCode only
```

## Migrating from coding-agent-lessons

Run the installer to automatically migrate:
```bash
./install.sh
```

This migrates:
- `~/.config/coding-agent-lessons/` → `~/.config/claude-recall/`
- `.coding-agent-lessons/` → `.claude-recall/`

Environment variables (all work, checked in order):
- `CLAUDE_RECALL_BASE` (preferred)
- `RECALL_BASE` (legacy)
- `LESSONS_BASE` (legacy)

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
HANDOFF: Implement WebSocket reconnection
HANDOFF UPDATE hf-abc1234: tried fail - Simple setTimeout retry races with disconnect
HANDOFF UPDATE hf-abc1234: tried success - Event-based with AbortController
HANDOFF COMPLETE hf-abc1234
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

1. **Session Start**: Top 3 lessons by stars + handoffs injected as context
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
2. **Auto-sync**: stop-hook captures final todo state to HANDOFFS.md
3. **Restore**: Next session, inject-hook formats handoff as TodoWrite continuation

**Via manual commands**:
1. **Create**: `HANDOFF: title` or `PLAN MODE: title`
2. **Track**: Update status, phase, tried steps, next steps
3. **Complete**: `HANDOFF COMPLETE hf-abc1234` triggers lesson extraction prompt
4. **Archive**: Completed handoffs move to archive, recent ones stay visible

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
~/.config/claude-recall/
├── LESSONS.md                  # System lessons (apply everywhere)
├── cli.py                      # Python CLI (primary)
├── lessons-manager.sh          # Bash wrapper (calls Python)
├── .decay-last-run             # Decay timestamp
└── .citation-state/            # Per-session checkpoints

~/.local/state/claude-recall/
└── debug.log                   # Debug logs (XDG state directory)

<project>/.claude-recall/
├── LESSONS.md                  # Project-specific lessons
└── HANDOFFS.md                 # Active work tracking
```

### Core Implementation

```
claude-recall/
├── core/                       # Python implementation
│   ├── cli.py                  # CLI entry point
│   └── ...                     # Manager, models, parsing
├── adapters/claude-code/       # Hook scripts
└── tests/                      # 420+ tests
```

## CLI Reference

```bash
# Check version
python3 core/cli.py --version

# Lessons
python3 core/cli.py add pattern "Title" "Content"
python3 core/cli.py add --system pattern "Title" "Content"  # System lesson
python3 core/cli.py cite L001
python3 core/cli.py list [--project|--system] [--category X]
python3 core/cli.py inject 5                    # Top 5 by stars
python3 core/cli.py score-relevance "query"     # Relevance scoring via Haiku

# Handoffs (work tracking)
python3 core/cli.py handoff add "Title" [--phase X]
python3 core/cli.py handoff update A001 --status in_progress
python3 core/cli.py handoff list
python3 core/cli.py handoff inject              # For context injection
```

## Hook Patterns

The stop-hook recognizes these patterns in assistant output:

```
LESSON: title - content              # Add project lesson
LESSON: category: title - content    # Add with category
[L001]: Applied...                   # Citation (increments uses/velocity)
[S002]: Following...                 # System lesson citation
```

## Configuration

### Environment Variables

```bash
CLAUDE_RECALL_BASE=~/.config/claude-recall    # System lessons location (preferred)
RECALL_BASE=~/.config/claude-recall           # Legacy alias
LESSONS_BASE=~/.config/claude-recall          # Legacy alias
PROJECT_DIR=/path/to/project                  # Project root
CLAUDE_RECALL_DEBUG=0|1|2|3                   # Debug logging level (preferred)
RECALL_DEBUG=0|1|2|3                          # Legacy alias
LESSONS_DEBUG=0|1|2|3                         # Legacy alias
```

### Debug Logging

Enable structured JSON logging:

```bash
export CLAUDE_RECALL_DEBUG=1   # 0=off, 1=info, 2=debug, 3=trace
```

Logs written to `~/.local/state/claude-recall/debug.log` (XDG state directory).

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
3. **TRACK** handoffs for multi-step work
4. **UPDATE** phase and status as work progresses
5. **EXTRACT** lessons when completing handoffs

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
