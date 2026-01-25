---
description: Manage handoffs - track multi-step work across sessions with automatic todo sync and lesson extraction.
argument-hint: [list | add <title> | update <id> | complete <id> | delete <id> | show <id>]
allowed-tools: Bash(claude-recall:*)
---

Run the `claude-recall` CLI with `$ARGUMENTS` and return only the CLI output.

Rules:
- If `$ARGUMENTS` is empty, use `handoff list`.
- If the user omits `handoff`, prepend it.
- Do not include any extra explanation or documentation.

Command:
```
claude-recall handoff $ARGUMENTS
```
