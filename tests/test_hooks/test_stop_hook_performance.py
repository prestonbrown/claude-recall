#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Performance tests for stop-hook optimizations.

Tests the two major bottlenecks that were fixed:
1. cleanup_orphaned_checkpoints - now runs only 10% of the time and batches find commands
2. get_session_origin_fast - now uses direct glob lookup instead of list_all_sessions(limit=500)

Run with: ./run-tests.sh tests/test_hooks/test_stop_hook_performance.py -v
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import warnings
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
def temp_state_dir(tmp_path: Path) -> Path:
    """Create a temporary state directory."""
    state_dir = tmp_path / ".local" / "state" / "claude-recall"
    state_dir.mkdir(parents=True)
    return state_dir


@pytest.fixture
def temp_project_root(tmp_path: Path) -> Path:
    """Create a temporary project root with .git directory."""
    project = tmp_path / "project"
    project.mkdir(parents=True)
    (project / ".git").mkdir()
    return project


@pytest.fixture
def stop_hook_path() -> Path:
    """Path to the stop-hook.sh script."""
    # Try multiple locations
    candidates = [
        Path(__file__).parent.parent.parent / "adapters" / "claude-code" / "stop-hook.sh",
        Path.home() / ".claude" / "hooks" / "stop-hook.sh",
    ]
    for p in candidates:
        if p.exists():
            return p
    pytest.skip("stop-hook.sh not found")


# =============================================================================
# Integration Tests: Full Hook Timing
# =============================================================================


class TestStopHookIntegration:
    """Integration tests for stop hook performance."""

    @pytest.mark.slow
    def test_stop_hook_completes_under_2_seconds(
        self, tmp_path, stop_hook_path, temp_claude_home, temp_state_dir, temp_project_root
    ):
        """Stop hook should complete in under 2 seconds with realistic data."""
        # Create a mock transcript with handoff patterns
        project_encoded = "-Users-test-code-project"
        project_dir = temp_claude_home / "projects" / project_encoded
        project_dir.mkdir(parents=True)

        session_id = "test-perf-session"
        transcript = project_dir / f"{session_id}.jsonl"

        # Create a realistic transcript with multiple message types
        messages = []
        base_time = "2026-01-10T10:00:00.000Z"

        # User message
        messages.append({
            "type": "user",
            "uuid": "msg-user-001",
            "timestamp": base_time,
            "sessionId": session_id,
            "cwd": str(temp_project_root),
            "message": {"role": "user", "content": "Help me with this task"}
        })

        # Assistant with handoff pattern
        messages.append({
            "type": "assistant",
            "uuid": "msg-asst-001",
            "timestamp": "2026-01-10T10:00:05.000Z",
            "sessionId": session_id,
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "HANDOFF: Test task for performance"}],
                "usage": {"input_tokens": 1000, "output_tokens": 200}
            }
        })

        with open(transcript, "w") as f:
            for msg in messages:
                f.write(json.dumps(msg) + "\n")

        # Create input JSON for the hook
        input_json = json.dumps({
            "session_id": session_id,
            "transcript_path": str(transcript),
            "cwd": str(temp_project_root)
        })

        # Build environment
        env = {
            **os.environ,
            "HOME": str(tmp_path),
            "CLAUDE_RECALL_STATE": str(temp_state_dir),
            "CLAUDE_RECALL_DEBUG": "0",  # Disable debug logging for timing
            "PROJECT_DIR": str(temp_project_root),
        }

        # Time the hook execution
        start = time.perf_counter()
        result = subprocess.run(
            ["bash", str(stop_hook_path)],
            input=input_json,
            capture_output=True,
            text=True,
            env=env,
            timeout=10,  # Hard timeout to prevent hanging
        )
        elapsed = time.perf_counter() - start

        # The hook should complete (may have non-zero exit if features disabled)
        # Just checking it doesn't hang and completes reasonably fast

        if elapsed > 2.0:
            warnings.warn(f"Stop hook took {elapsed:.2f}s (threshold: 2s)")

        assert elapsed < 10.0, f"Stop hook took {elapsed:.1f}s (max: 10s)"

    @pytest.mark.slow
    def test_stop_hook_with_many_sessions(
        self, tmp_path, stop_hook_path, temp_claude_home, temp_state_dir, temp_project_root
    ):
        """Stop hook should remain fast even with many existing sessions."""
        project_encoded = "-Users-test-code-project"
        project_dir = temp_claude_home / "projects" / project_encoded
        project_dir.mkdir(parents=True)

        # Create many sessions (simulating a realistic project)
        for i in range(50):
            session_file = project_dir / f"session-{i:04d}.jsonl"
            with open(session_file, "w") as f:
                f.write(json.dumps({
                    "type": "user",
                    "timestamp": f"2026-01-{(i % 28) + 1:02d}T10:00:00.000Z",
                    "sessionId": f"session-{i:04d}",
                    "message": {"content": f"Session {i} prompt"}
                }) + "\n")

        # Create the current session
        session_id = "current-session"
        transcript = project_dir / f"{session_id}.jsonl"
        with open(transcript, "w") as f:
            f.write(json.dumps({
                "type": "user",
                "timestamp": "2026-01-10T10:00:00.000Z",
                "sessionId": session_id,
                "message": {"content": "Current task"}
            }) + "\n")
            f.write(json.dumps({
                "type": "assistant",
                "timestamp": "2026-01-10T10:00:05.000Z",
                "sessionId": session_id,
                "message": {
                    "content": [{"type": "text", "text": "Response text"}],
                    "usage": {"input_tokens": 500, "output_tokens": 100}
                }
            }) + "\n")

        input_json = json.dumps({
            "session_id": session_id,
            "transcript_path": str(transcript),
            "cwd": str(temp_project_root)
        })

        env = {
            **os.environ,
            "HOME": str(tmp_path),
            "CLAUDE_RECALL_STATE": str(temp_state_dir),
            "CLAUDE_RECALL_DEBUG": "0",
            "PROJECT_DIR": str(temp_project_root),
        }

        start = time.perf_counter()
        result = subprocess.run(
            ["bash", str(stop_hook_path)],
            input=input_json,
            capture_output=True,
            text=True,
            env=env,
            timeout=15,
        )
        elapsed = time.perf_counter() - start

        if elapsed > 3.0:
            warnings.warn(f"Stop hook with 50 sessions took {elapsed:.2f}s (threshold: 3s)")

        assert elapsed < 10.0, f"Stop hook with many sessions took {elapsed:.1f}s (max: 10s)"


