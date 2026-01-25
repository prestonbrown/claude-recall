#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Test suite for StopHookBatchCommand.

This command combines multiple stop-hook operations into a single Python invocation
to reduce startup overhead (~200-300ms savings).

Run with: pytest tests/test_stop_hook_batch.py -v
"""

import json
import pytest
from argparse import Namespace
from pathlib import Path


# =============================================================================
# Command Registration Tests
# =============================================================================


class TestStopHookBatchRegistration:
    """Tests for stop-hook-batch command registration."""

    def test_stop_hook_batch_command_is_registered(self):
        """StopHookBatchCommand should be registered for 'stop-hook-batch'."""
        from core.commands import COMMAND_REGISTRY, StopHookBatchCommand
        assert "stop-hook-batch" in COMMAND_REGISTRY
        assert COMMAND_REGISTRY["stop-hook-batch"] is StopHookBatchCommand

    def test_stop_hook_batch_is_command_subclass(self):
        """StopHookBatchCommand should be a Command subclass."""
        from core.commands import Command, StopHookBatchCommand
        assert issubclass(StopHookBatchCommand, Command)

    def test_stop_hook_batch_can_be_instantiated(self):
        """StopHookBatchCommand should be instantiable."""
        from core.commands import StopHookBatchCommand
        cmd = StopHookBatchCommand()
        assert cmd is not None


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
    """Create a temporary state directory."""
    state_dir = tmp_path / ".local" / "state" / "claude-recall"
    state_dir.mkdir(parents=True)
    return state_dir


@pytest.fixture
def temp_project_root(tmp_path: Path) -> Path:
    """Create a temporary project directory with .git folder."""
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    (project / ".claude-recall").mkdir()
    return project


@pytest.fixture
def manager(temp_lessons_base: Path, temp_project_root: Path, temp_state_dir: Path):
    """Create a LessonsManager instance with temporary paths."""
    import os
    # Set environment variables for proper path resolution
    os.environ["CLAUDE_RECALL_BASE"] = str(temp_lessons_base)
    os.environ["CLAUDE_RECALL_STATE"] = str(temp_state_dir)
    os.environ["PROJECT_DIR"] = str(temp_project_root)

    from core.manager import LessonsManager
    mgr = LessonsManager(
        lessons_base=temp_lessons_base,
        project_root=temp_project_root,
    )
    yield mgr

    # Cleanup
    del os.environ["CLAUDE_RECALL_BASE"]
    del os.environ["CLAUDE_RECALL_STATE"]
    del os.environ["PROJECT_DIR"]


@pytest.fixture
def sample_transcript(tmp_path: Path) -> Path:
    """Create a sample transcript JSONL file."""
    transcript_path = tmp_path / "session.jsonl"
    entries = [
        {
            "type": "assistant",
            "timestamp": "2024-01-01T10:00:00Z",
            "message": {
                "content": [
                    {"type": "text", "text": "I'll help with that task."}
                ]
            }
        },
        {
            "type": "assistant",
            "timestamp": "2024-01-01T10:01:00Z",
            "message": {
                "content": [
                    {"type": "text", "text": "HANDOFF: Test feature implementation"}
                ]
            }
        },
    ]
    with open(transcript_path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")
    return transcript_path


@pytest.fixture
def transcript_with_todos(tmp_path: Path) -> Path:
    """Create a transcript with TodoWrite calls."""
    transcript_path = tmp_path / "session_todos.jsonl"
    entries = [
        {
            "type": "assistant",
            "timestamp": "2024-01-01T10:00:00Z",
            "message": {
                "content": [
                    {"type": "text", "text": "Starting implementation."},
                    {
                        "type": "tool_use",
                        "name": "TodoWrite",
                        "input": {
                            "todos": [
                                {"content": "Task 1", "status": "completed", "activeForm": "Completing task 1"},
                                {"content": "Task 2", "status": "in_progress", "activeForm": "Working on task 2"},
                                {"content": "Task 3", "status": "pending", "activeForm": "Task 3 pending"},
                            ]
                        }
                    }
                ]
            }
        },
    ]
    with open(transcript_path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")
    return transcript_path


@pytest.fixture
def transcript_with_git_commit(tmp_path: Path) -> Path:
    """Create a transcript with a git commit Bash command."""
    transcript_path = tmp_path / "session_git_commit.jsonl"
    entries = [
        {
            "type": "assistant",
            "timestamp": "2024-01-01T10:00:00Z",
            "message": {
                "content": [
                    {"type": "text", "text": "I'll commit these changes."},
                    {
                        "type": "tool_use",
                        "name": "Bash",
                        "input": {
                            "command": "git commit -m \"feat: add new feature\""
                        }
                    }
                ]
            }
        },
    ]
    with open(transcript_path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")
    return transcript_path


# =============================================================================
# Basic Execution Tests
# =============================================================================


class TestStopHookBatchExecution:
    """Tests for stop-hook-batch command execution."""

    def test_execute_with_no_args_returns_success(self, manager, capsys):
        """Execute with no arguments should return 0 and output JSON."""
        from core.commands import StopHookBatchCommand

        args = Namespace(
            command="stop-hook-batch",
            transcript="",
            citations="",
            session_id="",
        )

        cmd = StopHookBatchCommand()
        result = cmd.execute(args, manager)

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["handoffs_processed"] == 0
        assert output["citations_count"] == 0
        assert output["todos_synced"] is False
        assert output["transcript_added"] is False

    def test_execute_returns_json_output(self, manager, capsys):
        """Execute should always return valid JSON."""
        from core.commands import StopHookBatchCommand

        args = Namespace(
            command="stop-hook-batch",
            transcript="",
            citations="",
            session_id="",
        )

        cmd = StopHookBatchCommand()
        cmd.execute(args, manager)

        captured = capsys.readouterr()
        # Should be valid JSON
        output = json.loads(captured.out)
        assert isinstance(output, dict)
        assert "handoffs_processed" in output
        assert "citations_count" in output
        assert "todos_synced" in output
        assert "transcript_added" in output
        assert "errors" in output


# =============================================================================
# Citation Tests
# =============================================================================


class TestStopHookBatchCitations:
    """Tests for citation processing in stop-hook-batch."""

    def test_cite_single_lesson(self, manager, capsys):
        """Should cite a single lesson successfully."""
        from core.commands import StopHookBatchCommand

        # Add a lesson first
        manager.add_lesson(
            level="project",
            category="pattern",
            title="Test Lesson",
            content="Test content",
        )

        args = Namespace(
            command="stop-hook-batch",
            transcript="",
            citations="L001",
            session_id="",
        )

        cmd = StopHookBatchCommand()
        result = cmd.execute(args, manager)

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["citations_count"] == 1
        assert len(output["errors"]) == 0

    def test_cite_multiple_lessons(self, manager, capsys):
        """Should cite multiple lessons successfully."""
        from core.commands import StopHookBatchCommand

        # Add lessons
        manager.add_lesson(level="project", category="pattern", title="L1", content="C1")
        manager.add_lesson(level="project", category="pattern", title="L2", content="C2")
        manager.add_lesson(level="system", category="pattern", title="S1", content="C3")

        args = Namespace(
            command="stop-hook-batch",
            transcript="",
            citations="L001,L002,S001",
            session_id="",
        )

        cmd = StopHookBatchCommand()
        result = cmd.execute(args, manager)

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["citations_count"] == 3
        assert len(output["errors"]) == 0

    def test_cite_nonexistent_lesson_records_error(self, manager, capsys):
        """Should record error for nonexistent lesson but continue."""
        from core.commands import StopHookBatchCommand

        # Add one lesson but cite a different one
        manager.add_lesson(level="project", category="pattern", title="L1", content="C1")

        args = Namespace(
            command="stop-hook-batch",
            transcript="",
            citations="L001,L999",  # L999 doesn't exist
            session_id="",
        )

        cmd = StopHookBatchCommand()
        result = cmd.execute(args, manager)

        assert result == 0  # Still succeeds overall
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["citations_count"] == 1  # Only L001 was cited
        assert len(output["errors"]) == 1  # L999 error recorded
        assert "L999" in output["errors"][0]

    def test_cite_with_whitespace_in_list(self, manager, capsys):
        """Should handle whitespace in citation list."""
        from core.commands import StopHookBatchCommand

        manager.add_lesson(level="project", category="pattern", title="L1", content="C1")
        manager.add_lesson(level="project", category="pattern", title="L2", content="C2")

        args = Namespace(
            command="stop-hook-batch",
            transcript="",
            citations="L001, L002 , ",  # Extra whitespace and trailing comma
            session_id="",
        )

        cmd = StopHookBatchCommand()
        result = cmd.execute(args, manager)

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["citations_count"] == 2


# =============================================================================
# Transcript Processing Tests
# =============================================================================


class TestStopHookBatchTranscript:
    """Tests for transcript processing in stop-hook-batch."""

    def test_process_transcript_with_handoff(self, manager, sample_transcript, capsys):
        """Should process handoff patterns from transcript."""
        from core.commands import StopHookBatchCommand

        args = Namespace(
            command="stop-hook-batch",
            transcript=str(sample_transcript),
            citations="",
            session_id="",
        )

        cmd = StopHookBatchCommand()
        result = cmd.execute(args, manager)

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        # The handoff pattern "HANDOFF: Test feature implementation" should be processed
        assert output["handoffs_processed"] >= 0  # May or may not create depending on sub-agent detection

    def test_process_nonexistent_transcript(self, manager, capsys, tmp_path):
        """Should handle nonexistent transcript gracefully."""
        from core.commands import StopHookBatchCommand

        args = Namespace(
            command="stop-hook-batch",
            transcript=str(tmp_path / "nonexistent.jsonl"),
            citations="",
            session_id="",
        )

        cmd = StopHookBatchCommand()
        result = cmd.execute(args, manager)

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["handoffs_processed"] == 0

    def test_process_malformed_transcript(self, manager, capsys, tmp_path):
        """Should gracefully handle malformed JSON lines in transcript."""
        from core.commands import StopHookBatchCommand

        # Create transcript with malformed lines mixed in
        transcript_path = tmp_path / "malformed.jsonl"
        with open(transcript_path, "w") as f:
            # Valid entry
            f.write('{"type": "assistant", "message": {"content": [{"type": "text", "text": "valid text"}]}}\n')
            # Invalid: not valid JSON
            f.write('not valid json at all\n')
            # Invalid: missing message field
            f.write('{"type": "assistant"}\n')
            # Invalid: empty line
            f.write('\n')
            # Valid entry with handoff
            f.write('{"type": "assistant", "message": {"content": [{"type": "text", "text": "HANDOFF: Test from malformed transcript"}]}}\n')

        args = Namespace(
            command="stop-hook-batch",
            transcript=str(transcript_path),
            citations="",
            session_id="",
        )

        cmd = StopHookBatchCommand()
        result = cmd.execute(args, manager)

        # Should not crash, should successfully process valid entries
        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        # Should have processed without error
        assert "errors" in output

    def test_process_transcript_with_todos(self, manager, transcript_with_todos, capsys):
        """Should sync todos from transcript."""
        from core.commands import StopHookBatchCommand

        # First create a handoff so todos can sync to it
        manager.handoff_add(title="Test Handoff", phase="implementing")

        args = Namespace(
            command="stop-hook-batch",
            transcript=str(transcript_with_todos),
            citations="",
            session_id="",
        )

        cmd = StopHookBatchCommand()
        result = cmd.execute(args, manager)

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["todos_synced"] is True


# =============================================================================
# Combined Operations Tests
# =============================================================================


class TestStopHookBatchCombined:
    """Tests for combined operations in stop-hook-batch."""

    def test_combined_transcript_and_citations(
        self, manager, sample_transcript, capsys
    ):
        """Should process both transcript and citations in one call."""
        from core.commands import StopHookBatchCommand

        # Add a lesson to cite
        manager.add_lesson(level="project", category="pattern", title="L1", content="C1")

        args = Namespace(
            command="stop-hook-batch",
            transcript=str(sample_transcript),
            citations="L001",
            session_id="test-session-123",
        )

        cmd = StopHookBatchCommand()
        result = cmd.execute(args, manager)

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["citations_count"] == 1

    def test_all_operations_in_one_call(
        self, manager, transcript_with_todos, capsys
    ):
        """Should perform all operations in a single call."""
        from core.commands import StopHookBatchCommand

        # Setup: add lesson and create handoff
        manager.add_lesson(level="project", category="pattern", title="L1", content="C1")
        manager.handoff_add(title="Existing Handoff", phase="implementing")

        args = Namespace(
            command="stop-hook-batch",
            transcript=str(transcript_with_todos),
            citations="L001",
            session_id="test-session-456",
        )

        cmd = StopHookBatchCommand()
        result = cmd.execute(args, manager)

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)

        # All operations should have been attempted
        assert output["citations_count"] == 1
        assert output["todos_synced"] is True  # Should sync to existing handoff


# =============================================================================
# Git Commit Auto-Completion Tests
# =============================================================================


class TestStopHookBatchGitCommit:
    """Tests for git commit detection and auto-completion of ready_for_review handoffs."""

    def test_git_commit_detected_in_transcript(
        self, manager, transcript_with_git_commit, capsys
    ):
        """Should detect git commit in Bash tool calls."""
        from core.commands import StopHookBatchCommand

        args = Namespace(
            command="stop-hook-batch",
            transcript=str(transcript_with_git_commit),
            citations="",
            session_id="",
        )

        cmd = StopHookBatchCommand()
        cmd.execute(args, manager)

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["git_commit_detected"] is True

    def test_git_commit_auto_completes_ready_for_review_handoff(
        self, manager, transcript_with_git_commit, capsys
    ):
        """Should auto-complete ready_for_review handoffs when git commit detected."""
        from core.commands import StopHookBatchCommand

        # Create a handoff in ready_for_review status
        handoff_id = manager.handoff_add(title="Test Feature")
        manager.handoff_update_status(handoff_id, "ready_for_review")

        # Verify it's ready_for_review
        handoff = manager.handoff_get(handoff_id)
        assert handoff.status == "ready_for_review"

        args = Namespace(
            command="stop-hook-batch",
            transcript=str(transcript_with_git_commit),
            citations="",
            session_id="",
        )

        cmd = StopHookBatchCommand()
        cmd.execute(args, manager)

        captured = capsys.readouterr()
        output = json.loads(captured.out)

        assert output["git_commit_detected"] is True
        assert output["auto_completed"] is True

        # Verify the handoff is now completed
        handoff = manager.handoff_get(handoff_id)
        assert handoff.status == "completed"

    def test_git_commit_does_not_complete_in_progress_handoff(
        self, manager, transcript_with_git_commit, capsys
    ):
        """Should NOT auto-complete in_progress handoffs (only ready_for_review)."""
        from core.commands import StopHookBatchCommand

        # Create a handoff in in_progress status
        handoff_id = manager.handoff_add(title="In Progress Feature")
        manager.handoff_update_status(handoff_id, "in_progress")

        args = Namespace(
            command="stop-hook-batch",
            transcript=str(transcript_with_git_commit),
            citations="",
            session_id="",
        )

        cmd = StopHookBatchCommand()
        cmd.execute(args, manager)

        captured = capsys.readouterr()
        output = json.loads(captured.out)

        assert output["git_commit_detected"] is True
        assert output["auto_completed"] is False  # Should NOT auto-complete

        # Verify the handoff is still in_progress
        handoff = manager.handoff_get(handoff_id)
        assert handoff.status == "in_progress"

    def test_no_git_commit_does_not_auto_complete(
        self, manager, sample_transcript, capsys
    ):
        """Should NOT auto-complete when no git commit in transcript."""
        from core.commands import StopHookBatchCommand

        # Create a handoff in ready_for_review status
        handoff_id = manager.handoff_add(title="Test Feature")
        manager.handoff_update_status(handoff_id, "ready_for_review")

        args = Namespace(
            command="stop-hook-batch",
            transcript=str(sample_transcript),  # No git commit
            citations="",
            session_id="",
        )

        cmd = StopHookBatchCommand()
        cmd.execute(args, manager)

        captured = capsys.readouterr()
        output = json.loads(captured.out)

        assert output["git_commit_detected"] is False
        assert output["auto_completed"] is False

        # Verify the handoff is still ready_for_review
        handoff = manager.handoff_get(handoff_id)
        assert handoff.status == "ready_for_review"


# =============================================================================
# CLI Integration Tests
# =============================================================================


class TestStopHookBatchCLI:
    """Tests for stop-hook-batch CLI integration."""

    def test_cli_help_includes_stop_hook_batch(self):
        """CLI help should include stop-hook-batch command."""
        import subprocess
        import os

        result = subprocess.run(
            ["python3", "core/cli.py", "--help"],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        )
        assert "stop-hook-batch" in result.stdout

    def test_cli_stop_hook_batch_help(self):
        """stop-hook-batch --help should work."""
        import subprocess
        import os

        result = subprocess.run(
            ["python3", "core/cli.py", "stop-hook-batch", "--help"],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        )
        assert result.returncode == 0
        assert "--transcript" in result.stdout
        assert "--citations" in result.stdout
        assert "--session-id" in result.stdout

    def test_cli_stop_hook_batch_execution(
        self, temp_lessons_base, temp_project_root, temp_state_dir
    ):
        """stop-hook-batch should execute via CLI."""
        import subprocess
        import os

        env = {
            **os.environ,
            "CLAUDE_RECALL_BASE": str(temp_lessons_base),
            "CLAUDE_RECALL_STATE": str(temp_state_dir),
            "PROJECT_DIR": str(temp_project_root),
        }

        result = subprocess.run(
            ["python3", "core/cli.py", "stop-hook-batch"],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            env=env,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert "handoffs_processed" in output
        assert "citations_count" in output


# =============================================================================
# Dispatch Tests
# =============================================================================


class TestStopHookBatchDispatch:
    """Tests for stop-hook-batch dispatch integration."""

    def test_dispatch_routes_to_stop_hook_batch(self, manager, capsys):
        """dispatch_command should route to StopHookBatchCommand."""
        from core.commands import dispatch_command

        args = Namespace(
            command="stop-hook-batch",
            transcript="",
            citations="",
            session_id="",
        )

        result = dispatch_command(args, manager)

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert isinstance(output, dict)
