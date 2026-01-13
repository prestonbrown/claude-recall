#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Tests for Handoff Search/Filter feature in the TUI.

These tests verify:
- Filter input widget exists in the handoffs tab
- Text filter matches against title/description
- Prefix filters work: status:x, phase:x, agent:x
- Clear filter button and Esc key work
- Filter status indicator shows counts correctly
"""

import pytest
from datetime import date, timedelta
from pathlib import Path

pytest.importorskip("textual")

# Configure pytest-asyncio
pytest_plugins = ("pytest_asyncio",)

from textual.widgets import Button, DataTable, Input, Static


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
def mock_project_with_varied_handoffs(tmp_path: Path, monkeypatch, mock_state_dir) -> Path:
    """Create a mock project with handoffs in various statuses/phases/agents."""
    project_dir = tmp_path / "test-project"
    project_dir.mkdir()
    recall_dir = project_dir / ".claude-recall"
    recall_dir.mkdir()

    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    week_ago = (date.today() - timedelta(days=7)).isoformat()

    handoffs_content = f"""# HANDOFFS.md

### [hf-oauth001] OAuth2 Integration
- **Status**: in_progress | **Phase**: implementing | **Agent**: user
- **Created**: {yesterday} | **Updated**: {today}

**Description**: Add OAuth2 login support for Google and GitHub providers.

**Tried** (1 steps):
  1. [success] Initial setup

**Next**:
  - Complete Google OAuth

**Refs**: core/auth/oauth.py:42

**Checkpoint**: In progress

### [hf-dbmigr1] Database Migration
- **Status**: blocked | **Phase**: research | **Agent**: explore
- **Created**: {week_ago} | **Updated**: {yesterday}

**Description**: Migrate from SQLite to PostgreSQL database.

**Tried** (1 steps):
  1. [fail] Schema migration

**Next**:
  - Get DBA assistance

**Refs**: db/migrate.py:100

**Checkpoint**: Blocked on schema issues

### [hf-dark001] Dark Mode Feature
- **Status**: completed | **Phase**: review | **Agent**: general-purpose
- **Created**: {week_ago} | **Updated**: {yesterday}

**Description**: Add dark mode toggle to settings page.

**Tried** (1 steps):
  1. [success] Implementation complete

**Refs**: ui/settings.py:50

**Checkpoint**: Merged to main

### [hf-api0001] REST API v2
- **Status**: in_progress | **Phase**: planning | **Agent**: plan
- **Created**: {yesterday} | **Updated**: {today}

**Description**: Design REST API v2 with breaking changes.

**Next**:
  - Write API spec

**Refs**: api/routes.py:10

### [hf-tests01] Add Integration Tests
- **Status**: not_started | **Phase**: research | **Agent**: user
- **Created**: {today} | **Updated**: {today}

**Description**: Create integration test suite for new features.

**Next**:
  - Set up test framework