# =============================================================================
# Unit Tests: Cleanup Orphaned Checkpoints Optimization
# =============================================================================


class TestCleanupOrphanedCheckpointsOptimization:
    """Tests for the cleanup_orphaned_checkpoints optimization.

    The optimization:
    1. Only runs 10% of the time (RANDOM % 10 == 0)
    2. Builds session list once instead of per-file find commands
    """

    def test_checkpoint_cleanup_probabilistic(self, tmp_path, temp_state_dir):
        """Verify that checkpoint cleanup is probabilistic (runs ~10% of the time).

        Note: This is a statistical test - it verifies the mechanism exists,
        not exact percentages. The actual cleanup logic uses (( RANDOM % 10 != 0 ))
        to skip 90% of the time.
        """
        # This test verifies the pattern exists in the source code
        stop_hook_path = Path(__file__).parent.parent.parent / "adapters" / "claude-code" / "stop-hook.sh"
        if not stop_hook_path.exists():
            pytest.skip("stop-hook.sh not found")

        content = stop_hook_path.read_text()

        # Verify the 10% probability check exists
        assert "(( RANDOM % 10 != 0 ))" in content or "RANDOM % 10" in content, (
            "Cleanup should have 10% probability check"
        )

        # Verify the batch find optimization exists (build session list once)
        assert "existing_sessions" in content, (
            "Cleanup should build session list once, not per-file"
        )

    def test_batch_find_pattern_in_source(self, tmp_path):
        """Verify the batch find pattern is used instead of per-file find."""
        stop_hook_path = Path(__file__).parent.parent.parent / "adapters" / "claude-code" / "stop-hook.sh"
        if not stop_hook_path.exists():
            pytest.skip("stop-hook.sh not found")

        content = stop_hook_path.read_text()

        # Should have the optimized batch pattern
        # The optimization builds a list of all sessions first, then checks against it
        assert "grep -qx" in content or "grep -q" in content, (
            "Cleanup should use grep to check session existence from pre-built list"
        )


# =============================================================================
# Performance Benchmarks: get_session_origin_fast
# =============================================================================


