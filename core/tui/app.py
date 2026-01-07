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
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    RichLog,
    Static,
    TabbedContent,
    TabPane,
)
from textual import work

try:
    from textual_plotext import PlotextPlot
except ImportError:
    PlotextPlot = None  # type: ignore

try:
    from core.tui.log_reader import LogReader, format_event_line
    from core.tui.models import DebugEvent
    from core.tui.state_reader import StateReader
    from core.tui.stats import StatsAggregator
except ImportError:
    from .log_reader import LogReader, format_event_line
    from .models import DebugEvent
    from .state_reader import StateReader
    from .stats import StatsAggregator


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


def format_event_rich(event: DebugEvent) -> str:
    """
    Format an event as a Rich-markup string for Textual widgets.

    Args:
        event: The debug event to format

    Returns:
        Formatted string with Rich markup
    """
    # Extract time portion
    ts = event.timestamp
    if "T" in ts:
        time_part = ts.split("T")[1][:8]
    else:
        time_part = ts[:8] if len(ts) >= 8 else ts

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
        Binding("p", "toggle_pause", "Pause"),
        Binding("r", "refresh", "Refresh"),
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
                    RichLog(id="session-events", highlight=True, markup=True),
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
                    lines.append(f"  [{lesson.id}] {lesson.title[:40]} ({lesson.uses} uses, vel={lesson.velocity:.1f})")
                lines.append("")

        except Exception as e:
            lines.append(f"[red]Error loading lessons: {e}[/red]")
            lines.append("")

        # Handoffs
        try:
            handoffs = self.state_reader.get_handoffs()
            active_handoffs = [h for h in handoffs if h.is_active]

            lines.append("[bold]Handoffs[/bold]")
            lines.append(f"  Total: {len(handoffs)}")
            lines.append(f"  Active: {len(active_handoffs)}")
            lines.append("")

            if active_handoffs:
                lines.append("[bold]Active Handoffs[/bold]")
                for h in active_handoffs:
                    status_color = "red" if h.is_blocked else "yellow" if h.status == "ready_for_review" else "green"
                    lines.append(f"  [{h.id}] {h.title[:35]}")
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

    def _setup_session_list(self) -> None:
        """Initialize the session list DataTable."""
        session_table = self.query_one("#session-list", DataTable)
        session_table.add_columns("Session ID", "Project", "Events", "Errors", "Citations")

        # Populate with sessions
        sessions = self.log_reader.get_sessions()[:20]  # Limit to 20 most recent

        for session_id in sessions:
            session_stats = self.stats.compute_session_stats(session_id)
            errors = session_stats["errors"]
            error_str = f"[red]{errors}[/red]" if errors > 0 else "0"

            session_table.add_row(
                session_id[:12] + "..." if len(session_id) > 15 else session_id,
                session_stats["project"][:15],
                str(session_stats["event_count"]),
                error_str,
                str(session_stats["citations"]),
                key=session_id,
            )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle session selection in the session list."""
        if event.data_table.id != "session-list":
            return

        session_id = event.row_key.value
        if session_id:
            self._show_session_events(session_id)

    def _show_session_events(self, session_id: str) -> None:
        """Display events for a selected session."""
        session_log = self.query_one("#session-events", RichLog)
        session_log.clear()

        events = self.log_reader.filter_by_session(session_id)
        for event in events:
            session_log.write(format_event_rich(event))

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
        self._update_charts()
        self.notify("Refreshed")

    def _get_dynamic_subtitle(self) -> str:
        """Build dynamic subtitle showing status."""
        parts = []
        if self.project_filter:
            parts.append(f"Project: {self.project_filter}")
        if self._paused:
            parts.append("[PAUSED]")

        now = datetime.now().strftime("%H:%M:%S")
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
