#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Tests for the GenericSelectModal class.

GenericSelectModal is a unified modal for selecting from a list of options,
replacing the three nearly identical classes:
- StatusSelectScreen
- PhaseSelectScreen
- AgentSelectScreen

Tests verify:
- Modal displays correct title and options
- Number key bindings (1-5) work
- Arrow key navigation with Enter works
- Escape dismisses the modal
- Selection returns correct value format
"""

from datetime import date

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
- **Description**: Test handoff for modal testing.

**Tried**:
1. [success] Initial implementation

**Next**: Complete testing

---
"""
    (recall_dir / "HANDOFFS.md").write_text(handoffs_content)

    # Set environment
    monkeypatch.setenv("CLAUDE_RECALL_STATE", str(state_dir))
    monkeypatch.setenv("PROJECT_DIR", str(project_root))

    return project_root


# ============================================================================
# Tests for GenericSelectModal Class Existence
# ============================================================================


class TestGenericSelectModalExists:
    """Tests that the GenericSelectModal class exists and can be imported."""

    def test_generic_select_modal_importable(self):
        """GenericSelectModal should be importable from core.tui.app."""
        from core.tui.app import GenericSelectModal

        assert GenericSelectModal is not None

    def test_generic_select_modal_is_modal_screen(self):
        """GenericSelectModal should be a ModalScreen subclass."""
        from textual.screen import ModalScreen

        from core.tui.app import GenericSelectModal

        assert issubclass(GenericSelectModal, ModalScreen)

    def test_generic_select_modal_accepts_required_params(self):
        """GenericSelectModal should accept handoff_id, handoff_title, options, field_name, update_method."""
        from core.tui.app import GenericSelectModal

        screen = GenericSelectModal(
            handoff_id="hf-test001",
            handoff_title="Test Feature",
            options=["option1", "option2"],
            field_name="status",
            update_method="handoff_update_status",
        )
        assert screen.handoff_id == "hf-test001"
        assert screen.handoff_title == "Test Feature"
        assert screen.options == ["option1", "option2"]
        assert screen.field_name == "status"
        assert screen.update_method == "handoff_update_status"


# ============================================================================
# Tests for Modal Title and Content
# ============================================================================


class TestGenericSelectModalContent:
    """Tests for the content and layout of GenericSelectModal."""

    @pytest.mark.asyncio
    async def test_modal_has_correct_title(self, temp_project_with_handoffs):
        """Modal title should include the field name capitalized."""
        from textual.widgets import Static

        from core.tui.app import GenericSelectModal, RecallMonitorApp

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            app.push_screen(
                GenericSelectModal(
                    handoff_id="hf-test001",
                    handoff_title="Test Feature",
                    options=["not_started", "in_progress", "blocked"],
                    field_name="status",
                    update_method="handoff_update_status",
                )
            )
            await pilot.pause()

            # Find the modal title static widget
            title_widget = app.screen.query_one(".modal-title", Static)
            title_text = str(title_widget.render())

            # Title should contain "Status" (capitalized field_name)
            assert "Status" in title_text, f"Title should contain 'Status', got: {title_text}"

    @pytest.mark.asyncio
    async def test_modal_shows_handoff_title(self, temp_project_with_handoffs):
        """Modal should display the handoff title."""
        from textual.widgets import Static

        from core.tui.app import GenericSelectModal, RecallMonitorApp

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            app.push_screen(
                GenericSelectModal(
                    handoff_id="hf-test001",
                    handoff_title="Test Feature",
                    options=["option1"],
                    field_name="phase",
                    update_method="handoff_update_phase",
                )
            )
            await pilot.pause()

            # Find the subtitle static widget
            subtitle_widget = app.screen.query_one(".modal-subtitle", Static)
            subtitle_text = str(subtitle_widget.render())

            assert "Test Feature" in subtitle_text, (
                f"Subtitle should contain handoff title, got: {subtitle_text}"
            )

    @pytest.mark.asyncio
    async def test_modal_renders_all_options(self, temp_project_with_handoffs):
        """OptionList should have all provided options."""
        from textual.widgets import OptionList

        from core.tui.app import GenericSelectModal, RecallMonitorApp

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            options = ["not_started", "in_progress", "blocked", "ready_for_review", "completed"]
            app.push_screen(
                GenericSelectModal(
                    handoff_id="hf-test001",
                    handoff_title="Test Feature",
                    options=options,
                    field_name="status",
                    update_method="handoff_update_status",
                )
            )
            await pilot.pause()

            # Get the OptionList
            option_list = app.screen.query_one(OptionList)

            # Should have the correct number of options
            assert option_list.option_count == len(options), (
                f"Expected {len(options)} options, got {option_list.option_count}"
            )


