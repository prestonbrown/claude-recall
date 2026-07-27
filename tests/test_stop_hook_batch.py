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


@pytest.mark.skip(reason="Python CLI removed - stop-hook-batch now handled by Go binary")
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


# =============================================================================
# Cached Transcript Tests
# =============================================================================


class TestStopHookBatchAILessons:
    """Tests for batch AI lesson processing."""

    def test_ai_lessons_adds_single_lesson(self, manager, capsys):
        """Should add a single AI lesson from JSON."""
        from core.commands import StopHookBatchCommand

        ai_lessons = [
            {
                "category": "pattern",
                "title": "Test AI Lesson",
                "content": "This is test content",
                "type": "informational",
            }
        ]

        args = Namespace(
            command="stop-hook-batch",
            transcript="",
            cached_transcript=False,
            citations="",
            session_id="",
            ai_lessons=json.dumps(ai_lessons),
        )

        cmd = StopHookBatchCommand()
        result = cmd.execute(args, manager)

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["ai_lessons_added"] == 1

    def test_ai_lessons_adds_multiple_lessons(self, manager, capsys):
        """Should add multiple AI lessons in one call."""
        from core.commands import StopHookBatchCommand

        ai_lessons = [
            {"category": "pattern", "title": "Lesson 1", "content": "Content 1", "type": ""},
            {"category": "correction", "title": "Lesson 2", "content": "Content 2", "type": "constraint"},
            {"category": "gotcha", "title": "Lesson 3", "content": "Content 3", "type": ""},
        ]

        args = Namespace(
            command="stop-hook-batch",
            transcript="",
            cached_transcript=False,
            citations="",
            session_id="",
            ai_lessons=json.dumps(ai_lessons),
        )

        cmd = StopHookBatchCommand()
        result = cmd.execute(args, manager)

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["ai_lessons_added"] == 3

    def test_ai_lessons_skips_lessons_without_title(self, manager, capsys):
        """Should skip AI lessons without a title."""
        from core.commands import StopHookBatchCommand

        ai_lessons = [
            {"category": "pattern", "title": "", "content": "No title"},
            {"category": "pattern", "title": "Has title", "content": "Content"},
        ]

        args = Namespace(
            command="stop-hook-batch",
            transcript="",
            cached_transcript=False,
            citations="",
            session_id="",
            ai_lessons=json.dumps(ai_lessons),
        )

        cmd = StopHookBatchCommand()
        cmd.execute(args, manager)

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["ai_lessons_added"] == 1

    def test_ai_lessons_handles_invalid_json(self, manager, capsys):
        """Should handle invalid JSON gracefully."""
        from core.commands import StopHookBatchCommand

        args = Namespace(
            command="stop-hook-batch",
            transcript="",
            cached_transcript=False,
            citations="",
            session_id="",
            ai_lessons="not valid json",
        )

        cmd = StopHookBatchCommand()
        result = cmd.execute(args, manager)

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["ai_lessons_added"] == 0
        assert any("ai_lessons_parse" in e for e in output["errors"])

    def test_ai_lessons_empty_array(self, manager, capsys):
        """Should handle empty AI lessons array."""
        from core.commands import StopHookBatchCommand

        args = Namespace(
            command="stop-hook-batch",
            transcript="",
            cached_transcript=False,
            citations="",
            session_id="",
            ai_lessons="[]",
        )

        cmd = StopHookBatchCommand()
        result = cmd.execute(args, manager)

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["ai_lessons_added"] == 0
        assert len(output["errors"]) == 0
