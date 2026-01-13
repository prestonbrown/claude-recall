#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Tests for shared TUI formatting utilities."""

import platform
import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from core.tui.models import DebugEvent


class TestGetTimeFormat:
    """Tests for the _get_time_format function."""

    def test_get_time_format_returns_string(self):
        """Should return a format string."""
        from core.tui.formatting import _get_time_format

        result = _get_time_format()
        assert isinstance(result, str)
        # Should be a valid strftime format string
        assert "%" in result

    def test_get_time_format_non_darwin_returns_locale(self):
        """On non-Darwin platforms, should return %X (locale-dependent)."""
        from core.tui.formatting import _get_time_format

        # Clear the cache before testing
        _get_time_format.cache_clear()

        with patch("platform.system", return_value="Linux"):
            result = _get_time_format()
            assert result == "%X"

        _get_time_format.cache_clear()

    def test_get_time_format_darwin_24h(self):
        """On Darwin with 24h preference, should return %H:%M:%S."""
        from core.tui.formatting import _get_time_format

        _get_time_format.cache_clear()

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "1\n"

        with patch("platform.system", return_value="Darwin"):
            with patch("subprocess.run", return_value=mock_result):
                result = _get_time_format()
                assert result == "%H:%M:%S"

        _get_time_format.cache_clear()

    def test_get_time_format_darwin_12h(self):
        """On Darwin with 12h preference, should return %r."""
        from core.tui.formatting import _get_time_format

        _get_time_format.cache_clear()

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "0\n"

        with patch("platform.system", return_value="Darwin"):
            with patch("subprocess.run", return_value=mock_result):
                result = _get_time_format()
                assert result == "%r"

        _get_time_format.cache_clear()

    def test_get_time_format_darwin_default_fallback(self):
        """On Darwin with subprocess error, should fallback to %r."""
        from core.tui.formatting import _get_time_format

        _get_time_format.cache_clear()

        with patch("platform.system", return_value="Darwin"):
            with patch("subprocess.run", side_effect=FileNotFoundError):
                result = _get_time_format()
                assert result == "%r"

        _get_time_format.cache_clear()


class TestFormatEventTime:
    """Tests for the _format_event_time function."""

    def test_format_event_time_with_valid_timestamp(self):
        """Should format a valid timestamp correctly."""
        from core.tui.formatting import _format_event_time

        event = DebugEvent(
            event="test",
            level="info",
            timestamp="2025-01-05T10:30:45Z",
            session_id="sess-123",
            pid=12345,
            project="test-project",
            raw={},
        )

        result = _format_event_time(event)
        assert isinstance(result, str)
        # Should contain time components (hour, minute, second pattern)
        assert ":" in result

    def test_format_event_time_fallback_for_invalid_timestamp(self):
        """Should fallback gracefully for events with unparseable timestamps."""
        from core.tui.formatting import _format_event_time

        event = DebugEvent(
            event="test",
            level="info",
            timestamp="2025-01-05T10:30:45Z",
            session_id="sess-123",
            pid=12345,
            project="test-project",
            raw={},
        )
        # Override timestamp_dt to None to simulate parse failure
        object.__setattr__(event, "_timestamp_dt", None)

        # Create event without parseable timestamp
        event2 = DebugEvent(
            event="test",
            level="info",
            timestamp="invalid-timestamp",
            session_id="sess-123",
            pid=12345,
            project="test-project",
            raw={},
        )

        result = _format_event_time(event2)
        assert isinstance(result, str)
        # Should return some portion of the raw timestamp
        assert len(result) <= 8

    def test_format_event_time_extracts_time_from_iso(self):
        """Should extract time from ISO format timestamp in fallback."""
        from core.tui.formatting import _format_event_time

        # Create an event and force fallback by making timestamp_dt None
        event = DebugEvent(
            event="test",
            level="info",
            timestamp="2025-01-05T14:30:45Z",
            session_id="sess-123",
            pid=12345,
            project="test-project",
            raw={},
        )

        result = _format_event_time(event)
        # Result should be a time string (format depends on locale/preferences)
        assert isinstance(result, str)
        assert len(result) >= 5  # At least HH:MM


