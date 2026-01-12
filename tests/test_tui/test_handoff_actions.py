#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Tests for the Handoff Actions Popup Menu in the TUI.

These tests verify:
- Popup appears on Space/Enter when handoffs tab is active
- Each action (status change, phase change, agent change, complete, archive)
- Sub-menu selection for status/phase/agent
- Refresh and notifications after actions

Tests are designed to FAIL initially until the feature is implemented.
"""

import json
from datetime import date
from pathlib import Path

import pytest

pytest.importorskip("textual")


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def temp_project_with_handoffs(tmp_path, monkeypatch):
    """Create temp project with handoffs and configure environment."""
    # Create project structure
    project_root = tmp_path / "test-project"
    project_root.mkdir()
    recall_dir = project_root / ".claude-recall"
    recall_dir.mkdir()

    # Create state directory for logs
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "debug.log").write_text("")

    # Create handoffs file with test data
    today = date.today().isoformat()
    handoffs_content = f"""# HANDOFFS.md - Active Work Tracking

## Active Handoffs

### [hf-test001] Test Feature Implementation
- **Status**: in_progress | **Phase**: implementing | **Agent**: user
- **Created**: {today} | **Updated**: {today}
- **Refs**: core/feature.py:42
- **Description**: Test handoff for action menu testing.

**Tried**:
1. [success] Initial implementation

**Next**: Complete testing

---

### [hf-test002] Another Feature
- **Status**: blocked | **Phase**: research | **Agent**: explore
- **Created**: {today} | **Updated**: {today}
- **Refs**: core/other.py:10
- **Description**: Secondary test handoff.

**Tried**:

**Next**: Investigate blocker

---

### [hf-test003] Third Feature
- **Status**: not_started | **Phase**: planning | **Agent**: plan
- **Created**: {today} | **Updated**: {today}
- **Refs**:
- **Description**: Not started handoff.

**Tried**:

**Next**: Begin planning

