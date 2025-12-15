# Claude Code Lessons System

A dynamic learning system for [Claude Code](https://github.com/anthropics/claude-code) that tracks patterns, corrections, and gotchas across sessions. Think of it as **persistent memory** that helps Claude learn from your feedback.

## ✨ Features

- **Two-tier architecture**: Project lessons (`[L###]`) and system lessons (`[S###]`)
- **Star rating system**: Lessons gain stars with each use, promoting high-value ones
- **Automatic injection**: Lessons shown at session start
- **Citation tracking**: When Claude applies a lesson, it gains stars
- **Slash command**: Type `/lessons` to view all lessons with star ratings
- **Export/Import**: Sync lessons across machines via SSH or tarball

## 🚀 Quick Install

```bash
curl -fsSL https://raw.githubusercontent.com/prestonbrown/claude-code-lessons/main/install.sh | bash
```

Or clone and run:

```bash
git clone https://github.com/prestonbrown/claude-code-lessons.git
cd claude-code-lessons
./install.sh
```

## 📖 Usage

### Adding Lessons

Type these directly in Claude Code:

```
LESSON: Always use spdlog - Never use printf or cout for logging
LESSON: pattern: XML event_cb - Use XML event_cb not lv_obj_add_event_cb()
SYSTEM LESSON: preference: Git commits - Use simple double-quoted strings
```

Format: `LESSON: [category:] title - content`

**Categories:** `pattern`, `correction`, `decision`, `gotcha`, `preference`

### Viewing Lessons

Type `/lessons` in Claude Code to see all your lessons with star ratings in a formatted table.

### How It Works

1. **SessionStart**: Lessons are injected as context
2. **When Claude applies a lesson**: It cites `[L001]` → star count increases
3. **50+ uses**: Project lesson promotes to system level
4. **Eviction**: Lowest-star lessons removed when cache fills (default: 30)

### Star Rating

```
[+----/----] = 0.5 stars (1 use)
[*----/----] = 1.0 star  (2 uses)
[*****/----] = 5.0 stars (10 uses) - Mature lesson
[*****/****] = 10 stars  (20 uses) - Display cap
50+ uses → PROMOTED TO SYSTEM LEVEL
```

## 🔄 Sync Across Machines

### Export lessons

```bash
~/.claude/install-lessons-system.sh --export
# Creates ~/claude-lessons-export.tar.gz
```

### Import from tarball

```bash
~/.claude/install-lessons-system.sh --import ~/claude-lessons-export.tar.gz
```

### Pull from SSH host

```bash
# System lessons only
~/.claude/install-lessons-system.sh --import-from user@hostname

# Include project lessons from host's current directory
~/.claude/install-lessons-system.sh --import-from user@hostname -p
```

## 📁 File Structure

```
~/.claude/
├── LESSONS.md              # System lessons (apply everywhere)
├── CLAUDE.md               # Instructions (lessons section added)
├── settings.json           # Hooks configuration
├── commands/
│   └── lessons.md          # /lessons slash command
└── hooks/
    ├── lessons-manager.sh      # Core CLI
    ├── lessons-inject-hook.sh  # SessionStart hook
    ├── lessons-capture-hook.sh # UserPromptSubmit hook
    └── lessons-stop-hook.sh    # Stop hook (citation tracking)

<project>/.claude/
└── LESSONS.md              # Project-specific lessons
```

## 🛠 Commands

| Command | Description |
|---------|-------------|
| `install.sh` | Install the lessons system |
| `install.sh --export [file]` | Export lessons to tarball |
| `install.sh --import <file>` | Import lessons from tarball |
| `install.sh --import-from <host>` | Pull lessons via SSH |
| `install.sh --uninstall` | Remove the system (keeps lessons) |

### Manager CLI

```bash
# Listing lessons
~/.claude/hooks/lessons-manager.sh list                      # Show all lessons
~/.claude/hooks/lessons-manager.sh list --project            # Project only
~/.claude/hooks/lessons-manager.sh list --system             # System only
~/.claude/hooks/lessons-manager.sh list --search "spdlog"    # Search by keyword
~/.claude/hooks/lessons-manager.sh list --category gotcha    # Filter by category
~/.claude/hooks/lessons-manager.sh list --stale              # Show stale lessons (60+ days uncited)
~/.claude/hooks/lessons-manager.sh list --verbose            # Full details with staleness

# Modifying lessons
~/.claude/hooks/lessons-manager.sh edit L005 "New content"   # Edit a lesson's content
~/.claude/hooks/lessons-manager.sh delete L003               # Delete a lesson
~/.claude/hooks/lessons-manager.sh cite L001                 # Manually cite

# Other
~/.claude/hooks/lessons-manager.sh evict                     # Run eviction
~/.claude/hooks/lessons-manager.sh help                      # Show all commands
```

### Duplicate Detection

When adding a lesson, the system checks for similar existing lessons by title. If a duplicate is found, you'll be warned:

```
WARNING: Similar lesson already exists: 'Verbose flags required'
Add anyway? Use 'add --force' to skip this check
```

### Staleness Tracking

Lessons that haven't been cited in 60+ days are marked as stale:

```
[L005] [+----/-----] Static buffers for subjects ⚠️ STALE(75d)
```

Use `list --stale` to see only stale lessons for review.

## 🤖 Claude's Behavior

When working with you, Claude will:

1. **CITE** lessons when applying them: *"Applying [L001]: using XML event_cb..."*
2. **PROPOSE** new lessons when:
   - You correct it
   - It discovers non-obvious patterns
   - Something fails and it learns why
3. **NEVER** add lessons without your explicit approval

## 📝 Example Lessons

From a real project (helixscreen):

| ID | Stars | Title |
|----|-------|-------|
| [L010] | ★☆☆☆☆ | No spdlog in destructors |
| [L013] | ★☆☆☆☆ | Callbacks before XML creation |
| [L005] | ★☆☆☆☆ | Static buffers for subjects |
| [L006] | ★☆☆☆☆ | get_color vs parse_color |

## 🔧 Configuration

Edit `~/.claude/settings.json`:

```json
{
  "lessonsSystem": {
    "enabled": true,
    "maxLessons": 30,
    "topLessonsToShow": 5,
    "evictionIntervalHours": 24,
    "promotionThreshold": 50
  }
}
```

## 📜 License

MIT License - see [LICENSE](LICENSE)

## 🙏 Acknowledgments

Built for use with [Claude Code](https://github.com/anthropics/claude-code) by Anthropic.