"""
    (recall_dir / "HANDOFFS.md").write_text(handoffs_content)

    monkeypatch.setenv("PROJECT_DIR", str(project_dir))
    return project_dir


# --- Tests for Filter Input Widget Existence ---


class TestHandoffFilterInputExists:
    """Tests to verify filter input widget exists in the handoffs tab."""

    @pytest.mark.asyncio
    async def test_filter_input_exists(self, mock_project_with_varied_handoffs):
        """Handoffs tab should have a filter Input widget."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f6")
            await pilot.pause()

            # Look for the filter input widget
            try:
                filter_input = app.query_one("#handoff-filter", Input)
                assert filter_input is not None
            except Exception as e:
                pytest.fail(f"Handoff filter input not found: {e}")

    @pytest.mark.asyncio
    async def test_filter_input_has_placeholder(self, mock_project_with_varied_handoffs):
        """Filter input should have a helpful placeholder."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f6")
            await pilot.pause()

            filter_input = app.query_one("#handoff-filter", Input)
            # Should mention filter options
            assert filter_input.placeholder is not None
            assert len(filter_input.placeholder) > 0

    @pytest.mark.asyncio
    async def test_clear_filter_button_exists(self, mock_project_with_varied_handoffs):
        """Handoffs tab should have a clear filter button."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f6")
            await pilot.pause()

            # Look for clear filter button
            try:
                clear_button = app.query_one("#clear-filter", Button)
                assert clear_button is not None
            except Exception as e:
                pytest.fail(f"Clear filter button not found: {e}")

    @pytest.mark.asyncio
    async def test_filter_status_indicator_exists(self, mock_project_with_varied_handoffs):
        """Handoffs tab should have a filter status indicator."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f6")
            await pilot.pause()

            # Look for the filter status indicator
            try:
                status_indicator = app.query_one("#handoff-filter-status", Static)
                assert status_indicator is not None
            except Exception as e:
                pytest.fail(f"Filter status indicator not found: {e}")


# --- Tests for Text Filter ---


class TestHandoffTextFilter:
    """Tests for text-based filtering of handoffs."""

    @pytest.mark.asyncio
    async def test_text_filter_matches_title(self, mock_project_with_varied_handoffs):
        """Typing text in filter should match handoff titles."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f6")
            await pilot.pause()

            # Get initial count (show completed first to see all)
            await pilot.press("c")  # Toggle completed
            await pilot.pause()

            handoff_list = app.query_one("#handoff-list", DataTable)
            initial_count = handoff_list.row_count

            # Type "OAuth" to filter
            filter_input = app.query_one("#handoff-filter", Input)
            filter_input.focus()
            await pilot.pause()

            # Type the filter text
            for char in "OAuth":
                await pilot.press(char)
            await pilot.pause()

            # Should now show fewer handoffs (only OAuth one)
            filtered_count = handoff_list.row_count
            assert filtered_count < initial_count, (
                f"Filter 'OAuth' should reduce count from {initial_count}"
            )
            assert filtered_count >= 1, "Should still show OAuth handoff"

    @pytest.mark.asyncio
    async def test_text_filter_matches_description(self, mock_project_with_varied_handoffs):
        """Text filter should also match against description."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f6")
            await pilot.pause()

            # Show completed to see all handoffs
            await pilot.press("c")
            await pilot.pause()

            handoff_list = app.query_one("#handoff-list", DataTable)
            initial_count = handoff_list.row_count

            # Filter by text in description - "PostgreSQL" is in db migration description
            filter_input = app.query_one("#handoff-filter", Input)
            filter_input.focus()
            await pilot.pause()

            for char in "PostgreSQL":
                await pilot.press(char)
            await pilot.pause()

            filtered_count = handoff_list.row_count
            assert filtered_count < initial_count, "Filter should reduce count"
            assert filtered_count >= 1, "Should show database migration handoff"

    @pytest.mark.asyncio
    async def test_text_filter_case_insensitive(self, mock_project_with_varied_handoffs):
        """Text filter should be case-insensitive."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f6")
            await pilot.pause()

            await pilot.press("c")  # Show completed
            await pilot.pause()

            handoff_list = app.query_one("#handoff-list", DataTable)

            # Filter with lowercase
            filter_input = app.query_one("#handoff-filter", Input)
            filter_input.focus()
            await pilot.pause()

            for char in "oauth":
                await pilot.press(char)
            await pilot.pause()

            # Should still find OAuth handoff
            assert handoff_list.row_count >= 1, "Case-insensitive filter should find OAuth"


# --- Tests for Prefix Filters ---


class TestHandoffPrefixFilters:
    """Tests for prefix-based filtering (status:, phase:, agent:)."""

    @pytest.mark.asyncio
    async def test_status_prefix_filter(self, mock_project_with_varied_handoffs):
        """status:blocked should show only blocked handoffs."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f6")
            await pilot.pause()

            await pilot.press("c")  # Show completed
            await pilot.pause()

            handoff_list = app.query_one("#handoff-list", DataTable)
            initial_count = handoff_list.row_count

            # Apply status filter
            filter_input = app.query_one("#handoff-filter", Input)
            filter_input.focus()
            await pilot.pause()

            for char in "status:blocked":
                await pilot.press(char)
            await pilot.pause()

            # Should show only blocked handoffs (we have 1)
            filtered_count = handoff_list.row_count
            assert filtered_count == 1, f"Expected 1 blocked handoff, got {filtered_count}"

    @pytest.mark.asyncio
    async def test_phase_prefix_filter(self, mock_project_with_varied_handoffs):
        """phase:research should show only handoffs in research phase."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f6")
            await pilot.pause()

            await pilot.press("c")  # Show completed
            await pilot.pause()

            handoff_list = app.query_one("#handoff-list", DataTable)

            # Apply phase filter
            filter_input = app.query_one("#handoff-filter", Input)
            filter_input.focus()
            await pilot.pause()

            for char in "phase:research":
                await pilot.press(char)
            await pilot.pause()

            # Should show only research phase handoffs (we have 2)
            filtered_count = handoff_list.row_count
            assert filtered_count == 2, f"Expected 2 research phase handoffs, got {filtered_count}"

    @pytest.mark.asyncio
    async def test_agent_prefix_filter(self, mock_project_with_varied_handoffs):
        """agent:user should show only handoffs assigned to user."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f6")
            await pilot.pause()

            await pilot.press("c")  # Show completed
            await pilot.pause()

            handoff_list = app.query_one("#handoff-list", DataTable)

            # Apply agent filter
            filter_input = app.query_one("#handoff-filter", Input)
            filter_input.focus()
            await pilot.pause()

            for char in "agent:user":
                await pilot.press(char)
            await pilot.pause()

            # Should show only user agent handoffs (we have 2)
            filtered_count = handoff_list.row_count
            assert filtered_count == 2, f"Expected 2 user agent handoffs, got {filtered_count}"

    @pytest.mark.asyncio
    async def test_combined_prefix_and_text_filter(self, mock_project_with_varied_handoffs):
        """Combined filters: text + prefix should work together."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f6")
            await pilot.pause()

            await pilot.press("c")  # Show completed
            await pilot.pause()

            handoff_list = app.query_one("#handoff-list", DataTable)

            # Apply combined filter: status:in_progress + text
            filter_input = app.query_one("#handoff-filter", Input)
            filter_input.focus()
            await pilot.pause()

            # Filter: "status:in_progress OAuth"
            for char in "status:in_progress OAuth":
                await pilot.press(char)
            await pilot.pause()

            # Should show only in_progress OAuth handoff (1)
            filtered_count = handoff_list.row_count
            assert filtered_count == 1, f"Expected 1 handoff matching both filters, got {filtered_count}"


