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
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from textual.app import App, ComposeResult, SystemCommand
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    LoadingIndicator,
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
    from core.tui.analytics import BLOCKED_ALERT_THRESHOLD_DAYS
    from core.tui.log_reader import LogReader, format_event_line
    from core.tui.models import DebugEvent, HandoffSummary
    from core.tui.state_reader import StateReader
    from core.tui.stats import StatsAggregator
    from core.tui.transcript_reader import TranscriptReader, TranscriptSummary
    from core.tui.formatting import (
        _format_event_time,
        EVENT_TYPE_COLORS,
        _get_time_format,
        extract_event_details,
    )
    from core.tui.app_state import AppState
    from core.tui.tag_renderer import render_tags, strip_tags
except ImportError:
    from .analytics import BLOCKED_ALERT_THRESHOLD_DAYS
    from .log_reader import LogReader, format_event_line
    from .models import DebugEvent, HandoffSummary
    from .state_reader import StateReader
    from .stats import StatsAggregator
    from .transcript_reader import TranscriptReader, TranscriptSummary
    from .formatting import (
        _format_event_time,
        EVENT_TYPE_COLORS,
        _get_time_format,
        extract_event_details,
    )
    from .app_state import AppState
    from .tag_renderer import render_tags, strip_tags

# Backward compatibility alias for EVENT_COLORS
EVENT_COLORS = EVENT_TYPE_COLORS


def _get_lessons_manager():
    """Create and return a LessonsManager instance.

    Handles fallback import paths for both development (core.manager)
    and installed (manager) contexts.
    """
    try:
        from core.manager import LessonsManager
    except ImportError:
        from manager import LessonsManager

    # Get lessons base directory
    base_path = (
        os.environ.get("CLAUDE_RECALL_BASE")
        or os.environ.get("RECALL_BASE")
        or os.environ.get("LESSONS_BASE")
    )
    lessons_base = Path(base_path) if base_path else Path.home() / ".config" / "claude-recall"

    # Get project root from environment or find git root
    project_root = os.environ.get("PROJECT_DIR")
    if project_root:
        project_root = Path(project_root)
    else:
        project_root = Path.cwd()
        while project_root != project_root.parent:
            if (project_root / ".git").exists():
                break
            project_root = project_root.parent
        else:
            project_root = Path.cwd()

    return LessonsManager(lessons_base, project_root)


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
    """Format event-specific details for Rich display.

    Uses shared extract_event_details for data extraction, then formats
    for Rich/Textual output (similar to ANSI but uses -> instead of arrow).
    """
    d = extract_event_details(event)

    if not d:
        # Generic fallback: show first interesting key
        skip_keys = {"event", "level", "timestamp", "session_id", "pid", "project"}
        for k, v in event.raw.items():
            if k not in skip_keys:
                return f"{k}={v}"
        return ""

    if event.event == "session_start":
        return f"{d['system_count']}S/{d['project_count']}L ({d['total']} total)"

    elif event.event == "citation":
        promo = f" {d['promo']}" if "promo" in d else ""
        return f"{d['lesson_id']} ({d['uses_before']}->{d['uses_after']}){promo}"

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


