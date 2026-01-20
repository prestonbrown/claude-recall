# Deployment Guide

Installation, configuration, and management of the Claude Recall system.

## Quick Install

```bash
# Clone repository
git clone https://github.com/prestonbrown/claude-recall.git
cd claude-recall

# Run installer
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

## Manual Installation

### Claude Code

1. **Create directories:**
```bash
mkdir -p ~/.claude/hooks
mkdir -p ~/.config/claude-recall
```

2. **Copy files:**
```bash
# Copy hook scripts
cp adapters/claude-code/inject-hook.sh ~/.claude/hooks/
cp adapters/claude-code/stop-hook.sh ~/.claude/hooks/
chmod +x ~/.claude/hooks/*.sh

# Copy core module
cp -r core/*.py ~/.config/claude-recall/
```

3. **Configure Claude Code:**

Add to `~/.claude/settings.json`:
```json
{
  "hooks": {
    "SessionStart": [
      {
        "type": "command",
        "command": "~/.claude/hooks/inject-hook.sh"
      }
    ],
    "Stop": [
      {
        "type": "command",
        "command": "~/.claude/hooks/stop-hook.sh"
      }
    ]
  },
  "claudeRecall": {
    "enabled": true
  }
}
```

### OpenCode

**Recommended installation:**

```bash
./install.sh --opencode
```

This installs:
- `~/.config/opencode/plugin/lessons.ts` - Plugin file
- `~/.config/opencode/command/lessons.md` - /lessons command
- `~/.config/opencode/command/handoffs.md` - /handoffs command
- `~/.config/opencode/AGENTS.md` - Global instructions

**Configuration:**

Edit `~/.config/opencode/opencode.json`:

```json
{
  "claudeRecall": {
    "enabled": true,
    "topLessonsToShow": 5,
    "relevanceTopN": 5,
    "remindEvery": 12,
    "decayIntervalDays": 7,
    "debugLevel": 1,
    "small_model": "claude-3-5-haiku-latest"
  }
}
```

**Troubleshooting:**

- **Plugin not loading:**
  - Check plugin file exists: `ls ~/.config/opencode/plugin/lessons.ts`
  - Check TypeScript compilation: View OpenCode logs for errors

- **Lessons not injecting:**
  - Verify enabled: Check opencode.json has `claudeRecall.enabled: true`
  - Check debug logs: View `~/.local/state/claude-recall/debug.log`
  - Increase debugLevel to 2 for detailed logging

- **Handoffs not syncing:**
  - Verify active handoff exists: Run `/handoffs list --active`
  - Check TodoWrite sync: Enable debugLevel 2 and look for "todowrite.sync" events

**Manual installation (for development):**

1. **Navigate to config directory:**
```bash
mkdir -p ~/.config/opencode/plugin
mkdir -p ~/.config/opencode/command
```

2. **Copy adapter files:**
```bash
cp adapters/opencode/plugin/lessons.ts ~/.config/opencode/plugin/
cp adapters/opencode/command/lessons.md ~/.config/opencode/command/
cp adapters/opencode/command/handoffs.md ~/.config/opencode/command/
```

## File Locations

### System Files

| Location | Purpose |
|----------|---------|
| `~/.config/claude-recall/` | System lessons base directory |
| `~/.config/claude-recall/LESSONS.md` | System-wide lessons |
| `~/.config/claude-recall/.decay-last-run` | Decay timestamp |
| `~/.config/claude-recall/.citation-state/` | Citation checkpoints |

### Claude Code Files

| Location | Purpose |
|----------|---------|
| `~/.claude/hooks/inject-hook.sh` | SessionStart hook |
| `~/.claude/hooks/stop-hook.sh` | Stop hook - citation tracking |
| `~/.claude/hooks/session-end-hook.sh` | Stop hook - captures handoff context |
| `~/.claude/hooks/precompact-hook.sh` | PreCompact hook - saves handoff context before compaction |
| `~/.claude/commands/lessons.md` | `/lessons` - manage lessons |
| `~/.claude/commands/implement.md` | `/implement` - implementation protocol |
| `~/.claude/commands/delegate.md` | `/delegate` - agent delegation rules |
| `~/.claude/commands/review.md` | `/review` - code review checklist |
| `~/.claude/commands/test-first.md` | `/test-first` - test-first discipline |
| `~/.claude/settings.json` | Claude Code configuration |

### Project Files

| Location | Purpose |
|----------|---------|
| `$PROJECT/.claude-recall/` | Project lessons directory |
| `$PROJECT/.claude-recall/LESSONS.md` | Project-specific lessons |
| `$PROJECT/.claude-recall/HANDOFFS.md` | Active work tracking |

### Repository vs Installed

```
Repository (source)                  Installed (runtime)
━━━━━━━━━━━━━━━━━━━━                ━━━━━━━━━━━━━━━━━━━━
adapters/claude-code/            → ~/.claude/hooks/
  inject-hook.sh                     inject-hook.sh
  stop-hook.sh                       stop-hook.sh
  session-end-hook.sh                session-end-hook.sh
  precompact-hook.sh                 precompact-hook.sh

adapters/claude-code/commands/   → ~/.claude/commands/
  lessons.md                         lessons.md
  implement.md                       implement.md
  delegate.md                        delegate.md
  review.md                          review.md
  test-first.md                      test-first.md

core/                            → ~/.config/claude-recall/
  cli.py, manager.py, etc.           *.py files
```

**Note:** Repository files are NOT used at runtime. Always reinstall after updates.

## Updating

### From Repository

```bash
cd /path/to/claude-recall
git pull
./install.sh
```

### Manual Update

```bash
# Update hooks
cp adapters/claude-code/inject-hook.sh ~/.claude/hooks/
cp adapters/claude-code/stop-hook.sh ~/.claude/hooks/

# Update core module
cp -r core/*.py ~/.config/claude-recall/
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CLAUDE_RECALL_BASE` | `~/.config/claude-recall` | System lessons location (preferred) |
| `RECALL_BASE` | - | Legacy alias for system lessons location |
| `LESSONS_BASE` | - | Legacy alias for system lessons location |
| `PROJECT_DIR` | Current directory | Project root |
| `LESSON_REMIND_EVERY` | `12` | Reminder frequency (prompts) |

### Claude Code Settings

In `~/.claude/settings.json`:

```json
{
  "claudeRecall": {
    "enabled": true
  }
}
```

Set `enabled: false` to temporarily disable the system.

## Verification

### Check Installation

```bash
# Verify files exist
ls -la ~/.claude/hooks/
ls -la ~/.config/claude-recall/

# Check permissions
file ~/.claude/hooks/*.sh
file ~/.config/claude-recall/cli.py
```

### Test Hooks

```bash
# Test inject hook
echo '{"cwd":"/tmp"}' | ~/.claude/hooks/inject-hook.sh

# Test manager directly
python3 ~/.config/claude-recall/cli.py list
python3 ~/.config/claude-recall/cli.py handoff list
```

### Verify in Session

Start a new Claude Code session. You should see:
- "LESSONS ACTIVE: X system (S###), Y project (L###)"
- Top lessons with star ratings
- "LESSON DUTY" reminder
- "HANDOFF TRACKING" instructions

## Troubleshooting

### Hooks Not Running

1. **Check settings.json syntax:**
   ```bash
   jq . ~/.claude/settings.json
   ```
   Invalid JSON prevents hook registration.

2. **Verify permissions:**
   ```bash
   chmod +x ~/.claude/hooks/*.sh
   ```

3. **Check Claude Code version:**
   Hooks require Claude Code with hook support.

### No Lessons Appearing

1. **Check lessons files exist:**
   ```bash
   ls ~/.config/claude-recall/LESSONS.md
   ls $PROJECT/.claude-recall/LESSONS.md
   ```

2. **Test manager directly:**
   ```bash
   PROJECT_DIR=$PWD python3 ~/.config/claude-recall/cli.py inject 5
   ```

### Citations Not Tracked

1. **Check checkpoint directory:**
   ```bash
   ls ~/.config/claude-recall/.citation-state/
   ```

2. **Verify transcript access:**
   Hook needs read access to Claude transcripts.

3. **Check Python available:**
   ```bash
   which python3
   python3 --version
   ```

### Handoffs Not Showing

1. **Check handoffs file:**
   ```bash
   cat $PROJECT/.claude-recall/HANDOFFS.md
   ```

2. **Test handoffs injection:**
   ```bash
   PROJECT_DIR=$PWD python3 ~/.config/claude-recall/cli.py handoff inject
   ```

### Decay Not Running

1. **Check decay state:**
   ```bash
   cat ~/.config/claude-recall/.decay-last-run
   ```

2. **Force decay manually:**
   ```bash
   PROJECT_DIR=$PWD python3 ~/.config/claude-recall/cli.py decay 30
   ```

## Backup and Migration

### Backup Lessons

```bash
# Backup system lessons
cp ~/.config/claude-recall/LESSONS.md ~/lessons-backup-$(date +%Y%m%d).md

# Backup project lessons and handoffs
cp .claude-recall/LESSONS.md ~/project-lessons-$(date +%Y%m%d).md
cp .claude-recall/HANDOFFS.md ~/handoffs-$(date +%Y%m%d).md
```

### Migrate to New Machine

1. **Copy lesson files:**
   ```bash
   scp old-machine:~/.config/claude-recall/LESSONS.md ~/.config/claude-recall/
   ```

2. **Install hooks** (see installation above)

3. **Decay state and checkpoints regenerate automatically**

### Export/Import Between Projects

```bash
# Export project lessons
cp $OLD_PROJECT/.claude-recall/LESSONS.md $NEW_PROJECT/.claude-recall/

# Merge lessons manually or use edit command to adjust IDs
```

## Disabling

### Temporarily Disable

In `~/.claude/settings.json`:
```json
{
  "claudeRecall": {
    "enabled": false
  }
}
```

Both hooks check this setting and exit early.

### Completely Uninstall

```bash
# Remove hooks
rm ~/.claude/hooks/inject-hook.sh
rm ~/.claude/hooks/stop-hook.sh

# Remove system files
rm -rf ~/.config/claude-recall/

# Remove from settings.json (manually edit)
```

## Version Compatibility

| Component | Requirement |
|-----------|-------------|
| Python | 3.8+ |
| Bash | 4.0+ |
| jq | 1.5+ (for hooks) |
| Claude Code | Hook support required |
| macOS | 10.15+ |
| Linux | Any recent distribution |

## Security Considerations

### Hook Security

- Hooks run with your user permissions
- Input is sanitized before passing to Python
- Command injection protection: `--` before user input
- ReDoS protection: Long lines skipped

### File Permissions

```bash
# Recommended permissions
chmod 755 ~/.claude/hooks/*.sh
chmod 644 ~/.config/claude-recall/cli.py
chmod 644 ~/.config/claude-recall/LESSONS.md
chmod 700 ~/.config/claude-recall/.citation-state/
```

### Sensitive Data

- Don't store secrets in lessons
- Project lessons are in `.claude-recall/` (add to `.gitignore` if needed)
- System lessons contain cross-project patterns (review before sharing)
