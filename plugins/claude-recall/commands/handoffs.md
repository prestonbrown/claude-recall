---
description: Manage active handoffs - track multi-step work across sessions with status, phase, and progress.
argument-hint: [list | show <id> | add <title> | update <id> [--status|--phase|--tried|--next] | complete <id> | archive <id> | delete <id> | ready]
allowed-tools: Bash(recall *)
---

# Handoffs

Track multi-step work across sessions: capture work in progress, record phases, log what was tried, and resume later.

**Arguments**: $ARGUMENTS

## Using the CLI

The `recall` binary is installed at `~/.local/bin/recall`. Commands:

```bash
recall handoff <command> [args...]
```

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
| List active | (none) or `list` | `recall handoff list` |
| Filter by status | `list --status <s>` | `recall handoff list --status <s>` |
| Include completed | `list --include-completed` | `recall handoff list --include-completed` |
| Show details | `show <id>` | `recall handoff show <id>` |
| Create new | `add <title>` | `recall handoff add "<title>"` |
| Create with options | `add <title> --phase <p>` | `recall handoff add "<title>" --phase <p>` |
| Set status | `update <id> --status <s>` | `recall handoff update <id> --status <s>` |
| Set phase | `update <id> --phase <p>` | `recall handoff update <id> --phase <p>` |
| Log attempt | `tried <id> <outcome> <desc>` | `recall handoff tried <id> <outcome> "<desc>"` |
| Set next steps | `update <id> --next <text>` | `recall handoff update <id> --next "<text>"` |
| Mark done | `complete <id>` | `recall handoff complete <id>` |
| Archive | `archive` | `recall handoff archive` |
| Remove | `delete <id>` | Show first, confirm with user |

## Examples

```bash
# List active
recall handoff list

# Filter by status
recall handoff list --status blocked

# Include completed
recall handoff list --include-completed

# Show specific
recall handoff show hf-abc1234

# Create new
recall handoff add "Implement dark mode toggle"

# Create with options
recall handoff add "Fix auth bug" --phase research --desc "Users getting logged out randomly"

# Set status
recall handoff update hf-abc1234 --status blocked

# Set phase
recall handoff update hf-abc1234 --phase implementing

# Log attempts
recall handoff tried hf-abc1234 success "Added unit tests for edge cases"
recall handoff tried hf-abc1234 fail "Tried caching but caused race condition"
recall handoff tried hf-abc1234 partial "Started refactor, needs more work"

# Set next steps
recall handoff update hf-abc1234 --next "Run integration tests and deploy to staging"

# Mark done
recall handoff complete hf-abc1234

# Archive old completed handoffs
recall handoff archive
```

## Quick Reference

- `/handoffs` - List active
- `/handoffs list` - List active
- `/handoffs list --status blocked` - Filter by status
- `/handoffs list --include-completed` - Include completed
- `/handoffs show hf-abc1234` - Show details
- `/handoffs add "Implement feature X"` - Create new
- `/handoffs update hf-abc1234 --phase implementing` - Set phase
- `/handoffs tried hf-abc1234 success "Done"` - Log attempt
- `/handoffs update hf-abc1234 --next "Write tests"` - Set next steps
- `/handoffs complete hf-abc1234` - Mark done
- `/handoffs archive` - Archive old completed
