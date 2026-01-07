#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Tests for the TUI log reader module."""

import json
import pytest
from datetime import datetime, timezone
from pathlib import Path

from core.tui.log_reader import LogReader, parse_event, format_event_line
from core.tui.models import DebugEvent


# --- Fixtures ---


@pytest.fixture
def temp_log_dir(tmp_path: Path) -> Path:
    """Create a temporary directory for log files."""
    return tmp_path


@pytest.fixture
def sample_session_start_event() -> dict:
    """Sample session_start event data."""
    return {
        "event": "session_start",
        "level": "info",
        "timestamp": "2025-01-05T10:30:00Z",
        "session_id": "sess-abc123",
        "pid": 12345,
        "project": "test-project",
        "total_lessons": 10,
        "system_count": 3,
        "project_count": 7,
    }


@pytest.fixture
def sample_citation_event() -> dict:
    """Sample citation event data."""
    return {
        "event": "citation",
        "level": "info",
        "timestamp": "2025-01-05T10:31:00Z",
        "session_id": "sess-abc123",
        "pid": 12345,
        "project": "test-project",
        "lesson_id": "L001",
        "uses_before": 5,
        "uses_after": 6,
        "promotion_ready": False,
    }


@pytest.fixture
def sample_error_event() -> dict:
    """Sample error event data."""
    return {
        "event": "error",
        "level": "error",
        "timestamp": "2025-01-05T10:32:00Z",
        "session_id": "sess-abc123",
        "pid": 12345,
        "project": "test-project",
        "op": "parse_lesson",
        "err": "Invalid JSON in LESSONS.md",
    }


@pytest.fixture
def sample_log_file(temp_log_dir: Path, sample_session_start_event, sample_citation_event) -> Path:
    """Create a sample log file with test events."""
    log_path = temp_log_dir / "debug.log"
    events = [sample_session_start_event, sample_citation_event]
    lines = [json.dumps(e) for e in events]
    log_path.write_text("\n".join(lines) + "\n")
    return log_path


# --- Tests for parse_event ---


class TestParseEvent:
    """Tests for the parse_event function."""

    def test_parse_event_valid_json(self, sample_session_start_event):
        """Parse a valid JSON log line."""
        line = json.dumps(sample_session_start_event)
        event = parse_event(line)

        assert event is not None
        assert event.event == "session_start"
        assert event.level == "info"
        assert event.timestamp == "2025-01-05T10:30:00Z"
        assert event.session_id == "sess-abc123"
        assert event.pid == 12345
        assert event.project == "test-project"
        assert event.raw == sample_session_start_event

    def test_parse_event_invalid_json(self):
        """Return None for invalid JSON."""
        event = parse_event("not valid json {")
        assert event is None

    def test_parse_event_empty_line(self):
        """Return None for empty line."""
        assert parse_event("") is None
        assert parse_event("   ") is None
        assert parse_event("\n") is None

    def test_parse_event_missing_fields_uses_defaults(self):
        """Parse event with missing fields uses sensible defaults."""
        minimal = {"event": "custom"}
        line = json.dumps(minimal)
        event = parse_event(line)

        assert event is not None
        assert event.event == "custom"
        assert event.level == "info"  # default
        assert event.timestamp == ""  # default
        assert event.session_id == ""  # default
        assert event.pid == 0  # default
        assert event.project == ""  # default

    def test_parse_event_preserves_raw_data(self, sample_citation_event):
        """Parse event preserves all raw data including extra fields."""
        line = json.dumps(sample_citation_event)
        event = parse_event(line)

        assert event is not None
        assert event.raw.get("lesson_id") == "L001"
        assert event.raw.get("uses_before") == 5
        assert event.raw.get("uses_after") == 6
        assert event.raw.get("promotion_ready") is False


# --- Tests for LogReader ---