# ============================================================================
# Tests for Number Key Bindings
# ============================================================================


class TestGenericSelectModalKeyBindings:
    """Tests for number key bindings in GenericSelectModal."""

    def test_modal_has_number_key_bindings(self):
        """GenericSelectModal should have bindings for keys 1-5."""
        from core.tui.app import GenericSelectModal

        screen = GenericSelectModal(
            handoff_id="hf-test001",
            handoff_title="Test Feature",
            options=["a", "b", "c"],
            field_name="status",
            update_method="handoff_update_status",
        )

        # Extract key bindings
        binding_keys = [b.key for b in screen.BINDINGS]

        # Should have 1-5 for selecting options
        for num in ["1", "2", "3", "4", "5"]:
            assert num in binding_keys, f"Key '{num}' should be bound"

        # Should have escape for cancel
        assert "escape" in binding_keys, "Escape key should be bound for cancel"

    @pytest.mark.asyncio
    async def test_number_key_1_selects_first_option(self, temp_project_with_handoffs):
        """Pressing '1' should select the first option."""
        from core.tui.app import GenericSelectModal, RecallMonitorApp

        app = RecallMonitorApp()
        result_holder = {"result": None}

        async with app.run_test() as pilot:
            await pilot.pause()

            def capture_result(result):
                result_holder["result"] = result

            app.push_screen(
                GenericSelectModal(
                    handoff_id="hf-test001",
                    handoff_title="Test Feature",
                    options=["first_option", "second_option"],
                    field_name="test_field",
                    update_method="handoff_update_status",
                ),
                callback=capture_result,
            )
            await pilot.pause()

            # Press '1' to select first option
            await pilot.press("1")
            await pilot.pause()

            # Modal should be dismissed and result captured
            assert result_holder["result"] is not None, "Callback should have been called"
            assert "test_field:first_option" in result_holder["result"], (
                f"Expected 'test_field:first_option', got: {result_holder['result']}"
            )

    @pytest.mark.asyncio
    async def test_number_key_2_selects_second_option(self, temp_project_with_handoffs):
        """Pressing '2' should select the second option."""
        from core.tui.app import GenericSelectModal, RecallMonitorApp

        app = RecallMonitorApp()
        result_holder = {"result": None}

        async with app.run_test() as pilot:
            await pilot.pause()

            def capture_result(result):
                result_holder["result"] = result

            app.push_screen(
                GenericSelectModal(
                    handoff_id="hf-test001",
                    handoff_title="Test Feature",
                    options=["first", "second", "third"],
                    field_name="phase",
                    update_method="handoff_update_phase",
                ),
                callback=capture_result,
            )
            await pilot.pause()

            await pilot.press("2")
            await pilot.pause()

            assert "phase:second" in result_holder["result"], (
                f"Expected 'phase:second', got: {result_holder['result']}"
            )

    @pytest.mark.asyncio
    async def test_number_key_beyond_options_does_nothing(self, temp_project_with_handoffs):
        """Pressing a number key beyond available options should do nothing."""
        from core.tui.app import GenericSelectModal, RecallMonitorApp

        app = RecallMonitorApp()
        result_holder = {"result": None}

        async with app.run_test() as pilot:
            await pilot.pause()

            def capture_result(result):
                result_holder["result"] = result

            # Only 2 options
            app.push_screen(
                GenericSelectModal(
                    handoff_id="hf-test001",
                    handoff_title="Test Feature",
                    options=["first", "second"],
                    field_name="test",
                    update_method="handoff_update_status",
                ),
                callback=capture_result,
            )
            await pilot.pause()

            # Press '5' - beyond available options
            await pilot.press("5")
            await pilot.pause()

            # Modal should still be visible (nothing happened)
            assert isinstance(app.screen, GenericSelectModal), (
                "Modal should still be open when pressing invalid number key"
            )


# ============================================================================
# Tests for Escape Dismissal
# ============================================================================


class TestGenericSelectModalEscape:
    """Tests for escape key dismissal."""

    @pytest.mark.asyncio
    async def test_escape_dismisses_modal(self, temp_project_with_handoffs):
        """ESC should dismiss modal with empty string."""
        from core.tui.app import GenericSelectModal, RecallMonitorApp

        app = RecallMonitorApp()
        result_holder = {"result": "not_called"}

        async with app.run_test() as pilot:
            await pilot.pause()

            def capture_result(result):
                result_holder["result"] = result

            app.push_screen(
                GenericSelectModal(
                    handoff_id="hf-test001",
                    handoff_title="Test Feature",
                    options=["a", "b"],
                    field_name="status",
                    update_method="handoff_update_status",
                ),
                callback=capture_result,
            )
            await pilot.pause()

            # Press Escape
            await pilot.press("escape")
            await pilot.pause()

            # Modal should be dismissed
            assert not isinstance(app.screen, GenericSelectModal), (
                "Modal should be dismissed after Escape"
            )
            # Result should be empty string
            assert result_holder["result"] == "", (
                f"Expected empty string on cancel, got: {result_holder['result']}"
            )


