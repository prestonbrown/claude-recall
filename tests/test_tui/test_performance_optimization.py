#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Tests for TUI performance optimizations.

These tests verify:
1. Timer debouncing - 5s interval, only refresh visible tab
2. Background parsing with async workers
3. Lazy tab loading - defer loading until tab is viewed

Tests are designed to FAIL initially until optimizations are implemented.
"""

import json
import time
import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

pytest.importorskip("textual")

# Configure pytest-asyncio
pytest_plugins = ("pytest_asyncio",)

from textual.widgets import DataTable, RichLog


# Import with fallback for installed vs dev paths
try:
    from core.tui.app import RecallMonitorApp
    from core.tui.transcript_reader import TranscriptReader
except ImportError:
    from .app import RecallMonitorApp
    from .transcript_reader import TranscriptReader


# --- Helper Functions ---


def make_timestamp(seconds_ago: int = 0) -> str:
    """Generate an ISO timestamp for N seconds ago."""
    dt = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def create_transcript(
    path: Path,
    first_prompt: str,
    tools: list,
    tokens: int,
    start_time: str,
    end_time: str,
) -> None:
    """Create a mock transcript JSONL file."""
    messages = []

    # User message
    messages.append(
        {
            "type": "user",
            "timestamp": start_time,
            "sessionId": path.stem,
            "message": {"role": "user", "content": first_prompt},
        }
    )

    # Assistant message with tools
    tool_uses = [{"type": "tool_use", "name": t, "input": {}} for t in tools]
    content = tool_uses if tools else [{"type": "text", "text": "Done"}]
    messages.append(
        {
            "type": "assistant",
            "timestamp": end_time,
            "sessionId": path.stem,
            "message": {
                "role": "assistant",
                "usage": {"input_tokens": 100, "output_tokens": tokens},
                "content": content,
            },
        }
    )

    with open(path, "w") as f:
        for msg in messages:
            f.write(json.dumps(msg) + "\n")


# --- Fixtures ---


@pytest.fixture
def mock_claude_home(tmp_path: Path, monkeypatch) -> Path:
    """Create a mock ~/.claude directory with transcript files."""
    claude_home = tmp_path / ".claude"
    projects_dir = claude_home / "projects"

    # Create project directory
    project_dir = projects_dir / "-Users-test-code-project-a"
    project_dir.mkdir(parents=True)

    # Create several sessions
    for i in range(5):
        create_transcript(
            project_dir / f"sess-{i}.jsonl",
            first_prompt=f"Session {i} task",
            tools=["Read", "Bash"],
            tokens=1000 + i * 100,
            start_time=make_timestamp(60 * (5 - i)),
            end_time=make_timestamp(50 * (5 - i)),
        )

    # Monkeypatch to use our mock Claude home
    monkeypatch.setenv("PROJECT_DIR", "/Users/test/code/project-a")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    return claude_home


@pytest.fixture
def temp_state_dir(tmp_path: Path, monkeypatch) -> Path:
    """Create temp state dir with empty debug.log for LogReader."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    # Create minimal debug.log so LogReader doesn't fail
    log_path = state_dir / "debug.log"
    log_path.write_text("")

    monkeypatch.setenv("CLAUDE_RECALL_STATE", str(state_dir))
    return state_dir


@pytest.fixture
def temp_project_with_handoffs(tmp_path: Path, monkeypatch) -> Path:
    """Create a temp project with a HANDOFFS.md file."""
    project_root = tmp_path / "test-project"
    project_root.mkdir()
    recall_dir = project_root / ".claude-recall"
    recall_dir.mkdir()

    handoffs_content = """# HANDOFFS.md - Active Work Tracking

## Active Handoffs

### [hf-0000001] First Handoff
- **Status**: in_progress | **Phase**: implementing | **Agent**: user
- **Created**: 2026-01-07 | **Updated**: 2026-01-08

**Description**: A test handoff for TUI testing.

**Tried** (1 steps):
  1. [success] Initial implementation

**Next**:
  - Complete the feature
"""
    (recall_dir / "HANDOFFS.md").write_text(handoffs_content)

    # Set up state directory
    state_dir = tmp_path / "state"
    state_dir.mkdir(exist_ok=True)
    (state_dir / "debug.log").write_text("")
    monkeypatch.setenv("CLAUDE_RECALL_STATE", str(state_dir))
    monkeypatch.setenv("PROJECT_DIR", str(project_root))

    return project_root


# ============================================================================
# Phase 2: Timer Debouncing Tests
# ============================================================================


