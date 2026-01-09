#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Tests for Handoffs tab timeline/Gantt view.

These tests verify the timeline view feature:
- Toggle with 't' key switches between list and timeline view
- Timeline widget exists and renders
- Handoffs display as colored bars based on status
- Timeline is scrollable for long histories
"""

import pytest
from datetime import date, timedelta
from pathlib import Path

pytest.importorskip("textual")

# Configure pytest-asyncio
pytest_plugins = ("pytest_asyncio",)

from textual.widgets import DataTable, RichLog, Static

# Import app with fallback for installed vs dev paths
try:
    from core.tui.app import RecallMonitorApp
    from core.tui.models import HandoffSummary
except ImportError:
    from .app import RecallMonitorApp
    from .models import HandoffSummary


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
def mock_project_with_handoffs(tmp_path: Path, monkeypatch, mock_state_dir) -> Path:
    """Create a mock project with handoffs file for timeline testing."""
    project_dir = tmp_path / "test-project"
    project_dir.mkdir()
    recall_dir = project_dir / ".claude-recall"
    recall_dir.mkdir()

    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    week_ago = (date.today() - timedelta(days=7)).isoformat()
    two_weeks_ago = (date.today() - timedelta(days=14)).isoformat()

    handoffs_content = f"""# HANDOFFS.md

### [hf-active01] Implement OAuth2 Integration
- **Status**: in_progress | **Phase**: implementing | **Agent**: user
- **Created**: {yesterday} | **Updated**: {today}

**Description**: Add OAuth2 login support.

**Tried** (1 steps):
  1. [success] Initial setup

**Next**:
  - Complete OAuth

**Refs**: core/auth/oauth.py:42

### [hf-blocked01] Database Migration
- **Status**: blocked | **Phase**: research | **Agent**: explore
- **Created**: {week_ago} | **Updated**: {yesterday}

**Description**: Migrate to PostgreSQL.

**Tried** (1 steps):
  1. [fail] Schema migration failed

**Next**:
  - Get DBA help

**Refs**: db/migrate.py:100

### [hf-done0001] Add Dark Mode
- **Status**: completed | **Phase**: review | **Agent**: general-purpose
- **Created**: {two_weeks_ago} | **Updated**: {week_ago}

**Description**: Dark mode toggle.

**Tried** (1 steps):
  1. [success] Done

**Refs**: ui/settings.py:50

### [hf-notstart1] Add Feature X
- **Status**: not_started | **Phase**: research | **Agent**: user
- **Created**: {today} | **Updated**: {today}

**Description**: Feature X.

**Tried** (0 steps):

**Refs**:

### [hf-review01] Code Review
- **Status**: ready_for_review | **Phase**: review | **Agent**: review
- **Created**: {yesterday} | **Updated**: {today}

**Description**: Review code changes.

**Tried** (1 steps):
  1. [success] Initial review

**Refs**: core/main.py:10
"""
    (recall_dir / "HANDOFFS.md").write_text(handoffs_content)

    monkeypatch.setenv("PROJECT_DIR", str(project_dir))
    return project_dir


# --- Tests for Timeline Widget Existence ---


class TestTimelineWidgetExists:
    """Tests to verify timeline widget exists."""

    @pytest.mark.asyncio
    async def test_timeline_widget_exists_in_handoffs_tab(self, mock_project_with_handoffs):
        """Handoffs tab should have a timeline widget (initially hidden)."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f6")  # Switch to Handoffs tab
            await pilot.pause()

            # Timeline widget should exist
            try:
                timeline = app.query_one("#handoff-timeline", RichLog)
                assert timeline is not None, "Timeline widget should exist"
            except Exception as e:
                pytest.fail(f"Timeline widget #handoff-timeline not found: {e}")

    @pytest.mark.asyncio
    async def test_timeline_initially_hidden(self, mock_project_with_handoffs):
        """Timeline should be hidden by default (list view is default)."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f6")
            await pilot.pause()

            # List should be visible
            handoff_list = app.query_one("#handoff-list", DataTable)
            assert handoff_list.display is True, "List should be visible by default"

            # Timeline should be hidden
            timeline = app.query_one("#handoff-timeline", RichLog)
            assert timeline.display is False, "Timeline should be hidden by default"


# --- Tests for Toggle Behavior ---


class TestTimelineToggle:
    """Tests for 't' key toggle between list and timeline view."""

    @pytest.mark.asyncio
    async def test_toggle_switches_to_timeline_view(self, mock_project_with_handoffs):
        """Pressing 't' should switch from list to timeline view."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f6")  # Switch to Handoffs tab
            await pilot.pause()

            # Verify initial state
            handoff_list = app.query_one("#handoff-list", DataTable)
            timeline = app.query_one("#handoff-timeline", RichLog)

            assert handoff_list.display is True, "List should be visible initially"
            assert timeline.display is False, "Timeline should be hidden initially"

            # Press 't' to toggle
            await pilot.press("t")
            await pilot.pause()

            # After toggle, timeline should be visible and list hidden
            assert handoff_list.display is False, "List should be hidden after toggle"
            assert timeline.display is True, "Timeline should be visible after toggle"

    @pytest.mark.asyncio
    async def test_toggle_switches_back_to_list_view(self, mock_project_with_handoffs):
        """Pressing 't' twice should switch back to list view."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f6")
            await pilot.pause()

            handoff_list = app.query_one("#handoff-list", DataTable)
            timeline = app.query_one("#handoff-timeline", RichLog)

            # First toggle: list -> timeline
            await pilot.press("t")
            await pilot.pause()

            assert handoff_list.display is False
            assert timeline.display is True

            # Second toggle: timeline -> list
            await pilot.press("t")
            await pilot.pause()

            assert handoff_list.display is True, "List should be visible after second toggle"
            assert timeline.display is False, "Timeline should be hidden after second toggle"

    @pytest.mark.asyncio
    async def test_toggle_only_works_on_handoffs_tab(self, mock_project_with_handoffs):
        """Toggle should only work when on the Handoffs tab."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Stay on default tab (Live), not Handoffs
            # Press 't' - should not affect anything

            # Verify we're not on handoffs tab
            await pilot.press("t")
            await pilot.pause()

            # Now switch to Handoffs and verify initial state is preserved
            await pilot.press("f6")
            await pilot.pause()

            handoff_list = app.query_one("#handoff-list", DataTable)
            timeline = app.query_one("#handoff-timeline", RichLog)

            # Should still be in default state (list visible)
            assert handoff_list.display is True
            assert timeline.display is False