class TestLogReader:
    """Tests for the LogReader class."""

    def test_load_buffer(self, sample_log_file: Path):
        """Load events from a test log file."""
        reader = LogReader(log_path=sample_log_file)
        count = reader.load_buffer()

        assert count == 2
        assert reader.buffer_size == 2

    def test_load_buffer_nonexistent_file(self, temp_log_dir: Path):
        """Load from nonexistent file returns 0."""
        nonexistent = temp_log_dir / "nonexistent.log"
        reader = LogReader(log_path=nonexistent)
        count = reader.load_buffer()

        assert count == 0
        assert reader.buffer_size == 0

    def test_filter_by_project(self, temp_log_dir: Path):
        """Filter events by project name."""
        log_path = temp_log_dir / "debug.log"
        events = [
            {"event": "test", "level": "info", "timestamp": "", "session_id": "", "pid": 0, "project": "project-a"},
            {"event": "test", "level": "info", "timestamp": "", "session_id": "", "pid": 0, "project": "project-b"},
            {"event": "test", "level": "info", "timestamp": "", "session_id": "", "pid": 0, "project": "Project-A"},  # Case test
        ]
        log_path.write_text("\n".join(json.dumps(e) for e in events) + "\n")

        reader = LogReader(log_path=log_path)
        filtered = reader.filter_by_project("project-a")

        # Case-insensitive match
        assert len(filtered) == 2

    def test_filter_by_session(self, temp_log_dir: Path):
        """Filter events by session ID."""
        log_path = temp_log_dir / "debug.log"
        events = [
            {"event": "test", "level": "info", "timestamp": "", "session_id": "sess-1", "pid": 0, "project": ""},
            {"event": "test", "level": "info", "timestamp": "", "session_id": "sess-2", "pid": 0, "project": ""},
            {"event": "test", "level": "info", "timestamp": "", "session_id": "sess-1", "pid": 0, "project": ""},
        ]
        log_path.write_text("\n".join(json.dumps(e) for e in events) + "\n")

        reader = LogReader(log_path=log_path)
        filtered = reader.filter_by_session("sess-1")

        assert len(filtered) == 2
        assert all(e.session_id == "sess-1" for e in filtered)

    def test_filter_by_event_type(self, temp_log_dir: Path):
        """Filter events by event type."""
        log_path = temp_log_dir / "debug.log"
        events = [
            {"event": "session_start", "level": "info", "timestamp": "", "session_id": "", "pid": 0, "project": ""},
            {"event": "citation", "level": "info", "timestamp": "", "session_id": "", "pid": 0, "project": ""},
            {"event": "citation", "level": "info", "timestamp": "", "session_id": "", "pid": 0, "project": ""},
        ]
        log_path.write_text("\n".join(json.dumps(e) for e in events) + "\n")

        reader = LogReader(log_path=log_path)
        filtered = reader.filter_by_event_type("citation")

        assert len(filtered) == 2
        assert all(e.event == "citation" for e in filtered)

    def test_filter_by_level(self, temp_log_dir: Path):
        """Filter events by log level."""
        log_path = temp_log_dir / "debug.log"
        events = [
            {"event": "test", "level": "info", "timestamp": "", "session_id": "", "pid": 0, "project": ""},
            {"event": "test", "level": "error", "timestamp": "", "session_id": "", "pid": 0, "project": ""},
            {"event": "test", "level": "debug", "timestamp": "", "session_id": "", "pid": 0, "project": ""},
        ]
        log_path.write_text("\n".join(json.dumps(e) for e in events) + "\n")

        reader = LogReader(log_path=log_path)
        filtered = reader.filter_by_level("error")

        assert len(filtered) == 1
        assert filtered[0].level == "error"

    def test_combined_filter(self, temp_log_dir: Path):
        """Filter events by multiple criteria."""
        log_path = temp_log_dir / "debug.log"
        events = [
            {"event": "citation", "level": "info", "timestamp": "", "session_id": "sess-1", "pid": 0, "project": "proj-a"},
            {"event": "citation", "level": "info", "timestamp": "", "session_id": "sess-2", "pid": 0, "project": "proj-a"},
            {"event": "error", "level": "error", "timestamp": "", "session_id": "sess-1", "pid": 0, "project": "proj-a"},
            {"event": "citation", "level": "info", "timestamp": "", "session_id": "sess-1", "pid": 0, "project": "proj-b"},
        ]
        log_path.write_text("\n".join(json.dumps(e) for e in events) + "\n")

        reader = LogReader(log_path=log_path)
        filtered = reader.filter(project="proj-a", session_id="sess-1", event_type="citation")

        assert len(filtered) == 1
        assert filtered[0].project == "proj-a"
        assert filtered[0].session_id == "sess-1"
        assert filtered[0].event == "citation"

    def test_read_recent(self, temp_log_dir: Path):
        """Read most recent N events."""
        log_path = temp_log_dir / "debug.log"
        events = [
            {"event": f"event-{i}", "level": "info", "timestamp": "", "session_id": "", "pid": 0, "project": ""}
            for i in range(10)
        ]
        log_path.write_text("\n".join(json.dumps(e) for e in events) + "\n")

        reader = LogReader(log_path=log_path)
        recent = reader.read_recent(3)

        assert len(recent) == 3
        assert recent[0].event == "event-7"
        assert recent[1].event == "event-8"
        assert recent[2].event == "event-9"

    def test_get_sessions(self, temp_log_dir: Path):
        """Get unique session IDs."""
        log_path = temp_log_dir / "debug.log"
        events = [
            {"event": "test", "level": "info", "timestamp": "", "session_id": "sess-1", "pid": 0, "project": ""},
            {"event": "test", "level": "info", "timestamp": "", "session_id": "sess-2", "pid": 0, "project": ""},
            {"event": "test", "level": "info", "timestamp": "", "session_id": "sess-1", "pid": 0, "project": ""},
            {"event": "test", "level": "info", "timestamp": "", "session_id": "sess-3", "pid": 0, "project": ""},
        ]
        log_path.write_text("\n".join(json.dumps(e) for e in events) + "\n")

        reader = LogReader(log_path=log_path)
        sessions = reader.get_sessions()

        assert len(sessions) == 3
        # Most recent first
        assert sessions[0] == "sess-3"

    def test_get_projects(self, temp_log_dir: Path):
        """Get unique project names sorted by frequency."""
        log_path = temp_log_dir / "debug.log"
        events = [
            {"event": "test", "level": "info", "timestamp": "", "session_id": "", "pid": 0, "project": "proj-a"},
            {"event": "test", "level": "info", "timestamp": "", "session_id": "", "pid": 0, "project": "proj-b"},
            {"event": "test", "level": "info", "timestamp": "", "session_id": "", "pid": 0, "project": "proj-a"},
            {"event": "test", "level": "info", "timestamp": "", "session_id": "", "pid": 0, "project": "proj-a"},
        ]
        log_path.write_text("\n".join(json.dumps(e) for e in events) + "\n")

        reader = LogReader(log_path=log_path)
        projects = reader.get_projects()

        assert len(projects) == 2
        # Most frequent first
        assert projects[0] == "proj-a"
        assert projects[1] == "proj-b"

    def test_clear_buffer(self, sample_log_file: Path):
        """Clear the event buffer."""
        reader = LogReader(log_path=sample_log_file)
        reader.load_buffer()
        assert reader.buffer_size > 0

        reader.clear_buffer()
        assert reader.buffer_size == 0

    def test_max_buffer_size(self, temp_log_dir: Path):
        """Buffer respects max size limit."""
        log_path = temp_log_dir / "debug.log"
        events = [
            {"event": f"event-{i}", "level": "info", "timestamp": "", "session_id": "", "pid": 0, "project": ""}
            for i in range(100)
        ]
        log_path.write_text("\n".join(json.dumps(e) for e in events) + "\n")

        reader = LogReader(log_path=log_path, max_buffer=10)
        reader.load_buffer()

        assert reader.buffer_size == 10
        # Should have most recent events
        all_events = reader.read_all()
        assert all_events[0].event == "event-90"
        assert all_events[-1].event == "event-99"

    def test_incremental_loading(self, temp_log_dir: Path):
        """Incremental loading reads new events only."""
        log_path = temp_log_dir / "debug.log"

        # Initial events
        events1 = [
            {"event": "event-1", "level": "info", "timestamp": "", "session_id": "", "pid": 0, "project": ""}
        ]
        log_path.write_text(json.dumps(events1[0]) + "\n")

        reader = LogReader(log_path=log_path)
        count1 = reader.load_buffer()
        assert count1 == 1

        # Append more events
        with open(log_path, "a") as f:
            f.write(json.dumps({"event": "event-2", "level": "info", "timestamp": "", "session_id": "", "pid": 0, "project": ""}) + "\n")

        count2 = reader.load_buffer()
        assert count2 == 1  # Only new event
        assert reader.buffer_size == 2

    def test_new_events_at_buffer_tail(self, temp_log_dir: Path):
        """New events are appended at the end of the buffer."""
        log_path = temp_log_dir / "debug.log"

        # Write initial events
        initial_events = [
            {"event": "initial-1", "level": "info", "timestamp": "", "session_id": "", "pid": 0, "project": ""},
            {"event": "initial-2", "level": "info", "timestamp": "", "session_id": "", "pid": 0, "project": ""},
            {"event": "initial-3", "level": "info", "timestamp": "", "session_id": "", "pid": 0, "project": ""},
        ]
        log_path.write_text("\n".join(json.dumps(e) for e in initial_events) + "\n")

        reader = LogReader(log_path=log_path)
        reader.load_buffer()
        initial_tail = list(reader._buffer)[-1].event

        # Add new events
        with open(log_path, "a") as f:
            f.write(json.dumps({"event": "new-1", "level": "info", "timestamp": "", "session_id": "", "pid": 0, "project": ""}) + "\n")
            f.write(json.dumps({"event": "new-2", "level": "info", "timestamp": "", "session_id": "", "pid": 0, "project": ""}) + "\n")

        new_count = reader.load_buffer()
        assert new_count == 2

        # New events should be at the tail
        buffer = list(reader._buffer)
        assert buffer[-1].event == "new-2"
        assert buffer[-2].event == "new-1"
        assert buffer[-3].event == "initial-3"

    def test_buffer_slice_gets_new_events(self, temp_log_dir: Path):
        """Slicing buffer[-count:] after load_buffer() returns exactly the new events."""
        log_path = temp_log_dir / "debug.log"

        # Write initial events
        initial_events = [
            {"event": f"old-{i}", "level": "info", "timestamp": "", "session_id": "", "pid": 0, "project": ""}
            for i in range(5)
        ]
        log_path.write_text("\n".join(json.dumps(e) for e in initial_events) + "\n")

        reader = LogReader(log_path=log_path)
        reader.load_buffer()

        # Add new events with distinct marker
        with open(log_path, "a") as f:
            for i in range(3):
                f.write(json.dumps({"event": f"NEW-{i}", "level": "info", "timestamp": "", "session_id": "", "pid": 0, "project": ""}) + "\n")

        new_count = reader.load_buffer()
        assert new_count == 3

        # Slice should get exactly the new events
        buffer = list(reader._buffer)
        sliced = buffer[-new_count:]
        assert len(sliced) == 3
        assert sliced[0].event == "NEW-0"
        assert sliced[1].event == "NEW-1"
        assert sliced[2].event == "NEW-2"

    def test_buffer_slice_with_rotation(self, temp_log_dir: Path):
        """Buffer slicing works correctly even when buffer is at capacity."""
        log_path = temp_log_dir / "debug.log"

        # Fill buffer to capacity (using small max for test)
        initial_events = [
            {"event": f"old-{i}", "level": "info", "timestamp": "", "session_id": "", "pid": 0, "project": ""}
            for i in range(10)
        ]
        log_path.write_text("\n".join(json.dumps(e) for e in initial_events) + "\n")

        reader = LogReader(log_path=log_path, max_buffer=10)
        reader.load_buffer()
        assert reader.buffer_size == 10

        # Add new events (will push out old ones)
        with open(log_path, "a") as f:
            for i in range(3):
                f.write(json.dumps({"event": f"NEW-{i}", "level": "info", "timestamp": "", "session_id": "", "pid": 0, "project": ""}) + "\n")

        new_count = reader.load_buffer()
        assert new_count == 3
        assert reader.buffer_size == 10  # Still at capacity

        # Slice should still get the new events
        buffer = list(reader._buffer)
        sliced = buffer[-new_count:]
        assert len(sliced) == 3
        assert sliced[0].event == "NEW-0"
        assert sliced[1].event == "NEW-1"
        assert sliced[2].event == "NEW-2"


