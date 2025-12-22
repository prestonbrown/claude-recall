# Coding Agent Lessons

A dynamic learning system for AI coding agents that tracks patterns, corrections, and gotchas across sessions. Works with **Claude Code**, **OpenCode**, and other AI coding tools.

Think of it as **persistent memory** that helps your coding agent learn from your feedback.

## Features

- **Tool-agnostic**: Works with Claude Code, OpenCode, and extensible to other tools
- **Two-tier architecture**: Project lessons (`[L###]`) and system lessons (`[S###]`)
- **Star rating system**: Lessons gain stars with each use, promoting high-value ones
- **Automatic injection**: Lessons shown at session start
- **Citation tracking**: When the agent applies a lesson, it gains stars
- **Slash command**: Type `/lessons` to view all lessons
- **Migration support**: Easily migrate from old Claude Code-specific locations

## Quick Install

```bash
# Auto-detect installed tools and install for all
./install.sh

# Or install for specific tools:
./install.sh --claude    # Claude Code only
./install.sh --opencode  # OpenCode only
```

### Install from GitHub

```bash
git clone https://github.com/prestonbrown/coding-agent-lessons.git
cd coding-agent-lessons
./install.sh
```

## Usage

### Adding Lessons

Type these directly in your coding agent session:

```
LESSON: Always use spdlog - Never use printf or cout for logging
LESSON: pattern: XML event_cb - Use XML event_cb not lv_obj_add_event_cb()
SYSTEM LESSON: preference: Git commits - Use simple double-quoted strings
```

Format: `LESSON: [category:] title - content`

**Categories:** `pattern`, `correction`, `decision`, `gotcha`, `preference`

### Viewing & Managing Lessons

Use the `/lessons` slash command:

```
/lessons                        # List all lessons
/lessons search <term>          # Search by keyword
/lessons category gotcha        # Filter by category
/lessons stale                  # Show lessons uncited 60+ days
/lessons edit L005 "New text"   # Edit a lesson's content
/lessons delete L003            # Delete a lesson
```

### How It Works

1. **Session Start**: Lessons are injected as context, reminder counter resets
2. **Periodic Reminders**: Every 12 prompts, high-star lessons appear as `📚 LESSON CHECK`
3. **When the agent applies a lesson**: It cites `[L001]` → star count increases
4. **50+ uses**: Project lesson promotes to system level
5. **Eviction**: Lowest-star lessons removed when cache fills (default: 30)

### Periodic Reminders

High-star lessons (3+ stars) are shown every 12 prompts to keep them top of mind:

```
📚 LESSON CHECK - High-priority lessons to keep in mind:
### [L014] [*****/+----] Register all XML components
### [L010] [*****/+----] No spdlog in destructors
### [L001] [****-/-----] Conventional commits format
```

Configure reminder frequency with environment variable:
```bash
export LESSON_REMIND_EVERY=12  # Default: every 12 prompts
```

Reset the reminder counter manually:
```bash
~/.config/coding-agent-lessons/lessons-manager.sh reset-reminder
```

### Star Rating

```
[+----/-----] = 1 use (new lesson)
[*----/-----] = 2 uses
[***--/-----] = 6 uses
[*****/-----] = 10 uses - Mature lesson
[*****/****+] = 19 uses
50+ uses → PROMOTED TO SYSTEM LEVEL
```

## File Locations

**Tool-agnostic locations** (new):

```
~/.config/coding-agent-lessons/
├── lessons-manager.sh          # Core CLI
├── lesson-reminder-hook.sh     # Periodic reminder script (for Claude Code)
├── LESSONS.md                  # System lessons (apply everywhere)
├── .reminder-state             # Prompt counter (auto-managed)
└── plugins/
    └── opencode-lesson-reminder.ts  # OpenCode plugin

<project>/.coding-agent-lessons/
└── LESSONS.md              # Project-specific lessons
```

