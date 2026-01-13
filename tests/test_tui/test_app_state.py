# SPDX-License-Identifier: MIT
"""Tests for TUI app state dataclasses."""

import pytest
from dataclasses import is_dataclass


class TestSortState:
    """Tests for SortState dataclass."""

    def test_sort_state_is_dataclass(self):
        from core.tui.app_state import SortState

        assert is_dataclass(SortState)

    def test_sort_state_defaults(self):
        from core.tui.app_state import SortState

        state = SortState()
        assert state.column is None
        assert state.reverse is False

    def test_sort_state_custom_values(self):
        from core.tui.app_state import SortState

        state = SortState(column="timestamp", reverse=True)
        assert state.column == "timestamp"
        assert state.reverse is True


class TestSessionState:
    """Tests for SessionState dataclass."""

    def test_session_state_is_dataclass(self):
        from core.tui.app_state import SessionState

        assert is_dataclass(SessionState)

    def test_session_state_has_sort(self):
        from core.tui.app_state import SessionState

        state = SessionState()
        assert hasattr(state, "sort")

    def test_session_state_defaults(self):
        from core.tui.app_state import SessionState

        state = SessionState()
        assert state.current_id is None
        assert state.user_selected_id is None
        assert state.data == {}
        assert state.show_system is False
        assert state.timeline_view is False

    def test_session_state_sort_is_sort_state(self):
        from core.tui.app_state import SessionState, SortState

        state = SessionState()
        assert isinstance(state.sort, SortState)


class TestHandoffState:
    """Tests for HandoffState dataclass."""

    def test_handoff_state_is_dataclass(self):
        from core.tui.app_state import HandoffState

        assert is_dataclass(HandoffState)

    def test_handoff_state_has_filter(self):
        from core.tui.app_state import HandoffState

        state = HandoffState()
        assert hasattr(state, "filter_text")

    def test_handoff_state_defaults(self):
        from core.tui.app_state import HandoffState

        state = HandoffState()
        assert state.current_id is None
        assert state.user_selected_id is None
        assert state.enter_confirmed_id is None
        assert state.data == {}
        assert state.filter_text == ""
        assert state.show_completed is False
        assert state.total_count == 0
        assert state.detail_sessions == []
        assert state.detail_blockers == []

    def test_handoff_state_sort_is_sort_state(self):
        from core.tui.app_state import HandoffState, SortState

        state = HandoffState()
        assert isinstance(state.sort, SortState)


class TestAppState:
    """Tests for AppState dataclass."""

    def test_app_state_is_dataclass(self):
        from core.tui.app_state import AppState

        assert is_dataclass(AppState)

    def test_app_state_has_session_and_handoff(self):
        from core.tui.app_state import AppState

        state = AppState()
        assert hasattr(state, "session")
        assert hasattr(state, "handoff")

    def test_app_state_defaults(self):
        from core.tui.app_state import AppState

        state = AppState()
        assert state.project_filter is None
        assert state.paused is False
        assert state.last_event_count == 0
        assert state.live_activity_user_scrolled is False
        assert state.tabs_loaded == {}

    def test_app_state_session_is_session_state(self):
        from core.tui.app_state import AppState, SessionState

        state = AppState()
        assert isinstance(state.session, SessionState)

    def test_app_state_handoff_is_handoff_state(self):
        from core.tui.app_state import AppState, HandoffState

        state = AppState()
        assert isinstance(state.handoff, HandoffState)

    def test_app_state_nested_access(self):
        """Test that nested state can be accessed and modified."""
        from core.tui.app_state import AppState

        state = AppState()
        # Access nested sort state
        state.session.sort.column = "timestamp"
        state.session.sort.reverse = True
        assert state.session.sort.column == "timestamp"
        assert state.session.sort.reverse is True

        # Access handoff filter
        state.handoff.filter_text = "test"
        assert state.handoff.filter_text == "test"