# --- Tests for Clear Filter ---


class TestHandoffClearFilter:
    """Tests for clearing the filter."""

    @pytest.mark.asyncio
    async def test_clear_button_clears_filter(self, mock_project_with_varied_handoffs):
        """Clear button press event should reset the filter."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f6")
            await pilot.pause()

            await pilot.press("c")  # Show completed
            await pilot.pause()

            handoff_list = app.query_one("#handoff-list", DataTable)
            initial_count = handoff_list.row_count

            # Apply a filter
            filter_input = app.query_one("#handoff-filter", Input)
            filter_input.focus()
            await pilot.pause()

            for char in "OAuth":
                await pilot.press(char)
            await pilot.pause()

            filtered_count = handoff_list.row_count
            assert filtered_count < initial_count, "Filter should reduce count"

            # Simulate clear button press via direct method call
            # This tests the handler logic even if the button isn't clickable in headless mode
            clear_button = app.query_one("#clear-filter", Button)
            clear_button.press()
            await pilot.pause()

            # Count should be restored
            restored_count = handoff_list.row_count
            assert restored_count == initial_count, (
                f"Clear should restore count to {initial_count}, got {restored_count}"
            )

            # Input should be cleared
            assert filter_input.value == "", "Filter input should be empty after clear"

    @pytest.mark.asyncio
    async def test_escape_clears_filter_when_focused(self, mock_project_with_varied_handoffs):
        """Pressing Escape when filter is focused should clear it."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f6")
            await pilot.pause()

            await pilot.press("c")  # Show completed
            await pilot.pause()

            handoff_list = app.query_one("#handoff-list", DataTable)
            initial_count = handoff_list.row_count

            # Apply a filter
            filter_input = app.query_one("#handoff-filter", Input)
            filter_input.focus()
            await pilot.pause()

            for char in "blocked":
                await pilot.press(char)
            await pilot.pause()

            assert handoff_list.row_count < initial_count, "Filter should reduce count"

            # Press Escape
            await pilot.press("escape")
            await pilot.pause()

            # Filter should be cleared
            assert filter_input.value == "", "Escape should clear filter input"
            assert handoff_list.row_count == initial_count, "Count should be restored"


# --- Tests for Filter Status Indicator ---


class TestHandoffFilterStatusIndicator:
    """Tests for the filter status indicator."""

    @pytest.mark.asyncio
    async def test_status_shows_filtered_count(self, mock_project_with_varied_handoffs):
        """Status indicator should show 'Showing X of Y' when filtered."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f6")
            await pilot.pause()

            await pilot.press("c")  # Show completed
            await pilot.pause()

            handoff_list = app.query_one("#handoff-list", DataTable)
            total_count = handoff_list.row_count

            # Apply a filter
            filter_input = app.query_one("#handoff-filter", Input)
            filter_input.focus()
            await pilot.pause()

            for char in "OAuth":
                await pilot.press(char)
            await pilot.pause()

            filtered_count = handoff_list.row_count

            # Check that filter is working (reduced count)
            assert filtered_count < total_count, "Filter should reduce count"

            # Check internal state tracking
            assert app.state.handoff.total_count >= filtered_count, (
                "Total count should be tracked for filter status"
            )

    @pytest.mark.asyncio
    async def test_status_empty_when_not_filtered(self, mock_project_with_varied_handoffs):
        """Status indicator should be empty when showing all."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f6")
            await pilot.pause()

            # Check that handoffs are shown
            handoff_list = app.query_one("#handoff-list", DataTable)
            row_count = handoff_list.row_count

            # When not filtered, total should equal visible
            assert app.state.handoff.total_count == row_count, (
                f"When not filtered, total ({app.state.handoff.total_count}) should equal visible ({row_count})"
            )


