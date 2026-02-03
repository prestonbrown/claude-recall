---
description: Manage the Claude Recall lessons system - a learning cache that tracks corrections and patterns across sessions.
argument-hint: [list | search <term> | category <cat> | stale | show <id> | add <cat> <title> - <content> | cite <id> | delete <id>]
allowed-tools: Bash(recall *)
---

# Lesson Management

Manage your personal learning system: capture patterns, corrections, gotchas, preferences, and architectural decisions.

**Arguments**: $ARGUMENTS

## Using the CLI

The `recall` binary is installed at `~/.local/bin/recall`. Commands:

```bash
recall <command> [args...]
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
| List all | (none) or `list` | `recall list` |
| Search | `search <term>` | `recall list --search "<term>"` |
| Filter | `category <cat>` | `recall list --category <cat>` |
| Stale | `stale` | `recall list --stale` |
| Show | `show <id>` | `recall show <id>` |
| Add | `add <cat> <title> - <content>` | `recall add <cat> "<title>" "<content>"` |
| Cite | `cite <id>` | `recall cite <id>` |
| Edit | `edit <id> <content>` | `recall edit <id> --content "<new content>"` |
| Delete | `delete <id>` | Show first, confirm with user, then `recall delete <id>` |

## Full Command Examples

```bash
# List all lessons
recall list

# Search for lessons about git
recall list --search "git"

# Show a specific lesson
recall show L001

# Add a new lesson
recall add correction "Stage files explicitly" "Use git add <file> for specific files"

# Cite a lesson (increments usage count)
recall cite L001

# Edit a lesson
recall edit L001 --content "Updated content here"
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