def _format_handoff_date(date_str: str) -> str:
    """Format a handoff date string (YYYY-MM-DD) with relative labels.

    Returns:
        - "today" for today's date
        - "yesterday" for yesterday's date
        - "Jan 10" for dates within the current year
        - "Jan 10, 2024" for dates in other years
    """
    if not date_str:
        return "-"

    try:
        dt = date.fromisoformat(date_str)
    except (ValueError, TypeError):
        return date_str  # Return original if parse fails

    today = date.today()
    yesterday = today - timedelta(days=1)

    if dt == today:
        return "today"
    elif dt == yesterday:
        return "yesterday"
    elif dt.year == today.year:
        return dt.strftime("%b %d")
    else:
        return dt.strftime("%b %d, %Y")


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
            GenericSelectModal(
                handoff_id=self.handoff_id,
                handoff_title=self.handoff_title,
                options=["not_started", "in_progress", "blocked", "ready_for_review", "completed"],
                field_name="status",
                update_method="handoff_update_status",
            ),
            callback=self._on_submenu_result,
        )

    def action_set_phase(self) -> None:
        """Open phase selection sub-menu."""
        self.app.push_screen(
            GenericSelectModal(
                handoff_id=self.handoff_id,
                handoff_title=self.handoff_title,
                options=["research", "planning", "implementing", "review"],
                field_name="phase",
                update_method="handoff_update_phase",
            ),
            callback=self._on_submenu_result,
        )

    def action_set_agent(self) -> None:
        """Open agent selection sub-menu."""
        self.app.push_screen(
            GenericSelectModal(
                handoff_id=self.handoff_id,
                handoff_title=self.handoff_title,
                options=["explore", "general-purpose", "plan", "review", "user"],
                field_name="agent",
                update_method="handoff_update_agent",
            ),
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


class GenericSelectModal(ModalScreen[str]):
    """Generic modal for selecting from a list of options.

    Unified replacement for StatusSelectScreen, PhaseSelectScreen, and AgentSelectScreen.
    Supports both arrow key navigation with Enter and direct number key bindings (1-5).

    Args:
        handoff_id: The handoff ID being updated
        handoff_title: Display title of the handoff
        options: List of option values to display
        field_name: Name of the field being updated (e.g., "status", "phase", "agent")
        update_method: Name of manager method to call (e.g., "handoff_update_status")
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("1", "select_1", "Select 1", show=False),
        Binding("2", "select_2", "Select 2", show=False),
        Binding("3", "select_3", "Select 3", show=False),
        Binding("4", "select_4", "Select 4", show=False),
        Binding("5", "select_5", "Select 5", show=False),
    ]

    def __init__(
        self,
        handoff_id: str,
        handoff_title: str,
        options: List[str],
        field_name: str,
        update_method: str,
    ) -> None:
        super().__init__()
        self.handoff_id = handoff_id
        self.handoff_title = handoff_title
        self.options = options
        self.field_name = field_name
        self.update_method = update_method

    def compose(self) -> ComposeResult:
        with Vertical(id="select-modal"):
            yield Static(
                f"[bold]Select {self.field_name.title()}[/bold]",
                classes="modal-title",
            )
            yield Static(
                f"For: {self.handoff_title[:50]}",
                classes="modal-subtitle",
            )
            option_list = OptionList(
                *[
                    Option(f"[{i + 1}] {opt}", id=opt)
                    for i, opt in enumerate(self.options)
                ],
                id="select-options",
            )
            yield option_list
            yield Static("[dim][Esc] Cancel[/dim]")

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        """Handle option selection from OptionList."""
        self._select(str(event.option.id))

    def action_cancel(self) -> None:
        """Cancel selection and dismiss."""
        self.dismiss("")

    def action_select_1(self) -> None:
        if len(self.options) >= 1:
            self._select(self.options[0])

    def action_select_2(self) -> None:
        if len(self.options) >= 2:
            self._select(self.options[1])

    def action_select_3(self) -> None:
        if len(self.options) >= 3:
            self._select(self.options[2])

    def action_select_4(self) -> None:
        if len(self.options) >= 4:
            self._select(self.options[3])

    def action_select_5(self) -> None:
        if len(self.options) >= 5:
            self._select(self.options[4])

    def _select(self, value: str) -> None:
        """Apply selection and dismiss.

        Returns the result in "field:value" format regardless of whether
        the manager update succeeds. The notification shows any errors.
        """
        result = f"{self.field_name}:{value}"
        try:
            mgr = _get_lessons_manager()
            method = getattr(mgr, self.update_method)
            method(self.handoff_id, value)
            self.app.notify(f"{self.field_name.title()} updated to: {value}")
        except Exception as e:
            self.app.notify(f"Error: {e}", severity="error")
        self.dismiss(result)


class LoadingScreen(ModalScreen):
    """Full-screen loading modal shown during startup."""

    BINDINGS = [
        # No escape binding - must wait for loading
    ]

    def __init__(self) -> None:
        super().__init__()

    def compose(self) -> ComposeResult:
        with Vertical(id="loading-modal"):
            yield Static("[bold]Claude Recall[/bold]", classes="modal-title")
            yield LoadingIndicator()
            yield Static("Initializing...", id="loading-status")

    def update_status(self, text: str) -> None:
        self.query_one("#loading-status", Static).update(text)


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
        Binding("e", "expand_session", "Expand/Enrich"),
        Binding("c", "toggle_completed", "Completed"),
        Binding("w", "toggle_system_sessions", "System", show=True),
        Binding("t", "toggle_timeline", "Timeline", show=True),
        Binding("ctrl+c", "copy_session", "Copy", priority=True),
        Binding("h", "goto_handoff", "Handoff", show=False),
        # Handoff details navigation (hidden, context-specific)
        Binding("b", "goto_blocker", "Blocker", show=False),
        Binding("1", "goto_session_1", show=False),
        Binding("2", "goto_session_2", show=False),
        Binding("3", "goto_session_3", show=False),
        Binding("4", "goto_session_4", show=False),
        Binding("5", "goto_session_5", show=False),
        Binding("6", "goto_session_6", show=False),
        Binding("7", "goto_session_7", show=False),
        Binding("8", "goto_session_8", show=False),
        Binding("9", "goto_session_9", show=False),
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
        # Centralized state management
        self.state = AppState(project_filter=project_filter)
        # Readers and aggregators (not part of state - they have methods)
        self.log_reader = LogReader(log_path=log_path)
        self.state_reader = StateReader()
        self.stats = StatsAggregator(self.log_reader, self.state_reader)
        self.transcript_reader = TranscriptReader()
        self._refresh_timer = None
        # Current project path (not part of AppState - it's constant)
        self._current_project = os.environ.get("PROJECT_DIR", os.getcwd())
        # Unified toggle: False = current project, non-empty sessions
        #                 True = all projects, all sessions (including empty)
        self._show_all: bool = False

    def get_system_commands(self, screen: Screen) -> Iterable[SystemCommand]:
        """Add custom commands to the command palette."""
        yield from super().get_system_commands(screen)
        yield SystemCommand(
            "Refresh",
            "Refresh all views (events, health, state, sessions)",
            self.action_refresh,
        )
        yield SystemCommand(
            "Toggle Pause",
            "Pause or resume auto-refresh",
            self.action_toggle_pause,
        )
        yield SystemCommand(
            "Toggle All Projects",
            "Switch between current project and all projects",
            self.action_toggle_all,
        )
        yield SystemCommand(
            "Toggle Completed Handoffs",
            "Show or hide completed handoffs",
            self.action_toggle_completed,
        )
        yield SystemCommand(
            "Toggle System Sessions",
            "Show or hide system/warmup sessions",
            self.action_toggle_system_sessions,
        )

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
                    LoadingIndicator(id="session-loading"),
                    DataTable(id="session-list"),
                    Static("Session Events", classes="section-title"),
                    RichLog(id="session-events", highlight=True, markup=True, wrap=True, auto_scroll=False),
                )

            with TabPane("Handoffs", id="handoffs"):
                yield Vertical(
                    Horizontal(
                        Static("Filter: ", classes="filter-label"),
                        Input(id="handoff-filter", placeholder="text, status:x, phase:x, agent:x"),
                        Button("X", id="clear-filter", variant="error"),
                        classes="filter-row",
                    ),
                    DataTable(id="handoff-list"),
                    RichLog(id="handoff-timeline", highlight=True, markup=True, wrap=True, auto_scroll=False),
                    Static("Handoff Details", classes="section-title"),
                    RichLog(id="handoff-details", highlight=True, markup=True, wrap=True, auto_scroll=False),
                )

            with TabPane("Charts", id="charts"):
                yield Vertical(
                    Static("Loading charts...", id="sparklines-panel"),
                    Horizontal(
                        OptionList(
                            Option("24h", id="24"),
                            Option("7d", id="168"),
                            Option("30d", id="720"),
                            id="chart-period-selector",
                        ),
                        id="chart-period-row",
                        classes="filter-row",
                    ),
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
        self.push_screen(LoadingScreen())
        self._load_all_async()

    @work(exclusive=True)
    async def _load_all_async(self) -> None:
        """Load initial data for the live tab only (lazy loading for other tabs).

        Note: We avoid asyncio.to_thread() here because the loading methods
        perform Textual widget operations (e.g., event_log.write()) which must
        run on the main thread. Instead, we call methods directly and yield
        control to the event loop between steps using asyncio.sleep(0).

        Lazy loading optimization: Only the "live" tab (initial tab) is loaded at
        startup. Other tabs are loaded on first activation via
        on_tabbed_content_tab_activated().
        """
        # Wait for the LoadingScreen to be fully composed
        # The screen may not be mounted yet when the worker starts
        for _ in range(50):  # Max 500ms wait
            await asyncio.sleep(0.01)
            if isinstance(self.screen, LoadingScreen) and self.screen.is_mounted:
                break

        loading = self.screen
        if not isinstance(loading, LoadingScreen):
            # Screen was dismissed or replaced, skip loading UI updates
            # Only load events for the initial "live" tab
            self._load_events()
            self.state.tabs_loaded["live"] = True
            self._update_subtitle()
            self._refresh_timer = self.set_interval(5.0, self._on_refresh_timer)
            return

        try:
            loading.update_status("Loading events...")
            await asyncio.sleep(0)  # Yield to event loop for UI updates
            try:
                self._load_events()
            except Exception as e:
                self.notify(f"Error loading events: {e}", severity="error")

            # Mark "live" tab as loaded (other tabs will be lazy-loaded)
            self.state.tabs_loaded["live"] = True

        finally:
            self._update_subtitle()
            self._refresh_timer = self.set_interval(5.0, self._on_refresh_timer)
            # Dismiss loading screen
            self.pop_screen()

    def _load_events(self) -> None:
        """Load and display events in the log."""
        event_log = self.query_one("#event-log", RichLog)

        # Get events (filtered if needed)
        if self.state.project_filter:
            events = self.log_reader.filter_by_project(self.state.project_filter)
        else:
            events = self.log_reader.read_recent(100)

        # Clear and repopulate
        event_log.clear()
        for event in events:
            event_log.write(format_event_rich(event))

        self.state.last_event_count = self.log_reader.buffer_size

    def _on_refresh_timer(self) -> None:
        """Sync timer callback - updates subtitle and triggers async refresh.

        Only refreshes tabs that have been loaded (lazy loading awareness).
        """
        self._update_subtitle()
        if not self.state.paused:
            # Only refresh events if "live" tab has been loaded
            if self.state.tabs_loaded.get("live", False):
                self._refresh_events()
            # Only refresh the currently visible tab if it's loaded
            try:
                tabs = self.query_one(TabbedContent)
                active = tabs.active
                if active == "session" and self.state.tabs_loaded.get("session", False):
                    self._refresh_session_list_async()
                elif active == "handoffs" and self.state.tabs_loaded.get("handoffs", False):
                    self._refresh_handoff_list_async()
                # For health/state/charts tabs, they only need refresh on manual request
            except Exception:
                pass

    @work(exclusive=True)
    async def _refresh_events(self) -> None:
        """Async worker to check for and display new events."""
        new_count = await asyncio.to_thread(self.log_reader.load_buffer)
        if new_count > 0:
            self._append_new_events(new_count)

    def _append_new_events(self, count: int) -> None:
        """Append only the new events (last 'count' from buffer).

        Preserves scroll position if user has scrolled away from the bottom.
        """
        event_log = self.query_one("#event-log", RichLog)

        # Check if user is at/near the bottom before appending
        # Allow small threshold (2 lines) for rounding
        at_bottom = event_log.scroll_y >= event_log.max_scroll_y - 2

        # Update tracking based on scroll position
        if at_bottom:
            # User scrolled back to bottom - resume auto-scroll
            self.state.live_activity_user_scrolled = False
            event_log.auto_scroll = True
        else:
            # User scrolled away - preserve their position
            self.state.live_activity_user_scrolled = True

        # Save scroll position if user has scrolled away
        saved_scroll_y = event_log.scroll_y if self.state.live_activity_user_scrolled else None

        # Access buffer directly - don't use read_recent() which calls load_buffer() again
        buffer = list(self.log_reader._buffer)
        events = buffer[-count:] if count <= len(buffer) else buffer

        # Filter if needed
        if self.state.project_filter:
            events = [e for e in events if e.project.lower() == self.state.project_filter.lower()]

        # Temporarily disable auto_scroll if user has scrolled away
        if self.state.live_activity_user_scrolled:
            event_log.auto_scroll = False

        for event in events:
            event_log.write(format_event_rich(event))

        # Restore scroll position if user had scrolled away
        if saved_scroll_y is not None:
            event_log.scroll_y = saved_scroll_y

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

        # Context Budget (24h avg)
        if stats.injection_count > 0:
            lines.append("[bold]Context Budget (24h avg)[/bold]")
            lines.append(f"  Total: ~{int(stats.avg_total_tokens)} tokens")
            lines.append(f"  |-- Lessons: ~{int(stats.avg_lessons_tokens)} tokens")
            lines.append(f"  |-- Handoffs: ~{int(stats.avg_handoffs_tokens)} tokens")
            lines.append(f"  +-- Duties: ~{int(stats.avg_duties_tokens)} tokens")
            lines.append(f"  (n={stats.injection_count} injections)")
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

            # Low-effectiveness lessons for review
            try:
                low_eff = self.state_reader.get_lesson_effectiveness(threshold=0.6, min_citations=3)
                if low_eff:
                    lines.append("[bold]Low Effectiveness Lessons[/bold]")
                    lines.append("[dim]Lessons cited often but may not be helping[/dim]")
                    for lesson_id, rate, total_citations in low_eff[:5]:
                        pct = round(rate * 100)
                        # Get lesson title if available
                        lesson_match = next(
                            (l for l in all_lessons if l.id == lesson_id), None
                        ) if all_lessons else None
                        if lesson_match:
                            title_width = max(15, available_width - 40)
                            lines.append(
                                f"  [yellow]\\[{lesson_id}][/yellow] {truncate(lesson_match.title, title_width)} "
                                f"[red]{pct}% effective[/red] ({total_citations} citations)"
                            )
                        else:
                            lines.append(
                                f"  [yellow]\\[{lesson_id}][/yellow] [red]{pct}% effective[/red] ({total_citations} citations)"
                            )
                    lines.append("")
            except Exception:
                # Effectiveness tracking is optional, don't fail if it errors
                pass

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

            # Handoff Analytics section
            if handoffs:
                flow_metrics = self.state_reader.get_handoff_flow_metrics(handoffs)

                lines.append("[bold]Handoff Analytics[/bold]")

                # Status funnel - compact single line
                status_parts = []
                for status in ["not_started", "in_progress", "blocked", "ready_for_review", "completed"]:
                    count = flow_metrics.by_status.get(status, 0)
                    if count > 0:
                        # Short labels for compact display
                        label_map = {
                            "not_started": "new",
                            "in_progress": "active",
                            "blocked": "blocked",
                            "ready_for_review": "review",
                            "completed": "done",
                        }
                        status_parts.append(f"{count} {label_map[status]}")
                if status_parts:
                    lines.append(f"  Status: {' | '.join(status_parts)}")

                # Phase distribution (only for non-completed) - show percentages
                if flow_metrics.by_phase and flow_metrics.active_count > 0:
                    phase_parts = []
                    for phase in ["research", "planning", "implementing", "review"]:
                        count = flow_metrics.by_phase.get(phase, 0)
                        if count > 0:
                            pct = (count / flow_metrics.active_count) * 100
                            phase_parts.append(f"{phase} {pct:.0f}%")
                    if phase_parts:
                        lines.append(f"  Phases: {' | '.join(phase_parts)}")

                # Average cycle time (only if we have completed handoffs)
                if flow_metrics.by_status.get("completed", 0) > 0:
                    lines.append(f"  Avg cycle: {flow_metrics.avg_cycle_days:.1f} days")

                # Blocked alerts
                if flow_metrics.blocked_over_threshold:
                    lines.append(f"  [red]Blocked >{BLOCKED_ALERT_THRESHOLD_DAYS}d:[/red]")
                    for hf_id, hf_title, days in flow_metrics.blocked_over_threshold[:3]:
                        lines.append(f"    {hf_id} ({days}d)")

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
        return self.state.session.show_system

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

            if system_count > 0 and not self.state.session.show_system:
                title_widget.update(
                    f"Sessions ({user_count} user, {system_count} system hidden)"
                )
            else:
                title_widget.update(f"Sessions ({user_count + system_count})")
        except Exception:
            # If we can't find or update the title, silently ignore
            pass

    def _setup_session_columns(self) -> None:
        """Set up DataTable columns for session list (UI only, instant)."""
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

    def _load_session_data(self) -> List[TranscriptSummary]:
        """Load session data from transcript files (pure I/O, thread-safe).

        Returns:
            List of TranscriptSummary objects.
        """
        # _show_all toggles: all projects + all sessions (including empty) vs current project + non-empty
        if self._show_all:
            return self.transcript_reader.list_all_sessions_fast(limit=50, max_age_hours=168, include_empty=True)  # 7 days
        else:
            return self.transcript_reader.list_sessions(
                self._current_project, limit=50, include_empty=False
            )

    def _populate_session_data(self, sessions: List[TranscriptSummary]) -> None:
        """Populate the session DataTable with loaded data (UI only).

        Args:
            sessions: List of TranscriptSummary objects to display.
        """
        session_table = self.query_one("#session-list", DataTable)

        # Clear any existing session data
        self.state.session.data.clear()

        # Update the section title with counts
        self._update_session_title(sessions)

        for summary in sessions:
            # Skip system sessions unless toggle is on
            if not self._should_show_session(summary):
                continue

            session_id = summary.session_id
            self.state.session.data[session_id] = summary

            self._populate_session_row(session_table, session_id, summary)

    def _setup_session_list(self) -> None:
        """Initialize the session list DataTable synchronously.

        Used for direct navigation when async loading isn't appropriate.
        For normal tab activation, use _setup_session_list_async instead.
        """
        self._setup_session_columns()
        sessions = self._load_session_data()
        self._populate_session_data(sessions)

    def _populate_session_row(
        self, session_table: DataTable, session_id: str, summary: TranscriptSummary
    ) -> None:
        """Add a row to the session table with formatted values.

        Args:
            session_table: The DataTable widget to add the row to
            session_id: The session identifier (used as row key)
            summary: TranscriptSummary containing session data
        """
        # Format display values - strip XML tags for clean display
        topic = strip_tags(summary.first_prompt)
        topic = topic[:40] + "..." if len(topic) > 40 else topic
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

    @work(exclusive=True, group="session_setup")
    async def _setup_session_list_async(self) -> None:
        """Load session list asynchronously to avoid UI freeze."""
        loading = self.query_one("#session-loading", LoadingIndicator)
        session_table = self.query_one("#session-list", DataTable)

        try:
            loading.add_class("loading")
            session_table.add_class("loading")

            # Yield to event loop so loading indicator renders before blocking I/O
            await asyncio.sleep(0)

            self._setup_session_columns()  # Instant UI chrome

            # Yield again after column setup to keep UI responsive
            await asyncio.sleep(0)

            sessions = await asyncio.to_thread(self._load_session_data)  # Background I/O
            self._populate_session_data(sessions)  # Populate UI
        except Exception as e:
            self.notify(f"Error loading sessions: {e}", severity="error")
        finally:
            loading.remove_class("loading")
            session_table.remove_class("loading")

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        """Handle row highlight (arrow key navigation) in data tables."""
        if event.row_key is None:
            return

        row_key = event.row_key.value
        if not row_key:
            return

        if event.data_table.id == "session-list":
            # Track user's selection for persistence during refresh
            self.state.session.user_selected_id = row_key
            self._show_session_events(row_key)
        elif event.data_table.id == "handoff-list":
            # Track user's selection for persistence during refresh
            self.state.handoff.user_selected_id = row_key
            # Note: Don't set _current_handoff_id here - that breaks double-action [L007]
            # _current_handoff_id is only set in on_data_table_row_selected (Enter press)
            self._show_handoff_details(row_key)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle row selection (Enter/Space) in data tables.

        For handoffs: opens the action popup for the highlighted row.
        Requires double-action only when clicking (not arrow-key navigation).
        """
        if event.row_key is None:
            return

        row_key = event.row_key.value
        if not row_key:
            return

        # Only handle for handoff-list - open action menu with double-action
        if event.data_table.id == "handoff-list":
            handoff = self.state.handoff.data.get(row_key)
            if not handoff:
                return

            # Only show popup if this row was ALREADY selected (double-action)
            if row_key == self.state.handoff.current_id:
                # Second Enter/click - open popup
                self.push_screen(
                    HandoffActionScreen(handoff.id, handoff.title),
                    callback=self._on_handoff_action_result,
                )
            else:
                # First Enter/click - just select and show details
                # (clicking bypasses row_highlighted, so handle it here too)
                self.state.handoff.current_id = row_key
                self.state.handoff.user_selected_id = row_key
                self._show_handoff_details(row_key)

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle input changes in filter fields."""
        if event.input.id == "handoff-filter":
            self.state.handoff.filter_text = event.value
            self._refresh_handoff_list()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press events."""
        if event.button.id == "clear-filter":
            try:
                filter_input = self.query_one("#handoff-filter", Input)
                filter_input.value = ""
                self.state.handoff.filter_text = ""
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
                if filter_input.has_focus and self.state.handoff.filter_text:
                    filter_input.value = ""
                    self.state.handoff.filter_text = ""
                    self._refresh_handoff_list()
                    event.prevent_default()
                    event.stop()
            except Exception:
                pass

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        """Handle tab activation - load data on first visit (lazy loading)."""
        tab_id = event.pane.id

        # Check if tab needs initial loading (lazy loading)
        # Mark as loaded AFTER success to allow retry on failure
        if not self.state.tabs_loaded.get(tab_id, False):
            if tab_id == "health":
                try:
                    self._update_health()
                    self.state.tabs_loaded[tab_id] = True
                except Exception as e:
                    self.notify(f"Error loading health: {e}", severity="error")
            elif tab_id == "state":
                try:
                    self._update_state()
                    self.state.tabs_loaded[tab_id] = True
                except Exception as e:
                    self.notify(f"Error loading state: {e}", severity="error")
            elif tab_id == "session":
                self.state.tabs_loaded[tab_id] = True  # Prevent re-trigger
                self._setup_session_list_async()
            elif tab_id == "handoffs":
                try:
                    self._setup_handoff_list()
                    self.state.tabs_loaded[tab_id] = True
                except Exception as e:
                    self.notify(f"Error loading handoffs: {e}", severity="error")
            elif tab_id == "charts":
                try:
                    self._update_charts()
                    self.state.tabs_loaded[tab_id] = True
                except Exception as e:
                    self.notify(f"Error loading charts: {e}", severity="error")

        # Existing "live" tab handling - reset scroll state
        if tab_id == "live":
            # Reset auto-scroll when switching to live tab
            self.state.live_activity_user_scrolled = False
            try:
                event_log = self.query_one("#event-log", RichLog)
                event_log.auto_scroll = True
                # Scroll to bottom to show latest events
                self.call_after_refresh(event_log.scroll_end)
            except Exception:
                pass

    def _on_handoff_action_result(self, result: str) -> None:
        """Handle result from HandoffActionScreen.

        Args:
            result: Action result string (e.g., 'complete', 'archive', 'status:blocked')
        """
        if not result:
            return

        handoff_id = self.state.handoff.current_id
        if not handoff_id:
            self.notify("No handoff selected", severity="error")
            return

        if result == "complete":
            # Complete the handoff
            try:
                mgr = _get_lessons_manager()
                mgr.handoff_complete(handoff_id)
                self.notify(f"Handoff {handoff_id} completed")
            except Exception as e:
                self.notify(f"Error completing handoff: {e}", severity="error")
                return
        elif result == "archive":
            # Archive the handoff
            try:
                mgr = _get_lessons_manager()
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
        if column_key == self.state.session.sort.column:
            self.state.session.sort.reverse = not self.state.session.sort.reverse
        else:
            self.state.session.sort.column = column_key
            self.state.session.sort.reverse = False

        self._sort_session_table(column_key, self.state.session.sort.reverse)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle chart time period selection."""
        if event.option_list.id == "chart-period-selector":
            period_hours = int(event.option.id)
            self.state.chart_period_hours = period_hours
            self._update_charts()

    def _sort_session_table(self, column_key: str, reverse: bool) -> None:
        """Sort the session table by the given column."""
        session_table = self.query_one("#session-list", DataTable)

        # Define sort key based on column (using TranscriptSummary)
        def get_sort_value(session_id: str):
            summary = self.state.session.data.get(session_id)
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
            self.state.session.data.keys(),
            key=get_sort_value,
            reverse=reverse,
        )

        # Clear and repopulate table in sorted order
        session_table.clear()
        for session_id in sorted_sessions:
            summary = self.state.session.data[session_id]
            if not isinstance(summary, TranscriptSummary):
                continue

            self._populate_session_row(session_table, session_id, summary)

    def _show_session_events(self, session_id: str) -> None:
        """Display transcript timeline for a selected session."""
        session_log = self.query_one("#session-events", RichLog)

        # Check if we're viewing the same session (to avoid scroll reset)
        is_same_session = self.state.session.current_id == session_id

        # Save scroll position before clearing (only for same session refresh)
        saved_scroll_x = session_log.scroll_x if is_same_session else None
        saved_scroll_y = session_log.scroll_y if is_same_session else None

        session_log.clear()

        # Update tracking
        self.state.session.current_id = session_id

        # Get the summary from cached data
        summary = self.state.session.data.get(session_id)
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
        session_log.write(f"[bold]Session:[/bold] {session_id}")
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
                # USER: [HH:MM:SS] USER    "First 200 chars of content..."
                content = render_tags(msg.content[:200])
                content = content.replace("\n", " ")
                if len(msg.content) > 200:
                    content += "..."
                session_log.write(f"[cyan][{time_str}] USER    \"{content}\"[/cyan]")

            elif msg.type == "assistant":
                if msg.tools_used:
                    # ASSISTANT with tools: [HH:MM:SS] TOOL    Read, Bash, Edit
                    tools_str = ", ".join(msg.tools_used)
                    session_log.write(f"[yellow][{time_str}] TOOL    {tools_str}[/yellow]")
                else:
                    # ASSISTANT text only: [HH:MM:SS] CLAUDE  "First 200 chars of response..."
                    content = render_tags(msg.content[:200])
                    content = content.replace("\n", " ")
                    if len(msg.content) > 200:
                        content += "..."
                    session_log.write(f"[green][{time_str}] CLAUDE  \"{content}\"[/green]")

        # Handle scroll position: restore for same session, scroll to top for new session
        if is_same_session and saved_scroll_x is not None and saved_scroll_y is not None:
            # Restore scroll position on refresh of same session
            def restore_scroll() -> None:
                session_log.scroll_x = min(saved_scroll_x, session_log.max_scroll_x)
                session_log.scroll_y = min(saved_scroll_y, session_log.max_scroll_y)

            self.call_after_refresh(restore_scroll)
        else:
            # Scroll to top when viewing a different session
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
        """Update the filter status indicator (no-op, widget removed for space)."""
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
        if self.state.handoff.show_completed:
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
                if not self.state.handoff.show_completed and not self._is_recently_completed(handoff):
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
        handoff_table.add_column("Age", key="age")
        handoff_table.add_column("Updated", key="updated")
        handoff_table.add_column("Tried", key="tried")
        handoff_table.add_column("Next", key="next")

        # Hide timeline widget initially (list view is default)
        timeline = self.query_one("#handoff-timeline", RichLog)
        timeline.display = False

        # Clear any existing handoff data
        self.state.handoff.data.clear()

        # Get handoffs from StateReader
        handoffs = self.state_reader.get_handoffs()

        # Update the section title with counts
        self._update_handoff_title(handoffs)

        # Parse the current filter
        parsed_filter = self._parse_handoff_filter(self.state.handoff.filter_text)

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
            self.state.handoff.data[handoff.id] = handoff
            self._populate_handoff_row(handoff_table, handoff)

        # Store total for filter status updates
        self.state.handoff.total_count = total_visible
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

        # Format updated date with relative labels
        updated_display = _format_handoff_date(handoff.updated)

        # Count tried and next steps
        tried_count = str(len(handoff.tried_steps))
        # For completed handoffs, show "-" instead of next count
        next_count = "-" if handoff.status == "completed" else str(len(handoff.next_steps))

        row_data = [
            handoff.id[:12] if len(handoff.id) > 12 else handoff.id,
            title,
            status_display,
            handoff.phase,
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

        # Check if viewing same handoff (refresh) vs new selection
        is_same_handoff = self.state.handoff.displayed_id == handoff_id
        saved_scroll_x = details_log.scroll_x if is_same_handoff else None
        saved_scroll_y = details_log.scroll_y if is_same_handoff else None

        details_log.clear()

        # Clear navigation state
        self.state.handoff.detail_sessions = []
        self.state.handoff.detail_blockers = []

        handoff = self.state.handoff.data.get(handoff_id)
        if handoff is None:
            details_log.write("[dim]No handoff data available[/dim]")
            return

        # Header with ID and title
        details_log.write(f"[bold cyan]{handoff.id}[/bold cyan] {handoff.title}")
        details_log.write("")

        # Combined status/phase line
        status_colors = {
            "not_started": "dim",
            "in_progress": "green",
            "blocked": "red",
            "ready_for_review": "yellow",
            "completed": "cyan",
        }
        status_color = status_colors.get(handoff.status, "white")
        details_log.write(
            f"[{status_color}]{handoff.status}[/{status_color}] ({handoff.phase}) | "
            f"Agent: {handoff.agent}"
        )

        # Get sessions early for time tracking
        sessions = self._get_sessions_for_handoff(handoff_id)
        session_count = len(sessions) if sessions else 0

        # Time tracking: sessions and duration
        duration_str = f"{handoff.age_days}d" if handoff.age_days > 0 else "today"
        created_display = _format_handoff_date(handoff.created)
        updated_display = _format_handoff_date(handoff.updated)
        details_log.write(
            f"[bold]Created:[/bold] {created_display} | "
            f"[bold]Updated:[/bold] {updated_display}"
        )
        details_log.write(
            f"[bold]Time:[/bold] {session_count} session{'s' if session_count != 1 else ''} "
            f"over {duration_str}"
        )
        details_log.write("")

        # Completion summary (prominent for completed handoffs)
        if handoff.status == "completed" and handoff.handoff and handoff.handoff.summary:
            details_log.write("[bold green]Completion Summary[/bold green]")
            details_log.write(f"  {handoff.handoff.summary}")
            details_log.write("")

        # Project
        if handoff.project:
            details_log.write(f"[bold]Project:[/bold] {handoff.project}")
            details_log.write("")

        # Blocked by (store for navigation)
        if handoff.blocked_by:
            self.state.handoff.detail_blockers = list(handoff.blocked_by)
            details_log.write(
                f"[bold red]Blocked By:[/bold red] {', '.join(handoff.blocked_by)} "
                f"[dim](press 'b' to view)[/dim]"
            )
            details_log.write("")

        # Description
        if handoff.description:
            details_log.write(f"[bold]Description:[/bold] {handoff.description}")
        else:
            details_log.write("[dim](no description)[/dim]")
        details_log.write("")

        # Tried steps with summary counts and icons
        if handoff.tried_steps:
            success_count = sum(1 for s in handoff.tried_steps if s.outcome == "success")
            fail_count = sum(1 for s in handoff.tried_steps if s.outcome == "fail")
            partial_count = sum(1 for s in handoff.tried_steps if s.outcome == "partial")

            header = f"[bold]Tried ({len(handoff.tried_steps)}):[/bold]"
            if success_count:
                header += f" [green]{success_count}[/green]"
            if fail_count:
                header += f" [red]{fail_count}[/red]"
            if partial_count:
                header += f" [yellow]{partial_count}~[/yellow]"

            details_log.write(header)
            for i, step in enumerate(handoff.tried_steps, 1):
                outcome_icons = {"success": "[green][/green]", "fail": "[red][/red]", "partial": "[yellow]~[/yellow]"}
                icon = outcome_icons.get(step.outcome, "?")
                details_log.write(f"  {i}. {icon} {step.description}")
        else:
            details_log.write("[dim]Tried: none[/dim]")
        details_log.write("")

        # Current progress (in-progress todo)
        if handoff.checkpoint:
            details_log.write(f"[bold cyan]In Progress:[/bold cyan] {handoff.checkpoint}")
            details_log.write("")

        # Next steps (pending todos) - filter bogus items
        if handoff.next_steps:
            valid_next_steps = [
                item for item in handoff.next_steps
                if item and item.strip() and item.strip() not in ("-", "--", "---")
            ]
            if valid_next_steps:
                details_log.write(f"[bold]Pending ({len(valid_next_steps)}):[/bold]")
                for item in valid_next_steps:
                    details_log.write(f"  [dim]○[/dim] {item}")
                details_log.write("")

        # Completed section - show tried steps with outcome="success"
        if handoff.tried_steps:
            completed_steps = [s for s in handoff.tried_steps if s.outcome == "success"]
            if completed_steps:
                details_log.write(f"[bold green]Completed ({len(completed_steps)}):[/bold green]")
                for step in completed_steps:
                    details_log.write(f"  [green][/green] {step.description}")
                details_log.write("")

        # Refs
        if handoff.refs:
            details_log.write(f"[bold]Refs:[/bold] {', '.join(handoff.refs)}")
            details_log.write("")

        # Transcript Stats section (lightweight context, no LLM)
        # Check if we've already tried extraction (key exists, even if None)
        if handoff_id in self.state.handoff.lightweight_context:
            lw_ctx = self.state.handoff.lightweight_context[handoff_id]
            if lw_ctx:
                details_log.write("[bold cyan]Transcript Stats[/bold cyan]")
                # Tool usage summary
                if lw_ctx.tool_counts:
                    tool_summary = ", ".join(
                        f"{count} {name}" for name, count in
                        sorted(lw_ctx.tool_counts.items(), key=lambda x: -x[1])[:6]
                    )
                    details_log.write(f"  [bold]Tools:[/bold] {tool_summary}")
                # Files modified (most important)
                if lw_ctx.files_modified:
                    files_str = ", ".join(lw_ctx.files_modified[:8])
                    if len(lw_ctx.files_modified) > 8:
                        files_str += f" +{len(lw_ctx.files_modified) - 8} more"
                    details_log.write(f"  [bold]Modified:[/bold] {files_str}")
                # Files touched (read)
                read_only = [f for f in lw_ctx.files_touched if f not in lw_ctx.files_modified]
                if read_only:
                    files_str = ", ".join(read_only[:6])
                    if len(read_only) > 6:
                        files_str += f" +{len(read_only) - 6} more"
                    details_log.write(f"  [bold]Read:[/bold] {files_str}")
                # Message count
                details_log.write(f"  [bold]Messages:[/bold] {lw_ctx.message_count}")
                # Last user message
                if lw_ctx.last_user_message:
                    details_log.write(f"  [bold]Last:[/bold] [dim]{lw_ctx.last_user_message}[/dim]")
                details_log.write("")
            # else: lw_ctx is None means no transcript - show nothing
        elif handoff_id in self.state.handoff.extracting_context:
            details_log.write("[dim]Loading transcript stats...[/dim]")
            details_log.write("")
        else:
            # Mark as extracting in main thread BEFORE dispatching to avoid race
            self.state.handoff.extracting_context.add(handoff_id)
            self._extract_lightweight_context(handoff_id)
            details_log.write("[dim]Loading transcript stats...[/dim]")
            details_log.write("")

        # Handoff Context section (enriched via LLM)
        if handoff.handoff:
            ctx = handoff.handoff
            # Only show section header if we have content (and not already shown completion summary)
            has_context = (
                ctx.git_ref or
                (ctx.summary and handoff.status != "completed") or
                ctx.critical_files or ctx.recent_changes or
                ctx.learnings or ctx.blockers
            )
            if has_context:
                details_log.write("[bold cyan]Handoff Context[/bold cyan]")

                # Git ref (abbreviated to 8 chars)
                if ctx.git_ref:
                    short_ref = ctx.git_ref[:8] if len(ctx.git_ref) >= 8 else ctx.git_ref
                    details_log.write(f"  [bold]Git:[/bold] {short_ref}")

                # Summary (only if not completed - already shown above)
                if ctx.summary and handoff.status != "completed":
                    details_log.write(f"  [bold]Summary:[/bold] {ctx.summary}")

                # Critical files
                if ctx.critical_files:
                    details_log.write(
                        f"  [bold]Critical Files:[/bold] {', '.join(ctx.critical_files)}"
                    )

                # Recent changes (git changes)
                if ctx.recent_changes:
                    details_log.write(f"  [bold]Git Changes ({len(ctx.recent_changes)}):[/bold]")
                    for change in ctx.recent_changes[:10]:
                        details_log.write(f"    [dim]•[/dim] {change}")
                    if len(ctx.recent_changes) > 10:
                        details_log.write(f"    [dim]... and {len(ctx.recent_changes) - 10} more[/dim]")

                # Learnings with icons
                if ctx.learnings:
                    details_log.write(f"  [bold]Learnings:[/bold]")
                    for learning in ctx.learnings:
                        # Check if it looks like a lesson citation [L001] or [S001]
                        stripped = learning.strip()
                        if stripped.startswith("[L") or stripped.startswith("[S"):
                            details_log.write(f"    [blue][/blue] {learning}")
                        else:
                            details_log.write(f"    [yellow][/yellow] {learning}")

                # Blockers
                if ctx.blockers:
                    details_log.write(f"  [bold red]Blockers:[/bold red]")
                    for blocker in ctx.blockers:
                        details_log.write(f"    [red][/red] {blocker}")

                details_log.write("")
        else:
            details_log.write("[dim](not yet enriched - press 'e' to extract context)[/dim]")
            details_log.write("")

        # Sessions section with numbered navigation
        if sessions:
            self.state.handoff.detail_sessions = sessions
            details_log.write(f"[bold cyan]Sessions ({len(sessions)})[/bold cyan] [dim](press 1-9 to navigate)[/dim]")
            for i, session in enumerate(sessions[:9], 1):  # Limit to 9 for single-digit nav
                session_id = session.get("session_id", "")
                created = session.get("created", "")
                # Format the created timestamp (show full datetime)
                if created and "T" in created:
                    # Convert ISO format to readable datetime
                    created_display = created.replace("T", " ").split(".")[0]
                else:
                    created_display = created
                # Show truncated ID for UUIDs, full ID for short ones
                if len(session_id) > 20:
                    session_display = f"{session_id[:12]}..."
                else:
                    session_display = session_id
                details_log.write(f"  [{i}] {session_display} ({created_display})")
            if len(sessions) > 9:
                details_log.write(f"  [dim]... and {len(sessions) - 9} more[/dim]")
        else:
            details_log.write("[dim](no sessions linked)[/dim]")

        # Track displayed handoff and handle scroll position
        self.state.handoff.displayed_id = handoff_id
        if is_same_handoff and saved_scroll_x is not None and saved_scroll_y is not None:
            # Restore scroll position on refresh
            def restore_scroll() -> None:
                details_log.scroll_x = min(saved_scroll_x, details_log.max_scroll_x)
                details_log.scroll_y = min(saved_scroll_y, details_log.max_scroll_y)

            self.call_after_refresh(restore_scroll)
        else:
            # Scroll to top for new selection
            self.call_after_refresh(details_log.scroll_home)

    def _navigate_to_handoff(self, handoff_id: str) -> None:
        """Navigate to handoffs tab and select the given handoff.

        Args:
            handoff_id: The handoff ID to navigate to (e.g., 'hf-abc1234')
        """
        try:
            # Ensure handoffs tab data is loaded (lazy loading support)
            if not self.state.tabs_loaded.get("handoffs", False):
                self._setup_handoff_list()
                self.state.tabs_loaded["handoffs"] = True

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
            # Ensure session tab data is loaded (lazy loading support)
            if not self.state.tabs_loaded.get("session", False):
                self._setup_session_list()
                self.state.tabs_loaded["session"] = True

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

    def _get_transcript_path_for_handoff(self, handoff_id: str) -> Optional[str]:
        """Get the most recent transcript path for a handoff.

        Args:
            handoff_id: The handoff ID to find transcript for

        Returns:
            Path to transcript file, or None if not found
        """
        import json

        session_handoffs_file = self.state_reader.state_dir / "session-handoffs.json"
        if not session_handoffs_file.exists():
            return None

        try:
            data = json.loads(session_handoffs_file.read_text())
        except (json.JSONDecodeError, OSError):
            return None

        # Find sessions linked to this handoff, sorted by created time
        linked = []
        for session_id, entry in data.items():
            if isinstance(entry, dict) and entry.get("handoff_id") == handoff_id:
                transcript_path = entry.get("transcript_path")
                created = entry.get("created", "")
                if transcript_path:
                    linked.append((created, transcript_path))

        if not linked:
            return None

        # Return most recent transcript
        linked.sort(key=lambda x: x[0], reverse=True)
        return linked[0][1]

    @work(thread=True)
    def _extract_lightweight_context(self, handoff_id: str) -> None:
        """Extract lightweight context for a handoff in background thread.

        Note: Caller should add handoff_id to extracting_context before calling
        to avoid race conditions between check and dispatch.

        Args:
            handoff_id: The handoff ID to extract context for
        """
        # Skip if already cached (another extraction may have completed)
        if handoff_id in self.state.handoff.lightweight_context:
            self.state.handoff.extracting_context.discard(handoff_id)
            return

        try:
            # Get transcript path
            transcript_path = self._get_transcript_path_for_handoff(handoff_id)
            if not transcript_path:
                # Cache as "no transcript" so we don't keep trying
                self.state.handoff.lightweight_context[handoff_id] = None
            else:
                # Import the extractor
                try:
                    from core.context_extractor import extract_lightweight_context
                except ImportError:
                    from context_extractor import extract_lightweight_context

                # Extract context (file parsing only, no API)
                context = extract_lightweight_context(transcript_path)
                # Cache result (even if None, to avoid retrying)
                self.state.handoff.lightweight_context[handoff_id] = context

            # Always refresh display when done
            current_id = self.state.handoff.user_selected_id or self.state.handoff.current_id
            if current_id == handoff_id:
                self.call_from_thread(self._show_handoff_details, handoff_id)
        finally:
            self.state.handoff.extracting_context.discard(handoff_id)

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
        if self.state.session.current_id is None:
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
                entry = data.get(self.state.session.current_id)
                if isinstance(entry, dict):
                    handoff_id = entry.get("handoff_id")
            except (json.JSONDecodeError, OSError):
                pass

        if handoff_id:
            self._navigate_to_handoff(handoff_id)
        else:
            # Try date-based matching as fallback
            summary = self.state.session.data.get(self.state.session.current_id)
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

    def action_goto_blocker(self) -> None:
        """Navigate to the first blocking handoff from handoff details."""
        # Only active when viewing handoff details with blockers
        try:
            tabs = self.query_one(TabbedContent)
            if tabs.active != "handoffs":
                return
        except Exception:
            return

        if not self.state.handoff.detail_blockers:
            return

        # Navigate to first blocker
        blocker_id = self.state.handoff.detail_blockers[0]
        self._navigate_to_handoff(blocker_id)

    def _action_goto_session(self, index: int) -> None:
        """Navigate to session by index (0-based) from handoff details."""
        # Only active when viewing handoff details with sessions
        try:
            tabs = self.query_one(TabbedContent)
            if tabs.active != "handoffs":
                return
        except Exception:
            return

        if not self.state.handoff.detail_sessions or index >= len(self.state.handoff.detail_sessions):
            return

        session_id = self.state.handoff.detail_sessions[index].get("session_id", "")
        if session_id:
            self._navigate_to_session(session_id)

    def action_goto_session_1(self) -> None:
        """Navigate to session 1 from handoff details."""
        self._action_goto_session(0)

    def action_goto_session_2(self) -> None:
        """Navigate to session 2 from handoff details."""
        self._action_goto_session(1)

    def action_goto_session_3(self) -> None:
        """Navigate to session 3 from handoff details."""
        self._action_goto_session(2)

    def action_goto_session_4(self) -> None:
        """Navigate to session 4 from handoff details."""
        self._action_goto_session(3)

    def action_goto_session_5(self) -> None:
        """Navigate to session 5 from handoff details."""
        self._action_goto_session(4)

    def action_goto_session_6(self) -> None:
        """Navigate to session 6 from handoff details."""
        self._action_goto_session(5)

    def action_goto_session_7(self) -> None:
        """Navigate to session 7 from handoff details."""
        self._action_goto_session(6)

    def action_goto_session_8(self) -> None:
        """Navigate to session 8 from handoff details."""
        self._action_goto_session(7)

    def action_goto_session_9(self) -> None:
        """Navigate to session 9 from handoff details."""
        self._action_goto_session(8)

    def _refresh_handoff_list(self) -> None:
        """Refresh the handoffs list with current filter settings.

        Preserves scroll position and user selection across refresh.
        """
        handoff_table = self.query_one("#handoff-list", DataTable)

        # Save scroll position and cursor row before clearing
        saved_scroll_x = handoff_table.scroll_x
        saved_scroll_y = handoff_table.scroll_y
        saved_cursor_row = handoff_table.cursor_row

        handoff_table.clear()
        self.state.handoff.data.clear()

        # Get handoffs from StateReader
        handoffs = self.state_reader.get_handoffs()

        # Update the section title with counts
        self._update_handoff_title(handoffs)

        # Parse the current filter
        parsed_filter = self._parse_handoff_filter(self.state.handoff.filter_text)

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
            self.state.handoff.data[handoff.id] = handoff
            self._populate_handoff_row(handoff_table, handoff)

        # Store total for filter status updates
        self.state.handoff.total_count = total_visible
        self._update_filter_status(visible_count, total_visible)

        # Restore scroll position FIRST (before cursor movement)
        # This prevents the selected item from jumping to the bottom of visible area
        handoff_table.scroll_x = min(saved_scroll_x, handoff_table.max_scroll_x)
        handoff_table.scroll_y = min(saved_scroll_y, handoff_table.max_scroll_y)

        # Restore cursor position AFTER scroll (row is already visible, no auto-scroll triggered)
        # (DataTable auto-selects first row when populated, causing visual flicker)
        if self.state.handoff.user_selected_id is not None:
            if self.state.handoff.user_selected_id in self.state.handoff.data:
                # Find the row index for the previously selected handoff
                row_keys = list(handoff_table.rows.keys())
                for idx, row_key in enumerate(row_keys):
                    if row_key.value == self.state.handoff.user_selected_id:
                        handoff_table.move_cursor(row=idx, scroll=False)
                        break
            else:
                # Handoff was removed/archived, clear the details panel
                details_log = self.query_one("#handoff-details", RichLog)
                details_log.clear()
                details_log.write("[dim]Handoff no longer available[/dim]")
                if self.state.handoff.current_id == self.state.handoff.user_selected_id:
                    self.state.handoff.current_id = None
                self.state.handoff.user_selected_id = None
        else:
            # No explicit selection - restore cursor row if valid
            if saved_cursor_row is not None and saved_cursor_row < handoff_table.row_count:
                handoff_table.move_cursor(row=saved_cursor_row, scroll=False)

        # Clear confirmed selection if the handoff was removed
        if self.state.handoff.current_id is not None:
            if self.state.handoff.current_id not in self.state.handoff.data:
                self.state.handoff.current_id = None

        # Defer only the details refresh (scroll already restored above)
        def restore_details() -> None:
            if self.state.handoff.user_selected_id is not None:
                if self.state.handoff.user_selected_id in self.state.handoff.data:
                    self._show_handoff_details(self.state.handoff.user_selected_id)

        self.call_after_refresh(restore_details)

    def action_toggle_completed(self) -> None:
        """Toggle visibility of completed handoffs."""
        # Only applies when on handoffs tab
        try:
            tabs = self.query_one(TabbedContent)
            if tabs.active != "handoffs":
                return
        except Exception:
            return

        self.state.handoff.show_completed = not self.state.handoff.show_completed
        self._refresh_handoff_list()

        status = "shown" if self.state.handoff.show_completed else "hidden"
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

        self.state.session.timeline_view = not self.state.session.timeline_view

        # Show/hide the appropriate widgets
        table = self.query_one("#handoff-list", DataTable)
        timeline = self.query_one("#handoff-timeline", RichLog)

        table.display = not self.state.session.timeline_view
        timeline.display = self.state.session.timeline_view

        if self.state.session.timeline_view:
            self._render_timeline()
            self.notify("Timeline view")
        else:
            self.notify("List view")

    def _render_timeline(self) -> None:
        """Render handoffs as a timeline with colored bars."""
        timeline = self.query_one("#handoff-timeline", RichLog)
        timeline.clear()

        # Get handoffs data
        handoffs = list(self.state.handoff.data.values())
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

    def _compute_hourly_activity(self, events: List[DebugEvent], hours: int = 24) -> List[float]:
        """
        Compute activity counts aggregated by time bucket.

        For 24h: 24 hourly buckets
        For 7d (168h): 7 daily buckets
        For 30d (720h): 30 daily buckets

        Args:
            events: List of debug events
            hours: Time period in hours (24, 168, or 720)

        Returns:
            List of floats representing event counts per bucket (oldest to newest)
        """
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=hours)

        # Determine bucket configuration
        if hours <= 24:
            # Hourly buckets
            num_buckets = hours
            bucket_hours = 1
        else:
            # Daily buckets for 7d and 30d
            num_buckets = hours // 24
            bucket_hours = 24

        # Initialize buckets
        buckets: defaultdict[int, int] = defaultdict(int)

        for event in events:
            ts = event.timestamp_dt
            if ts is None:
                continue
            if ts < cutoff:
                continue

            # Calculate bucket index
            hours_ago = (now - ts).total_seconds() / 3600
            bucket_idx = int(hours_ago / bucket_hours)

            if 0 <= bucket_idx < num_buckets:
                # Reverse index so oldest is first
                final_idx = num_buckets - 1 - bucket_idx
                buckets[final_idx] += 1

        # Convert to list (ensure all buckets represented)
        return [float(buckets.get(i, 0)) for i in range(num_buckets)]

    def _update_activity_chart(self, events: List[DebugEvent]) -> None:
        """Update the activity timeline bar chart."""
        try:
            chart = self.query_one("#activity-chart", PlotextPlot)
        except Exception:
            return

        period_hours = self.state.chart_period_hours
        data = self._compute_hourly_activity(events, hours=period_hours)

        # Clear and redraw
        chart.plt.clear_figure()

        # Generate labels and title based on period
        if period_hours <= 24:
            title = f"Activity Timeline ({period_hours}h)"
            xlabel = "Hours Ago"
            num_buckets = period_hours
            positions = list(range(num_buckets))
            labels = [f"{num_buckets - 1 - h}h" if h % 4 == 0 else "" for h in positions]
            tick_positions = positions[::4]
            tick_labels = labels[::4]
        elif period_hours <= 168:  # 7 days
            title = "Activity Timeline (7d)"
            xlabel = "Days Ago"
            num_buckets = period_hours // 24
            positions = list(range(num_buckets))
            labels = [f"{num_buckets - 1 - d}d" for d in positions]
            tick_positions = positions
            tick_labels = labels
        else:  # 30 days
            title = "Activity Timeline (30d)"
            xlabel = "Days Ago"
            num_buckets = period_hours // 24
            positions = list(range(num_buckets))
            labels = [f"{num_buckets - 1 - d}" if d % 5 == 0 else "" for d in positions]
            tick_positions = positions[::5]
            tick_labels = [l for l in labels if l]

        chart.plt.title(title)
        chart.plt.xlabel(xlabel)
        chart.plt.bar(positions, data, width=0.8)
        chart.plt.xticks(tick_positions, tick_labels)
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
        self.state.paused = not self.state.paused
        status = "PAUSED" if self.state.paused else "RUNNING"
        self.notify(f"Auto-refresh: {status}")

    def action_refresh(self) -> None:
        """Manual refresh of all views.

        Only refreshes tabs that have been loaded (lazy loading awareness).
        """
        # Always refresh events (live tab is always loaded at startup)
        if self.state.tabs_loaded.get("live", False):
            self._load_events()
        # Only refresh tabs that have been loaded
        if self.state.tabs_loaded.get("health", False):
            self._update_health()
        if self.state.tabs_loaded.get("state", False):
            self._update_state()
        if self.state.tabs_loaded.get("session", False):
            self._refresh_session_list()
        if self.state.tabs_loaded.get("handoffs", False):
            self._refresh_handoff_list()
        if self.state.tabs_loaded.get("charts", False):
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
        self.state.session.show_system = not self.state.session.show_system
        self._refresh_session_list()
        self.notify(f"System sessions {'shown' if self.state.session.show_system else 'hidden'}")

    def action_expand_session(self) -> None:
        """Context-sensitive 'e' key action.

        On session tab: Open modal with expanded session details.
        On handoffs tab: Enrich the selected handoff with transcript context.
        """
        # Check which tab is active
        try:
            tabs = self.query_one(TabbedContent)
            active_tab = tabs.active
        except Exception:
            active_tab = None

        if active_tab == "handoffs":
            # Enrich handoff
            self._enrich_selected_handoff()
            return

        # Default: expand session (for session tab or other contexts)
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

        if not session_id or session_id not in self.state.session.data:
            self.notify("Session data not found", severity="error")
            return

        # Get session data and open modal
        summary = self.state.session.data[session_id]
        if isinstance(summary, TranscriptSummary):
            self.push_screen(SessionDetailModal(session_id, summary))
        else:
            self.notify("Invalid session data format", severity="error")

    @work(thread=True)
    def _enrich_selected_handoff(self) -> None:
        """Enrich the currently selected handoff with context extraction."""
        # Use _user_selected_handoff_id (set on arrow navigation) so 'e' works
        # without requiring a prior Enter press
        handoff_id = self.state.handoff.user_selected_id or self.state.handoff.current_id
        if not handoff_id:
            self.call_from_thread(self.notify, "No handoff selected", severity="warning")
            return

        try:
            from core.handoffs import enrich_handoff
        except ImportError:
            from handoffs import enrich_handoff

        result = enrich_handoff(handoff_id)

        if result.success:
            self.call_from_thread(self.notify, f"Enriched {handoff_id}", severity="information")
            self.call_from_thread(self._refresh_handoff_list)
        else:
            error_msg = result.error or "Unknown error"
            self.call_from_thread(self.notify, f"Enrichment failed: {error_msg}", severity="error")

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

        if not session_id or session_id not in self.state.session.data:
            self.notify("Session data not found", severity="error")
            return

        # Format session data for clipboard (using TranscriptSummary)
        summary = self.state.session.data[session_id]
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
        saved_scroll_x = session_table.scroll_x
        saved_scroll_y = session_table.scroll_y

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

        self.state.session.data.clear()

        # Get sessions from TranscriptReader
        # _show_all toggles: all projects + all sessions (including empty) vs current project + non-empty
        if self._show_all:
            sessions = self.transcript_reader.list_all_sessions_fast(limit=50, max_age_hours=168, include_empty=True)  # 7 days
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
            self.state.session.data[session_id] = summary

            self._populate_session_row(session_table, session_id, summary)

        # Restore scroll position
        session_table.scroll_x = min(saved_scroll_x, session_table.max_scroll_x)
        session_table.scroll_y = min(saved_scroll_y, session_table.max_scroll_y)

        # Preserve user's selection if it still exists in the new data
        if self.state.session.user_selected_id is not None:
            if self.state.session.user_selected_id in self.state.session.data:
                # Find the row index for the previously selected session
                row_keys = list(session_table.rows.keys())
                for idx, row_key in enumerate(row_keys):
                    if row_key.value == self.state.session.user_selected_id:
                        session_table.move_cursor(row=idx, scroll=False)
                        break

    @work(exclusive=True, group="session_refresh")
    async def _refresh_session_list_async(self) -> None:
        """Async worker to refresh session list in background.

        Delegates file I/O to a background thread to avoid blocking the UI.
        """
        # Perform the refresh on main thread (UI operations must be on main thread)
        # But mark this as an async worker so the timer doesn't block
        self._refresh_session_list()

    @work(exclusive=True, group="handoff_refresh")
    async def _refresh_handoff_list_async(self) -> None:
        """Async worker to refresh handoff list in background.

        Delegates file I/O to a background thread to avoid blocking the UI.
        """
        # Perform the refresh on main thread (UI operations must be on main thread)
        # But mark this as an async worker so the timer doesn't block
        self._refresh_handoff_list()

    def _get_dynamic_subtitle(self) -> str:
        """Build dynamic subtitle showing status."""
        parts = []
        if self.state.project_filter:
            parts.append(f"Project: {self.state.project_filter}")
        if self.state.paused:
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
