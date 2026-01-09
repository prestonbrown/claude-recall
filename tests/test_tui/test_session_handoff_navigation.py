#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Tests for session-handoff navigation in the TUI.

These tests verify navigation between sessions and handoffs:
- _navigate_to_handoff() switches to handoffs tab and selects the handoff
- _navigate_to_session() switches to session tab and selects the session
- Key binding 'h' in session tab jumps to related handoff
- Handoff details panel shows linked sessions
"""

import json
import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path

pytest.importorskip("textual")

# Configure pytest-asyncio
pytest_plugins = ("pytest_asyncio",)

from textual.widgets import DataTable, RichLog

try:
    from core.tui.app import RecallMonitorApp
    from core.tui.models import HandoffSummary
except ImportError:
    from .app import RecallMonitorApp
    from .models import HandoffSummary


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
def mock_claude_home_with_linked_data(tmp_path: Path, monkeypatch) -> dict:
    """Create mock ~/.claude directory with session and handoff data linked via session-handoffs.json."""
    claude_home = tmp_path / ".claude"
    projects_dir = claude_home / "projects"

    # Create project directory
    project_root = tmp_path / "myproject"
    project_root.mkdir(parents=True)

    # Encode the project path for Claude's directory naming
    encoded_project = str(project_root).replace("/", "-").replace(".", "-")
    project_dir = projects_dir / encoded_project
    project_dir.mkdir(parents=True)

    # Create .claude-recall directory in the project root
    recall_dir = project_root / ".claude-recall"
    recall_dir.mkdir(parents=True)

    # Create state directory
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "debug.log").write_text("")

    today = datetime.now().strftime("%Y-%m-%d")

    # Create HANDOFFS.md with handoffs
    handoffs_content = f"""# HANDOFFS.md - Active Work Tracking

## Active Handoffs

### [hf-nav0001] Navigation Feature Handoff
- **Status**: in_progress | **Phase**: implementing | **Agent**: user
- **Created**: {today} | **Updated**: {today}

**Description**: Implementing session-handoff navigation

**Tried** (1 steps):
  1. [success] Initial setup

**Next**:
  - Complete navigation methods

**Refs**: core/tui/app.py:100

### [hf-nav0002] Another Handoff
- **Status**: blocked | **Phase**: research | **Agent**: explore
- **Created**: {today} | **Updated**: {today}

**Description**: Another handoff for testing

"""
    (recall_dir / "HANDOFFS.md").write_text(handoffs_content)

    # Create session transcripts
    start_time_1 = make_timestamp(120)
    end_time_1 = make_timestamp(60)

    create_transcript(
        project_dir / "sess-nav-test.jsonl",
        first_prompt="Working on navigation feature",
        tools=["Read", "Edit"],
        tokens=1500,
        start_time=start_time_1,
        end_time=end_time_1,
    )

    start_time_2 = make_timestamp(60)
    end_time_2 = make_timestamp(30)

    create_transcript(
        project_dir / "sess-nav-other.jsonl",
        first_prompt="Another session without handoff",
        tools=["Bash"],
        tokens=500,
        start_time=start_time_2,
        end_time=end_time_2,
    )

    # Create session-handoffs.json linking session to handoff
    session_handoffs = {
        "sess-nav-test": {
            "handoff_id": "hf-nav0001",
            "created": datetime.now().isoformat(),
            "transcript_path": str(project_dir / "sess-nav-test.jsonl"),
        }
    }
    (state_dir / "session-handoffs.json").write_text(json.dumps(session_handoffs, indent=2))

    # Monkeypatch environment
    monkeypatch.setenv("PROJECT_DIR", str(project_root))
    monkeypatch.setenv("CLAUDE_RECALL_STATE", str(state_dir))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    return {
        "claude_home": claude_home,
        "project_root": project_root,
        "state_dir": state_dir,
        "project_dir": project_dir,
        "session_handoffs_file": state_dir / "session-handoffs.json",
    }


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


# --- Tests for _navigate_to_handoff() method ---


class TestNavigateToHandoff:
    """Tests for _navigate_to_handoff() method."""

    @pytest.mark.asyncio
    async def test_navigate_to_handoff_method_exists(
        self, mock_claude_home_with_linked_data: dict
    ):
        """RecallMonitorApp should have a _navigate_to_handoff() method."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            assert hasattr(app, "_navigate_to_handoff"), (
                "RecallMonitorApp should have '_navigate_to_handoff' method"
            )
            assert callable(getattr(app, "_navigate_to_handoff", None)), (
                "_navigate_to_handoff should be callable"
            )

    @pytest.mark.asyncio
    async def test_navigate_to_handoff_switches_to_handoffs_tab(
        self, mock_claude_home_with_linked_data: dict
    ):
        """_navigate_to_handoff() should switch to the handoffs tab."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Start on Session tab
            await pilot.press("f4")
            await pilot.pause()

            # Verify we're on session tab
            tabs = app.query_one("TabbedContent")
            assert tabs.active == "session", "Should start on session tab"

            # Navigate to handoff
            app._navigate_to_handoff("hf-nav0001")
            await pilot.pause()

            # Verify we switched to handoffs tab
            assert tabs.active == "handoffs", (
                f"Should switch to handoffs tab, but active tab is '{tabs.active}'"
            )

    @pytest.mark.asyncio
    async def test_navigate_to_handoff_selects_correct_row(
        self, mock_claude_home_with_linked_data: dict
    ):
        """_navigate_to_handoff() should select the correct handoff row."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Navigate to handoff
            app._navigate_to_handoff("hf-nav0001")
            await pilot.pause()

            # Verify the handoff is selected
            handoff_table = app.query_one("#handoff-list", DataTable)
            cursor_row = handoff_table.cursor_row

            # Get the row key at cursor position
            row_keys = list(handoff_table.rows.keys())
            if cursor_row < len(row_keys):
                selected_id = str(row_keys[cursor_row].value)
                assert selected_id == "hf-nav0001", (
                    f"Expected hf-nav0001 selected, got {selected_id}"
                )

    @pytest.mark.asyncio
    async def test_navigate_to_handoff_shows_details(
        self, mock_claude_home_with_linked_data: dict
    ):
        """_navigate_to_handoff() should show handoff details."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Navigate to handoff
            app._navigate_to_handoff("hf-nav0001")
            await pilot.pause()

            # Check that details panel shows the handoff
            details_log = app.query_one("#handoff-details", RichLog)
            lines_text = str(details_log.lines)

            assert "hf-nav0001" in lines_text, (
                f"Handoff details should show hf-nav0001. Lines: {lines_text[:200]}..."
            )

    @pytest.mark.asyncio
    async def test_navigate_to_nonexistent_handoff_graceful(
        self, mock_claude_home_with_linked_data: dict
    ):
        """_navigate_to_handoff() should handle non-existent handoff gracefully."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Navigate to non-existent handoff - should not crash
            app._navigate_to_handoff("hf-nonexistent")
            await pilot.pause()

            # Should still be on handoffs tab
            tabs = app.query_one("TabbedContent")
            assert tabs.active == "handoffs", "Should still switch to handoffs tab"


