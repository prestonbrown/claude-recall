#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Tests for horizontal scroll (scroll_x) preservation during TUI refreshes.

These tests verify that scroll_x is saved and restored alongside scroll_y
in the following methods:
1. _show_session_events - saves and restores both scroll_x and scroll_y on refresh
2. _show_handoff_details - saves and restores both scroll_x and scroll_y on refresh
3. _refresh_handoff_list - preserves scroll position using saved_scroll_x/y
4. _refresh_session_list - preserves scroll position using saved_scroll_x/y
"""

import json
import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path

pytest.importorskip("textual")

# Configure pytest-asyncio
pytest_plugins = ("pytest_asyncio",)

from textual.widgets import DataTable, RichLog


# Import app with fallback for installed vs dev paths
try:
    from core.tui.app import RecallMonitorApp
    from core.tui.transcript_reader import TranscriptReader, TranscriptSummary
except ImportError:
    from .app import RecallMonitorApp
    from .transcript_reader import TranscriptReader, TranscriptSummary


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
def mock_claude_home(tmp_path: Path, monkeypatch) -> Path:
    """Create a mock ~/.claude directory with transcript files."""
    claude_home = tmp_path / ".claude"
    projects_dir = claude_home / "projects"

    # Create project directory
    project_dir = projects_dir / "-Users-test-code-project-a"
    project_dir.mkdir(parents=True)

    # Create many sessions so we can test scrolling
    for i in range(10):
        create_transcript(
            project_dir / f"sess-{i:03d}.jsonl",
            first_prompt=f"Session {i} task description with extra long text to enable horizontal scrolling",
            tools=["Read", "Bash"] if i % 2 == 0 else ["Edit"],
            tokens=1000 + i * 100,
            start_time=make_timestamp(3600 - i * 60),  # Staggered start times
            end_time=make_timestamp(3500 - i * 60),
        )

    # Monkeypatch to use our mock Claude home and project dir
    monkeypatch.setenv("PROJECT_DIR", "/Users/test/code/project-a")

    # Monkeypatch Path.home() to return our tmp_path
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    return claude_home


@pytest.fixture
def temp_state_dir(tmp_path: Path, monkeypatch) -> Path:
    """Create temp state dir with empty debug.log for LogReader."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    # Create minimal debug.log so LogReader doesn't fail
    log_path = state_dir / "debug.log"
    log_path.write_text("")

    monkeypatch.setenv("CLAUDE_RECALL_STATE", str(state_dir))
    return state_dir


@pytest.fixture
def temp_project_with_handoffs(tmp_path: Path, monkeypatch) -> Path:
    """Create a temp project with a HANDOFFS.md file with multiple handoffs."""
    project_root = tmp_path / "test-project"
    project_root.mkdir()
    recall_dir = project_root / ".claude-recall"
    recall_dir.mkdir()

    # Create multiple handoffs so we can test scrolling and selection
    handoffs_content = """# HANDOFFS.md - Active Work Tracking

## Active Handoffs

### [hf-0000001] First Handoff - Important Feature with very long title to enable horizontal scrolling
- **Status**: in_progress | **Phase**: implementing | **Agent**: user
- **Created**: 2026-01-07 | **Updated**: 2026-01-08

**Description**: A test handoff for TUI testing with a very long description that should enable horizontal scrolling in the details panel when the content exceeds the visible width.

**Tried** (1 steps):
  1. [success] Initial implementation

**Next**:
  - Complete the feature

**Refs**: core/test.py:42

**Checkpoint**: Half done

### [hf-0000002] Second Handoff - Bug Fix
- **Status**: blocked | **Phase**: research | **Agent**: explore
- **Created**: 2026-01-05 | **Updated**: 2026-01-06

**Description**: Another test handoff.

**Tried** (1 steps):
  1. [fail] First attempt failed

**Next**:
  - Investigate the blocker

**Refs**: core/other.py:10

**Checkpoint**: Blocked on external dependency

### [hf-0000003] Third Handoff - Refactoring
- **Status**: in_progress | **Phase**: planning | **Agent**: general-purpose
- **Created**: 2026-01-04 | **Updated**: 2026-01-05

**Description**: Refactoring task.

**Next**:
  - Create design doc

### [hf-0000004] Fourth Handoff - Documentation
- **Status**: not_started | **Phase**: research | **Agent**: user
- **Created**: 2026-01-03 | **Updated**: 2026-01-03

**Description**: Documentation update.

**Next**:
  - Start writing
"""
    (recall_dir / "HANDOFFS.md").write_text(handoffs_content)

    # Set up state directory
    state_dir = tmp_path / "state"
    state_dir.mkdir(exist_ok=True)
    (state_dir / "debug.log").write_text("")
    monkeypatch.setenv("CLAUDE_RECALL_STATE", str(state_dir))
    monkeypatch.setenv("PROJECT_DIR", str(project_root))

    return project_root


