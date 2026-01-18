#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Tests for lazy tab loading in the RecallMonitorApp TUI.

These tests verify that:
1. Only the initial "live" tab is loaded at startup
2. Other tabs load data on first activation (lazy loading)
3. Tabs don't reload on subsequent activations
4. Refresh timer only refreshes tabs that have been loaded
"""

from pathlib import Path
import json
import pytest
from unittest.mock import patch, MagicMock

pytest.importorskip("textual")

# Configure pytest-asyncio
pytest_plugins = ("pytest_asyncio",)

from textual.widgets import RichLog, Static, DataTable

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
    ]

    lines = [json.dumps(e) for e in events]
    log_path.write_text("\n".join(lines) + "\n")

    # Patch environment to use temp state dir
    monkeypatch.setenv("CLAUDE_RECALL_STATE", str(state_dir))

    return log_path


# --- Test: Only "live" tab loaded at startup ---


@pytest.mark.asyncio
async def test_only_live_tab_loaded_at_startup(temp_log_with_events: Path):
    """
    Verify that only the "live" tab is marked as loaded at startup.

    Other tabs should NOT be loaded until the user activates them.
    This tests the lazy loading optimization.
    """
    app = RecallMonitorApp(log_path=temp_log_with_events)

    async with app.run_test() as pilot:
        # Wait for mount and initial data load
        await pilot.pause()

        # "live" tab should be marked as loaded
        assert app.state.tabs_loaded.get("live", False) is True, (
            "The 'live' tab should be marked as loaded at startup. "
            f"tabs_loaded state: {app.state.tabs_loaded}"
        )

        # Other tabs should NOT be loaded yet
        other_tabs = ["health", "state", "session", "handoffs", "charts"]
        for tab_id in other_tabs:
            assert app.state.tabs_loaded.get(tab_id, False) is False, (
                f"Tab '{tab_id}' should NOT be loaded at startup (lazy loading). "
                f"tabs_loaded state: {app.state.tabs_loaded}"
            )


@pytest.mark.asyncio
async def test_event_log_has_content_at_startup(temp_log_with_events: Path):
    """
    Verify the event log (live tab) has content after mount.

    The live tab is the initial tab and MUST be loaded at startup.
    """
    app = RecallMonitorApp(log_path=temp_log_with_events)

    async with app.run_test() as pilot:
        await pilot.pause()

        event_log = app.query_one("#event-log", RichLog)

        # Event log should have content (live tab was loaded)
        assert len(event_log.lines) > 0, (
            "Event log should have content after mount. "
            "The 'live' tab should be fully loaded at startup."
        )


# --- Test: Tabs load on first activation ---


@pytest.mark.asyncio
async def test_health_tab_loads_on_first_activation(temp_log_with_events: Path):
    """
    Verify the health tab loads data when first activated.

    Before activation: tab should not be loaded
    After activation: tab should be loaded and show real content
    """
    app = RecallMonitorApp(log_path=temp_log_with_events)

    async with app.run_test() as pilot:
        await pilot.pause()

        # Before activation - health tab should not be loaded
        assert app.state.tabs_loaded.get("health", False) is False, (
            "Health tab should not be loaded before activation"
        )

        # Activate health tab (F2)
        await pilot.press("f2")
        await pilot.pause()

        # After activation - health tab should be loaded
        assert app.state.tabs_loaded.get("health", False) is True, (
            "Health tab should be marked as loaded after activation. "
            f"tabs_loaded state: {app.state.tabs_loaded}"
        )

        # Health stats should have real content
        health_stats = app.query_one("#health-stats", Static)
        content = str(health_stats.render())

        # Should have actual stats, not just "Loading..."
        assert "Loading" not in content or "System Health" in content, (
            f"Health stats should show actual data after tab activation. "
            f"Got: {content[:100]}..."
        )


@pytest.mark.asyncio
async def test_state_tab_loads_on_first_activation(temp_log_with_events: Path):
    """
    Verify the state tab loads data when first activated.
    """
    app = RecallMonitorApp(log_path=temp_log_with_events)

    async with app.run_test() as pilot:
        await pilot.pause()

        # Before activation
        assert app.state.tabs_loaded.get("state", False) is False

        # Activate state tab (F3)
        await pilot.press("f3")
        await pilot.pause()

        # After activation
        assert app.state.tabs_loaded.get("state", False) is True, (
            "State tab should be marked as loaded after activation"
        )


@pytest.mark.asyncio
async def test_session_tab_loads_on_first_activation(temp_log_with_events: Path):
    """
    Verify the session tab loads data when first activated.
    """
    app = RecallMonitorApp(log_path=temp_log_with_events)

    async with app.run_test() as pilot:
        await pilot.pause()

        # Before activation
        assert app.state.tabs_loaded.get("session", False) is False

        # Activate session tab (F4)
        await pilot.press("f4")
        await pilot.pause()

        # After activation
        assert app.state.tabs_loaded.get("session", False) is True, (
            "Session tab should be marked as loaded after activation"
        )


@pytest.mark.asyncio
async def test_handoffs_tab_loads_on_first_activation(temp_log_with_events: Path):
    """
    Verify the handoffs tab loads data when first activated.
    """
    app = RecallMonitorApp(log_path=temp_log_with_events)

    async with app.run_test() as pilot:
        await pilot.pause()

        # Before activation
        assert app.state.tabs_loaded.get("handoffs", False) is False

        # Activate handoffs tab (F6 - see BINDINGS in app.py)
        await pilot.press("f6")
        await pilot.pause()

        # After activation
        assert app.state.tabs_loaded.get("handoffs", False) is True, (
            "Handoffs tab should be marked as loaded after activation"
        )


@pytest.mark.asyncio
async def test_charts_tab_loads_on_first_activation(temp_log_with_events: Path):
    """
    Verify the charts tab loads data when first activated.
    """
    app = RecallMonitorApp(log_path=temp_log_with_events)

    async with app.run_test() as pilot:
        await pilot.pause()

        # Before activation
        assert app.state.tabs_loaded.get("charts", False) is False

        # Activate charts tab (F5 - see BINDINGS in app.py)
        await pilot.press("f5")
        await pilot.pause()

        # After activation
        assert app.state.tabs_loaded.get("charts", False) is True, (
            "Charts tab should be marked as loaded after activation"
        )


# --- Test: Tabs don't reload on subsequent activations ---


@pytest.mark.asyncio
async def test_tab_does_not_reload_on_subsequent_activation(temp_log_with_events: Path):
    """
    Verify that tabs don't reload data when activated a second time.

    This tests that the tabs_loaded flag prevents duplicate loading.
    """
    app = RecallMonitorApp(log_path=temp_log_with_events)

    async with app.run_test() as pilot:
        await pilot.pause()

        # First activation of health tab
        await pilot.press("f2")
        await pilot.pause()

        # Track that health is loaded
        assert app.state.tabs_loaded.get("health", False) is True

        # Switch away to live tab
        await pilot.press("f1")
        await pilot.pause()

        # Track call count by patching _update_health
        call_count = 0
        original_update_health = app._update_health

        def counting_update_health():
            nonlocal call_count
            call_count += 1
            return original_update_health()

        app._update_health = counting_update_health

        # Switch back to health tab (second activation)
        await pilot.press("f2")
        await pilot.pause()

        # _update_health should NOT have been called on second activation
        assert call_count == 0, (
            f"_update_health was called {call_count} times on second activation. "
            "Tabs should not reload on subsequent activations (tabs_loaded should prevent this)."
        )


@pytest.mark.asyncio
async def test_multiple_tab_switches_only_load_once(temp_log_with_events: Path):
    """
    Verify that switching between tabs multiple times only loads each tab once.
    """
    app = RecallMonitorApp(log_path=temp_log_with_events)

    async with app.run_test() as pilot:
        await pilot.pause()

        # Visit all tabs
        for key in ["f2", "f3", "f4", "f5", "f6"]:
            await pilot.press(key)
            await pilot.pause()

        # All tabs should be loaded
        expected_loaded = {"live", "health", "state", "session", "handoffs", "charts"}
        for tab_id in expected_loaded:
            assert app.state.tabs_loaded.get(tab_id, False) is True, (
                f"Tab '{tab_id}' should be loaded after visiting all tabs"
            )

        # Now track calls while switching tabs again
        load_counts = {"health": 0, "state": 0, "session": 0, "handoffs": 0, "charts": 0}

        # Store original methods
        originals = {
            "health": app._update_health,
            "state": app._update_state,
            "session": app._setup_session_list,
            "handoffs": app._setup_handoff_list,
            "charts": app._update_charts,
        }

        # Replace with counting wrappers
        def make_counter(tab_id, original):
            def wrapper(*args, **kwargs):
                load_counts[tab_id] += 1
                return original(*args, **kwargs)
            return wrapper

        app._update_health = make_counter("health", originals["health"])
        app._update_state = make_counter("state", originals["state"])
        app._setup_session_list = make_counter("session", originals["session"])
        app._setup_handoff_list = make_counter("handoffs", originals["handoffs"])
        app._update_charts = make_counter("charts", originals["charts"])

        # Switch to all tabs again
        for key in ["f2", "f3", "f4", "f5", "f6"]:
            await pilot.press(key)
            await pilot.pause()

        # No loading methods should have been called (all tabs already loaded)
        for tab_id, count in load_counts.items():
            assert count == 0, (
                f"Tab '{tab_id}' load method was called {count} times on re-activation. "
                "Should be 0 (tabs already loaded)."
            )


# --- Test: Refresh timer respects tabs_loaded ---


@pytest.mark.asyncio
async def test_refresh_timer_only_refreshes_loaded_tabs(temp_log_with_events: Path):
    """
    Verify that the refresh timer only refreshes tabs that have been loaded.

    Unloaded tabs should not be refreshed (no point loading data the user hasn't seen).
    """
    app = RecallMonitorApp(log_path=temp_log_with_events)

    async with app.run_test() as pilot:
        await pilot.pause()

        # Only "live" tab is loaded at startup
        # health, state, etc. should NOT be refreshed by the timer

        # Track refresh calls
        refresh_calls = {"health": 0, "state": 0, "charts": 0}

        originals = {
            "health": app._update_health,
            "state": app._update_state,
            "charts": app._update_charts,
        }

        def make_counter(tab_id, original):
            def wrapper(*args, **kwargs):
                refresh_calls[tab_id] += 1
                return original(*args, **kwargs)
            return wrapper

        app._update_health = make_counter("health", originals["health"])
        app._update_state = make_counter("state", originals["state"])
        app._update_charts = make_counter("charts", originals["charts"])

        # Wait for auto-refresh timer (5 second interval + buffer)
        await pilot.pause(delay=6.0)

        # None of the unloaded tabs should have been refreshed
        for tab_id, count in refresh_calls.items():
            if not app.state.tabs_loaded.get(tab_id, False):
                assert count == 0, (
                    f"Tab '{tab_id}' was refreshed {count} times but is not loaded. "
                    "Refresh timer should only refresh loaded tabs."
                )


@pytest.mark.asyncio
async def test_refresh_timer_refreshes_currently_active_loaded_tab(temp_log_with_events: Path):
    """
    Verify that the refresh timer refreshes the currently active tab if loaded.

    The session tab has specific refresh behavior - verify it works after loading.
    """
    app = RecallMonitorApp(log_path=temp_log_with_events)

    async with app.run_test() as pilot:
        await pilot.pause()

        # Activate session tab to load it
        await pilot.press("f4")
        await pilot.pause()

        # Verify session tab is loaded
        assert app.state.tabs_loaded.get("session", False) is True

        # Track refresh calls
        session_refresh_count = 0
        original_refresh = app._refresh_session_list_async

        def counting_refresh():
            nonlocal session_refresh_count
            session_refresh_count += 1
            return original_refresh()

        app._refresh_session_list_async = counting_refresh

        # Wait for auto-refresh timer
        await pilot.pause(delay=6.0)

        # Session tab should have been refreshed (it's active and loaded)
        assert session_refresh_count > 0, (
            "Session tab should be refreshed by timer when active and loaded. "
            f"Refresh count: {session_refresh_count}"
        )