# --- Tests for format_event_line ---


class TestFormatEventLine:
    """Tests for the format_event_line function."""

    def test_format_event_line_session_start(self, sample_session_start_event):
        """Format session_start event."""
        event = parse_event(json.dumps(sample_session_start_event))
        line = format_event_line(event, color=False)

        assert "10:30:00" in line
        assert "session_start" in line
        assert "test-project" in line
        assert "3S/7L" in line
        assert "10 total" in line

    def test_format_event_line_citation(self, sample_citation_event):
        """Format citation event."""
        event = parse_event(json.dumps(sample_citation_event))
        line = format_event_line(event, color=False)

        assert "10:31:00" in line
        assert "citation" in line
        assert "L001" in line
        assert "5" in line  # uses_before
        assert "6" in line  # uses_after

    def test_format_event_line_error(self, sample_error_event):
        """Format error event."""
        event = parse_event(json.dumps(sample_error_event))
        line = format_event_line(event, color=False)

        assert "10:32:00" in line
        assert "error" in line
        assert "parse_lesson" in line
        assert "Invalid JSON" in line

    def test_format_event_line_with_color(self, sample_citation_event):
        """Format event with ANSI color codes."""
        event = parse_event(json.dumps(sample_citation_event))
        line = format_event_line(event, color=True)

        # Should contain ANSI escape codes
        assert "\033[" in line
        assert "\033[0m" in line  # Reset code

    def test_format_event_line_hook_end(self):
        """Format hook_end event with timing."""
        event_data = {
            "event": "hook_end",
            "level": "info",
            "timestamp": "2025-01-05T10:35:00Z",
            "session_id": "sess-xyz",
            "pid": 12345,
            "project": "test-project",
            "hook": "SessionStart",
            "total_ms": 42.5,
        }
        event = parse_event(json.dumps(event_data))
        line = format_event_line(event, color=False)

        assert "hook_end" in line
        assert "SessionStart" in line
        assert "42ms" in line or "43ms" in line  # Rounded

    def test_format_event_line_handoff_created(self):
        """Format handoff_created event."""
        event_data = {
            "event": "handoff_created",
            "level": "info",
            "timestamp": "2025-01-05T10:36:00Z",
            "session_id": "sess-xyz",
            "pid": 12345,
            "project": "test-project",
            "handoff_id": "hf-abc123",
            "title": "Implement new feature",
        }
        event = parse_event(json.dumps(event_data))
        line = format_event_line(event, color=False)

        assert "handoff_created" in line
        assert "hf-abc123" in line
        assert "Implement new feature" in line

    def test_format_event_line_decay_result(self):
        """Format decay_result event."""
        event_data = {
            "event": "decay_result",
            "level": "info",
            "timestamp": "2025-01-05T10:37:00Z",
            "session_id": "sess-xyz",
            "pid": 12345,
            "project": "test-project",
            "decayed_uses": 5,
            "decayed_velocity": 3,
        }
        event = parse_event(json.dumps(event_data))
        line = format_event_line(event, color=False)

        assert "decay_result" in line
        assert "5 uses" in line
        assert "3 velocity" in line

    def test_format_event_line_hook_phase(self):
        """Format hook_phase event shows hook.phase: duration."""
        event_data = {
            "event": "hook_phase",
            "level": "debug",
            "timestamp": "2025-01-05T10:35:30Z",
            "session_id": "sess-xyz",
            "pid": 12345,
            "project": "test-project",
            "hook": "stop",
            "phase": "process_lessons",
            "ms": 42.5,
        }
        event = parse_event(json.dumps(event_data))
        line = format_event_line(event, color=False)

        assert "hook_phase" in line
        assert "stop.process_lessons" in line
        assert "42ms" in line or "43ms" in line  # Rounded

    def test_format_event_line_generic_event(self):
        """Format generic event shows first interesting key."""
        event_data = {
            "event": "custom_event",
            "level": "info",
            "timestamp": "2025-01-05T10:38:00Z",
            "session_id": "sess-xyz",
            "pid": 12345,
            "project": "test-project",
            "custom_field": "custom_value",
        }
        event = parse_event(json.dumps(event_data))
        line = format_event_line(event, color=False)

        assert "custom_event" in line
        assert "custom_field=custom_value" in line
