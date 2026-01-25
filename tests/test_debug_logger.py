#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Test suite for debug logger.

Run with: pytest tests/test_debug_logger.py -v
"""

import json
import os
import pytest
from pathlib import Path

from core.debug_logger import (
    CLAUDE_RECALL_CONFIG_PATH,
    DebugLogger,
    get_logger,
    reset_logger,
    _get_debug_level,
    _get_session_id,
    _read_settings_debug_level,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def temp_lessons_base(tmp_path: Path) -> Path:
    """Create a temporary lessons base directory."""
    lessons_base = tmp_path / ".config" / "claude-recall"
    lessons_base.mkdir(parents=True)
    return lessons_base


@pytest.fixture
def temp_state_dir(tmp_path: Path) -> Path:
    """Create a temporary state directory for logs."""
    state_dir = tmp_path / ".local" / "state" / "claude-recall"
    state_dir.mkdir(parents=True)
    return state_dir


@pytest.fixture(autouse=True)
def reset_logger_state():
    """Reset the global logger before each test."""
    reset_logger()
    yield
    reset_logger()


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Clean up environment variables after each test."""
    monkeypatch.delenv("CLAUDE_RECALL_DEBUG", raising=False)
    monkeypatch.delenv("CLAUDE_RECALL_BASE", raising=False)
    monkeypatch.delenv("CLAUDE_RECALL_STATE", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    # Also clean legacy env vars for backward compat
    monkeypatch.delenv("LESSONS_DEBUG", raising=False)
    monkeypatch.delenv("LESSONS_BASE", raising=False)


# =============================================================================
# Tests: Level Configuration
# =============================================================================


class TestDebugLevel:
    """Test debug level parsing."""

    @pytest.fixture
    def no_settings_file(self, tmp_path: Path, monkeypatch):
        """Patch CLAUDE_RECALL_CONFIG_PATH to non-existent file for isolation."""
        import core.debug_logger as dl
        fake_path = tmp_path / ".config" / "claude-recall" / "config.json"
        monkeypatch.setattr(dl, "CLAUDE_RECALL_CONFIG_PATH", fake_path)
        return fake_path

    def test_enabled_by_default(self, monkeypatch, no_settings_file):
        """Logger should be enabled (level 1) when CLAUDE_RECALL_DEBUG is not set."""
        monkeypatch.delenv("CLAUDE_RECALL_DEBUG", raising=False)
        monkeypatch.delenv("RECALL_DEBUG", raising=False)
        monkeypatch.delenv("LESSONS_DEBUG", raising=False)
        assert _get_debug_level() == 1

    def test_level_0_disabled(self, monkeypatch):
        """Level 0 should disable logging."""
        monkeypatch.setenv("CLAUDE_RECALL_DEBUG", "0")
        assert _get_debug_level() == 0

    def test_level_1_info(self, monkeypatch):
        """Level 1 should enable info logging."""
        monkeypatch.setenv("CLAUDE_RECALL_DEBUG", "1")
        assert _get_debug_level() == 1

    def test_level_2_debug(self, monkeypatch):
        """Level 2 should enable debug logging."""
        monkeypatch.setenv("CLAUDE_RECALL_DEBUG", "2")
        assert _get_debug_level() == 2

    def test_level_3_trace(self, monkeypatch):
        """Level 3 should enable trace logging."""
        monkeypatch.setenv("CLAUDE_RECALL_DEBUG", "3")
        assert _get_debug_level() == 3

    def test_truthy_values(self, monkeypatch):
        """Truthy string values should enable level 1."""
        for value in ["true", "True", "TRUE", "yes", "on"]:
            monkeypatch.setenv("CLAUDE_RECALL_DEBUG", value)
            assert _get_debug_level() == 1

    def test_invalid_values(self, monkeypatch):
        """Invalid values should disable logging."""
        monkeypatch.setenv("CLAUDE_RECALL_DEBUG", "invalid")
        assert _get_debug_level() == 0


# =============================================================================
# Tests: Settings File Configuration
# =============================================================================


class TestSettingsConfig:
    """Test debug level from ~/.config/claude-recall/config.json."""

    @pytest.fixture
    def temp_config_path(self, tmp_path: Path, monkeypatch):
        """Create a temporary config.json and patch CLAUDE_RECALL_CONFIG_PATH."""
        config_dir = tmp_path / ".config" / "claude-recall"
        config_dir.mkdir(parents=True)
        config_path = config_dir / "config.json"
        # Patch the module constant
        import core.debug_logger as dl
        monkeypatch.setattr(dl, "CLAUDE_RECALL_CONFIG_PATH", config_path)
        return config_path

    def test_reads_debug_level_from_settings(self, temp_config_path, monkeypatch):
        """Should read debugLevel from config.json."""
        monkeypatch.delenv("CLAUDE_RECALL_DEBUG", raising=False)
        monkeypatch.delenv("RECALL_DEBUG", raising=False)
        monkeypatch.delenv("LESSONS_DEBUG", raising=False)

        temp_config_path.write_text(json.dumps({
            "debugLevel": 2
        }))
        assert _read_settings_debug_level() == 2
        assert _get_debug_level() == 2

    def test_env_var_overrides_settings(self, temp_config_path, monkeypatch):
        """Env var should take precedence over config.json."""
        temp_config_path.write_text(json.dumps({
            "debugLevel": 2
        }))
        monkeypatch.setenv("CLAUDE_RECALL_DEBUG", "3")
        assert _get_debug_level() == 3

    def test_returns_none_when_no_file(self, temp_config_path, monkeypatch):
        """Should return None when config file doesn't exist."""
        monkeypatch.delenv("CLAUDE_RECALL_DEBUG", raising=False)
        # Don't create the file
        assert _read_settings_debug_level() is None
        # Should fall back to default
        assert _get_debug_level() == 1

    def test_returns_none_when_no_debug_level(self, temp_config_path, monkeypatch):
        """Should return None when debugLevel not in config."""
        monkeypatch.delenv("CLAUDE_RECALL_DEBUG", raising=False)
        monkeypatch.delenv("RECALL_DEBUG", raising=False)
        monkeypatch.delenv("LESSONS_DEBUG", raising=False)

        temp_config_path.write_text(json.dumps({
            "enabled": True
        }))
        assert _read_settings_debug_level() is None
        assert _get_debug_level() == 1

    def test_handles_invalid_json(self, temp_config_path, monkeypatch):
        """Should return None for invalid JSON."""
        monkeypatch.delenv("CLAUDE_RECALL_DEBUG", raising=False)
        temp_config_path.write_text("not valid json{")
        assert _read_settings_debug_level() is None

    def test_handles_missing_debug_level_key(self, temp_config_path, monkeypatch):
        """Should return None when debugLevel key missing."""
        monkeypatch.delenv("CLAUDE_RECALL_DEBUG", raising=False)
        temp_config_path.write_text(json.dumps({"hooks": {}}))
        assert _read_settings_debug_level() is None


# =============================================================================
# Tests: Logger Instance
# =============================================================================


class TestDebugLogger:
    """Test DebugLogger class."""

    def test_enabled_property(self, monkeypatch, temp_state_dir):
        """Enabled property should reflect level."""
        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))

        monkeypatch.setenv("CLAUDE_RECALL_DEBUG", "0")
        logger = DebugLogger()
        assert not logger.enabled

        monkeypatch.setenv("CLAUDE_RECALL_DEBUG", "1")
        logger = DebugLogger()
        assert logger.enabled

    def test_level_property(self, monkeypatch, temp_state_dir):
        """Level property should return configured level."""
        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        monkeypatch.setenv("CLAUDE_RECALL_DEBUG", "2")
        logger = DebugLogger()
        assert logger.level == 2

    def test_no_write_when_disabled(self, monkeypatch, temp_state_dir):
        """No log file should be created when disabled."""
        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        monkeypatch.setenv("CLAUDE_RECALL_DEBUG", "0")

        logger = DebugLogger()
        logger.session_start(
            project_root="/test",
            lessons_base="/base",
            total_lessons=5,
            system_count=2,
            project_count=3,
            top_lessons=[],
            total_tokens=100,
        )

        log_file = temp_state_dir / "debug.log"
        assert not log_file.exists()


