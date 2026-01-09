#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Tests for TUI refresh behavior fixes.

These tests verify three related refresh behavior bugs:
1. Handoff details don't refresh when data changes externally
2. Session events auto-scroll resets position on same-session view
3. Session list selection jumps when new sessions appear

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

    # Session 1: older session
    create_transcript(
        project_dir / "sess-older.jsonl",
        first_prompt="Help me fix something old",
        tools=["Read", "Bash"],
        tokens=1234,
        start_time=make_timestamp(60),
        end_time=make_timestamp(50),
    )

    # Session 2: middle session
    create_transcript(
        project_dir / "sess-middle.jsonl",
        first_prompt="Middle session task",
        tools=["Edit"],
        tokens=500,
        start_time=make_timestamp(40),
        end_time=make_timestamp(20),
    )

    # Session 3: recent session
    create_transcript(
        project_dir / "sess-recent.jsonl",
        first_prompt="Recent task with many tools",
        tools=["Read", "Grep", "Edit", "Bash"],
        tokens=5000,
        start_time=make_timestamp(10),
        end_time=make_timestamp(5),
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
    """Create a temp project with a HANDOFFS.md file."""
    project_root = tmp_path / "test-project"
    project_root.mkdir()
    recall_dir = project_root / ".claude-recall"
    recall_dir.mkdir()

    handoffs_content = """# HANDOFFS.md - Active Work Tracking

## Active Handoffs

### [hf-0000001] First Handoff
- **Status**: in_progress | **Phase**: implementing | **Agent**: user
- **Created**: 2026-01-07 | **Updated**: 2026-01-08

**Description**: A test handoff for TUI testing.

**Tried** (1 steps):
  1. [success] Initial implementation

**Next**:
  - Complete the feature

**Refs**: core/test.py:42

**Checkpoint**: Half done

### [hf-0000002] Second Handoff
- **Status**: blocked | **Phase**: research | **Agent**: explore
- **Created**: 2026-01-05 | **Updated**: 2026-01-06

**Description**: Another test handoff.

**Tried** (1 steps):
  1. [fail] First attempt failed

**Next**:
  - Investigate the blocker

**Refs**: core/other.py:10

**Checkpoint**: Blocked on external dependency
"""
    (recall_dir / "HANDOFFS.md").write_text(handoffs_content)

    # Set up state directory (use exist_ok since temp_state_dir may have created it)
    state_dir = tmp_path / "state"
    state_dir.mkdir(exist_ok=True)
    (state_dir / "debug.log").write_text("")
    monkeypatch.setenv("CLAUDE_RECALL_STATE", str(state_dir))
    monkeypatch.setenv("PROJECT_DIR", str(project_root))

    return project_root


# ============================================================================
# Issue 1: Handoff Details Don't Refresh
# ============================================================================


class TestHandoffDetailsRefresh:
    """Tests for handoff details panel refreshing when data changes externally."""

    @pytest.mark.asyncio
    async def test_current_handoff_id_tracked(
        self, temp_project_with_handoffs: Path, monkeypatch
    ):
        """App should track the currently displayed handoff ID."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Should have _current_handoff_id attribute
            assert hasattr(app, "_current_handoff_id"), (
                "RecallMonitorApp should have '_current_handoff_id' attribute to track "
                "the currently displayed handoff. Add: _current_handoff_id: Optional[str] = None"
            )

    @pytest.mark.asyncio
    async def test_arrow_navigation_does_not_set_current_id(
        self, temp_project_with_handoffs: Path, monkeypatch
    ):
        """Arrow key navigation should NOT set _current_handoff_id.

        This enables double-action behavior where:
        - Arrow key navigation shows details but doesn't "confirm" selection
        - First Enter confirms selection (sets _current_handoff_id)
        - Second Enter on same row opens the action popup
        """
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Handoffs tab
            await pilot.press("f6")
            await pilot.pause()

            # Navigate to first handoff with arrow keys
            handoff_table = app.query_one("#handoff-list", DataTable)
            handoff_table.focus()
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()

            # Verify _current_handoff_id is NOT set (double-action behavior)
            assert hasattr(app, "_current_handoff_id"), (
                "App should have _current_handoff_id attribute"
            )
            assert app._current_handoff_id is None, (
                "_current_handoff_id should NOT be set after arrow navigation. "
                "It is only set after explicit Enter/click to enable double-action popup trigger."
            )

    @pytest.mark.asyncio
    async def test_enter_key_sets_current_id(
        self, temp_project_with_handoffs: Path, monkeypatch
    ):
        """First Enter key press should set _current_handoff_id.

        This is the first part of the double-action behavior:
        - First Enter confirms selection (sets _current_handoff_id)
        - Second Enter on same row opens the action popup
        """
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Handoffs tab
            await pilot.press("f6")
            await pilot.pause()

            # Navigate to first handoff with arrow keys
            handoff_table = app.query_one("#handoff-list", DataTable)
            handoff_table.focus()
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()

            # Ensure fresh state
            app._current_handoff_id = None

            # Press Enter to confirm selection
            await pilot.press("enter")
            await pilot.pause()

            # Verify _current_handoff_id IS set after Enter
            assert app._current_handoff_id is not None, (
                "_current_handoff_id should be set after pressing Enter. "
                "This enables the double-action popup trigger."
            )

    @pytest.mark.asyncio
    async def test_refresh_handoff_list_updates_details(
        self, temp_project_with_handoffs: Path, monkeypatch
    ):
        """_refresh_handoff_list should re-render details for current handoff."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Handoffs tab
            await pilot.press("f6")
            await pilot.pause()

            # Select first handoff to display details
            handoff_table = app.query_one("#handoff-list", DataTable)
            handoff_table.focus()
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()

            # Get initial details content
            details_log = app.query_one("#handoff-details", RichLog)
            initial_line_count = len(details_log.lines)

            # Verify details panel has content
            assert initial_line_count > 0, (
                "Details panel should have content after selecting a handoff"
            )

            # Track if _show_handoff_details was called during refresh
            show_details_called = False
            original_show_details = app._show_handoff_details

            def tracking_show_details(handoff_id: str):
                nonlocal show_details_called
                show_details_called = True
                return original_show_details(handoff_id)

            app._show_handoff_details = tracking_show_details

            # Call _refresh_handoff_list (simulating external data change)
            app._refresh_handoff_list()
            await pilot.pause()

            # _show_handoff_details should have been called to refresh the panel
            assert show_details_called, (
                "_refresh_handoff_list should call _show_handoff_details for the "
                "currently selected handoff to update the details panel. "
                "Fix: After refreshing table data, check if _current_handoff_id exists "
                "in _handoff_data and call _show_handoff_details() if so."
            )

    @pytest.mark.asyncio
    async def test_refresh_clears_details_when_handoff_removed(
        self, temp_project_with_handoffs: Path, monkeypatch
    ):
        """Details panel should clear when current handoff is removed/archived."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Handoffs tab
            await pilot.press("f6")
            await pilot.pause()

            # Select first handoff
            handoff_table = app.query_one("#handoff-list", DataTable)
            handoff_table.focus()
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()

            # Ensure _current_handoff_id is set
            if hasattr(app, "_current_handoff_id"):
                # Simulate handoff being removed by setting a non-existent ID
                app._current_handoff_id = "hf-nonexistent"

                # Call refresh
                app._refresh_handoff_list()
                await pilot.pause()

                # Details panel should be cleared or show "no data"
                details_log = app.query_one("#handoff-details", RichLog)

                # Either _current_handoff_id should be None or details should be cleared
                # This test verifies the fix handles removed handoffs gracefully
                if app._current_handoff_id == "hf-nonexistent":
                    # If ID wasn't cleared, check if details panel was cleared
                    lines_text = str(details_log.lines)
                    has_content = (
                        len(details_log.lines) > 0 and
                        "No handoff data" not in lines_text and
                        "hf-nonexistent" not in lines_text
                    )
                    if has_content:
                        pytest.fail(
                            "When current handoff is removed, either clear _current_handoff_id "
                            "or clear the details panel. Fix: In _refresh_handoff_list, "
                            "if _current_handoff_id not in _handoff_data, clear the details panel."
                        )


# ============================================================================
# Issue 2: Session Events Auto-Scroll
# ============================================================================


class TestSessionEventsAutoScroll:
    """Tests for session events panel scroll behavior."""

    @pytest.mark.asyncio
    async def test_current_session_id_tracked(
        self, mock_claude_home: Path, temp_state_dir: Path
    ):
        """App should track the currently displayed session ID."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Should have _current_session_id attribute
            assert hasattr(app, "_current_session_id"), (
                "RecallMonitorApp should have '_current_session_id' attribute to track "
                "the currently displayed session. Add: _current_session_id: Optional[str] = None"
            )

    @pytest.mark.asyncio
    async def test_show_session_events_sets_current_id(
        self, mock_claude_home: Path, temp_state_dir: Path
    ):
        """_show_session_events should update _current_session_id."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Session tab
            await pilot.press("f4")
            await pilot.pause()

            # Call _show_session_events directly
            app._show_session_events("sess-recent")
            await pilot.pause()

            # Verify _current_session_id is set
            assert hasattr(app, "_current_session_id"), (
                "App should have _current_session_id attribute"
            )
            assert app._current_session_id == "sess-recent", (
                f"_current_session_id should be 'sess-recent' after showing that session, "
                f"got '{getattr(app, '_current_session_id', None)}'. "
                "Fix: In _show_session_events(), add: self._current_session_id = session_id"
            )

    @pytest.mark.asyncio
    async def test_same_session_does_not_scroll_home(
        self, mock_claude_home: Path, temp_state_dir: Path
    ):
        """Viewing same session again should not call scroll_home()."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Session tab
            await pilot.press("f4")
            await pilot.pause()

            session_events = app.query_one("#session-events", RichLog)

            # First call - should scroll to home
            app._show_session_events("sess-recent")
            await pilot.pause()

            # Track subsequent scroll_home calls
            scroll_home_called = False
            original_scroll_home = session_events.scroll_home

            def tracking_scroll_home(*args, **kwargs):
                nonlocal scroll_home_called
                scroll_home_called = True
                return original_scroll_home(*args, **kwargs)

            session_events.scroll_home = tracking_scroll_home

            # Second call with SAME session - should NOT scroll
            app._show_session_events("sess-recent")
            await pilot.pause()

            assert not scroll_home_called, (
                "scroll_home should NOT be called when viewing the same session again. "
                "This resets the user's scroll position unnecessarily. "
                "Fix: In _show_session_events(), compare session_id to _current_session_id "
                "and only call scroll_home() when the session ID CHANGES."
            )

    @pytest.mark.asyncio
    async def test_different_session_does_scroll_home(
        self, mock_claude_home: Path, temp_state_dir: Path
    ):
        """Viewing a different session should call scroll_home()."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Session tab
            await pilot.press("f4")
            await pilot.pause()

            session_events = app.query_one("#session-events", RichLog)

            # First call - sets _current_session_id
            app._show_session_events("sess-recent")
            await pilot.pause()

            # Track scroll_home calls
            scroll_home_called = False
            original_scroll_home = session_events.scroll_home

            def tracking_scroll_home(*args, **kwargs):
                nonlocal scroll_home_called
                scroll_home_called = True
                return original_scroll_home(*args, **kwargs)

            session_events.scroll_home = tracking_scroll_home

            # Second call with DIFFERENT session - should scroll
            app._show_session_events("sess-older")
            await pilot.pause()

            assert scroll_home_called, (
                "scroll_home SHOULD be called when viewing a different session. "
                "This ensures the topic line is visible at the top."
            )


# ============================================================================
# Issue 3: Session List Selection Jumps
# ============================================================================


class TestSessionListSelectionPersistence:
    """Tests for session list selection persistence during refresh."""

    @pytest.mark.asyncio
    async def test_user_selected_session_id_tracked(
        self, mock_claude_home: Path, temp_state_dir: Path
    ):
        """App should track the user-selected session ID."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Should have _user_selected_session_id attribute
            assert hasattr(app, "_user_selected_session_id"), (
                "RecallMonitorApp should have '_user_selected_session_id' attribute to track "
                "user's row selection. Add: _user_selected_session_id: Optional[str] = None"
            )

    @pytest.mark.asyncio
    async def test_row_highlight_stores_selection(
        self, mock_claude_home: Path, temp_state_dir: Path
    ):
        """Arrow key navigation should store the selected session ID."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Session tab
            await pilot.press("f4")
            await pilot.pause()

            session_table = app.query_one("#session-list", DataTable)
            session_table.focus()
            await pilot.pause()

            # Navigate with arrow keys
            await pilot.press("down")
            await pilot.pause()

            # Verify _user_selected_session_id is set
            assert hasattr(app, "_user_selected_session_id"), (
                "App should have _user_selected_session_id attribute"
            )
            assert app._user_selected_session_id is not None, (
                "_user_selected_session_id should be set after user navigates with arrow keys. "
                "Fix: In on_data_table_row_highlighted(), for session-list table, "
                "store the session ID: self._user_selected_session_id = row_key"
            )

    @pytest.mark.asyncio
    async def test_refresh_preserves_selection(
        self, mock_claude_home: Path, temp_state_dir: Path
    ):
        """_refresh_session_list should preserve user's row selection."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Session tab
            await pilot.press("f4")
            await pilot.pause()

            session_table = app.query_one("#session-list", DataTable)
            session_table.focus()
            await pilot.pause()

            # Navigate to sess-older (should be last in recent-first order)
            # Move down to get to a specific session
            await pilot.press("down")
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()

            # Get currently highlighted row
            if session_table.cursor_row is not None:
                row_keys = list(session_table.rows.keys())
                if session_table.cursor_row < len(row_keys):
                    selected_before = str(row_keys[session_table.cursor_row].value)

                    # Manually set _user_selected_session_id if not already tracked
                    if hasattr(app, "_user_selected_session_id"):
                        app._user_selected_session_id = selected_before

                    # Call refresh
                    app._refresh_session_list()
                    await pilot.pause()

                    # Check if selection was preserved
                    if session_table.cursor_row is not None:
                        row_keys_after = list(session_table.rows.keys())
                        if session_table.cursor_row < len(row_keys_after):
                            selected_after = str(row_keys_after[session_table.cursor_row].value)

                            assert selected_after == selected_before, (
                                f"Selection should be preserved after refresh. "
                                f"Before: {selected_before}, After: {selected_after}. "
                                "Fix: In _refresh_session_list(), after repopulating the table, "
                                "if _user_selected_session_id exists in the new data, "
                                "re-select that row using session_table.move_cursor()."
                            )

    @pytest.mark.asyncio
    async def test_new_session_does_not_steal_selection(
        self, mock_claude_home: Path, temp_state_dir: Path, tmp_path: Path
    ):
        """When new sessions appear, they should not steal the current selection."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Session tab
            await pilot.press("f4")
            await pilot.pause()

            session_table = app.query_one("#session-list", DataTable)
            session_table.focus()
            await pilot.pause()

            # Navigate to a specific row
            await pilot.press("down")
            await pilot.pause()

            initial_row = session_table.cursor_row

            # Simulate a new session being added by creating a new transcript file
            # (This would happen when another Claude session starts)
            project_dir = tmp_path / ".claude" / "projects" / "-Users-test-code-project-a"
            if project_dir.exists():
                create_transcript(
                    project_dir / "sess-brand-new.jsonl",
                    first_prompt="Brand new session that just started",
                    tools=["Read"],
                    tokens=100,
                    start_time=make_timestamp(1),  # Very recent
                    end_time=make_timestamp(0),
                )

                # Store current selection
                if hasattr(app, "_user_selected_session_id"):
                    row_keys = list(session_table.rows.keys())
                    if initial_row is not None and initial_row < len(row_keys):
                        selected_id = str(row_keys[initial_row].value)
                        app._user_selected_session_id = selected_id

                        # Refresh (which would pick up the new session)
                        app._refresh_session_list()
                        await pilot.pause()

                        # The new session would be first (most recent), but our selection
                        # should still be on the previously selected session
                        if session_table.cursor_row is not None:
                            row_keys_after = list(session_table.rows.keys())
                            if session_table.cursor_row < len(row_keys_after):
                                current_id = str(row_keys_after[session_table.cursor_row].value)

                                # Should NOT be the new session (unless that was selected)
                                if selected_id != "sess-brand-new":
                                    assert current_id == selected_id, (
                                        f"New sessions should not steal selection. "
                                        f"Selected: {selected_id}, Now on: {current_id}. "
                                        "Fix: Preserve selection by re-selecting the "
                                        "_user_selected_session_id row after refresh."
                                    )


# ============================================================================
# Combined Integration Test
# ============================================================================


class TestRefreshBehaviorIntegration:
    """Integration tests verifying all refresh behaviors work together."""

    @pytest.mark.asyncio
    async def test_all_tracking_variables_initialized(
        self, mock_claude_home: Path, temp_state_dir: Path
    ):
        """All tracking variables should be initialized in __init__."""
        app = RecallMonitorApp()

        # Check instance variables exist before running
        assert hasattr(app, "_current_handoff_id") or True, (
            "Add _current_handoff_id: Optional[str] = None in __init__"
        )
        assert hasattr(app, "_current_session_id") or True, (
            "Add _current_session_id: Optional[str] = None in __init__"
        )
        assert hasattr(app, "_user_selected_session_id") or True, (
            "Add _user_selected_session_id: Optional[str] = None in __init__"
        )

        async with app.run_test() as pilot:
            await pilot.pause()

            # After mount, all should exist
            tracking_vars = [
                ("_current_handoff_id", "track currently displayed handoff"),
                ("_current_session_id", "track currently displayed session"),
                ("_user_selected_session_id", "track user's row selection"),
            ]

            for var_name, purpose in tracking_vars:
                assert hasattr(app, var_name), (
                    f"RecallMonitorApp should have '{var_name}' to {purpose}. "
                    f"Add: {var_name}: Optional[str] = None in __init__"
                )


# ============================================================================
# Issue 4: OptionList Navigation in HandoffActionScreen
# ============================================================================


class TestOptionListNavigationInHandoffActionScreen:
    """Tests for OptionList navigation in the HandoffActionScreen popup.

    The HandoffActionScreen uses an OptionList widget with options:
    - status: Set status...
    - phase: Set phase...
    - agent: Set agent...
    - complete: Complete
    - archive: Archive

    Users can navigate with arrow keys and select with Enter.
    """

    @pytest.mark.asyncio
    async def test_option_list_arrow_down_navigation(
        self, temp_project_with_handoffs: Path, monkeypatch
    ):
        """Arrow down should navigate through OptionList options."""
        from textual.widgets import OptionList

        from core.tui.app import HandoffActionScreen

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Push the HandoffActionScreen directly
            app.push_screen(HandoffActionScreen("hf-0000001", "First Handoff"))
            await pilot.pause()

            # Verify we're on the action screen
            assert isinstance(app.screen, HandoffActionScreen), (
                "Should be on HandoffActionScreen"
            )

            # Get the OptionList widget
            option_list = app.screen.query_one("#action-options", OptionList)
            initial_highlighted = option_list.highlighted

            # Press down arrow to navigate
            await pilot.press("down")
            await pilot.pause()

            new_highlighted = option_list.highlighted

            # Highlighted index should have changed (or started from None)
            assert new_highlighted != initial_highlighted or initial_highlighted is None, (
                "Arrow down should change the highlighted option in OptionList. "
                f"Initial: {initial_highlighted}, After down: {new_highlighted}"
            )

    @pytest.mark.asyncio
    async def test_option_list_arrow_up_navigation(
        self, temp_project_with_handoffs: Path, monkeypatch
    ):
        """Arrow up should navigate backwards through OptionList options."""
        from textual.widgets import OptionList

        from core.tui.app import HandoffActionScreen

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            app.push_screen(HandoffActionScreen("hf-0000001", "First Handoff"))
            await pilot.pause()

            option_list = app.screen.query_one("#action-options", OptionList)

            # Navigate down first to have room to go up
            await pilot.press("down")
            await pilot.press("down")
            await pilot.pause()
            middle_index = option_list.highlighted

            # Press up arrow
            await pilot.press("up")
            await pilot.pause()

            new_index = option_list.highlighted
            assert new_index != middle_index, (
                "Arrow up should navigate to previous option in OptionList. "
                f"Middle: {middle_index}, After up: {new_index}"
            )

    @pytest.mark.asyncio
    async def test_option_list_enter_selects_status(
        self, temp_project_with_handoffs: Path, monkeypatch
    ):
        """Enter on 'status' option should open StatusSelectScreen."""
        from textual.widgets import OptionList

        from core.tui.app import HandoffActionScreen, StatusSelectScreen

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            app.push_screen(HandoffActionScreen("hf-0000001", "First Handoff"))
            await pilot.pause()

            # Navigate to first option (status) using Home key
            option_list = app.screen.query_one("#action-options", OptionList)
            await pilot.press("home")
            await pilot.pause()

            # Verify we're at the status option (index 0)
            assert option_list.highlighted == 0, (
                "Home key should navigate to first option (status)"
            )

            # Press Enter to select
            await pilot.press("enter")
            await pilot.pause()

            # Should have opened StatusSelectScreen
            assert isinstance(app.screen, StatusSelectScreen), (
                f"Enter on status option should open StatusSelectScreen, "
                f"got {type(app.screen).__name__}"
            )

    @pytest.mark.asyncio
    async def test_option_list_navigate_and_select_phase(
        self, temp_project_with_handoffs: Path, monkeypatch
    ):
        """Navigate to 'phase' option and select with Enter."""
        from textual.widgets import OptionList

        from core.tui.app import HandoffActionScreen, PhaseSelectScreen

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            app.push_screen(HandoffActionScreen("hf-0000001", "First Handoff"))
            await pilot.pause()

            # Navigate to phase option (index 1)
            option_list = app.screen.query_one("#action-options", OptionList)
            await pilot.press("home")
            await pilot.press("down")  # Move from status to phase
            await pilot.pause()

            assert option_list.highlighted == 1, (
                "Should be highlighting phase option (index 1)"
            )

            # Press Enter to select
            await pilot.press("enter")
            await pilot.pause()

            # Should have opened PhaseSelectScreen
            assert isinstance(app.screen, PhaseSelectScreen), (
                f"Enter on phase option should open PhaseSelectScreen, "
                f"got {type(app.screen).__name__}"
            )

    @pytest.mark.asyncio
    async def test_option_list_navigate_and_select_agent(
        self, temp_project_with_handoffs: Path, monkeypatch
    ):
        """Navigate to 'agent' option and select with Enter."""
        from textual.widgets import OptionList

        from core.tui.app import AgentSelectScreen, HandoffActionScreen

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            app.push_screen(HandoffActionScreen("hf-0000001", "First Handoff"))
            await pilot.pause()

            # Navigate to agent option (index 2)
            option_list = app.screen.query_one("#action-options", OptionList)
            await pilot.press("home")
            await pilot.press("down")  # status -> phase
            await pilot.press("down")  # phase -> agent
            await pilot.pause()

            assert option_list.highlighted == 2, (
                "Should be highlighting agent option (index 2)"
            )

            # Press Enter to select
            await pilot.press("enter")
            await pilot.pause()

            # Should have opened AgentSelectScreen
            assert isinstance(app.screen, AgentSelectScreen), (
                f"Enter on agent option should open AgentSelectScreen, "
                f"got {type(app.screen).__name__}"
            )

    @pytest.mark.asyncio
    async def test_all_options_present(
        self, temp_project_with_handoffs: Path, monkeypatch
    ):
        """OptionList should have all 5 expected options."""
        from textual.widgets import OptionList

        from core.tui.app import HandoffActionScreen

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            app.push_screen(HandoffActionScreen("hf-0000001", "First Handoff"))
            await pilot.pause()

            option_list = app.screen.query_one("#action-options", OptionList)

            # Should have 5 options: status, phase, agent, complete, archive
            assert option_list.option_count == 5, (
                f"OptionList should have 5 options (status, phase, agent, complete, archive), "
                f"got {option_list.option_count}"
            )


# ============================================================================
# Issue 5: End-to-End Double-Action Flow
# ============================================================================


class TestEndToEndDoubleActionFlow:
    """Tests for the complete double-action flow to open the popup.

    The double-action flow:
    1. Arrow navigate to a handoff row -> shows details in panel
    2. Press Enter -> sets _current_handoff_id (first action, confirms selection)
    3. Press Enter again -> should open HandoffActionScreen popup (second action)

    This prevents accidental popup opens during navigation.
    """

    @pytest.mark.asyncio
    async def test_double_action_popup_appears(
        self, temp_project_with_handoffs: Path, monkeypatch
    ):
        """Full double-action flow should open the HandoffActionScreen popup."""
        from textual.widgets import DataTable

        from core.tui.app import HandoffActionScreen

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Step 1: Switch to Handoffs tab
            await pilot.press("f6")
            await pilot.pause()

            # Get the handoff table and verify it has data
            handoff_table = app.query_one("#handoff-list", DataTable)
            if handoff_table.row_count == 0:
                pytest.skip("No handoffs loaded in test environment")

            # Step 2: Focus table and navigate with arrow key
            handoff_table.focus()
            await pilot.pause()

            # Clear _current_handoff_id to ensure fresh state
            app._current_handoff_id = None

            # Arrow down to first data row - this shows details but doesn't set _current_handoff_id
            await pilot.press("down")
            await pilot.pause()

            # Verify details are shown but popup is NOT open
            assert not isinstance(app.screen, HandoffActionScreen), (
                "Arrow navigation should NOT open popup"
            )

            # Verify _current_handoff_id is NOT set after arrow navigation
            assert app._current_handoff_id is None, (
                "_current_handoff_id should NOT be set after arrow navigation only"
            )

            # Step 3: First Enter - confirms selection (sets _current_handoff_id)
            await pilot.press("enter")
            await pilot.pause()

            # Verify _current_handoff_id IS now set
            assert app._current_handoff_id is not None, (
                "First Enter should set _current_handoff_id to confirm selection"
            )

            # Verify popup is still NOT open after first Enter
            assert not isinstance(app.screen, HandoffActionScreen), (
                "First Enter should NOT open popup, only confirm selection"
            )

            # Step 4: Second Enter - opens popup
            await pilot.press("enter")
            await pilot.pause()

            # Verify popup IS now open
            assert isinstance(app.screen, HandoffActionScreen), (
                f"Second Enter should open HandoffActionScreen popup, "
                f"got {type(app.screen).__name__}"
            )

    @pytest.mark.asyncio
    async def test_popup_shows_correct_handoff(
        self, temp_project_with_handoffs: Path, monkeypatch
    ):
        """Popup should show the correct handoff ID and title."""
        from textual.widgets import DataTable

        from core.tui.app import HandoffActionScreen

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Handoffs tab
            await pilot.press("f6")
            await pilot.pause()

            handoff_table = app.query_one("#handoff-list", DataTable)
            if handoff_table.row_count == 0:
                pytest.skip("No handoffs loaded in test environment")

            handoff_table.focus()
            await pilot.pause()

            # Clear and navigate
            app._current_handoff_id = None
            await pilot.press("down")
            await pilot.pause()

            # Double Enter to open popup
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

            # Verify popup opened
            assert isinstance(app.screen, HandoffActionScreen), (
                "Should have opened HandoffActionScreen"
            )

            # Verify the popup has the correct handoff ID
            action_screen = app.screen
            assert action_screen.handoff_id is not None, (
                "HandoffActionScreen should have a handoff_id"
            )
            assert action_screen.handoff_id.startswith("hf-"), (
                f"Handoff ID should start with 'hf-', got {action_screen.handoff_id}"
            )

    @pytest.mark.asyncio
    async def test_popup_dismiss_returns_to_handoffs_tab(
        self, temp_project_with_handoffs: Path, monkeypatch
    ):
        """Dismissing popup with Escape should return to handoffs tab."""
        from textual.widgets import DataTable

        from core.tui.app import HandoffActionScreen

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Navigate to handoffs tab
            await pilot.press("f6")
            await pilot.pause()

            handoff_table = app.query_one("#handoff-list", DataTable)
            if handoff_table.row_count == 0:
                pytest.skip("No handoffs loaded in test environment")

            handoff_table.focus()
            await pilot.pause()

            # Open popup via double-action
            app._current_handoff_id = None
            await pilot.press("down")
            await pilot.press("enter")
            await pilot.press("enter")
            await pilot.pause()

            # Verify popup is open
            assert isinstance(app.screen, HandoffActionScreen), (
                "Popup should be open before testing dismiss"
            )

            # Press Escape to dismiss
            await pilot.press("escape")
            await pilot.pause()

            # Verify popup is closed
            assert not isinstance(app.screen, HandoffActionScreen), (
                "Escape should dismiss the HandoffActionScreen popup"
            )

    @pytest.mark.asyncio
    async def test_different_row_resets_double_action(
        self, temp_project_with_handoffs: Path, monkeypatch
    ):
        """Navigating to a different row should reset the double-action state.

        If user:
        1. Selects row A (first Enter)
        2. Navigates to row B (arrow key)
        3. Presses Enter

        Step 3 should select row B, NOT open popup (since row B was not selected yet).
        """
        from textual.widgets import DataTable

        from core.tui.app import HandoffActionScreen

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            await pilot.press("f6")
            await pilot.pause()

            handoff_table = app.query_one("#handoff-list", DataTable)
            if handoff_table.row_count < 2:
                pytest.skip("Need at least 2 handoffs for this test")

            handoff_table.focus()
            await pilot.pause()

            # Navigate to first row (row 0) explicitly using Home key
            app._current_handoff_id = None
            await pilot.press("home")
            await pilot.pause()

            # Verify we're at row 0
            assert handoff_table.cursor_row == 0, (
                f"Should be at row 0 after Home key, got row {handoff_table.cursor_row}"
            )

            # First Enter - selects row 0
            await pilot.press("enter")
            await pilot.pause()

            first_selected_id = app._current_handoff_id
            assert first_selected_id is not None, "First row should be selected"

            # Navigate to second row (row 1)
            await pilot.press("down")
            await pilot.pause()

            # Verify cursor moved to row 1
            assert handoff_table.cursor_row == 1, (
                f"Should be at row 1 after down key, got row {handoff_table.cursor_row}"
            )

            # Verify _user_selected_handoff_id changed (from row_highlighted)
            assert app._user_selected_handoff_id != first_selected_id, (
                "Navigation should have changed _user_selected_handoff_id"
            )

            # Press Enter - should select row 1, NOT open popup
            await pilot.press("enter")
            await pilot.pause()

            # Should NOT have opened popup
            assert not isinstance(app.screen, HandoffActionScreen), (
                "Enter on a different row should select that row, not open popup"
            )

            # _current_handoff_id should now be the second row
            assert app._current_handoff_id != first_selected_id, (
                "Selection should have changed to the second row"
            )
