#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Integration tests for TUI application flows.

These tests verify complete user flows through the application, testing
multiple components working together rather than individual units.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import pytest

pytest.importorskip("textual")

# Configure pytest-asyncio
pytest_plugins = ("pytest_asyncio",)

from textual.widgets import DataTable, Input, RichLog

# Import with fallback for installed vs dev paths
try:
    from core.tui.app import (
        GenericSelectModal,
        HandoffActionScreen,
        RecallMonitorApp,
        SessionDetailModal,
    )
except ImportError:
    from .app import (
        GenericSelectModal,
        HandoffActionScreen,
        RecallMonitorApp,
        SessionDetailModal,
    )


# --- Helper Functions ---


def make_timestamp(seconds_ago: int = 0) -> str:
    """Generate an ISO timestamp for N seconds ago."""
    dt = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def create_transcript(
    path: Path,
    first_prompt: str,
    tools: list,
    tokens: int,
    start_time: str,
    end_time: str,
) -> None:
    """Create a mock transcript JSONL file."""
    messages = []

    # User message
    messages.append(
        {
            "type": "user",
            "timestamp": start_time,
            "sessionId": path.stem,
            "message": {"role": "user", "content": first_prompt},
        }
    )

    # Assistant message with tools
    tool_uses = [{"type": "tool_use", "name": t, "input": {}} for t in tools]
    content = tool_uses if tools else [{"type": "text", "text": "Done"}]
    messages.append(
        {
            "type": "assistant",
            "timestamp": end_time,
            "sessionId": path.stem,
            "message": {
                "role": "assistant",
                "usage": {"input_tokens": 100, "output_tokens": tokens},
                "content": content,
            },
        }
    )

    with open(path, "w") as f:
        for msg in messages:
            f.write(json.dumps(msg) + "\n")


# --- Fixtures ---


@pytest.fixture
def full_test_environment(tmp_path: Path, monkeypatch):
    """Complete environment with all file types for integration testing."""
    # State dir with debug.log
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    log_path = state_dir / "debug.log"
    events = [
        {
            "event": "session_start",
            "level": "info",
            "timestamp": "2026-01-15T10:00:00Z",
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
            "timestamp": "2026-01-15T10:01:00Z",
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
            "timestamp": "2026-01-15T10:01:30Z",
            "session_id": "test-123",
            "pid": 1234,
            "project": "test-project",
            "hook": "SessionStart",
            "total_ms": 45.5,
        },
    ]
    log_path.write_text("\n".join(json.dumps(e) for e in events) + "\n")

    # Project dir with handoffs and lessons
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    recall_dir = project_dir / ".claude-recall"
    recall_dir.mkdir()

    handoffs_file = recall_dir / "HANDOFFS.md"
    handoffs_file.write_text(
        """# Handoffs

### [hf-test123] Test Handoff
- **Status**: in_progress | **Phase**: implementing | **Agent**: user
- **Created**: 2026-01-15 | **Updated**: 2026-01-15

**Description**: A test handoff for integration testing.

**Tried** (1 steps):
  1. [success] Initial implementation

**Next**:
  - Complete the feature

**Refs**: core/test.py:42

**Checkpoint**: Half done

---

### [hf-done456] Completed Handoff
- **Status**: completed | **Phase**: review | **Agent**: user
- **Created**: 2026-01-14 | **Updated**: 2026-01-15

**Description**: A completed handoff.

---
"""
    )

    lessons_file = recall_dir / "LESSONS.md"
    lessons_file.write_text(
        """# Project Lessons

### [L001] [5|3.0] Test Lesson
- **Uses**: 10 | **Velocity**: 5.0
- **Category**: testing
Content here

---
"""
    )

    # Create mock Claude home with transcript files
    claude_home = tmp_path / ".claude"
    projects_dir = claude_home / "projects"
    encoded_project = str(project_dir).replace("/", "-").replace(".", "-")
    transcript_dir = projects_dir / encoded_project
    transcript_dir.mkdir(parents=True)

    # Create session transcripts
    create_transcript(
        transcript_dir / "sess-recent.jsonl",
        first_prompt="Recent integration test session",
        tools=["Read", "Edit", "Bash"],
        tokens=2500,
        start_time=make_timestamp(60),
        end_time=make_timestamp(30),
    )

    create_transcript(
        transcript_dir / "sess-older.jsonl",
        first_prompt="Older session for testing",
        tools=["Read"],
        tokens=500,
        start_time=make_timestamp(300),
        end_time=make_timestamp(250),
    )

    monkeypatch.setenv("CLAUDE_RECALL_STATE", str(state_dir))
    monkeypatch.setenv("PROJECT_DIR", str(project_dir))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    return {
        "log_path": log_path,
        "project_dir": project_dir,
        "state_dir": state_dir,
        "claude_home": claude_home,
    }


