---
description: Execute MAJOR features with planning, delegation, test-first development, and code review. Use for new features, fixes, or refactoring involving 4+ files or architectural changes.
argument-hint: "[feature-name]"
allowed-tools: Task, EnterPlanMode, TodoWrite, Bash(git:*), Bash(./run-tests.sh:*)
---

# IMPLEMENTATION PROTOCOL

> **Critical**: All CLAUDE.md rules apply.

## WHERE ARE YOU?

| State | Action |
|-------|--------|
| No plan yet | → MODE 1: Plan First |
| Have approved plan | → MODE 2: Execute |

---

## MODE 1: PLAN FIRST

1. **Classify**: MAJOR (4+ files, new feature, architectural) or MINOR?
2. **MAJOR**: Use `EnterPlanMode` → explore → design → get user approval
3. **MINOR**: Mental plan is fine, proceed directly

---

## MODE 2: EXECUTE

### Use TodoWrite to Track Progress

Create todos for each phase/step to track progress.

### Follow These Protocols

1. **Delegate work** → See `/delegate` for rules
2. **Write tests first** → See `/test-first` for discipline
3. **Review before commit** → Run `/code-review` (built-in)

### Per Phase

```
1. Tests FIRST (mandatory)
2. Delegate implementation to agent
3. Code review (mandatory)
4. Fix review issues
5. Commit: git commit -m "[phase-N] description"
6. Mark todo complete
```

### Completion

1. Run full test suite - must pass
2. Mark final todo complete
3. Review session for lessons learned

### Stop Rule

**3 failures on same issue → STOP.** Document:
- What you tried
- Why it failed
- Your hypothesis
- What would unblock progress

