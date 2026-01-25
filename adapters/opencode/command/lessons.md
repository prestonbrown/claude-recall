---
description: Manage the Claude Recall lessons system - a learning cache that tracks corrections and patterns across sessions.
argument-hint: [list | search <term> | category <cat> | stale | show <id> | add <cat> <title> - <content> | cite <id> | delete <id>]
allowed-tools: Bash(claude-recall:*)
---

Run the `claude-recall` CLI with `$ARGUMENTS` and return only the CLI output.

Rules:
- If `$ARGUMENTS` is empty, use `list`.
- Do not include any extra explanation or documentation.

Command:
```
claude-recall $ARGUMENTS
```
