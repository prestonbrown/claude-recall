#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Tests for completed handoffs visibility in the TUI.

These tests verify:
- Recently completed handoffs (within 48 hours) visible by default
- Old completed handoffs hidden by default
- Toggle shows/hides all completed
- Count indicator shows correct numbers
"""

import pytest
from datetime import date, timedelta
from pathlib import Path

pytest.importorskip("textual")

# Configure pytest-asyncio
pytest_plugins = ("pytest_asyncio",)

from textual.widgets import DataTable, RichLog, Static, Tab

# Import app with fallback for installed vs dev paths
try:
    from core.tui.app import RecallMonitorApp
    from core.tui.models import HandoffSummary, TriedStep
    from core.tui.state_reader import StateReader
except ImportError:
    from .app import RecallMonitorApp
    from .models import HandoffSummary, TriedStep
    from .state_reader import StateReader


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
def mock_project_with_mixed_handoffs(tmp_path: Path, monkeypatch, mock_state_dir) -> Path:
    """Create a mock project with completed handoffs of various ages."""
    project_dir = tmp_path / "test-project"
    project_dir.mkdir()
    recall_dir = project_dir / ".claude-recall"
    recall_dir.mkdir()

    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    two_days_ago = (date.today() - timedelta(days=2)).isoformat()
    week_ago = (date.today() - timedelta(days=7)).isoformat()
    month_ago = (date.today() - timedelta(days=30)).isoformat()

    handoffs_content = f"""# HANDOFFS.md

### [hf-active01] Active Work Item
- **Status**: in_progress | **Phase**: implementing | **Agent**: user
- **Created**: {yesterday} | **Updated**: {today}

**Description**: An active handoff.

**Next**:
  - Continue work

### [hf-active02] Another Active Work Item
- **Status**: blocked | **Phase**: research | **Agent**: explore
- **Created**: {week_ago} | **Updated**: {yesterday}

**Description**: A blocked handoff.

**Next**:
  - Resolve blocker

### [hf-recent01] Recently Completed Feature
- **Status**: completed | **Phase**: review | **Agent**: general-purpose
- **Created**: {two_days_ago} | **Updated**: {today}

**Description**: Completed today - should be visible by default.

**Tried** (1 steps):
  1. [success] Implementation complete

### [hf-recent02] Just Finished Yesterday
- **Status**: completed | **Phase**: review | **Agent**: user
- **Created**: {week_ago} | **Updated**: {yesterday}

**Description**: Completed yesterday - should be visible by default.

**Tried** (1 steps):
  1. [success] All done

### [hf-old0001] Old Completed Feature
- **Status**: completed | **Phase**: review | **Agent**: general-purpose
- **Created**: {month_ago} | **Updated**: {week_ago}

**Description**: Completed a week ago - should be hidden by default.

**Tried** (1 steps):
  1. [success] Completed long ago

### [hf-old0002] Another Old Completed
- **Status**: completed | **Phase**: review | **Agent**: user
- **Created**: {month_ago} | **Updated**: {week_ago}

**Description**: Also completed long ago - should be hidden by default.

**Tried** (1 steps):
  1. [success] Finished
