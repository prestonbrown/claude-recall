#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Unit tests for sparse handoff display placeholders in the TUI.

Phase 1 of the "Enrich Sparse Handoff Display" feature:
- "(no description)" when description is empty
- "(not yet enriched - press 'e' to extract context)" when no handoff context
- "(no sessions linked)" when sessions empty
- "Tried: none" instead of hiding the tried section

These are UNIT TESTS that test the display logic directly without running
the full TUI app. They capture what would be written to the display.

Tests are designed to FAIL initially (test-first development) because the
current implementation HIDES empty sections instead of showing placeholders.
"""

from typing import List
from unittest.mock import MagicMock, patch

import pytest


# ============================================================================
# Test Helper: Mock RichLog that captures writes
# ============================================================================


class MockRichLog:
    """Mock RichLog widget that captures all writes for testing."""

    def __init__(self):
        self.lines: List[str] = []

    def write(self, text: str) -> None:
        """Capture text that would be written to the log."""
        self.lines.append(text)

    def clear(self) -> None:
        """Clear captured lines."""
        self.lines = []

    def scroll_home(self) -> None:
        """No-op for mock."""
        pass

    def get_text(self) -> str:
        """Get all captured lines as a single string."""
        return "\n".join(self.lines)


# ============================================================================
# Test Helper: Create HandoffSummary objects
# ============================================================================


def create_sparse_handoff():
    """Create a sparse HandoffSummary with empty optional fields."""
    from core.tui.models import HandoffSummary

    return HandoffSummary(
        id="hf-sparse01",
        title="Sparse Handoff for Testing",
        status="in_progress",
        phase="implementing",
        created="2026-01-08",
        updated="2026-01-08",
        # Empty/default values for optional fields:
        project="",
        agent="user",
        description="",  # Empty - should show "(no description)"
        tried_steps=[],  # Empty - should show "Tried: none"
        next_steps=[],
        refs=[],
        checkpoint="",
        blocked_by=[],
        handoff=None,  # No context - should show "(not yet enriched...)"
    )


def create_rich_handoff():
    """Create a rich HandoffSummary with all fields populated."""
    from core.tui.models import HandoffContextSummary, HandoffSummary, TriedStep

    context = HandoffContextSummary(
        summary="Feature is 80% complete",
        critical_files=["core/app.py:42"],
        recent_changes=["Added new feature"],
        learnings=["Discovered edge case"],
        blockers=[],
        git_ref="abc1234def5678",
    )

    return HandoffSummary(
        id="hf-rich001",
        title="Rich Handoff with All Fields",
        status="in_progress",
        phase="implementing",
        created="2026-01-07",
        updated="2026-01-08",
        project="/Users/test/rich-project",
        agent="general-purpose",
        description="This handoff has a full description for testing.",
        tried_steps=[
            TriedStep(outcome="success", description="First attempt worked"),
            TriedStep(outcome="partial", description="Second attempt partially worked"),
        ],
        next_steps=["Complete remaining work"],
        refs=["core/app.py:42"],
        checkpoint="Making good progress",
        blocked_by=[],
        handoff=context,
    )


# ============================================================================
# Test Helper: Simulate _show_handoff_details
# ============================================================================


def simulate_show_handoff_details(handoff, sessions=None):
    """
    Simulate _show_handoff_details by calling the actual implementation
    with a mocked RichLog widget.

    Returns the MockRichLog with captured output.
    """
    if sessions is None:
        sessions = []

    mock_log = MockRichLog()

    # Import the app module to access the display logic
    # We need to mock the app's query_one and other methods
    from core.tui.app import RecallMonitorApp

    # Create a mock app instance
    app = MagicMock(spec=RecallMonitorApp)

    # Set up the handoff data
    app._handoff_data = {handoff.id: handoff}
    app._handoff_detail_sessions = []
    app._handoff_detail_blockers = []
    app._current_handoff_id = None

    # Mock query_one to return our mock log
    app.query_one.return_value = mock_log

    # Mock _get_sessions_for_handoff to return our sessions
    app._get_sessions_for_handoff.return_value = sessions

    # Mock call_after_refresh to be a no-op
    app.call_after_refresh = MagicMock()

    # Now call the actual method using the real implementation
    # We need to bind the method to our mock app
    RecallMonitorApp._show_handoff_details(app, handoff.id)

    return mock_log


# ============================================================================
# Tests for empty description placeholder
# ============================================================================


class TestEmptyDescriptionPlaceholder:
    """Tests for showing placeholder when description is empty."""

    def test_empty_description_shows_placeholder(self):
        """When description is empty, should show '(no description)' placeholder.

        NOTE: This test is expected to FAIL with current implementation
        because _show_handoff_details uses `if handoff.description:` which
        HIDES the section entirely instead of showing placeholder text.
        """
        handoff = create_sparse_handoff()
        mock_log = simulate_show_handoff_details(handoff)
        rendered_text = mock_log.get_text()

        # This SHOULD pass once we add placeholder text
        assert "(no description)" in rendered_text, (
            f"Expected '(no description)' placeholder in output when description is empty.\n"
            f"Got:\n{rendered_text}"
        )

    def test_populated_description_no_placeholder(self):
        """When description is populated, should NOT show placeholder."""
        handoff = create_rich_handoff()
        mock_log = simulate_show_handoff_details(handoff)
        rendered_text = mock_log.get_text()

        # The actual description should be shown
        assert "This handoff has a full description" in rendered_text, (
            f"Expected actual description in output.\n"
            f"Got:\n{rendered_text}"
        )
        # Placeholder should NOT appear
        assert "(no description)" not in rendered_text, (
            f"Should NOT show placeholder when description exists.\n"
            f"Got:\n{rendered_text}"
        )


# ============================================================================
# Tests for empty handoff context placeholder
# ============================================================================


class TestEmptyContextPlaceholder:
    """Tests for showing placeholder when handoff context is missing."""

    def test_empty_context_shows_enrich_placeholder(self):
        """When handoff context is missing, should show enrich prompt.

        NOTE: This test is expected to FAIL with current implementation
        because _show_handoff_details uses `if handoff.handoff:` which
        HIDES the context section entirely instead of showing placeholder.
        """
        handoff = create_sparse_handoff()
        mock_log = simulate_show_handoff_details(handoff)
        rendered_text = mock_log.get_text()

        expected_placeholder = "(not yet enriched - press 'e' to extract context)"
        assert expected_placeholder in rendered_text, (
            f"Expected '{expected_placeholder}' in output when context is missing.\n"
            f"Got:\n{rendered_text}"
        )

    def test_populated_context_no_enrich_placeholder(self):
        """When handoff context exists, should NOT show enrich placeholder."""
        handoff = create_rich_handoff()
        mock_log = simulate_show_handoff_details(handoff)
        rendered_text = mock_log.get_text()

        # Handoff Context section should be shown
        assert "Handoff Context" in rendered_text, (
            f"Expected 'Handoff Context' section in output.\n"
            f"Got:\n{rendered_text}"
        )
        # Enrich placeholder should NOT appear
        assert "not yet enriched" not in rendered_text, (
            f"Should NOT show enrich placeholder when context exists.\n"
            f"Got:\n{rendered_text}"
        )


# ============================================================================
# Tests for empty sessions placeholder
# ============================================================================


class TestEmptySessionsPlaceholder:
    """Tests for showing placeholder when no sessions are linked."""

    def test_empty_sessions_shows_placeholder(self):
        """When no sessions are linked, should show '(no sessions linked)' placeholder.

        NOTE: This test is expected to FAIL with current implementation
        because _show_handoff_details uses `if sessions:` which
        HIDES the sessions section entirely instead of showing placeholder.
        """
        handoff = create_sparse_handoff()
        # Pass empty sessions list
        mock_log = simulate_show_handoff_details(handoff, sessions=[])
        rendered_text = mock_log.get_text()

        assert "(no sessions linked)" in rendered_text, (
            f"Expected '(no sessions linked)' placeholder in output.\n"
            f"Got:\n{rendered_text}"
        )

    def test_populated_sessions_no_placeholder(self):
        """When sessions exist, should show sessions, not placeholder."""
        handoff = create_rich_handoff()
        mock_sessions = [
            {"session_id": "sess-001", "created": "2026-01-08T10:00:00Z"},
            {"session_id": "sess-002", "created": "2026-01-08T11:00:00Z"},
        ]
        mock_log = simulate_show_handoff_details(handoff, sessions=mock_sessions)
        rendered_text = mock_log.get_text()

        # Sessions section should be shown
        assert "Sessions (2)" in rendered_text, (
            f"Expected 'Sessions (2)' section in output.\n"
            f"Got:\n{rendered_text}"
        )
        # Placeholder should NOT appear
        assert "(no sessions linked)" not in rendered_text, (
            f"Should NOT show placeholder when sessions exist.\n"
            f"Got:\n{rendered_text}"
        )


# ============================================================================
# Tests for empty tried steps placeholder
# ============================================================================


class TestEmptyTriedStepsPlaceholder:
    """Tests for showing 'Tried: none' when no tried steps exist."""

    def test_empty_tried_shows_none_placeholder(self):
        """When no tried steps exist, should show 'Tried: none' instead of hiding.

        NOTE: This test is expected to FAIL with current implementation
        because _show_handoff_details uses `if handoff.tried_steps:` which
        HIDES the tried section entirely instead of showing "Tried: none".
        """
        handoff = create_sparse_handoff()
        mock_log = simulate_show_handoff_details(handoff)
        rendered_text = mock_log.get_text()

        assert "Tried: none" in rendered_text, (
            f"Expected 'Tried: none' placeholder in output.\n"
            f"Got:\n{rendered_text}"
        )

    def test_populated_tried_shows_steps(self):
        """When tried steps exist, should show the steps, not 'none' placeholder."""
        handoff = create_rich_handoff()
        mock_log = simulate_show_handoff_details(handoff)
        rendered_text = mock_log.get_text()

        # Tried section with count should be shown
        assert "Tried (2)" in rendered_text, (
            f"Expected 'Tried (2)' section in output.\n"
            f"Got:\n{rendered_text}"
        )
        # The "none" placeholder should NOT appear
        assert "Tried: none" not in rendered_text, (
            f"Should NOT show 'Tried: none' when steps exist.\n"
            f"Got:\n{rendered_text}"
        )


# ============================================================================
# Combined test for all placeholders on sparse handoff
# ============================================================================


class TestSparseHandoffAllPlaceholders:
    """Combined test verifying all placeholders appear together on sparse handoff."""

    def test_sparse_handoff_shows_all_placeholders(self):
        """A sparse handoff should show all relevant placeholders at once.

        NOTE: This test is expected to FAIL with current implementation
        because all empty sections are hidden rather than showing placeholders.
        """
        handoff = create_sparse_handoff()
        mock_log = simulate_show_handoff_details(handoff, sessions=[])
        rendered_text = mock_log.get_text()

        # All placeholders should be present
        placeholders = [
            ("(no description)", "empty description"),
            ("(not yet enriched - press 'e' to extract context)", "missing context"),
            ("(no sessions linked)", "no sessions"),
            ("Tried: none", "no tried steps"),
        ]

        missing = []
        for placeholder, desc in placeholders:
            if placeholder not in rendered_text:
                missing.append(f"'{placeholder}' ({desc})")

        assert not missing, (
            f"Missing placeholders: {', '.join(missing)}\n"
            f"Got:\n{rendered_text}"
        )


# ============================================================================
# Test that implementation SHOWS placeholders for empty sections
# ============================================================================


class TestCurrentImplementationHidesBehavior:
    """
    Tests verifying that placeholders are shown for empty sections.

    These tests verify the placeholder behavior implemented in Phase 1
    of the "Enrich Sparse Handoff Display" feature.
    """

    def test_current_hides_empty_description(self):
        """Empty description shows placeholder instead of hiding."""
        handoff = create_sparse_handoff()
        mock_log = simulate_show_handoff_details(handoff)
        rendered_text = mock_log.get_text()

        # Now shows placeholder when description is empty
        assert "(no description)" in rendered_text, (
            "Empty description should show placeholder"
        )

    def test_current_hides_empty_context(self):
        """Empty context shows enrich placeholder instead of hiding."""
        handoff = create_sparse_handoff()
        mock_log = simulate_show_handoff_details(handoff)
        rendered_text = mock_log.get_text()

        # Now shows enrich placeholder when handoff.handoff is None
        assert "(not yet enriched - press 'e' to extract context)" in rendered_text, (
            "Empty context should show enrich placeholder"
        )

    def test_current_hides_empty_sessions(self):
        """Empty sessions shows placeholder instead of hiding."""
        handoff = create_sparse_handoff()
        mock_log = simulate_show_handoff_details(handoff, sessions=[])
        rendered_text = mock_log.get_text()

        # Now shows placeholder when sessions is empty
        assert "(no sessions linked)" in rendered_text, (
            "Empty sessions should show placeholder"
        )

    def test_current_hides_empty_tried(self):
        """Empty tried steps shows placeholder instead of hiding."""
        handoff = create_sparse_handoff()
        mock_log = simulate_show_handoff_details(handoff)
        rendered_text = mock_log.get_text()

        # Now shows placeholder when tried_steps is empty
        assert "Tried: none" in rendered_text, (
            "Empty tried steps should show placeholder"
        )
