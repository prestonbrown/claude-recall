# Deployment Guide

Installation, configuration, and management of the coding-agent-lessons system.

## Quick Install

```bash
# Clone repository
git clone https://github.com/prestonbrown/coding-agent-lessons.git
cd coding-agent-lessons

# Run installer
./install.sh

# Or install for specific tools:
./install.sh --claude    # Claude Code only
./install.sh --opencode  # OpenCode only
```

## Manual Installation

### Claude Code

1. **Create directories:**
```bash
mkdir -p ~/.claude/hooks
mkdir -p ~/.config/coding-agent-lessons
```

2. **Copy files:**
```bash
# Copy hook scripts
cp adapters/claude-code/inject-hook.sh ~/.claude/hooks/
cp adapters/claude-code/stop-hook.sh ~/.claude/hooks/
chmod +x ~/.claude/hooks/*.sh

# Copy core manager
cp core/cli.py ~/.config/coding-agent-lessons/
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
  "lessonsSystem": {
    "enabled": true
  }
}
```

### OpenCode

1. **Navigate to plugins directory:**
```bash
cd ~/.opencode/plugins
```

2. **Link or copy adapter:**
```bash
# Symlink (recommended for development)
ln -s /path/to/coding-agent-lessons/adapters/opencode lessons-plugin

# Or copy files
mkdir -p lessons-plugin
cp -r /path/to/coding-agent-lessons/adapters/opencode/* lessons-plugin/
```

3. **Register plugin** (method depends on OpenCode version)

## File Locations

### System Files

| Location | Purpose |
|----------|---------|
| `~/.config/coding-agent-lessons/` | System lessons base directory |
| `~/.config/coding-agent-lessons/LESSONS.md` | System-wide lessons |
| `~/.config/coding-agent-lessons/.decay-last-run` | Decay timestamp |
| `~/.config/coding-agent-lessons/.citation-state/` | Citation checkpoints |

### Claude Code Files

| Location | Purpose |
|----------|---------|
| `~/.claude/hooks/inject-hook.sh` | SessionStart hook |
| `~/.claude/hooks/stop-hook.sh` | Stop hook - citation tracking |
| `~/.claude/hooks/session-end-hook.sh` | Stop hook - handoff context capture |
| `~/.claude/hooks/precompact-hook.sh` | PreCompact hook - handoff context before compaction |
| `~/.claude/settings.json` | Claude Code configuration |

### Project Files

| Location | Purpose |
|----------|---------|
| `$PROJECT/.coding-agent-lessons/` | Project lessons directory |
| `$PROJECT/.coding-agent-lessons/LESSONS.md` | Project-specific lessons |
| `$PROJECT/.coding-agent-lessons/APPROACHES.md` | Active work tracking |

### Repository vs Installed

```
Repository (source)                  Installed (runtime)
━━━━━━━━━━━━━━━━━━━━                ━━━━━━━━━━━━━━━━━━━━
adapters/claude-code/            → ~/.claude/hooks/
  inject-hook.sh                     inject-hook.sh
  stop-hook.sh                       stop-hook.sh
  session-end-hook.sh                session-end-hook.sh
  precompact-hook.sh                 precompact-hook.sh

core/                            → ~/.config/coding-agent-lessons/
  lessons_manager.py                 lessons_manager.py
```

**Note:** Repository files are NOT used at runtime. Always reinstall after updates.

## Updating

### From Repository

```bash
cd /path/to/coding-agent-lessons
git pull
./install.sh
```

### Manual Update

```bash
# Update hooks
cp adapters/claude-code/inject-hook.sh ~/.claude/hooks/
cp adapters/claude-code/stop-hook.sh ~/.claude/hooks/

# Update manager
cp core/lessons_manager.py ~/.config/coding-agent-lessons/
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LESSONS_BASE` | `~/.config/coding-agent-lessons` | System lessons location |
| `PROJECT_DIR` | Current directory | Project root |
| `LESSON_REMIND_EVERY` | `12` | Reminder frequency (prompts) |