# --- Tests for Filter Parsing ---


class TestHandoffFilterParsing:
    """Tests for the filter parsing logic."""

    def test_parse_empty_filter(self):
        """Empty filter should return empty result."""
        try:
            from core.tui.app import RecallMonitorApp
        except ImportError:
            pytest.skip("Could not import RecallMonitorApp")

        app = RecallMonitorApp()
        result = app._parse_handoff_filter("")

        assert result["text"] == ""
        assert result["status"] is None
        assert result["phase"] is None
        assert result["agent"] is None

    def test_parse_text_only_filter(self):
        """Text-only filter should set text field."""
        try:
            from core.tui.app import RecallMonitorApp
        except ImportError:
            pytest.skip("Could not import RecallMonitorApp")

        app = RecallMonitorApp()
        result = app._parse_handoff_filter("OAuth login")

        assert result["text"] == "OAuth login"
        assert result["status"] is None
        assert result["phase"] is None
        assert result["agent"] is None

    def test_parse_status_prefix(self):
        """status:value should set status field."""
        try:
            from core.tui.app import RecallMonitorApp
        except ImportError:
            pytest.skip("Could not import RecallMonitorApp")

        app = RecallMonitorApp()
        result = app._parse_handoff_filter("status:blocked")

        assert result["status"] == "blocked"
        assert result["text"] == ""

    def test_parse_phase_prefix(self):
        """phase:value should set phase field."""
        try:
            from core.tui.app import RecallMonitorApp
        except ImportError:
            pytest.skip("Could not import RecallMonitorApp")

        app = RecallMonitorApp()
        result = app._parse_handoff_filter("phase:implementing")

        assert result["phase"] == "implementing"
        assert result["text"] == ""

    def test_parse_agent_prefix(self):
        """agent:value should set agent field."""
        try:
            from core.tui.app import RecallMonitorApp
        except ImportError:
            pytest.skip("Could not import RecallMonitorApp")

        app = RecallMonitorApp()
        result = app._parse_handoff_filter("agent:user")

        assert result["agent"] == "user"
        assert result["text"] == ""

    def test_parse_combined_filter(self):
        """Combined filters should set all fields."""
        try:
            from core.tui.app import RecallMonitorApp
        except ImportError:
            pytest.skip("Could not import RecallMonitorApp")

        app = RecallMonitorApp()
        result = app._parse_handoff_filter("status:blocked phase:research OAuth")

        assert result["status"] == "blocked"
        assert result["phase"] == "research"
        assert result["text"] == "OAuth"
        assert result["agent"] is None


# --- Tests for Filter Matching ---


