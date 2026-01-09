#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Main TUI application for the claude-recall debug viewer.

Provides real-time monitoring of lessons system activity with:
- Live event log with color-coded event types
- System health metrics (hook timing, error counts)
- State overview (lessons, handoffs, decay)
- Session inspector for event correlation
"""

import asyncio
import os
import platform
import subprocess
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import List, Optional


@lru_cache(maxsize=1)
def _get_time_format() -> str:
    """Get the appropriate time format string based on system preferences.

    On macOS: checks AppleICUForce24HourTime preference
      - 1 = 24h format → %H:%M:%S
      - 0 or unset = 12h format → %r (with AM/PM)
    On other platforms: uses %X (locale-dependent)
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

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    OptionList,
    RichLog,
    Static,
    TabbedContent,
    TabPane,
)
from textual.widgets.option_list import Option
from textual import work

try:
    from textual_plotext import PlotextPlot
except ImportError:
    PlotextPlot = None  # type: ignore

try:
    from core.tui.log_reader import LogReader, format_event_line
    from core.tui.models import DebugEvent, HandoffSummary
    from core.tui.state_reader import StateReader
    from core.tui.stats import StatsAggregator
    from core.tui.transcript_reader import TranscriptReader, TranscriptSummary
except ImportError:
    from .log_reader import LogReader, format_event_line
    from .models import DebugEvent, HandoffSummary
    from .state_reader import StateReader
    from .stats import StatsAggregator
    from .transcript_reader import TranscriptReader, TranscriptSummary


# Textual Rich markup colors for event types
EVENT_COLORS = {
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

# Sparkline characters for mini charts (8 levels)
SPARKLINE_CHARS = "▁▂▃▄▅▆▇█"


def make_sparkline(values: List[float], width: int = 0) -> str:
    """
    Convert a list of numbers to a sparkline string.

    Uses 8 Unicode block characters to represent relative values.
    Empty or all-zero lists return empty string.

    Args:
        values: List of numeric values to visualize
        width: If > 0, truncate/pad to this width (uses most recent values)

    Returns:
        Sparkline string like "▁▂▃▄▅▆▇█"
    """
    if not values:
        return ""

    # If width specified, take most recent values
    if width > 0 and len(values) > width:
        values = values[-width:]

    min_val = min(values)
    max_val = max(values)
    val_range = max_val - min_val

    if val_range == 0:
        # All values the same - show middle height
        return SPARKLINE_CHARS[3] * len(values)

    result = []
    for v in values:
        # Normalize to 0-7 range for 8 characters
        normalized = (v - min_val) / val_range
        idx = min(7, int(normalized * 7.99))
        result.append(SPARKLINE_CHARS[idx])

    return "".join(result)


def _format_event_time(event: DebugEvent) -> str:
    """Format event timestamp in locale-aware format, converted to local timezone."""
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


def format_event_rich(event: DebugEvent) -> str:
    """
    Format an event as a Rich-markup string for Textual widgets.

    Args:
        event: The debug event to format

    Returns:
        Formatted string with Rich markup
    """
    time_part = _format_event_time(event)

    color = EVENT_COLORS.get(event.event, "")
    event_name = event.event[:18].ljust(18)
    project = (event.project[:15] if event.project else "").ljust(15)

    # Format event-specific details
    details = _format_event_details(event)

    if color:
        return f"[{color}][{time_part}] {event_name} {project} {details}[/{color}]"
    else:
        return f"[{time_part}] {event_name} {project} {details}"


def _format_event_details(event: DebugEvent) -> str:
    """Extract event-specific details for display."""
    raw = event.raw

    if event.event == "session_start":
        total = raw.get("total_lessons", 0)
        sys_count = raw.get("system_count", 0)
        proj_count = raw.get("project_count", 0)
        return f"{sys_count}S/{proj_count}L ({total} total)"

    elif event.event == "citation":
        lesson_id = raw.get("lesson_id", "?")
        uses_before = raw.get("uses_before", 0)
        uses_after = raw.get("uses_after", 0)
        promo = " PROMO!" if raw.get("promotion_ready") else ""
        return f"{lesson_id} ({uses_before}->{uses_after}){promo}"

    elif event.event == "decay_result":
        uses = raw.get("decayed_uses", 0)
        vel = raw.get("decayed_velocity", 0)
        return f"{uses} uses, {vel} velocity decayed"

    elif event.event == "error":
        op = raw.get("op", "")
        err = str(raw.get("err", ""))[:50]
        return f"{op}: {err}"

    elif event.event == "hook_end":
        hook = raw.get("hook", "")
        total_ms = raw.get("total_ms", 0)
        return f"{hook}: {total_ms:.0f}ms"

    elif event.event == "handoff_created":
        hid = raw.get("handoff_id", "")
        title = raw.get("title", "")[:30]
        return f"{hid} {title}"

    elif event.event == "handoff_completed":
        hid = raw.get("handoff_id", "")
        tried = raw.get("tried_count", 0)
        return f"{hid} ({tried} steps)"

    elif event.event == "lesson_added":
        lid = raw.get("lesson_id", "")
        level = raw.get("lesson_level", "")
        return f"{lid} ({level})"

    elif event.event == "hook_phase":
        hook = raw.get("hook", "")
        phase = raw.get("phase", "")
        ms = raw.get("ms", 0)
        return f"{hook}.{phase}: {ms:.0f}ms"

    else:
        # Generic: show first interesting key
        skip_keys = {"event", "level", "timestamp", "session_id", "pid", "project"}
        for k, v in raw.items():
            if k not in skip_keys:
                return f"{k}={v}"
        return ""


# Session tab formatting helpers
SESSION_ACTIVE_THRESHOLD_MINUTES = 5


def _format_session_time(dt: Optional[datetime]) -> str:
    """Format datetime in locale-aware format, converted to local timezone.

    Shows time only for today, date+time for other days.
    Uses system time format preference (12h vs 24h).
    """
    if dt is None:
        return "--:--"

    # Ensure dt is timezone-aware
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    # Convert to local timezone for display
    local_dt = dt.astimezone()
    local_now = datetime.now().astimezone()
    today = local_now.date()
    dt_date = local_dt.date()

    time_fmt = _get_time_format()
    if dt_date == today:
        # Today: show just time
        return local_dt.strftime(time_fmt)
    elif dt_date.year == today.year:
        # This year: show month/day + time (compact)
        return local_dt.strftime(f"%b %d {time_fmt}")
    else:
        # Different year: show full date + time
        return local_dt.strftime(f"%x {time_fmt}")


def _format_duration(ms: float) -> str:
    """Format duration in ms as human-readable string."""
    if ms <= 0:
        return "--"
    seconds = ms / 1000
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    if minutes < 60:
        return f"{minutes}m {secs}s"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}h {mins}m"


def _format_tokens(tokens: int) -> str:
    """Format token count with k suffix for thousands."""
    if tokens == 0:
        return "--"
    if tokens >= 1000:
        return f"{tokens / 1000:.1f}k"
    return str(tokens)


def _compute_session_status(last_event_time: Optional[datetime]) -> str:
    """Determine if session is Active or Idle based on last activity."""
    if last_event_time is None:
        return "Idle"

    now = datetime.now(timezone.utc)
    # Ensure last_event_time is timezone-aware
    if last_event_time.tzinfo is None:
        last_event_time = last_event_time.replace(tzinfo=timezone.utc)

    age_minutes = (now - last_event_time).total_seconds() / 60
    return "Active" if age_minutes < SESSION_ACTIVE_THRESHOLD_MINUTES else "Idle"


def _find_matching_handoff(
    session_date: date, handoffs: List[HandoffSummary]
) -> Optional[HandoffSummary]:
    """Find handoff that was active during the session.

    Matches handoffs where session_date is between handoff.created and handoff.updated.
    If multiple match, returns the most recently updated one.

    Args:
        session_date: The date of the session
        handoffs: List of handoffs to search

    Returns:
        Matching HandoffSummary, or None if no match
    """
    matches = []
    for hf in handoffs:
        # Parse dates (format: YYYY-MM-DD)
        try:
            if not hf.created or not hf.updated:
                continue
            created = date.fromisoformat(hf.created)
            updated = date.fromisoformat(hf.updated)
            if created <= session_date <= updated:
                matches.append((hf, updated))
        except ValueError:
            continue

    if not matches:
        return None

    # Return the most recently updated match
    return max(matches, key=lambda x: x[1])[0]


def _decode_project_path(session_path: Path) -> Optional[Path]:
    """Decode project path from Claude's encoded directory naming.

    Claude encodes project paths like:
    /Users/test/code/myproject -> -Users-test-code-myproject

    Args:
        session_path: Path to session JSONL file

    Returns:
        Decoded project path, or None if can't decode
    """
    # Get the project directory name (parent of the session file)
    project_dir_name = session_path.parent.name
    if not project_dir_name.startswith("-"):
        return None

    # Decode: replace - with / (but handle -- for . in paths)
    # First, protect double-dashes (which represent .)
    decoded = project_dir_name.replace("--", "\x00")
    # Then replace single dashes with /
    decoded = decoded.replace("-", "/")
    # Restore dots
    decoded = decoded.replace("\x00", "/.")

    # The decoded path should start with /
    if not decoded.startswith("/"):
        return None

    return Path(decoded)


