# LESSONS.md - Project Level

> **Lessons System**: Cite lessons with [L###] when applying them.
> Stars accumulate with each use. At 50 uses, project lessons promote to system.
>
> **Add lessons**: `LESSON: [category:] title - content`
> **Categories**: pattern, correction, decision, gotcha, preference

## Active Lessons


### [L001] [***--|-----] Delimiter conflicts
- **Uses**: 7 | **Velocity**: 0.04 | **Learned**: 2025-12-27 | **Last**: 2026-01-18 | **Category**: pattern | **Type**: informational
> When adding special characters to display formats (like | in star ratings), check if they conflict with internal delimiters used for parsing. We had to switch from | to ~ as the internal field separator.


### [L002] [**---|-----] Two-phase file updates
- **Uses**: 4 | **Velocity**: 0.01 | **Learned**: 2025-12-27 | **Last**: 2026-01-05 | **Category**: pattern | **Type**: constraint
> When modifying a file based on its contents, collect items to change first, then apply updates with fresh reads. Modifying while reading causes stale data bugs.


### [L003] [**---|-----] Test HOME override
- **Uses**: 3 | **Velocity**: 0.01 | **Learned**: 2025-12-27 | **Last**: 2025-12-29 | **Category**: gotcha | **Type**: constraint
> When tests override HOME, hooks still look for manager at hardcoded paths. Must symlink manager to test LESSONS_BASE or tests fail silently.


### [L004] [*----|-----] Silent hook failures
- **Uses**: 2 | **Velocity**: 0.01 | **Learned**: 2026-01-06 | **Last**: 2026-01-06 | **Category**: pattern | **Type**: constraint
> Always log errors before returning from hooks, especially external hooks like inject-hook.sh. Silent failures make debugging impossible - we had session_start not logging because inject_context() returned early before logging, and inject-hook.sh swallowed python errors. Add error logging paths that write to debug log even on failure.


### [L005] [*----|-----] Commit LESSONS.md periodically
- **Uses**: 2 | **Velocity**: 0.01 | **Learned**: 2026-01-07 | **Last**: 2026-01-07 | **Category**: pattern | **Type**: informational
> LESSONS.md is shared across checkouts of claude-recall for common project understanding. Commit it periodically to sync lessons between machines/sessions.


### [L006] [*----|-----] OptionList for popup navigation
- **Uses**: 1 | **Velocity**: 0.0 | **Learned**: 2026-01-09 | **Last**: 2026-01-09 | **Category**: pattern | **Type**: informational
> In Textual TUI, use OptionList widget instead of Static for modal popup menus. OptionList provides built-in arrow key navigation and Enter selection. Static widgets don't handle keyboard navigation.


### [L007] [*----|-----] Double-action popup trigger
- **Uses**: 2 | **Velocity**: 0.01 | **Learned**: 2026-01-09 | **Last**: 2026-01-11 | **Category**: pattern | **Type**: informational
> Track confirmed selection separately from current selection (e.g., _current_handoff_id vs _user_selected_handoff_id). First action confirms selection, second action on same item opens popup. Prevents accidental popup triggers.


### [L008] [*----|-----] Consistent state_dir usage
- **Uses**: 1 | **Velocity**: 0.0 | **Learned**: 2026-01-09 | **Last**: 2026-01-09 | **Category**: pattern | **Type**: constraint
> Always use self.state_reader.state_dir for state file paths rather than reimplementing path resolution inline. Duplicating env var checks leads to inconsistencies.