class TestEventTypeColors:
    """Tests for the EVENT_TYPE_COLORS mapping."""

    def test_event_colors_has_all_types(self):
        """Should have entries for all expected event types."""
        from core.tui.formatting import EVENT_TYPE_COLORS

        expected_types = [
            "session_start",
            "citation",
            "error",
            "decay_result",
            "handoff_created",
            "handoff_change",
            "handoff_completed",
            "timing",
            "hook_start",
            "hook_end",
            "hook_phase",
            "lesson_added",
        ]

        for event_type in expected_types:
            assert event_type in EVENT_TYPE_COLORS, f"Missing color for: {event_type}"

    def test_event_colors_values_are_strings(self):
        """All color values should be strings (color names or Rich markup)."""
        from core.tui.formatting import EVENT_TYPE_COLORS

        for event_type, color in EVENT_TYPE_COLORS.items():
            assert isinstance(color, str), f"Color for {event_type} is not a string"
            assert len(color) > 0, f"Color for {event_type} is empty"

    def test_event_colors_values_are_semantic(self):
        """Colors should be semantic names, not ANSI codes."""
        from core.tui.formatting import EVENT_TYPE_COLORS

        for event_type, color in EVENT_TYPE_COLORS.items():
            # Should not contain ANSI escape sequences
            assert "\033[" not in color, f"Color for {event_type} contains ANSI codes"
            # Should be readable color names
            assert color.replace("_", "").replace(" ", "").isalpha() or color in [
                "bold red",
                "bright_green",
            ], f"Color for {event_type} is not semantic: {color}"


class TestAnsiColors:
    """Tests for the ANSI_COLORS mapping (for terminal output)."""

    def test_ansi_colors_has_all_types(self):
        """Should have entries for all expected event types."""
        from core.tui.formatting import ANSI_COLORS

        expected_types = [
            "session_start",
            "citation",
            "error",
            "decay_result",
            "handoff_created",
            "handoff_change",
            "handoff_completed",
            "timing",
            "hook_start",
            "hook_end",
            "hook_phase",
            "lesson_added",
            "reset",
        ]

        for event_type in expected_types:
            assert event_type in ANSI_COLORS, f"Missing ANSI color for: {event_type}"

    def test_ansi_colors_contain_escape_sequences(self):
        """ANSI colors should contain escape sequences."""
        from core.tui.formatting import ANSI_COLORS

        for event_type, code in ANSI_COLORS.items():
            assert "\033[" in code, f"ANSI code for {event_type} missing escape sequence"

    def test_ansi_colors_reset_code(self):
        """Reset code should reset formatting."""
        from core.tui.formatting import ANSI_COLORS

        assert ANSI_COLORS["reset"] == "\033[0m"


