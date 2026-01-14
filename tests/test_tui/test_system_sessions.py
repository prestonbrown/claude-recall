#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Tests for agent session filtering in the TUI.

These tests verify:
- Agent sessions (all non-"User" origins) hidden by default
- Toggle shows/hides agent sessions
- Count indicator shows correct numbers
- Command palette has toggle option
"""

import json
import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path

pytest.importorskip("textual")

# Configure pytest-asyncio
pytest_plugins = ("pytest_asyncio",)

from textual.widgets import DataTable, Static

# Import app with fallback for installed vs dev paths
try:
    from core.tui.app import RecallMonitorApp
    from core.tui.transcript_reader import TranscriptSummary
except ImportError:
    from .app import RecallMonitorApp
    from .transcript_reader import TranscriptSummary


# --- Helper Functions ---


def make_timestamp(seconds_ago: int = 0) -> str:
    """Generate an ISO timestamp for N seconds ago."""
    dt = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def create_transcript(
    path: Path,
    first_prompt: str,
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

    # Assistant message
    messages.append(
        {
            "type": "assistant",
            "timestamp": end_time,
            "sessionId": path.stem,
            "message": {
                "role": "assistant",
                "usage": {"input_tokens": 100, "output_tokens": 50},
                "content": [{"type": "text", "text": "Done"}],
            },
        }
    )

    with open(path, "w") as f:
        for msg in messages:
            f.write(json.dumps(msg) + "\n")


# --- Fixtures ---


@pytest.fixture
def mock_state_dir(tmp_path: Path, monkeypatch) -> Path:
    """Create a mock state directory."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    # Create empty debug.log to prevent app errors
    (state_dir / "debug.log").write_text("")

    monkeypatch.setenv("CLAUDE_RECALL_STATE", str(state_dir))
    return state_dir


@pytest.fixture
def mock_claude_home_with_system_sessions(tmp_path: Path, monkeypatch, mock_state_dir) -> Path:
    """Create a mock ~/.claude directory with system and user sessions."""
    claude_home = tmp_path / ".claude"
    projects_dir = claude_home / "projects"

    project_dir = projects_dir / "-Users-test-code-project-a"
    project_dir.mkdir(parents=True)

    # User sessions (should be visible by default)
    # Note: Prompts must NOT start with agent keywords (implement, fix, explore, etc.)
    create_transcript(
        project_dir / "sess-user1.jsonl",
        first_prompt="Help me with the authentication bug",
        start_time=make_timestamp(60),
        end_time=make_timestamp(50),
    )

    create_transcript(
        project_dir / "sess-user2.jsonl",
        first_prompt="I need to add a new feature",
        start_time=make_timestamp(40),
        end_time=make_timestamp(30),
    )

    create_transcript(
        project_dir / "sess-user3.jsonl",
        first_prompt="Can you help with validation patterns?",
        start_time=make_timestamp(35),
        end_time=make_timestamp(25),
    )

    # Agent sessions (should be hidden by default) - Explore origin
    create_transcript(
        project_dir / "sess-explore.jsonl",
        first_prompt="Explore the codebase for validation patterns",
        start_time=make_timestamp(33),
        end_time=make_timestamp(23),
    )

    # System sessions (should be hidden by default)
    create_transcript(
        project_dir / "sess-system1.jsonl",
        first_prompt="Analyze this conversation and extract key information",
        start_time=make_timestamp(55),
        end_time=make_timestamp(45),
    )

    create_transcript(
        project_dir / "sess-system2.jsonl",
        first_prompt="Score each lesson's relevance to this query",
        start_time=make_timestamp(45),
        end_time=make_timestamp(35),
    )

    # Warmup sessions (should be hidden by default)
    create_transcript(
        project_dir / "sess-warmup1.jsonl",
        first_prompt="Warmup initialization task",
        start_time=make_timestamp(50),
        end_time=make_timestamp(40),
    )

    create_transcript(
        project_dir / "sess-warmup2.jsonl",
        first_prompt="Warmup for sub-agent",
        start_time=make_timestamp(30),
        end_time=make_timestamp(20),
    )

    monkeypatch.setenv("PROJECT_DIR", "/Users/test/code/project-a")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    return claude_home


# --- Tests for Agent Sessions Hidden by Default ---


