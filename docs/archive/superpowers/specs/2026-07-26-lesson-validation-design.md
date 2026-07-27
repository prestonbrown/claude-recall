# Lesson Validation & Stat/Content Split — Design

Status: approved 2026-07-26
Scope: `recall validate`, tombstoned deletes, ID reserve-on-allocate, stats sidecar.

## Problem

Lessons go stale and nothing detects it. A 2026-07-26 audit of helixscreen's 63 project
lessons (commit `c300ffe9a`) found three actively wrong, and the two worst were the two
most-cited:

- **L014** (41 uses) taught `lv_xml_component_register_from_file()` in `main.cpp`. The word
  order is transposed — that symbol has zero occurrences in the tree. The real function is
  `lv_xml_register_component_from_file`, called from `src/xml_registration.cpp:267`.
- **L060** (100 uses) taught `--test -vv -p panel_name`. The `-p/--panel` flag was removed;
  no such option is registered in `src/system/cli_args.cpp`. Navigation is now
  `helix-screen ctl` (`src/main.cpp:105`).
- **L021** recommended storing temperatures as "centidegrees" — the exact misnomer
  `tests/shell/test_code_lint.bats:75` forbids. The unit is decidegrees.

A fourth was caught by hand on 2026-07-25: **L048** named `drain_queue_for_testing()`, which
never existed.

Citation count is anti-correlated with correctness. Stars and velocity measure how often a
lesson is used, not whether it is still true, and nothing re-validates a lesson against the
repo it describes. High-traffic lessons therefore drift furthest.

## What the obvious approach does not catch

helixscreen has a working precedent for the doc equivalent in `scripts/check_doc_refs.py`:
it resolves backticked paths and exits nonzero on a miss. The obvious move is to point the
same technique at lesson bodies.

**Measured against the pre-audit lesson set (`33ca666c7^`), that approach catches 0 of the 3.**
Three distinct structural misses:

| Lesson | Why backtick-resolution misses it |
|---|---|
| L021 | "Centidegrees" is prose, never backticked. No reference-resolution check can see it. |
| L060 | `-p panel_name` sits inside a multi-token backticked command. Token extraction skips spans containing spaces, or drowns in noise if it does not. |
| L014 | The phantom symbol **resolves**. `scripts/check_doc_refs.py:15` names it in a comment explaining that it does not exist. |

L014 generalizes into the central design constraint: **presence-anywhere is a broken oracle.**
A phantom taught by a lesson propagates into artifacts, and those artifacts then vouch for the
phantom. `drain_queue_for_testing()` is now written into 4 plan/spec docs. The transposed XML
symbol is live in 7 doc files including `docs/devel/DEVELOPER_QUICK_REFERENCE.md` and
`docs/devel/UI_TESTING.md`.

## Data (measured 2026-07-26)

Prototype extractor over helixscreen's current 59 lessons: 101 checkable refs, 14 flagged,
of which **~11 are false positives** in three families:

1. **Deliberate negative references** — corrected lessons name absent things on purpose:
   "NOT `component_register`", "the `-p` flag is GONE", "previously named
   `drain_queue_for_testing()`". A naive validator flags precisely the lessons just fixed.
2. **Device/runtime paths** — `/var/log/messages`, `/opt/helixscreen/`, `/tmp/helixscreen.log`
   are paths on the test printer, not in the repo.
3. **Prose shorthand with slashes** — `lv_draw_rect/_triangle/_fill`, `DRAW_MAIN_END/DRAW_POST`
   classify as paths but are English.

Corpus scope: only three projects have lesson sets — helixscreen (59), claude-recall (10),
habitat (1). claude-recall's ten lessons contain **zero** checkable references; they are all
process advice. The technique only bites where lessons cite code, which is 1 of 3 projects.
helixscreen is the case, not a sample.

### Rot runs in both directions

12 lesson IDs are cited in helixscreen's tree but absent from the store: L003, L004, L007,
L010, L012, L013, L029, L041, L049, L081, L084, L085. These are live references —
`include/ui_panel_print_status.h:676` reads "see [L084]: lifetime must outlive observer", and
L084 was merged into L077 by the audit. `[L012]` is cited in `include/moonraker_manager.h:345`
and `src/application/moonraker_manager.cpp:107` and recommends the `alive_` pattern the audit
commit calls deprecated.

Because `[L###]` is baked into code comments, **lesson IDs are a load-bearing public API.**
Deleting or merging a lesson breaks references the way removing a function does. The audit
created 14 new dangling refs.

### The ID collision is a miscrediting bug, not just ambiguity

`citationPattern = \[([LS]\d{3})\]` (`go/cmd/recall-hook/batch.go:162`) runs against agent
output. helixscreen independently uses `L081` as a permanent label for the bg-thread
`expired()` TOCTOU anti-pattern, baked into `scripts/check_l081_anti_pattern.py`, the
`// L081_OK` convention, `CLAUDE.md:147`, and `THREADING.md` — 18 bracketed occurrences.
Those are indistinguishable from citations, so any agent echoing one credited recall's L081
(a lesson about defer escaping the UpdateQueue batch). It carried 28 uses; some fraction was
phantom.

## Decisions (locked)

1. **Advisory by default, never a gate.** `recall validate` exits 0 unless `--strict`.
   Given an 11-of-14 FP rate, a hard gate gets switched off within a week.
2. **Negative references are absorbed by a dismissal ledger, not by authored markup.**
   No retrofit of 59 lessons, no new syntax.
3. **Verification excludes comments, docs, and plans.** Only real build inputs count as
   evidence a symbol exists.
