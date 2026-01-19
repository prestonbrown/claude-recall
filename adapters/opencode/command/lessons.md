---
description: Manage the Claude Recall lessons system - a learning cache that tracks corrections and patterns across sessions.
argument-hint: [list | search <term> | category <cat> | stale | show <id> | add <cat> <title> - <content> | cite <id> | delete <id>]
allowed-tools: Bash(python3:*)
---

# Lesson Management

Manage your personal learning system: capture patterns, corrections, gotchas, preferences, and architectural decisions.

**Arguments**: $ARGUMENTS

## Finding the CLI

The CLI location varies by installation. Use this pattern to find and run it:

```bash
RECALL_CLI=$(ls ~/.claude/plugins/cache/claude-recall/claude-recall/*/core/cli.py 2>/dev/null | head -1)
python3 "$RECALL_CLI" <command> [args...]
```

Or as a one-liner for each command:

```bash
python3 "$(ls ~/.claude/plugins/cache/claude-recall/claude-recall/*/core/cli.py 2>/dev/null | head -1)" <command>
```

## Categories

- **pattern** - Reusable approaches that work well
- **correction** - Fixes for repeated mistakes
- **gotcha** - Non-obvious pitfalls to avoid
- **preference** - User's preferred conventions
- **decision** - Architectural choices and their rationale

## Commands

Based on the first argument, execute the corresponding operation:

| Action | Args | CLI Command |
|--------|------|-------------|
| List all | (none) or `list` | `list` |
| Search | `search <term>` | `search "<term>"` |
| Filter | `category <cat>` | `list --category <cat>` |
| Stale | `stale` | `list --stale` |
| Show | `show <id>` | `show <id>` |
| Add | `add <cat> <title> - <content>` | `add <cat> "<title>" "<content>"` |
| Cite | `cite <id>` | `cite <id>` |
| Edit | `edit <id> <content>` | `edit <id> "<new content>"` |
| Delete | `delete <id>` | Show first, confirm with user, then `delete <id>` |

## Full Command Examples

```bash
# Find CLI (set once per session)
RECALL_CLI=$(ls ~/.claude/plugins/cache/claude-recall/claude-recall/*/core/cli.py 2>/dev/null | head -1)

# List all lessons
python3 "$RECALL_CLI" list

# Search for lessons about git
python3 "$RECALL_CLI" search "git"

# Show a specific lesson
python3 "$RECALL_CLI" show L001

# Add a new lesson
python3 "$RECALL_CLI" add correction "Stage files explicitly" "Use git add <file> for specific files"

# Cite a lesson (increments usage count)
python3 "$RECALL_CLI" cite L001

# Edit a lesson
python3 "$RECALL_CLI" edit L001 "Updated content here"
```

## Output Format

Format list output as a markdown table with columns: ID, Stars, Category, Title, Content (truncated).

## Quick Reference

- `/lessons` - List all lessons
- `/lessons search git` - Find lessons mentioning "git"
- `/lessons category correction` - Show only corrections
- `/lessons stale` - Show lessons that haven't been used recently
- `/lessons show L001` - Show full lesson details
- `/lessons add correction "Stage files explicitly" - "Use git add <file> for specific files"`
- `/lessons cite L001` - Mark a lesson as used
- `/lessons edit L001 "Updated content"` - Edit lesson content
- `/lessons delete S003` - Remove lesson (requires confirmation)