# ============================================================================
# Tests for Arrow Navigation and Selection
# ============================================================================


class TestGenericSelectModalArrowNavigation:
    """Tests for arrow key navigation in GenericSelectModal."""

    @pytest.mark.asyncio
    async def test_modal_has_option_list(self, temp_project_with_handoffs):
        """GenericSelectModal should contain an OptionList widget."""
        from textual.widgets import OptionList

        from core.tui.app import GenericSelectModal, RecallMonitorApp

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            app.push_screen(
                GenericSelectModal(
                    handoff_id="hf-test001",
                    handoff_title="Test Feature",
                    options=["a", "b", "c"],
                    field_name="status",
                    update_method="handoff_update_status",
                )
            )
            await pilot.pause()

            option_lists = app.screen.query(OptionList)
            assert len(option_lists) > 0, "Modal should contain an OptionList widget"

    @pytest.mark.asyncio
    async def test_arrow_down_navigates_options(self, temp_project_with_handoffs):
        """Arrow down should navigate to next option."""
        from textual.widgets import OptionList

        from core.tui.app import GenericSelectModal, RecallMonitorApp

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            app.push_screen(
                GenericSelectModal(
                    handoff_id="hf-test001",
                    handoff_title="Test Feature",
                    options=["a", "b", "c"],
                    field_name="status",
                    update_method="handoff_update_status",
                )
            )
            await pilot.pause()

            option_list = app.screen.query_one(OptionList)
            initial_index = option_list.highlighted

            await pilot.press("down")
            await pilot.pause()

            new_index = option_list.highlighted
            assert new_index != initial_index or initial_index is None, (
                "Arrow down should change highlighted option"
            )

    @pytest.mark.asyncio
    async def test_enter_selects_highlighted_option(self, temp_project_with_handoffs):
        """Enter should select the currently highlighted option."""
        from textual.widgets import OptionList

        from core.tui.app import GenericSelectModal, RecallMonitorApp

        app = RecallMonitorApp()
        result_holder = {"result": None}

        async with app.run_test() as pilot:
            await pilot.pause()

            def capture_result(result):
                result_holder["result"] = result

            app.push_screen(
                GenericSelectModal(
                    handoff_id="hf-test001",
                    handoff_title="Test Feature",
                    options=["first", "second", "third"],
                    field_name="status",
                    update_method="handoff_update_status",
                ),
                callback=capture_result,
            )
            await pilot.pause()

            # Navigate to second option
            await pilot.press("down")
            await pilot.pause()

            # Press Enter to select
            await pilot.press("enter")
            await pilot.pause()

            # Modal should be dismissed with second option
            assert not isinstance(app.screen, GenericSelectModal), "Modal should be dismissed"
            assert result_holder["result"] is not None, "Callback should have been called"


# ============================================================================
# Tests for Selection Result Format
# ============================================================================


class TestGenericSelectModalResultFormat:
    """Tests for the format of selection results."""

    @pytest.mark.asyncio
    async def test_selection_returns_field_colon_value_format(
        self, temp_project_with_handoffs
    ):
        """Selecting an option should dismiss with 'field:value' format."""
        from core.tui.app import GenericSelectModal, RecallMonitorApp

        app = RecallMonitorApp()
        result_holder = {"result": None}

        async with app.run_test() as pilot:
            await pilot.pause()

            def capture_result(result):
                result_holder["result"] = result

            app.push_screen(
                GenericSelectModal(
                    handoff_id="hf-test001",
                    handoff_title="Test Feature",
                    options=["in_progress", "blocked"],
                    field_name="status",
                    update_method="handoff_update_status",
                ),
                callback=capture_result,
            )
            await pilot.pause()

            await pilot.press("1")
            await pilot.pause()

            # Result should be "field:value"
            assert result_holder["result"] == "status:in_progress", (
                f"Expected 'status:in_progress', got: {result_holder['result']}"
            )

    @pytest.mark.asyncio
    async def test_phase_selection_format(self, temp_project_with_handoffs):
        """Phase selection should return 'phase:value' format."""
        from core.tui.app import GenericSelectModal, RecallMonitorApp

        app = RecallMonitorApp()
        result_holder = {"result": None}

        async with app.run_test() as pilot:
            await pilot.pause()

            def capture_result(result):
                result_holder["result"] = result

            app.push_screen(
                GenericSelectModal(
                    handoff_id="hf-test001",
                    handoff_title="Test Feature",
                    options=["research", "planning", "implementing", "review"],
                    field_name="phase",
                    update_method="handoff_update_phase",
                ),
                callback=capture_result,
            )
            await pilot.pause()

            await pilot.press("3")  # Select "implementing"
            await pilot.pause()

            assert result_holder["result"] == "phase:implementing", (
                f"Expected 'phase:implementing', got: {result_holder['result']}"
            )

    @pytest.mark.asyncio
    async def test_agent_selection_format(self, temp_project_with_handoffs):
        """Agent selection should return 'agent:value' format."""
        from core.tui.app import GenericSelectModal, RecallMonitorApp

        app = RecallMonitorApp()
        result_holder = {"result": None}

        async with app.run_test() as pilot:
            await pilot.pause()

            def capture_result(result):
                result_holder["result"] = result

            app.push_screen(
                GenericSelectModal(
                    handoff_id="hf-test001",
                    handoff_title="Test Feature",
                    options=["explore", "general-purpose", "plan", "review", "user"],
                    field_name="agent",
                    update_method="handoff_update_agent",
                ),
                callback=capture_result,
            )
            await pilot.pause()

            await pilot.press("2")  # Select "general-purpose"
            await pilot.pause()

            assert result_holder["result"] == "agent:general-purpose", (
                f"Expected 'agent:general-purpose', got: {result_holder['result']}"
            )


