#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
TUI module for claude-recall debug viewer.

Provides real-time monitoring of lessons system activity:
- Live event log from debug.log
- System health metrics (hook timing, error counts)
- State overview (lessons, handoffs)
- Session inspection with event correlation

Usage:
    from core.tui import RecallMonitorApp, run_app
    run_app()  # Launch TUI
    run_app(project_filter="my-project")  # Filter to project
"""

from .models import (
    DebugEvent,
    SystemStats,
    LessonSummary,
    HandoffSummary,
    DecayInfo,
)
from .log_reader import LogReader, parse_event, format_event_line, get_default_log_path
from .state_reader import StateReader
from .stats import StatsAggregator

# Defer app import to avoid textual dependency at module load time
# Users who don't need the TUI won't need textual installed
def _get_app():
    """Lazy import of app module to avoid textual import at module load."""
    from .app import RecallMonitorApp, run_app
    return RecallMonitorApp, run_app


def run_app(*args, **kwargs):
    """Run the TUI application. See app.run_app for details."""
    _, _run_app = _get_app()
    return _run_app(*args, **kwargs)


__all__ = [
    # Models
    "DebugEvent",
    "SystemStats",
    "LessonSummary",
    "HandoffSummary",
    "DecayInfo",
    # Log reader
    "LogReader",
    "parse_event",
    "format_event_line",
    "get_default_log_path",
    # State reader
    "StateReader",
    # Stats
    "StatsAggregator",
    # App (lazy loaded)
    "RecallMonitorApp",
    "run_app",
]
