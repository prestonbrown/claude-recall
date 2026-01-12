# Ideas & Future Enhancements

Ideas that aren't ready for implementation but worth capturing for later.

---

## Git Commit Log Signal for Orphan Handoff Detection

**Context:** We added conservative orphan handoff auto-completion (status=ready_for_review, all success steps, >1 day old). But some orphans may not meet these criteria.

**Idea:** Use git commit log as a secondary "smell test" for handoffs that look complete but weren't closed out:

1. Compare handoff creation date to recent commits
2. If commits exist after handoff creation, that's evidence work was done
3. Instead of auto-completing, prompt/ASK the user about these handoffs
4. Let user decide: complete it, keep it active, or archive it

**Why prompt instead of auto-complete:**
- Git commits don't guarantee the handoff work is done (could be unrelated commits)
- Gives user control over ambiguous cases
- Safer than false positives

**Implementation notes:**
- Could run `git log --oneline --since="<handoff_created>"` to check for commits
- Consider checking commit messages for handoff ID references
- Add to inject hook or as a separate cleanup command

---

## Relevance Scoring for Handoff Injection

**Context:** Currently all active handoffs are injected. With many handoffs, this could consume too many tokens.

**Idea:** Score handoffs by relevance to current context (similar to lesson relevance scoring):
- Recently updated handoffs rank higher
- Handoffs matching current directory/files rank higher
- User's first prompt could influence which handoffs to show

---

## Token Usage Monitoring

**Context:** We made a 90% token reduction in handoff injection, but have no visibility into actual production usage.

**Idea:** Monitor and log token consumption:
- Track tokens used by lessons injection
- Track tokens used by handoffs injection
- Log to debug output for analysis
- Could help identify when injection is getting too heavy

---

## TodoWrite as Primary Activity Source

**Context:** Handoffs rely on explicit agent output patterns (HANDOFF UPDATE, HANDOFF COMPLETE), but agents don't naturally emit these - they just do work. Meanwhile, agents DO use TodoWrite naturally.

**Problem:** Tried steps are sparse, handoffs don't capture actual work done, state gets stale.

**Idea:** Auto-populate tried steps from completed TodoWrite items:
- Every completed todo → tried step with outcome "success"
- Stop hook continues parsing explicit patterns for fail/partial
- Zero cognitive load for agents - they already use TodoWrite
- Augment with file mutation data from Edit/Write tool usage

**Implementation notes:**
- Stop hook already sees tool usage - can track Edit/Write targets
- Associate files with tried steps: "[success] Implement X - modified: a.py, b.py"
- Compress file lists: show count if >3 files

---

## Handoff Title Drift Detection

**Context:** Sessions often start with one goal but evolve. The handoff title becomes stale but nothing prompts an update. Example: "Fix title truncation" became "Handoff system improvements" but title never updated.

**Problem:** Handoff titles don't reflect actual scope of work done.

**Idea:** Detect when work has drifted from original title:
- Compare tried step keywords against title keywords
- If N+ steps without title overlap → prompt agent to update title
- Or auto-suggest new title based on recent step themes
- Could also detect when handoff should split into multiple

**Signals for drift:**
- TodoWrite items don't match handoff title theme
- More than 5 tried steps with no keyword overlap to title
- Phase changed but title still describes early-phase work

---

## Phase and Status Inference from Activity

**Context:** Handoffs get stuck in wrong states. "Research" phase even after 80 implementation steps. "In progress" even when all work done.

**Idea:** Infer handoff state from observable artifacts:

**Phase inference:**
- 10+ Edit/Write calls → `implementing`
- Test runs appearing → `implementing` or `review`
- Git commits → `review`

**Status inference:**
- All todos complete + no pending "Next" → `ready_for_review`
- Recent git commit matching handoff scope → consider complete
- Handoff dormant N days with all success steps → auto-complete (implemented!)

---

## System Reminder Injection for Hook Actions

**Context:** When hooks create handoffs (e.g., post-exitplanmode), the agent often doesn't notice. The hook output appears in tool results but reads like a log message, not actionable information. Agent then fails to reference the handoff that was just created.

**Problem:** Hooks do work but agents don't know about it. Creates friction and defeats the purpose.

**Alternative idea (if explicit hook output isn't enough):**
- After hook creates a handoff, inject a system reminder
- Not just in tool output, but as something agent naturally incorporates
- Example: `<system-reminder>Handoff hf-b2f00dc was just created for "Test Suite Audit Plan". Reference this ID when handing off to a new session.</system-reminder>`

**Trade-off:** More complex to implement than just improving hook output format, but more reliable since agents definitely process system reminders.

---

## Store Full Datetimes for Handoffs

**Context:** Handoff timestamps currently store only dates (YYYY-MM-DD), not full datetimes. The TUI shows "today" or "yesterday" but can't show what time a handoff was created or updated.

**Problem:** When multiple handoffs happen on the same day, you can't tell which is more recent. The "Updated" column doesn't help distinguish recent activity.

**Idea:** Change handoff data model to store ISO 8601 datetimes:
- `created`: "2024-01-15T14:30:00" instead of "2024-01-15"
- `updated`: Same format
- TUI displays: "today 2:30 PM" or "yesterday 9:15 AM"
- Use existing `_get_time_format()` to respect user's 12h/24h preference

**Implementation notes:**
- Update `core/models.py` Handoff dataclass
- Update `core/handoffs.py` where timestamps are set
- Update TUI `_format_handoff_date()` to parse and display times
- Migration: existing date-only values should still parse (add T00:00:00 default)

---

## Git Commit Integration for Handoffs

**Context:** Commits are the strongest signal of completed work. Currently handoffs don't integrate with git at all.

**Idea:** Use git commits as milestone markers:
- Post-commit hook → creates tried step from commit message
- Commit = strong signal of completed unit of work
- Could trigger handoff checkpoint or auto-complete if commit message matches handoff scope
- Could auto-update handoff title based on commit message themes

**Implementation:**
- Add post-commit hook to installation
- Parse commit message for handoff ID references
- If no ID, match by keyword similarity to active handoffs

---
