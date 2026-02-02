#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Regression tests for hook timing at debug level 1.

Verifies that hook timing is logged at the default debug level (1) so the TUI
can display timing statistics. Prior to this fix, timing was only logged at
level 2+, causing the TUI to show all zeros.

Run with: ./run-tests.sh tests/test_hook_timing.py -v
"""

import json
import os
import subprocess
import sys
import pytest
from pathlib import Path

from core.debug_logger import DebugLogger, reset_logger


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def temp_state_dir(tmp_path: Path) -> Path:
    """Create a temporary state directory for logs."""
    state_dir = tmp_path / ".local" / "state" / "claude-recall"
    state_dir.mkdir(parents=True)
    return state_dir


@pytest.fixture
def temp_project_root(tmp_path: Path) -> Path:
    """Create a temporary project root."""
    project_root = tmp_path / "project"
    project_root.mkdir(parents=True)
    return project_root


@pytest.fixture(autouse=True)
def reset_logger_state():
    """Reset the global logger before and after each test."""
    reset_logger()
    yield
    reset_logger()


# =============================================================================
# Unit Tests: DebugLogger hook methods at level 1
# =============================================================================


class TestHookTimingAtLevel1:
    """Verify hook timing logs at debug level 1 (the default)."""

    def test_hook_start_logs_at_level_1(self, monkeypatch, temp_state_dir):
        """hook_start should log at level 1."""
        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        monkeypatch.setenv("CLAUDE_RECALL_DEBUG", "1")

        logger = DebugLogger()
        start_time = logger.hook_start("inject", trigger="auto")

        assert isinstance(start_time, float)
        assert start_time > 0

        log_file = temp_state_dir / "debug.log"
        assert log_file.exists(), "hook_start should create log at level 1"

        entry = json.loads(log_file.read_text().strip())
        assert entry["event"] == "hook_start"
        assert entry["hook"] == "inject"
        assert entry["trigger"] == "auto"

    def test_hook_end_logs_at_level_1(self, monkeypatch, temp_state_dir):
        """hook_end should log at level 1."""
        import time
        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        monkeypatch.setenv("CLAUDE_RECALL_DEBUG", "1")

        logger = DebugLogger()
        start = logger.hook_start("stop")
        time.sleep(0.01)  # Small delay
        logger.hook_end("stop", start, {"parse": 10.0, "sync": 20.0})

        log_file = temp_state_dir / "debug.log"
        assert log_file.exists()

        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 2, "Should have hook_start and hook_end entries"

        end_entry = json.loads(lines[1])
        assert end_entry["event"] == "hook_end"
        assert end_entry["hook"] == "stop"
        assert "total_ms" in end_entry
        assert end_entry["phases"]["parse"] == 10.0
        assert end_entry["phases"]["sync"] == 20.0

    def test_hook_phase_logs_at_level_1(self, monkeypatch, temp_state_dir):
        """hook_phase should log at level 1."""
        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        monkeypatch.setenv("CLAUDE_RECALL_DEBUG", "1")

        logger = DebugLogger()
        logger.hook_phase("inject", "load_lessons", 42.5, {"count": 10})

        log_file = temp_state_dir / "debug.log"
        assert log_file.exists(), "hook_phase should create log at level 1"

        entry = json.loads(log_file.read_text().strip())
        assert entry["event"] == "hook_phase"
        assert entry["hook"] == "inject"
        assert entry["phase"] == "load_lessons"
        assert entry["ms"] == 42.5


class TestHookTimingAtLevel0:
    """Verify hook timing does NOT log at debug level 0."""

    def test_hook_start_not_logged_at_level_0(self, monkeypatch, temp_state_dir):
        """hook_start should not log at level 0."""
        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        monkeypatch.setenv("CLAUDE_RECALL_DEBUG", "0")

        logger = DebugLogger()
        logger.hook_start("inject", trigger="auto")

        log_file = temp_state_dir / "debug.log"
        assert not log_file.exists(), "hook_start should not log at level 0"

    def test_hook_end_not_logged_at_level_0(self, monkeypatch, temp_state_dir):
        """hook_end should not log at level 0."""
        import time
        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        monkeypatch.setenv("CLAUDE_RECALL_DEBUG", "0")

        logger = DebugLogger()
        start = logger.hook_start("stop")
        time.sleep(0.01)
        logger.hook_end("stop", start, {"parse": 10.0})

        log_file = temp_state_dir / "debug.log"
        assert not log_file.exists(), "hook_end should not log at level 0"

    def test_hook_phase_not_logged_at_level_0(self, monkeypatch, temp_state_dir):
        """hook_phase should not log at level 0."""
        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        monkeypatch.setenv("CLAUDE_RECALL_DEBUG", "0")

        logger = DebugLogger()
        logger.hook_phase("inject", "load_lessons", 42.5)

        log_file = temp_state_dir / "debug.log"
        assert not log_file.exists(), "hook_phase should not log at level 0"


# =============================================================================
# CLI Integration Tests
# =============================================================================


@pytest.mark.skip(reason="Python CLI removed - debug commands now handled by Go binary")
class TestCLIHookTiming:
    """Test hook timing via CLI commands at level 1.

    NOTE: Skipped because Python CLI was removed; Go binary handles debug commands.
    """

    def test_cli_hook_end_logs_at_level_1(
        self, monkeypatch, temp_state_dir, temp_project_root
    ):
        """CLI debug hook-end should log at level 1."""
        env = {
            **os.environ,
            "CLAUDE_RECALL_STATE": str(temp_state_dir),
            "CLAUDE_RECALL_DEBUG": "1",
            "PROJECT_DIR": str(temp_project_root),
        }

        result = subprocess.run(
            [sys.executable, "-m", "core.cli", "debug", "hook-end", "inject", "50.5"],
            env=env,
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent,
        )

        assert result.returncode == 0, f"CLI failed: {result.stderr}"

        log_file = temp_state_dir / "debug.log"
        assert log_file.exists(), "hook-end should create log at level 1"

        entry = json.loads(log_file.read_text().strip())
        assert entry["event"] == "hook_end"
        assert entry["hook"] == "inject"
        assert entry["total_ms"] == 50.5

    def test_cli_hook_start_logs_at_level_1(
        self, monkeypatch, temp_state_dir, temp_project_root
    ):
        """CLI debug hook-start should log at level 1."""
        env = {
            **os.environ,
            "CLAUDE_RECALL_STATE": str(temp_state_dir),
            "CLAUDE_RECALL_DEBUG": "1",
            "PROJECT_DIR": str(temp_project_root),
        }

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "core.cli",
                "debug",
                "hook-start",
                "stop",
                "--trigger",
                "auto",
            ],
            env=env,
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent,
        )

        assert result.returncode == 0, f"CLI failed: {result.stderr}"

        log_file = temp_state_dir / "debug.log"
        assert log_file.exists(), "hook-start should create log at level 1"

        entry = json.loads(log_file.read_text().strip())
        assert entry["event"] == "hook_start"
        assert entry["hook"] == "stop"
        assert entry["trigger"] == "auto"

    def test_cli_hook_end_not_logged_at_level_0(
        self, monkeypatch, temp_state_dir, temp_project_root
    ):
        """CLI debug hook-end should not log at level 0."""
        env = {
            **os.environ,
            "CLAUDE_RECALL_STATE": str(temp_state_dir),
            "CLAUDE_RECALL_DEBUG": "0",
            "PROJECT_DIR": str(temp_project_root),
        }

        result = subprocess.run(
            [sys.executable, "-m", "core.cli", "debug", "hook-end", "inject", "50.5"],
            env=env,
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent,
        )

        assert result.returncode == 0

        log_file = temp_state_dir / "debug.log"
        assert not log_file.exists(), "hook-end should not log at level 0"

    def test_cli_hook_end_with_phases_flag_works(
        self, monkeypatch, temp_state_dir, temp_project_root
    ):
        """CLI debug hook-end with --phases flag works correctly."""
        env = {
            **os.environ,
            "CLAUDE_RECALL_STATE": str(temp_state_dir),
            "CLAUDE_RECALL_DEBUG": "1",
            "PROJECT_DIR": str(temp_project_root),
        }

        # This is the CORRECT way to pass phases - using --phases flag
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "core.cli",
                "debug",
                "hook-end",
                "inject",
                "50.5",
                "--phases",
                '{"parse":10,"sync":20}',
            ],
            env=env,
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent,
        )

        assert result.returncode == 0, f"CLI failed: {result.stderr}"

        log_file = temp_state_dir / "debug.log"
        assert log_file.exists(), "hook-end should create log at level 1"

        entry = json.loads(log_file.read_text().strip())
        assert entry["event"] == "hook_end"
        assert entry["hook"] == "inject"
        assert entry["total_ms"] == 50.5
        assert entry["phases"]["parse"] == 10
        assert entry["phases"]["sync"] == 20

    def test_cli_hook_end_with_phases_positional_fails(
        self, monkeypatch, temp_state_dir, temp_project_root
    ):
        """CLI debug hook-end with phases as positional arg fails (documents the bash bug)."""
        env = {
            **os.environ,
            "CLAUDE_RECALL_STATE": str(temp_state_dir),
            "CLAUDE_RECALL_DEBUG": "1",
            "PROJECT_DIR": str(temp_project_root),
        }

        # This mimics what bash INCORRECTLY does - passing phases as positional arg
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "core.cli",
                "debug",
                "hook-end",
                "inject",
                "50.5",
                '{"parse":10}',
            ],
            env=env,
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent,
        )

        # This SHOULD fail because phases is a positional arg, not --phases flag
        assert result.returncode != 0, "Positional phases should fail (argparse rejects it)"