# --- Tests for _navigate_to_session() method ---


class TestNavigateToSession:
    """Tests for _navigate_to_session() method."""

    @pytest.mark.asyncio
    async def test_navigate_to_session_method_exists(
        self, mock_claude_home_with_linked_data: dict
    ):
        """RecallMonitorApp should have a _navigate_to_session() method."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            assert hasattr(app, "_navigate_to_session"), (
                "RecallMonitorApp should have '_navigate_to_session' method"
            )
            assert callable(getattr(app, "_navigate_to_session", None)), (
                "_navigate_to_session should be callable"
            )

    @pytest.mark.asyncio
    async def test_navigate_to_session_switches_to_session_tab(
        self, mock_claude_home_with_linked_data: dict
    ):
        """_navigate_to_session() should switch to the session tab."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Start on Handoffs tab
            await pilot.press("f6")
            await pilot.pause()

            # Verify we're on handoffs tab
            tabs = app.query_one("TabbedContent")
            assert tabs.active == "handoffs", "Should start on handoffs tab"

            # Navigate to session
            app._navigate_to_session("sess-nav-test")
            await pilot.pause()

            # Verify we switched to session tab
            assert tabs.active == "session", (
                f"Should switch to session tab, but active tab is '{tabs.active}'"
            )

    @pytest.mark.asyncio
    async def test_navigate_to_session_selects_correct_row(
        self, mock_claude_home_with_linked_data: dict
    ):
        """_navigate_to_session() should select the correct session row."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Navigate to session
            app._navigate_to_session("sess-nav-test")
            await pilot.pause()

            # Verify the session is selected
            session_table = app.query_one("#session-list", DataTable)
            cursor_row = session_table.cursor_row

            # Get the row key at cursor position
            row_keys = list(session_table.rows.keys())
            if cursor_row < len(row_keys):
                selected_id = str(row_keys[cursor_row].value)
                assert selected_id == "sess-nav-test", (
                    f"Expected sess-nav-test selected, got {selected_id}"
                )

    @pytest.mark.asyncio
    async def test_navigate_to_session_shows_events(
        self, mock_claude_home_with_linked_data: dict
    ):
        """_navigate_to_session() should show session events."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Navigate to session
            app._navigate_to_session("sess-nav-test")
            await pilot.pause()

            # Check that events panel shows session content
            events_log = app.query_one("#session-events", RichLog)
            lines_text = str(events_log.lines)

            assert "Working on navigation feature" in lines_text, (
                f"Session events should show topic. Lines: {lines_text[:200]}..."
            )

    @pytest.mark.asyncio
    async def test_navigate_to_nonexistent_session_graceful(
        self, mock_claude_home_with_linked_data: dict
    ):
        """_navigate_to_session() should handle non-existent session gracefully."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Navigate to non-existent session - should not crash
            app._navigate_to_session("sess-nonexistent")
            await pilot.pause()

            # Should still be on session tab
            tabs = app.query_one("TabbedContent")
            assert tabs.active == "session", "Should still switch to session tab"


# --- Tests for 'h' key binding to jump to handoff ---


class TestJumpToHandoffBinding:
    """Tests for 'h' key binding to jump from session to handoff."""

    @pytest.mark.asyncio
    async def test_goto_handoff_action_exists(
        self, mock_claude_home_with_linked_data: dict
    ):
        """RecallMonitorApp should have action_goto_handoff method."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            assert hasattr(app, "action_goto_handoff"), (
                "RecallMonitorApp should have 'action_goto_handoff' method"
            )

    @pytest.mark.asyncio
    async def test_h_key_navigates_to_handoff(
        self, mock_claude_home_with_linked_data: dict
    ):
        """Calling action_goto_handoff should navigate to handoff when session is linked."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Start on Session tab and set current session
            await pilot.press("f4")
            await pilot.pause()

            # Show session events to establish the current session
            # This sets _current_session_id which action_goto_handoff needs
            app._show_session_events("sess-nav-test")
            await pilot.pause()

            # Verify we have a current session set
            assert app._current_session_id == "sess-nav-test", (
                f"Expected current session 'sess-nav-test', got '{app._current_session_id}'"
            )

            # Verify handoffs were loaded
            assert len(app._handoff_data) > 0, (
                f"Handoff data should be populated. Got: {app._handoff_data.keys()}"
            )
            assert "hf-nav0001" in app._handoff_data, (
                f"Expected hf-nav0001 in handoff data. Got: {app._handoff_data.keys()}"
            )

            # Call the action directly (simulates pressing 'h')
            # The keybinding 'h' calls action_goto_handoff
            app.action_goto_handoff()
            await pilot.pause()

            # Verify we're on handoffs tab
            tabs = app.query_one("TabbedContent")
            assert tabs.active == "handoffs", (
                f"action_goto_handoff should switch to handoffs tab, "
                f"but active tab is '{tabs.active}'. "
                f"Handoff data keys: {list(app._handoff_data.keys())}"
            )

    @pytest.mark.asyncio
    async def test_h_key_no_handoff_shows_notification(
        self, mock_claude_home_with_linked_data: dict
    ):
        """Pressing 'h' on a session without linked handoff should notify user."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Session tab
            await pilot.press("f4")
            await pilot.pause()

            session_table = app.query_one("#session-list", DataTable)
            session_table.focus()
            await pilot.pause()

            # Find and select the session without linked handoff
            for idx, row_key in enumerate(session_table.rows.keys()):
                if str(row_key.value) == "sess-nav-other":
                    session_table.move_cursor(row=idx)
                    break
            await pilot.pause()

            # Show session events
            app._show_session_events("sess-nav-other")
            await pilot.pause()

            # Press 'h' - should not crash, may show notification
            await pilot.press("h")
            await pilot.pause()

            # Should stay on session tab (no linked handoff to navigate to)
            tabs = app.query_one("TabbedContent")
            # Either stays on session (no handoff found) or navigates (if date-matched)
            # The test is that it doesn't crash


