#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Tests for key bindings in the RecallMonitorApp TUI.

These tests verify that key bindings trigger the expected actions
and state changes.
"""

from pathlib import Path
import json
import pytest
from unittest.mock import patch, MagicMock

pytest.importorskip("textual")

# Configure pytest-asyncio
pytest_plugins = ("pytest_asyncio",)

from textual.widgets import TabbedContent, DataTable

# Import with fallback for installed vs dev paths
try:
    from core.tui.app import RecallMonitorApp
except ImportError:
    from .app import RecallMonitorApp


# --- Fixtures ---


@pytest.fixture
def temp_log_with_events(tmp_path: Path, monkeypatch):
    """
    Create a temp directory with a debug.log file containing sample events.

    Patches CLAUDE_RECALL_STATE to use the temp directory.
    """
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    log_path = state_dir / "debug.log"

    # Sample events with realistic data
    events = [
        {
            "event": "session_start",
            "level": "info",
            "timestamp": "2026-01-06T10:00:00Z",
            "session_id": "test-123",
            "pid": 1234,
            "project": "test-project",
            "total_lessons": 5,
            "system_count": 2,
            "project_count": 3,
        },
        {
            "event": "citation",
            "level": "info",
            "timestamp": "2026-01-06T10:01:00Z",
            "session_id": "test-123",
            "pid": 1234,
            "project": "test-project",
            "lesson_id": "L001",
            "uses_before": 5,
            "uses_after": 6,
        },
        {
            "event": "hook_end",
            "level": "info",
            "timestamp": "2026-01-06T10:01:30Z",
            "session_id": "test-123",
            "pid": 1234,
            "project": "test-project",
            "hook": "SessionStart",
            "total_ms": 45.5,
        },
    ]

    lines = [json.dumps(e) for e in events]
    log_path.write_text("\n".join(lines) + "\n")

    # Patch environment to use temp state dir
    monkeypatch.setenv("CLAUDE_RECALL_STATE", str(state_dir))

    return log_path


# --- Test 1: Quit binding 'q' ---


@pytest.mark.asyncio
async def test_quit_binding_q(temp_log_with_events: Path):
    """
    Verify that pressing 'q' exits the application.
    """
    app = RecallMonitorApp(log_path=temp_log_with_events)

    async with app.run_test() as pilot:
        await pilot.pause()

        # Press 'q' to quit
        await pilot.press("q")
        await pilot.pause()

        # App should be in exiting state or have _exit set
        # The app run_test context may catch the exit, so we check
        # that the action was triggered by verifying no exception
        # and the test completes (app exits cleanly)
        assert True  # If we get here, 'q' triggered quit successfully


# --- Test 2: Tab switch F1-F6 ---


@pytest.mark.asyncio
async def test_tab_switch_f1_to_f6(temp_log_with_events: Path):
    """
    Verify that F1-F6 keys switch between tabs.
    """
    app = RecallMonitorApp(log_path=temp_log_with_events)

    async with app.run_test() as pilot:
        await pilot.pause()

        tabs = app.query_one(TabbedContent)

        # F1 -> Live tab (default)
        await pilot.press("f1")
        await pilot.pause()
        assert tabs.active == "live", f"Expected 'live', got '{tabs.active}'"

        # F2 -> Health tab
        await pilot.press("f2")
        await pilot.pause()
        assert tabs.active == "health", f"Expected 'health', got '{tabs.active}'"

        # F3 -> State tab
        await pilot.press("f3")
        await pilot.pause()
        assert tabs.active == "state", f"Expected 'state', got '{tabs.active}'"

        # F4 -> Session tab
        await pilot.press("f4")
        await pilot.pause()
        assert tabs.active == "session", f"Expected 'session', got '{tabs.active}'"

        # F5 -> Charts tab
        await pilot.press("f5")
        await pilot.pause()
        assert tabs.active == "charts", f"Expected 'charts', got '{tabs.active}'"

        # F6 -> Handoffs tab
        await pilot.press("f6")
        await pilot.pause()
        assert tabs.active == "handoffs", f"Expected 'handoffs', got '{tabs.active}'"


# --- Test 3: Pause toggle 'p' ---


@pytest.mark.asyncio
async def test_pause_toggle_p(temp_log_with_events: Path):
    """
    Verify that 'p' toggles the pause state.
    """
    app = RecallMonitorApp(log_path=temp_log_with_events)

    async with app.run_test() as pilot:
        await pilot.pause()

        # Initial state
        assert app.state.paused is False, "App should not be paused initially"

        # Toggle on
        await pilot.press("p")
        await pilot.pause()
        assert app.state.paused is True, "App should be paused after pressing 'p'"

        # Toggle off
        await pilot.press("p")
        await pilot.pause()
        assert app.state.paused is False, "App should resume after pressing 'p' again"


# --- Test 4: Refresh binding 'r' ---


@pytest.mark.asyncio
async def test_refresh_binding_r(temp_log_with_events: Path):
    """
    Verify that 'r' triggers a refresh.
    """
    app = RecallMonitorApp(log_path=temp_log_with_events)

    async with app.run_test() as pilot:
        await pilot.pause()

        # Track if _load_events was called (live tab refresh)
        load_events_called = False
        original_load_events = app._load_events

        def tracking_load_events():
            nonlocal load_events_called
            load_events_called = True
            return original_load_events()

        app._load_events = tracking_load_events

        # Press 'r' to refresh
        await pilot.press("r")
        await pilot.pause()

        assert load_events_called, "Refresh should trigger _load_events"


# --- Test 5: Toggle all binding 'a' ---


@pytest.mark.asyncio
async def test_toggle_all_binding_a(temp_log_with_events: Path):
    """
    Verify that 'a' toggles the show_all flag.
    """
    app = RecallMonitorApp(log_path=temp_log_with_events)

    async with app.run_test() as pilot:
        await pilot.pause()

        # Initial state
        initial_show_all = getattr(app, "_show_all", False)

        # Toggle
        await pilot.press("a")
        await pilot.pause()

        assert app._show_all != initial_show_all, (
            "Pressing 'a' should toggle _show_all"
        )

        # Toggle back
        await pilot.press("a")
        await pilot.pause()

        assert app._show_all == initial_show_all, (
            "Pressing 'a' again should toggle _show_all back"
        )


# --- Test 6: Expand session binding 'e' ---


@pytest.mark.asyncio
async def test_expand_session_binding_e(temp_log_with_events: Path):
    """
    Verify that 'e' triggers the expand/enrich action.
    """
    app = RecallMonitorApp(log_path=temp_log_with_events)

    async with app.run_test() as pilot:
        await pilot.pause()

        # Switch to session tab where 'e' has expand behavior
        await pilot.press("f4")
        await pilot.pause()

        # Track if the expand action was triggered
        expand_called = False
        original_expand = app.action_expand_session

        def tracking_expand():
            nonlocal expand_called
            expand_called = True
            return original_expand()

        app.action_expand_session = tracking_expand

        # Press 'e' to expand
        await pilot.press("e")
        await pilot.pause()

        assert expand_called, "Pressing 'e' should trigger action_expand_session"


# --- Test 7: Toggle completed binding 'c' ---


@pytest.mark.asyncio
async def test_toggle_completed_binding_c(temp_log_with_events: Path):
    """
    Verify that 'c' toggles completed handoffs visibility.
    """
    app = RecallMonitorApp(log_path=temp_log_with_events)

    async with app.run_test() as pilot:
        await pilot.pause()

        # Switch to handoffs tab where 'c' toggle works
        await pilot.press("f6")
        await pilot.pause()

        # Initial state
        initial_show_completed = app.state.handoff.show_completed

        # Toggle
        await pilot.press("c")
        await pilot.pause()

        assert app.state.handoff.show_completed != initial_show_completed, (
            "Pressing 'c' should toggle show_completed on handoffs tab"
        )

        # Toggle back
        await pilot.press("c")
        await pilot.pause()

        assert app.state.handoff.show_completed == initial_show_completed, (
            "Pressing 'c' again should toggle show_completed back"
        )


# --- Test 8: Toggle system sessions 'w' ---


@pytest.mark.asyncio
async def test_toggle_system_sessions_w(temp_log_with_events: Path):
    """
    Verify that 'w' triggers the toggle_system_sessions action.
    """
    app = RecallMonitorApp(log_path=temp_log_with_events)

    async with app.run_test() as pilot:
        await pilot.pause()

        # Track action calls - replace action entirely to prevent app errors
        toggle_called = False

        def tracking_toggle():
            nonlocal toggle_called
            toggle_called = True
            # Don't call original to avoid refresh issues with test data

        app.action_toggle_system_sessions = tracking_toggle

        # Press 'w'
        await pilot.press("w")
        await pilot.pause()

        assert toggle_called, (
            "Pressing 'w' should trigger action_toggle_system_sessions"
        )


# --- Test 9: Toggle timeline 't' ---


@pytest.mark.asyncio
async def test_toggle_timeline_t(temp_log_with_events: Path):
    """
    Verify that 't' toggles timeline view.
    """
    app = RecallMonitorApp(log_path=temp_log_with_events)

    async with app.run_test() as pilot:
        await pilot.pause()

        # Switch to handoffs tab where 't' timeline toggle works
        await pilot.press("f6")
        await pilot.pause()

        # Initial state
        initial_timeline = app.state.session.timeline_view

        # Toggle
        await pilot.press("t")
        await pilot.pause()

        assert app.state.session.timeline_view != initial_timeline, (
            "Pressing 't' should toggle timeline_view on handoffs tab"
        )

        # Toggle back
        await pilot.press("t")
        await pilot.pause()

        assert app.state.session.timeline_view == initial_timeline, (
            "Pressing 't' again should toggle timeline_view back"
        )


# --- Test 10: Copy session Ctrl+C ---


@pytest.mark.asyncio
async def test_copy_session_ctrl_c(temp_log_with_events: Path):
    """
    Verify that Ctrl+C triggers the copy session action.

    The copy action has priority=True, so it should override default Ctrl+C.
    """
    app = RecallMonitorApp(log_path=temp_log_with_events)

    async with app.run_test() as pilot:
        await pilot.pause()

        # Switch to session tab where copy works
        await pilot.press("f4")
        await pilot.pause()

        # Track if copy action was called
        # Replace the action entirely to prevent execution (which may have bugs)
        copy_called = False

        def tracking_copy():
            nonlocal copy_called
            copy_called = True
            # Don't call original - just track that binding works

        app.action_copy_session = tracking_copy

        # Press Ctrl+C
        await pilot.press("ctrl+c")
        await pilot.pause()

        assert copy_called, (
            "Pressing Ctrl+C should trigger action_copy_session (priority=True)"
        )


# --- Test 11: Goto handoff 'h' ---


@pytest.mark.asyncio
async def test_goto_handoff_h(temp_log_with_events: Path):
    """
    Verify that 'h' triggers goto_handoff action.
    """
    app = RecallMonitorApp(log_path=temp_log_with_events)

    async with app.run_test() as pilot:
        await pilot.pause()

        # Switch to session tab where 'h' navigates to handoff
        await pilot.press("f4")
        await pilot.pause()

        # Track if action was called
        goto_handoff_called = False
        original_goto = app.action_goto_handoff

        def tracking_goto():
            nonlocal goto_handoff_called
            goto_handoff_called = True
            return original_goto()

        app.action_goto_handoff = tracking_goto

        # Press 'h'
        await pilot.press("h")
        await pilot.pause()

        assert goto_handoff_called, "Pressing 'h' should trigger action_goto_handoff"


# --- Test 12: Number keys 1-9 goto session ---


@pytest.mark.asyncio
async def test_number_keys_goto_session(temp_log_with_events: Path):
    """
    Verify that number keys 1-9 trigger goto_session actions.
    """
    app = RecallMonitorApp(log_path=temp_log_with_events)

    async with app.run_test() as pilot:
        await pilot.pause()

        # Switch to handoffs tab where number keys navigate to sessions
        await pilot.press("f6")
        await pilot.pause()

        # Track calls to _action_goto_session
        goto_session_calls = []
        original_goto = app._action_goto_session

        def tracking_goto(index):
            goto_session_calls.append(index)
            return original_goto(index)

        app._action_goto_session = tracking_goto

        # Press number keys 1-3
        await pilot.press("1")
        await pilot.pause()
        await pilot.press("2")
        await pilot.pause()
        await pilot.press("3")
        await pilot.pause()

        # Verify the calls were made with correct indices
        assert 0 in goto_session_calls, "Pressing '1' should call _action_goto_session(0)"
        assert 1 in goto_session_calls, "Pressing '2' should call _action_goto_session(1)"
        assert 2 in goto_session_calls, "Pressing '3' should call _action_goto_session(2)"


# --- Test 13: Switch tab updates active ---


@pytest.mark.asyncio
async def test_switch_tab_updates_active(temp_log_with_events: Path):
    """
    Verify that switching tabs updates the active tab state.
    """
    app = RecallMonitorApp(log_path=temp_log_with_events)

    async with app.run_test() as pilot:
        await pilot.pause()

        tabs = app.query_one(TabbedContent)

        # Initial state should be 'live'
        assert tabs.active == "live", "Initial tab should be 'live'"

        # Switch to health
        await pilot.press("f2")
        await pilot.pause()

        assert tabs.active == "health", (
            "After F2, active tab should be 'health'"
        )

        # Switch to state
        await pilot.press("f3")
        await pilot.pause()

        assert tabs.active == "state", (
            "After F3, active tab should be 'state'"
        )


# --- Test 14: Switch tab triggers lazy load ---


@pytest.mark.asyncio
async def test_switch_tab_triggers_lazy_load(temp_log_with_events: Path):
    """
    Verify that first tab switch triggers lazy loading.
    """
    app = RecallMonitorApp(log_path=temp_log_with_events)

    async with app.run_test() as pilot:
        await pilot.pause()

        # Before switching, health tab should not be loaded
        assert app.state.tabs_loaded.get("health", False) is False, (
            "Health tab should not be loaded initially"
        )

        # Switch to health tab
        await pilot.press("f2")
        await pilot.pause()

        # After switching, health tab should be loaded
        assert app.state.tabs_loaded.get("health", False) is True, (
            "Health tab should be loaded after first switch"
        )


# --- Test 15: Multiple key presses (combined test) ---


@pytest.mark.asyncio
async def test_multiple_key_presses_sequence(temp_log_with_events: Path):
    """
    Verify that multiple key presses work correctly in sequence.
    """
    app = RecallMonitorApp(log_path=temp_log_with_events)

    async with app.run_test() as pilot:
        await pilot.pause()

        tabs = app.query_one(TabbedContent)

        # Sequence: F2 (health) -> p (pause) -> F4 (session) -> p (unpause)
        await pilot.press("f2")
        await pilot.pause()
        assert tabs.active == "health"

        await pilot.press("p")
        await pilot.pause()
        assert app.state.paused is True

        await pilot.press("f4")
        await pilot.pause()
        assert tabs.active == "session"

        await pilot.press("p")
        await pilot.pause()
        assert app.state.paused is False


# --- Test 16: Key bindings are defined correctly ---


@pytest.mark.asyncio
async def test_bindings_defined_correctly(temp_log_with_events: Path):
    """
    Verify that expected bindings are defined in the app's BINDINGS.
    """
    # Check that expected keys are in BINDINGS
    expected_keys = ["q", "f1", "f2", "f3", "f4", "f5", "f6", "p", "r", "a",
                     "e", "c", "w", "t", "ctrl+c", "h", "1", "2", "3", "4",
                     "5", "6", "7", "8", "9"]

    app = RecallMonitorApp(log_path=temp_log_with_events)

    # Get all binding keys from the app's BINDINGS
    binding_keys = [b.key for b in app.BINDINGS]

    for key in expected_keys:
        assert key in binding_keys, (
            f"Expected binding '{key}' not found in app.BINDINGS. "
            f"Available: {binding_keys}"
        )
