# Roadmap

Open work, roughly in priority order. Everything here is a known gap with
evidence behind it, not a wishlist. Shipped design docs live in
[docs/archive/](docs/archive/README.md).

## Now

### Reap session dedup files

`~/.local/state/claude-recall/` holds **2,310** `session-dedup-*.json` files, the
oldest from 2026-02-23, and the state directory is **74 MB**. Nothing deletes
them — `hook-lib.sh` only resolves the path and reads/writes. One file per
session accumulates forever.

Needs an age-based sweep (the dedup set is only meaningful for a live session),
run from a hook that already fires, or on `recall decay`.

### Decide the fate of `core/` Python

With the TUI removed, **nothing calls `core/` at runtime** — not the hooks, not
`install.sh`, not the adapters. It is a library exercised only by its own tests.
It still holds a complete second implementation of the lessons store, kept
format-compatible with the Go parser by `tests/test_format_compat.py`.

Either commit to it as a maintained parity implementation and say so, or delete
it and drop the Python test suite with it. The current in-between state costs
maintenance for no runtime benefit.

### Fix or delete the shell test suites

All five of `tests/test-*.sh` currently fail, and none of them run in CI:

| Suite | Status |
|---|---|
| `test-hook-guards.sh` | fails — 5 assertions, checks a guard convention hooks no longer follow |
| `test-install.sh` | fails |
| `test-lessons-manager.sh` | fails — drives `core/lessons_manager.py`, which no longer exists |
| `test-stop-hook.sh` | fails |
| `test-velocity.sh` | fails |

They are the only tests asserting on installed-hook behaviour end to end, so
they are worth repairing rather than dropping — but a suite that always fails
and never runs is worse than none.

### Document `recall validate`

It shipped (`go/internal/validate/`, ~500 lines with a dismissal ledger and a
reverse citation check) and appears in **no** user-facing documentation — not
README, ARCHITECTURE, or CLAUDE.md.

## Next

### Staleness surfacing at injection

Deferred from the [lesson validation
design](docs/archive/superpowers/specs/2026-07-26-lesson-validation-design.md):
weight re-validation prompts by `age × uses`, so the lessons most likely to have
drifted are the ones you get asked about. The audit that motivated `validate`
found citation count *anti-correlated* with correctness — the two most-cited
lessons were both wrong.

### Injection precision

The long-running thread: file-path filtering and the negative-feedback loop
shipped, then the graduated trust multiplier replaced the binary injection
penalty. A blind panel found uncited lessons are ~95% genuinely off-topic, so
the dominant problem is injection relevance rather than labelling. Next
increment is unscoped.

## Housekeeping

- Remove the orphaned `~/.claude/plugins/cache/claude-recall/claude-recall/1.2.0/`
  directory (with a stray `1.1.0` nested inside it). Unregistered since the
  cache moved to 1.4.0.
- `recall.log` reached 7.5 MB with no rotation policy documented.
- The `chore/remove-handoffs` branch was squash-merged, so git cannot verify it
  as merged; it also carries an accidental `.venv/` commit in its history.
  Delete with `git branch -D` once you are satisfied with the merge.

## Conventions

Active design docs belong in `docs/superpowers/specs/`; move them to
`docs/archive/` once the work ships, and add a row to the archive index saying
what shipped and where the code lives.