# ============================================================================
# Tests for Integration with HandoffActionScreen
# ============================================================================


class TestGenericSelectModalIntegration:
    """Tests for using GenericSelectModal from HandoffActionScreen."""

    @pytest.mark.asyncio
    async def test_status_action_uses_generic_modal(self, temp_project_with_handoffs):
        """Pressing 's' on action screen should open GenericSelectModal for status."""
        from core.tui.app import GenericSelectModal, HandoffActionScreen, RecallMonitorApp

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            app.push_screen(HandoffActionScreen("hf-test001", "Test Feature"))
            await pilot.pause()

            await pilot.press("s")
            await pilot.pause()

            # Should have opened GenericSelectModal (or StatusSelectScreen if not migrated yet)
            # Once migrated, this should be GenericSelectModal
            screen = app.screen
            assert isinstance(screen, GenericSelectModal), (
                f"Expected GenericSelectModal, got {type(screen).__name__}"
            )
            assert screen.field_name == "status"

    @pytest.mark.asyncio
    async def test_phase_action_uses_generic_modal(self, temp_project_with_handoffs):
        """Pressing 'p' on action screen should open GenericSelectModal for phase."""
        from core.tui.app import GenericSelectModal, HandoffActionScreen, RecallMonitorApp

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            app.push_screen(HandoffActionScreen("hf-test001", "Test Feature"))
            await pilot.pause()

            await pilot.press("p")
            await pilot.pause()

            screen = app.screen
            assert isinstance(screen, GenericSelectModal), (
                f"Expected GenericSelectModal, got {type(screen).__name__}"
            )
            assert screen.field_name == "phase"

    @pytest.mark.asyncio
    async def test_agent_action_uses_generic_modal(self, temp_project_with_handoffs):
        """Pressing 'a' on action screen should open GenericSelectModal for agent."""
        from core.tui.app import GenericSelectModal, HandoffActionScreen, RecallMonitorApp

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            app.push_screen(HandoffActionScreen("hf-test001", "Test Feature"))
            await pilot.pause()

            await pilot.press("a")
            await pilot.pause()

            screen = app.screen
            assert isinstance(screen, GenericSelectModal), (
                f"Expected GenericSelectModal, got {type(screen).__name__}"
            )
            assert screen.field_name == "agent"


# ============================================================================
# Tests for Old Classes Removed
# ============================================================================


class TestOldClassesRemoved:
    """Tests verifying old modal classes are removed after migration."""

    def test_status_select_screen_not_in_app(self):
        """StatusSelectScreen should not exist after migration."""
        from core.tui import app

        assert not hasattr(app, "StatusSelectScreen"), (
            "StatusSelectScreen should be removed - use GenericSelectModal instead"
        )

    def test_phase_select_screen_not_in_app(self):
        """PhaseSelectScreen should not exist after migration."""
        from core.tui import app

        assert not hasattr(app, "PhaseSelectScreen"), (
            "PhaseSelectScreen should be removed - use GenericSelectModal instead"
        )

    def test_agent_select_screen_not_in_app(self):
        """AgentSelectScreen should not exist after migration."""
        from core.tui import app

        assert not hasattr(app, "AgentSelectScreen"), (
            "AgentSelectScreen should be removed - use GenericSelectModal instead"
        )