class TestSystemSessionsHiddenByDefault:
    """Tests that agent sessions (non-User origins) are hidden by default."""

    @pytest.mark.asyncio
    async def test_system_sessions_hidden_by_default(self, mock_claude_home_with_system_sessions):
        """Sessions with non-User origins should be hidden by default."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Session tab
            await pilot.press("f4")
            await pilot.pause()

            session_table = app.query_one("#session-list", DataTable)

            # Should show: 3 user sessions (user1, user2, user3)
            # Should NOT show: 1 explore + 2 system + 2 warmup = 5 hidden
            row_count = session_table.row_count
            assert row_count == 3, (
                f"Expected 3 user sessions (agent sessions hidden by default), got {row_count}. "
                "All non-User sessions should be hidden by default."
            )

    @pytest.mark.asyncio
    async def test_warmup_sessions_hidden_by_default(self, mock_claude_home_with_system_sessions):
        """Sessions with origin 'Warmup' should be hidden by default."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Session tab
            await pilot.press("f4")
            await pilot.pause()

            # Verify that no warmup sessions are visible
            session_data = app.state.session.data
            visible_origins = [s.origin for s in session_data.values()]

            assert "Warmup" not in visible_origins, (
                f"Warmup sessions should be hidden by default. "
                f"Visible origins: {visible_origins}"
            )

    @pytest.mark.asyncio
    async def test_only_user_sessions_visible_by_default(self, mock_claude_home_with_system_sessions):
        """Only sessions with origin 'User' should be visible by default."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Session tab
            await pilot.press("f4")
            await pilot.pause()

            session_data = app.state.session.data
            visible_origins = set(s.origin for s in session_data.values())

            # Only User sessions should be visible
            assert visible_origins == {"User"}, (
                f"Only 'User' origin should be visible by default. "
                f"Visible origins: {visible_origins}"
            )


# --- Tests for Toggle Agent Sessions ---


class TestToggleSystemSessions:
    """Tests for the agent sessions toggle ('w' key)."""

    @pytest.mark.asyncio
    async def test_toggle_shows_system_sessions(self, mock_claude_home_with_system_sessions):
        """Pressing 'w' should show all agent sessions."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Session tab
            await pilot.press("f4")
            await pilot.pause()

            session_table = app.query_one("#session-list", DataTable)
            initial_count = session_table.row_count

            # Initial count should be 3 (user sessions only)
            assert initial_count == 3, f"Expected 3 user sessions initially, got {initial_count}"

            # Press 'w' to toggle - should show ALL sessions including agent sessions
            await pilot.press("w")
            await pilot.pause()

            after_toggle = session_table.row_count

            # After toggle, should show all 8 sessions (3 user + 1 explore + 2 system + 2 warmup)
            assert after_toggle == 8, (
                f"Expected 8 sessions after toggle (all visible), got {after_toggle}"
            )

    @pytest.mark.asyncio
    async def test_toggle_twice_returns_to_default(self, mock_claude_home_with_system_sessions):
        """Pressing 'w' twice should return to hiding system sessions."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Session tab
            await pilot.press("f4")
            await pilot.pause()

            session_table = app.query_one("#session-list", DataTable)
            initial_count = session_table.row_count

            # Toggle on
            await pilot.press("w")
            await pilot.pause()

            # Toggle off
            await pilot.press("w")
            await pilot.pause()

            after_double_toggle = session_table.row_count

            # Should be back to initial count (3 user sessions)
            assert after_double_toggle == initial_count, (
                f"Expected {initial_count} sessions after double toggle, "
                f"got {after_double_toggle}"
            )

    @pytest.mark.asyncio
    async def test_toggle_state_persists_across_refresh(self, mock_claude_home_with_system_sessions):
        """Toggle state should persist across manual refresh."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Session tab
            await pilot.press("f4")
            await pilot.pause()

            # Toggle to show system sessions
            await pilot.press("w")
            await pilot.pause()

            session_table = app.query_one("#session-list", DataTable)
            after_toggle = session_table.row_count

            # Press 'r' to refresh
            await pilot.press("r")
            await pilot.pause()

            after_refresh = session_table.row_count

            # Should still show all sessions after refresh
            assert after_refresh == after_toggle, (
                f"Toggle state should persist after refresh. "
                f"Expected {after_toggle}, got {after_refresh}"
            )


# --- Tests for Count Indicator ---


