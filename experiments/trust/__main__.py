"""CLI entry: ``python -m experiments.trust --log <path>``.

Replays the historical session log, scores every candidate trust formula, prints
the comparison table, and writes the tradeoff-curve CSV to
``experiments/trust/results/``. READ-ONLY with respect to all runtime state.
"""

from __future__ import annotations

import argparse
import os
import sys

from . import replay as R
from . import report as report_mod


def default_log_path() -> str:
    state = os.environ.get("CLAUDE_RECALL_STATE")
    if state:
        return os.path.join(state, "session-log.jsonl")
    return os.path.expanduser("~/.local/state/claude-recall/session-log.jsonl")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m experiments.trust",
        description="Offline backtest of candidate trust formulas against the "
                    "historical injection->citation log (read-only).",
    )
    parser.add_argument(
        "--log",
        default=default_log_path(),
        help="Path to session-log.jsonl "
             "(default: $CLAUDE_RECALL_STATE/session-log.jsonl or "
             "~/.local/state/claude-recall/session-log.jsonl)",
    )
    parser.add_argument(
        "--out",
        default=report_mod.RESULTS_DIR,
        help="Directory for the tradeoff-curve CSV "
             "(default: experiments/trust/results/)",
    )
    parser.add_argument(
        "--labels",
        default=None,
        help="Optional external label file mapping (session, lesson) -> "
             "applied(bool), used in place of the citation-derived label. "
             "Accepts .jsonl of {session,lesson,applied} records, a .json list "
             "of the same, or a .json object of '<session>|<lesson>': bool. "
             "Omit to run the default citation-labeled backtest unchanged.",
    )
    args = parser.parse_args(argv)

    if not os.path.exists(args.log):
        print(f"error: log not found: {args.log}", file=sys.stderr)
        return 1

    label_override = None
    if args.labels:
        if not os.path.exists(args.labels):
            print(f"error: labels file not found: {args.labels}",
                  file=sys.stderr)
            return 1
        label_override = R.load_label_file(args.labels)
        print(f"loaded {len(label_override)} external labels from {args.labels}")

    events = R.replay(args.log, label_override=label_override)
    if not events:
        print("no relevance-scored injection events survived filtering.",
              file=sys.stderr)
        return 1

    for line in report_mod.summary_lines(events):
        print(line)
    print()

    results = report_mod.evaluate_all(events)
    print(report_mod.format_table(results))
    print()

    csv_path = report_mod.write_tradeoff_csv(events, out_dir=args.out)
    print(f"tradeoff curves written to: {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