# =============================================================================
# Tests: JSON Lines Output
# =============================================================================


class TestJsonLinesOutput:
    """Test JSON lines format output."""

    def test_writes_json_lines(self, monkeypatch, temp_state_dir):
        """Should write valid JSON lines to log file."""
        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        monkeypatch.setenv("CLAUDE_RECALL_DEBUG", "1")

        logger = DebugLogger()
        logger.lesson_added(
            lesson_id="L001",
            level="project",
            category="pattern",
            source="human",
            title_length=10,
            content_length=50,
        )

        log_file = temp_state_dir / "debug.log"
        assert log_file.exists()

        content = log_file.read_text().strip()
        entry = json.loads(content)

        assert entry["event"] == "lesson_added"
        assert entry["lesson_id"] == "L001"
        assert entry["level"] == "info"
        assert "timestamp" in entry
        assert "session_id" in entry
        assert "pid" in entry

    def test_session_start_event(self, monkeypatch, temp_state_dir):
        """Should log session_start with correct fields."""
        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        monkeypatch.setenv("CLAUDE_RECALL_DEBUG", "1")

        logger = DebugLogger()
        logger.session_start(
            project_root="/test/project",
            lessons_base="/test/base",
            total_lessons=10,
            system_count=3,
            project_count=7,
            top_lessons=[{"id": "L001", "uses": 5}],
            total_tokens=500,
        )

        log_file = temp_state_dir / "debug.log"
        entry = json.loads(log_file.read_text().strip())

        assert entry["event"] == "session_start"
        assert entry["project_root"] == "/test/project"
        assert entry["total_lessons"] == 10
        assert entry["total_tokens"] == 500
        assert len(entry["top_lessons"]) == 1

    def test_citation_event(self, monkeypatch, temp_state_dir):
        """Should log citation with before/after values."""
        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        monkeypatch.setenv("CLAUDE_RECALL_DEBUG", "1")

        logger = DebugLogger()
        logger.citation(
            lesson_id="L003",
            uses_before=5,
            uses_after=6,
            velocity_before=2.0,
            velocity_after=3.0,
            promotion_ready=False,
        )

        log_file = temp_state_dir / "debug.log"
        entry = json.loads(log_file.read_text().strip())

        assert entry["event"] == "citation"
        assert entry["lesson_id"] == "L003"
        assert entry["uses_before"] == 5
        assert entry["uses_after"] == 6
        assert entry["velocity_before"] == 2.0
        assert entry["velocity_after"] == 3.0
        assert entry["promotion_ready"] is False

    def test_handoff_events(self, monkeypatch, temp_state_dir):
        """Should log handoff lifecycle events."""
        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        monkeypatch.setenv("CLAUDE_RECALL_DEBUG", "1")

        logger = DebugLogger()

        # Created event
        logger.handoff_created(
            handoff_id="H001",
            title="Test handoff",
            phase="research",
            agent="user",
        )

        # Change event
        logger.handoff_change(
            handoff_id="H001",
            action="phase_change",
            old_value="research",
            new_value="implementing",
        )

        # Completed event
        logger.handoff_completed(
            handoff_id="H001",
            tried_count=3,
            duration_days=5,
        )

        log_file = temp_state_dir / "debug.log"
        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 3

        created = json.loads(lines[0])
        assert created["event"] == "handoff_created"
        assert created["handoff_id"] == "H001"

        changed = json.loads(lines[1])
        assert changed["event"] == "handoff_change"
        assert changed["action"] == "phase_change"

        completed = json.loads(lines[2])
        assert completed["event"] == "handoff_completed"
        assert completed["tried_count"] == 3