class SessionDetailModal(ModalScreen):
    """Modal screen showing expanded session details.

    Displays full session information without truncation:
    - Session ID and project
    - Full topic (first user prompt)
    - Start and last activity times
    - Message count and token usage
    - Tool breakdown
    - Lesson citations
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
    ]

    def __init__(self, session_id: str, session_data: "TranscriptSummary") -> None:
        """Initialize with session data.

        Args:
            session_id: The session identifier
            session_data: TranscriptSummary containing session details
        """
        super().__init__()
        self.session_id = session_id
        self.session_data = session_data

    def compose(self) -> ComposeResult:
        """Compose the modal content."""
        summary = self.session_data

        with Vertical(id="session-detail-modal"):
            yield Static("[bold]Session Details[/bold]", classes="modal-title")

            with VerticalScroll(id="session-detail-content"):
                # Session ID
                yield Static(f"[bold]Session ID:[/bold] {self.session_id}")

                # Project
                yield Static(f"[bold]Project:[/bold] {summary.project}")

                # Full topic (no truncation)
                topic = summary.first_prompt.replace("\n", " ")
                yield Static(f"[bold]Topic:[/bold] {topic}")

                # Times
                yield Static(
                    f"[bold]Started:[/bold] {_format_session_time(summary.start_time)}"
                )
                yield Static(
                    f"[bold]Last Activity:[/bold] {_format_session_time(summary.last_activity)}"
                )

                # Message count
                yield Static(f"[bold]Messages:[/bold] {summary.message_count}")

                # Token usage with breakdown
                yield Static(f"[bold]Tokens:[/bold] {_format_tokens(summary.total_tokens)} total")
                yield Static(
                    f"  Input: {_format_tokens(summary.input_tokens)} | "
                    f"Output: {_format_tokens(summary.output_tokens)}"
                )
                if summary.cache_read_tokens > 0 or summary.cache_creation_tokens > 0:
                    yield Static(
                        f"  Cache: {_format_tokens(summary.cache_read_tokens)} read | "
                        f"{_format_tokens(summary.cache_creation_tokens)} created"
                    )

                # Tool breakdown
                if summary.tool_breakdown:
                    tool_parts = [
                        f"{name}({count})"
                        for name, count in sorted(
                            summary.tool_breakdown.items(), key=lambda x: -x[1]
                        )
                    ]
                    yield Static(f"[bold]Tools:[/bold] {' '.join(tool_parts)}")
                else:
                    yield Static("[bold]Tools:[/bold] None")

                # Lesson citations
                if summary.lesson_citations:
                    citations_str = ", ".join(summary.lesson_citations)
                    yield Static(f"[bold]Lessons Cited:[/bold] {citations_str}")

            yield Button("Close", id="close-modal", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press events."""
        if event.button.id == "close-modal":
            self.dismiss()


# Valid options for handoff actions (imported from core.handoffs constants)
VALID_STATUSES = ["not_started", "in_progress", "blocked", "ready_for_review", "completed"]
VALID_PHASES = ["research", "planning", "implementing", "review"]
VALID_AGENTS = ["explore", "general-purpose", "plan", "review", "user"]


class HandoffActionScreen(ModalScreen[str]):
    """Popup for handoff actions.

    Shows actions available for a selected handoff:
    - Set status
    - Set phase
    - Set agent
    - Complete
    - Archive

    Supports both arrow key navigation with Enter and direct key bindings.
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Cancel"),
        Binding("s", "set_status", "Status"),
        Binding("p", "set_phase", "Phase"),
        Binding("a", "set_agent", "Agent"),
        Binding("c", "complete", "Complete"),
        Binding("x", "archive", "Archive"),
    ]

    def __init__(self, handoff_id: str, handoff_title: str) -> None:
        """Initialize with handoff data.

        Args:
            handoff_id: The handoff ID (e.g., 'hf-abc1234')
            handoff_title: The handoff title
        """
        super().__init__()
        self.handoff_id = handoff_id
        self.handoff_title = handoff_title

    def compose(self) -> ComposeResult:
        """Compose the modal content."""
        with Vertical(id="handoff-action-modal"):
            yield Static(
                f"[bold]{self.handoff_id}[/bold]: {self.handoff_title}",
                classes="modal-title",
            )
            yield OptionList(
                Option("[s] Set status...", id="status"),
                Option("[p] Set phase...", id="phase"),
                Option("[a] Set agent...", id="agent"),
                Option("[c] Complete", id="complete"),
                Option("[x] Archive", id="archive"),
                id="action-options",
            )
            yield Static("[dim][Esc] Cancel[/dim]")

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        """Handle option selection from OptionList."""
        option_id = str(event.option.id)
        if option_id == "status":
            self.action_set_status()
        elif option_id == "phase":
            self.action_set_phase()
        elif option_id == "agent":
            self.action_set_agent()
        elif option_id == "complete":
            self.action_complete()
        elif option_id == "archive":
            self.action_archive()

    def action_set_status(self) -> None:
        """Open status selection sub-menu."""
        self.app.push_screen(
            StatusSelectScreen(self.handoff_id, self.handoff_title),
            callback=self._on_submenu_result,
        )

    def action_set_phase(self) -> None:
        """Open phase selection sub-menu."""
        self.app.push_screen(
            PhaseSelectScreen(self.handoff_id, self.handoff_title),
            callback=self._on_submenu_result,
        )

    def action_set_agent(self) -> None:
        """Open agent selection sub-menu."""
        self.app.push_screen(
            AgentSelectScreen(self.handoff_id, self.handoff_title),
            callback=self._on_submenu_result,
        )

    def action_complete(self) -> None:
        """Complete the handoff."""
        self.dismiss("complete")

    def action_archive(self) -> None:
        """Archive the handoff."""
        self.dismiss("archive")

    def _on_submenu_result(self, result: str) -> None:
        """Handle result from sub-menu. Dismiss if action was taken."""
        if result:
            self.dismiss(result)


class StatusSelectScreen(ModalScreen[str]):
    """Sub-menu for selecting handoff status.

    Supports both arrow key navigation with Enter and direct number key bindings.
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Cancel"),
        Binding("1", "select_1", "not_started"),
        Binding("2", "select_2", "in_progress"),
        Binding("3", "select_3", "blocked"),
        Binding("4", "select_4", "ready_for_review"),
        Binding("5", "select_5", "completed"),
    ]

    def __init__(self, handoff_id: str, handoff_title: str) -> None:
        super().__init__()
        self.handoff_id = handoff_id
        self.handoff_title = handoff_title

    def compose(self) -> ComposeResult:
        with Vertical(id="status-select-modal"):
            yield Static("[bold]Select Status[/bold]", classes="modal-title")
            yield OptionList(
                Option("[1] not_started", id="not_started"),
                Option("[2] in_progress", id="in_progress"),
                Option("[3] blocked", id="blocked"),
                Option("[4] ready_for_review", id="ready_for_review"),
                Option("[5] completed", id="completed"),
                id="status-options",
            )
            yield Static("[dim][Esc] Cancel[/dim]")

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        """Handle option selection from OptionList."""
        status = str(event.option.id)
        self._select_status(status)

    def action_select_1(self) -> None:
        self._select_status("not_started")

    def action_select_2(self) -> None:
        self._select_status("in_progress")

    def action_select_3(self) -> None:
        self._select_status("blocked")

    def action_select_4(self) -> None:
        self._select_status("ready_for_review")

    def action_select_5(self) -> None:
        self._select_status("completed")

    def _select_status(self, status: str) -> None:
        """Apply status change and dismiss."""
        try:
            from core.lessons import LessonsManager

            mgr = LessonsManager()
            mgr.handoff_update_status(self.handoff_id, status)
            self.app.notify(f"Status updated to: {status}")
            self.dismiss(f"status:{status}")
        except Exception as e:
            self.app.notify(f"Error: {e}", severity="error")
            self.dismiss("")


class PhaseSelectScreen(ModalScreen[str]):
    """Sub-menu for selecting handoff phase.

    Supports both arrow key navigation with Enter and direct number key bindings.
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Cancel"),
        Binding("1", "select_1", "research"),
        Binding("2", "select_2", "planning"),
        Binding("3", "select_3", "implementing"),
        Binding("4", "select_4", "review"),
    ]

    def __init__(self, handoff_id: str, handoff_title: str) -> None:
        super().__init__()
        self.handoff_id = handoff_id
        self.handoff_title = handoff_title

    def compose(self) -> ComposeResult:
        with Vertical(id="phase-select-modal"):
            yield Static("[bold]Select Phase[/bold]", classes="modal-title")
            yield OptionList(
                Option("[1] research", id="research"),
                Option("[2] planning", id="planning"),
                Option("[3] implementing", id="implementing"),
                Option("[4] review", id="review"),
                id="phase-options",
            )
            yield Static("[dim][Esc] Cancel[/dim]")

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        """Handle option selection from OptionList."""
        phase = str(event.option.id)
        self._select_phase(phase)

    def action_select_1(self) -> None:
        self._select_phase("research")

    def action_select_2(self) -> None:
        self._select_phase("planning")

    def action_select_3(self) -> None:
        self._select_phase("implementing")

    def action_select_4(self) -> None:
        self._select_phase("review")

    def _select_phase(self, phase: str) -> None:
        """Apply phase change and dismiss."""
        try:
            from core.lessons import LessonsManager

            mgr = LessonsManager()
            mgr.handoff_update_phase(self.handoff_id, phase)
            self.app.notify(f"Phase updated to: {phase}")
            self.dismiss(f"phase:{phase}")
        except Exception as e:
            self.app.notify(f"Error: {e}", severity="error")
            self.dismiss("")


class AgentSelectScreen(ModalScreen[str]):
    """Sub-menu for selecting handoff agent.

    Supports both arrow key navigation with Enter and direct number key bindings.
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Cancel"),
        Binding("1", "select_1", "explore"),
        Binding("2", "select_2", "general-purpose"),
        Binding("3", "select_3", "plan"),
        Binding("4", "select_4", "review"),
        Binding("5", "select_5", "user"),
    ]

    def __init__(self, handoff_id: str, handoff_title: str) -> None:
        super().__init__()
        self.handoff_id = handoff_id
        self.handoff_title = handoff_title

    def compose(self) -> ComposeResult:
        with Vertical(id="agent-select-modal"):
            yield Static("[bold]Select Agent[/bold]", classes="modal-title")
            yield OptionList(
                Option("[1] explore", id="explore"),
                Option("[2] general-purpose", id="general-purpose"),
                Option("[3] plan", id="plan"),
                Option("[4] review", id="review"),
                Option("[5] user", id="user"),
                id="agent-options",
            )
            yield Static("[dim][Esc] Cancel[/dim]")

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        """Handle option selection from OptionList."""
        agent = str(event.option.id)
        self._select_agent(agent)

    def action_select_1(self) -> None:
        self._select_agent("explore")

    def action_select_2(self) -> None:
        self._select_agent("general-purpose")

    def action_select_3(self) -> None:
        self._select_agent("plan")

    def action_select_4(self) -> None:
        self._select_agent("review")

    def action_select_5(self) -> None:
        self._select_agent("user")

    def _select_agent(self, agent: str) -> None:
        """Apply agent change and dismiss."""
        try:
            from core.lessons import LessonsManager

            mgr = LessonsManager()
            mgr.handoff_update_agent(self.handoff_id, agent)
            self.app.notify(f"Agent updated to: {agent}")
            self.dismiss(f"agent:{agent}")
        except Exception as e:
            self.app.notify(f"Error: {e}", severity="error")
            self.dismiss("")


