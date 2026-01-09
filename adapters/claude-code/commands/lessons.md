---
description: Manage the Claude Recall lessons system - a learning cache that tracks corrections and patterns across sessions.
argument-hint: [list | search <term> | category <cat> | stale | add <cat> <title> - <content> | edit <id> <field> <value> | delete <id>]
allowed-tools: Bash(~/.config/claude-recall/lessons-manager.sh:*)
---

# Lesson Management

Manage your personal learning system: capture patterns, corrections, gotchas, preferences, and architectural decisions.

**Arguments**: $ARGUMENTS

## Categories

- **pattern** - Reusable approaches that work well
- **correction** - Fixes for repeated mistakes
- **gotcha** - Non-obvious pitfalls to avoid
- **preference** - User's preferred conventions
- **decision** - Architectural choices and their rationale

## Commands

Based on the first argument ($1), execute one of these operations:

| Action | Args | Command |
|--------|------|---------|
| List all | (none) or `list` | `~/.config/claude-recall/lessons-manager.sh list` |
| Search | `search <term>` | `~/.config/claude-recall/lessons-manager.sh list --search "<term>"` |
| Filter | `category <cat>` | `~/.config/claude-recall/lessons-manager.sh list --category <cat>` |
| Stale | `stale` | `~/.config/claude-recall/lessons-manager.sh list --stale` |
| Add | `add <cat> <title> - <content>` | `~/.config/claude-recall/lessons-manager.sh add <cat> "<title>" "<content>"` |
| Edit | `edit <id> <field> <value>` | `~/.config/claude-recall/lessons-manager.sh edit <id> <field> "<value>"` |
| Delete | `delete <id>` | Show lesson first, confirm with user, then `~/.config/claude-recall/lessons-manager.sh delete <id>` |

## Output Format

Format list output as a markdown table with columns: ID, Stars, Category, Title, Content (truncated).

## Examples

- `/lessons` - List all lessons
- `/lessons search git` - Find lessons mentioning "git"
- `/lessons category correction` - Show only corrections
- `/lessons stale` - Show lessons that haven't been used recently
- `/lessons add correction "Stage files explicitly" - "Use git add <file> for specific files"`
- `/lessons edit L001 content "Updated content here"`
- `/lessons delete S003` - Remove system lesson (requires confirmation)