def _get_sessions_title_content(app) -> str:
    """Helper to get the sessions section title content."""
    try:
        session_pane = app.query_one("#session")
        title_widgets = session_pane.query("Static.section-title")
        for widget in title_widgets:
            content = str(widget.render())
            if "session" in content.lower():
                return content.lower()
        return ""
    except Exception:
        return ""


class TestSessionCountIndicator:
    """Tests for the session count indicator."""

    @pytest.mark.asyncio
    async def test_count_indicator_shows_user_count(self, mock_claude_home_with_system_sessions):
        """Count indicator should show number of user sessions."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Session tab
            await pilot.press("f4")
            await pilot.pause()

            # Get the title content from the Static widget
            title_content = _get_sessions_title_content(app)

            # Should indicate 3 user sessions
            has_user_count = "3 user" in title_content

            assert has_user_count, (
                f"Count indicator should show '3 user'. Got title: '{title_content}'"
            )

    @pytest.mark.asyncio
    async def test_count_indicator_shows_hidden_count(self, mock_claude_home_with_system_sessions):
        """Count indicator should show how many agent sessions are hidden."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Session tab
            await pilot.press("f4")
            await pilot.pause()

            # Get the title content from the Static widget
            title_content = _get_sessions_title_content(app)

            # Should indicate 5 hidden (1 explore + 2 system + 2 warmup)
            has_hidden_info = "5 agent hidden" in title_content

            assert has_hidden_info, (
                f"Count indicator should show '5 agent hidden'. "
                f"Got title: '{title_content}'"
            )

    @pytest.mark.asyncio
    async def test_count_indicator_updates_after_toggle(self, mock_claude_home_with_system_sessions):
        """Count indicator should update when toggle is pressed."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Session tab
            await pilot.press("f4")
            await pilot.pause()

            # Get initial title
            initial_title = _get_sessions_title_content(app)

            # Toggle to show system sessions
            await pilot.press("w")
            await pilot.pause()

            # Get updated title
            after_toggle_title = _get_sessions_title_content(app)

            # After toggle, should show total count without "hidden"
            # The exact format depends on implementation, but "hidden" should not appear
            # when all sessions are shown
            assert "hidden" not in after_toggle_title or after_toggle_title != initial_title, (
                f"Count indicator should update after toggle. "
                f"Initial: '{initial_title}', After: '{after_toggle_title}'"
            )


# --- Tests for Binding Exists ---


class TestSystemSessionsFooterHint:
    """Tests for the agent sessions toggle binding."""

    @pytest.mark.asyncio
    async def test_agent_toggle_binding_exists(self, mock_claude_home_with_system_sessions):
        """'w' key binding should exist for agent sessions toggle."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Session tab
            await pilot.press("f4")
            await pilot.pause()

            # Get all bindings and check for 'w' key
            bindings = app.active_bindings

            # Check that 'w' binding exists
            w_binding = None
            for binding_info in bindings.values():
                if binding_info.binding.key == "w":
                    w_binding = binding_info.binding
                    break

            assert w_binding is not None, "Should have 'w' key binding"

            # The binding description should indicate it's for agents toggle
            desc = w_binding.description.lower()
            assert "agents" in desc, (
                f"'w' binding should mention 'agents', "
                f"got description: '{w_binding.description}'"
            )


# --- Tests for Integration with All Toggle ---


class TestSystemSessionsWithAllToggle:
    """Tests for agent sessions toggle interaction with 'all projects' toggle."""

    @pytest.mark.asyncio
    async def test_agent_toggle_works_in_all_projects_mode(self, mock_claude_home_with_system_sessions):
        """Agent sessions toggle should work when viewing all projects."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Session tab
            await pilot.press("f4")
            await pilot.pause()

            # Toggle to all projects mode
            await pilot.press("a")
            await pilot.pause()

            session_table = app.query_one("#session-list", DataTable)
            initial_count = session_table.row_count

            # Should still show only user sessions (3)
            assert initial_count == 3, (
                f"Expected 3 user sessions in all-projects mode, got {initial_count}"
            )

            # Toggle agent sessions
            await pilot.press("w")
            await pilot.pause()

            after_toggle = session_table.row_count

            # Should now show all 8 sessions (3 user + 1 explore + 2 system + 2 warmup)
            assert after_toggle == 8, (
                f"Expected 8 sessions after agent toggle in all-projects mode, "
                f"got {after_toggle}"
            )
