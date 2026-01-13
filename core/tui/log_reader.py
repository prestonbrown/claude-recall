#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Log reader for the TUI debug viewer.

Provides JSON parsing and buffered reading of debug.log with filtering
capabilities.
"""

import json
import os
from collections import deque
from pathlib import Path
from typing import Deque, Iterator, List, Optional

try:
    from core.tui.models import DebugEvent
    from core.tui.formatting import _format_event_time, ANSI_COLORS, extract_event_details
except ImportError:
    from .models import DebugEvent
    from .formatting import _format_event_time, ANSI_COLORS, extract_event_details

# Backward compatibility alias for COLORS
COLORS = ANSI_COLORS


def _format_details_from_extracted(event: DebugEvent, d: dict) -> str:
    """Format extracted details dict into display string for ANSI output."""
    if event.event == "session_start":
        return f"{d['system_count']}S/{d['project_count']}L ({d['total']} total)"

    elif event.event == "citation":
        promo = f" {d['promo']}" if "promo" in d else ""
        return f"{d['lesson_id']} ({d['uses_before']}\u2192{d['uses_after']}){promo}"

    elif event.event == "decay_result":
        return f"{d['decayed_uses']} uses, {d['decayed_velocity']} velocity decayed"

    elif event.event == "error":
        return f"{d['op']}: {d['err']}"

    elif event.event == "hook_end":
        ms = float(d["total_ms"])
        return f"{d['hook']}: {ms:.0f}ms"

    elif event.event == "hook_phase":
        ms = float(d["ms"])
        return f"{d['hook']}.{d['phase']}: {ms:.0f}ms"

    elif event.event == "handoff_created":
        return f"{d['handoff_id']} {d['title']}"

    elif event.event == "handoff_completed":
        return f"{d['handoff_id']} ({d['tried_count']} steps)"

    elif event.event == "lesson_added":
        return f"{d['lesson_id']} ({d['level']})"

    return ""


def format_event_line(event: DebugEvent, color: bool = True) -> str:
    """
    Format an event as a single colorized line for tail output.

    Args:
        event: The debug event to format
        color: Whether to use ANSI colors (default True)

    Returns:
        Formatted string for terminal display
    """
    time_part = _format_event_time(event)

    # Get color codes
    event_color = COLORS.get(event.event, "") if color else ""
    reset = COLORS["reset"] if color else ""

    # Extract event details using shared extractor
    d = extract_event_details(event)

    # Format details string from extracted data
    if d:
        details = _format_details_from_extracted(event, d)
    else:
        # Generic fallback: show first interesting key
        details = ""
        skip_keys = {"event", "level", "timestamp", "session_id", "pid", "project"}
        for k, v in event.raw.items():
            if k not in skip_keys:
                details = f"{k}={v}"
                break

    # Build line
    project = event.project[:15].ljust(15) if event.project else "".ljust(15)
    event_name = event.event[:18].ljust(18)

    return f"{event_color}[{time_part}] {event_name} {project} {details}{reset}"


def get_default_log_path() -> Path:
    """
    Get the default debug log path.

    Uses CLAUDE_RECALL_STATE env var if set, otherwise falls back
    to XDG state directory (~/.local/state/claude-recall/debug.log).

    Returns:
        Path to the debug.log file
    """
    explicit_state = os.environ.get("CLAUDE_RECALL_STATE")
    if explicit_state:
        return Path(explicit_state) / "debug.log"

    xdg_state = os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state")
    return Path(xdg_state) / "claude-recall" / "debug.log"


def parse_event(line: str) -> Optional[DebugEvent]:
    """
    Parse a single JSON line into a DebugEvent.

    Args:
        line: A JSON line from debug.log

    Returns:
        DebugEvent if parsing succeeds, None otherwise
    """
    line = line.strip()
    if not line:
        return None

    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None

    # Extract required fields with defaults
    event_type = data.get("event", "unknown")
    level = data.get("level", "info")
    timestamp = data.get("timestamp", "")
    session_id = data.get("session_id", "")
    pid = data.get("pid", 0)
    project = data.get("project", "")

    return DebugEvent(
        event=event_type,
        level=level,
        timestamp=timestamp,
        session_id=session_id,
        pid=pid,
        project=project,
        raw=data,
    )


class LogReader:
    """
    Buffered log reader with filtering capabilities.

    Maintains a ring buffer of recent events for efficient memory usage.
    Supports filtering by project, session, event type, and level.

    Attributes:
        log_path: Path to the debug.log file
        max_buffer: Maximum number of events to buffer
    """

    def __init__(
        self,
        log_path: Optional[Path] = None,
        max_buffer: int = 1000,
    ) -> None:
        """
        Initialize the log reader.

        Args:
            log_path: Path to debug.log file. If None, uses default path.
            max_buffer: Maximum events to keep in buffer (default 1000)
        """
        self.log_path = log_path or get_default_log_path()
        self.max_buffer = max_buffer
        self._buffer: Deque[DebugEvent] = deque(maxlen=max_buffer)
        self._last_position: int = 0
        self._last_inode: Optional[int] = None

    @property
    def buffer_size(self) -> int:
        """Number of events currently in buffer."""
        return len(self._buffer)

    def _check_rotation(self) -> bool:
        """
        Check if the log file was rotated.

        Detects rotation by comparing inodes. If rotated, resets
        position to read from the beginning of the new file.

        Returns:
            True if file was rotated, False otherwise
        """
        if not self.log_path.exists():
            return False

        try:
            current_inode = self.log_path.stat().st_ino
            if self._last_inode is not None and current_inode != self._last_inode:
                # File was rotated - reset position
                self._last_position = 0
                self._last_inode = current_inode
                return True
            self._last_inode = current_inode
            return False
        except OSError:
            return False

    def load_buffer(self) -> int:
        """
        Load events from log file into buffer.

        Reads from last position to handle incremental updates.
        Handles log rotation by detecting inode changes.

        Returns:
            Number of new events loaded
        """
        if not self.log_path.exists():
            return 0

        self._check_rotation()

        try:
            with open(self.log_path, "r", encoding="utf-8", errors="replace") as f:
                # Seek to last position
                f.seek(self._last_position)

                new_count = 0
                for line in f:
                    event = parse_event(line)
                    if event is not None:
                        self._buffer.append(event)
                        new_count += 1

                # Update position
                self._last_position = f.tell()
                return new_count

        except OSError:
            return 0

    def read_recent(self, n: int = 100) -> List[DebugEvent]:
        """
        Read the last N events from buffer.

        Args:
            n: Number of recent events to return (default 100)

        Returns:
            List of events, most recent last
        """
        # Ensure buffer is loaded
        self.load_buffer()

        # Return last n events
        events = list(self._buffer)
        return events[-n:] if len(events) > n else events

    def read_all(self) -> List[DebugEvent]:
        """
        Read all buffered events.

        Returns:
            List of all events in buffer, oldest first
        """
        self.load_buffer()
        return list(self._buffer)

    def filter_by_project(self, project: str) -> List[DebugEvent]:
        """
        Filter buffered events by project name.

        Args:
            project: Project name to filter by (case-insensitive)

        Returns:
            List of events matching the project
        """
        self.load_buffer()
        project_lower = project.lower()
        return [
            e for e in self._buffer
            if e.project.lower() == project_lower
        ]

    def filter_by_session(self, session_id: str) -> List[DebugEvent]:
        """
        Filter buffered events by session ID.

        Args:
            session_id: Session ID to filter by

        Returns:
            List of events matching the session
        """
        self.load_buffer()
        return [e for e in self._buffer if e.session_id == session_id]

    def filter_by_event_type(self, event_type: str) -> List[DebugEvent]:
        """
        Filter buffered events by event type.

        Args:
            event_type: Event type to filter by (e.g., 'citation', 'error')

        Returns:
            List of events matching the type
        """
        self.load_buffer()
        return [e for e in self._buffer if e.event == event_type]

    def filter_by_level(self, level: str) -> List[DebugEvent]:
        """
        Filter buffered events by log level.

        Args:
            level: Log level to filter by ('info', 'debug', 'trace', 'error')

        Returns:
            List of events matching the level
        """
        self.load_buffer()
        return [e for e in self._buffer if e.level == level]

    def filter(
        self,
        project: Optional[str] = None,
        session_id: Optional[str] = None,
        event_type: Optional[str] = None,
        level: Optional[str] = None,
    ) -> List[DebugEvent]:
        """
        Filter buffered events by multiple criteria.

        All specified criteria must match (AND logic).

        Args:
            project: Project name filter (case-insensitive)
            session_id: Session ID filter
            event_type: Event type filter
            level: Log level filter

        Returns:
            List of events matching all specified criteria
        """
        self.load_buffer()

        events = list(self._buffer)

        if project:
            project_lower = project.lower()
            events = [e for e in events if e.project.lower() == project_lower]

        if session_id:
            events = [e for e in events if e.session_id == session_id]

        if event_type:
            events = [e for e in events if e.event == event_type]

        if level:
            events = [e for e in events if e.level == level]

        return events

    def get_sessions(self) -> List[str]:
        """
        Get unique session IDs from buffered events.

        Returns:
            List of unique session IDs, most recent first
        """
        self.load_buffer()

        # Use dict to preserve order (Python 3.7+)
        seen: dict = {}
        for event in reversed(self._buffer):
            if event.session_id and event.session_id not in seen:
                seen[event.session_id] = True

        return list(seen.keys())

    def get_projects(self) -> List[str]:
        """
        Get unique project names from buffered events.

        Returns:
            List of unique project names, most frequent first
        """
        self.load_buffer()

        counts: dict = {}
        for event in self._buffer:
            if event.project:
                counts[event.project] = counts.get(event.project, 0) + 1

        # Sort by count descending
        return sorted(counts.keys(), key=lambda p: counts[p], reverse=True)

    def clear_buffer(self) -> None:
        """Clear the event buffer."""
        self._buffer.clear()

    def get_log_size_bytes(self) -> int:
        """
        Get the current log file size in bytes.

        Returns:
            File size in bytes, or 0 if file doesn't exist
        """
        if not self.log_path.exists():
            return 0
        try:
            return self.log_path.stat().st_size
        except OSError:
            return 0

    def iter_events(self) -> Iterator[DebugEvent]:
        """
        Iterate over all buffered events.

        Yields:
            DebugEvent objects in chronological order
        """
        self.load_buffer()
        yield from self._buffer