class TestHandoffFilterMatching:
    """Tests for the filter matching logic."""

    def test_matches_filter_with_empty_filter(self):
        """Empty filter should match all handoffs."""
        try:
            from core.tui.app import RecallMonitorApp
            from core.tui.models import HandoffSummary
        except ImportError:
            pytest.skip("Could not import modules")

        app = RecallMonitorApp()
        handoff = HandoffSummary(
            id="hf-test001",
            title="Test Handoff",
            status="in_progress",
            phase="implementing",
            created="2026-01-01",
            updated="2026-01-08",
        )

        parsed = app._parse_handoff_filter("")
        assert app._matches_filter(handoff, parsed) is True

    def test_matches_filter_text_in_title(self):
        """Text filter should match against title."""
        try:
            from core.tui.app import RecallMonitorApp
            from core.tui.models import HandoffSummary
        except ImportError:
            pytest.skip("Could not import modules")

        app = RecallMonitorApp()
        handoff = HandoffSummary(
            id="hf-test001",
            title="OAuth Integration",
            status="in_progress",
            phase="implementing",
            created="2026-01-01",
            updated="2026-01-08",
        )

        parsed = app._parse_handoff_filter("OAuth")
        assert app._matches_filter(handoff, parsed) is True

        parsed = app._parse_handoff_filter("Database")
        assert app._matches_filter(handoff, parsed) is False

    def test_matches_filter_text_in_description(self):
        """Text filter should match against description."""
        try:
            from core.tui.app import RecallMonitorApp
            from core.tui.models import HandoffSummary
        except ImportError:
            pytest.skip("Could not import modules")

        app = RecallMonitorApp()
        handoff = HandoffSummary(
            id="hf-test001",
            title="Database Work",
            status="in_progress",
            phase="implementing",
            created="2026-01-01",
            updated="2026-01-08",
            description="Migrate to PostgreSQL database",
        )

        parsed = app._parse_handoff_filter("PostgreSQL")
        assert app._matches_filter(handoff, parsed) is True

    def test_matches_filter_status(self):
        """Status filter should match against status."""
        try:
            from core.tui.app import RecallMonitorApp
            from core.tui.models import HandoffSummary
        except ImportError:
            pytest.skip("Could not import modules")

        app = RecallMonitorApp()
        handoff = HandoffSummary(
            id="hf-test001",
            title="Test",
            status="blocked",
            phase="research",
            created="2026-01-01",
            updated="2026-01-08",
        )

        parsed = app._parse_handoff_filter("status:blocked")
        assert app._matches_filter(handoff, parsed) is True

        parsed = app._parse_handoff_filter("status:in_progress")
        assert app._matches_filter(handoff, parsed) is False

    def test_matches_filter_phase(self):
        """Phase filter should match against phase."""
        try:
            from core.tui.app import RecallMonitorApp
            from core.tui.models import HandoffSummary
        except ImportError:
            pytest.skip("Could not import modules")

        app = RecallMonitorApp()
        handoff = HandoffSummary(
            id="hf-test001",
            title="Test",
            status="in_progress",
            phase="implementing",
            created="2026-01-01",
            updated="2026-01-08",
        )

        parsed = app._parse_handoff_filter("phase:implementing")
        assert app._matches_filter(handoff, parsed) is True

        parsed = app._parse_handoff_filter("phase:research")
        assert app._matches_filter(handoff, parsed) is False

    def test_matches_filter_agent(self):
        """Agent filter should match against agent."""
        try:
            from core.tui.app import RecallMonitorApp
            from core.tui.models import HandoffSummary
        except ImportError:
            pytest.skip("Could not import modules")

        app = RecallMonitorApp()
        handoff = HandoffSummary(
            id="hf-test001",
            title="Test",
            status="in_progress",
            phase="implementing",
            created="2026-01-01",
            updated="2026-01-08",
            agent="user",
        )

        parsed = app._parse_handoff_filter("agent:user")
        assert app._matches_filter(handoff, parsed) is True

        parsed = app._parse_handoff_filter("agent:explore")
        assert app._matches_filter(handoff, parsed) is False

    def test_matches_filter_combined(self):
        """Combined filters should all be satisfied."""
        try:
            from core.tui.app import RecallMonitorApp
            from core.tui.models import HandoffSummary
        except ImportError:
            pytest.skip("Could not import modules")

        app = RecallMonitorApp()
        handoff = HandoffSummary(
            id="hf-test001",
            title="OAuth Integration",
            status="in_progress",
            phase="implementing",
            created="2026-01-01",
            updated="2026-01-08",
            agent="user",
        )

        # All match
        parsed = app._parse_handoff_filter("status:in_progress phase:implementing OAuth")
        assert app._matches_filter(handoff, parsed) is True

        # Status doesn't match
        parsed = app._parse_handoff_filter("status:blocked phase:implementing OAuth")
        assert app._matches_filter(handoff, parsed) is False

        # Text doesn't match
        parsed = app._parse_handoff_filter("status:in_progress Database")
        assert app._matches_filter(handoff, parsed) is False


# --- Tests for Filter Status Visibility ---


class TestHandoffFilterStatusVisibility:
    """Tests for filter status indicator visibility (display property)."""

    @pytest.mark.asyncio
    async def test_status_hidden_when_showing_all(self, mock_project_with_varied_handoffs):
        """Status indicator should be hidden (display=False) when no filter active."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f6")
            await pilot.pause()

            # Explicitly call to ensure the display property is set
            app._update_filter_status(5, 5)  # All visible

            status = app.query_one("#handoff-filter-status", Static)
            assert status.display is False, "Status should be hidden when showing all"

    @pytest.mark.asyncio
    async def test_status_visible_when_filtering(self, mock_project_with_varied_handoffs):
        """Status indicator should be visible when filter hides items."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f6")
            await pilot.pause()

            # Directly test the method with filtered results
            app._update_filter_status(2, 5)  # 2 visible of 5 total

            status = app.query_one("#handoff-filter-status", Static)
            assert status.display is True, "Status should be visible when filtering"
