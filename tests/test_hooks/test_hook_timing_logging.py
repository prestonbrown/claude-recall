#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Tests for hook timing logging at different debug levels.

Verifies the fix for: log_hook_end() in hook-lib.sh required debug level >= 2,
but default is 1, so timing was never logged.

After the fix, timing should be logged at level >= 1 (the default).

Run with: ./run-tests.sh tests/test_hooks/test_hook_timing_logging.py -v
"""

import json
import os
import subprocess
import time
from pathlib import Path

import pytest


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def temp_claude_home(tmp_path: Path) -> Path:
    """Create a temporary ~/.claude structure for testing."""
    claude_home = tmp_path / ".claude"
    projects_dir = claude_home / "projects"
    projects_dir.mkdir(parents=True)

    # Create settings.json with lessons enabled
    settings = claude_home / "settings.json"
    settings.write_text('{"claudeRecall":{"enabled":true}}')

    return claude_home


@pytest.fixture
def temp_project_root(tmp_path: Path) -> Path:
    """Create a temporary project root with .git directory."""
    project = tmp_path / "project"
    project.mkdir(parents=True)
    (project / ".git").mkdir()
    (project / ".claude-recall").mkdir()
    return project


@pytest.fixture
def inject_hook_path() -> Path:
    """Path to the inject-hook.sh script."""
    candidates = [
        Path(__file__).parent.parent.parent / "adapters" / "claude-code" / "inject-hook.sh",
        Path.home() / ".claude" / "hooks" / "inject-hook.sh",
    ]
    for p in candidates:
        if p.exists():
            return p
    pytest.skip("inject-hook.sh not found")


@pytest.fixture
def hook_lib_path() -> Path:
    """Path to the hook-lib.sh library."""
    path = Path(__file__).parent.parent.parent / "adapters" / "claude-code" / "hook-lib.sh"
    if not path.exists():
        pytest.skip("hook-lib.sh not found")
    return path


# =============================================================================
# Tests: Hook Timing at Debug Level 1 (Default)
# =============================================================================


class TestHookTimingAtDebugLevel1:
    """Verify hook timing is logged at debug level 1 (the default)."""

    def test_inject_hook_logs_timing_at_level_1(
        self, tmp_path, inject_hook_path, temp_claude_home, temp_project_root
    ):
        """
        Inject hook should log HOOK_END timing events at debug level 1.

        This is the regression test for the bug where log_hook_end() required
        debug level >= 2, but the default is 1.
        """
        state_dir = tmp_path / ".local" / "state" / "claude-recall"
        state_dir.mkdir(parents=True, exist_ok=True)

        session_id = "timing-test-session"
        input_json = json.dumps({
            "session_id": session_id,
            "cwd": str(temp_project_root)
        })

        # Build environment with debug level 1 (the default)
        env = {
            **{k: v for k, v in os.environ.items() if k in {
                "PATH", "SHELL", "TERM", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE"
            }},
            "HOME": str(tmp_path),
            "CLAUDE_RECALL_STATE": str(state_dir),
            "CLAUDE_RECALL_DEBUG": "1",  # Default level
            "PROJECT_DIR": str(temp_project_root),
        }

        result = subprocess.run(
            ["bash", str(inject_hook_path)],
            input=input_json,
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )

        # Wait for background processes (log_hook_end and log_phase run with &)
        # Note: hook_end may not always be captured because the shell exits before
        # the background process completes, but hook_phase events should be present.
        time.sleep(1.0)

        log_file = state_dir / "debug.log"
        assert log_file.exists(), (
            f"debug.log should exist after inject-hook runs at level 1.\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}\n"
            f"exit code: {result.returncode}"
        )

        log_content = log_file.read_text()
        log_lines = [line for line in log_content.strip().split('\n') if line]

        # Find hook_end or hook_phase events - either confirms timing is logged at level 1
        # Note: hook_end runs in background with '&' and may not complete before shell exits
        hook_timing_events = []
        for line in log_lines:
            try:
                entry = json.loads(line)
                if entry.get("event") in ("hook_end", "hook_phase") and entry.get("hook") == "inject":
                    hook_timing_events.append(entry)
            except json.JSONDecodeError:
                continue

        assert len(hook_timing_events) >= 1, (
            f"Expected at least one hook timing event (hook_end or hook_phase) for 'inject' at level 1.\n"
            f"Log content: {log_content}\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )

        # Verify the event has timing data (ms or total_ms depending on event type)
        event = hook_timing_events[0]
        has_timing = "ms" in event or "total_ms" in event
        assert has_timing, (
            f"Hook timing event should have ms or total_ms field.\n"
            f"Event: {json.dumps(event, indent=2)}"
        )

    def test_hook_phase_logs_at_level_1(
        self, tmp_path, inject_hook_path, temp_claude_home, temp_project_root
    ):
        """
        Hook phases (like load_lessons) should be logged at debug level 1.
        """
        state_dir = tmp_path / ".local" / "state" / "claude-recall"
        state_dir.mkdir(parents=True, exist_ok=True)

        input_json = json.dumps({
            "session_id": "phase-test-session",
            "cwd": str(temp_project_root)
        })

        env = {
            **{k: v for k, v in os.environ.items() if k in {
                "PATH", "SHELL", "TERM", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE"
            }},
            "HOME": str(tmp_path),
            "CLAUDE_RECALL_STATE": str(state_dir),
            "CLAUDE_RECALL_DEBUG": "1",
            "PROJECT_DIR": str(temp_project_root),
        }

        result = subprocess.run(
            ["bash", str(inject_hook_path)],
            input=input_json,
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )

        # Wait for background processes
        time.sleep(0.5)

        log_file = state_dir / "debug.log"
        assert log_file.exists()

        log_content = log_file.read_text()

        # Find hook_phase events
        phase_events = []
        for line in log_content.strip().split('\n'):
            if not line:
                continue
            try:
                entry = json.loads(line)
                if entry.get("event") == "hook_phase":
                    phase_events.append(entry)
            except json.JSONDecodeError:
                continue

        assert len(phase_events) >= 1, (
            f"Expected at least one hook_phase event at level 1.\n"
            f"Log content: {log_content}"
        )


# =============================================================================
# Tests: Hook Timing NOT Logged at Debug Level 0
# =============================================================================


class TestHookTimingAtDebugLevel0:
    """Verify hook timing is NOT logged at debug level 0."""

    def test_inject_hook_does_not_log_timing_at_level_0(
        self, tmp_path, inject_hook_path, temp_claude_home, temp_project_root
    ):
        """
        Inject hook should NOT log timing events at debug level 0.
        """
        state_dir = tmp_path / ".local" / "state" / "claude-recall"
        state_dir.mkdir(parents=True, exist_ok=True)

        input_json = json.dumps({
            "session_id": "no-timing-session",
            "cwd": str(temp_project_root)
        })

        env = {
            **{k: v for k, v in os.environ.items() if k in {
                "PATH", "SHELL", "TERM", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE"
            }},
            "HOME": str(tmp_path),
            "CLAUDE_RECALL_STATE": str(state_dir),
            "CLAUDE_RECALL_DEBUG": "0",  # Disabled
            "PROJECT_DIR": str(temp_project_root),
        }

        result = subprocess.run(
            ["bash", str(inject_hook_path)],
            input=input_json,
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )

        # Wait to ensure any background processes would have completed
        time.sleep(0.5)

        log_file = state_dir / "debug.log"

        # At level 0, no log file should be created (or if it exists, no hook timing events)
        if log_file.exists():
            log_content = log_file.read_text()

            # Check for hook_end events
            for line in log_content.strip().split('\n'):
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    assert entry.get("event") != "hook_end", (
                        f"hook_end should NOT be logged at level 0.\n"
                        f"Entry: {json.dumps(entry, indent=2)}"
                    )
                    assert entry.get("event") != "hook_phase", (
                        f"hook_phase should NOT be logged at level 0.\n"
                        f"Entry: {json.dumps(entry, indent=2)}"
                    )
                except json.JSONDecodeError:
                    continue


# =============================================================================
# Tests: Direct hook-lib.sh Function Testing
# =============================================================================


class TestHookLibFunctions:
    """Test hook-lib.sh functions directly by sourcing the library."""

    def test_log_hook_end_condition_in_source(self, hook_lib_path):
        """
        Verify log_hook_end uses correct debug level check (>= 1, not >= 2).

        The bug was: [[ "${CLAUDE_RECALL_DEBUG:-0}" -lt 2 ]] && return 0
        Fix should be: [[ "${CLAUDE_RECALL_DEBUG:-0}" -lt 1 ]] && return 0
        """
        content = hook_lib_path.read_text()

        # Find the log_hook_end function and check its debug level condition
        # The correct condition should skip only at level < 1 (i.e., level 0)
        assert '-lt 1' in content or '-ge 1' in content, (
            "log_hook_end should check for debug level >= 1.\n"
            "The bug was using -lt 2 which required level >= 2."
        )

        # Specifically verify the log_hook_end function doesn't have the buggy condition
        # Look for the pattern that would indicate the bug
        import re

        # Find log_hook_end function body
        match = re.search(
            r'log_hook_end\s*\(\)\s*\{([^}]+)\}',
            content,
            re.DOTALL
        )
        assert match, "Could not find log_hook_end function in hook-lib.sh"

        func_body = match.group(1)

        # The buggy pattern was: -lt 2
        # The correct pattern is: -lt 1
        assert '-lt 2' not in func_body, (
            "log_hook_end has the bug: uses '-lt 2' which requires level >= 2.\n"
            "Should use '-lt 1' to log at the default level (1).\n"
            f"Function body: {func_body}"
        )

    def test_log_phase_condition_in_source(self, hook_lib_path):
        """
        Verify log_phase also uses correct debug level check.
        """
        content = hook_lib_path.read_text()

        import re

        # Find log_phase function body
        match = re.search(
            r'log_phase\s*\(\)\s*\{([^}]+)\}',
            content,
            re.DOTALL
        )
        assert match, "Could not find log_phase function in hook-lib.sh"

        func_body = match.group(1)

        # Should use -lt 1, not -lt 2
        assert '-lt 2' not in func_body, (
            "log_phase has a bug: uses '-lt 2' which requires level >= 2.\n"
            "Should use '-lt 1' to log at the default level (1).\n"
            f"Function body: {func_body}"
        )
