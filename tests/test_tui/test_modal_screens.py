#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Tests for Modal Screens (SessionDetailModal and LoadingScreen).

SessionDetailModal displays full session information:
- Session ID and project
- Full topic (first user prompt)
- Start and last activity times
- Token usage with breakdown
- Tool breakdown
- Lesson citations

LoadingScreen is a full-screen loading modal shown during startup.
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest

pytest.importorskip("textual")

# Configure pytest-asyncio
pytest_plugins = ("pytest_asyncio",)

from textual.app import App, ComposeResult
from textual.widgets import Button, LoadingIndicator, Static

from core.tui.app import LoadingScreen, SessionDetailModal
from core.tui.transcript_reader import TranscriptSummary


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_transcript_summary():
    """Full TranscriptSummary for modal testing."""
    return TranscriptSummary(
        session_id="abc123-def456",
        path=Path("/tmp/test.jsonl"),
        project="test-project",
        first_prompt="This is a long user prompt for testing",
        message_count=25,
        tool_breakdown={"Read": 5, "Write": 3, "Bash": 2},
        input_tokens=15000,
        output_tokens=8000,
        cache_read_tokens=5000,
        cache_creation_tokens=2000,
        start_time=datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc),
        last_activity=datetime(2026, 1, 15, 11, 30, tzinfo=timezone.utc),
        lesson_citations=["L001", "L002", "S003"],
    )


@pytest.fixture
def temp_project_for_modal(tmp_path, monkeypatch):
    """Create minimal environment for modal testing."""
    # Create state directory for logs
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "debug.log").write_text("")

    # Set environment
    monkeypatch.setenv("CLAUDE_RECALL_STATE", str(state_dir))

    return state_dir


# ============================================================================
# Test App for Hosting Modals
# ============================================================================


class ModalTestApp(App):
    """Test app for hosting modals."""

    def compose(self) -> ComposeResult:
        yield Static("Test App")


# ============================================================================
# SessionDetailModal Tests
# ============================================================================


class TestSessionDetailModalCompose:
    """Tests for SessionDetailModal widget composition."""

    @pytest.mark.asyncio
    async def test_session_detail_modal_compose(
        self, mock_transcript_summary, temp_project_for_modal
    ):
        """SessionDetailModal should create expected widgets."""
        app = ModalTestApp()

        async with app.run_test() as pilot:
            modal = SessionDetailModal("abc123-def456", mock_transcript_summary)
            app.push_screen(modal)
            await pilot.pause()

            # Modal should have main container with id="session-detail-modal"
            modal_container = app.screen.query_one("#session-detail-modal")
            assert modal_container is not None

            # Should have modal title
            title_widgets = app.screen.query(".modal-title")
            assert len(title_widgets) > 0

            # Should have session detail content scroll container
            content_scroll = app.screen.query_one("#session-detail-content")
            assert content_scroll is not None

            # Should have close button
            close_button = app.screen.query_one("#close-modal", Button)
            assert close_button is not None


