"""Trust-model backtest harness.

Replays the historical injection->citation log through several candidate
"trust" formulas and reports which best predicts citations. Fully offline and
READ-ONLY: it only reads ``session-log.jsonl`` and never modifies LESSONS.md,
injection-stats.json, runtime state, or any Go code.

See ``docs/superpowers/specs/2026-07-23-trust-model-backtest-design.md``.
"""
