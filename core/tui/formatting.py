#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Shared formatting utilities for TUI components.

Consolidates time formatting and color definitions used by both
the log reader (terminal output) and app (Textual/Rich display).
"""

import platform
import subprocess
from datetime import timezone
from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import DebugEvent


@lru_cache(maxsize=1)
def _get_time_format() -> str:
    """Get the appropriate time format string based on system preferences.

    On macOS: checks AppleICUForce24HourTime preference
      - 1 = 24h format -> %H:%M:%S
      - 0 or unset = 12h format -> %r (with AM/PM)
    On other platforms: uses %X (locale-dependent)

    Returns:
        A strftime format string for time display.
    """
    if platform.system() != "Darwin":
        return "%X"  # Trust locale on Linux/other

    try:
        result = subprocess.run(
            ["defaults", "read", "NSGlobalDomain", "AppleICUForce24HourTime"],
            capture_output=True,
            text=True,
            timeout=1,
        )
        if result.returncode == 0 and result.stdout.strip() == "1":
            return "%H:%M:%S"  # User prefers 24h
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    return "%r"  # Default to 12h AM/PM on macOS


def _format_event_time(event: "DebugEvent") -> str:
    """Format event timestamp using system time format preference, in local timezone.

    Args:
        event: The debug event containing timestamp information.

    Returns:
        Formatted time string suitable for display.
    """
    dt = event.timestamp_dt
    if dt is None:
        # Fallback to raw timestamp extraction
        ts = event.timestamp
        if "T" in ts:
            return ts.split("T")[1][:8]
        return ts[:8] if len(ts) >= 8 else ts
    # Ensure timezone-aware and convert to local
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local_dt = dt.astimezone()
    return local_dt.strftime(_get_time_format())


# Semantic color mapping for Textual/Rich markup (color names, not ANSI codes)
EVENT_TYPE_COLORS = {
    "session_start": "cyan",
    "citation": "green",
    "error": "bold red",
    "decay_result": "yellow",
    "handoff_created": "magenta",
    "handoff_change": "magenta",
    "handoff_completed": "magenta",
    "timing": "dim",
    "hook_start": "dim",
    "hook_end": "dim",
    "hook_phase": "dim",
    "lesson_added": "bright_green",
}

# ANSI color codes for terminal output
ANSI_COLORS = {
    "session_start": "\033[36m",  # cyan
    "citation": "\033[32m",  # green
    "error": "\033[1;31m",  # bold red
    "decay_result": "\033[33m",  # yellow
    "handoff_created": "\033[35m",  # magenta
    "handoff_change": "\033[35m",
    "handoff_completed": "\033[35m",
    "timing": "\033[2m",  # dim
    "hook_start": "\033[2m",
    "hook_end": "\033[2m",
    "hook_phase": "\033[2m",
    "lesson_added": "\033[92m",  # bright_green
    "reset": "\033[0m",
}


from typing import Any, Dict


def extract_event_details(event: "DebugEvent") -> Dict[str, str]:
    """Extract structured details from any event type.

    Consolidates event detail extraction logic used by both ANSI (log_reader)
    and Rich (app) formatters. Returns a dict with string key-value pairs
    that can be formatted by either output system.

    Args:
        event: The debug event containing raw data.

    Returns:
        Dict with extracted details as string values. Empty dict for unknown events.
    """
    raw: Dict[str, Any] = event.raw
    result: Dict[str, str] = {}

    if event.event == "session_start":
        result["total"] = str(raw.get("total_lessons", 0))
        result["system_count"] = str(raw.get("system_count", 0))
        result["project_count"] = str(raw.get("project_count", 0))

    elif event.event == "citation":
        result["lesson_id"] = raw.get("lesson_id", "?")
        result["uses_before"] = str(raw.get("uses_before", 0))
        result["uses_after"] = str(raw.get("uses_after", 0))
        if raw.get("promotion_ready"):
            result["promo"] = "PROMO!"

    elif event.event == "decay_result":
        result["decayed_uses"] = str(raw.get("decayed_uses", 0))
        result["decayed_velocity"] = str(raw.get("decayed_velocity", 0))

    elif event.event == "error":
        result["op"] = raw.get("op", "")
        err = str(raw.get("err", ""))[:50]
        result["err"] = err

    elif event.event == "hook_end":
        result["hook"] = raw.get("hook", "")
        result["total_ms"] = str(raw.get("total_ms", 0))

    elif event.event == "hook_phase":
        result["hook"] = raw.get("hook", "")
        result["phase"] = raw.get("phase", "")
        result["ms"] = str(raw.get("ms", 0))

    elif event.event == "handoff_created":
        result["handoff_id"] = raw.get("handoff_id", "")
        result["title"] = raw.get("title", "")[:30]

    elif event.event == "handoff_completed":
        result["handoff_id"] = raw.get("handoff_id", "")
        result["tried_count"] = str(raw.get("tried_count", 0))

    elif event.event == "lesson_added":
        result["lesson_id"] = raw.get("lesson_id", "")
        result["level"] = raw.get("lesson_level", "")

    return result
