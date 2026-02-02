#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Minimal CLI for TUI-only access.

This module provides the 'watch' command for the Claude Recall debug TUI.
All other CLI commands are handled by the Go binary (go/bin/recall).

Usage:
    python3 -m core.tui_cli watch            # Full TUI mode
    python3 -m core.tui_cli watch --summary  # One-shot text summary
    python3 -m core.tui_cli watch --tail     # Simple colorized tail mode
"""

import argparse
import sys

try:
    from core._version import __version__
except ImportError:
    from _version import __version__


def main():
    """CLI entry point for TUI-only access."""
    parser = argparse.ArgumentParser(
        description="Claude Recall - TUI Debug Viewer",
        epilog="For other commands, use: recall <command> (Go CLI)"
    )
    parser.add_argument(
        "--version", action="version", version=f"claude-recall {__version__}"
    )
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # watch command - TUI debug viewer
    watch_parser = subparsers.add_parser("watch", help="Launch debug TUI viewer")
    watch_parser.add_argument("--project", "-p", help="Filter to specific project")
    watch_parser.add_argument(
        "--summary", action="store_true", help="One-shot text summary (no TUI)"
    )
    watch_parser.add_argument(
        "--tail", action="store_true", help="Simple colorized tail mode (no TUI)"
    )
    watch_parser.add_argument(
        "--lines", "-n", type=int, default=50, help="Number of lines for tail/summary"
    )

    args = parser.parse_args()

    # Default to watch (TUI) when no subcommand given
    if not args.command:
        args.command = "watch"
        args.project = None
        args.summary = False
        args.tail = False
        args.lines = 50

    if args.command == "watch":
        try:
            from core.tui.log_reader import (
                LogReader,
                get_default_log_path,
                format_event_line,
            )
            from core.tui.state_reader import StateReader
            from core.tui.stats import StatsAggregator
        except ImportError:
            from tui.log_reader import (
                LogReader,
                get_default_log_path,
                format_event_line,
            )
            from tui.state_reader import StateReader
            from tui.stats import StatsAggregator

        log_path = get_default_log_path()
        reader = LogReader(log_path)
        reader.load_buffer()

        if args.summary:
            # One-shot text summary for agents
            state_reader = StateReader()
            aggregator = StatsAggregator(reader, state_reader)
            print(aggregator.format_summary(project=args.project, limit=args.lines))

        elif args.tail:
            # Simple colorized tail mode
            events = reader.read_recent(args.lines)
            if args.project:
                events = [e for e in events if e.project == args.project]
            for event in events:
                print(format_event_line(event))

        else:
            # Full TUI mode
            try:
                from core.tui.app import RecallMonitorApp
            except ImportError:
                try:
                    from tui.app import RecallMonitorApp
                except ImportError as e:
                    print(f"Error: TUI requires textual package: {e}", file=sys.stderr)
                    print("Install with: pip install textual", file=sys.stderr)
                    sys.exit(1)
            app = RecallMonitorApp(project_filter=args.project)
            app.run()
    else:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        print("This CLI only supports the 'watch' command.", file=sys.stderr)
        print("For other commands, use: recall <command> (Go CLI)", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