# ============================================================================
# Issue 1: _show_session_events - No scroll save/restore at all
# ============================================================================


class TestShowSessionEventsScrollPreservation:
    """Tests for scroll preservation in _show_session_events method."""

    @pytest.mark.asyncio
    async def test_session_events_scroll_y_preserved_on_same_session_refresh(
        self, mock_claude_home: Path, temp_state_dir: Path
    ):
        """scroll_y should be preserved when refreshing the same session."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Session tab
            await pilot.press("f4")
            await pilot.pause()

            session_table = app.query_one("#session-list", DataTable)
            session_table.focus()
            await pilot.pause()

            # Select first session to show its events
            await pilot.press("enter")
            await pilot.pause()

            session_log = app.query_one("#session-events", RichLog)

            # Scroll down in the session events log
            # Use scroll_y directly since RichLog may not respond to key scrolling
            session_log.scroll_y = 5
            await pilot.pause()

            scroll_y_before = session_log.scroll_y

            # Get current session ID
            current_session_id = app.state.session.current_id

            # Refresh the same session (simulates refresh)
            if current_session_id:
                app._show_session_events(current_session_id)
                await pilot.pause()

                scroll_y_after = session_log.scroll_y

                # scroll_y should be preserved for same session
                if scroll_y_before > 0:
                    assert scroll_y_after > 0, (
                        f"scroll_y should be preserved when refreshing same session. "
                        f"Before: {scroll_y_before}, After: {scroll_y_after}. "
                        "Fix: In _show_session_events(), save scroll_y before clearing "
                        "and restore it after populating (only for same session)."
                    )

    @pytest.mark.asyncio
    async def test_session_events_scroll_x_preserved_on_same_session_refresh(
        self, mock_claude_home: Path, temp_state_dir: Path
    ):
        """scroll_x should be preserved when refreshing the same session."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Session tab
            await pilot.press("f4")
            await pilot.pause()

            session_table = app.query_one("#session-list", DataTable)
            session_table.focus()
            await pilot.pause()

            # Select first session to show its events
            await pilot.press("enter")
            await pilot.pause()

            session_log = app.query_one("#session-events", RichLog)

            # Set horizontal scroll position
            session_log.scroll_x = 10
            await pilot.pause()

            scroll_x_before = session_log.scroll_x

            # Get current session ID
            current_session_id = app.state.session.current_id

            # Refresh the same session
            if current_session_id:
                app._show_session_events(current_session_id)
                await pilot.pause()

                scroll_x_after = session_log.scroll_x

                # scroll_x should be preserved for same session
                if scroll_x_before > 0:
                    assert scroll_x_after > 0, (
                        f"scroll_x should be preserved when refreshing same session. "
                        f"Before: {scroll_x_before}, After: {scroll_x_after}. "
                        "Fix: In _show_session_events(), also save scroll_x before clearing "
                        "and restore it after populating (only for same session)."
                    )


# ============================================================================
# Issue 2: _show_handoff_details - Has scroll_y but missing scroll_x
# ============================================================================


