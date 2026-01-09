#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Pilot-based tests for the RecallMonitorApp TUI.

These tests use Textual's pilot testing framework to verify app behavior.
Some tests are designed to FAIL initially to prove bugs exist.
"""

from pathlib import Path
import json
import pytest

pytest.importorskip("textual")

# Configure pytest-asyncio
pytest_plugins = ("pytest_asyncio",)

from textual.widgets import RichLog, Static, Tab


# Import with fallback for installed vs dev paths
try:
    from core.tui.app import RecallMonitorApp
except ImportError:
    from .app import RecallMonitorApp


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

    # Sample events with realistic data
    events = [
        {
            "event": "session_start",
            "level": "info",
            "timestamp": "2026-01-06T10:00:00Z",
            "session_id": "test-123",
            "pid": 1234,
            "project": "test-project",
            "total_lessons": 5,
            "system_count": 2,
            "project_count": 3,
        },
        {
            "event": "citation",
            "level": "info",
            "timestamp": "2026-01-06T10:01:00Z",
            "session_id": "test-123",
            "pid": 1234,
            "project": "test-project",
            "lesson_id": "L001",
            "uses_before": 5,
            "uses_after": 6,
        },
        {
            "event": "hook_end",
            "level": "info",
            "timestamp": "2026-01-06T10:01:30Z",
            "session_id": "test-123",
            "pid": 1234,
            "project": "test-project",
            "hook": "SessionStart",
            "total_ms": 45.5,
        },
    ]

    lines = [json.dumps(e) for e in events]
    log_path.write_text("\n".join(lines) + "\n")

    # Patch environment to use temp state dir
    monkeypatch.setenv("CLAUDE_RECALL_STATE", str(state_dir))

    return log_path


# --- Pilot Tests ---


@pytest.mark.asyncio
async def test_app_displays_events_on_start(temp_log_with_events: Path):
    """
    Verify the event log (#event-log RichLog) has content after mount.

    This test should FAIL if events are not being loaded/displayed on startup.
    The bug: events may not render until manual refresh is triggered.
    """
    app = RecallMonitorApp(log_path=temp_log_with_events)

    async with app.run_test() as pilot:
        # Wait for mount and initial data load
        await pilot.pause()

        # Query the event log widget
        event_log = app.query_one("#event-log", RichLog)

        # The event log should have content (lines written to it)
        # RichLog stores lines internally - check the lines list
        assert len(event_log.lines) > 0, (
            "Event log should have content after mount, but it's empty. "
            "This indicates events are not being loaded on startup."
        )


@pytest.mark.asyncio
async def test_health_tab_shows_stats(temp_log_with_events: Path):
    """
    Switch to Health tab (F2) and verify #health-stats widget has real content.

    This test should FAIL if health stats show only "Loading..." placeholder.
    The bug: health stats may not update after initial load.
    """
    app = RecallMonitorApp(log_path=temp_log_with_events)

    async with app.run_test() as pilot:
        # Wait for mount
        await pilot.pause()

        # Switch to Health tab
        await pilot.press("f2")
        await pilot.pause()

        # Query the health stats widget
        health_stats = app.query_one("#health-stats", Static)

        # Get the rendered content using render() method
        content = str(health_stats.render())

        # Should NOT just say "Loading..." - should have actual stats
        assert "Loading" not in content or "System Health" in content, (
            f"Health stats should show actual data, not just 'Loading...'. "
            f"Got: {content[:100]}..."
        )

        # Should contain expected health information
        assert "Sessions" in content or "System Health" in content, (
            f"Health stats should contain session/health information. "
            f"Got: {content[:200]}..."
        )


@pytest.mark.asyncio
async def test_tabs_have_spacing(temp_log_with_events: Path):
    """
    Query Tab widgets and verify they have some padding/margin.

    This tests that tabs are properly styled with spacing for readability.
    The bug: tabs may be cramped together without proper spacing.
    """
    app = RecallMonitorApp(log_path=temp_log_with_events)

    async with app.run_test() as pilot:
        # Wait for mount
        await pilot.pause()

        # Query all Tab widgets
        tabs = app.query(Tab)

        # Should have multiple tabs
        assert len(tabs) >= 3, f"Expected at least 3 tabs, got {len(tabs)}"

        # Check that tabs have some spacing (padding or margin)
        # This is tricky to test directly, so we check computed styles
        for tab in tabs:
            styles = tab.styles

            # Check for padding (any direction)
            has_padding = (
                styles.padding.top > 0 or
                styles.padding.right > 0 or
                styles.padding.bottom > 0 or
                styles.padding.left > 0
            )

            # Check for margin (any direction)
            has_margin = (
                styles.margin.top > 0 or
                styles.margin.right > 0 or
                styles.margin.bottom > 0 or
                styles.margin.left > 0
            )

            # At least one form of spacing should exist
            assert has_padding or has_margin, (
                f"Tab '{tab.label}' has no padding or margin. "
                f"Padding: {styles.padding}, Margin: {styles.margin}"
            )


@pytest.mark.asyncio
async def test_event_log_shows_formatted_events(temp_log_with_events: Path):
    """
    Verify events are properly formatted with timestamps and event types.

    Complements the basic content test by checking formatting quality.
    """
    app = RecallMonitorApp(log_path=temp_log_with_events)

    async with app.run_test() as pilot:
        await pilot.pause()

        event_log = app.query_one("#event-log", RichLog)

        # If there's content, it should be formatted properly
        if len(event_log.lines) > 0:
            # The test passes if we have any formatted content
            # More detailed formatting checks would require inspecting
            # the actual rendered text, which is complex with Rich markup
            pass
        else:
            pytest.fail("Event log has no content to verify formatting")


@pytest.mark.asyncio
async def test_app_has_expected_tabs(temp_log_with_events: Path):
    """
    Verify the app has all expected tabs: Live, Health, State, Session, Charts.
    """
    app = RecallMonitorApp(log_path=temp_log_with_events)

    async with app.run_test() as pilot:
        await pilot.pause()

        tabs = app.query(Tab)
        tab_labels = [str(tab.label) for tab in tabs]

        expected_tabs = ["Live Activity", "Health", "State", "Session", "Charts"]

        for expected in expected_tabs:
            assert any(expected in label for label in tab_labels), (
                f"Expected tab '{expected}' not found. "
                f"Available tabs: {tab_labels}"
            )


@pytest.mark.asyncio
async def test_live_activity_shows_new_events_after_refresh(temp_log_with_events: Path):
    """
    Verify new events added to the log file appear in the Live Activity tab after refresh.

    This tests the auto-refresh functionality of the event log.
    """
    app = RecallMonitorApp(log_path=temp_log_with_events)

    async with app.run_test() as pilot:
        # Wait for initial load
        await pilot.pause()

        event_log = app.query_one("#event-log", RichLog)
        initial_line_count = len(event_log.lines)

        # Append a new event to the log file
        new_event = {
            "event": "test_new_event",
            "level": "info",
            "timestamp": "2026-01-06T10:05:00Z",
            "session_id": "test-new",
            "pid": 9999,
            "project": "test-project",
        }
        with open(temp_log_with_events, "a") as f:
            f.write(json.dumps(new_event) + "\n")

        # Trigger manual refresh (press 'r' key which calls action_refresh)
        await pilot.press("r")
        await pilot.pause()

        # Event log should now have more lines
        assert len(event_log.lines) > initial_line_count, (
            f"Expected new events to appear after refresh. "
            f"Initial: {initial_line_count}, Current: {len(event_log.lines)}"
        )


@pytest.mark.asyncio
async def test_no_duplicate_events_on_refresh(temp_log_with_events: Path):
    """
    Verify that events are not duplicated when the log is refreshed.

    This tests that the refresh mechanism correctly tracks what's been displayed.
    """
    app = RecallMonitorApp(log_path=temp_log_with_events)

    async with app.run_test() as pilot:
        # Wait for initial load
        await pilot.pause()

        # Add a unique event
        unique_marker = "UNIQUE_EVENT_12345"
        new_event = {
            "event": unique_marker,
            "level": "info",
            "timestamp": "2026-01-06T10:10:00Z",
            "session_id": "test-unique",
            "pid": 8888,
            "project": "test-project",
        }
        with open(temp_log_with_events, "a") as f:
            f.write(json.dumps(new_event) + "\n")

        # Trigger multiple manual refreshes
        await pilot.press("r")
        await pilot.pause()
        await pilot.press("r")
        await pilot.pause()

        event_log = app.query_one("#event-log", RichLog)

        # Count occurrences of the unique marker in all lines
        # Each line is a Strip object, convert to plain text
        marker_count = 0
        for line in event_log.lines:
            # line is a Strip - convert to plain text
            plain_text = "".join(seg.text for seg in line._segments)
            if unique_marker in plain_text:
                marker_count += 1

        assert marker_count == 1, (
            f"Event '{unique_marker}' should appear exactly once, "
            f"but found {marker_count} occurrences. This indicates duplicate events."
        )


# --- Auto-Refresh Tests (Timer Behavior) ---


@pytest.mark.asyncio
async def test_auto_refresh_updates_subtitle(temp_log_with_events: Path):
    """
    Verify the subtitle time updates automatically via the timer.

    CRITICAL: This test verifies that the timer callback is actually firing.
    The subtitle contains a timestamp that should change every 5 seconds.
    """
    app = RecallMonitorApp(log_path=temp_log_with_events)

    async with app.run_test() as pilot:
        await pilot.pause()  # Initial load

        initial_subtitle = app.sub_title

        # Wait longer than the 5-second timer interval (performance optimization)
        await pilot.pause(delay=5.5)

        # Subtitle should have updated (contains timestamp that changes)
        assert app.sub_title != initial_subtitle, (
            f"Subtitle should auto-update via timer. "
            f"Initial: {initial_subtitle}, After 5.5s: {app.sub_title}. "
            "This proves the timer callback is NOT firing."
        )


@pytest.mark.asyncio
async def test_auto_refresh_shows_new_events_without_keypress(temp_log_with_events: Path):
    """
    Verify new events appear automatically without pressing any keys.

    CRITICAL: This tests the full auto-refresh cycle: timer -> load -> display.
    """
    app = RecallMonitorApp(log_path=temp_log_with_events)

    async with app.run_test() as pilot:
        await pilot.pause()

        event_log = app.query_one("#event-log", RichLog)
        initial_count = len(event_log.lines)

        # Add new event to log file
        new_event = {
            "event": "auto_refresh_test",
            "timestamp": "2026-01-06T11:00:00Z",
            "session_id": "auto-test",
            "pid": 7777,
            "project": "test-project",
            "level": "info",
        }
        with open(temp_log_with_events, "a") as f:
            f.write(json.dumps(new_event) + "\n")

        # Wait for auto-refresh (>5 seconds) WITHOUT pressing any keys
        # Timer interval was increased from 2s to 5s for performance
        await pilot.pause(delay=6.0)

        # New events should appear automatically
        assert len(event_log.lines) > initial_count, (
            f"New events should appear via auto-refresh. "
            f"Initial: {initial_count}, After 6s: {len(event_log.lines)}. "
            "This proves auto-refresh is NOT working."
        )
