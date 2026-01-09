#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Tests for TUI Session tab functionality.

These tests verify the Session tab works correctly with TranscriptReader:
- Session list populates from Claude transcript files
- Column sorting works (header clicks trigger sort)
- Session events display shows transcript timeline
- Topic column shows first user prompt
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
    from core.tui.app import (
        RecallMonitorApp,
        SessionDetailModal,
        _decode_project_path,
        _find_matching_handoff,
        _format_session_time,
        _format_tokens,
    )
    from core.tui.models import HandoffSummary
    from core.tui.transcript_reader import TranscriptReader, TranscriptSummary
except ImportError:
    from .app import (
        RecallMonitorApp,
        SessionDetailModal,
        _decode_project_path,
        _find_matching_handoff,
        _format_session_time,
        _format_tokens,
    )
    from .models import HandoffSummary
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

    # Create project directory (URL-encoded current working dir)
    # For testing, use a simple project path matching PROJECT_DIR
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

    # Session 2: middle session (no tokens - edge case)
    create_transcript(
        project_dir / "sess-middle.jsonl",
        first_prompt="Middle session task",
        tools=["Edit"],
        tokens=0,
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

    # Session 4: session with very long topic (> 100 chars)
    # This long prompt tests that the full topic is displayed without truncation
    long_topic = (
        "Implement a comprehensive authentication system with OAuth2 support, "
        "including Google and GitHub providers, session management with Redis, "
        "and JWT token refresh mechanisms for the new microservices architecture"
    )
    assert len(long_topic) > 100, f"Long topic should be > 100 chars, got {len(long_topic)}"
    create_transcript(
        project_dir / "sess-long-topic.jsonl",
        first_prompt=long_topic,
        tools=["Read", "Edit"],
        tokens=2500,
        start_time=make_timestamp(30),
        end_time=make_timestamp(25),
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


# --- Tests for TranscriptReader ---


class TestTranscriptReader:
    """Tests for TranscriptReader reading transcript files."""

    def test_list_sessions_finds_transcripts(self, mock_claude_home: Path):
        """TranscriptReader should find transcript files in project directory."""
        reader = TranscriptReader(claude_home=mock_claude_home)
        sessions = reader.list_sessions("/Users/test/code/project-a")

        assert len(sessions) == 4, (
            f"Expected 4 sessions from transcript files, got {len(sessions)}"
        )

    def test_list_sessions_sorted_by_recency(self, mock_claude_home: Path):
        """Sessions should be sorted by last_activity, most recent first."""
        reader = TranscriptReader(claude_home=mock_claude_home)
        sessions = reader.list_sessions("/Users/test/code/project-a")

        # Recent (5s ago) should be first, older (50s ago) should be last
        assert sessions[0].session_id == "sess-recent", (
            f"Expected sess-recent first (most recent), got {sessions[0].session_id}"
        )
        assert sessions[-1].session_id == "sess-older", (
            f"Expected sess-older last (oldest), got {sessions[-1].session_id}"
        )

    def test_session_summary_extracts_first_prompt(self, mock_claude_home: Path):
        """TranscriptSummary should capture first user message as first_prompt."""
        reader = TranscriptReader(claude_home=mock_claude_home)
        sessions = reader.list_sessions("/Users/test/code/project-a")

        # Find sess-recent
        recent = next(s for s in sessions if s.session_id == "sess-recent")
        assert recent.first_prompt == "Recent task with many tools", (
            f"Expected first_prompt from user message, got '{recent.first_prompt}'"
        )

    def test_session_summary_extracts_tool_breakdown(self, mock_claude_home: Path):
        """TranscriptSummary should count tool usage from assistant messages."""
        reader = TranscriptReader(claude_home=mock_claude_home)
        sessions = reader.list_sessions("/Users/test/code/project-a")

        # Find sess-recent (has 4 tools)
        recent = next(s for s in sessions if s.session_id == "sess-recent")

        total_tools = sum(recent.tool_breakdown.values())
        assert total_tools == 4, (
            f"Expected 4 total tools, got {total_tools}. "
            f"Tool breakdown: {recent.tool_breakdown}"
        )

    def test_session_summary_extracts_tokens(self, mock_claude_home: Path):
        """TranscriptSummary should sum input + output tokens from assistant messages."""
        reader = TranscriptReader(claude_home=mock_claude_home)
        sessions = reader.list_sessions("/Users/test/code/project-a")

        # Find sess-recent (input_tokens=100, output_tokens=5000, total=5100)
        recent = next(s for s in sessions if s.session_id == "sess-recent")
        assert recent.input_tokens == 100, (
            f"Expected 100 input tokens, got {recent.input_tokens}"
        )
        assert recent.output_tokens == 5000, (
            f"Expected 5000 output tokens, got {recent.output_tokens}"
        )
        assert recent.total_tokens == 5100, (
            f"Expected 5100 total tokens (100+5000), got {recent.total_tokens}"
        )

        # Find sess-middle (input_tokens=100, output_tokens=0, total=100)
        middle = next(s for s in sessions if s.session_id == "sess-middle")
        assert middle.total_tokens == 100, (
            f"Expected 100 total tokens for middle session, got {middle.total_tokens}"
        )

    def test_load_session_returns_messages(self, mock_claude_home: Path):
        """load_session should return TranscriptMessage list."""
        reader = TranscriptReader(claude_home=mock_claude_home)
        sessions = reader.list_sessions("/Users/test/code/project-a")

        recent = next(s for s in sessions if s.session_id == "sess-recent")
        messages = reader.load_session(recent.path)

        # Should have 2 messages: user and assistant
        assert len(messages) == 2, (
            f"Expected 2 messages (user + assistant), got {len(messages)}"
        )
        assert messages[0].type == "user", "First message should be user"
        assert messages[1].type == "assistant", "Second message should be assistant"

    def test_load_session_extracts_tools(self, mock_claude_home: Path):
        """Assistant messages should have tools_used populated."""
        reader = TranscriptReader(claude_home=mock_claude_home)
        sessions = reader.list_sessions("/Users/test/code/project-a")

        recent = next(s for s in sessions if s.session_id == "sess-recent")
        messages = reader.load_session(recent.path)

        assistant_msg = messages[1]
        assert assistant_msg.tools_used == ["Read", "Grep", "Edit", "Bash"], (
            f"Expected tools from assistant message, got {assistant_msg.tools_used}"
        )


# --- Tests for Display Formatting ---


class TestDisplayFormatting:
    """Tests for session display formatting functions."""

    def test_format_tokens_shows_k_suffix(self):
        """Tokens >= 1000 should display with k suffix."""
        assert _format_tokens(1234) == "1.2k", (
            f"Expected '1.2k' for 1234 tokens, got '{_format_tokens(1234)}'"
        )
        assert _format_tokens(5000) == "5.0k", (
            f"Expected '5.0k' for 5000 tokens, got '{_format_tokens(5000)}'"
        )

    def test_format_tokens_zero_shows_dash(self):
        """Zero tokens should display as '--'."""
        assert _format_tokens(0) == "--", (
            f"Expected '--' for 0 tokens, got '{_format_tokens(0)}'"
        )

    def test_format_tokens_small_shows_number(self):
        """Tokens < 1000 should display as number."""
        assert _format_tokens(500) == "500", (
            f"Expected '500' for 500 tokens, got '{_format_tokens(500)}'"
        )

    def test_format_session_time_distinct(self, mock_claude_home: Path):
        """Start and last times should be different when events are apart."""
        reader = TranscriptReader(claude_home=mock_claude_home)
        sessions = reader.list_sessions("/Users/test/code/project-a")

        older = next(s for s in sessions if s.session_id == "sess-older")

        start_display = _format_session_time(older.start_time)
        last_display = _format_session_time(older.last_activity)

        assert start_display != last_display, (
            f"Start and Last display should differ but both show '{start_display}'. "
            "Session has events 10 seconds apart."
        )


# --- Tests for Session Sorting ---


class TestSessionSorting:
    """Tests for session table sorting functionality."""

    @pytest.mark.asyncio
    async def test_sort_by_tokens_orders_correctly(
        self, mock_claude_home: Path, temp_state_dir: Path
    ):
        """Sorting by tokens column puts rows in correct order."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Session tab
            await pilot.press("f4")
            await pilot.pause()

            session_table = app.query_one("#session-list", DataTable)

            # Should have 4 sessions
            assert session_table.row_count == 4, (
                f"Expected 4 sessions in table, got {session_table.row_count}"
            )

            # Call the internal method to sort by tokens descending
            app._sort_session_table("tokens", reverse=True)
            await pilot.pause()

            # Get sorted order
            sorted_order = [str(row_key.value) for row_key in session_table.rows.keys()]

            # After sorting by tokens descending:
            # sess-recent (5000) > sess-older (1234) > sess-middle (0)
            assert sorted_order[0] == "sess-recent", (
                f"After sorting by tokens desc, expected sess-recent first, "
                f"but got {sorted_order[0]}. Order: {sorted_order}"
            )
            assert sorted_order[-1] == "sess-middle", (
                f"After sorting by tokens desc, expected sess-middle last, "
                f"but got {sorted_order[-1]}. Order: {sorted_order}"
            )

    @pytest.mark.asyncio
    async def test_sort_by_tools_orders_correctly(
        self, mock_claude_home: Path, temp_state_dir: Path
    ):
        """Sorting by tools column puts rows in correct order."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Session tab
            await pilot.press("f4")
            await pilot.pause()

            session_table = app.query_one("#session-list", DataTable)

            # Sort by tools descending
            app._sort_session_table("tools", reverse=True)
            await pilot.pause()

            sorted_order = [str(row_key.value) for row_key in session_table.rows.keys()]

            # Tool counts: sess-recent (4) > sess-older (2) > sess-middle (1)
            assert sorted_order[0] == "sess-recent", (
                f"Expected sess-recent first (4 tools), got {sorted_order[0]}"
            )
            assert sorted_order[-1] == "sess-middle", (
                f"Expected sess-middle last (1 tool), got {sorted_order[-1]}"
            )

    @pytest.mark.asyncio
    async def test_header_click_toggles_sort_direction(
        self, mock_claude_home: Path, temp_state_dir: Path
    ):
        """Clicking same header should toggle ascending/descending."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Session tab
            await pilot.press("f4")
            await pilot.pause()

            session_table = app.query_one("#session-list", DataTable)

            # First sort: ascending (reverse=False)
            app._sort_session_table("tokens", reverse=False)
            await pilot.pause()

            first_order = [str(row_key.value) for row_key in session_table.rows.keys()]

            # Ascending: sess-middle (0) < sess-older (1234) < sess-recent (5000)
            assert first_order[0] == "sess-middle", (
                f"In ascending order, sess-middle should be first, got {first_order[0]}"
            )

            # Second sort: descending (reverse=True)
            app._sort_session_table("tokens", reverse=True)
            await pilot.pause()

            second_order = [str(row_key.value) for row_key in session_table.rows.keys()]

            # Descending: sess-recent (5000) > sess-older (1234) > sess-middle (0)
            assert second_order[0] == "sess-recent", (
                f"In descending order, sess-recent should be first, got {second_order[0]}"
            )

            # Orders should be reversed
            assert first_order != second_order, (
                "Toggling sort direction should change order."
            )


# --- Tests for Session Events Display ---


class TestSessionEvents:
    """Tests for session event display functionality."""

    @pytest.mark.asyncio
    async def test_row_highlight_shows_events(
        self, mock_claude_home: Path, temp_state_dir: Path
    ):
        """Arrow key navigation should show transcript in detail panel."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Session tab
            await pilot.press("f4")
            await pilot.pause()

            session_table = app.query_one("#session-list", DataTable)
            session_events = app.query_one("#session-events", RichLog)

            # Focus the session table
            session_table.focus()
            await pilot.pause()

            # Navigate with arrow keys to trigger highlight event
            await pilot.press("down")
            await pilot.pause()
            await pilot.press("up")
            await pilot.pause()

            # Session events panel should now have content
            event_count = len(session_events.lines)

            assert event_count > 0, (
                f"Session events panel should have transcript entries, "
                f"but has {event_count} lines. "
                "Row highlighting may not be triggering _show_session_events."
            )

    @pytest.mark.asyncio
    async def test_show_session_events_displays_transcript(
        self, mock_claude_home: Path, temp_state_dir: Path
    ):
        """_show_session_events should populate panel with transcript timeline."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Session tab
            await pilot.press("f4")
            await pilot.pause()

            session_events = app.query_one("#session-events", RichLog)

            # Call _show_session_events directly to show a specific session
            app._show_session_events("sess-older")
            await pilot.pause()

            # Should have content for sess-older
            line_count = len(session_events.lines)

            assert line_count > 0, (
                f"_show_session_events should populate panel with transcript. "
                f"Got {line_count} lines."
            )

            # Verify it shows the correct session's content
            lines_text = str(session_events.lines)
            assert "Help me fix something old" in lines_text, (
                f"Panel should show sess-older's topic. Lines: {lines_text[:200]}..."
            )

    @pytest.mark.asyncio
    async def test_show_session_events_shows_topic(
        self, mock_claude_home: Path, temp_state_dir: Path
    ):
        """Session events panel should show the topic (first prompt)."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Session tab
            await pilot.press("f4")
            await pilot.pause()

            session_events = app.query_one("#session-events", RichLog)

            # Call _show_session_events
            app._show_session_events("sess-recent")
            await pilot.pause()

            # Get the rendered text content
            # RichLog.lines contains the actual text
            lines_text = str(session_events.lines)

            assert "Recent task with many tools" in lines_text, (
                f"Session events should show the topic (first prompt). "
                f"Lines: {lines_text[:200]}..."
            )

    @pytest.mark.asyncio
    async def test_show_session_events_shows_tools(
        self, mock_claude_home: Path, temp_state_dir: Path
    ):
        """Session events panel should show tool breakdown."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Session tab
            await pilot.press("f4")
            await pilot.pause()

            session_events = app.query_one("#session-events", RichLog)

            # Call _show_session_events
            app._show_session_events("sess-recent")
            await pilot.pause()

            # Get the rendered text content
            lines_text = str(session_events.lines)

            # Should show tool names
            assert "Read" in lines_text or "TOOL" in lines_text, (
                f"Session events should show tool usage. "
                f"Lines: {lines_text[:300]}..."
            )


# --- Tests for Session Table Integration ---


class TestSessionTableIntegration:
    """Integration tests for the session table."""

    @pytest.mark.asyncio
    async def test_session_table_shows_correct_data(
        self, mock_claude_home: Path, temp_state_dir: Path
    ):
        """Session table displays correct values from transcripts."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Session tab
            await pilot.press("f4")
            await pilot.pause()

            session_table = app.query_one("#session-list", DataTable)

            # Verify we have 4 sessions
            row_count = session_table.row_count
            assert row_count == 4, f"Expected 4 sessions in table, got {row_count}"

            # Find the row for sess-recent and check its data
            for row_key in session_table.rows.keys():
                if str(row_key.value) == "sess-recent":
                    # Get row data - columns are in order (single-project mode, no Project col):
                    # Session ID, Origin, Topic, Started, Last, Tools, Tokens, Msgs
                    row_data = session_table.get_row(row_key)

                    # Topic column (index 2) should show first prompt
                    topic_value = str(row_data[2])
                    assert "Recent task" in topic_value, (
                        f"Topic column should show first prompt, "
                        f"got '{topic_value}'"
                    )

                    # Tools column (index 5) should show "4"
                    tools_value = str(row_data[5])
                    assert tools_value == "4", (
                        f"Tools column should show '4' for 4 tools, "
                        f"got '{tools_value}'"
                    )

                    # Tokens column (index 6) should show "5.1k" for 5100 (100 input + 5000 output)
                    tokens_value = str(row_data[6])
                    assert tokens_value == "5.1k", (
                        f"Tokens column should show '5.1k' for 5100 tokens, "
                        f"got '{tokens_value}'"
                    )

                    # Messages column (index 7) should show "2"
                    msgs_value = str(row_data[7])
                    assert msgs_value == "2", (
                        f"Messages column should show '2', got '{msgs_value}'"
                    )

                    break
            else:
                pytest.fail("Could not find sess-recent row in table")

    @pytest.mark.asyncio
    async def test_session_selection_scrolls_to_top_for_new_session(
        self, mock_claude_home: Path, temp_state_dir: Path
    ):
        """Selecting a NEW session should scroll the events panel to the top.

        When viewing a different session than the current one, scroll_home()
        should be called to show the beginning (topic line).

        However, when viewing the SAME session again (e.g., during refresh),
        scroll_home() should NOT be called to preserve user's scroll position.
        """
        from unittest.mock import patch, MagicMock

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Session tab
            await pilot.press("f4")
            await pilot.pause()

            session_events = app.query_one("#session-events", RichLog)

            # First, show one session (this may have been done during mount)
            # Then switch to a DIFFERENT session and verify scroll_home is called
            app._current_session_id = "sess-older"  # Set to a different session

            # Track if scroll_home was called by patching
            scroll_home_called = False
            original_scroll_home = session_events.scroll_home

            def tracking_scroll_home(*args, **kwargs):
                nonlocal scroll_home_called
                scroll_home_called = True
                return original_scroll_home(*args, **kwargs)

            session_events.scroll_home = tracking_scroll_home

            # Call _show_session_events for a DIFFERENT session
            app._show_session_events("sess-recent")
            await pilot.pause()

            # Verify scroll_home was called when viewing a NEW session
            assert scroll_home_called, (
                "After switching to a DIFFERENT session, scroll_home() should be called "
                "to scroll to the top and show the topic line first."
            )

    @pytest.mark.asyncio
    async def test_events_panel_shows_full_topic(
        self, mock_claude_home: Path, temp_state_dir: Path
    ):
        """Events panel should display the full topic without truncation.

        Currently truncates to 100 chars: topic = summary.first_prompt[:100]
        Should show the full first_prompt without truncation.
        Location: core/tui/app.py:781-785 in _show_session_events
        """
        app = RecallMonitorApp()

        # Use wider terminal to fit full topic (217 chars)
        async with app.run_test(size=(250, 24)) as pilot:
            await pilot.pause()

            # Switch to Session tab
            await pilot.press("f4")
            await pilot.pause()

            session_events = app.query_one("#session-events", RichLog)

            # Call _show_session_events for the long-topic session
            app._show_session_events("sess-long-topic")
            await pilot.pause()

            # Get the rendered text content
            lines_text = str(session_events.lines)

            # The full topic is 210 chars, but TranscriptSummary.first_prompt
            # truncates to 200 chars. Verify we're not adding a second truncation at 100.
            # Current buggy code: topic = summary.first_prompt[:100]
            full_topic = (
                "Implement a comprehensive authentication system with OAuth2 support, "
                "including Google and GitHub providers, session management with Redis, "
                "and JWT token refresh mechanisms for the new microservices architecture"
            )

            # Check that text AFTER the 100-char mark appears (proves no 100-char truncation)
            # "session management" starts at char ~110, so it would be cut by [:100]
            # but should appear since first_prompt stores up to 200 chars
            assert "session management" in lines_text, (
                f"Events panel should show full first_prompt (up to 200 chars). "
                f"Text after char 100 ('session management') should appear. "
                f"Fix: Remove the [:100] truncation in _show_session_events. "
                f"Lines: {lines_text[:300]}..."
            )

            # Also verify ellipsis is NOT present (since we're not truncating)
            # The current buggy code adds "..." after truncation
            # NOTE: Only check for the specific truncation pattern, not all ellipsis
            # (user content in timeline may have ellipsis)
            topic_line = [line for line in str(session_events.lines).split("\\n")
                          if "Topic:" in str(line)]
            if topic_line:
                topic_text = str(topic_line[0])
                # If truncated at 100 chars, it would end with "..." after ~100 chars of topic
                truncated_end = full_topic[:100] + "..."
                assert truncated_end not in topic_text, (
                    f"Topic should NOT be truncated with '...' at 100 chars. "
                    f"Found truncated pattern in topic line: {topic_text}"
                )

    @pytest.mark.asyncio
    async def test_session_table_project_column(
        self, mock_claude_home: Path, temp_state_dir: Path
    ):
        """Project column shows correct project name (visible in all-projects mode)."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Session tab
            await pilot.press("f4")
            await pilot.pause()

            # Toggle to all-projects mode (so Project column is visible)
            await pilot.press("a")
            await pilot.pause()

            session_table = app.query_one("#session-list", DataTable)

            # Find any row and check project column (index 1 in all-projects mode)
            for row_key in session_table.rows.keys():
                row_data = session_table.get_row(row_key)
                project_value = str(row_data[1])
                assert "project-a" in project_value or project_value == "a", (
                    f"Project column should show project name, got '{project_value}'"
                )
                break

    @pytest.mark.asyncio
    async def test_session_data_cached(
        self, mock_claude_home: Path, temp_state_dir: Path
    ):
        """Session data should be cached in _session_data dict."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Session tab
            await pilot.press("f4")
            await pilot.pause()

            # Check that session data is cached
            assert len(app._session_data) == 4, (
                f"Expected 4 sessions in _session_data cache, "
                f"got {len(app._session_data)}"
            )

            # Verify cached data is TranscriptSummary
            for session_id, summary in app._session_data.items():
                assert isinstance(summary, TranscriptSummary), (
                    f"Cached data for {session_id} should be TranscriptSummary, "
                    f"got {type(summary)}"
                )


# --- Tests for Lesson Citations Display ---


def create_transcript_with_citations(
    path: Path,
    first_prompt: str,
    tools: list,
    tokens: int,
    start_time: str,
    end_time: str,
    assistant_text: str,
) -> None:
    """Create a mock transcript JSONL file with assistant text containing citations."""
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

    # Assistant message with tools and text content (including citations)
    content = []
    for t in tools:
        content.append({"type": "tool_use", "name": t, "input": {}})
    if assistant_text:
        content.append({"type": "text", "text": assistant_text})

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


@pytest.fixture
def mock_claude_home_with_citations(tmp_path: Path, monkeypatch) -> Path:
    """Create a mock ~/.claude directory with transcript files including citations."""
    claude_home = tmp_path / ".claude"
    projects_dir = claude_home / "projects"

    # Create project directory
    project_dir = projects_dir / "-Users-test-code-project-b"
    project_dir.mkdir(parents=True)

    # Session with citations
    create_transcript_with_citations(
        project_dir / "sess-with-citations.jsonl",
        first_prompt="Help me with authentication",
        tools=["Read", "Edit"],
        tokens=1500,
        start_time=make_timestamp(30),
        end_time=make_timestamp(20),
        assistant_text="Based on [L001]: Security patterns, I recommend using [S002]: OAuth best practices.",
    )

    # Session without citations
    create_transcript(
        project_dir / "sess-no-citations.jsonl",
        first_prompt="Simple task without lessons",
        tools=["Bash"],
        tokens=500,
        start_time=make_timestamp(15),
        end_time=make_timestamp(10),
    )

    # Monkeypatch to use our mock Claude home and project dir
    monkeypatch.setenv("PROJECT_DIR", "/Users/test/code/project-b")

    # Monkeypatch Path.home() to return our tmp_path
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    return claude_home


class TestLessonCitationsDisplay:
    """Tests for lesson citations display in session events panel."""

    @pytest.mark.asyncio
    async def test_events_panel_shows_lesson_citations(
        self, mock_claude_home_with_citations: Path, temp_state_dir: Path
    ):
        """Verify 'Lessons cited: L001, S002' appears when session has citations."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Session tab
            await pilot.press("f4")
            await pilot.pause()

            session_events = app.query_one("#session-events", RichLog)

            # Call _show_session_events for the session with citations
            app._show_session_events("sess-with-citations")
            await pilot.pause()

            # Get the rendered text content
            lines_text = str(session_events.lines)

            # Should show "Lessons cited:" line
            assert "Lessons cited:" in lines_text, (
                f"Session events panel should show 'Lessons cited:' for sessions with citations. "
                f"Lines: {lines_text[:300]}..."
            )

            # Should show the actual citation IDs
            assert "L001" in lines_text, (
                f"Session events should show L001 citation. Lines: {lines_text[:300]}..."
            )
            assert "S002" in lines_text, (
                f"Session events should show S002 citation. Lines: {lines_text[:300]}..."
            )

    @pytest.mark.asyncio
    async def test_events_panel_no_citations_line_when_empty(
        self, mock_claude_home_with_citations: Path, temp_state_dir: Path
    ):
        """Verify no 'Lessons cited' line when session has no citations."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Session tab
            await pilot.press("f4")
            await pilot.pause()

            session_events = app.query_one("#session-events", RichLog)

            # Call _show_session_events for the session WITHOUT citations
            app._show_session_events("sess-no-citations")
            await pilot.pause()

            # Get the rendered text content
            lines_text = str(session_events.lines)

            # Should NOT show "Lessons cited:" line
            assert "Lessons cited:" not in lines_text, (
                f"Session events panel should NOT show 'Lessons cited:' line when "
                f"session has no citations. Lines: {lines_text[:300]}..."
            )

    def test_transcript_summary_extracts_citations(
        self, mock_claude_home_with_citations: Path
    ):
        """TranscriptSummary should extract lesson citations from assistant messages."""
        reader = TranscriptReader(claude_home=mock_claude_home_with_citations)
        sessions = reader.list_sessions("/Users/test/code/project-b")

        # Find the session with citations
        with_citations = next(
            s for s in sessions if s.session_id == "sess-with-citations"
        )

        assert len(with_citations.lesson_citations) == 2, (
            f"Expected 2 lesson citations, got {len(with_citations.lesson_citations)}. "
            f"Citations: {with_citations.lesson_citations}"
        )
        assert "L001" in with_citations.lesson_citations, (
            f"Expected L001 in citations, got {with_citations.lesson_citations}"
        )
        assert "S002" in with_citations.lesson_citations, (
            f"Expected S002 in citations, got {with_citations.lesson_citations}"
        )

    def test_transcript_summary_empty_citations_for_no_lessons(
        self, mock_claude_home_with_citations: Path
    ):
        """TranscriptSummary should have empty citations list when no lessons cited."""
        reader = TranscriptReader(claude_home=mock_claude_home_with_citations)
        sessions = reader.list_sessions("/Users/test/code/project-b")

        # Find the session without citations
        no_citations = next(
            s for s in sessions if s.session_id == "sess-no-citations"
        )

        assert len(no_citations.lesson_citations) == 0, (
            f"Expected 0 lesson citations for session without lessons, "
            f"got {len(no_citations.lesson_citations)}. "
            f"Citations: {no_citations.lesson_citations}"
        )


# --- Tests for Session Detail Modal ---


class TestSessionDetailModal:
    """Tests for the session detail modal functionality."""

    @pytest.mark.asyncio
    async def test_expand_keybinding_opens_modal(
        self, mock_claude_home: Path, temp_state_dir: Path
    ):
        """Pressing 'e' on a highlighted session should open the detail modal."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Session tab
            await pilot.press("f4")
            await pilot.pause()

            session_table = app.query_one("#session-list", DataTable)

            # Focus the session table and select a row
            session_table.focus()
            await pilot.pause()

            # Press 'e' to expand
            await pilot.press("e")
            await pilot.pause()

            # Check that a modal screen was pushed
            # The app should now have SessionDetailModal as the active screen
            assert len(app.screen_stack) > 1, (
                "Expected modal to be pushed onto screen stack after pressing 'e'"
            )
            assert isinstance(app.screen, SessionDetailModal), (
                f"Expected SessionDetailModal to be active screen, got {type(app.screen)}"
            )

    @pytest.mark.asyncio
    async def test_modal_shows_session_details(
        self, mock_claude_home: Path, temp_state_dir: Path
    ):
        """Modal should display full session details."""
        app = RecallMonitorApp()

        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()

            # Switch to Session tab
            await pilot.press("f4")
            await pilot.pause()

            session_table = app.query_one("#session-list", DataTable)
            session_table.focus()
            await pilot.pause()

            # Navigate to sess-recent (should be first row, most recent)
            await pilot.press("e")
            await pilot.pause()

            # Modal should be visible
            assert isinstance(app.screen, SessionDetailModal), (
                "Modal should be the active screen"
            )

            # Get modal content - check for session details
            modal = app.screen
            assert modal.session_id is not None, "Modal should have session_id set"
            assert modal.session_data is not None, "Modal should have session_data set"

    @pytest.mark.asyncio
    async def test_modal_escape_dismisses(
        self, mock_claude_home: Path, temp_state_dir: Path
    ):
        """Pressing Escape should dismiss the modal."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Session tab and open modal
            await pilot.press("f4")
            await pilot.pause()

            session_table = app.query_one("#session-list", DataTable)
            session_table.focus()
            await pilot.pause()

            await pilot.press("e")
            await pilot.pause()

            # Verify modal is open
            assert isinstance(app.screen, SessionDetailModal), "Modal should be open"

            # Press Escape to dismiss
            await pilot.press("escape")
            await pilot.pause()

            # Modal should be dismissed
            assert not isinstance(app.screen, SessionDetailModal), (
                "Modal should be dismissed after pressing Escape"
            )

    @pytest.mark.asyncio
    async def test_modal_close_button_dismisses(
        self, mock_claude_home: Path, temp_state_dir: Path
    ):
        """Close button press event should dismiss the modal."""
        from textual.widgets import Button

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Session tab and open modal
            await pilot.press("f4")
            await pilot.pause()

            session_table = app.query_one("#session-list", DataTable)
            session_table.focus()
            await pilot.pause()

            await pilot.press("e")
            await pilot.pause()

            # Verify modal is open
            assert isinstance(app.screen, SessionDetailModal), "Modal should be open"

            # Focus the Close button and press Enter to activate it
            close_button = app.screen.query_one("#close-modal", Button)
            close_button.focus()
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

            # Modal should be dismissed
            assert not isinstance(app.screen, SessionDetailModal), (
                "Modal should be dismissed after activating Close button"
            )

    @pytest.mark.asyncio
    async def test_modal_shows_full_topic(
        self, mock_claude_home: Path, temp_state_dir: Path
    ):
        """Modal should display the full topic without truncation."""
        app = RecallMonitorApp()

        # Use wider terminal to fit full topic
        async with app.run_test(size=(150, 30)) as pilot:
            await pilot.pause()

            # Switch to Session tab
            await pilot.press("f4")
            await pilot.pause()

            session_table = app.query_one("#session-list", DataTable)
            session_table.focus()
            await pilot.pause()

            # Find the row with sess-long-topic and navigate to it
            # Sessions are sorted by last_activity descending:
            # sess-recent (5s ago), sess-middle (20s ago), sess-long-topic (25s ago), sess-older (50s ago)
            # So sess-long-topic should be at index 2
            target_row_idx = None
            for idx, row_key in enumerate(session_table.rows.keys()):
                if str(row_key.value) == "sess-long-topic":
                    target_row_idx = idx
                    break

            if target_row_idx is not None:
                # Move cursor to the target row
                session_table.move_cursor(row=target_row_idx)
                await pilot.pause()

                await pilot.press("e")
                await pilot.pause()

                # Verify modal has the full topic
                if isinstance(app.screen, SessionDetailModal):
                    topic = app.screen.session_data.first_prompt
                    # The topic should contain text beyond the 100-char mark
                    assert "session management" in topic, (
                        f"Modal should show full topic including 'session management'. "
                        f"Got topic: {topic[:150]}..."
                    )
                else:
                    pytest.fail("Modal did not open")
            else:
                pytest.fail("Could not find sess-long-topic in session table")

    @pytest.mark.asyncio
    async def test_modal_shows_lesson_citations(
        self, mock_claude_home_with_citations: Path, temp_state_dir: Path
    ):
        """Modal should display lesson citations when present."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Session tab
            await pilot.press("f4")
            await pilot.pause()

            session_table = app.query_one("#session-list", DataTable)
            session_table.focus()
            await pilot.pause()

            # Open modal for first session
            await pilot.press("e")
            await pilot.pause()

            # Check that modal shows citations
            if isinstance(app.screen, SessionDetailModal):
                citations = app.screen.session_data.lesson_citations
                # One of the sessions has citations L001 and S002
                if citations:
                    assert "L001" in citations or "S002" in citations, (
                        f"Modal should show lesson citations. Got: {citations}"
                    )


# --- Tests for Handoff Correlation ---


class TestHandoffCorrelation:
    """Tests for handoff correlation display in session events panel."""

    def test_decode_project_path_simple(self):
        """_decode_project_path decodes simple project paths."""
        session_path = Path("/home/user/.claude/projects/-Users-test-code-myproject/sess.jsonl")
        result = _decode_project_path(session_path)

        assert result is not None, "Should decode valid path"
        assert result == Path("/Users/test/code/myproject"), (
            f"Expected /Users/test/code/myproject, got {result}"
        )

    def test_decode_project_path_with_dots(self):
        """_decode_project_path handles paths with dots (--  -> /.)."""
        session_path = Path("/home/user/.claude/projects/-Users-test--local-state/sess.jsonl")
        result = _decode_project_path(session_path)

        assert result is not None, "Should decode path with dots"
        assert result == Path("/Users/test/.local/state"), (
            f"Expected /Users/test/.local/state, got {result}"
        )

    def test_decode_project_path_invalid(self):
        """_decode_project_path returns None for invalid paths."""
        # Path without leading dash
        session_path = Path("/home/user/.claude/projects/invalid/sess.jsonl")
        result = _decode_project_path(session_path)

        assert result is None, "Should return None for path without leading dash"

    def test_find_matching_handoff_exact_match(self):
        """_find_matching_handoff finds handoff when session date equals created/updated."""
        from datetime import date

        handoffs = [
            HandoffSummary(
                id="hf-abc1234",
                title="Test Handoff",
                status="in_progress",
                phase="implementing",
                created="2026-01-07",
                updated="2026-01-07",
            )
        ]
        session_date = date(2026, 1, 7)

        result = _find_matching_handoff(session_date, handoffs)

        assert result is not None, "Should find handoff on exact date"
        assert result.id == "hf-abc1234", f"Expected hf-abc1234, got {result.id}"

    def test_find_matching_handoff_in_range(self):
        """_find_matching_handoff finds handoff when session date is between created and updated."""
        from datetime import date

        handoffs = [
            HandoffSummary(
                id="hf-abc1234",
                title="Multi-day Handoff",
                status="in_progress",
                phase="implementing",
                created="2026-01-05",
                updated="2026-01-10",
            )
        ]
        session_date = date(2026, 1, 7)  # Between created and updated

        result = _find_matching_handoff(session_date, handoffs)

        assert result is not None, "Should find handoff when date in range"
        assert result.id == "hf-abc1234"

    def test_find_matching_handoff_no_match(self):
        """_find_matching_handoff returns None when no handoff matches."""
        from datetime import date

        handoffs = [
            HandoffSummary(
                id="hf-abc1234",
                title="Old Handoff",
                status="completed",
                phase="review",
                created="2026-01-01",
                updated="2026-01-02",
            )
        ]
        session_date = date(2026, 1, 7)  # After handoff ended

        result = _find_matching_handoff(session_date, handoffs)

        assert result is None, "Should return None when no handoff matches date"

    def test_find_matching_handoff_prefers_most_recent(self):
        """_find_matching_handoff returns most recently updated when multiple match."""
        from datetime import date

        handoffs = [
            HandoffSummary(
                id="hf-older",
                title="Older Handoff",
                status="in_progress",
                phase="research",
                created="2026-01-01",
                updated="2026-01-08",
            ),
            HandoffSummary(
                id="hf-newer",
                title="Newer Handoff",
                status="in_progress",
                phase="implementing",
                created="2026-01-05",
                updated="2026-01-10",
            ),
        ]
        session_date = date(2026, 1, 7)  # Matches both

        result = _find_matching_handoff(session_date, handoffs)

        assert result is not None, "Should find matching handoff"
        assert result.id == "hf-newer", (
            f"Should prefer most recently updated handoff, got {result.id}"
        )

    def test_find_matching_handoff_skips_empty_dates(self):
        """_find_matching_handoff skips handoffs with empty date fields."""
        from datetime import date

        handoffs = [
            HandoffSummary(
                id="hf-no-dates",
                title="Missing Dates",
                status="in_progress",
                phase="research",
                created="",
                updated="",
            ),
            HandoffSummary(
                id="hf-valid",
                title="Valid Dates",
                status="in_progress",
                phase="implementing",
                created="2026-01-05",
                updated="2026-01-10",
            ),
        ]
        session_date = date(2026, 1, 7)

        result = _find_matching_handoff(session_date, handoffs)

        assert result is not None, "Should find valid handoff"
        assert result.id == "hf-valid", "Should skip handoff with empty dates"


@pytest.fixture
def mock_claude_home_with_handoff(tmp_path: Path, monkeypatch) -> Path:
    """Create mock ~/.claude and .claude-recall directories with handoff.

    The decoded project path from Claude's encoded directory naming
    is an absolute path. We create a project directory without dashes
    (since dashes in paths can't be reliably decoded) and use that.
    """
    claude_home = tmp_path / ".claude"
    projects_dir = claude_home / "projects"

    # Create a project directory without dashes
    # Use a simple path that we create inside tmp_path
    project_root = tmp_path / "myproject"
    project_root.mkdir(parents=True)

    # Encode the project path for Claude's directory naming
    # e.g., /tmp/.../myproject -> -tmp-...-myproject
    encoded_project = str(project_root).replace("/", "-").replace(".", "-")
    project_dir = projects_dir / encoded_project
    project_dir.mkdir(parents=True)

    # Create .claude-recall directory in the project root
    recall_dir = project_root / ".claude-recall"
    recall_dir.mkdir(parents=True)

    # Create HANDOFFS.md with a handoff that spans today
    today = datetime.now().strftime("%Y-%m-%d")
    handoffs_content = f"""# HANDOFFS.md - Active Work Tracking

## Active Handoffs

### [hf-test123] Test Handoff for TUI
- **Status**: in_progress | **Phase**: implementing | **Agent**: user
- **Created**: {today} | **Updated**: {today}
- **Refs**:
- **Description**: Testing handoff correlation

**Tried**:
1. [success] Initial setup

**Next**: Complete implementation
"""
    (recall_dir / "HANDOFFS.md").write_text(handoffs_content)

    # Create a session transcript with today's timestamp
    start_time = make_timestamp(60)  # 1 minute ago
    end_time = make_timestamp(30)  # 30 seconds ago

    create_transcript(
        project_dir / "sess-with-handoff.jsonl",
        first_prompt="Working on TUI handoff correlation",
        tools=["Read", "Edit"],
        tokens=1000,
        start_time=start_time,
        end_time=end_time,
    )

    # Monkeypatch to use our mock directories
    monkeypatch.setenv("PROJECT_DIR", str(project_root))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    return claude_home


class TestHandoffCorrelationDisplay:
    """Integration tests for handoff correlation display in TUI.

    Note: Full end-to-end testing of the handoff correlation feature requires
    a project path without dashes, which is difficult to guarantee in temp dirs.
    These tests focus on verifying the components work together.
    """

    def test_state_reader_loads_handoffs_from_project(self, tmp_path: Path):
        """StateReader.get_handoffs loads handoffs from project's .claude-recall."""
        try:
            from core.tui.state_reader import StateReader
        except ImportError:
            from .state_reader import StateReader

        # Create project with handoffs
        project_root = tmp_path / "project"
        project_root.mkdir()
        recall_dir = project_root / ".claude-recall"
        recall_dir.mkdir()

        today = datetime.now().strftime("%Y-%m-%d")
        handoffs_content = f"""# HANDOFFS.md

### [hf-abc1234] Test Handoff
- **Status**: in_progress | **Phase**: implementing | **Agent**: user
- **Created**: {today} | **Updated**: {today}
"""
        (recall_dir / "HANDOFFS.md").write_text(handoffs_content)

        reader = StateReader(project_root=project_root)
        handoffs = reader.get_handoffs(project_root)

        assert len(handoffs) == 1, f"Expected 1 handoff, got {len(handoffs)}"
        assert handoffs[0].id == "hf-abc1234"
        assert handoffs[0].phase == "implementing"
        assert handoffs[0].created == today
        assert handoffs[0].updated == today

    def test_handoff_correlation_logic_integration(self, tmp_path: Path):
        """Verify handoff matching works with StateReader data."""
        from datetime import date as dt_date

        try:
            from core.tui.state_reader import StateReader
        except ImportError:
            from .state_reader import StateReader

        # Create project with handoffs spanning multiple dates
        # Note: Handoff IDs must match pattern hf-[0-9a-f]{7} or [A-Z]\d{3}
        project_root = tmp_path / "project"
        project_root.mkdir()
        recall_dir = project_root / ".claude-recall"
        recall_dir.mkdir()

        handoffs_content = """# HANDOFFS.md

### [hf-0000001] Older Handoff
- **Status**: completed | **Phase**: review | **Agent**: user
- **Created**: 2026-01-01 | **Updated**: 2026-01-03

### [hf-0000002] Active Handoff
- **Status**: in_progress | **Phase**: implementing | **Agent**: user
- **Created**: 2026-01-05 | **Updated**: 2026-01-10
"""
        (recall_dir / "HANDOFFS.md").write_text(handoffs_content)

        reader = StateReader(project_root=project_root)
        handoffs = reader.get_handoffs(project_root)

        assert len(handoffs) == 2, f"Expected 2 handoffs, got {len(handoffs)}"

        # Session on 2026-01-07 should match hf-0000002 (Active Handoff)
        session_date = dt_date(2026, 1, 7)
        match = _find_matching_handoff(session_date, handoffs)

        assert match is not None, "Should find matching handoff"
        assert match.id == "hf-0000002", f"Expected hf-0000002, got {match.id}"

        # Session on 2026-01-02 should match hf-0000001 (Older Handoff)
        session_date = dt_date(2026, 1, 2)
        match = _find_matching_handoff(session_date, handoffs)

        assert match is not None, "Should find matching handoff"
        assert match.id == "hf-0000001", f"Expected hf-0000001, got {match.id}"

        # Session on 2026-01-04 should match nothing (between the two handoffs)
        session_date = dt_date(2026, 1, 4)
        match = _find_matching_handoff(session_date, handoffs)

        assert match is None, "Should not find matching handoff"


# ============================================================================
# Tests for Origin Column
# ============================================================================


def create_transcript_with_origin(
    path: Path,
    first_prompt: str,
    start_time: str,
    end_time: str,
) -> None:
    """Create a mock transcript JSONL file with specific first prompt for origin testing."""
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


@pytest.fixture
def mock_claude_home_with_origins(tmp_path: Path, monkeypatch) -> Path:
    """Create a mock ~/.claude directory with sessions of various origins."""
    claude_home = tmp_path / ".claude"
    projects_dir = claude_home / "projects"

    project_dir = projects_dir / "-Users-test-code-project-b"
    project_dir.mkdir(parents=True)

    # Create sessions with different origin patterns
    sessions = [
        ("sess-explore.jsonl", "Explore the codebase for authentication code"),
        ("sess-plan.jsonl", "Plan the implementation of OAuth2 support"),
        ("sess-general.jsonl", "Implement the login form validation"),
        ("sess-user.jsonl", "How do I add a new feature?"),
        ("sess-system.jsonl", "Analyze this conversation and extract key information"),
        ("sess-local-cmd.jsonl", "<local-command-caveat>User ran a command</local-command-caveat>"),
    ]

    for i, (filename, prompt) in enumerate(sessions):
        create_transcript_with_origin(
            project_dir / filename,
            first_prompt=prompt,
            start_time=make_timestamp(60 - i * 10),
            end_time=make_timestamp(55 - i * 10),
        )

    monkeypatch.setenv("PROJECT_DIR", "/Users/test/code/project-b")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    return claude_home


class TestOriginColumn:
    """Tests for the Origin column in session table."""

    @pytest.mark.asyncio
    async def test_session_table_has_origin_column(
        self, mock_claude_home_with_origins: Path, temp_state_dir: Path
    ):
        """Session table should have an Origin column."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Session tab
            await pilot.press("f4")
            await pilot.pause()

            session_table = app.query_one("#session-list", DataTable)

            # Get column labels
            column_labels = [str(col.label) for col in session_table.columns.values()]

            assert "Origin" in column_labels, (
                f"Expected 'Origin' column, but columns are: {column_labels}"
            )

    @pytest.mark.asyncio
    async def test_origin_column_shows_correct_values(
        self, mock_claude_home_with_origins: Path, temp_state_dir: Path
    ):
        """Origin column should show correct values for each session type."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Session tab
            await pilot.press("f4")
            await pilot.pause()

            # Toggle to show system sessions (they are hidden by default)
            await pilot.press("w")
            await pilot.pause()

            session_table = app.query_one("#session-list", DataTable)

            # Get the session data from the cached data
            session_data = app._session_data

            # Check each session has expected origin
            explore_session = session_data.get("sess-explore")
            assert explore_session is not None, "sess-explore should be in session data"
            assert explore_session.origin == "Explore", (
                f"Expected 'Explore' origin, got '{explore_session.origin}'"
            )

            plan_session = session_data.get("sess-plan")
            assert plan_session is not None, "sess-plan should be in session data"
            assert plan_session.origin == "Plan", (
                f"Expected 'Plan' origin, got '{plan_session.origin}'"
            )

            general_session = session_data.get("sess-general")
            assert general_session is not None, "sess-general should be in session data"
            assert general_session.origin == "General", (
                f"Expected 'General' origin, got '{general_session.origin}'"
            )

            user_session = session_data.get("sess-user")
            assert user_session is not None, "sess-user should be in session data"
            assert user_session.origin == "User", (
                f"Expected 'User' origin, got '{user_session.origin}'"
            )

            system_session = session_data.get("sess-system")
            assert system_session is not None, "sess-system should be in session data"
            assert system_session.origin == "System", (
                f"Expected 'System' origin, got '{system_session.origin}'"
            )

            local_cmd_session = session_data.get("sess-local-cmd")
            assert local_cmd_session is not None, "sess-local-cmd should be in session data"
            assert local_cmd_session.origin == "User", (
                f"Expected 'User' origin for local-command-caveat, got '{local_cmd_session.origin}'"
            )


# ============================================================================
# Tests for Project Column Visibility
# ============================================================================


@pytest.fixture
def mock_claude_home_multi_project(tmp_path: Path, monkeypatch) -> Path:
    """Create a mock ~/.claude with multiple projects."""
    claude_home = tmp_path / ".claude"
    projects_dir = claude_home / "projects"

    # Project A
    project_a_dir = projects_dir / "-Users-test-code-project-a"
    project_a_dir.mkdir(parents=True)
    create_transcript(
        project_a_dir / "sess-a1.jsonl",
        first_prompt="Task in project A",
        tools=["Read"],
        tokens=100,
        start_time=make_timestamp(60),
        end_time=make_timestamp(50),
    )

    # Project B
    project_b_dir = projects_dir / "-Users-test-code-project-b"
    project_b_dir.mkdir(parents=True)
    create_transcript(
        project_b_dir / "sess-b1.jsonl",
        first_prompt="Task in project B",
        tools=["Edit"],
        tokens=200,
        start_time=make_timestamp(40),
        end_time=make_timestamp(30),
    )

    monkeypatch.setenv("PROJECT_DIR", "/Users/test/code/project-a")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    return claude_home


class TestProjectColumnVisibility:
    """Tests for hiding/showing Project column based on view mode."""

    @pytest.mark.asyncio
    async def test_project_column_hidden_in_single_project_mode(
        self, mock_claude_home_multi_project: Path, temp_state_dir: Path
    ):
        """Project column should be hidden when viewing single project (default)."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Session tab
            await pilot.press("f4")
            await pilot.pause()

            session_table = app.query_one("#session-list", DataTable)

            # Get column labels
            column_labels = [str(col.label) for col in session_table.columns.values()]

            # In single-project mode, Project column should NOT be present
            assert "Project" not in column_labels, (
                f"Project column should be hidden in single-project mode. "
                f"Columns: {column_labels}"
            )

    @pytest.mark.asyncio
    async def test_project_column_visible_in_all_projects_mode(
        self, mock_claude_home_multi_project: Path, temp_state_dir: Path
    ):
        """Project column should be visible when viewing all projects (after 'a' toggle)."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Session tab
            await pilot.press("f4")
            await pilot.pause()

            # Toggle to all-projects mode
            await pilot.press("a")
            await pilot.pause()

            session_table = app.query_one("#session-list", DataTable)

            # Get column labels
            column_labels = [str(col.label) for col in session_table.columns.values()]

            # In all-projects mode, Project column should be present
            assert "Project" in column_labels, (
                f"Project column should be visible in all-projects mode. "
                f"Columns: {column_labels}"
            )

    @pytest.mark.asyncio
    async def test_toggle_back_hides_project_column(
        self, mock_claude_home_multi_project: Path, temp_state_dir: Path
    ):
        """Pressing 'a' again should hide Project column."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Session tab
            await pilot.press("f4")
            await pilot.pause()

            session_table = app.query_one("#session-list", DataTable)

            # Toggle to all-projects mode
            await pilot.press("a")
            await pilot.pause()

            column_labels_all = [str(col.label) for col in session_table.columns.values()]
            assert "Project" in column_labels_all, "Project should be visible after first toggle"

            # Toggle back to single-project mode
            await pilot.press("a")
            await pilot.pause()

            column_labels_single = [str(col.label) for col in session_table.columns.values()]
            assert "Project" not in column_labels_single, (
                "Project should be hidden after toggling back"
            )


# ============================================================================
# Tests for Live Refresh
# ============================================================================


class TestSessionLiveRefresh:
    """Tests for session list live refresh functionality."""

    @pytest.mark.asyncio
    async def test_refresh_key_works_in_session_tab(
        self, mock_claude_home: Path, temp_state_dir: Path
    ):
        """Pressing 'r' in session tab should trigger refresh."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Session tab
            await pilot.press("f4")
            await pilot.pause()

            session_table = app.query_one("#session-list", DataTable)
            initial_count = session_table.row_count

            # Press 'r' to refresh
            await pilot.press("r")
            await pilot.pause()

            # Table should still have the same sessions (no new ones added)
            # This just verifies 'r' doesn't crash and table is still populated
            assert session_table.row_count == initial_count, (
                f"Session count should be {initial_count} after refresh, "
                f"got {session_table.row_count}"
            )

    @pytest.mark.asyncio
    async def test_timer_callback_refreshes_session_list(
        self, mock_claude_home: Path, temp_state_dir: Path
    ):
        """_on_refresh_timer should refresh the session list."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Session tab
            await pilot.press("f4")
            await pilot.pause()

            session_table = app.query_one("#session-list", DataTable)
            initial_count = session_table.row_count

            # Manually call the timer callback (simulating auto-refresh)
            app._on_refresh_timer()
            await pilot.pause()

            # Table should still be populated
            assert session_table.row_count == initial_count, (
                f"Session count should be {initial_count} after timer refresh, "
                f"got {session_table.row_count}"
            )