# =============================================================================
# Tests: Level Gating
# =============================================================================


class TestLevelGating:
    """Test that events are gated by debug level."""

    def test_info_events_at_level_1(self, monkeypatch, temp_state_dir):
        """Info events should log at level 1."""
        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        monkeypatch.setenv("CLAUDE_RECALL_DEBUG", "1")

        logger = DebugLogger()
        logger.lesson_added("L001", "project", "pattern", "human", 10, 50)

        log_file = temp_state_dir / "debug.log"
        assert log_file.exists()

    def test_debug_events_not_at_level_1(self, monkeypatch, temp_state_dir):
        """Debug events should not log at level 1."""
        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        monkeypatch.setenv("CLAUDE_RECALL_DEBUG", "1")

        logger = DebugLogger()
        logger.injection_generated(
            token_budget=1000,
            lessons_included=5,
            lessons_excluded=10,
            included_ids=["L001", "L002"],
        )

        log_file = temp_state_dir / "debug.log"
        # Should not exist because injection_generated is level 2
        assert not log_file.exists()

    def test_debug_events_at_level_2(self, monkeypatch, temp_state_dir):
        """Debug events should log at level 2."""
        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        monkeypatch.setenv("CLAUDE_RECALL_DEBUG", "2")

        logger = DebugLogger()
        logger.injection_generated(
            token_budget=1000,
            lessons_included=5,
            lessons_excluded=10,
            included_ids=["L001", "L002"],
        )

        log_file = temp_state_dir / "debug.log"
        assert log_file.exists()

        entry = json.loads(log_file.read_text().strip())
        assert entry["event"] == "injection_generated"
        assert entry["level"] == "debug"

    def test_trace_events_at_level_3(self, monkeypatch, temp_state_dir):
        """Trace events should log at level 3."""
        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        monkeypatch.setenv("CLAUDE_RECALL_DEBUG", "3")

        logger = DebugLogger()
        with logger.trace_file_io("read", "/test/file.md"):
            pass  # Simulate file operation

        log_file = temp_state_dir / "debug.log"
        assert log_file.exists()

        entry = json.loads(log_file.read_text().strip())
        assert entry["event"] == "file_io"
        assert entry["level"] == "trace"
        assert "duration_ms" in entry