"""
    (recall_dir / "HANDOFFS.md").write_text(handoffs_content)

    monkeypatch.setenv("PROJECT_DIR", str(project_dir))
    return project_dir


# --- Tests for Recently Completed Visibility ---


class TestRecentlyCompletedVisible:
    """Tests that recently completed handoffs are visible by default."""

    @pytest.mark.asyncio
    async def test_recently_completed_visible_by_default(self, mock_project_with_mixed_handoffs):
        """Handoffs completed within 48 hours should be visible by default."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f6")
            await pilot.pause()

            handoff_list = app.query_one("#handoff-list", DataTable)

            # Should show: 2 active + 2 recently completed = 4
            # Should NOT show: 2 old completed
            row_count = handoff_list.row_count
            assert row_count == 4, (
                f"Expected 4 handoffs (2 active + 2 recent), got {row_count}. "
                "Recently completed (within 48h) should be visible by default."
            )

    @pytest.mark.asyncio
    async def test_old_completed_hidden_by_default(self, mock_project_with_mixed_handoffs):
        """Handoffs completed more than 48 hours ago should be hidden by default."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f6")
            await pilot.pause()

            handoff_list = app.query_one("#handoff-list", DataTable)

            # Verify the old completed handoffs are NOT in the table
            # We check the row count - old completed should be hidden
            row_count = handoff_list.row_count

            # 2 active + 2 recently completed = 4 (not 6)
            assert row_count < 6, (
                f"Expected fewer than 6 handoffs (old completed should be hidden), "
                f"got {row_count}"
            )


class TestToggleCompleted:
    """Tests for the completed handoffs toggle."""

    @pytest.mark.asyncio
    async def test_toggle_shows_all_completed(self, mock_project_with_mixed_handoffs):
        """Pressing 'c' should show all completed handoffs including old ones."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f6")
            await pilot.pause()

            handoff_list = app.query_one("#handoff-list", DataTable)
            initial_count = handoff_list.row_count

            # Press 'c' to toggle completed - should show ALL completed
            await pilot.press("c")
            await pilot.pause()

            after_toggle = handoff_list.row_count

            # After toggle, should show all 6 handoffs
            assert after_toggle == 6, (
                f"Expected 6 handoffs after toggle (all visible), got {after_toggle}"
            )

    @pytest.mark.asyncio
    async def test_toggle_twice_returns_to_default(self, mock_project_with_mixed_handoffs):
        """Pressing 'c' twice should return to showing only recent completed."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f6")
            await pilot.pause()

            handoff_list = app.query_one("#handoff-list", DataTable)
            initial_count = handoff_list.row_count

            # Toggle on
            await pilot.press("c")
            await pilot.pause()

            # Toggle off
            await pilot.press("c")
            await pilot.pause()

            after_double_toggle = handoff_list.row_count

            # Should be back to initial count (4: 2 active + 2 recent)
            assert after_double_toggle == initial_count, (
                f"Expected {initial_count} handoffs after double toggle, "
                f"got {after_double_toggle}"
            )


def _get_handoffs_title_content(app) -> str:
    """Helper to get the handoffs section title content."""
    try:
        handoffs_pane = app.query_one("#handoffs")
        title_widgets = handoffs_pane.query("Static.section-title")
        for widget in title_widgets:
            content = str(widget.render())
            if "handoff" in content.lower():
                return content.lower()
        return ""
    except Exception:
        return ""


class TestCountIndicator:
    """Tests for the handoff count indicator."""

    @pytest.mark.asyncio
    async def test_count_indicator_shows_active_count(self, mock_project_with_mixed_handoffs):
        """Count indicator should show number of active handoffs."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f6")
            await pilot.pause()

            # Get the title content from the Static widget
            title_content = _get_handoffs_title_content(app)

            # Should indicate 2 active handoffs
            has_active_count = "2 active" in title_content

            assert has_active_count, (
                f"Count indicator should show '2 active'. Got title: '{title_content}'"
            )

    @pytest.mark.asyncio
    async def test_count_indicator_shows_completed_count(self, mock_project_with_mixed_handoffs):
        """Count indicator should show number of completed handoffs."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f6")
            await pilot.pause()

            # Get the title content from the Static widget
            title_content = _get_handoffs_title_content(app)

            # Should indicate completed handoffs (total is 4)
            has_completed_count = "4 completed" in title_content

            assert has_completed_count, (
                f"Count indicator should show '4 completed'. Got title: '{title_content}'"
            )

    @pytest.mark.asyncio
    async def test_count_indicator_shows_hidden_count(self, mock_project_with_mixed_handoffs):
        """Count indicator should show how many completed are hidden."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f6")
            await pilot.pause()

            # Get the title content from the Static widget
            title_content = _get_handoffs_title_content(app)

            # Should indicate 2 hidden (old completed not shown)
            has_hidden_info = "+2 hidden" in title_content or "2 hidden" in title_content

            assert has_hidden_info, (
                f"Count indicator should show '+2 hidden'. Got title: '{title_content}'"
            )


class TestFooterHint:
    """Tests for the footer hint about toggle."""

    @pytest.mark.asyncio
    async def test_footer_shows_toggle_hint_on_handoffs_tab(self, mock_project_with_mixed_handoffs):
        """Footer should show '[c] Toggle completed' hint on handoffs tab."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f6")
            await pilot.pause()

            # Get footer content - the Binding with key 'c' should have description
            # visible in footer when on handoffs tab
            bindings = app.active_bindings

            # Check that 'c' binding has appropriate description
            c_binding = None
            for binding_info in bindings.values():
                if binding_info.binding.key == "c":
                    c_binding = binding_info.binding
                    break

            assert c_binding is not None, "Should have 'c' key binding"

            # The binding description should indicate it's for completed toggle
            desc = c_binding.description.lower()
            assert "completed" in desc or "toggle" in desc, (
                f"'c' binding should mention 'completed' or 'toggle', "
                f"got description: '{c_binding.description}'"
            )