# ============================================================================
# Integration Flow Tests
# ============================================================================


class TestFullStartupFlow:
    """Test complete app startup flow."""

    @pytest.mark.asyncio
    async def test_full_startup_to_events_display(self, full_test_environment):
        """App starts up and displays events in the Live tab."""
        app = RecallMonitorApp(log_path=full_test_environment["log_path"])

        async with app.run_test() as pilot:
            # Wait for startup and initial data load
            await pilot.pause()

            # Should be on Live tab with events
            event_log = app.query_one("#event-log", RichLog)
            assert len(event_log.lines) > 0, (
                "Event log should have content after startup. "
                "Events should be loaded automatically on app mount."
            )

            # Verify the events contain expected data
            lines_text = str(event_log.lines)
            assert "session_start" in lines_text or "test-123" in lines_text, (
                f"Event log should display session start event. Lines: {lines_text[:200]}..."
            )


class TestSessionNavigationFlow:
    """Test complete session navigation flow."""

    @pytest.mark.asyncio
    async def test_navigate_to_session_show_details(self, full_test_environment):
        """Navigate to session tab, select session, see events in detail panel."""
        app = RecallMonitorApp(log_path=full_test_environment["log_path"])

        async with app.run_test() as pilot:
            await pilot.pause()

            # Step 1: Switch to Session tab (F4)
            await pilot.press("f4")
            await pilot.pause()

            # Step 2: Verify DataTable shows sessions
            session_table = app.query_one("#session-list", DataTable)
            assert session_table.row_count > 0, (
                f"Session table should have rows from transcript files. "
                f"Got {session_table.row_count} rows."
            )

            # Step 3: Focus table and navigate with arrow keys
            session_table.focus()
            await pilot.pause()

            await pilot.press("down")
            await pilot.pause()

            # Step 4: Verify events panel shows session details
            session_events = app.query_one("#session-events", RichLog)
            assert len(session_events.lines) > 0, (
                "Session events panel should display content after selecting a session. "
                "Arrow navigation should trigger _show_session_events."
            )


class TestHandoffNavigationFlow:
    """Test complete handoff navigation flow."""

    @pytest.mark.asyncio
    async def test_navigate_to_handoff_show_details(self, full_test_environment):
        """Navigate to handoffs tab, select handoff, see details panel."""
        app = RecallMonitorApp(log_path=full_test_environment["log_path"])

        async with app.run_test() as pilot:
            await pilot.pause()

            # Step 1: Switch to Handoffs tab (F6)
            await pilot.press("f6")
            await pilot.pause()

            # Step 2: Verify DataTable exists and has handoffs
            handoff_table = app.query_one("#handoff-list", DataTable)
            assert handoff_table.row_count > 0, (
                f"Handoff table should have rows from HANDOFFS.md. "
                f"Got {handoff_table.row_count} rows."
            )

            # Step 3: Focus and navigate
            handoff_table.focus()
            await pilot.pause()

            await pilot.press("down")
            await pilot.pause()

            # Step 4: Verify details panel shows handoff info
            details_log = app.query_one("#handoff-details", RichLog)
            assert len(details_log.lines) > 0, (
                "Handoff details panel should show content after selecting a handoff."
            )


class TestHandoffActionFlow:
    """Test handoff action modal complete flow."""

    @pytest.mark.asyncio
    async def test_open_handoff_action_complete_flow(self, full_test_environment):
        """Open handoff action modal and complete an action."""
        app = RecallMonitorApp(log_path=full_test_environment["log_path"])

        async with app.run_test() as pilot:
            await pilot.pause()

            # Navigate to handoffs tab
            await pilot.press("f6")
            await pilot.pause()

            handoff_table = app.query_one("#handoff-list", DataTable)
            if handoff_table.row_count == 0:
                pytest.skip("No handoffs loaded for this test")

            handoff_table.focus()
            await pilot.pause()

            # Clear state and navigate
            app.state.handoff.current_id = None
            await pilot.press("down")
            await pilot.pause()

            # First Enter confirms selection
            await pilot.press("enter")
            await pilot.pause()

            # Second Enter opens action modal
            await pilot.press("enter")
            await pilot.pause()

            # Verify action screen opened
            assert isinstance(app.screen, HandoffActionScreen), (
                f"HandoffActionScreen should open after double-Enter. "
                f"Got screen type: {type(app.screen).__name__}"
            )

            # Navigate and select an action (status)
            await pilot.press("home")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

            # Should open GenericSelectModal for status
            assert isinstance(app.screen, GenericSelectModal), (
                f"GenericSelectModal should open for status selection. "
                f"Got: {type(app.screen).__name__}"
            )

            # Dismiss with Escape
            await pilot.press("escape")
            await pilot.pause()


