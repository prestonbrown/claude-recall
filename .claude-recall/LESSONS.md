# LESSONS.md - Project Level

> **Lessons System**: Cite lessons with [L###] when applying them.
> Stars accumulate with each use. At 50 uses, project lessons promote to system.
>
> **Add lessons**: `LESSON: [category:] title - content`
> **Categories**: pattern, correction, decision, gotcha, preference

## Active Lessons


### [L001] [**---|+----] Delimiter conflicts
- **Uses**: 4 | **Velocity**: 0.51 | **Learned**: 2025-12-27 | **Last**: 2026-01-05 | **Category**: pattern | **Type**: informational
> When adding special characters to display formats (like | in star ratings), check if they conflict with internal delimiters used for parsing. We had to switch from | to ~ as the internal field separator.


### [L002] [**---|-----] Two-phase file updates
- **Uses**: 3 | **Velocity**: 0.01 | **Learned**: 2025-12-27 | **Last**: 2025-12-30 | **Category**: pattern | **Type**: constraint
> When modifying a file based on its contents, collect items to change first, then apply updates with fresh reads. Modifying while reading causes stale data bugs.


### [L003] [**---|-----] Test HOME override
- **Uses**: 3 | **Velocity**: 0.01 | **Learned**: 2025-12-27 | **Last**: 2025-12-29 | **Category**: gotcha | **Type**: constraint
> When tests override HOME, hooks still look for manager at hardcoded paths. Must symlink manager to test LESSONS_BASE or tests fail silently.
