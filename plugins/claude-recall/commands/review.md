---
description: Code review protocol. Launch after implementation, before commit. Catches bugs, security issues, and test gaps.
allowed-tools: Task
---

# CODE REVIEW PROTOCOL

> **Mandatory** before every commit in MAJOR work.

## Launch Review Agent

Use `general-purpose` agent with this prompt template:

```
Review the changes in [list files]. Check for:

**Correctness**
- Logic errors and edge cases
- Off-by-one errors
- Null/undefined handling
- Race conditions (if async)

**Security**
- Injection vulnerabilities (SQL, command, XSS)
- Authentication/authorization gaps
- Sensitive data exposure
- Input validation at boundaries

**Tests**
- Coverage gaps (what's not tested?)
- Missing edge cases
- Tests that would pass even if feature removed

**Style**
- Consistency with existing patterns
- Naming clarity
- Unnecessary complexity

Suggest specific improvements with code examples.
```

## After Review

1. **Fix issues** found before committing
2. **Re-review** if changes were significant
3. **Document** any intentional deviations

## Quick Self-Review Checklist

If delegating full review isn't practical:

- [ ] Would tests fail if I removed this feature?
- [ ] Are all inputs validated at system boundaries?
- [ ] Are error messages safe (no sensitive data)?
- [ ] Did I add any TODOs that need tracking?
- [ ] Is there any copy-pasted code that should be abstracted?