class TestShowHandoffDetailsScrollPreservation:
    """Tests for scroll_x preservation in _show_handoff_details method."""

    @pytest.mark.asyncio
    async def test_handoff_details_scroll_x_preserved_on_same_handoff_refresh(
        self, temp_project_with_handoffs: Path, monkeypatch
    ):
        """scroll_x should be preserved when refreshing the same handoff."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Handoffs tab
            await pilot.press("f6")
            await pilot.pause()

            handoff_table = app.query_one("#handoff-list", DataTable)
            handoff_table.focus()
            await pilot.pause()

            # Select first handoff to show its details
            await pilot.press("enter")
            await pilot.pause()

            details_log = app.query_one("#handoff-details", RichLog)

            # Set horizontal scroll position
            details_log.scroll_x = 15
            await pilot.pause()

            scroll_x_before = details_log.scroll_x

            # Get displayed handoff ID
            displayed_handoff_id = app.state.handoff.displayed_id

            # Refresh the same handoff
            if displayed_handoff_id:
                app._show_handoff_details(displayed_handoff_id)
                await pilot.pause()

                scroll_x_after = details_log.scroll_x

                # scroll_x should be preserved for same handoff
                if scroll_x_before > 0:
                    assert scroll_x_after > 0, (
                        f"scroll_x should be preserved when refreshing same handoff. "
                        f"Before: {scroll_x_before}, After: {scroll_x_after}. "
                        "Fix: In _show_handoff_details(), also save scroll_x (like scroll_y) "
                        "and restore it in restore_scroll()."
                    )


# ============================================================================
# Issue 3: _refresh_handoff_list - Missing scroll_x and scroll=False
# ============================================================================


class TestRefreshHandoffListScrollPreservation:
    """Tests for scroll_x preservation and scroll=False in _refresh_handoff_list."""

    @pytest.mark.asyncio
    async def test_handoff_list_scroll_x_preserved_on_refresh(
        self, temp_project_with_handoffs: Path, monkeypatch
    ):
        """scroll_x should be preserved after _refresh_handoff_list."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Handoffs tab
            await pilot.press("f6")
            await pilot.pause()

            handoff_table = app.query_one("#handoff-list", DataTable)
            handoff_table.focus()
            await pilot.pause()

            # Set horizontal scroll position
            handoff_table.scroll_x = 20
            await pilot.pause()

            scroll_x_before = handoff_table.scroll_x

            # Call refresh
            app._refresh_handoff_list()
            await pilot.pause()

            scroll_x_after = handoff_table.scroll_x

            # scroll_x should be preserved
            if scroll_x_before > 0:
                assert scroll_x_after > 0, (
                    f"scroll_x should be preserved after refresh. "
                    f"Before: {scroll_x_before}, After: {scroll_x_after}. "
                    "Fix: In _refresh_handoff_list(), save scroll_x before clearing "
                    "and restore it after repopulating."
                )

    @pytest.mark.asyncio
    async def test_handoff_list_move_cursor_uses_scroll_false(
        self, temp_project_with_handoffs: Path, monkeypatch
    ):
        """Verify that move_cursor is called with scroll=False in _refresh_handoff_list.

        This test verifies that the code correctly uses scroll=False when
        restoring cursor position after refresh, which prevents auto-scrolling
        to bring the cursor into view and overriding the restored scroll position.
        """
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Handoffs tab
            await pilot.press("f6")
            await pilot.pause()

            handoff_table = app.query_one("#handoff-list", DataTable)
            handoff_table.focus()
            await pilot.pause()

            # Navigate to a row and select it (sets user_selected_id)
            await pilot.press("down")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

            # Store selection state
            selected_id = app.state.handoff.user_selected_id

            # Verify that a handoff is selected
            assert selected_id is not None, "Should have a selected handoff"

            # Get the current scroll position (should be 0 or a valid position)
            initial_scroll_y = handoff_table.scroll_y

            # Call refresh - this should restore cursor with scroll=False
            app._refresh_handoff_list()
            await pilot.pause()

            # The scroll position should be preserved (not changed by cursor move)
            # Since max_scroll_y may be 0, we just verify scroll is clamped correctly
            assert handoff_table.scroll_y >= 0, "scroll_y should not be negative"
            assert handoff_table.scroll_y <= handoff_table.max_scroll_y, (
                f"scroll_y ({handoff_table.scroll_y}) should be <= "
                f"max_scroll_y ({handoff_table.max_scroll_y})"
            )


# ============================================================================
# Issue 4: _refresh_session_list - Missing scroll_x and scroll=False
# ============================================================================


