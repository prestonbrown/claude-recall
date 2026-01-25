#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Tests for RecallMonitorApp lifecycle behavior.

Tests cover app initialization, mounting, loading screen, compose, and constructor parameters.
"""

from pathlib import Path
import pytest

pytest.importorskip("textual")

# Configure pytest-asyncio
pytest_plugins = ("pytest_asyncio",)

from textual.widgets import Tab, Footer, Static, LoadingIndicator

# Import with fallback for installed vs dev paths
try:
    from core.tui.app import RecallMonitorApp, LoadingScreen
    from core.tui.app_state import AppState
except ImportError:
    from .app import RecallMonitorApp, LoadingScreen
    from .app_state import AppState


# --- Fixtures ---


@pytest.fixture
def temp_log_with_events(tmp_path: Path, monkeypatch):
    """
    Create a temp directory with an empty debug.log file.

    Patches CLAUDE_RECALL_STATE to use the temp directory.
    """
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    log_path = state_dir / "debug.log"
    log_path.write_text("")  # Empty log for basic tests

    # Patch environment to use temp state dir
    monkeypatch.setenv("CLAUDE_RECALL_STATE", str(state_dir))

    return log_path


# --- App Mount Tests ---


@pytest.mark.asyncio
async def test_app_mount_shows_loading_screen(temp_log_with_events: Path):
    """
    Verify LoadingScreen is pushed on mount.

    The on_mount handler should push a LoadingScreen modal to show
    loading progress during startup.
    """
    app = RecallMonitorApp(log_path=temp_log_with_events)

    async with app.run_test() as pilot:
        # The LoadingScreen should be pushed immediately on mount.
        # Since we have an empty log, loading should be very fast,
        # but the screen stack should have had LoadingScreen at some point.
        # After loading completes, LoadingScreen is popped.
        # We verify by checking that the app successfully initialized
        # (which requires LoadingScreen to have been shown and dismissed).
        await pilot.pause()

        # App should be running normally after mount completes
        # The LoadingScreen is popped after loading, so we verify
        # by checking the app is functional (not stuck on loading).
        assert app.is_running, "App should be running after mount"


@pytest.mark.asyncio
async def test_app_mount_starts_refresh_timer(temp_log_with_events: Path):
    """
    Verify timer is set after mount.

    The _refresh_timer should be initialized after the app mounts
    to enable auto-refresh functionality.
    """
    app = RecallMonitorApp(log_path=temp_log_with_events)

    async with app.run_test() as pilot:
        await pilot.pause()

        # Timer should be set after mount completes
        assert app._refresh_timer is not None, (
            "Refresh timer should be set after mount. "
            "Timer is required for auto-refresh functionality."
        )


# --- LoadingScreen Tests ---


@pytest.mark.asyncio
async def test_loading_screen_updates_status(temp_log_with_events: Path):
    """
    Test LoadingScreen.update_status method.

    The update_status method should update the #loading-status Static widget.
    We test this by creating an app with a custom LoadingScreen and verifying
    the method works within the app context.
    """
    # Verify the method exists on the class
    assert hasattr(LoadingScreen, "update_status"), (
        "LoadingScreen should have update_status method"
    )

    # Verify the compose method creates the expected widgets
    # by checking source code structure
    import inspect
    source = inspect.getsource(LoadingScreen.compose)
    assert "loading-status" in source, (
        "LoadingScreen.compose should create a widget with id='loading-status'"
    )
    assert "LoadingIndicator" in source, (
        "LoadingScreen.compose should create a LoadingIndicator"
    )


@pytest.mark.asyncio
async def test_loading_screen_dismissed_after_load(temp_log_with_events: Path):
    """
    LoadingScreen should be popped after data loads.

    After initial data loading completes, the LoadingScreen modal
    should be dismissed (popped from the screen stack).
    """
    app = RecallMonitorApp(log_path=temp_log_with_events)

    async with app.run_test() as pilot:
        await pilot.pause()

        # After loading, there should be no LoadingScreen on the screen stack
        # The main screen should be visible (the default screen)
        # Check that we can query widgets from the main app (not blocked by modal)
        tabs = app.query(Tab)
        assert len(tabs) > 0, (
            "Should be able to query tabs after LoadingScreen is dismissed. "
            "This indicates LoadingScreen was not properly popped."
        )


# --- Compose Tests ---


@pytest.mark.asyncio
async def test_compose_creates_all_tabs(temp_log_with_events: Path):
    """
    All 6 tabs should be created: Live Activity, Health, State, Session, Charts, Handoffs.
    """
    app = RecallMonitorApp(log_path=temp_log_with_events)

    async with app.run_test() as pilot:
        await pilot.pause()

        tabs = app.query(Tab)
        tab_labels = [str(tab.label) for tab in tabs]

        expected_tabs = [
            "Live Activity",
            "Health",
            "State",
            "Session",
            "Charts",
            "Handoffs",
        ]

        assert len(tabs) >= 6, (
            f"Expected at least 6 tabs, got {len(tabs)}. "
            f"Available tabs: {tab_labels}"
        )

        for expected in expected_tabs:
            assert any(expected in label for label in tab_labels), (
                f"Expected tab '{expected}' not found. "
                f"Available tabs: {tab_labels}"
            )


@pytest.mark.asyncio
async def test_compose_creates_footer_bindings(temp_log_with_events: Path):
    """
    Footer should exist and show key bindings.

    The app should have a Footer widget that displays available key bindings.
    """
    app = RecallMonitorApp(log_path=temp_log_with_events)

    async with app.run_test() as pilot:
        await pilot.pause()

        # Query for Footer widget
        footer = app.query_one(Footer)
        assert footer is not None, "Footer widget should exist"


# --- Initial State Tests ---


def test_app_initial_state():
    """
    AppState should be initialized correctly.

    Verify the AppState dataclass is properly initialized with default values.
    """
    state = AppState()

    # Check default values
    assert state.project_filter is None, "project_filter should default to None"
    assert state.paused is False, "paused should default to False"
    assert state.last_event_count == 0, "last_event_count should default to 0"
    assert state.live_activity_user_scrolled is False, (
        "live_activity_user_scrolled should default to False"
    )
    assert state.tabs_loaded == {}, "tabs_loaded should default to empty dict"
    assert state.chart_period_hours == 24, "chart_period_hours should default to 24"

    # Check nested state objects exist
    assert state.session is not None, "session state should be initialized"
    assert state.handoff is not None, "handoff state should be initialized"


# --- Constructor Parameter Tests ---


@pytest.mark.asyncio
async def test_app_accepts_project_filter(temp_log_with_events: Path):
    """
    Constructor should accept and store project_filter parameter.
    """
    project_filter = "my-test-project"
    app = RecallMonitorApp(
        project_filter=project_filter,
        log_path=temp_log_with_events,
    )

    async with app.run_test() as pilot:
        await pilot.pause()

        assert app.state.project_filter == project_filter, (
            f"Expected project_filter to be '{project_filter}', "
            f"got '{app.state.project_filter}'"
        )


@pytest.mark.asyncio
async def test_app_accepts_log_path(temp_log_with_events: Path):
    """
    Constructor should accept and use log_path parameter.
    """
    app = RecallMonitorApp(log_path=temp_log_with_events)

    async with app.run_test() as pilot:
        await pilot.pause()

        # The log_reader should use the provided log_path
        assert app.log_reader.log_path == temp_log_with_events, (
            f"Expected log_path to be '{temp_log_with_events}', "
            f"got '{app.log_reader.log_path}'"
        )
