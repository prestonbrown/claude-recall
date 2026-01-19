---
description: Manage active handoffs - track multi-step work across sessions with status, phase, and progress.
argument-hint: [list | show <id> | add <title> | update <id> [--status|--phase|--tried|--next] | complete <id> | archive <id> | delete <id> | ready]
allowed-tools: Bash(python3:*)
---

# Handoffs

Track multi-step work across sessions: capture work in progress, record phases, log what was tried, and resume later.

**Arguments**: $ARGUMENTS

## Finding the CLI

The CLI location varies by installation. Use this pattern to find and run it:

```bash
RECALL_CLI=$(ls ~/.claude/plugins/cache/claude-recall/claude-recall/*/core/cli.py 2>/dev/null | head -1)
python3 "$RECALL_CLI" <command> [args...]
```

Note: All commands below are under the `handoff` subgroup.

## Phases

- **research** - Exploring the problem space
- **planning** - Designing the solution
- **implementing** - Writing code
- **review** - Testing and reviewing changes

## Statuses

- **not_started** - Not yet begun
- **in_progress** - Currently being worked on
- **blocked** - Waiting on something
- **ready_for_review** - Ready for code review
- **completed** - Finished successfully

## Commands

Based on the first argument, execute the corresponding operation:

| Action | Args | CLI Command |
|--------|------|-------------|
| List active | (none) or `list` | `list` |
| Filter by status | `list --status <s>` | `list --status <s>` |
| Include completed | `list --include-completed` | `list --include-completed` |
| Show details | `show <id>` | `show <id>` |
| Create new | `add <title>` | `add "<title>"` |
| Create with options | `add <title> --phase <p>` | `add "<title>" --phase <p>` |
| Set status | `update <id> --status <s>` | `update <id> --status <s>` |
| Set phase | `update <id> --phase <p>` | `update <id> --phase <p>` |
| Log attempt | `update <id> --tried <outcome> <desc>` | `update <id> --tried <outcome> "<desc>"` |
| Set next steps | `update <id> --next <text>` | `update <id> --next "<text>"` |
| Mark done | `complete <id>` | `complete <id>` |
| Archive | `archive <id>` | `archive <id>` |
| Remove | `delete <id>` | `delete <id>` (confirm first) |
| Show ready | `ready` | `ready` |

## Examples

```bash
# Find CLI (set once per session)
RECALL_CLI=$(ls ~/.claude/plugins/cache/claude-recall/claude-recall/*/core/cli.py 2>/dev/null | head -1)
CMD="python3 $RECALL_CLI handoff"

# List active
$CMD list

# Filter by status
$CMD list --status blocked

# Include completed
$CMD list --include-completed

# Show specific
$CMD show H001

# Create new
$CMD add "Implement dark mode toggle"

# Create with options
$CMD add "Fix auth bug" --phase research --desc "Users getting logged out randomly"

# Set status
$CMD update H001 --status blocked

# Set phase
$CMD update H001 --phase implementing

# Log attempts
$CMD update H001 --tried success "Added unit tests for edge cases"
$CMD update H001 --tried fail "Tried caching but caused race condition"
$CMD update H001 --tried partial "Started refactor, needs more work"

# Set next steps
$CMD update H001 --next "Run integration tests and deploy to staging"

# Mark done
$CMD complete H001

# Archive
$CMD archive H001

# Show ready
$CMD ready
```

## Quick Reference

- `/handoffs` - List active
- `/handoffs list` - List active
- `/handoffs list --status blocked` - Filter by status
- `/handoffs list --include-completed` - Include completed
- `/handoffs show H001` - Show details
- `/handoffs add "Implement feature X"` - Create new
- `/handoffs update H001 --phase implementing` - Set phase
- `/handoffs update H001 --tried success "Done"` - Log attempt
- `/handoffs update H001 --next "Write tests"` - Set next steps
- `/handoffs complete H001` - Mark done
- `/handoffs archive H002` - Archive
- `/handoffs delete H003` - Remove (confirm first)
- `/handoffs ready` - Show ready