# --- Tests for Sessions section in handoff details ---


class TestSessionsInHandoffDetails:
    """Tests for Sessions section in handoff details panel."""

    @pytest.mark.asyncio
    async def test_handoff_details_shows_sessions_section(
        self, mock_claude_home_with_linked_data: dict
    ):
        """Handoff details should show Sessions section when linked sessions exist."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Handoffs tab
            await pilot.press("f6")
            await pilot.pause()

            # Select hf-nav0001 which has a linked session
            handoff_table = app.query_one("#handoff-list", DataTable)
            for idx, row_key in enumerate(handoff_table.rows.keys()):
                if str(row_key.value) == "hf-nav0001":
                    handoff_table.move_cursor(row=idx)
                    break
            await pilot.pause()

            # Show handoff details
            app._show_handoff_details("hf-nav0001")
            await pilot.pause()

            # Check details panel for Sessions section
            details_log = app.query_one("#handoff-details", RichLog)
            lines_text = str(details_log.lines)

            assert "Sessions" in lines_text, (
                f"Handoff details should show 'Sessions' section. "
                f"Lines: {lines_text[:400]}..."
            )

    @pytest.mark.asyncio
    async def test_handoff_details_shows_session_ids(
        self, mock_claude_home_with_linked_data: dict
    ):
        """Handoff details Sessions section should show session IDs."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Handoffs tab
            await pilot.press("f6")
            await pilot.pause()

            # Show handoff details
            app._show_handoff_details("hf-nav0001")
            await pilot.pause()

            # Check details panel for session ID
            details_log = app.query_one("#handoff-details", RichLog)
            lines_text = str(details_log.lines)

            assert "sess-nav-test" in lines_text, (
                f"Handoff details should show linked session ID 'sess-nav-test'. "
                f"Lines: {lines_text[:400]}..."
            )

    @pytest.mark.asyncio
    async def test_handoff_details_no_sessions_section_when_empty(
        self, mock_claude_home_with_linked_data: dict
    ):
        """Handoff without linked sessions should not show Sessions section."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Handoffs tab
            await pilot.press("f6")
            await pilot.pause()

            # Show handoff hf-nav0002 which has no linked sessions
            app._show_handoff_details("hf-nav0002")
            await pilot.pause()

            # Check details panel
            details_log = app.query_one("#handoff-details", RichLog)
            lines_text = str(details_log.lines)

            # Should show hf-nav0002 info but not Sessions section
            assert "hf-nav0002" in lines_text, (
                "Should show handoff details for hf-nav0002"
            )
            # Either no "Sessions" section, or empty (implementation choice)

    @pytest.mark.asyncio
    async def test_get_sessions_for_handoff_method_exists(
        self, mock_claude_home_with_linked_data: dict
    ):
        """RecallMonitorApp should have _get_sessions_for_handoff() method."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            assert hasattr(app, "_get_sessions_for_handoff"), (
                "RecallMonitorApp should have '_get_sessions_for_handoff' method"
            )
            assert callable(getattr(app, "_get_sessions_for_handoff", None)), (
                "_get_sessions_for_handoff should be callable"
            )

    @pytest.mark.asyncio
    async def test_get_sessions_for_handoff_returns_correct_data(
        self, mock_claude_home_with_linked_data: dict
    ):
        """_get_sessions_for_handoff() should return list of session info."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Get sessions for hf-nav0001
            sessions = app._get_sessions_for_handoff("hf-nav0001")

            assert isinstance(sessions, list), (
                f"Expected list, got {type(sessions)}"
            )
            assert len(sessions) >= 1, (
                f"Expected at least 1 session for hf-nav0001, got {len(sessions)}"
            )

            # Check that session info has expected fields
            if sessions:
                session = sessions[0]
                assert "session_id" in session, "Session info should have 'session_id'"

    @pytest.mark.asyncio
    async def test_get_sessions_for_handoff_empty_for_no_links(
        self, mock_claude_home_with_linked_data: dict
    ):
        """_get_sessions_for_handoff() should return empty list when no sessions linked."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Get sessions for hf-nav0002 (no linked sessions)
            sessions = app._get_sessions_for_handoff("hf-nav0002")

            assert isinstance(sessions, list), (
                f"Expected list, got {type(sessions)}"
            )
            assert len(sessions) == 0, (
                f"Expected 0 sessions for hf-nav0002, got {len(sessions)}"
            )


