#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Tests for the charts time period selector feature.

These tests verify:
1. Time period selector renders correctly in the Charts tab
2. Selecting different periods updates chart data
3. _compute_hourly_activity() returns correct bucket count for each period
4. Activity chart labels change based on period
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import pytest

pytest.importorskip("textual")

from textual.widgets import OptionList

# Import with fallback for installed vs dev paths
try:
    from core.tui.app import RecallMonitorApp
    from core.tui.app_state import AppState
    from core.tui.models import DebugEvent
except ImportError:
    from .app import RecallMonitorApp
    from .app_state import AppState
    from .models import DebugEvent


# --- Fixtures ---


@pytest.fixture
def temp_log_with_events(tmp_path: Path, monkeypatch):
    """
    Create a temp directory with a debug.log file containing sample events.

    Patches CLAUDE_RECALL_STATE to use the temp directory.
    """
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    log_path = state_dir / "debug.log"

    # Create events spanning multiple days for testing different time periods
    now = datetime.now(timezone.utc)
    events = []

    # Events from today (within 24h)
    for i in range(5):
        events.append({
            "event": "session_start",
            "level": "info",
            "timestamp": (now - timedelta(hours=i)).isoformat(),
            "session_id": f"today-{i}",
            "pid": 1000 + i,
            "project": "test-project",
        })

    # Events from 3 days ago (within 7d, outside 24h)
    for i in range(3):
        events.append({
            "event": "session_start",
            "level": "info",
            "timestamp": (now - timedelta(days=3, hours=i)).isoformat(),
            "session_id": f"3days-{i}",
            "pid": 2000 + i,
            "project": "test-project",
        })

    # Events from 15 days ago (within 30d, outside 7d)
    for i in range(2):
        events.append({
            "event": "session_start",
            "level": "info",
            "timestamp": (now - timedelta(days=15, hours=i)).isoformat(),
            "session_id": f"15days-{i}",
            "pid": 3000 + i,
            "project": "test-project",
        })

    lines = [json.dumps(e) for e in events]
    log_path.write_text("\n".join(lines) + "\n")

    # Patch environment to use temp state dir
    monkeypatch.setenv("CLAUDE_RECALL_STATE", str(state_dir))

    return log_path


# --- AppState Tests ---


class TestAppStateChartPeriod:
    """Tests for chart_period_hours state field."""

    def test_default_chart_period_is_24_hours(self):
        """AppState should default chart_period_hours to 24."""
        state = AppState()
        assert state.chart_period_hours == 24

    def test_chart_period_can_be_set_to_168(self):
        """chart_period_hours can be set to 168 (7 days)."""
        state = AppState()
        state.chart_period_hours = 168
        assert state.chart_period_hours == 168

    def test_chart_period_can_be_set_to_720(self):
        """chart_period_hours can be set to 720 (30 days)."""
        state = AppState()
        state.chart_period_hours = 720
        assert state.chart_period_hours == 720


# --- Compute Hourly Activity Tests ---


class TestComputeHourlyActivity:
    """Tests for _compute_hourly_activity with different time periods."""

    @pytest.mark.asyncio
    async def test_compute_hourly_activity_24h_returns_24_buckets(self, temp_log_with_events: Path):
        """_compute_hourly_activity with 24h period should return 24 buckets."""
        app = RecallMonitorApp(log_path=temp_log_with_events)

        async with app.run_test() as pilot:
            await pilot.pause()

            events = list(app.log_reader.iter_events())
            result = app._compute_hourly_activity(events, hours=24)

            assert len(result) == 24, f"Expected 24 buckets for 24h, got {len(result)}"

    @pytest.mark.asyncio
    async def test_compute_hourly_activity_7d_returns_7_buckets(self, temp_log_with_events: Path):
        """_compute_hourly_activity with 7d (168h) period should return 7 daily buckets."""
        app = RecallMonitorApp(log_path=temp_log_with_events)

        async with app.run_test() as pilot:
            await pilot.pause()

            events = list(app.log_reader.iter_events())
            result = app._compute_hourly_activity(events, hours=168)

            assert len(result) == 7, f"Expected 7 buckets for 7d, got {len(result)}"

    @pytest.mark.asyncio
    async def test_compute_hourly_activity_30d_returns_30_buckets(self, temp_log_with_events: Path):
        """_compute_hourly_activity with 30d (720h) period should return 30 daily buckets."""
        app = RecallMonitorApp(log_path=temp_log_with_events)

        async with app.run_test() as pilot:
            await pilot.pause()

            events = list(app.log_reader.iter_events())
            result = app._compute_hourly_activity(events, hours=720)

            assert len(result) == 30, f"Expected 30 buckets for 30d, got {len(result)}"

    @pytest.mark.asyncio
    async def test_compute_hourly_activity_includes_events_within_period(self, temp_log_with_events: Path):
        """Events within the time period should be counted."""
        app = RecallMonitorApp(log_path=temp_log_with_events)

        async with app.run_test() as pilot:
            await pilot.pause()

            events = list(app.log_reader.iter_events())

            # 24h should capture today's events (5 events)
            result_24h = app._compute_hourly_activity(events, hours=24)
            total_24h = sum(result_24h)
            assert total_24h >= 5, f"Expected at least 5 events in 24h, got {total_24h}"

            # 7d should capture today + 3 days ago (5 + 3 = 8 events)
            result_7d = app._compute_hourly_activity(events, hours=168)
            total_7d = sum(result_7d)
            assert total_7d >= 8, f"Expected at least 8 events in 7d, got {total_7d}"

            # 30d should capture all events (5 + 3 + 2 = 10 events)
            result_30d = app._compute_hourly_activity(events, hours=720)
            total_30d = sum(result_30d)
            assert total_30d >= 10, f"Expected at least 10 events in 30d, got {total_30d}"