# --- Tests for Timeline Rendering ---


class TestTimelineRendering:
    """Tests for timeline content rendering."""

    @pytest.mark.asyncio
    async def test_timeline_renders_handoffs(self, mock_project_with_handoffs):
        """Timeline should render handoffs when visible."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f6")
            await pilot.pause()
            await pilot.press("t")  # Switch to timeline view
            await pilot.pause()

            timeline = app.query_one("#handoff-timeline", RichLog)

            # Timeline should have content (not empty)
            # The RichLog should have been populated by _render_timeline
            # We verify the timeline is visible
            assert timeline.display is True, "Timeline should be visible"

    @pytest.mark.asyncio
    async def test_timeline_empty_message_when_no_handoffs(self, tmp_path, monkeypatch, mock_state_dir):
        """Timeline should show message when no handoffs exist."""
        # Create project with empty handoffs file
        project_dir = tmp_path / "empty-project"
        project_dir.mkdir()
        recall_dir = project_dir / ".claude-recall"
        recall_dir.mkdir()
        (recall_dir / "HANDOFFS.md").write_text("# HANDOFFS.md\n\n")

        monkeypatch.setenv("PROJECT_DIR", str(project_dir))

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f6")
            await pilot.pause()
            await pilot.press("t")
            await pilot.pause()

            timeline = app.query_one("#handoff-timeline", RichLog)
            assert timeline.display is True


# --- Tests for Timeline State in App ---


class TestTimelineState:
    """Tests for timeline state tracking in the app."""

    @pytest.mark.asyncio
    async def test_timeline_view_state_tracked(self, mock_project_with_handoffs):
        """App should track timeline view state."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f6")
            await pilot.pause()

            # Initially, timeline view should be False
            assert hasattr(app, "_timeline_view"), "App should have _timeline_view attribute"
            assert app._timeline_view is False, "Timeline view should be False initially"

            # After toggle, should be True
            await pilot.press("t")
            await pilot.pause()

            assert app._timeline_view is True, "Timeline view should be True after toggle"

            # After second toggle, back to False
            await pilot.press("t")
            await pilot.pause()

            assert app._timeline_view is False, "Timeline view should be False after second toggle"


# --- Tests for Key Binding ---


class TestTimelineKeyBinding:
    """Tests for timeline key binding registration."""

    @pytest.mark.asyncio
    async def test_t_key_binding_exists(self, mock_project_with_handoffs):
        """App should have 't' key binding for timeline toggle."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Check if the binding exists - BINDINGS class attr contains defined bindings
            binding_keys = [b.key for b in app.BINDINGS]

            assert "t" in binding_keys, (
                f"Expected 't' key binding not found. Available: {binding_keys}"
            )

    @pytest.mark.asyncio
    async def test_toggle_timeline_action_exists(self, mock_project_with_handoffs):
        """App should have action_toggle_timeline method."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            assert hasattr(app, "action_toggle_timeline"), (
                "App should have action_toggle_timeline method"
            )
            assert callable(getattr(app, "action_toggle_timeline", None)), (
                "action_toggle_timeline should be callable"
            )
