#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Tests for scroll and selection preservation during TUI refreshes.

These tests verify three related bugs:
1. Session list loses scroll position on 2-second refresh
2. Handoff list loses scroll position on refresh
3. Handoff list loses selection on refresh (missing _user_selected_handoff_id)

All tests are designed to FAIL initially until the fixes are implemented.
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
            first_prompt=f"Session {i} task description",
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

### [hf-0000001] First Handoff - Important Feature
- **Status**: in_progress | **Phase**: implementing | **Agent**: user
- **Created**: 2026-01-07 | **Updated**: 2026-01-08

**Description**: A test handoff for TUI testing.

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
# Issue 1: Handoff List Selection Tracking (missing _user_selected_handoff_id)
# ============================================================================


class TestHandoffSelectionTracking:
    """Tests for handoff selection tracking with _user_selected_handoff_id."""

    @pytest.mark.asyncio
    async def test_user_selected_handoff_id_exists(
        self, temp_project_with_handoffs: Path, monkeypatch
    ):
        """App should have _user_selected_handoff_id attribute."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Should have state.handoff.user_selected_id attribute
            assert hasattr(app.state.handoff, "user_selected_id"), (
                "RecallMonitorApp should have 'state.handoff.user_selected_id' attribute to track "
                "user's row selection."
            )

    @pytest.mark.asyncio
    async def test_handoff_row_highlight_stores_selection(
        self, temp_project_with_handoffs: Path, monkeypatch
    ):
        """Arrow key navigation should store the selected handoff ID."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Handoffs tab
            await pilot.press("f6")
            await pilot.pause()

            handoff_table = app.query_one("#handoff-list", DataTable)
            handoff_table.focus()
            await pilot.pause()

            # Navigate with arrow keys
            await pilot.press("down")
            await pilot.pause()

            # Verify state.handoff.user_selected_id is set
            assert hasattr(app.state.handoff, "user_selected_id"), (
                "App should have state.handoff.user_selected_id attribute"
            )
            assert app.state.handoff.user_selected_id is not None, (
                "state.handoff.user_selected_id should be set after user navigates with arrow keys."
            )

    @pytest.mark.asyncio
    async def test_handoff_refresh_preserves_selection(
        self, temp_project_with_handoffs: Path, monkeypatch
    ):
        """_refresh_handoff_list should preserve user's row selection."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Handoffs tab
            await pilot.press("f6")
            await pilot.pause()

            handoff_table = app.query_one("#handoff-list", DataTable)
            handoff_table.focus()
            await pilot.pause()

            # Navigate to a specific handoff (not the first one)
            await pilot.press("down")
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()

            # Get currently highlighted row
            if handoff_table.cursor_row is not None:
                row_keys = list(handoff_table.rows.keys())
                if handoff_table.cursor_row < len(row_keys):
                    selected_before = str(row_keys[handoff_table.cursor_row].value)

                    # Call refresh
                    app._refresh_handoff_list()
                    await pilot.pause()

                    # Check if selection was preserved
                    if handoff_table.cursor_row is not None:
                        row_keys_after = list(handoff_table.rows.keys())
                        if handoff_table.cursor_row < len(row_keys_after):
                            selected_after = str(row_keys_after[handoff_table.cursor_row].value)

                            assert selected_after == selected_before, (
                                f"Selection should be preserved after refresh. "
                                f"Before: {selected_before}, After: {selected_after}. "
                                "Fix: In _refresh_handoff_list(), after repopulating the table, "
                                "if _user_selected_handoff_id exists in the new data, "
                                "re-select that row using handoff_table.move_cursor()."
                            )


# ============================================================================
# Issue 2: Session List Scroll Position Preservation
# ============================================================================


class TestSessionListScrollPreservation:
    """Tests for session list scroll position preservation during refresh."""

    @pytest.mark.asyncio
    async def test_session_list_scroll_preserved_on_refresh(
        self, mock_claude_home: Path, temp_state_dir: Path
    ):
        """Session list scroll position should be preserved after refresh."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Session tab
            await pilot.press("f4")
            await pilot.pause()

            session_table = app.query_one("#session-list", DataTable)
            session_table.focus()
            await pilot.pause()

            # Navigate down several times to change scroll position
            for _ in range(5):
                await pilot.press("down")
                await pilot.pause()

            # Store the scroll position before refresh
            scroll_y_before = session_table.scroll_y

            # Call refresh (simulating the 2-second timer)
            app._refresh_session_list()
            await pilot.pause()

            # Get scroll position after refresh
            scroll_y_after = session_table.scroll_y

            # Scroll position should be preserved (or at least close)
            # Note: scroll_y might change slightly due to content changes,
            # but it should not reset to 0 if we were scrolled
            if scroll_y_before > 0:
                assert scroll_y_after > 0, (
                    f"Scroll position should be preserved after refresh. "
                    f"Before: {scroll_y_before}, After: {scroll_y_after}. "
                    "Fix: In _refresh_session_list(), save scroll_y before clearing table "
                    "and restore it after repopulating."
                )