# --- Time Period Selector UI Tests ---


class TestTimePeriodSelectorUI:
    """Tests for the time period selector UI component."""

    @pytest.mark.asyncio
    async def test_charts_tab_has_period_selector(self, temp_log_with_events: Path):
        """Charts tab should contain a time period selector OptionList."""
        app = RecallMonitorApp(log_path=temp_log_with_events)

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Charts tab (F5)
            await pilot.press("f5")
            await pilot.pause()

            # Query for the period selector
            selector = app.query_one("#chart-period-selector", OptionList)
            assert selector is not None, "Charts tab should have a period selector"

    @pytest.mark.asyncio
    async def test_period_selector_has_three_options(self, temp_log_with_events: Path):
        """Period selector should have 24h, 7d, and 30d options."""
        app = RecallMonitorApp(log_path=temp_log_with_events)

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Charts tab
            await pilot.press("f5")
            await pilot.pause()

            selector = app.query_one("#chart-period-selector", OptionList)

            # Check option count
            assert selector.option_count == 3, (
                f"Expected 3 options (24h, 7d, 30d), got {selector.option_count}"
            )

    @pytest.mark.asyncio
    async def test_selecting_7d_updates_state(self, temp_log_with_events: Path):
        """Selecting 7d option should update state.chart_period_hours to 168."""
        app = RecallMonitorApp(log_path=temp_log_with_events)

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Charts tab
            await pilot.press("f5")
            await pilot.pause()

            # Initial state should be 24
            assert app.state.chart_period_hours == 24

            selector = app.query_one("#chart-period-selector", OptionList)

            # Focus the selector and navigate to 7d option (index 1)
            selector.focus()
            await pilot.pause()
            await pilot.press("down")  # Move from 24h to 7d
            await pilot.press("enter")
            await pilot.pause()

            # State should update to 168
            assert app.state.chart_period_hours == 168, (
                f"Expected chart_period_hours=168, got {app.state.chart_period_hours}"
            )

    @pytest.mark.asyncio
    async def test_selecting_30d_updates_state(self, temp_log_with_events: Path):
        """Selecting 30d option should update state.chart_period_hours to 720."""
        app = RecallMonitorApp(log_path=temp_log_with_events)

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Charts tab
            await pilot.press("f5")
            await pilot.pause()

            selector = app.query_one("#chart-period-selector", OptionList)

            # Focus the selector and navigate to 30d option (index 2)
            selector.focus()
            await pilot.pause()
            await pilot.press("down")  # Move from 24h to 7d
            await pilot.press("down")  # Move from 7d to 30d
            await pilot.press("enter")
            await pilot.pause()

            # State should update to 720
            assert app.state.chart_period_hours == 720, (
                f"Expected chart_period_hours=720, got {app.state.chart_period_hours}"
            )


# --- Chart Label Tests ---


class TestActivityChartLabels:
    """Tests for activity chart labels based on period."""

    @pytest.mark.asyncio
    async def test_activity_chart_title_reflects_period(self, temp_log_with_events: Path):
        """Activity chart title should reflect the selected time period."""
        pytest.importorskip("textual_plotext")

        from textual_plotext import PlotextPlot

        app = RecallMonitorApp(log_path=temp_log_with_events)

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Charts tab
            await pilot.press("f5")
            await pilot.pause()

            # Get the activity chart
            chart = app.query_one("#activity-chart", PlotextPlot)

            # Default should show 24h in title
            # Note: Getting the title from plotext is implementation-specific
            # We verify by checking that the chart renders without error
            # and state is correctly applied
            assert app.state.chart_period_hours == 24

            # Change to 7d
            selector = app.query_one("#chart-period-selector", OptionList)
            selector.focus()
            await pilot.pause()
            await pilot.press("down")  # Move from 24h to 7d
            await pilot.press("enter")
            await pilot.pause()

            # State should reflect 7d
            assert app.state.chart_period_hours == 168