class TestSessionDetailModalContent:
    """Tests for SessionDetailModal content display."""

    @pytest.mark.asyncio
    async def test_session_detail_modal_shows_session_id(
        self, mock_transcript_summary, temp_project_for_modal
    ):
        """Session ID should be displayed in the modal."""
        app = ModalTestApp()

        async with app.run_test() as pilot:
            modal = SessionDetailModal("abc123-def456", mock_transcript_summary)
            app.push_screen(modal)
            await pilot.pause()

            # Find all Static widgets and check for session ID
            content = [str(w.render()) for w in app.screen.query(Static)]
            assert any("abc123-def456" in c for c in content), (
                f"Session ID 'abc123-def456' should be displayed. Got: {content}"
            )

    @pytest.mark.asyncio
    async def test_session_detail_modal_shows_project(
        self, mock_transcript_summary, temp_project_for_modal
    ):
        """Project name should be displayed in the modal."""
        app = ModalTestApp()

        async with app.run_test() as pilot:
            modal = SessionDetailModal("abc123-def456", mock_transcript_summary)
            app.push_screen(modal)
            await pilot.pause()

            # Find all Static widgets and check for project name
            content = [str(w.render()) for w in app.screen.query(Static)]
            assert any("test-project" in c for c in content), (
                f"Project name 'test-project' should be displayed. Got: {content}"
            )

    @pytest.mark.asyncio
    async def test_session_detail_modal_shows_full_topic(
        self, mock_transcript_summary, temp_project_for_modal
    ):
        """Full topic should be displayed without truncation."""
        app = ModalTestApp()

        async with app.run_test() as pilot:
            modal = SessionDetailModal("abc123-def456", mock_transcript_summary)
            app.push_screen(modal)
            await pilot.pause()

            # Find all Static widgets and check for full topic
            content = [str(w.render()) for w in app.screen.query(Static)]
            assert any("This is a long user prompt for testing" in c for c in content), (
                f"Full topic should be displayed. Got: {content}"
            )

    @pytest.mark.asyncio
    async def test_session_detail_modal_shows_times(
        self, mock_transcript_summary, temp_project_for_modal
    ):
        """Start and last activity times should be displayed."""
        app = ModalTestApp()

        async with app.run_test() as pilot:
            modal = SessionDetailModal("abc123-def456", mock_transcript_summary)
            app.push_screen(modal)
            await pilot.pause()

            # Find all Static widgets
            content = [str(w.render()) for w in app.screen.query(Static)]
            content_str = " ".join(content)

            # Should have Started and Last Activity labels
            assert any("Started" in c for c in content), (
                f"'Started' label should be displayed. Got: {content_str}"
            )
            assert any("Last Activity" in c for c in content), (
                f"'Last Activity' label should be displayed. Got: {content_str}"
            )

    @pytest.mark.asyncio
    async def test_session_detail_modal_shows_token_breakdown(
        self, mock_transcript_summary, temp_project_for_modal
    ):
        """Input/output/cache tokens should be displayed."""
        app = ModalTestApp()

        async with app.run_test() as pilot:
            modal = SessionDetailModal("abc123-def456", mock_transcript_summary)
            app.push_screen(modal)
            await pilot.pause()

            # Find all Static widgets
            content = [str(w.render()) for w in app.screen.query(Static)]
            content_str = " ".join(content)

            # Should have token information
            assert any("Tokens" in c for c in content), (
                f"'Tokens' label should be displayed. Got: {content_str}"
            )

            # Should show Input and Output
            assert any("Input" in c for c in content), (
                f"'Input' token count should be displayed. Got: {content_str}"
            )
            assert any("Output" in c for c in content), (
                f"'Output' token count should be displayed. Got: {content_str}"
            )

            # Should show cache info (since our fixture has cache tokens > 0)
            assert any("Cache" in c for c in content), (
                f"'Cache' token info should be displayed. Got: {content_str}"
            )

    @pytest.mark.asyncio
    async def test_session_detail_modal_shows_tool_breakdown(
        self, mock_transcript_summary, temp_project_for_modal
    ):
        """Tool usage counts should be displayed."""
        app = ModalTestApp()

        async with app.run_test() as pilot:
            modal = SessionDetailModal("abc123-def456", mock_transcript_summary)
            app.push_screen(modal)
            await pilot.pause()

            # Find all Static widgets
            content = [str(w.render()) for w in app.screen.query(Static)]
            content_str = " ".join(content)

            # Should have Tools label
            assert any("Tools" in c for c in content), (
                f"'Tools' label should be displayed. Got: {content_str}"
            )

            # Should show tool names and counts (format: "Read(5)")
            assert any("Read" in c for c in content), (
                f"Tool 'Read' should be displayed. Got: {content_str}"
            )

    @pytest.mark.asyncio
    async def test_session_detail_modal_shows_lesson_citations(
        self, mock_transcript_summary, temp_project_for_modal
    ):
        """Cited lessons should be displayed."""
        app = ModalTestApp()

        async with app.run_test() as pilot:
            modal = SessionDetailModal("abc123-def456", mock_transcript_summary)
            app.push_screen(modal)
            await pilot.pause()

            # Find all Static widgets
            content = [str(w.render()) for w in app.screen.query(Static)]
            content_str = " ".join(content)

            # Should have Lessons Cited label
            assert any("Lessons Cited" in c for c in content), (
                f"'Lessons Cited' label should be displayed. Got: {content_str}"
            )

            # Should show citation IDs
            assert any("L001" in c for c in content), (
                f"Citation 'L001' should be displayed. Got: {content_str}"
            )
            assert any("L002" in c for c in content), (
                f"Citation 'L002' should be displayed. Got: {content_str}"
            )
            assert any("S003" in c for c in content), (
                f"Citation 'S003' should be displayed. Got: {content_str}"
            )