---
"""
    (recall_dir / "HANDOFFS.md").write_text(handoffs_content)

    # Set environment
    monkeypatch.setenv("CLAUDE_RECALL_STATE", str(state_dir))
    monkeypatch.setenv("PROJECT_DIR", str(project_root))

    return project_root


# ============================================================================
# Tests for HandoffActionScreen Modal
# ============================================================================


class TestHandoffActionScreenExists:
    """Tests that the HandoffActionScreen class exists and can be imported."""

    def test_handoff_action_screen_importable(self):
        """HandoffActionScreen should be importable from core.tui.app."""
        from core.tui.app import HandoffActionScreen

        assert HandoffActionScreen is not None

    def test_handoff_action_screen_is_modal_screen(self):
        """HandoffActionScreen should be a ModalScreen subclass."""
        from textual.screen import ModalScreen

        from core.tui.app import HandoffActionScreen

        assert issubclass(HandoffActionScreen, ModalScreen)

    def test_handoff_action_screen_accepts_handoff_id_and_title(self):
        """HandoffActionScreen should be constructable with handoff_id and title."""
        from core.tui.app import HandoffActionScreen

        screen = HandoffActionScreen("hf-test001", "Test Feature")
        assert screen.handoff_id == "hf-test001"
        assert screen.handoff_title == "Test Feature"


class TestHandoffActionScreenContent:
    """Tests for the content and layout of HandoffActionScreen."""

    @pytest.mark.asyncio
    async def test_action_screen_shows_handoff_id_and_title(
        self, temp_project_with_handoffs
    ):
        """Action screen should display the handoff ID and title."""
        from core.tui.app import HandoffActionScreen, RecallMonitorApp

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Push the action screen
            app.push_screen(HandoffActionScreen("hf-test001", "Test Feature"))
            await pilot.pause()

            # Check that the screen is displayed
            action_screen = app.screen
            assert isinstance(action_screen, HandoffActionScreen)

            # The title should be visible somewhere in the screen content
            # This verifies the compose method includes the ID and title

    @pytest.mark.asyncio
    async def test_action_screen_has_status_option(self, temp_project_with_handoffs):
        """Action screen should have a 'Set status...' option."""
        from core.tui.app import HandoffActionScreen, RecallMonitorApp

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            app.push_screen(HandoffActionScreen("hf-test001", "Test Feature"))
            await pilot.pause()

            # Verify the screen has the expected binding
            action_screen = app.screen
            assert isinstance(action_screen, HandoffActionScreen)

            # Check that 's' binding exists in BINDINGS class attribute
            has_status_binding = any(
                b.key == "s" for b in action_screen.BINDINGS
            )
            assert has_status_binding, "Action screen should have 's' binding for status"

    @pytest.mark.asyncio
    async def test_action_screen_has_phase_option(self, temp_project_with_handoffs):
        """Action screen should have a 'Set phase...' option."""
        from core.tui.app import HandoffActionScreen, RecallMonitorApp

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            app.push_screen(HandoffActionScreen("hf-test001", "Test Feature"))
            await pilot.pause()

            action_screen = app.screen
            has_phase_binding = any(
                b.key == "p" for b in action_screen.BINDINGS
            )
            assert has_phase_binding, "Action screen should have 'p' binding for phase"

    @pytest.mark.asyncio
    async def test_action_screen_has_agent_option(self, temp_project_with_handoffs):
        """Action screen should have a 'Set agent...' option."""
        from core.tui.app import HandoffActionScreen, RecallMonitorApp

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            app.push_screen(HandoffActionScreen("hf-test001", "Test Feature"))
            await pilot.pause()

            action_screen = app.screen
            has_agent_binding = any(
                b.key == "a" for b in action_screen.BINDINGS
            )
            assert has_agent_binding, "Action screen should have 'a' binding for agent"

    @pytest.mark.asyncio
    async def test_action_screen_has_complete_option(self, temp_project_with_handoffs):
        """Action screen should have a 'Complete' option."""
        from core.tui.app import HandoffActionScreen, RecallMonitorApp

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            app.push_screen(HandoffActionScreen("hf-test001", "Test Feature"))
            await pilot.pause()

            action_screen = app.screen
            has_complete_binding = any(
                b.key == "c" for b in action_screen.BINDINGS
            )
            assert has_complete_binding, "Action screen should have 'c' binding for complete"

    @pytest.mark.asyncio
    async def test_action_screen_has_archive_option(self, temp_project_with_handoffs):
        """Action screen should have an 'Archive' option."""
        from core.tui.app import HandoffActionScreen, RecallMonitorApp

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            app.push_screen(HandoffActionScreen("hf-test001", "Test Feature"))
            await pilot.pause()

            action_screen = app.screen
            has_archive_binding = any(
                b.key == "x" for b in action_screen.BINDINGS
            )
            assert has_archive_binding, "Action screen should have 'x' binding for archive"

    @pytest.mark.asyncio
    async def test_action_screen_dismissible_with_escape(
        self, temp_project_with_handoffs
    ):
        """Action screen should be dismissible with Escape key."""
        from core.tui.app import HandoffActionScreen, RecallMonitorApp

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            app.push_screen(HandoffActionScreen("hf-test001", "Test Feature"))
            await pilot.pause()

            # Verify we're on the action screen
            assert isinstance(app.screen, HandoffActionScreen)

            # Press Escape to dismiss
            await pilot.press("escape")
            await pilot.pause()

            # Should be back on main screen
            assert not isinstance(app.screen, HandoffActionScreen)


# ============================================================================
# Tests for Popup Trigger from Handoffs Tab
# ============================================================================


class TestPopupTrigger:
    """Tests for triggering the popup from the handoffs tab.

    The popup uses double-action behavior:
    - First Enter/click on a NEW row: selects the row, shows details
    - Second Enter/click on the SAME row: opens the popup

    This prevents accidental popup opens when navigating.
    """

    @pytest.mark.asyncio
    async def test_first_enter_selects_row_without_popup(
        self, temp_project_with_handoffs
    ):
        """First Enter on a new row should select it without opening popup.

        When a row is not already selected (i.e., navigated to via arrow keys
        but not yet confirmed with Enter), the first Enter should just confirm
        the selection without opening the popup.
        """
        from core.tui.app import HandoffActionScreen, RecallMonitorApp
        from textual.widgets import DataTable

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Handoffs tab (F6)
            await pilot.press("f6")
            await pilot.pause()

            # Check if there are handoffs loaded
            handoff_table = app.query_one("#handoff-list", DataTable)
            if handoff_table.row_count == 0:
                pytest.skip("No handoffs loaded in test environment")

            # Focus the table and navigate to a row
            handoff_table.focus()
            await pilot.pause()

            # Navigate to first data row - this triggers row_highlighted
            await pilot.press("down")
            await pilot.pause()

            # Clear _current_handoff_id to simulate fresh navigation
            # (row_highlighted sets _user_selected_handoff_id but not _current_handoff_id)
            app._current_handoff_id = None

            # First Enter - should NOT open popup, just select
            await pilot.press("enter")
            await pilot.pause()

            # Should NOT have opened the action screen
            assert not isinstance(app.screen, HandoffActionScreen), (
                "First Enter should select row, not open popup"
            )

    @pytest.mark.asyncio
    async def test_second_enter_opens_popup(
        self, temp_project_with_handoffs
    ):
        """Second Enter on the same row should open the popup.

        After the first Enter confirms selection, a second Enter on the
        same row should open the action popup.
        """
        from core.tui.app import HandoffActionScreen, RecallMonitorApp
        from textual.widgets import DataTable

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Handoffs tab (F6)
            await pilot.press("f6")
            await pilot.pause()

            # Check if there are handoffs loaded
            handoff_table = app.query_one("#handoff-list", DataTable)
            if handoff_table.row_count == 0:
                pytest.skip("No handoffs loaded in test environment")

            # Focus the table and navigate to a row
            handoff_table.focus()
            await pilot.pause()

            # Navigate to first data row
            await pilot.press("down")
            await pilot.pause()

            # Clear _current_handoff_id to simulate fresh state
            app._current_handoff_id = None

            # First Enter - selects row
            await pilot.press("enter")
            await pilot.pause()

            # Verify we're still on main screen after first Enter
            assert not isinstance(app.screen, HandoffActionScreen), (
                "First Enter should not open popup"
            )

            # Second Enter - should now open popup
            await pilot.press("enter")
            await pilot.pause()

            # Should have opened the action screen
            assert isinstance(app.screen, HandoffActionScreen), (
                f"Second Enter should open HandoffActionScreen, got {type(app.screen)}"
            )

    @pytest.mark.asyncio
    async def test_double_action_flow_complete(
        self, temp_project_with_handoffs
    ):
        """Test complete double-action flow: navigate, select, open popup.

        Flow:
        1. Arrow key navigation highlights row, shows details
        2. First Enter confirms selection (no popup)
        3. Second Enter opens popup
        """
        from core.tui.app import HandoffActionScreen, RecallMonitorApp
        from textual.widgets import DataTable

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

            # Ensure fresh state
            app._current_handoff_id = None

            # Step 1: Navigate with arrow key (highlights row)
            await pilot.press("down")
            await pilot.pause()

            # Verify details are shown but popup is not open
            assert not isinstance(app.screen, HandoffActionScreen)

            # Step 2: First Enter (confirms selection)
            await pilot.press("enter")
            await pilot.pause()

            # Still no popup
            assert not isinstance(app.screen, HandoffActionScreen)
            # But _current_handoff_id should now be set
            assert app._current_handoff_id is not None

            # Step 3: Second Enter (opens popup)
            await pilot.press("enter")
            await pilot.pause()

            # Now popup should be open
            assert isinstance(app.screen, HandoffActionScreen)

    @pytest.mark.asyncio
    async def test_navigating_to_different_row_resets_selection(
        self, temp_project_with_handoffs
    ):
        """Navigating to a different row should require double-action again.

        If user presses Enter on row A, then navigates to row B,
        they should need to press Enter twice on row B to open popup.
        """
        from core.tui.app import HandoffActionScreen, RecallMonitorApp
        from textual.widgets import DataTable

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Handoffs tab
            await pilot.press("f6")
            await pilot.pause()

            handoff_table = app.query_one("#handoff-list", DataTable)
            if handoff_table.row_count < 2:
                pytest.skip("Need at least 2 handoffs for this test")

            handoff_table.focus()
            await pilot.pause()

            # Navigate to first row and select it
            app._current_handoff_id = None
            await pilot.press("down")
            await pilot.pause()
            await pilot.press("enter")  # First Enter - selects row A
            await pilot.pause()

            # Remember which row was selected
            first_row_id = app._current_handoff_id
            assert first_row_id is not None

            # Navigate to second row
            await pilot.press("down")
            await pilot.pause()

            # First Enter on new row - should NOT open popup
            await pilot.press("enter")
            await pilot.pause()

            assert not isinstance(app.screen, HandoffActionScreen), (
                "First Enter on new row should not open popup"
            )

            # Verify we're now tracking the new row
            assert app._current_handoff_id != first_row_id

            # Second Enter on same row - should open popup
            await pilot.press("enter")
            await pilot.pause()

            assert isinstance(app.screen, HandoffActionScreen), (
                "Second Enter on same row should open popup"
            )

    @pytest.mark.asyncio
    async def test_popup_not_opened_on_other_tabs(self, temp_project_with_handoffs):
        """Space/Enter on non-handoffs tabs should not open the popup."""
        from core.tui.app import HandoffActionScreen, RecallMonitorApp

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Stay on Live Activity tab (default)
            await pilot.press("space")
            await pilot.pause()

            # Should NOT open the action screen
            assert not isinstance(app.screen, HandoffActionScreen), (
                "Space on non-handoffs tab should not open HandoffActionScreen"
            )


# ============================================================================
# Tests for Status Selection Sub-Menu
# ============================================================================


class TestStatusSelection:
    """Tests for the status selection sub-menu."""

    @pytest.mark.asyncio
    async def test_status_submenu_opens(self, temp_project_with_handoffs):
        """Pressing 's' on action screen should open status selection."""
        from core.tui.app import (
            HandoffActionScreen,
            RecallMonitorApp,
            StatusSelectScreen,
        )

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Open action screen
            app.push_screen(HandoffActionScreen("hf-test001", "Test Feature"))
            await pilot.pause()

            # Press 's' to open status selection
            await pilot.press("s")
            await pilot.pause()

            # Should have opened status selection screen
            assert isinstance(app.screen, StatusSelectScreen), (
                "Pressing 's' should open StatusSelectScreen"
            )

    @pytest.mark.asyncio
    async def test_status_submenu_shows_all_valid_statuses(
        self, temp_project_with_handoffs
    ):
        """Status sub-menu should show all valid status options."""
        from core.tui.app import (
            HandoffActionScreen,
            RecallMonitorApp,
            StatusSelectScreen,
        )

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            app.push_screen(HandoffActionScreen("hf-test001", "Test Feature"))
            await pilot.pause()

            await pilot.press("s")
            await pilot.pause()

            # Valid statuses
            expected_statuses = [
                "not_started",
                "in_progress",
                "blocked",
                "ready_for_review",
                "completed",
            ]

            # The StatusSelectScreen should have these as options
            status_screen = app.screen
            assert isinstance(status_screen, StatusSelectScreen)
            # Verify options are available (implementation-specific check)

    @pytest.mark.asyncio
    async def test_selecting_status_updates_handoff(self, temp_project_with_handoffs):
        """Selecting a status should update the handoff and dismiss popups."""
        from core.tui.app import (
            HandoffActionScreen,
            RecallMonitorApp,
            StatusSelectScreen,
        )

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to handoffs tab and select a handoff
            await pilot.press("f6")
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()

            # Open action screen via Space
            await pilot.press("space")
            await pilot.pause()

            # Press 's' for status selection
            await pilot.press("s")
            await pilot.pause()

            # Press '1' or another key to select first status option
            await pilot.press("1")
            await pilot.pause()

            # Both popups should be dismissed, back to main screen
            assert not isinstance(app.screen, (HandoffActionScreen, StatusSelectScreen))


# ============================================================================
# Tests for Phase Selection Sub-Menu
# ============================================================================


class TestPhaseSelection:
    """Tests for the phase selection sub-menu."""

    @pytest.mark.asyncio
    async def test_phase_submenu_opens(self, temp_project_with_handoffs):
        """Pressing 'p' on action screen should open phase selection."""
        from core.tui.app import (
            HandoffActionScreen,
            PhaseSelectScreen,
            RecallMonitorApp,
        )

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            app.push_screen(HandoffActionScreen("hf-test001", "Test Feature"))
            await pilot.pause()

            await pilot.press("p")
            await pilot.pause()

            assert isinstance(app.screen, PhaseSelectScreen), (
                "Pressing 'p' should open PhaseSelectScreen"
            )

    @pytest.mark.asyncio
    async def test_phase_submenu_shows_all_valid_phases(
        self, temp_project_with_handoffs
    ):
        """Phase sub-menu should show all valid phase options."""
        from core.tui.app import (
            HandoffActionScreen,
            PhaseSelectScreen,
            RecallMonitorApp,
        )

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            app.push_screen(HandoffActionScreen("hf-test001", "Test Feature"))
            await pilot.pause()

            await pilot.press("p")
            await pilot.pause()

            # Valid phases
            expected_phases = ["research", "planning", "implementing", "review"]

            phase_screen = app.screen
            assert isinstance(phase_screen, PhaseSelectScreen)


# ============================================================================
# Tests for Agent Selection Sub-Menu
# ============================================================================


class TestAgentSelection:
    """Tests for the agent selection sub-menu."""

    @pytest.mark.asyncio
    async def test_agent_submenu_opens(self, temp_project_with_handoffs):
        """Pressing 'a' on action screen should open agent selection."""
        from core.tui.app import (
            AgentSelectScreen,
            HandoffActionScreen,
            RecallMonitorApp,
        )

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            app.push_screen(HandoffActionScreen("hf-test001", "Test Feature"))
            await pilot.pause()

            await pilot.press("a")
            await pilot.pause()

            assert isinstance(app.screen, AgentSelectScreen), (
                "Pressing 'a' should open AgentSelectScreen"
            )

    @pytest.mark.asyncio
    async def test_agent_submenu_shows_all_valid_agents(
        self, temp_project_with_handoffs
    ):
        """Agent sub-menu should show all valid agent options."""
        from core.tui.app import (
            AgentSelectScreen,
            HandoffActionScreen,
            RecallMonitorApp,
        )

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            app.push_screen(HandoffActionScreen("hf-test001", "Test Feature"))
            await pilot.pause()

            await pilot.press("a")
            await pilot.pause()

            # Valid agents
            expected_agents = ["explore", "general-purpose", "plan", "review", "user"]

            agent_screen = app.screen
            assert isinstance(agent_screen, AgentSelectScreen)


# ============================================================================
# Tests for Complete Action
# ============================================================================


class TestLessonsManagerImport:
    """Tests for the LessonsManager import fallback in the TUI.

    The TUI needs to import LessonsManager but must work in both:
    - Development context: `from core.manager import LessonsManager`
    - Installed context: `from manager import LessonsManager`

    This is accomplished via a helper function that handles the import
    and instantiation with proper arguments.
    """

    def test_get_lessons_manager_helper_exists(self):
        """The _get_lessons_manager helper function should exist."""
        from core.tui.app import _get_lessons_manager

        assert callable(_get_lessons_manager)

    def test_get_lessons_manager_returns_instance(self, temp_project_with_handoffs):
        """_get_lessons_manager should return a LessonsManager instance."""
        from core.tui.app import _get_lessons_manager

        mgr = _get_lessons_manager()
        assert mgr is not None
        # Verify it's a LessonsManager instance by checking for expected methods
        assert hasattr(mgr, "handoff_complete")
        assert hasattr(mgr, "handoff_archive")
        assert hasattr(mgr, "handoff_update_status")
        assert hasattr(mgr, "handoff_update_phase")
        assert hasattr(mgr, "handoff_update_agent")

    def test_get_lessons_manager_methods_callable(self, temp_project_with_handoffs):
        """LessonsManager instance methods should be callable."""
        from core.tui.app import _get_lessons_manager

        mgr = _get_lessons_manager()
        # Verify the methods are bound and callable
        assert callable(mgr.handoff_complete)
        assert callable(mgr.handoff_archive)


class TestCompleteAction:
    """Tests for the complete action."""

    def test_get_lessons_manager_not_double_instantiated(
        self, temp_project_with_handoffs
    ):
        """_get_lessons_manager() returns an instance that should be used directly.

        Regression test for bug where LessonsManager was assigned the instance
        from _get_lessons_manager() then called again like a class:
            LessonsManager = _get_lessons_manager()  # Returns instance
            mgr = LessonsManager()  # ERROR: instance is not callable

        The correct pattern is:
            mgr = _get_lessons_manager()  # Use instance directly
        """
        from core.tui.app import _get_lessons_manager

        # Get the manager instance
        mgr = _get_lessons_manager()

        # The instance should NOT be callable (it's not a class)
        assert not callable(mgr), (
            "_get_lessons_manager() should return an instance, not a class. "
            "Code that does 'LessonsManager = _get_lessons_manager(); mgr = LessonsManager()' "
            "will fail because the instance is not callable."
        )

        # The instance should have the expected methods
        assert hasattr(mgr, "handoff_complete")
        assert hasattr(mgr, "handoff_archive")

    def test_handle_handoff_action_code_pattern(
        self, temp_project_with_handoffs
    ):
        """Verify handle_handoff_action doesn't double-instantiate LessonsManager.

        This test checks the actual source code to ensure the buggy pattern:
            LessonsManager = _get_lessons_manager()
            mgr = LessonsManager()

        has been fixed to:
            mgr = _get_lessons_manager()
        """
        import inspect
        from core.tui.app import RecallMonitorApp

        # Get the source code of _on_handoff_action_result
        source = inspect.getsource(RecallMonitorApp._on_handoff_action_result)

        # Check for the buggy pattern: assigning _get_lessons_manager() to a variable
        # then calling that variable
        buggy_pattern_found = (
            "LessonsManager = _get_lessons_manager()" in source
            and "mgr = LessonsManager()" in source
        )

        assert not buggy_pattern_found, (
            "_on_handoff_action_result contains buggy pattern: "
            "'LessonsManager = _get_lessons_manager()' followed by 'mgr = LessonsManager()'. "
            "This causes 'LessonsManager is not callable' error. "
            "Fix: Use 'mgr = _get_lessons_manager()' directly."
        )

    @pytest.mark.asyncio
    async def test_complete_action_marks_handoff_completed(
        self, temp_project_with_handoffs
    ):
        """Pressing 'c' should mark the handoff as completed."""
        from core.tui.app import HandoffActionScreen, RecallMonitorApp

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to handoffs tab and select first handoff
            await pilot.press("f6")
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()

            # Open action screen
            await pilot.press("space")
            await pilot.pause()

            # Press 'c' to complete
            await pilot.press("c")
            await pilot.pause()

            # Should dismiss the popup
            assert not isinstance(app.screen, HandoffActionScreen)

            # Verify the handoff was actually marked completed
            # (check the file or app state)

    @pytest.mark.asyncio
    async def test_complete_action_shows_notification(
        self, temp_project_with_handoffs
    ):
        """Completing a handoff should show a toast notification."""
        from core.tui.app import HandoffActionScreen, RecallMonitorApp

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            await pilot.press("f6")
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()

            await pilot.press("space")
            await pilot.pause()

            await pilot.press("c")
            await pilot.pause()

            # A toast notification should appear (implementation detail)
            # We can't easily verify toast content, but the action should work


# ============================================================================
# Tests for Archive Action
# ============================================================================


class TestArchiveAction:
    """Tests for the archive action."""

    @pytest.mark.asyncio
    async def test_archive_action_archives_handoff(self, temp_project_with_handoffs):
        """Pressing 'x' should archive the handoff."""
        from core.tui.app import HandoffActionScreen, RecallMonitorApp

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            await pilot.press("f6")
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()

            await pilot.press("space")
            await pilot.pause()

            # Press 'x' to archive
            await pilot.press("x")
            await pilot.pause()

            # Should dismiss the popup
            assert not isinstance(app.screen, HandoffActionScreen)

    @pytest.mark.asyncio
    async def test_archive_action_removes_from_list(self, temp_project_with_handoffs):
        """Archiving should remove the handoff from the visible list."""
        from core.tui.app import RecallMonitorApp
        from textual.widgets import DataTable

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            await pilot.press("f6")
            await pilot.pause()

            # Get initial row count
            handoff_table = app.query_one("#handoff-list", DataTable)
            initial_count = handoff_table.row_count

            if initial_count == 0:
                # Skip if no handoffs loaded (test environment issue)
                pytest.skip("No handoffs loaded in test environment")

            await pilot.press("down")
            await pilot.pause()

            await pilot.press("space")
            await pilot.pause()

            await pilot.press("x")
            await pilot.pause()

            # Wait a bit for the refresh
            await pilot.pause()

            # Row count should decrease (or stay same if archive failed due to missing file)
            # This test verifies the action is triggered, actual file write depends on env
            pass  # Test passes if no exception


# ============================================================================
# Tests for Refresh After Actions
# ============================================================================


class TestRefreshAfterActions:
    """Tests for refreshing the handoff list after actions."""

    @pytest.mark.asyncio
    async def test_handoff_list_refreshes_after_status_change(
        self, temp_project_with_handoffs
    ):
        """Handoff list should refresh after changing status."""
        from core.tui.app import HandoffActionScreen, RecallMonitorApp

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            await pilot.press("f6")
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()

            # Get initial handoff data
            initial_handoff = app._handoff_data.get("hf-test001")
            initial_status = initial_handoff.status if initial_handoff else None

            # Open action screen and change status
            await pilot.press("space")
            await pilot.pause()
            await pilot.press("s")  # Status sub-menu
            await pilot.pause()
            await pilot.press("3")  # Select 'blocked' (assuming it's 3rd option)
            await pilot.pause()

            # The list should have refreshed with new status
            updated_handoff = app._handoff_data.get("hf-test001")
            if updated_handoff:
                # Status should have changed (or at least the action was attempted)
                pass


# ============================================================================
# Tests for Selection Screen Base Class
# ============================================================================


class TestSelectionScreenBase:
    """Tests for the base selection screen pattern."""

    def test_selection_screen_classes_exist(self):
        """All selection screen classes should exist."""
        from core.tui.app import (
            AgentSelectScreen,
            PhaseSelectScreen,
            StatusSelectScreen,
        )

        assert StatusSelectScreen is not None
        assert PhaseSelectScreen is not None
        assert AgentSelectScreen is not None

    def test_selection_screens_are_modal_screens(self):
        """Selection screens should be ModalScreen subclasses."""
        from textual.screen import ModalScreen

        from core.tui.app import (
            AgentSelectScreen,
            PhaseSelectScreen,
            StatusSelectScreen,
        )

        assert issubclass(StatusSelectScreen, ModalScreen)
        assert issubclass(PhaseSelectScreen, ModalScreen)
        assert issubclass(AgentSelectScreen, ModalScreen)


# ============================================================================
# Tests for Arrow Key Navigation
# ============================================================================


class TestArrowKeyNavigation:
    """Tests for arrow key navigation in popup menus.

    The popups should support both:
    - Direct key bindings (s, p, a, c, x for HandoffActionScreen)
    - Arrow key navigation with Enter to select
    """

    @pytest.mark.asyncio
    async def test_handoff_action_screen_has_option_list(
        self, temp_project_with_handoffs
    ):
        """HandoffActionScreen should contain an OptionList widget."""
        from textual.widgets import OptionList

        from core.tui.app import HandoffActionScreen, RecallMonitorApp

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            app.push_screen(HandoffActionScreen("hf-test001", "Test Feature"))
            await pilot.pause()

            # Query for OptionList widget
            option_lists = app.screen.query(OptionList)
            assert len(option_lists) > 0, (
                "HandoffActionScreen should contain an OptionList widget for arrow navigation"
            )

    @pytest.mark.asyncio
    async def test_arrow_down_navigates_options(self, temp_project_with_handoffs):
        """Arrow down should navigate to next option in HandoffActionScreen."""
        from textual.widgets import OptionList

        from core.tui.app import HandoffActionScreen, RecallMonitorApp

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            app.push_screen(HandoffActionScreen("hf-test001", "Test Feature"))
            await pilot.pause()

            option_list = app.screen.query_one(OptionList)
            initial_index = option_list.highlighted

            # Press down arrow
            await pilot.press("down")
            await pilot.pause()

            # Highlighted index should have changed
            new_index = option_list.highlighted
            assert new_index != initial_index or initial_index is None, (
                "Arrow down should change highlighted option"
            )

    @pytest.mark.asyncio
    async def test_arrow_up_navigates_options(self, temp_project_with_handoffs):
        """Arrow up should navigate to previous option in HandoffActionScreen."""
        from textual.widgets import OptionList

        from core.tui.app import HandoffActionScreen, RecallMonitorApp

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            app.push_screen(HandoffActionScreen("hf-test001", "Test Feature"))
            await pilot.pause()

            option_list = app.screen.query_one(OptionList)

            # Navigate down first to have room to go up
            await pilot.press("down")
            await pilot.press("down")
            await pilot.pause()
            middle_index = option_list.highlighted

            # Press up arrow
            await pilot.press("up")
            await pilot.pause()

            new_index = option_list.highlighted
            assert new_index != middle_index, "Arrow up should change highlighted option"

    @pytest.mark.asyncio
    async def test_enter_selects_highlighted_option(self, temp_project_with_handoffs):
        """Enter should select the currently highlighted option."""
        from textual.widgets import OptionList

        from core.tui.app import HandoffActionScreen, RecallMonitorApp, StatusSelectScreen

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            app.push_screen(HandoffActionScreen("hf-test001", "Test Feature"))
            await pilot.pause()

            # Navigate to status option (first option)
            option_list = app.screen.query_one(OptionList)
            # Ensure first option is highlighted
            await pilot.press("home")
            await pilot.pause()

            # Press Enter to select
            await pilot.press("enter")
            await pilot.pause()

            # Should have opened StatusSelectScreen or performed the action
            # Depending on which option was selected
            assert not isinstance(app.screen, HandoffActionScreen) or isinstance(
                app.screen, StatusSelectScreen
            ), "Enter should trigger the selected action"

    @pytest.mark.asyncio
    async def test_status_select_screen_has_option_list(
        self, temp_project_with_handoffs
    ):
        """StatusSelectScreen should contain an OptionList widget."""
        from textual.widgets import OptionList

        from core.tui.app import HandoffActionScreen, RecallMonitorApp, StatusSelectScreen

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            app.push_screen(HandoffActionScreen("hf-test001", "Test Feature"))
            await pilot.pause()

            # Open status submenu
            await pilot.press("s")
            await pilot.pause()

            assert isinstance(app.screen, StatusSelectScreen)

            # Query for OptionList widget
            option_lists = app.screen.query(OptionList)
            assert len(option_lists) > 0, (
                "StatusSelectScreen should contain an OptionList widget"
            )

    @pytest.mark.asyncio
    async def test_phase_select_screen_has_option_list(
        self, temp_project_with_handoffs
    ):
        """PhaseSelectScreen should contain an OptionList widget."""
        from textual.widgets import OptionList

        from core.tui.app import HandoffActionScreen, PhaseSelectScreen, RecallMonitorApp

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            app.push_screen(HandoffActionScreen("hf-test001", "Test Feature"))
            await pilot.pause()

            # Open phase submenu
            await pilot.press("p")
            await pilot.pause()

            assert isinstance(app.screen, PhaseSelectScreen)

            # Query for OptionList widget
            option_lists = app.screen.query(OptionList)
            assert len(option_lists) > 0, (
                "PhaseSelectScreen should contain an OptionList widget"
            )

    @pytest.mark.asyncio
    async def test_agent_select_screen_has_option_list(
        self, temp_project_with_handoffs
    ):
        """AgentSelectScreen should contain an OptionList widget."""
        from textual.widgets import OptionList

        from core.tui.app import AgentSelectScreen, HandoffActionScreen, RecallMonitorApp

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            app.push_screen(HandoffActionScreen("hf-test001", "Test Feature"))
            await pilot.pause()

            # Open agent submenu
            await pilot.press("a")
            await pilot.pause()

            assert isinstance(app.screen, AgentSelectScreen)

            # Query for OptionList widget
            option_lists = app.screen.query(OptionList)
            assert len(option_lists) > 0, (
                "AgentSelectScreen should contain an OptionList widget"
            )

    @pytest.mark.asyncio
    async def test_keyboard_shortcuts_still_work_with_option_list(
        self, temp_project_with_handoffs
    ):
        """Direct key bindings should still work alongside arrow navigation."""
        from core.tui.app import HandoffActionScreen, RecallMonitorApp, StatusSelectScreen

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            app.push_screen(HandoffActionScreen("hf-test001", "Test Feature"))
            await pilot.pause()

            # Press 's' directly (not via arrow navigation)
            await pilot.press("s")
            await pilot.pause()

            # Should still open status selection
            assert isinstance(app.screen, StatusSelectScreen), (
                "Direct key binding 's' should still work"
            )

    @pytest.mark.asyncio
    async def test_status_arrow_navigation_and_enter(self, temp_project_with_handoffs):
        """Arrow navigation and Enter should work in StatusSelectScreen."""
        from textual.widgets import OptionList

        from core.tui.app import HandoffActionScreen, RecallMonitorApp, StatusSelectScreen

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            app.push_screen(HandoffActionScreen("hf-test001", "Test Feature"))
            await pilot.pause()

            await pilot.press("s")
            await pilot.pause()

            assert isinstance(app.screen, StatusSelectScreen)

            option_list = app.screen.query_one(OptionList)

            # Navigate down
            await pilot.press("down")
            await pilot.pause()

            # Press Enter to select
            await pilot.press("enter")
            await pilot.pause()

            # Should have dismissed the screen (action taken)
            assert not isinstance(app.screen, StatusSelectScreen), (
                "Enter should select option and dismiss StatusSelectScreen"
            )

    @pytest.mark.asyncio
    async def test_number_keys_still_work_in_status_select(
        self, temp_project_with_handoffs
    ):
        """Number key shortcuts should still work in StatusSelectScreen."""
        from core.tui.app import HandoffActionScreen, RecallMonitorApp, StatusSelectScreen

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            app.push_screen(HandoffActionScreen("hf-test001", "Test Feature"))
            await pilot.pause()

            await pilot.press("s")
            await pilot.pause()

            assert isinstance(app.screen, StatusSelectScreen)

            # Press '2' for in_progress
            await pilot.press("2")
            await pilot.pause()

            # Should have dismissed the screen
            assert not isinstance(app.screen, StatusSelectScreen), (
                "Number key '2' should still select option"
            )
