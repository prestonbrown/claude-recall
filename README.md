# Coding Agent Lessons

A dynamic learning and work tracking system for AI coding agents. Tracks patterns, corrections, and gotchas across sessions while helping manage ongoing work with approaches tracking.

Works with **Claude Code**, **OpenCode**, and other AI coding tools.

## Features

### Lessons System
- **Two-tier architecture**: Project lessons (`[L###]`) and system lessons (`[S###]`)
- **Dual-dimension rating**: `[uses|velocity]` shows both total usage and recent activity
- **Automatic promotion**: 50+ uses promotes project lessons to system level
- **Velocity decay**: Lessons lose momentum when not used, stay relevant
- **AI-generated lessons**: Agent can propose lessons (marked with robot emoji)
- **Token tracking**: Warns when context injection is heavy (>2000 tokens)

### Approaches System
- **Work tracking**: Track ongoing tasks with tried approaches and next steps
- **Phases**: `research` → `planning` → `implementing` → `review`
- **Agent tracking**: Know which agent type worked on what
- **Code snippets**: Attach relevant code to approaches
- **Completion workflow**: Extract lessons when finishing work

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

### Tracking Approaches

For multi-step work, use approaches:

```
APPROACH: Implement WebSocket reconnection
APPROACH UPDATE A001: status in_progress
APPROACH UPDATE A001: phase implementing
APPROACH UPDATE A001: tried fail - Simple setTimeout retry races with disconnect
APPROACH UPDATE A001: tried success - Event-based with AbortController
APPROACH UPDATE A001: next Write integration tests
APPROACH COMPLETE A001
```

### Plan Mode Integration

When entering plan mode, create a tracked approach:

```
PLAN MODE: Implement user authentication
```

This creates an approach with `phase=research` and `agent=plan`.

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

1. **Session Start**: Top lessons injected as context with token count
2. **Citation**: Agent cites `[L001]` when applying → uses/velocity increase
3. **Decay**: Weekly decay reduces velocity; stale lessons lose uses
4. **Promotion**: 50+ uses → project lesson promotes to system level

### Rating System

```
[*----|-----]  1 use, no velocity (new)
[**---|+----]  3 uses, some recent activity
[****-|**---]  15 uses, moderate velocity
[*****|*****]  31+ uses, high velocity (very active)
```

Left side: Total uses (logarithmic scale)
Right side: Recent velocity (decays over time)

### Approaches Lifecycle

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
│   └── lessons_manager.py      # Python implementation (primary)
├── adapters/
│   ├── claude-code/
│   │   ├── inject-hook.sh      # SessionStart - injects context
│   │   └── stop-hook.sh        # Stop - tracks citations/patterns
│   └── opencode/
│       └── ...
└── tests/
    ├── test_lessons_manager.py # 62 lesson tests
    └── test_approaches.py      # 139 approach tests
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
python3 core/lessons_manager.py inject 5  # Top 5 for context
python3 core/lessons_manager.py decay 30  # Decay lessons unused 30+ days

# Approaches
python3 core/lessons_manager.py approach add "Title" [--phase X] [--agent Y]
python3 core/lessons_manager.py approach update A001 --status in_progress
python3 core/lessons_manager.py approach update A001 --phase implementing
python3 core/lessons_manager.py approach update A001 --tried fail "Description"
python3 core/lessons_manager.py approach update A001 --next "Next steps"
python3 core/lessons_manager.py approach update A001 --code "snippet"
python3 core/lessons_manager.py approach complete A001
python3 core/lessons_manager.py approach archive A001
python3 core/lessons_manager.py approach list [--status X]
python3 core/lessons_manager.py approach inject  # For context
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
LESSON_REMIND_EVERY=12                        # Reminder frequency (prompts)
```

### Claude Code Settings

In `~/.claude/settings.json`:
```json
{
  "hooks": {
    "SessionStart": [{"command": "path/to/inject-hook.sh"}],
    "Stop": [{"command": "path/to/stop-hook.sh"}]
  },
  "lessonsSystem": {
    "enabled": true
  }
}
```

## Agent Behavior

When working with you, the agent will:

1. **CITE** lessons when applying: *"Applying [L001]: using XML event_cb..."*
2. **PROPOSE** lessons when corrected or discovering patterns
3. **TRACK** approaches for multi-step work
4. **UPDATE** phase and status as work progresses
5. **EXTRACT** lessons when completing approaches

## Testing

```bash
# Run all tests (201 tests)
python3 -m pytest tests/ -v

# Run specific test files
python3 -m pytest tests/test_lessons_manager.py -v  # 62 tests
python3 -m pytest tests/test_approaches.py -v       # 139 tests
```

See [docs/TESTING.md](docs/TESTING.md) for detailed testing guide.

## Documentation

- [DEVELOPMENT.md](DEVELOPMENT.md) - Architecture and contributing
- [docs/TESTING.md](docs/TESTING.md) - Test framework
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) - Installation and hooks

## License

MIT License - see [LICENSE](LICENSE)