# =============================================================================
# Tests: Session ID
# =============================================================================


class TestSessionId:
    """Test session ID generation."""

    def test_session_id_consistent(self):
        """Session ID should be consistent within a process."""
        id1 = _get_session_id()
        id2 = _get_session_id()
        assert id1 == id2

    def test_session_id_format(self):
        """Session ID should be 12 hex characters."""
        session_id = _get_session_id()
        assert len(session_id) == 12
        assert all(c in "0123456789abcdef" for c in session_id)


# =============================================================================
# Tests: Global Logger
# =============================================================================


class TestGlobalLogger:
    """Test global logger singleton."""

    def test_get_logger_returns_same_instance(self, monkeypatch, temp_state_dir):
        """get_logger should return the same instance."""
        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        monkeypatch.setenv("CLAUDE_RECALL_DEBUG", "1")

        logger1 = get_logger()
        logger2 = get_logger()
        assert logger1 is logger2

    def test_reset_logger_clears_instance(self, monkeypatch, temp_state_dir):
        """reset_logger should clear the global instance."""
        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        monkeypatch.setenv("CLAUDE_RECALL_DEBUG", "1")

        logger1 = get_logger()
        reset_logger()
        logger2 = get_logger()
        assert logger1 is not logger2


# =============================================================================
# Tests: Timing Methods
# =============================================================================


class TestTimingMethods:
    """Test timing context managers and hook timing methods."""

    def test_timer_context_manager_logs_at_level_2(self, monkeypatch, temp_state_dir):
        """timer context manager should log at level 2."""
        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        monkeypatch.setenv("CLAUDE_RECALL_DEBUG", "2")

        logger = DebugLogger()
        with logger.timer("test_operation", {"count": 5}):
            pass  # Simulate operation

        log_file = temp_state_dir / "debug.log"
        assert log_file.exists()

        entry = json.loads(log_file.read_text().strip())
        assert entry["event"] == "timing"
        assert entry["op"] == "test_operation"
        assert "ms" in entry
        assert entry["count"] == 5

    def test_timer_context_manager_not_at_level_1(self, monkeypatch, temp_state_dir):
        """timer context manager should not log at level 1."""
        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        monkeypatch.setenv("CLAUDE_RECALL_DEBUG", "1")

        logger = DebugLogger()
        with logger.timer("test_operation"):
            pass

        log_file = temp_state_dir / "debug.log"
        assert not log_file.exists()

    def test_hook_phase_logs_timing(self, monkeypatch, temp_state_dir):
        """hook_phase should log phase timing at level 2."""
        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        monkeypatch.setenv("CLAUDE_RECALL_DEBUG", "2")

        logger = DebugLogger()
        logger.hook_phase("inject", "load_lessons", 42.5, {"count": 10})

        log_file = temp_state_dir / "debug.log"
        assert log_file.exists()

        entry = json.loads(log_file.read_text().strip())
        assert entry["event"] == "hook_phase"
        assert entry["hook"] == "inject"
        assert entry["phase"] == "load_lessons"
        assert entry["ms"] == 42.5
        assert entry["count"] == 10

    def test_hook_start_returns_time(self, monkeypatch, temp_state_dir):
        """hook_start should return start time for duration calculation."""
        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        monkeypatch.setenv("CLAUDE_RECALL_DEBUG", "2")

        logger = DebugLogger()
        start = logger.hook_start("inject", trigger="auto")

        assert isinstance(start, float)
        assert start > 0

        log_file = temp_state_dir / "debug.log"
        assert log_file.exists()

        entry = json.loads(log_file.read_text().strip())
        assert entry["event"] == "hook_start"
        assert entry["hook"] == "inject"
        assert entry["trigger"] == "auto"

    def test_hook_end_logs_total_and_phases(self, monkeypatch, temp_state_dir):
        """hook_end should log total time and phase breakdown."""
        import time
        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        monkeypatch.setenv("CLAUDE_RECALL_DEBUG", "2")

        logger = DebugLogger()
        start = logger.hook_start("stop")
        time.sleep(0.01)  # Small delay
        logger.hook_end("stop", start, {"parse": 10.0, "sync": 20.0})

        log_file = temp_state_dir / "debug.log"
        content = log_file.read_text().strip().split("\n")
        assert len(content) == 2

        end_entry = json.loads(content[1])
        assert end_entry["event"] == "hook_end"
        assert end_entry["hook"] == "stop"
        assert end_entry["total_ms"] >= 10  # At least 10ms
        assert end_entry["phases"]["parse"] == 10.0
        assert end_entry["phases"]["sync"] == 20.0
