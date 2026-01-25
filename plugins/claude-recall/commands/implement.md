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
| Have approved plan | → MODE 2: Execute (handoff auto-created) |
| Resuming from handoff | → MODE 2: Execute (check handoff for context) |

---

## MODE 1: PLAN FIRST

1. **Classify**: MAJOR (4+ files, new feature, architectural) or MINOR?
2. **MAJOR**: Use `EnterPlanMode` → explore → design → get user approval
3. **MINOR**: Mental plan is fine, proceed directly

**Note**: When you exit plan mode, a handoff is **automatically created** and linked to this session.

---

## MODE 2: EXECUTE

### Use TodoWrite to Track Progress

Create todos for each phase/step. The system will:
- Auto-create handoff if 3+ todos (if not already linked)
- Sync todo states to handoff tried/next steps
- Link session automatically (no manual `[hf-XXX]` prefix needed)

### Follow These Protocols

1. **Delegate work** → See `/delegate` for rules
2. **Write tests first** → See `/test-first` for discipline
3. **Review before commit** → See `/review` for checklist

### Per Phase

```
1. Tests FIRST (mandatory)
2. Delegate implementation to agent
3. Code review (mandatory)
4. Fix review issues
5. Commit: git commit -m "[phase-N] description"
6. Mark todo complete (auto-syncs to handoff)
```

### Completion

1. Run full test suite - must pass
2. Mark final todo complete
3. Output: `HANDOFF COMPLETE LAST` (triggers lesson review prompt)

### Stop Rule

**3 failures on same issue → STOP.** Document:
- What you tried
- Why it failed
- Your hypothesis
- What would unblock progress

---

## HANDOFF COMMANDS (when needed)

Most handoff tracking is **automatic** via TodoWrite. Use these only when needed:

| Command | When |
|---------|------|
| `HANDOFF: title` | Manual creation (no todos/plan mode) |
| `HANDOFF UPDATE LAST: tried success - desc` | Record attempt outside todos |
| `HANDOFF UPDATE LAST: next steps here` | Update next steps |
| `HANDOFF COMPLETE LAST` | Mark done + trigger lesson review |

`LAST` = most recently updated active (non-completed) handoff. Can also use explicit `hf-XXXXXXX`.
