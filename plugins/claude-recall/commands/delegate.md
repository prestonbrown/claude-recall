---
description: Rules for delegating work to agents. When to use Explore vs general-purpose agents, and when direct work is acceptable.
allowed-tools: Task
---

# DELEGATION PROTOCOL

> **Default**: Delegate. Direct work is the exception.

## Decision Matrix

| Need | Agent | Prompt Tips |
|------|-------|-------------|
| Search/explore 2+ files | `Explore` | Be specific about what you're looking for |
| Find code patterns | `Explore` | Include example patterns to match |
| Understand architecture | `Explore` | Ask for summary + key files |
| Implement feature | `general-purpose` | Include: files, requirements, constraints |
| Fix bug | `general-purpose` | Include: symptom, suspected cause, test to verify |
| Refactor code | `general-purpose` | Include: current state, target state, what to preserve |
| Write tests | `general-purpose` | Include: what to test, edge cases, existing patterns |

## Direct Work ONLY If ALL True

- Single file
- Exact location known
- Less than 10 lines
- No investigation needed

**If you catch yourself doing file reads/edits for implementation → STOP → delegate.**

## Agent Prompting Tips

**Be explicit about**:
- Relevant files and their purposes
- Test expectations and how to verify
- Constraints (don't modify X, must use Y pattern)
- What success looks like

**Example**:
```
Implement rate limiting for the /api/submit endpoint.

Files:
- src/api/routes.ts (add middleware)
- src/middleware/rate-limit.ts (create new)
- tests/api/rate-limit.test.ts (create new)

Requirements:
- 10 requests per minute per IP
- Return 429 with Retry-After header
- Use existing Redis connection from src/db/redis.ts

Tests should verify: limit works, counter resets, header is correct.
```