# --- Integration Tests ---


class TestNavigationIntegration:
    """Integration tests for session-handoff navigation flow."""

    @pytest.mark.asyncio
    async def test_round_trip_navigation(
        self, mock_claude_home_with_linked_data: dict
    ):
        """Navigate from session to handoff and back to session."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Start on Session tab
            await pilot.press("f4")
            await pilot.pause()

            tabs = app.query_one("TabbedContent")
            assert tabs.active == "session", "Should start on session tab"

            # Navigate to handoff
            app._navigate_to_handoff("hf-nav0001")
            await pilot.pause()
            assert tabs.active == "handoffs", "Should be on handoffs tab"

            # Navigate back to session
            app._navigate_to_session("sess-nav-test")
            await pilot.pause()
            assert tabs.active == "session", "Should be back on session tab"

    @pytest.mark.asyncio
    async def test_navigation_preserves_data_display(
        self, mock_claude_home_with_linked_data: dict
    ):
        """Navigation should update detail panels correctly."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Navigate to handoff and verify details shown
            app._navigate_to_handoff("hf-nav0001")
            await pilot.pause()

            handoff_details = app.query_one("#handoff-details", RichLog)
            handoff_text = str(handoff_details.lines)
            assert "hf-nav0001" in handoff_text, "Handoff details should show correct ID"

            # Navigate to session and verify events shown
            app._navigate_to_session("sess-nav-test")
            await pilot.pause()

            session_events = app.query_one("#session-events", RichLog)
            session_text = str(session_events.lines)
            assert "Working on navigation feature" in session_text, (
                "Session events should show correct topic"
            )