class RecallMonitorApp(App):
    """
    Main Textual application for claude-recall monitoring.

    Displays real-time debug events, system health, state overview,
    and session inspection in a tabbed interface.
    """

    TITLE = "Claude Recall Monitor"
    CSS_PATH = "styles/app.tcss"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("f1", "switch_tab('live')", "Live"),
        Binding("f2", "switch_tab('health')", "Health"),
        Binding("f3", "switch_tab('state')", "State"),
        Binding("f4", "switch_tab('session')", "Session"),
        Binding("f5", "switch_tab('charts')", "Charts"),
        Binding("f6", "switch_tab('handoffs')", "Handoffs"),
        Binding("p", "toggle_pause", "Pause"),
        Binding("r", "refresh", "Refresh"),
        Binding("a", "toggle_all", "All"),
        Binding("e", "expand_session", "Expand"),
        Binding("c", "toggle_completed", "Completed"),
        Binding("w", "toggle_system_sessions", "System", show=True),
        Binding("t", "toggle_timeline", "Timeline", show=True),
        Binding("ctrl+c", "copy_session", "Copy", priority=True),
        Binding("h", "goto_handoff", "Handoff", show=False),
    ]

    def __init__(
        self,
        project_filter: Optional[str] = None,
        log_path: Optional[Path] = None,
    ) -> None:
        """
        Initialize the app.

        Args:
            project_filter: Filter events to specific project (optional)
            log_path: Override log file path (optional)
        """
        super().__init__()
        self.project_filter = project_filter
        self.log_reader = LogReader(log_path=log_path)
        self.state_reader = StateReader()
        self.stats = StatsAggregator(self.log_reader, self.state_reader)
        self._paused = False
        self._last_event_count = 0
        self._refresh_timer = None
        # Session tab state
        self._session_data: dict = {}  # Raw data by session_id for sorting
        self._session_sort_column: Optional[str] = None
        self._session_sort_reverse: bool = False
        # Transcript reader for session tab
        self.transcript_reader = TranscriptReader()
        self._current_project = os.environ.get("PROJECT_DIR", os.getcwd())
        # Unified toggle: False = current project, non-empty sessions
        #                 True = all projects, all sessions (including empty)
        self._show_all: bool = False
        # Handoffs tab state
        self._handoff_data: dict = {}  # Raw data by handoff_id
        self._handoff_sort_column: Optional[str] = None
        self._handoff_sort_reverse: bool = False
        self._show_completed_handoffs: bool = False
        self._current_handoff_id: Optional[str] = None  # Track currently displayed handoff
        self._enter_confirmed_handoff_id: Optional[str] = None  # Track Enter-confirmed selection for double-action
        self._handoff_filter: str = ""  # Current filter text
        self._handoff_total_count: int = 0  # Total handoffs before filtering
        # Session tab refresh state
        self._current_session_id: Optional[str] = None  # Track currently displayed session
        self._user_selected_session_id: Optional[str] = None  # Track user's row selection
        # Handoff tab refresh state
        self._user_selected_handoff_id: Optional[str] = None  # Track user's handoff row selection
        # System sessions toggle - False = hide System/Warmup, True = show all
        self._show_system_sessions: bool = False
        # Timeline view toggle - False = list view, True = timeline view
        self._timeline_view: bool = False

    def compose(self) -> ComposeResult:
        """Compose the app layout."""
        yield Header()

        with TabbedContent(initial="live"):
            with TabPane("Live Activity", id="live"):
                yield RichLog(id="event-log", highlight=True, markup=True)

            with TabPane("Health", id="health"):
                yield Vertical(
                    Static("Loading health stats...", id="health-stats"),
                    id="health-panel",
                )

            with TabPane("State", id="state"):
                yield Vertical(
                    Static("Loading state overview...", id="state-overview"),
                    id="state-panel",
                )

            with TabPane("Session", id="session"):
                yield Vertical(
                    Static("Sessions", classes="section-title"),
                    DataTable(id="session-list"),
                    Static("Session Events", classes="section-title"),
                    RichLog(id="session-events", highlight=True, markup=True, wrap=True, auto_scroll=False),
                )

            with TabPane("Handoffs", id="handoffs"):
                yield Vertical(
                    Static("Handoffs", classes="section-title"),
                    Horizontal(
                        Static("Filter: ", classes="filter-label"),
                        Input(id="handoff-filter", placeholder="text, status:x, phase:x, agent:x"),
                        Button("X", id="clear-filter", variant="error"),
                        classes="filter-row",
                    ),
                    Static("", id="handoff-filter-status"),
                    DataTable(id="handoff-list"),
                    RichLog(id="handoff-timeline", highlight=True, markup=True, wrap=True, auto_scroll=False),
                    Static("Handoff Details", classes="section-title"),
                    RichLog(id="handoff-details", highlight=True, markup=True, wrap=True, auto_scroll=False),
                )

            with TabPane("Charts", id="charts"):
                yield Vertical(
                    Static("Loading charts...", id="sparklines-panel"),
                    Horizontal(
                        PlotextPlot(id="activity-chart") if PlotextPlot else Static("[dim]plotext not available[/dim]"),
                        PlotextPlot(id="timing-chart") if PlotextPlot else Static("[dim]plotext not available[/dim]"),
                        id="charts-row",
                    ),
                    id="charts-panel",
                )

        yield Footer()

    def on_mount(self) -> None:
        """Initialize on app mount."""
        # Load initial data with error handling
        try:
            self._load_events()
        except Exception as e:
            self.notify(f"Error loading events: {e}", severity="error")

        try:
            self._update_health()
        except Exception as e:
            self.notify(f"Error updating health: {e}", severity="error")

        try:
            self._update_state()
        except Exception as e:
            self.notify(f"Error updating state: {e}", severity="error")

        try:
            self._setup_session_list()
        except Exception as e:
            self.notify(f"Error setting up sessions: {e}", severity="error")

        try:
            self._setup_handoff_list()
        except Exception as e:
            self.notify(f"Error setting up handoffs: {e}", severity="error")

        try:
            self._update_charts()
        except Exception as e:
            self.notify(f"Error updating charts: {e}", severity="error")

        self._update_subtitle()

        # Start auto-refresh timer (2 seconds) - must use sync callback
        self._refresh_timer = self.set_interval(2.0, self._on_refresh_timer)

    def _load_events(self) -> None:
        """Load and display events in the log."""
        event_log = self.query_one("#event-log", RichLog)

        # Get events (filtered if needed)
        if self.project_filter:
            events = self.log_reader.filter_by_project(self.project_filter)
        else:
            events = self.log_reader.read_recent(100)

        # Clear and repopulate
        event_log.clear()
        for event in events:
            event_log.write(format_event_rich(event))

        self._last_event_count = self.log_reader.buffer_size

    def _on_refresh_timer(self) -> None:
        """Sync timer callback - updates subtitle and triggers async refresh."""
        self._update_subtitle()
        if not self._paused:
            self._refresh_events()
            self._refresh_session_list()
            self._refresh_handoff_list()

    @work(exclusive=True)
    async def _refresh_events(self) -> None:
        """Async worker to check for and display new events."""
        new_count = await asyncio.to_thread(self.log_reader.load_buffer)
        if new_count > 0:
            self._append_new_events(new_count)

    def _append_new_events(self, count: int) -> None:
        """Append only the new events (last 'count' from buffer)."""
        event_log = self.query_one("#event-log", RichLog)

        # Access buffer directly - don't use read_recent() which calls load_buffer() again
        buffer = list(self.log_reader._buffer)
        events = buffer[-count:] if count <= len(buffer) else buffer

        # Filter if needed
        if self.project_filter:
            events = [e for e in events if e.project.lower() == self.project_filter.lower()]

        for event in events:
            event_log.write(format_event_rich(event))

    def _update_health(self) -> None:
        """Update health statistics display."""
        health_widget = self.query_one("#health-stats", Static)
        stats = self.stats.compute()

        # Format health display
        lines = []

        # Health status header
        if stats.errors_today == 0 and stats.avg_hook_ms < 100:
            status = "[green]OK[/green]"
        elif stats.errors_today > 0 or stats.avg_hook_ms > 200:
            status = "[red]WARNING[/red]"
        else:
            status = "[yellow]DEGRADED[/yellow]"

        lines.append(f"[bold]System Health:[/bold] {status}")
        lines.append("")

        # Today's activity
        lines.append("[bold]Today's Activity[/bold]")
        lines.append(f"  Sessions: {stats.sessions_today}")
        lines.append(f"  Citations: {stats.citations_today}")
        errors_color = "red" if stats.errors_today > 0 else "green"
        lines.append(f"  Errors: [{errors_color}]{stats.errors_today}[/{errors_color}]")
        lines.append("")

        # Hook timing
        lines.append("[bold]Hook Timing[/bold]")
        avg_color = "green" if stats.avg_hook_ms < 100 else "yellow" if stats.avg_hook_ms < 200 else "red"
        lines.append(f"  Average: [{avg_color}]{stats.avg_hook_ms:.1f}ms[/{avg_color}]")
        p95_color = "green" if stats.p95_hook_ms < 150 else "yellow" if stats.p95_hook_ms < 300 else "red"
        lines.append(f"  P95: [{p95_color}]{stats.p95_hook_ms:.1f}ms[/{p95_color}]")
        lines.append(f"  Max: {stats.max_hook_ms:.1f}ms")
        lines.append("")

        # Per-hook breakdown - pass pre-computed stats to avoid redundant compute()
        timing_summary = self.stats.get_timing_summary(stats)
        if timing_summary:
            lines.append("[bold]Hook Breakdown[/bold]")
            for hook, timing in sorted(timing_summary.items()):
                lines.append(f"  {hook}: avg={timing['avg_ms']:.0f}ms p95={timing['p95_ms']:.0f}ms (n={timing['count']})")
            lines.append("")

        # Log info
        lines.append("[bold]Log File[/bold]")
        lines.append(f"  Size: {stats.log_size_mb:.2f} MB")
        lines.append(f"  Buffered events: {stats.log_line_count}")
        lines.append("")

        # Event type breakdown
        if stats.events_by_type:
            lines.append("[bold]Event Types[/bold]")
            for etype, count in sorted(stats.events_by_type.items(), key=lambda x: -x[1])[:10]:
                lines.append(f"  {etype}: {count}")
            lines.append("")

        # Project breakdown
        if stats.events_by_project:
            lines.append("[bold]Projects[/bold]")
            for proj, count in sorted(stats.events_by_project.items(), key=lambda x: -x[1])[:5]:
                lines.append(f"  {proj}: {count}")

        health_widget.update("\n".join(lines))

    def _update_state(self) -> None:
        """Update state overview display."""
        state_widget = self.query_one("#state-overview", Static)

        # Get available width for truncation (fallback to 80 if not yet sized)
        available_width = state_widget.size.width if state_widget.size.width > 0 else 80

        def truncate(text: str, max_len: int) -> str:
            """Truncate text with ellipsis if too long."""
            if len(text) <= max_len:
                return text
            return text[:max_len - 3] + "..." if max_len > 3 else text[:max_len]

        lines = []

        # Lesson counts
        try:
            lesson_counts = self.state_reader.get_lesson_counts()
            lines.append("[bold]Lessons[/bold]")
            lines.append(f"  System: {lesson_counts.get('system', 0)}")
            lines.append(f"  Project: {lesson_counts.get('project', 0)}")
            lines.append(f"  Total: {lesson_counts.get('total', 0)}")
            lines.append("")

            # Top lessons by usage
            all_lessons = self.state_reader.get_lessons()
            if all_lessons:
                top_lessons = sorted(all_lessons, key=lambda l: l.uses, reverse=True)[:5]
                lines.append("[bold]Top Lessons (by uses)[/bold]")
                for lesson in top_lessons:
                    level_tag = "S" if lesson.is_system else "L"
                    # "  [L001] " = 9 chars prefix, " (X uses, vel=Y.Z)" = ~25 chars suffix
                    title_width = max(15, available_width - 34)
                    lines.append(f"  [{lesson.id}] {truncate(lesson.title, title_width)} ({lesson.uses} uses, vel={lesson.velocity:.1f})")
                lines.append("")

        except Exception as e:
            lines.append(f"[red]Error loading lessons: {e}[/red]")
            lines.append("")

        # Handoffs
        try:
            handoffs = self.state_reader.get_handoffs()
            active_handoffs = [h for h in handoffs if h.is_active]
            stats = self.state_reader.get_handoff_stats(handoffs)

            lines.append("[bold]Handoffs[/bold]")
            lines.append(
                f"  Total: {stats['total_count']} | "
                f"Active: {stats['active_count']} | "
                f"Blocked: {stats['blocked_count']}"
            )

            # Age statistics
            if stats["total_count"] > 0:
                age_stats = stats["age_stats"]
                lines.append(
                    f"  Age: {age_stats['min_age_days']}d - {age_stats['max_age_days']}d "
                    f"(avg: {age_stats['avg_age_days']:.1f}d) | "
                    f"Stale: {stats['stale_count']}"
                )
            lines.append("")

            if active_handoffs:
                lines.append("[bold]Active Handoffs[/bold]")
                for h in active_handoffs:
                    status_color = "red" if h.is_blocked else "yellow" if h.status == "ready_for_review" else "green"
                    # "  [hf-xxxxxxx] " = 17 chars prefix (escaped brackets)
                    title_width = max(20, available_width - 17)
                    # Escape brackets to prevent Rich markup interpretation
                    lines.append(f"  \\[{h.id}] {truncate(h.title, title_width)}")
                    lines.append(f"    [{status_color}]{h.status}[/{status_color}] | {h.phase}")
                lines.append("")

        except Exception as e:
            lines.append(f"[red]Error loading handoffs: {e}[/red]")
            lines.append("")

        # Decay info
        try:
            decay_info = self.state_reader.get_decay_info()
            lines.append("[bold]Decay State[/bold]")
            if decay_info.decay_state_exists:
                lines.append(f"  Last decay: {decay_info.last_decay_date or 'unknown'}")
                lines.append(f"  Sessions since: {decay_info.sessions_since_decay}")
            else:
                lines.append("  [dim]No decay state file[/dim]")

        except Exception as e:
            lines.append(f"[red]Error loading decay info: {e}[/red]")

        state_widget.update("\n".join(lines))

    def _is_system_session(self, summary: TranscriptSummary) -> bool:
        """Check if a session is a system/warmup session.

        Args:
            summary: The session summary to check

        Returns:
            True if the session origin is 'System' or 'Warmup', False otherwise
        """
        return summary.origin in ("System", "Warmup")

    def _should_show_session(self, summary: TranscriptSummary) -> bool:
        """Determine if a session should be shown based on current filter settings.

        Args:
            summary: The session to check

        Returns:
            True if the session should be displayed, False otherwise
        """
        # Always show non-system sessions
        if not self._is_system_session(summary):
            return True

        # Show system sessions if toggle is on
        return self._show_system_sessions

    def _get_session_counts(self, sessions: List[TranscriptSummary]) -> tuple:
        """Calculate counts for user and system sessions.

        Args:
            sessions: List of all sessions

        Returns:
            Tuple of (user_count, system_count)
        """
        user_count = 0
        system_count = 0

        for session in sessions:
            if self._is_system_session(session):
                system_count += 1
            else:
                user_count += 1

        return user_count, system_count

    def _update_session_title(self, sessions: List[TranscriptSummary]) -> None:
        """Update the sessions section title with count indicator.

        Args:
            sessions: List of all sessions
        """
        try:
            # Find the first Static widget with "Sessions" in the session pane
            session_pane = self.query_one("#session")
            title_widget = session_pane.query("Static.section-title").first()

            user_count, system_count = self._get_session_counts(sessions)

            if system_count > 0 and not self._show_system_sessions:
                title_widget.update(
                    f"Sessions ({user_count} user, {system_count} system hidden)"
                )
            else:
                title_widget.update(f"Sessions ({user_count + system_count})")
        except Exception:
            # If we can't find or update the title, silently ignore
            pass

    def _setup_session_list(self) -> None:
        """Initialize the session list DataTable with sortable columns."""
        session_table = self.query_one("#session-list", DataTable)

        # Enable row cursor for RowHighlighted events on arrow key navigation
        session_table.cursor_type = "row"

        # Add columns with keys for sorting
        # Project column only shown in all-projects mode
        session_table.add_column("Session ID", key="session_id")
        if self._show_all:
            session_table.add_column("Project", key="project")
        session_table.add_column("Origin", key="origin")
        session_table.add_column("Topic", key="topic")
        session_table.add_column("Started", key="started")
        session_table.add_column("Last", key="last_activity")
        session_table.add_column("Tools", key="tools")
        session_table.add_column("Tokens", key="tokens")
        session_table.add_column("Msgs", key="messages")

        # Clear any existing session data
        self._session_data.clear()

        # Get sessions from TranscriptReader
        # _show_all toggles: all projects + all sessions (including empty) vs current project + non-empty
        if self._show_all:
            sessions = self.transcript_reader.list_all_sessions(limit=50, include_empty=True)
        else:
            sessions = self.transcript_reader.list_sessions(
                self._current_project, limit=50, include_empty=False
            )

        # Update the section title with counts
        self._update_session_title(sessions)

        for summary in sessions:
            # Skip system sessions unless toggle is on
            if not self._should_show_session(summary):
                continue

            session_id = summary.session_id
            self._session_data[session_id] = summary

            self._populate_session_row(session_table, session_id, summary)

    def _populate_session_row(
        self, session_table: DataTable, session_id: str, summary: TranscriptSummary
    ) -> None:
        """Add a row to the session table with formatted values.

        Args:
            session_table: The DataTable widget to add the row to
            session_id: The session identifier (used as row key)
            summary: TranscriptSummary containing session data
        """
        # Format display values
        topic = summary.first_prompt[:40] + "..." if len(summary.first_prompt) > 40 else summary.first_prompt
        topic = topic.replace("\n", " ")  # Remove newlines for display
        total_tools = sum(summary.tool_breakdown.values())

        # Build row data - Project column only in all-projects mode
        row_data = [session_id[:12] + "..." if len(session_id) > 15 else session_id]
        if self._show_all:
            row_data.append(summary.project[:12])
        row_data.extend([
            summary.origin,
            topic,
            _format_session_time(summary.start_time),
            _format_session_time(summary.last_activity),
            str(total_tools),
            _format_tokens(summary.total_tokens),
            str(summary.message_count),
        ])

        session_table.add_row(*row_data, key=session_id)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        """Handle row highlight (arrow key navigation) in data tables."""
        if event.row_key is None:
            return

        row_key = event.row_key.value
        if not row_key:
            return

        if event.data_table.id == "session-list":
            # Track user's selection for persistence during refresh
            self._user_selected_session_id = row_key
            self._show_session_events(row_key)
        elif event.data_table.id == "handoff-list":
            # Track user's selection for persistence during refresh
            self._user_selected_handoff_id = row_key
            self._show_handoff_details(row_key)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle row selection (Enter/Space) in data tables.

        Uses double-action behavior for handoffs:
        - First Enter/click on a NEW row: selects the row, shows details
        - Second Enter/click on the SAME row: opens the action popup

        This prevents accidental popup opens when navigating.
        """
        if event.row_key is None:
            return

        row_key = event.row_key.value
        if not row_key:
            return

        # Only handle for handoff-list - open action menu with double-action
        if event.data_table.id == "handoff-list":
            handoff = self._handoff_data.get(row_key)
            if not handoff:
                return

            # Only show popup if this row was ALREADY selected (double-action)
            if row_key == self._current_handoff_id:
                # Second Enter/click - open popup
                self.push_screen(
                    HandoffActionScreen(handoff.id, handoff.title),
                    callback=self._on_handoff_action_result,
                )
            else:
                # First Enter/click - just select and show details
                # (clicking bypasses row_highlighted, so handle it here too)
                self._current_handoff_id = row_key
                self._user_selected_handoff_id = row_key
                self._show_handoff_details(row_key)

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle input changes in filter fields."""
        if event.input.id == "handoff-filter":
            self._handoff_filter = event.value
            self._refresh_handoff_list()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press events."""
        if event.button.id == "clear-filter":
            try:
                filter_input = self.query_one("#handoff-filter", Input)
                filter_input.value = ""
                self._handoff_filter = ""
                self._refresh_handoff_list()
            except Exception:
                pass

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in input fields - move focus to table."""
        if event.input.id == "handoff-filter":
            try:
                handoff_table = self.query_one("#handoff-list", DataTable)
                handoff_table.focus()
            except Exception:
                pass

    def on_key(self, event) -> None:
        """Handle key events for clearing filter with Escape."""
        if event.key == "escape":
            try:
                filter_input = self.query_one("#handoff-filter", Input)
                if filter_input.has_focus and self._handoff_filter:
                    filter_input.value = ""
                    self._handoff_filter = ""
                    self._refresh_handoff_list()
                    event.prevent_default()
                    event.stop()
            except Exception:
                pass

    def _on_handoff_action_result(self, result: str) -> None:
        """Handle result from HandoffActionScreen.

        Args:
            result: Action result string (e.g., 'complete', 'archive', 'status:blocked')
        """
        if not result:
            return

        handoff_id = self._current_handoff_id
        if not handoff_id:
            self.notify("No handoff selected", severity="error")
            return

        if result == "complete":
            # Complete the handoff
            try:
                from core.lessons import LessonsManager

                mgr = LessonsManager()
                mgr.handoff_complete(handoff_id)
                self.notify(f"Handoff {handoff_id} completed")
            except Exception as e:
                self.notify(f"Error completing handoff: {e}", severity="error")
                return
        elif result == "archive":
            # Archive the handoff
            try:
                from core.lessons import LessonsManager

                mgr = LessonsManager()
                mgr.handoff_archive(handoff_id)
                self.notify(f"Handoff {handoff_id} archived")
            except Exception as e:
                self.notify(f"Error archiving handoff: {e}", severity="error")
                return

        # Refresh the handoff list after any action
        self._refresh_handoff_list()

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        """Handle column header click to sort the session table."""
        if event.data_table.id != "session-list":
            return

        if event.column_key is None:
            return

        column_key = event.column_key.value

        # Toggle sort direction if clicking same column
        if column_key == self._session_sort_column:
            self._session_sort_reverse = not self._session_sort_reverse
        else:
            self._session_sort_column = column_key
            self._session_sort_reverse = False

        self._sort_session_table(column_key, self._session_sort_reverse)

    def _sort_session_table(self, column_key: str, reverse: bool) -> None:
        """Sort the session table by the given column."""
        session_table = self.query_one("#session-list", DataTable)

        # Define sort key based on column (using TranscriptSummary)
        def get_sort_value(session_id: str):
            summary = self._session_data.get(session_id)
            if not isinstance(summary, TranscriptSummary):
                return ""
            if column_key == "session_id":
                return session_id
            elif column_key == "project":
                return summary.project
            elif column_key == "origin":
                return summary.origin
            elif column_key == "topic":
                return summary.first_prompt
            elif column_key == "started":
                return summary.start_time
            elif column_key == "last_activity":
                return summary.last_activity
            elif column_key == "tools":
                return sum(summary.tool_breakdown.values())
            elif column_key == "tokens":
                return summary.total_tokens
            elif column_key == "messages":
                return summary.message_count
            return ""

        # Get sorted session IDs
        sorted_sessions = sorted(
            self._session_data.keys(),
            key=get_sort_value,
            reverse=reverse,
        )

        # Clear and repopulate table in sorted order
        session_table.clear()
        for session_id in sorted_sessions:
            summary = self._session_data[session_id]
            if not isinstance(summary, TranscriptSummary):
                continue

            self._populate_session_row(session_table, session_id, summary)

    def _show_session_events(self, session_id: str) -> None:
        """Display transcript timeline for a selected session."""
        session_log = self.query_one("#session-events", RichLog)

        # Check if we're viewing the same session (to avoid scroll reset)
        is_same_session = self._current_session_id == session_id

        session_log.clear()

        # Update tracking
        self._current_session_id = session_id

        # Get the summary from cached data
        summary = self._session_data.get(session_id)
        if summary is None or not isinstance(summary, TranscriptSummary):
            session_log.write("[dim]No transcript data available[/dim]")
            return

        # Load full transcript
        messages = self.transcript_reader.load_session(summary.path)
        if not messages:
            session_log.write("[dim]Empty transcript[/dim]")
            return

        # Header: Topic (full first prompt)
        topic = summary.first_prompt.replace("\n", " ")
        session_log.write(f"[bold]Topic:[/bold] {topic}")
        session_log.write("")

        # Handoff correlation - find handoffs active during this session
        project_root = _decode_project_path(summary.path)
        if project_root and summary.start_time:
            handoffs = self.state_reader.get_handoffs(project_root)
            if handoffs:
                session_date = summary.start_time.date()
                matching_handoff = _find_matching_handoff(session_date, handoffs)
                if matching_handoff:
                    session_log.write(
                        f"[bold]Handoff:[/bold] {matching_handoff.id} ({matching_handoff.phase})"
                    )
                    session_log.write("")

        # Tool breakdown line
        if summary.tool_breakdown:
            tool_parts = [f"{name}({count})" for name, count in sorted(summary.tool_breakdown.items(), key=lambda x: -x[1])]
            session_log.write(f"[bold]Tools:[/bold] {' '.join(tool_parts)}")
            session_log.write("")

        # Lesson citations if any
        if summary.lesson_citations:
            citations_str = ", ".join(summary.lesson_citations)
            session_log.write(f"[bold]Lessons cited:[/bold] {citations_str}")
            session_log.write("")

        # Separator
        session_log.write("[dim]" + "-" * 60 + "[/dim]")
        session_log.write("")

        # Chronological messages with timestamps
        time_fmt = _get_time_format()
        for msg in messages:
            # Convert to local time for display
            local_dt = msg.timestamp.astimezone()
            time_str = local_dt.strftime(time_fmt)

            if msg.type == "user":
                # USER: [HH:MM:SS] USER    "First 80 chars of content..."
                content = msg.content[:80].replace("\n", " ")
                if len(msg.content) > 80:
                    content += "..."
                session_log.write(f"[cyan][{time_str}] USER    \"{content}\"[/cyan]")

            elif msg.type == "assistant":
                if msg.tools_used:
                    # ASSISTANT with tools: [HH:MM:SS] TOOL    Read, Bash, Edit
                    tools_str = ", ".join(msg.tools_used)
                    session_log.write(f"[yellow][{time_str}] TOOL    {tools_str}[/yellow]")
                else:
                    # ASSISTANT text only: [HH:MM:SS] CLAUDE  "First 80 chars of response..."
                    content = msg.content[:80].replace("\n", " ")
                    if len(msg.content) > 80:
                        content += "..."
                    session_log.write(f"[green][{time_str}] CLAUDE  \"{content}\"[/green]")

        # Only scroll to top when viewing a different session (not on refresh of same session)
        if not is_same_session:
            # Defer scroll to after refresh so content is fully rendered
            self.call_after_refresh(session_log.scroll_home)

    # -------------------------------------------------------------------------
    # Handoffs Tab Methods
    # -------------------------------------------------------------------------

    def _is_recently_completed(self, handoff: HandoffSummary) -> bool:
        """Check if a handoff was completed within the last 48 hours.

        Args:
            handoff: The handoff to check

        Returns:
            True if completed within 48 hours, False otherwise
        """
        if handoff.status != "completed":
            return False

        try:
            updated_date = date.fromisoformat(handoff.updated)
            cutoff = date.today() - timedelta(days=2)
            return updated_date >= cutoff
        except (ValueError, TypeError):
            return False

    def _parse_handoff_filter(self, filter_text: str) -> dict:
        """Parse filter text into components.

        Supports:
        - Free text: matches against title and description
        - status:value - filter by status
        - phase:value - filter by phase
        - agent:value - filter by agent

        Args:
            filter_text: The raw filter text

        Returns:
            Dict with keys: text, status, phase, agent
        """
        result = {"text": "", "status": None, "phase": None, "agent": None}

        if not filter_text:
            return result

        parts = filter_text.split()
        text_parts = []

        for part in parts:
            if part.startswith("status:"):
                result["status"] = part[7:]
            elif part.startswith("phase:"):
                result["phase"] = part[6:]
            elif part.startswith("agent:"):
                result["agent"] = part[6:]
            else:
                text_parts.append(part)

        result["text"] = " ".join(text_parts)
        return result

    def _matches_filter(self, handoff: HandoffSummary, parsed_filter: dict) -> bool:
        """Check if handoff matches the filter criteria.

        Args:
            handoff: The handoff to check
            parsed_filter: Parsed filter dict from _parse_handoff_filter

        Returns:
            True if handoff matches all filter criteria
        """
        # Text match (title or description) - case insensitive
        if parsed_filter["text"]:
            text = parsed_filter["text"].lower()
            title_match = text in handoff.title.lower()
            desc_match = text in (handoff.description or "").lower()
            if not title_match and not desc_match:
                return False

        # Status match
        if parsed_filter["status"] and handoff.status != parsed_filter["status"]:
            return False

        # Phase match
        if parsed_filter["phase"] and handoff.phase != parsed_filter["phase"]:
            return False

        # Agent match
        if parsed_filter["agent"] and handoff.agent != parsed_filter["agent"]:
            return False

        return True

    def _update_filter_status(self, visible: int, total: int) -> None:
        """Update the filter status indicator.

        Args:
            visible: Number of visible handoffs
            total: Total number of handoffs (before filtering)
        """
        try:
            status = self.query_one("#handoff-filter-status", Static)
            if visible < total:
                status.update(f"[dim]Showing {visible} of {total} handoffs[/dim]")
            else:
                status.update("")
        except Exception:
            pass

    def _should_show_handoff(self, handoff: HandoffSummary) -> bool:
        """Determine if a handoff should be shown based on current filter settings.

        Args:
            handoff: The handoff to check

        Returns:
            True if the handoff should be displayed, False otherwise
        """
        # Always show non-completed handoffs
        if handoff.status != "completed":
            return True

        # Show all completed if toggle is on
        if self._show_completed_handoffs:
            return True

        # Show recently completed (within 48 hours) even when toggle is off
        return self._is_recently_completed(handoff)

    def _get_handoff_counts(self, handoffs: List[HandoffSummary]) -> tuple:
        """Calculate counts for active, completed, and hidden handoffs.

        Args:
            handoffs: List of all handoffs

        Returns:
            Tuple of (active_count, completed_count, hidden_count)
        """
        active_count = 0
        completed_count = 0
        hidden_count = 0

        for handoff in handoffs:
            if handoff.status != "completed":
                active_count += 1
            else:
                completed_count += 1
                if not self._show_completed_handoffs and not self._is_recently_completed(handoff):
                    hidden_count += 1

        return active_count, completed_count, hidden_count

    def _update_handoff_title(self, handoffs: List[HandoffSummary]) -> None:
        """Update the handoffs section title with count indicator.

        Args:
            handoffs: List of all handoffs
        """
        try:
            # Find the first Static widget with "Handoffs" in the handoffs pane
            handoffs_pane = self.query_one("#handoffs")
            title_widget = handoffs_pane.query("Static.section-title").first()

            active_count, completed_count, hidden_count = self._get_handoff_counts(handoffs)

            if hidden_count > 0:
                title_widget.update(
                    f"Handoffs ({active_count} active, {completed_count} completed, +{hidden_count} hidden)"
                )
            else:
                title_widget.update(
                    f"Handoffs ({active_count} active, {completed_count} completed)"
                )
        except Exception:
            # If we can't find or update the title, silently ignore
            pass

    def _setup_handoff_list(self) -> None:
        """Initialize the handoff list DataTable with sortable columns."""
        handoff_table = self.query_one("#handoff-list", DataTable)

        # Enable row cursor for RowHighlighted events on arrow key navigation
        handoff_table.cursor_type = "row"

        # Add columns with keys for sorting
        handoff_table.add_column("ID", key="id")
        handoff_table.add_column("Title", key="title")
        handoff_table.add_column("Status", key="status")
        handoff_table.add_column("Phase", key="phase")
        handoff_table.add_column("Agent", key="agent")
        handoff_table.add_column("Age", key="age")
        handoff_table.add_column("Updated", key="updated")
        handoff_table.add_column("Tried", key="tried")
        handoff_table.add_column("Next", key="next")

        # Hide timeline widget initially (list view is default)
        timeline = self.query_one("#handoff-timeline", RichLog)
        timeline.display = False

        # Clear any existing handoff data
        self._handoff_data.clear()

        # Get handoffs from StateReader
        handoffs = self.state_reader.get_handoffs()

        # Update the section title with counts
        self._update_handoff_title(handoffs)

        # Parse the current filter
        parsed_filter = self._parse_handoff_filter(self._handoff_filter)

        # Track total for filter status
        total_visible = 0
        visible_count = 0

        for handoff in handoffs:
            # Skip handoffs that shouldn't be shown based on completed toggle
            if not self._should_show_handoff(handoff):
                continue

            total_visible += 1

            # Apply text/prefix filter
            if not self._matches_filter(handoff, parsed_filter):
                continue

            visible_count += 1
            self._handoff_data[handoff.id] = handoff
            self._populate_handoff_row(handoff_table, handoff)

        # Store total for filter status updates
        self._handoff_total_count = total_visible
        self._update_filter_status(visible_count, total_visible)

    def _populate_handoff_row(
        self, handoff_table: DataTable, handoff: HandoffSummary
    ) -> None:
        """Add a row to the handoff table with formatted values.

        Args:
            handoff_table: The DataTable widget to add the row to
            handoff: HandoffSummary containing handoff data
        """
        # Format title (truncate if needed)
        title = handoff.title[:30] + "..." if len(handoff.title) > 30 else handoff.title

        # Format status with color markup
        status_colors = {
            "not_started": "dim",
            "in_progress": "green",
            "blocked": "red",
            "ready_for_review": "yellow",
            "completed": "cyan",
        }
        status_color = status_colors.get(handoff.status, "white")
        status_display = f"[{status_color}]{handoff.status}[/{status_color}]"

        # Format age
        age_display = f"{handoff.age_days}d"

        # Format updated date
        updated_display = handoff.updated if handoff.updated else "-"

        # Count tried and next steps
        tried_count = str(len(handoff.tried_steps))
        next_count = str(len(handoff.next_steps))

        row_data = [
            handoff.id[:12] if len(handoff.id) > 12 else handoff.id,
            title,
            status_display,
            handoff.phase,
            handoff.agent[:10] if len(handoff.agent) > 10 else handoff.agent,
            age_display,
            updated_display,
            tried_count,
            next_count,
        ]

        handoff_table.add_row(*row_data, key=handoff.id)

    def _show_handoff_details(self, handoff_id: str) -> None:
        """Display details for a selected handoff.

        Note: This does NOT set _current_handoff_id. That is only set in
        on_data_table_row_selected when the user explicitly presses Enter/clicks
        to confirm selection. This enables double-action behavior where:
        - Arrow navigation shows details but doesn't "confirm" selection
        - First Enter confirms selection (sets _current_handoff_id)
        - Second Enter on same row opens the action popup
        """
        details_log = self.query_one("#handoff-details", RichLog)
        details_log.clear()

        handoff = self._handoff_data.get(handoff_id)
        if handoff is None:
            details_log.write("[dim]No handoff data available[/dim]")
            return

        # Header with ID and title
        details_log.write(f"[bold cyan]{handoff.id}[/bold cyan] {handoff.title}")
        details_log.write("")

        # Status line
        status_colors = {
            "not_started": "dim",
            "in_progress": "green",
            "blocked": "red",
            "ready_for_review": "yellow",
            "completed": "cyan",
        }
        status_color = status_colors.get(handoff.status, "white")
        details_log.write(
            f"[bold]Status:[/bold] [{status_color}]{handoff.status}[/{status_color}] | "
            f"[bold]Phase:[/bold] {handoff.phase} | "
            f"[bold]Agent:[/bold] {handoff.agent}"
        )

        # Dates
        details_log.write(
            f"[bold]Created:[/bold] {handoff.created} | "
            f"[bold]Updated:[/bold] {handoff.updated} | "
            f"[bold]Age:[/bold] {handoff.age_days} days"
        )
        details_log.write("")

        # Project (new field)
        if handoff.project:
            details_log.write(f"[bold]Project:[/bold] {handoff.project}")
            details_log.write("")

        # Blocked by (new field)
        if handoff.blocked_by:
            details_log.write(
                f"[bold red]Blocked By:[/bold red] {', '.join(handoff.blocked_by)}"
            )
            details_log.write("")

        # Description
        if handoff.description:
            details_log.write(f"[bold]Description:[/bold] {handoff.description}")
            details_log.write("")

        # Tried steps (completed todos)
        if handoff.tried_steps:
            details_log.write(f"[bold]Completed ({len(handoff.tried_steps)}):[/bold]")
            for i, step in enumerate(handoff.tried_steps, 1):
                outcome_colors = {"success": "green", "fail": "red", "partial": "yellow"}
                color = outcome_colors.get(step.outcome, "white")
                details_log.write(f"  {i}. [{color}]{step.outcome}[/{color}] {step.description}")
            details_log.write("")

        # Current progress (in-progress todo)
        if handoff.checkpoint:
            details_log.write(f"[bold cyan]In Progress:[/bold cyan] {handoff.checkpoint}")
            details_log.write("")

        # Next steps (pending todos)
        if handoff.next_steps:
            details_log.write(f"[bold]Pending ({len(handoff.next_steps)}):[/bold]")
            for item in handoff.next_steps:
                details_log.write(f"  ○ {item}")
            details_log.write("")

        # Refs
        if handoff.refs:
            details_log.write(f"[bold]Refs:[/bold] {', '.join(handoff.refs)}")
            details_log.write("")

        # Handoff Context section (new fields)
        if handoff.handoff:
            ctx = handoff.handoff
            details_log.write("[bold cyan]Handoff Context[/bold cyan]")

            # Git ref (abbreviated to 8 chars)
            if ctx.git_ref:
                short_ref = ctx.git_ref[:8] if len(ctx.git_ref) >= 8 else ctx.git_ref
                details_log.write(f"  [bold]Git:[/bold] {short_ref}")

            # Summary
            if ctx.summary:
                details_log.write(f"  [bold]Summary:[/bold] {ctx.summary}")

            # Critical files
            if ctx.critical_files:
                details_log.write(
                    f"  [bold]Critical Files:[/bold] {', '.join(ctx.critical_files)}"
                )

            # Recent changes
            if ctx.recent_changes:
                details_log.write(f"  [bold]Recent Changes:[/bold]")
                for change in ctx.recent_changes:
                    details_log.write(f"    - {change}")

            # Learnings
            if ctx.learnings:
                details_log.write(f"  [bold]Learnings:[/bold]")
                for learning in ctx.learnings:
                    details_log.write(f"    - {learning}")

            # Blockers
            if ctx.blockers:
                details_log.write(f"  [bold red]Blockers:[/bold red]")
                for blocker in ctx.blockers:
                    details_log.write(f"    - {blocker}")

        # Sessions section - show linked sessions from session-handoffs.json
        sessions = self._get_sessions_for_handoff(handoff_id)
        if sessions:
            details_log.write("")
            details_log.write("[bold cyan]Sessions[/bold cyan]")
            for session in sessions:
                session_id = session.get("session_id", "")
                created = session.get("created", "")
                # Format the created timestamp (show date only)
                if created and "T" in created:
                    created = created.split("T")[0]
                details_log.write(f"  {session_id} ({created})")

        # Scroll to top
        self.call_after_refresh(details_log.scroll_home)

    def _navigate_to_handoff(self, handoff_id: str) -> None:
        """Navigate to handoffs tab and select the given handoff.

        Args:
            handoff_id: The handoff ID to navigate to (e.g., 'hf-abc1234')
        """
        try:
            # Switch to handoffs tab
            tabs = self.query_one(TabbedContent)
            tabs.active = "handoffs"

            # Find and select the handoff row
            table = self.query_one("#handoff-list", DataTable)
            for idx, row_key in enumerate(table.rows.keys()):
                if str(row_key.value) == handoff_id:
                    table.move_cursor(row=idx)
                    self._show_handoff_details(handoff_id)
                    break
        except Exception as e:
            self.notify(f"Navigation failed: {e}", severity="error")

    def _navigate_to_session(self, session_id: str) -> None:
        """Navigate to session tab and select the given session.

        Args:
            session_id: The session ID to navigate to
        """
        try:
            # Switch to session tab
            tabs = self.query_one(TabbedContent)
            tabs.active = "session"

            # Find and select the session row
            table = self.query_one("#session-list", DataTable)
            for idx, row_key in enumerate(table.rows.keys()):
                if str(row_key.value) == session_id:
                    table.move_cursor(row=idx)
                    self._show_session_events(session_id)
                    break
        except Exception as e:
            self.notify(f"Navigation failed: {e}", severity="error")

    def _get_sessions_for_handoff(self, handoff_id: str) -> List[dict]:
        """Get sessions linked to a handoff from session-handoffs.json.

        Args:
            handoff_id: The handoff ID to find sessions for

        Returns:
            List of dicts with session_id and created fields
        """
        import json

        # Use state_reader's state_dir for consistent path resolution
        session_handoffs_file = self.state_reader.state_dir / "session-handoffs.json"

        if not session_handoffs_file.exists():
            return []

        try:
            data = json.loads(session_handoffs_file.read_text())
        except (json.JSONDecodeError, OSError):
            return []

        # Find sessions that are linked to this handoff
        sessions = []
        for session_id, entry in data.items():
            if isinstance(entry, dict) and entry.get("handoff_id") == handoff_id:
                sessions.append({
                    "session_id": session_id,
                    "created": entry.get("created", ""),
                })

        return sessions

    def action_goto_handoff(self) -> None:
        """Navigate from current session to its linked handoff (if any)."""
        # Only active in session tab
        try:
            tabs = self.query_one(TabbedContent)
            if tabs.active != "session":
                return
        except Exception:
            return

        # Get current session ID
        if self._current_session_id is None:
            self.notify("No session selected")
            return

        # Look up handoff for this session
        import json

        # Use state_reader's state_dir for consistent path resolution
        session_handoffs_file = self.state_reader.state_dir / "session-handoffs.json"

        handoff_id = None
        if session_handoffs_file.exists():
            try:
                data = json.loads(session_handoffs_file.read_text())
                entry = data.get(self._current_session_id)
                if isinstance(entry, dict):
                    handoff_id = entry.get("handoff_id")
            except (json.JSONDecodeError, OSError):
                pass

        if handoff_id:
            self._navigate_to_handoff(handoff_id)
        else:
            # Try date-based matching as fallback
            summary = self._session_data.get(self._current_session_id)
            if summary and summary.start_time:
                project_root = _decode_project_path(summary.path)
                if project_root:
                    handoffs = self.state_reader.get_handoffs(project_root)
                    if handoffs:
                        session_date = summary.start_time.date()
                        matching_handoff = _find_matching_handoff(session_date, handoffs)
                        if matching_handoff:
                            self._navigate_to_handoff(matching_handoff.id)
                            return

            self.notify("No linked handoff found for this session")

    def _refresh_handoff_list(self) -> None:
        """Refresh the handoffs list with current filter settings.

        Preserves scroll position and user selection across refresh.
        """
        handoff_table = self.query_one("#handoff-list", DataTable)

        # Save scroll position before clearing
        scroll_y = handoff_table.scroll_y

        handoff_table.clear()
        self._handoff_data.clear()

        # Get handoffs from StateReader
        handoffs = self.state_reader.get_handoffs()

        # Update the section title with counts
        self._update_handoff_title(handoffs)

        # Parse the current filter
        parsed_filter = self._parse_handoff_filter(self._handoff_filter)

        # Track total for filter status
        total_visible = 0
        visible_count = 0

        for handoff in handoffs:
            # Skip handoffs that shouldn't be shown based on completed toggle
            if not self._should_show_handoff(handoff):
                continue

            total_visible += 1

            # Apply text/prefix filter
            if not self._matches_filter(handoff, parsed_filter):
                continue

            visible_count += 1
            self._handoff_data[handoff.id] = handoff
            self._populate_handoff_row(handoff_table, handoff)

        # Store total for filter status updates
        self._handoff_total_count = total_visible
        self._update_filter_status(visible_count, total_visible)

        # Restore scroll position
        handoff_table.scroll_y = scroll_y

        # Preserve user's selection if it still exists in the new data
        if self._user_selected_handoff_id is not None:
            if self._user_selected_handoff_id in self._handoff_data:
                # Find the row index for the previously selected handoff
                row_keys = list(handoff_table.rows.keys())
                for idx, row_key in enumerate(row_keys):
                    if row_key.value == self._user_selected_handoff_id:
                        handoff_table.move_cursor(row=idx)
                        break
                # Re-render details for the highlighted handoff
                self._show_handoff_details(self._user_selected_handoff_id)
            else:
                # Handoff was removed/archived, clear the details panel
                details_log = self.query_one("#handoff-details", RichLog)
                details_log.clear()
                details_log.write("[dim]Handoff no longer available[/dim]")
                # Also clear the confirmed selection if it was the same
                if self._current_handoff_id == self._user_selected_handoff_id:
                    self._current_handoff_id = None
                self._user_selected_handoff_id = None

        # Clear confirmed selection if the handoff was removed but user moved to another
        if self._current_handoff_id is not None:
            if self._current_handoff_id not in self._handoff_data:
                self._current_handoff_id = None

    def action_toggle_completed(self) -> None:
        """Toggle visibility of completed handoffs."""
        # Only applies when on handoffs tab
        try:
            tabs = self.query_one(TabbedContent)
            if tabs.active != "handoffs":
                return
        except Exception:
            return

        self._show_completed_handoffs = not self._show_completed_handoffs
        self._refresh_handoff_list()

        status = "shown" if self._show_completed_handoffs else "hidden"
        self.notify(f"Completed handoffs: {status}")

    def action_toggle_timeline(self) -> None:
        """Toggle between list and timeline view in handoffs tab."""
        # Only active when on handoffs tab
        try:
            tabs = self.query_one(TabbedContent)
            if tabs.active != "handoffs":
                return
        except Exception:
            return

        self._timeline_view = not self._timeline_view

        # Show/hide the appropriate widgets
        table = self.query_one("#handoff-list", DataTable)
        timeline = self.query_one("#handoff-timeline", RichLog)

        table.display = not self._timeline_view
        timeline.display = self._timeline_view

        if self._timeline_view:
            self._render_timeline()
            self.notify("Timeline view")
        else:
            self.notify("List view")

    def _render_timeline(self) -> None:
        """Render handoffs as a timeline with colored bars."""
        timeline = self.query_one("#handoff-timeline", RichLog)
        timeline.clear()

        # Get handoffs data
        handoffs = list(self._handoff_data.values())
        if not handoffs:
            timeline.write("[dim]No handoffs to display[/dim]")
            return

        # Get date range from all handoffs
        min_date = None
        max_date = None

        for h in handoffs:
            try:
                created = date.fromisoformat(h.created)
                updated = date.fromisoformat(h.updated)
                if min_date is None or created < min_date:
                    min_date = created
                if max_date is None or updated > max_date:
                    max_date = updated
            except (ValueError, TypeError):
                continue

        if min_date is None or max_date is None:
            timeline.write("[dim]No valid date range[/dim]")
            return

        # Ensure at least 1 day range
        total_days = (max_date - min_date).days + 1
        if total_days < 1:
            total_days = 1

        # Bar width for timeline
        bar_width = 50

        # Header with date range
        timeline.write(f"[bold]Timeline: {min_date.isoformat()} to {max_date.isoformat()}[/bold]")
        timeline.write("")

        # Status color map
        status_colors = {
            "completed": "green",
            "in_progress": "yellow",
            "blocked": "red",
            "not_started": "blue",
            "ready_for_review": "cyan",
        }

        # Sort handoffs by created date
        sorted_handoffs = sorted(handoffs, key=lambda h: h.created)

        for handoff in sorted_handoffs:
            try:
                created = date.fromisoformat(handoff.created)
                updated = date.fromisoformat(handoff.updated)
            except (ValueError, TypeError):
                continue

            # Calculate bar position and width
            start_offset = (created - min_date).days
            end_offset = (updated - min_date).days
            start_pos = int((start_offset / total_days) * bar_width)
            end_pos = int((end_offset / total_days) * bar_width)
            bar_len = max(1, end_pos - start_pos + 1)

            # Get color based on status
            color = status_colors.get(handoff.status, "white")

            # Render the bar
            padding = " " * start_pos
            bar = "\u2588" * bar_len  # Full block character
            label = f" {handoff.id[:10]} ({handoff.status})"

            timeline.write(f"{padding}[{color}]{bar}[/] {label}")

        timeline.write("")
        timeline.write("[dim]Legend: [green]completed[/] [yellow]in_progress[/] [red]blocked[/] [blue]not_started[/] [cyan]ready_for_review[/][/dim]")

    def _update_charts(self) -> None:
        """Update charts panel with sparklines and plotext charts."""
        # Update sparklines section
        sparklines_widget = self.query_one("#sparklines-panel", Static)
        stats = self.stats.compute()
        # Pass pre-computed stats to avoid redundant compute() call
        timing_summary = self.stats.get_timing_summary(stats)

        lines = []
        lines.append("[bold]Quick Trends[/bold]")
        lines.append("")

        # Hook latency sparklines
        lines.append("[bold]Hook Latency Trends[/bold]")
        for hook, timings in stats.hook_timings.items():
            if timings:
                sparkline = make_sparkline(timings, width=20)
                avg = sum(timings) / len(timings)
                lines.append(f"  {hook:12} {sparkline} avg={avg:.0f}ms")

        if not stats.hook_timings:
            lines.append("  [dim]No timing data available[/dim]")

        lines.append("")

        # Activity by hour sparkline
        events = list(self.log_reader.iter_events())
        hourly_counts = self._compute_hourly_activity(events)
        if hourly_counts:
            sparkline = make_sparkline(hourly_counts, width=24)
            lines.append("[bold]Activity (last 24h by hour)[/bold]")
            lines.append(f"  {sparkline}")
            total = sum(hourly_counts)
            lines.append(f"  Total events: {total}")

        sparklines_widget.update("\n".join(lines))

        # Update plotext charts if available
        if PlotextPlot:
            self._update_activity_chart(events)
            self._update_timing_chart(timing_summary)

    def _compute_hourly_activity(self, events: List[DebugEvent]) -> List[float]:
        """
        Compute event counts by hour for the last 24 hours.

        Args:
            events: List of debug events

        Returns:
            List of 24 floats representing event counts per hour (oldest to newest)
        """
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=24)

        # Initialize 24 hour buckets
        hourly: defaultdict[int, int] = defaultdict(int)

        for event in events:
            ts = event.timestamp_dt
            if ts is None:
                continue
            if ts < cutoff:
                continue

            # Calculate hour offset (0 = 24h ago, 23 = current hour)
            hours_ago = int((now - ts).total_seconds() / 3600)
            if 0 <= hours_ago < 24:
                hour_idx = 23 - hours_ago
                hourly[hour_idx] += 1

        # Convert to list (ensure all 24 hours represented)
        return [float(hourly.get(i, 0)) for i in range(24)]

    def _update_activity_chart(self, events: List[DebugEvent]) -> None:
        """Update the activity timeline bar chart."""
        try:
            chart = self.query_one("#activity-chart", PlotextPlot)
        except Exception:
            return

        hourly = self._compute_hourly_activity(events)

        # Clear and redraw
        chart.plt.clear_figure()
        chart.plt.title("Activity Timeline (24h)")
        chart.plt.xlabel("Hours Ago")

        # Create hour labels (24h ago to now)
        hours = list(range(24))
        hour_labels = [f"{23-h}h" if h % 4 == 0 else "" for h in hours]

        chart.plt.bar(hours, hourly, width=0.8)
        chart.plt.xticks(hours[::4], hour_labels[::4])
        chart.refresh()

    def _update_timing_chart(self, timing_summary: dict) -> None:
        """Update the hook timing horizontal bar chart."""
        try:
            chart = self.query_one("#timing-chart", PlotextPlot)
        except Exception:
            return

        if not timing_summary:
            chart.plt.clear_figure()
            chart.plt.title("Hook Timing (no data)")
            chart.refresh()
            return

        # Prepare data for horizontal bar chart
        hooks = list(timing_summary.keys())
        avgs = [timing_summary[h]["avg_ms"] for h in hooks]
        p95s = [timing_summary[h]["p95_ms"] for h in hooks]

        chart.plt.clear_figure()
        chart.plt.title("Hook Timing Breakdown")

        # Use simple bar chart with hooks on x-axis
        positions = list(range(len(hooks)))
        chart.plt.bar(positions, avgs, label="avg", width=0.4)
        chart.plt.bar([p + 0.4 for p in positions], p95s, label="p95", width=0.4)

        # Truncate hook names for display
        short_hooks = [h[:10] for h in hooks]
        chart.plt.xticks(positions, short_hooks)
        chart.plt.ylabel("ms")
        chart.refresh()

    def action_switch_tab(self, tab_id: str) -> None:
        """Switch to a specific tab."""
        tabbed = self.query_one(TabbedContent)
        tabbed.active = tab_id

    def action_toggle_pause(self) -> None:
        """Toggle pause/resume of auto-refresh."""
        self._paused = not self._paused
        status = "PAUSED" if self._paused else "RUNNING"
        self.notify(f"Auto-refresh: {status}")

    def action_refresh(self) -> None:
        """Manual refresh of all views."""
        self._load_events()
        self._update_health()
        self._update_state()
        self._refresh_session_list()
        self._refresh_handoff_list()
        self._update_charts()
        self.notify("Refreshed")

    def action_toggle_all(self) -> None:
        """Toggle between current project (non-empty) and all projects (all sessions)."""
        self._show_all = not self._show_all
        if self._show_all:
            self.notify("Showing all projects, all sessions")
        else:
            self.notify("Showing current project, non-empty sessions")
        self._refresh_session_list()

    def action_toggle_system_sessions(self) -> None:
        """Toggle visibility of system/warmup sessions."""
        self._show_system_sessions = not self._show_system_sessions
        self._refresh_session_list()
        self.notify(f"System sessions {'shown' if self._show_system_sessions else 'hidden'}")

    def action_expand_session(self) -> None:
        """Open modal with expanded session details for the highlighted row."""
        try:
            session_table = self.query_one("#session-list", DataTable)
        except Exception:
            return

        # Get highlighted row key
        if session_table.cursor_row is None:
            self.notify("No session selected", severity="warning")
            return

        # Get the session_id from row key
        try:
            row_key_obj = list(session_table.rows.keys())[session_table.cursor_row]
            session_id = row_key_obj.value
        except (IndexError, AttributeError):
            self.notify("Could not get session ID", severity="error")
            return

        if not session_id or session_id not in self._session_data:
            self.notify("Session data not found", severity="error")
            return

        # Get session data and open modal
        summary = self._session_data[session_id]
        if isinstance(summary, TranscriptSummary):
            self.push_screen(SessionDetailModal(session_id, summary))
        else:
            self.notify("Invalid session data format", severity="error")

    def action_copy_session(self) -> None:
        """Copy highlighted session data to clipboard."""
        try:
            session_table = self.query_one("#session-list", DataTable)
        except Exception:
            return

        # Get highlighted row key
        if session_table.cursor_row is None:
            self.notify("No session selected", severity="warning")
            return

        row_key = session_table.get_row_at(session_table.cursor_row)
        if row_key is None:
            self.notify("No session selected", severity="warning")
            return

        # Get the session_id from row key (it's the key we set when adding rows)
        try:
            # DataTable stores row keys; get the key for cursor row
            row_key_obj = list(session_table.rows.keys())[session_table.cursor_row]
            session_id = row_key_obj.value
        except (IndexError, AttributeError):
            self.notify("Could not get session ID", severity="error")
            return

        if not session_id or session_id not in self._session_data:
            self.notify("Session data not found", severity="error")
            return

        # Format session data for clipboard (using TranscriptSummary)
        summary = self._session_data[session_id]
        if isinstance(summary, TranscriptSummary):
            text = (
                f"Session: {session_id} | "
                f"Project: {summary.project} | "
                f"Messages: {summary.message_count} | "
                f"Tokens: {summary.total_tokens} | "
                f"Started: {_format_session_time(summary.start_time)}"
            )
        else:
            # Fallback for old format
            text = f"Session: {session_id}"

        # Copy to clipboard using platform-appropriate command
        try:
            if sys.platform == "darwin":
                subprocess.run(["pbcopy"], input=text.encode(), check=True)
            elif sys.platform == "win32":
                subprocess.run(["clip"], input=text.encode(), check=True, shell=True)
            else:
                # Linux - try xclip first, fall back to xsel
                try:
                    subprocess.run(
                        ["xclip", "-selection", "clipboard"],
                        input=text.encode(),
                        check=True,
                    )
                except FileNotFoundError:
                    subprocess.run(
                        ["xsel", "--clipboard", "--input"],
                        input=text.encode(),
                        check=True,
                    )
            self.notify("Copied to clipboard")
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            self.notify(f"Copy failed: {e}", severity="error")

    def _refresh_session_list(self) -> None:
        """Refresh the session list table with current filter settings.

        Rebuilds columns when show_all toggle changes (to show/hide Project column).
        Preserves scroll position and user selection across refresh.
        """
        session_table = self.query_one("#session-list", DataTable)

        # Save scroll position before clearing
        scroll_y = session_table.scroll_y

        # Check if we need to rebuild columns (Project column visibility changed)
        column_labels = [str(col.label) for col in session_table.columns.values()]
        has_project_col = "Project" in column_labels
        needs_project_col = self._show_all

        if has_project_col != needs_project_col:
            # Need to rebuild columns - clear everything first
            session_table.clear(columns=True)

            # Re-add columns with correct Project visibility
            session_table.add_column("Session ID", key="session_id")
            if self._show_all:
                session_table.add_column("Project", key="project")
            session_table.add_column("Origin", key="origin")
            session_table.add_column("Topic", key="topic")
            session_table.add_column("Started", key="started")
            session_table.add_column("Last", key="last_activity")
            session_table.add_column("Tools", key="tools")
            session_table.add_column("Tokens", key="tokens")
            session_table.add_column("Msgs", key="messages")
        else:
            # Just clear rows, keep columns
            session_table.clear()

        self._session_data.clear()

        # Get sessions from TranscriptReader
        # _show_all toggles: all projects + all sessions (including empty) vs current project + non-empty
        if self._show_all:
            sessions = self.transcript_reader.list_all_sessions(limit=50, include_empty=True)
        else:
            sessions = self.transcript_reader.list_sessions(
                self._current_project, limit=50, include_empty=False
            )

        # Update the section title with counts
        self._update_session_title(sessions)

        for summary in sessions:
            # Skip system sessions unless toggle is on
            if not self._should_show_session(summary):
                continue

            session_id = summary.session_id
            self._session_data[session_id] = summary

            self._populate_session_row(session_table, session_id, summary)

        # Restore scroll position
        session_table.scroll_y = scroll_y

        # Preserve user's selection if it still exists in the new data
        if self._user_selected_session_id is not None:
            if self._user_selected_session_id in self._session_data:
                # Find the row index for the previously selected session
                row_keys = list(session_table.rows.keys())
                for idx, row_key in enumerate(row_keys):
                    if row_key.value == self._user_selected_session_id:
                        session_table.move_cursor(row=idx)
                        break

    def _get_dynamic_subtitle(self) -> str:
        """Build dynamic subtitle showing status."""
        parts = []
        if self.project_filter:
            parts.append(f"Project: {self.project_filter}")
        if self._paused:
            parts.append("[PAUSED]")

        now = datetime.now().strftime(_get_time_format())
        parts.append(now)

        return " | ".join(parts) if parts else ""

    def _update_subtitle(self) -> None:
        """Update the app subtitle with current status."""
        self.sub_title = self._get_dynamic_subtitle()


def run_app(
    project_filter: Optional[str] = None,
    log_path: Optional[Path] = None,
) -> None:
    """
    Run the TUI application.

    Args:
        project_filter: Filter events to specific project (optional)
        log_path: Override log file path (optional)
    """
    app = RecallMonitorApp(project_filter=project_filter, log_path=log_path)
    app.run()


if __name__ == "__main__":
    run_app()