class TestSessionDetailModalDismissal:
    """Tests for SessionDetailModal dismissal behavior."""

    @pytest.mark.asyncio
    async def test_session_detail_modal_escape_dismisses(
        self, mock_transcript_summary, temp_project_for_modal
    ):
        """ESC key should close the modal."""
        app = ModalTestApp()

        async with app.run_test() as pilot:
            modal = SessionDetailModal("abc123-def456", mock_transcript_summary)
            app.push_screen(modal)
            await pilot.pause()

            # Verify modal is shown
            assert isinstance(app.screen, SessionDetailModal), "Modal should be displayed"

            # Press Escape
            await pilot.press("escape")
            await pilot.pause()

            # Modal should be dismissed
            assert not isinstance(app.screen, SessionDetailModal), (
                "Modal should be dismissed after pressing Escape"
            )

    @pytest.mark.asyncio
    async def test_session_detail_modal_close_button_dismisses(
        self, mock_transcript_summary, temp_project_for_modal
    ):
        """Close button should close the modal."""
        app = ModalTestApp()

        async with app.run_test() as pilot:
            modal = SessionDetailModal("abc123-def456", mock_transcript_summary)
            app.push_screen(modal)
            await pilot.pause()

            # Verify modal is shown
            assert isinstance(app.screen, SessionDetailModal), "Modal should be displayed"

            # Click the close button
            close_button = app.screen.query_one("#close-modal", Button)
            await pilot.click(close_button)
            await pilot.pause()

            # Modal should be dismissed
            assert not isinstance(app.screen, SessionDetailModal), (
                "Modal should be dismissed after clicking Close button"
            )


# ============================================================================
# LoadingScreen Tests
# ============================================================================


class TestLoadingScreenCompose:
    """Tests for LoadingScreen widget composition."""

    @pytest.mark.asyncio
    async def test_loading_screen_compose(self, temp_project_for_modal):
        """LoadingScreen should create LoadingIndicator and status label."""
        app = ModalTestApp()

        async with app.run_test() as pilot:
            loading_screen = LoadingScreen()
            app.push_screen(loading_screen)
            await pilot.pause()

            # Should have loading modal container
            loading_modal = app.screen.query_one("#loading-modal")
            assert loading_modal is not None

            # Should have LoadingIndicator widget
            loading_indicators = app.screen.query(LoadingIndicator)
            assert len(loading_indicators) > 0, "LoadingIndicator should be present"

            # Should have status label
            status_label = app.screen.query_one("#loading-status", Static)
            assert status_label is not None

            # Initial status should be "Initializing..."
            status_text = str(status_label.render())
            assert "Initializing" in status_text, (
                f"Initial status should be 'Initializing...', got: {status_text}"
            )


class TestLoadingScreenStatus:
    """Tests for LoadingScreen status updates."""

    @pytest.mark.asyncio
    async def test_loading_screen_update_status(self, temp_project_for_modal):
        """Dynamic status updates should change the status label."""
        app = ModalTestApp()

        async with app.run_test() as pilot:
            loading_screen = LoadingScreen()
            app.push_screen(loading_screen)
            await pilot.pause()

            # Update status
            loading_screen.update_status("Loading sessions...")
            await pilot.pause()

            # Check that status label was updated
            status_label = app.screen.query_one("#loading-status", Static)
            status_text = str(status_label.render())
            assert "Loading sessions" in status_text, (
                f"Status should be updated to 'Loading sessions...', got: {status_text}"
            )

            # Update again
            loading_screen.update_status("Almost done...")
            await pilot.pause()

            status_text = str(status_label.render())
            assert "Almost done" in status_text, (
                f"Status should be updated to 'Almost done...', got: {status_text}"
            )


class TestLoadingScreenBindings:
    """Tests for LoadingScreen key bindings."""

    def test_loading_screen_no_escape_binding(self):
        """LoadingScreen should have no escape binding (must wait for loading)."""
        loading_screen = LoadingScreen()

        # Extract key bindings
        binding_keys = [b.key for b in loading_screen.BINDINGS]

        # Should NOT have escape binding
        assert "escape" not in binding_keys, (
            "LoadingScreen should not have escape binding - users must wait for loading"
        )

        # BINDINGS list should be empty
        assert len(loading_screen.BINDINGS) == 0, (
            f"LoadingScreen BINDINGS should be empty, got: {loading_screen.BINDINGS}"
        )