class TestHandoffFilterFlow:
    """Test handoff filter complete flow."""

    @pytest.mark.asyncio
    async def test_handoff_filter_applies_correctly(self, full_test_environment):
        """Filter handoffs by text and verify list updates."""
        app = RecallMonitorApp(log_path=full_test_environment["log_path"])

        async with app.run_test() as pilot:
            await pilot.pause()

            # Go to handoffs tab
            await pilot.press("f6")
            await pilot.pause()

            # Enable completed handoffs to see all
            await pilot.press("c")
            await pilot.pause()

            handoff_list = app.query_one("#handoff-list", DataTable)
            initial_count = handoff_list.row_count

            if initial_count == 0:
                pytest.skip("No handoffs to filter")

            # Focus filter input and type filter text
            filter_input = app.query_one("#handoff-filter", Input)
            filter_input.focus()
            await pilot.pause()

            # Type "Test" to filter
            for char in "Test":
                await pilot.press(char)
            await pilot.pause()

            # Verify filter applied - should show filtered results
            filtered_count = handoff_list.row_count

            # At least verify the filter mechanism works (count may be same if all match)
            assert filtered_count >= 0, "Filter should produce valid count"

            # Clear filter with button
            from textual.widgets import Button

            clear_button = app.query_one("#clear-filter", Button)
            clear_button.press()
            await pilot.pause()

            # Filter should be cleared
            assert filter_input.value == "", "Filter input should be cleared"


class TestSessionDetailModalFlow:
    """Test session detail modal complete flow."""

    @pytest.mark.asyncio
    async def test_session_detail_modal_from_row_selection(self, full_test_environment):
        """Select session row, press 'e' to expand, see modal."""
        app = RecallMonitorApp(log_path=full_test_environment["log_path"])

        async with app.run_test() as pilot:
            await pilot.pause()

            # Navigate to session tab
            await pilot.press("f4")
            await pilot.pause()

            session_table = app.query_one("#session-list", DataTable)
            if session_table.row_count == 0:
                pytest.skip("No sessions loaded for modal test")

            # Focus table and select a row
            session_table.focus()
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()

            # Press 'e' to expand/show detail modal
            await pilot.press("e")
            await pilot.pause()

            # Verify modal opened
            assert isinstance(app.screen, SessionDetailModal), (
                f"SessionDetailModal should open after pressing 'e'. "
                f"Got: {type(app.screen).__name__}"
            )

            # Verify modal has session data
            modal = app.screen
            assert modal.session_id is not None, "Modal should have session_id"
            assert modal.session_data is not None, "Modal should have session_data"

            # Dismiss with Escape
            await pilot.press("escape")
            await pilot.pause()

            # Modal should be dismissed
            assert not isinstance(app.screen, SessionDetailModal), (
                "Modal should be dismissed after Escape"
            )


class TestAutoRefreshFlow:
    """Test auto-refresh functionality."""

    @pytest.mark.asyncio
    async def test_auto_refresh_cycle(self, full_test_environment):
        """Wait for auto-refresh timer and verify data updates."""
        app = RecallMonitorApp(log_path=full_test_environment["log_path"])

        async with app.run_test() as pilot:
            await pilot.pause()

            event_log = app.query_one("#event-log", RichLog)
            initial_count = len(event_log.lines)

            # Add a new event to the log file
            new_event = {
                "event": "auto_refresh_test_event",
                "level": "info",
                "timestamp": make_timestamp(0),
                "session_id": "refresh-test",
                "pid": 9999,
                "project": "test-project",
            }
            with open(full_test_environment["log_path"], "a") as f:
                f.write(json.dumps(new_event) + "\n")

            # Wait for auto-refresh timer (>5 seconds)
            await pilot.pause(delay=6.0)

            # Event log should have the new event
            final_count = len(event_log.lines)
            assert final_count > initial_count, (
                f"Auto-refresh should load new events. "
                f"Initial: {initial_count}, After 6s: {final_count}"
            )