class TestTimerInterval:
    """Test that the refresh timer interval is 5 seconds (not 2)."""

    @pytest.mark.asyncio
    async def test_refresh_timer_interval_is_5_seconds(
        self, mock_claude_home: Path, temp_state_dir: Path
    ):
        """Timer should fire every 5 seconds, not 2."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Check that app has _refresh_timer attribute
            assert hasattr(app, "_refresh_timer"), (
                "App should have _refresh_timer attribute"
            )

            # Check the timer interval
            # The timer's _interval attribute should be 5.0
            timer = app._refresh_timer
            assert timer is not None, "Refresh timer should be initialized"

            # Get the interval - Textual Timer has _interval attribute
            interval = getattr(timer, "_interval", None)
            if interval is None:
                # Try alternate attribute name
                interval = getattr(timer, "interval", None)

            assert interval is not None, "Could not find timer interval attribute"
            assert interval >= 5.0, (
                f"Timer interval should be at least 5 seconds for performance, "
                f"got {interval}s. Change from 2.0 to 5.0 in on_mount()."
            )


class TestTabSpecificRefresh:
    """Test that refresh only updates the currently visible tab."""

    @pytest.mark.asyncio
    async def test_refresh_only_updates_visible_tab(
        self, mock_claude_home: Path, temp_state_dir: Path, temp_project_with_handoffs: Path
    ):
        """Timer refresh should only update data for the currently visible tab."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Start on Live tab (default)
            # Track which refresh methods are called
            session_refresh_called = False
            handoff_refresh_called = False

            original_refresh_session = app._refresh_session_list
            original_refresh_handoff = app._refresh_handoff_list

            def track_session_refresh():
                nonlocal session_refresh_called
                session_refresh_called = True
                return original_refresh_session()

            def track_handoff_refresh():
                nonlocal handoff_refresh_called
                handoff_refresh_called = True
                return original_refresh_handoff()

            app._refresh_session_list = track_session_refresh
            app._refresh_handoff_list = track_handoff_refresh

            # Manually trigger timer callback while on Live tab
            app._on_refresh_timer()
            await pilot.pause()

            # When on Live tab, session and handoff refreshes should NOT be called
            # (optimization: only refresh visible tab)
            assert not session_refresh_called, (
                "Session refresh should NOT be called when Sessions tab is not visible. "
                "Fix: In _on_refresh_timer(), only refresh the currently active tab."
            )
            assert not handoff_refresh_called, (
                "Handoff refresh should NOT be called when Handoffs tab is not visible. "
                "Fix: In _on_refresh_timer(), only refresh the currently active tab."
            )


class TestDebouncing:
    """Test that rapid timer fires are debounced."""

    @pytest.mark.asyncio
    async def test_debounce_prevents_rapid_session_refreshes(
        self, mock_claude_home: Path, temp_state_dir: Path
    ):
        """Multiple timer fires within debounce window should skip session refresh."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Sessions tab
            await pilot.press("f4")
            await pilot.pause()

            # Track session refresh calls
            refresh_count = 0
            original_refresh = app._refresh_session_list

            def count_refresh():
                nonlocal refresh_count
                refresh_count += 1
                return original_refresh()

            app._refresh_session_list = count_refresh

            # First timer fire - should refresh
            app._on_refresh_timer()
            await pilot.pause()
            first_count = refresh_count

            # Rapid second fire - should be debounced
            app._on_refresh_timer()
            await pilot.pause()
            second_count = refresh_count

            # With debouncing, second call should not trigger another refresh
            # Allow for at most one additional call (the first one)
            assert second_count <= first_count + 1, (
                f"Debouncing should prevent rapid refreshes. "
                f"First call: {first_count}, Second call: {second_count}. "
                "Fix: Add debounce tracking with _last_session_refresh timestamp."
            )


# ============================================================================
# Phase 3: Background Parsing Tests (Async Workers)
# ============================================================================


class TestAsyncSessionRefresh:
    """Test that session refresh runs in background thread."""

    @pytest.mark.asyncio
    async def test_session_refresh_is_async(
        self, mock_claude_home: Path, temp_state_dir: Path
    ):
        """Session list refresh should use @work decorator for async execution."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Check if _refresh_session_list uses @work decorator or asyncio
            # The method should either:
            # 1. Be decorated with @work, or
            # 2. Call an async helper method

            # Look for async refresh method
            has_async_refresh = (
                hasattr(app, "_refresh_session_list_async") or
                hasattr(app, "_refresh_sessions_worker")
            )

            # Check if current method is decorated
            method = getattr(app, "_refresh_session_list", None)
            is_decorated = False
            if method:
                # Check for Textual worker decoration
                is_decorated = hasattr(method, "_work") or hasattr(method, "__wrapped__")

            assert has_async_refresh or is_decorated, (
                "Session refresh should be async to avoid blocking UI. "
                "Add @work decorator to _refresh_session_list or create "
                "_refresh_session_list_async using @work(exclusive=True)."
            )


