# Archive

Design docs, implementation plans, and idea backlogs whose work has shipped or
been abandoned. They are kept as a record of why things are the way they are;
none of them describe current behaviour, and none should be treated as a spec.

For how the system works today see [ARCHITECTURE.md](../ARCHITECTURE.md),
[DEPLOYMENT.md](../DEPLOYMENT.md) and [TESTING.md](../TESTING.md).

## Shipped

| Document | Shipped as |
|---|---|
| [plans/2026-02-18-better-lesson-injection-design.md](plans/2026-02-18-better-lesson-injection-design.md) · [plan](plans/2026-02-18-better-lesson-injection-plan.md) | BM25 relevance scoring on every prompt (`smart-inject-hook.sh` → `recall score-local`). The same plan retired the handoff hooks, which is where the handoff removal began. |
| [plans/2026-03-25-observability-reporting-design.md](plans/2026-03-25-observability-reporting-design.md) · [plan](plans/2026-03-25-observability-reporting-plan.md) | `recall stats` and `recall digest` (`go/cmd/recall/stats.go`, `digest.go`), the session event log, and the precision digest. |
| [superpowers/specs/2026-03-31-injection-precision-design.md](superpowers/specs/2026-03-31-injection-precision-design.md) · [plan](superpowers/plans/2026-03-31-injection-precision.md) | File-path filtering and the negative-feedback loop for uncited lessons (`go/internal/feedback/`). |
| [superpowers/specs/2026-07-23-trust-model-backtest-design.md](superpowers/specs/2026-07-23-trust-model-backtest-design.md) | The graduated trust multiplier that replaced the binary injection penalty, plus the backtest harness in `experiments/`. |
| [superpowers/specs/2026-07-26-lesson-validation-design.md](superpowers/specs/2026-07-26-lesson-validation-design.md) | `recall validate` (`go/internal/validate/`), tombstoned deletes and ID reserve-on-allocate (`go/internal/lessons/reserve.go`), and the stats sidecar split (`go/internal/lessons/stats.go`). Its "out of scope" items — staleness surfacing at inject, and cleaning phantom symbols out of downstream docs — were never started. |
| [FLAKY_TEST_FIX_PLAN.md](FLAKY_TEST_FIX_PLAN.md) | Test isolation fixes for parallel pytest-xdist runs. |
| [OPENCODE_REVITALIZATION_PLAN.md](OPENCODE_REVITALIZATION_PLAN.md) · [completion notes](OPENCODE_REVITALIZATION_COMPLETE.md) | The OpenCode adapter rebuild against `@opencode-ai/plugin` 1.17.5 (`adapters/opencode/`). |

## Obsolete

| Document | Why |
|---|---|
| [IDEAS.md](IDEAS.md) | All nine entries were handoff features — orphan detection, phase inference, title drift, todo sync. Handoffs were removed entirely, so none of it applies. |

## A note on the handoff references

Several of these documents describe handoffs as a live feature. They were, when
the documents were written. Handoffs were removed in full — the Go store and
subcommands, the Python models, the PreCompact hook, the TUI tab, and the
OpenCode integration — because nothing produced them any more: the hooks that
created them had already been retired, and `HANDOFFS.md` did not exist in any
active project.