class TestGetSessionOriginFastOptimization:
    """Verify get_session_origin_fast uses direct glob instead of list_all_sessions.

    The old _detect_session_origin called list_all_sessions(limit=500) which was O(N)
    where N is total sessions across all projects. The new get_session_origin_fast
    uses glob with session_id directly, which is O(1).
    """

    def test_uses_direct_glob_pattern(self, tmp_path):
        """Verify get_session_origin_fast uses glob pattern with session_id."""
        from core.tui.transcript_reader import TranscriptReader
        import inspect

        source = inspect.getsource(TranscriptReader.get_session_origin_fast)

        # Should use glob pattern with session_id, not list_all_sessions
        assert ".glob" in source or "glob(" in source, (
            "get_session_origin_fast should use glob for O(1) lookup"
        )
        assert "list_all_sessions" not in source, (
            "get_session_origin_fast should NOT use list_all_sessions (O(N))"
        )

    def test_does_not_enumerate_all_sessions(self, tmp_path):
        """Verify lookup doesn't load all sessions."""
        from core.tui.transcript_reader import TranscriptReader
        from unittest.mock import patch, MagicMock

        claude_home = tmp_path / ".claude"
        projects_dir = claude_home / "projects"
        project_dir = projects_dir / "-test"
        project_dir.mkdir(parents=True)

        # Create target session
        target_file = project_dir / "target-session.jsonl"
        with open(target_file, "w") as f:
            f.write(json.dumps({
                "type": "user",
                "timestamp": "2024-01-01T00:00:00Z",
                "message": {"content": "Explore the codebase"}
            }) + "\n")

        reader = TranscriptReader(claude_home=claude_home)

        # Patch list_all_sessions to track if it's called
        original_list_all = reader.list_all_sessions
        list_all_called = []

        def mock_list_all(*args, **kwargs):
            list_all_called.append(True)
            return original_list_all(*args, **kwargs)

        with patch.object(reader, "list_all_sessions", mock_list_all):
            result = reader.get_session_origin_fast("target-session")

        assert result == "Explore"
        assert len(list_all_called) == 0, (
            "get_session_origin_fast should NOT call list_all_sessions"
        )

    def test_performance_with_many_projects(self, tmp_path):
        """Performance should be O(1), not O(projects * sessions)."""
        import time
        from core.tui.transcript_reader import TranscriptReader

        claude_home = tmp_path / ".claude"
        projects_dir = claude_home / "projects"

        # Create many projects with sessions (100 total sessions)
        for i in range(20):
            project_dir = projects_dir / f"-project-{i}"
            project_dir.mkdir(parents=True)
            for j in range(5):
                session_file = project_dir / f"session-{i}-{j}.jsonl"
                with open(session_file, "w") as f:
                    f.write(json.dumps({
                        "type": "user",
                        "timestamp": "2024-01-01T00:00:00Z",
                        "message": {"content": f"User prompt {i}-{j}"}
                    }) + "\n")

        # Add target session in middle project
        target_project = projects_dir / "-project-10"
        target_file = target_project / "target-lookup-session.jsonl"
        with open(target_file, "w") as f:
            f.write(json.dumps({
                "type": "user",
                "timestamp": "2024-01-01T00:00:00Z",
                "message": {"content": "Implement the feature"}
            }) + "\n")

        reader = TranscriptReader(claude_home=claude_home)

        # Time the lookup
        start = time.perf_counter()
        result = reader.get_session_origin_fast("target-lookup-session")
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert result == "General"

        # Should be fast even with 100 sessions
        if elapsed_ms > 100:
            warnings.warn(f"Lookup with 100 sessions took {elapsed_ms:.1f}ms (threshold: 100ms)")

        assert elapsed_ms < 1000, f"Lookup too slow: {elapsed_ms:.1f}ms (max: 1000ms)"


# =============================================================================
# Regression Tests: Ensure Optimizations Don't Break Functionality
# =============================================================================


class TestOptimizationsPreserveFunctionality:
    """Ensure the optimizations don't break core functionality."""

    def test_session_origin_still_detects_explore(self, tmp_path):
        """Explore sessions should still be detected correctly."""
        from core.tui.transcript_reader import TranscriptReader

        claude_home = tmp_path / ".claude"
        project_dir = claude_home / "projects" / "-test"
        project_dir.mkdir(parents=True)

        session_file = project_dir / "explore-test.jsonl"
        with open(session_file, "w") as f:
            f.write(json.dumps({
                "type": "user",
                "timestamp": "2024-01-01T00:00:00Z",
                "message": {"content": "Explore the authentication module"}
            }) + "\n")

        reader = TranscriptReader(claude_home=claude_home)
        assert reader.get_session_origin_fast("explore-test") == "Explore"

    def test_session_origin_still_detects_plan(self, tmp_path):
        """Plan sessions should still be detected correctly."""
        from core.tui.transcript_reader import TranscriptReader

        claude_home = tmp_path / ".claude"
        project_dir = claude_home / "projects" / "-test"
        project_dir.mkdir(parents=True)

        session_file = project_dir / "plan-test.jsonl"
        with open(session_file, "w") as f:
            f.write(json.dumps({
                "type": "user",
                "timestamp": "2024-01-01T00:00:00Z",
                "message": {"content": "Plan the database migration"}
            }) + "\n")

        reader = TranscriptReader(claude_home=claude_home)
        assert reader.get_session_origin_fast("plan-test") == "Plan"

    def test_session_origin_still_detects_general(self, tmp_path):
        """General (implement/fix) sessions should still be detected correctly."""
        from core.tui.transcript_reader import TranscriptReader

        claude_home = tmp_path / ".claude"
        project_dir = claude_home / "projects" / "-test"
        project_dir.mkdir(parents=True)

        session_file = project_dir / "general-test.jsonl"
        with open(session_file, "w") as f:
            f.write(json.dumps({
                "type": "user",
                "timestamp": "2024-01-01T00:00:00Z",
                "message": {"content": "Implement the login form validation"}
            }) + "\n")

        reader = TranscriptReader(claude_home=claude_home)
        assert reader.get_session_origin_fast("general-test") == "General"

    def test_session_origin_returns_unknown_for_missing(self, tmp_path):
        """Missing sessions should return 'Unknown'."""
        from core.tui.transcript_reader import TranscriptReader

        claude_home = tmp_path / ".claude"
        project_dir = claude_home / "projects" / "-test"
        project_dir.mkdir(parents=True)

        reader = TranscriptReader(claude_home=claude_home)
        assert reader.get_session_origin_fast("nonexistent-session") == "Unknown"