4. **Deletion becomes tombstoning.** IDs are an API; they get redirects, not holes.
5. **IDs are reserved on allocate**, not renamed. ~200 in-source citations must keep working.
6. **Stats move to a sidecar.** Durable content and volatile counters separate.

## Architecture

### 1. `recall validate` — new Go subcommand

**Extraction.** Walk lesson bodies; pull candidates from backtick spans *including multi-token
ones*. Inside a command span, tokenize and classify each word rather than treating the span as
one opaque token — this is what makes L060's dead `-p` visible.

Four ref kinds: `ident`, `path`, `flag`, `vocab`.

**Oracles**, each tuned to the FP family it must survive:

- `ident` — `git grep -w -F` scoped to configured source roots, **with comment lines excluded**.
  Comment stripping is not optional: it is the only reason L014's phantom resolved. Docs and
  plans are excluded for the same reason.
- `path` — repo-relative existence plus suffix match. Absolute paths are skipped entirely
  (device paths, family 2). A token containing `/` but no file extension and no resolving
  directory prefix is treated as prose shorthand and skipped (family 3).
- `flag` — checked against a project-declared arg-parser file (`src/system/cli_args.cpp` for
  helixscreen). Skipped when undeclared, so it is opt-in rather than noisy.
- `vocab` — runs project-declared validators against lesson bodies. Reuses gates the project
  already trusts instead of reimplementing them.

**Dismissal ledger** — `.claude-recall/validate-dismissed.json`, keyed by
*(lesson ID, token, hash of lesson body)*. Dismiss once; it stays dismissed until the body is
edited, which changes the hash and re-opens every ref in that lesson. This is what makes
family 1 tractable: L014's "NOT `component_register`" is dismissed once, and a later rewrite
of L014 is re-checked from scratch.

**Reverse check** — scan the tree for `[L###]`/`[S###]`; report any absent from the store.

**Ranking** — output sorted by `uses × age`, so the highest-traffic, longest-unverified
lessons surface first. This deliberately inverts the trust curve: frequent citation becomes a
reason to re-check, not a reason to trust.

### 2. Tombstones (`internal/lessons`, `internal/models`)

`recall delete` stops hard-deleting. A removed lesson keeps its ID and gains a
`**Superseded**: L077` field (or `deleted`), is excluded from injection and scoring, and
`recall show L084` resolves to a redirect. The allocator never reuses a tombstoned number.

### 3. Reserve-on-allocate

At `recall add`, collect every `L###`-shaped token in the project tree. Any number present
there but absent from the store is claimed by the project and skipped. This covers
helixscreen's `L081` and also reserves IDs with live dangling references, so the two
mechanisms reinforce each other.

### 4. Stats/content split

`.claude-recall/stats.json` holds `{id: {uses, velocity, last}}`. `LESSONS.md` keeps durable
fields only. The header rating `[***--|-----]` is derived from stats, so it moves too:
headers become `### [L001] Title`, and the rating renders at injection time.

`.claude-recall/.gitignore` is already `*`, so the sidecar is ignored with no new plumbing.

Backward compatibility: the parser accepts headers with and without the rating, and falls
back to inline `Uses`/`Velocity`/`Last` when the sidecar lacks an ID. A migration pass
extracts inline stats on first write.

Motivation, in the audit commit's own words: the stat bumps "are interleaved in the same file
and could not be separated."

### 5. Near-free fixes (helixscreen)

- Drop `:(glob)!.claude-recall/**` from the centidegree gate in `tests/shell/test_code_lint.bats`
  and audit that file's other gates for the same exemption; fix what it surfaces. This catches
  the L021 class with no new machinery.
- `git rm --cached .claude-recall/LESSONS.md.lock` — a lock file tracked via a stray `git add -f`.

## Testing (test-first — write these before the modules)

The fixture is real, not synthetic: the pre-audit `LESSONS.md` is recoverable at
`33ca666c7^` and contains all three known-wrong lessons.

1. **Regression, must-flag** — validate flags L014, L060, and L021 on the pre-audit file.
2. **Regression, must-not-flag** — validate does not flag their corrected forms in
   `c300ffe9a`.
3. **FP families** — device paths (`/var/log/messages`), prose slashes
   (`lv_draw_rect/_triangle/_fill`), and negative references produce no findings.
4. **Comment-stripping oracle** — a symbol appearing *only* in a comment is reported absent.
   Uses the `check_doc_refs.py:15` case directly.
5. **Ledger expiry** — a dismissed ref reappears after the lesson body changes.
6. **Reverse check** — the 12 known dangling IDs are reported.
7. **Tombstones** — `show` on a superseded ID returns the redirect; injection and scoring skip
   it; the allocator does not reuse it.
8. **Allocator** — a number claimed by the project is skipped.
9. **Round-trip** — parse/serialize is stable across both stats formats, and migration is
   idempotent.

## Out of scope

- **Staleness surfacing at inject** (re-validation prompts weighted by age × uses). Deferred.
- **Cleaning existing contamination** — 7 doc files and 4 plan/spec docs carry phantom
  symbols. `validate` will surface them; repointing is separate work.
- **Extending `check_doc_refs.py` to identifiers.** It currently checks paths only, which is
  why it did not catch L014 despite citing it as motivation.

## Success criteria

1. Validate flags all three audited failures on the pre-audit fixture and none of their fixes.
2. False positives on the current 59-lesson set drop from ~11 to 0 without suppressing the
   true positives.
3. `git status` in helixscreen stays clean across an injection cycle.
4. No existing `[L###]` citation in helixscreen source stops resolving.