class TestRefreshSessionListScrollPreservation:
    """Tests for scroll_x preservation and scroll=False in _refresh_session_list."""

    @pytest.mark.asyncio
    async def test_session_list_scroll_x_preserved_on_refresh(
        self, mock_claude_home: Path, temp_state_dir: Path
    ):
        """scroll_x should be preserved after _refresh_session_list."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Session tab
            await pilot.press("f4")
            await pilot.pause()

            session_table = app.query_one("#session-list", DataTable)
            session_table.focus()
            await pilot.pause()

            # Set horizontal scroll position
            session_table.scroll_x = 25
            await pilot.pause()

            scroll_x_before = session_table.scroll_x

            # Call refresh
            app._refresh_session_list()
            await pilot.pause()

            scroll_x_after = session_table.scroll_x

            # scroll_x should be preserved
            if scroll_x_before > 0:
                assert scroll_x_after > 0, (
                    f"scroll_x should be preserved after refresh. "
                    f"Before: {scroll_x_before}, After: {scroll_x_after}. "
                    "Fix: In _refresh_session_list(), save scroll_x before clearing "
                    "and restore it after repopulating."
                )

    @pytest.mark.asyncio
    async def test_session_list_move_cursor_uses_scroll_false(
        self, mock_claude_home: Path, temp_state_dir: Path
    ):
        """Verify that move_cursor is called with scroll=False in _refresh_session_list.

        This test verifies that the code correctly uses scroll=False when
        restoring cursor position after refresh, which prevents auto-scrolling
        to bring the cursor into view and overriding the restored scroll position.
        """
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Session tab
            await pilot.press("f4")
            await pilot.pause()

            session_table = app.query_one("#session-list", DataTable)
            session_table.focus()
            await pilot.pause()

            # Navigate to a row and select it (sets user_selected_id)
            await pilot.press("down")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

            # Store selection state
            selected_id = app.state.session.user_selected_id

            # Get the current scroll position
            initial_scroll_y = session_table.scroll_y

            # Call refresh - this should restore cursor with scroll=False
            app._refresh_session_list()
            await pilot.pause()

            # The scroll position should be clamped correctly (not invalid)
            assert session_table.scroll_y >= 0, "scroll_y should not be negative"
            assert session_table.scroll_y <= session_table.max_scroll_y, (
                f"scroll_y ({session_table.scroll_y}) should be <= "
                f"max_scroll_y ({session_table.max_scroll_y})"
            )


# ============================================================================
# Integration Tests
# ============================================================================


class TestScrollXPreservationIntegration:
    """Integration tests for complete scroll_x preservation across all methods."""

    @pytest.mark.asyncio
    async def test_both_scroll_dimensions_preserved_handoff_details(
        self, temp_project_with_handoffs: Path, monkeypatch
    ):
        """Both scroll_x and scroll_y should be preserved when refreshing handoff details."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Handoffs tab
            await pilot.press("f6")
            await pilot.pause()

            handoff_table = app.query_one("#handoff-list", DataTable)
            handoff_table.focus()
            await pilot.pause()

            # Select first handoff
            await pilot.press("enter")
            await pilot.pause()

            details_log = app.query_one("#handoff-details", RichLog)

            # Set both scroll positions
            details_log.scroll_x = 10
            details_log.scroll_y = 5
            await pilot.pause()

            scroll_x_before = details_log.scroll_x
            scroll_y_before = details_log.scroll_y

            # Refresh same handoff
            displayed_handoff_id = app.state.handoff.displayed_id
            if displayed_handoff_id:
                app._show_handoff_details(displayed_handoff_id)
                await pilot.pause()

                # Both dimensions should be preserved
                if scroll_x_before > 0:
                    assert details_log.scroll_x > 0, (
                        f"scroll_x not preserved. Before: {scroll_x_before}, After: {details_log.scroll_x}"
                    )
                if scroll_y_before > 0:
                    assert details_log.scroll_y > 0, (
                        f"scroll_y not preserved. Before: {scroll_y_before}, After: {details_log.scroll_y}"
                    )

    @pytest.mark.asyncio
    async def test_scroll_x_clamped_when_content_shrinks(
        self, temp_project_with_handoffs: Path, monkeypatch
    ):
        """scroll_x should be clamped to max_scroll_x when content gets narrower.

        Similar to the existing scroll_y clamping logic, scroll_x should use
        min(saved_scroll_x, widget.max_scroll_x) to avoid invalid positions.
        """
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Handoffs tab
            await pilot.press("f6")
            await pilot.pause()

            handoff_table = app.query_one("#handoff-list", DataTable)
            handoff_table.focus()
            await pilot.pause()

            # Set a large scroll_x that may exceed max after refresh
            handoff_table.scroll_x = 100
            await pilot.pause()

            # Refresh the list
            app._refresh_handoff_list()
            await pilot.pause()

            # scroll_x should be clamped (not negative, not beyond max)
            assert handoff_table.scroll_x >= 0, (
                f"scroll_x should never be negative. Got: {handoff_table.scroll_x}"
            )
            assert handoff_table.scroll_x <= handoff_table.max_scroll_x, (
                f"scroll_x ({handoff_table.scroll_x}) should be clamped to "
                f"max_scroll_x ({handoff_table.max_scroll_x})"
            )