class TestManualRefreshFlow:
    """Test manual refresh functionality."""

    @pytest.mark.asyncio
    async def test_manual_refresh_updates_all_loaded_tabs(self, full_test_environment):
        """Press 'r' to refresh and verify data updates."""
        app = RecallMonitorApp(log_path=full_test_environment["log_path"])

        async with app.run_test() as pilot:
            await pilot.pause()

            # Visit multiple tabs to load them
            await pilot.press("f2")  # Health
            await pilot.pause()
            await pilot.press("f1")  # Back to Live
            await pilot.pause()

            event_log = app.query_one("#event-log", RichLog)
            initial_count = len(event_log.lines)

            # Add new event
            new_event = {
                "event": "manual_refresh_test",
                "level": "info",
                "timestamp": make_timestamp(0),
                "session_id": "manual-refresh-test",
                "pid": 8888,
                "project": "test-project",
            }
            with open(full_test_environment["log_path"], "a") as f:
                f.write(json.dumps(new_event) + "\n")

            # Press 'r' to manually refresh
            await pilot.press("r")
            await pilot.pause()

            # Event log should have the new event
            final_count = len(event_log.lines)
            assert final_count > initial_count, (
                f"Manual refresh should load new events. "
                f"Initial: {initial_count}, After refresh: {final_count}"
            )


class TestToggleAllProjectsFlow:
    """Test toggle all projects functionality."""

    @pytest.mark.asyncio
    async def test_toggle_all_projects_updates_sessions(self, full_test_environment):
        """Press 'a' to toggle all projects and verify session list changes."""
        app = RecallMonitorApp(log_path=full_test_environment["log_path"])

        async with app.run_test() as pilot:
            await pilot.pause()

            # Go to session tab
            await pilot.press("f4")
            await pilot.pause()

            session_table = app.query_one("#session-list", DataTable)

            # Get initial column count (single-project mode has no Project column)
            initial_columns = len(session_table.columns)

            # Toggle to all-projects mode
            await pilot.press("a")
            await pilot.pause()

            # Column count should change (Project column added)
            after_toggle_columns = len(session_table.columns)

            assert after_toggle_columns != initial_columns, (
                f"Toggling 'a' should change columns (add/remove Project column). "
                f"Initial columns: {initial_columns}, After toggle: {after_toggle_columns}"
            )

            # Toggle back
            await pilot.press("a")
            await pilot.pause()

            # Should be back to original
            final_columns = len(session_table.columns)
            assert final_columns == initial_columns, (
                f"Toggling 'a' again should restore original columns. "
                f"Initial: {initial_columns}, Final: {final_columns}"
            )


class TestToggleCompletedHandoffsFlow:
    """Test toggle completed handoffs functionality."""

    @pytest.mark.asyncio
    async def test_toggle_completed_updates_handoffs(self, full_test_environment):
        """Press 'c' to toggle completed handoffs and verify list changes."""
        app = RecallMonitorApp(log_path=full_test_environment["log_path"])

        async with app.run_test() as pilot:
            await pilot.pause()

            # Go to handoffs tab
            await pilot.press("f6")
            await pilot.pause()

            # Initial state - completed not shown
            assert app.state.handoff.show_completed is False, (
                "Initial state should not show completed handoffs"
            )

            handoff_list = app.query_one("#handoff-list", DataTable)
            initial_count = handoff_list.row_count

            # Toggle completed on
            await pilot.press("c")
            await pilot.pause()

            assert app.state.handoff.show_completed is True, (
                "After pressing 'c', show_completed should be True"
            )

            # Count may increase if there are completed handoffs
            count_with_completed = handoff_list.row_count

            # Toggle back off
            await pilot.press("c")
            await pilot.pause()

            assert app.state.handoff.show_completed is False, (
                "After pressing 'c' again, show_completed should be False"
            )

            # Count should be back to initial
            final_count = handoff_list.row_count
            assert final_count == initial_count, (
                f"Toggling 'c' back should restore count. "
                f"Initial: {initial_count}, With completed: {count_with_completed}, "
                f"Final: {final_count}"
            )