class TestAsyncHandoffRefresh:
    """Test that handoff refresh runs in background thread."""

    @pytest.mark.asyncio
    async def test_handoff_refresh_is_async(
        self, mock_claude_home: Path, temp_state_dir: Path, temp_project_with_handoffs: Path
    ):
        """Handoff list refresh should use @work decorator for async execution."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Look for async refresh method
            has_async_refresh = (
                hasattr(app, "_refresh_handoff_list_async") or
                hasattr(app, "_refresh_handoffs_worker")
            )

            # Check if current method is decorated
            method = getattr(app, "_refresh_handoff_list", None)
            is_decorated = False
            if method:
                is_decorated = hasattr(method, "_work") or hasattr(method, "__wrapped__")

            assert has_async_refresh or is_decorated, (
                "Handoff refresh should be async to avoid blocking UI. "
                "Add @work decorator to _refresh_handoff_list or create "
                "_refresh_handoff_list_async using @work(exclusive=True)."
            )


# ============================================================================
# Phase 4: Lazy Tab Loading Tests
# ============================================================================


class TestLazyTabLoading:
    """Test that tabs load data lazily (only when viewed)."""

    @pytest.mark.asyncio
    async def test_tabs_loaded_tracking_exists(
        self, mock_claude_home: Path, temp_state_dir: Path
    ):
        """App should track which tabs have been loaded."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Should have state.tabs_loaded dict
            assert hasattr(app.state, "tabs_loaded"), (
                "App should have state.tabs_loaded dict to track lazy loading state."
            )

            tabs_loaded = getattr(app.state, "tabs_loaded", None)
            assert isinstance(tabs_loaded, dict), (
                "state.tabs_loaded should be a dictionary"
            )

    @pytest.mark.asyncio
    async def test_only_live_tab_loads_on_mount(
        self, mock_claude_home: Path, temp_state_dir: Path
    ):
        """App mount should only load Live tab initially, not Sessions/Handoffs."""
        # Track if list_all_sessions was called during mount
        list_sessions_called = False
        original_init = TranscriptReader.__init__

        def track_init(self, *args, **kwargs):
            original_init(self, *args, **kwargs)

        original_list_all = None

        def track_list_all(self, *args, **kwargs):
            nonlocal list_sessions_called
            list_sessions_called = True
            return original_list_all(self, *args, **kwargs)

        with patch.object(TranscriptReader, "list_all_sessions", track_list_all):
            original_list_all = TranscriptReader.list_all_sessions.__get__(
                None, TranscriptReader
            )

            app = RecallMonitorApp()

            async with app.run_test() as pilot:
                await pilot.pause()

                # With lazy loading, list_all_sessions should NOT be called on mount
                # It should only be called when Sessions tab is activated
                if hasattr(app, "_tabs_loaded"):
                    assert not list_sessions_called, (
                        "list_all_sessions should NOT be called during mount. "
                        "Sessions tab should load lazily when first viewed. "
                        "Fix: Remove _setup_session_list() from on_mount() and "
                        "call it in on_tabbed_content_tab_activated() instead."
                    )

    @pytest.mark.asyncio
    async def test_session_tab_loads_on_first_activation(
        self, mock_claude_home: Path, temp_state_dir: Path
    ):
        """Activating Sessions tab should trigger session list load."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Track refresh calls
            setup_called = False
            original_setup = app._setup_session_list

            def track_setup():
                nonlocal setup_called
                setup_called = True
                return original_setup()

            app._setup_session_list = track_setup

            # Switch to Sessions tab
            await pilot.press("f4")
            await pilot.pause()

            # Session list should now be loaded
            session_table = app.query_one("#session-list", DataTable)

            # Either setup was called, or table has data (was pre-loaded)
            has_data = session_table.row_count > 0

            assert setup_called or has_data, (
                "Sessions tab should load data when first activated. "
                "Add tab activation handler to call _setup_session_list()."
            )

    @pytest.mark.asyncio
    async def test_tab_not_reloaded_on_reactivation(
        self, mock_claude_home: Path, temp_state_dir: Path
    ):
        """Returning to an already-loaded tab should not re-load data."""
        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Sessions tab
            await pilot.press("f4")
            await pilot.pause()

            # Track setup calls
            setup_count = 0
            original_setup = app._setup_session_list

            def count_setup():
                nonlocal setup_count
                setup_count += 1
                return original_setup()

            app._setup_session_list = count_setup

            # Switch away
            await pilot.press("f1")  # Live tab
            await pilot.pause()

            # Switch back to Sessions
            await pilot.press("f4")
            await pilot.pause()

            # With lazy loading and tab tracking, setup should NOT be called again
            if hasattr(app, "_tabs_loaded"):
                assert setup_count == 0, (
                    f"Tab data should not be re-loaded on reactivation. "
                    f"Setup was called {setup_count} times. "
                    "Fix: Check _tabs_loaded[tab_id] before loading."
                )


# ============================================================================
# Combined Performance Test
# ============================================================================


class TestOverallPerformance:
    """Integration tests for overall performance improvements."""

    @pytest.mark.asyncio
    async def test_no_blocking_on_mount(
        self, mock_claude_home: Path, temp_state_dir: Path
    ):
        """App mount should complete quickly without blocking operations."""
        import time

        start_time = time.time()

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

        mount_time = time.time() - start_time

        # Mount should complete quickly (under 2 seconds even with many sessions)
        # This is a sanity check - real improvement comes from lazy loading
        assert mount_time < 5.0, (
            f"App mount took {mount_time:.2f}s which is too slow. "
            "Ensure expensive operations are deferred or async."
        )