class TestExtractEventDetails:
    """Tests for extract_event_details function - consolidates event detail extraction."""

    def test_extract_session_start_details(self):
        """Given event with session_start, extracts total_lessons, system_count, project_count."""
        from core.tui.formatting import extract_event_details

        event = DebugEvent(
            event="session_start",
            level="info",
            timestamp="2025-01-05T10:30:45Z",
            session_id="sess-123",
            pid=12345,
            project="test-project",
            raw={
                "total_lessons": 25,
                "system_count": 10,
                "project_count": 15,
            },
        )

        result = extract_event_details(event)

        assert result["total"] == "25"
        assert result["system_count"] == "10"
        assert result["project_count"] == "15"

    def test_extract_session_start_with_defaults(self):
        """Session start with missing fields uses defaults."""
        from core.tui.formatting import extract_event_details

        event = DebugEvent(
            event="session_start",
            level="info",
            timestamp="2025-01-05T10:30:45Z",
            session_id="sess-123",
            pid=12345,
            project="test-project",
            raw={},
        )

        result = extract_event_details(event)

        assert result["total"] == "0"
        assert result["system_count"] == "0"
        assert result["project_count"] == "0"

    def test_extract_citation_details(self):
        """Given citation event, extracts lesson_id, uses_before, uses_after, promotion_ready."""
        from core.tui.formatting import extract_event_details

        event = DebugEvent(
            event="citation",
            level="info",
            timestamp="2025-01-05T10:30:45Z",
            session_id="sess-123",
            pid=12345,
            project="test-project",
            raw={
                "lesson_id": "L001",
                "uses_before": 5,
                "uses_after": 6,
                "promotion_ready": False,
            },
        )

        result = extract_event_details(event)

        assert result["lesson_id"] == "L001"
        assert result["uses_before"] == "5"
        assert result["uses_after"] == "6"
        assert "promo" not in result

    def test_extract_citation_with_promotion(self):
        """Citation with promotion_ready flag includes promo marker."""
        from core.tui.formatting import extract_event_details

        event = DebugEvent(
            event="citation",
            level="info",
            timestamp="2025-01-05T10:30:45Z",
            session_id="sess-123",
            pid=12345,
            project="test-project",
            raw={
                "lesson_id": "L001",
                "uses_before": 49,
                "uses_after": 50,
                "promotion_ready": True,
            },
        )

        result = extract_event_details(event)

        assert result["promo"] == "PROMO!"

    def test_extract_lesson_added_details(self):
        """Given lesson_added event, extracts lesson_id, level."""
        from core.tui.formatting import extract_event_details

        event = DebugEvent(
            event="lesson_added",
            level="info",
            timestamp="2025-01-05T10:30:45Z",
            session_id="sess-123",
            pid=12345,
            project="test-project",
            raw={
                "lesson_id": "L005",
                "lesson_level": "project",
                "title": "My Lesson Title",
            },
        )

        result = extract_event_details(event)

        assert result["lesson_id"] == "L005"
        assert result["level"] == "project"

    def test_extract_error_details(self):
        """Given error event, extracts op and err message."""
        from core.tui.formatting import extract_event_details

        event = DebugEvent(
            event="error",
            level="error",
            timestamp="2025-01-05T10:30:45Z",
            session_id="sess-123",
            pid=12345,
            project="test-project",
            raw={
                "op": "parse_lessons",
                "err": "Invalid markdown format",
            },
        )

        result = extract_event_details(event)

        assert result["op"] == "parse_lessons"
        assert result["err"] == "Invalid markdown format"

    def test_extract_error_truncates_long_message(self):
        """Error messages are truncated to 50 chars."""
        from core.tui.formatting import extract_event_details

        long_error = "A" * 100

        event = DebugEvent(
            event="error",
            level="error",
            timestamp="2025-01-05T10:30:45Z",
            session_id="sess-123",
            pid=12345,
            project="test-project",
            raw={
                "op": "test",
                "err": long_error,
            },
        )

        result = extract_event_details(event)

        assert len(result["err"]) == 50

    def test_extract_decay_result_details(self):
        """Given decay_result event, extracts decayed uses and velocity."""
        from core.tui.formatting import extract_event_details

        event = DebugEvent(
            event="decay_result",
            level="info",
            timestamp="2025-01-05T10:30:45Z",
            session_id="sess-123",
            pid=12345,
            project="test-project",
            raw={
                "decayed_uses": 15,
                "decayed_velocity": 8,
            },
        )

        result = extract_event_details(event)

        assert result["decayed_uses"] == "15"
        assert result["decayed_velocity"] == "8"

    def test_extract_hook_end_details(self):
        """Given hook_end event, extracts hook name and total_ms."""
        from core.tui.formatting import extract_event_details

        event = DebugEvent(
            event="hook_end",
            level="info",
            timestamp="2025-01-05T10:30:45Z",
            session_id="sess-123",
            pid=12345,
            project="test-project",
            raw={
                "hook": "SessionStart",
                "total_ms": 45.5,
            },
        )

        result = extract_event_details(event)

        assert result["hook"] == "SessionStart"
        assert result["total_ms"] == "45.5"

    def test_extract_hook_phase_details(self):
        """Given hook_phase event, extracts hook, phase, and ms."""
        from core.tui.formatting import extract_event_details

        event = DebugEvent(
            event="hook_phase",
            level="info",
            timestamp="2025-01-05T10:30:45Z",
            session_id="sess-123",
            pid=12345,
            project="test-project",
            raw={
                "hook": "SessionStart",
                "phase": "inject",
                "ms": 12.3,
            },
        )

        result = extract_event_details(event)

        assert result["hook"] == "SessionStart"
        assert result["phase"] == "inject"
        assert result["ms"] == "12.3"

    def test_extract_handoff_created_details(self):
        """Given handoff_created event, extracts id and title."""
        from core.tui.formatting import extract_event_details

        event = DebugEvent(
            event="handoff_created",
            level="info",
            timestamp="2025-01-05T10:30:45Z",
            session_id="sess-123",
            pid=12345,
            project="test-project",
            raw={
                "handoff_id": "hf-abc123",
                "title": "Implement new feature",
            },
        )

        result = extract_event_details(event)

        assert result["handoff_id"] == "hf-abc123"
        assert result["title"] == "Implement new feature"

    def test_extract_handoff_created_truncates_long_title(self):
        """Handoff title is truncated to 30 chars."""
        from core.tui.formatting import extract_event_details

        long_title = "A" * 50

        event = DebugEvent(
            event="handoff_created",
            level="info",
            timestamp="2025-01-05T10:30:45Z",
            session_id="sess-123",
            pid=12345,
            project="test-project",
            raw={
                "handoff_id": "hf-abc123",
                "title": long_title,
            },
        )

        result = extract_event_details(event)

        assert len(result["title"]) == 30

    def test_extract_handoff_completed_details(self):
        """Given handoff_completed event, extracts id and tried_count."""
        from core.tui.formatting import extract_event_details

        event = DebugEvent(
            event="handoff_completed",
            level="info",
            timestamp="2025-01-05T10:30:45Z",
            session_id="sess-123",
            pid=12345,
            project="test-project",
            raw={
                "handoff_id": "hf-xyz789",
                "tried_count": 5,
            },
        )

        result = extract_event_details(event)

        assert result["handoff_id"] == "hf-xyz789"
        assert result["tried_count"] == "5"

    def test_extract_unknown_event_returns_empty(self):
        """Unknown event types return empty dict."""
        from core.tui.formatting import extract_event_details

        event = DebugEvent(
            event="some_future_event_type",
            level="info",
            timestamp="2025-01-05T10:30:45Z",
            session_id="sess-123",
            pid=12345,
            project="test-project",
            raw={"some_field": "some_value"},
        )

        result = extract_event_details(event)

        assert result == {}