### Claude Code Settings

In `~/.claude/settings.json`:

```json
{
  "lessonsSystem": {
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
ls -la ~/.config/coding-agent-lessons/

# Check permissions
file ~/.claude/hooks/*.sh
file ~/.config/coding-agent-lessons/lessons_manager.py
```

### Test Hooks

```bash
# Test inject hook
echo '{"cwd":"/tmp"}' | ~/.claude/hooks/inject-hook.sh

# Test manager directly
python3 ~/.config/coding-agent-lessons/lessons_manager.py list
python3 ~/.config/coding-agent-lessons/lessons_manager.py approach list
```

### Verify in Session

Start a new Claude Code session. You should see:
- "LESSONS ACTIVE: X system (S###), Y project (L###)"
- Top lessons with star ratings
- "LESSON DUTY" reminder
- "APPROACH TRACKING" instructions

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
   ls ~/.config/coding-agent-lessons/LESSONS.md
   ls $PROJECT/.coding-agent-lessons/LESSONS.md
   ```

2. **Test manager directly:**
   ```bash
   PROJECT_DIR=$PWD python3 ~/.config/coding-agent-lessons/lessons_manager.py inject 5
   ```

### Citations Not Tracked

1. **Check checkpoint directory:**
   ```bash
   ls ~/.config/coding-agent-lessons/.citation-state/
   ```

2. **Verify transcript access:**
   Hook needs read access to Claude transcripts.

3. **Check Python available:**
   ```bash
   which python3
   python3 --version
   ```

### Approaches Not Showing

1. **Check approaches file:**
   ```bash
   cat $PROJECT/.coding-agent-lessons/APPROACHES.md
   ```

2. **Test approach injection:**
   ```bash
   PROJECT_DIR=$PWD python3 ~/.config/coding-agent-lessons/lessons_manager.py approach inject
   ```

### Decay Not Running

1. **Check decay state:**
   ```bash
   cat ~/.config/coding-agent-lessons/.decay-last-run
   ```

2. **Force decay manually:**
   ```bash
   PROJECT_DIR=$PWD python3 ~/.config/coding-agent-lessons/lessons_manager.py decay 30
   ```

## Backup and Migration

### Backup Lessons

```bash
# Backup system lessons
cp ~/.config/coding-agent-lessons/LESSONS.md ~/lessons-backup-$(date +%Y%m%d).md

# Backup project lessons and approaches
cp .coding-agent-lessons/LESSONS.md ~/project-lessons-$(date +%Y%m%d).md
cp .coding-agent-lessons/APPROACHES.md ~/approaches-$(date +%Y%m%d).md
```

### Migrate to New Machine

1. **Copy lesson files:**
   ```bash
   scp old-machine:~/.config/coding-agent-lessons/LESSONS.md ~/.config/coding-agent-lessons/
   ```

2. **Install hooks** (see installation above)

3. **Decay state and checkpoints regenerate automatically**

### Export/Import Between Projects

```bash
# Export project lessons
cp $OLD_PROJECT/.coding-agent-lessons/LESSONS.md $NEW_PROJECT/.coding-agent-lessons/

# Merge lessons manually or use edit command to adjust IDs
```

## Disabling

### Temporarily Disable

In `~/.claude/settings.json`:
```json
{
  "lessonsSystem": {
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
rm -rf ~/.config/coding-agent-lessons/

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
chmod 644 ~/.config/coding-agent-lessons/lessons_manager.py
chmod 644 ~/.config/coding-agent-lessons/LESSONS.md
chmod 700 ~/.config/coding-agent-lessons/.citation-state/
```

### Sensitive Data

- Don't store secrets in lessons
- Project lessons are in `.coding-agent-lessons/` (add to `.gitignore` if needed)
- System lessons contain cross-project patterns (review before sharing)
