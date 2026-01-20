---
description: Manage handoffs - track multi-step work across sessions with automatic todo sync and lesson extraction.
argument-hint: [list | add <title> | update <id> | complete <id> | delete <id> | show <id>]
allowed-tools: Bash(python3:*)
---

# Handoff Management

Track multi-step work across sessions: major features, integration tasks, and architectural changes.

**Arguments**: $ARGUMENTS

## Finding the CLI

The CLI is managed by the plugin. Use subprocess calls:

```bash
python3 ~/.config/claude-recall/core/cli.py handoff <command> [args...]
```

Or detect installed location:

```bash
PYTHON_CLI=$(find ~/.config/claude-recall -name "cli.py" 2>/dev/null | head -1)
python3 "$PYTHON_CLI" handoff <command>
```

## When to Use Handoffs

Use handoffs for **MAJOR** work:
- New features (4+ files, architectural changes)
- Integration work across multiple systems
- Refactoring that spans multiple sessions
- Complex bug fixes requiring investigation

Use TodoWrite directly for **MINOR** work:
- Single-file fixes
- Configuration changes
- Documentation updates

## Commands

Based on the first argument, execute the corresponding operation:

| Action | Args | CLI Command |
|--------|------|-------------|
| List all | (none) or `list` | `handoff list` |
| List active | `list --active` | `handoff list --active` |
| Add | `add <title>` | `handoff add "<title>"` |
| Add with description | `add <title> --desc "<description>"` | `handoff add "<title>" --desc "<description>"` |
| Update | `update <id>` | `handoff update <id> [options]` |
| Complete | `complete <id>` | `handoff complete <id>` |
| Show | `show <id>` | `handoff show <id>` |
| Delete | `delete <id>` | Show first, confirm with user, then `handoff delete <id>` |

## Update Options

When updating a handoff, use these flags:

| Option | Args | Description |
|--------|------|-------------|
| `--status` | `not_started\|in_progress\|blocked\|completed` | Change handoff status |
| `--phase` | `research\|planning\|implementing\|review` | Update phase |
| `--tried` | `success\|fail\|partial - <description>` | Record an attempt |
| `--next` | `<text>` | Update next steps |
| `--desc` | `<text>` | Update description |
| `--files` | `<file1,file2>` | Update tracked files |
| `--agent` | `explore\|general-purpose\|plan\|review\|user` | Update agent |

## Handoff Phases

- **research**: Investigation and exploration
- **planning**: Architecture and design decisions
- **implementing**: Writing code and changes
- **review**: Testing and validation

## Handoff Status

- **not_started**: Not yet begun
- **in_progress**: Currently being worked on
- **blocked**: Waiting on dependencies
- **completed**: All work finished

## Pattern Capture

The assistant can capture handoffs directly from output:

- `HANDOFF: <title>` - Start a new handoff
- `HANDOFF: <title> - <description>` - Start handoff with description
- `HANDOFF COMPLETE <id>` - Mark handoff as complete
- `HANDOFF UPDATE <id>: tried success|fail|partial - <description>` - Record attempt

## TodoWrite Integration

When using TodoWrite with an active handoff, todos automatically sync to the handoff:
- Completed todos → Tried entries (success)
- In-progress todo → Checkpoint
- Pending todos → Next steps

## Full Command Examples

```bash
# List all handoffs
python3 ~/.config/claude-recall/core/cli.py handoff list

# List active handoffs only
python3 ~/.config/claude-recall/core/cli.py handoff list --active

# Create a new handoff
python3 ~/.config/claude-recall/core/cli.py handoff add "Implement OAuth2 flow"

# Create handoff with description
python3 ~/.config/claude-recall/core/cli.py handoff add "Implement OAuth2 flow" \
  --desc "Add authentication for API endpoints"

# Create handoff with phase
python3 ~/.config/claude-recall/core/cli.py handoff add "Refactor database" \
  --phase planning

# Show handoff details
python3 ~/.config/claude-recall/core/cli.py handoff show hf-abc1234

# Update handoff status
python3 ~/.config/claude-recall/core/cli.py handoff update hf-abc1234 --status in_progress

# Update handoff phase
python3 ~/.config/claude-recall/core/cli.py handoff update hf-abc1234 --phase implementing

# Record successful attempt
python3 ~/.config/claude-recall/core/cli.py handoff update hf-abc1234 \
  --tried success "Implemented user authentication endpoint"

# Record failed attempt
python3 ~/.config/claude-recall/core/cli.py handoff update hf-abc1234 \
  --tried fail "Rate limiting caused authentication to fail"

# Update next steps
python3 ~/.config/claude-recall/core/cli.py handoff update hf-abc1234 \
  --next "1. Add refresh token support\n2. Implement token revocation"

# Update tracked files
python3 ~/.config/claude-recall/core/cli.py handoff update hf-abc1234 \
  --files "src/auth.py,src/middleware.py,tests/test_auth.py"

# Complete handoff
python3 ~/.config/claude-recall/core/cli.py handoff complete hf-abc1234

# Delete handoff (show first, then delete)
python3 ~/.config/claude-recall/core/cli.py handoff show hf-abc1234
# After confirmation:
python3 ~/.config/claude-recall/core/cli.py handoff delete hf-abc1234
```

## Output Format

Format list output as a markdown table with columns: ID, Status, Phase, Title, Description (truncated).

## Quick Reference

- `/handoffs` - List all handoffs
- `/handoffs list --active` - Show only active handoffs
- `/handoffs add "Implement feature"` - Create new handoff
- `/handoffs show hf-abc1234` - Show handoff details
- `/handoffs update hf-abc1234 --status in_progress` - Update status
- `/handoffs update hf-abc1234 --tried success "Fixed bug"` - Record attempt
- `/handoffs complete hf-abc1234` - Mark handoff as complete
- `/handoffs delete hf-abc1234` - Delete handoff (requires confirmation)