**Claude Code adapter**:

```
~/.claude/
├── settings.json           # Hooks configuration
├── CLAUDE.md               # Instructions (lessons section added)
├── commands/
│   └── lessons.md          # /lessons slash command
└── hooks/
    ├── inject-hook.sh      # SessionStart hook
    ├── capture-hook.sh     # UserPromptSubmit hook
    └── stop-hook.sh        # Stop hook (citation tracking)
```

**OpenCode adapter**:

```
~/.config/opencode/
├── AGENTS.md               # Instructions (lessons section added)
├── command/
│   └── lessons.md          # /lessons slash command
└── plugin/
    └── lessons.ts          # OpenCode plugin
```

## Migration from Old Locations

If you were using the old Claude Code-specific locations:

```bash
./install.sh --migrate
```

This migrates:
- `~/.claude/LESSONS.md` → `~/.config/coding-agent-lessons/LESSONS.md`
- `.claude/LESSONS.md` → `.coding-agent-lessons/LESSONS.md`

Old files are backed up with `.migrated.YYYYMMDD` suffix.

## CLI Reference

```bash
# Manager commands (run directly or via /lessons)
~/.config/coding-agent-lessons/lessons-manager.sh list              # Show all
~/.config/coding-agent-lessons/lessons-manager.sh list --project    # Project only
~/.config/coding-agent-lessons/lessons-manager.sh list --system     # System only
~/.config/coding-agent-lessons/lessons-manager.sh list --search "term"
~/.config/coding-agent-lessons/lessons-manager.sh list --category gotcha
~/.config/coding-agent-lessons/lessons-manager.sh list --stale      # 60+ days uncited
~/.config/coding-agent-lessons/lessons-manager.sh list --verbose

# Modify lessons
~/.config/coding-agent-lessons/lessons-manager.sh add pattern "Title" "Content"
~/.config/coding-agent-lessons/lessons-manager.sh add-system gotcha "Title" "Content"
~/.config/coding-agent-lessons/lessons-manager.sh cite L001
~/.config/coding-agent-lessons/lessons-manager.sh edit L005 "New content"
~/.config/coding-agent-lessons/lessons-manager.sh delete L003

# Session injection (used by hooks)
~/.config/coding-agent-lessons/lessons-manager.sh inject 5
```

## Installer Commands

```bash
./install.sh                  # Auto-detect and install
./install.sh --claude         # Install Claude Code adapter only
./install.sh --opencode       # Install OpenCode adapter only
./install.sh --migrate        # Migrate from old locations
./install.sh --uninstall      # Remove adapters (keeps lessons)
./install.sh --help           # Show help
```

## Agent Behavior

When working with you, the agent will:

1. **CITE** lessons when applying them: *"Applying [L001]: using XML event_cb..."*
2. **PROPOSE** new lessons when:
   - You correct it
   - It discovers non-obvious patterns
   - Something fails and it learns why
3. **NEVER** add lessons without your explicit approval

## Example Lessons

| ID | Stars | Title |
|----|-------|-------|
| [L010] | [*----/-----] | No spdlog in destructors |
| [L013] | [**---/-----] | Callbacks before XML creation |
| [S001] | [***--/-----] | Git commit message format |

## Testing

Run the test suite:

```bash
./tests/run-all-tests.sh
```

## Adding Support for New Tools

1. Create an adapter in `adapters/<tool-name>/`
2. Implement hooks/plugins that call `lessons-manager.sh`
3. Add detection and installation logic to `install.sh`

The core `lessons-manager.sh` handles all lesson operations - adapters just need to:
- Call `inject` at session start
- Capture `LESSON:` commands from user input
- Call `cite` when the agent references lessons

## License

MIT License - see [LICENSE](LICENSE)

## Acknowledgments

Built for use with:
- [Claude Code](https://github.com/anthropics/claude-code) by Anthropic
- [OpenCode](https://opencode.ai) by SST