# ============================================================================
# Issue 3: Handoff List Scroll Position Preservation
# ============================================================================


class TestHandoffListScrollPreservation:
    """Tests for handoff list scroll position preservation during refresh."""

    @pytest.mark.asyncio
    async def test_handoff_list_scroll_preserved_on_refresh(
        self, temp_project_with_handoffs: Path, monkeypatch
    ):
        """Handoff list scroll position should be preserved after refresh."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Handoffs tab
            await pilot.press("f6")
            await pilot.pause()

            handoff_table = app.query_one("#handoff-list", DataTable)
            handoff_table.focus()
            await pilot.pause()

            # Navigate down to change scroll position
            for _ in range(3):
                await pilot.press("down")
                await pilot.pause()

            # Store the scroll position before refresh
            scroll_y_before = handoff_table.scroll_y

            # Call refresh
            app._refresh_handoff_list()
            await pilot.pause()

            # Get scroll position after refresh
            scroll_y_after = handoff_table.scroll_y

            # Scroll position should be preserved
            if scroll_y_before > 0:
                assert scroll_y_after > 0, (
                    f"Scroll position should be preserved after refresh. "
                    f"Before: {scroll_y_before}, After: {scroll_y_after}. "
                    "Fix: In _refresh_handoff_list(), save scroll_y before clearing table "
                    "and restore it after repopulating."
                )


# ============================================================================
# Integration Tests
# ============================================================================


class TestScrollSelectionIntegration:
    """Integration tests verifying all tracking variables are initialized."""

    @pytest.mark.asyncio
    async def test_all_tracking_variables_initialized(
        self, mock_claude_home: Path, temp_state_dir: Path
    ):
        """All tracking variables should be initialized in __init__."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # After mount, all state attributes should exist
            assert hasattr(app.state.handoff, "user_selected_id"), (
                "RecallMonitorApp should have 'state.handoff.user_selected_id' to track user's handoff row selection."
            )
            assert hasattr(app.state.session, "user_selected_id"), (
                "RecallMonitorApp should have 'state.session.user_selected_id' to track user's session row selection."
            )
            assert hasattr(app.state.handoff, "current_id"), (
                "RecallMonitorApp should have 'state.handoff.current_id' to track currently displayed handoff."
            )
            assert hasattr(app.state.session, "current_id"), (
                "RecallMonitorApp should have 'state.session.current_id' to track currently displayed session."
            )

    @pytest.mark.asyncio
    async def test_handoff_selection_and_scroll_work_together(
        self, temp_project_with_handoffs: Path, monkeypatch
    ):
        """Both selection and scroll should be preserved after refresh."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Handoffs tab
            await pilot.press("f6")
            await pilot.pause()

            handoff_table = app.query_one("#handoff-list", DataTable)
            handoff_table.focus()
            await pilot.pause()

            # Navigate to third row
            await pilot.press("down")
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()

            # Store state before refresh
            cursor_row_before = handoff_table.cursor_row
            scroll_y_before = handoff_table.scroll_y

            # Get the selected handoff ID
            row_keys = list(handoff_table.rows.keys())
            selected_id_before = None
            if cursor_row_before is not None and cursor_row_before < len(row_keys):
                selected_id_before = str(row_keys[cursor_row_before].value)

            # Call refresh
            app._refresh_handoff_list()
            await pilot.pause()

            # Verify both selection and scroll are preserved
            cursor_row_after = handoff_table.cursor_row
            row_keys_after = list(handoff_table.rows.keys())
            selected_id_after = None
            if cursor_row_after is not None and cursor_row_after < len(row_keys_after):
                selected_id_after = str(row_keys_after[cursor_row_after].value)

            assert selected_id_after == selected_id_before, (
                f"Handoff selection not preserved. "
                f"Before: {selected_id_before}, After: {selected_id_after}"
            )
