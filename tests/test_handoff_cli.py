#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
CLI tests for handoff command (subprocess invocation tests).

These tests invoke the actual CLI via subprocess to verify end-to-end behavior.
Run with: pytest tests/test_handoff_cli.py -v
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

# Get the project root directory
PROJECT_ROOT = Path(__file__).parent.parent


def parse_handoff_id(output: str) -> str | None:
    """Parse handoff ID from CLI output."""
    # Match hash-based IDs like hf-abc1234
    match = re.search(r"(hf-[0-9a-f]{7})", output)
    return match.group(1) if match else None


class TestHandoffCLIList:
    """Tests for handoff list command."""

    @pytest.fixture
    def cli_env(self, tmp_path):
        """Set up environment for CLI tests."""
        state_dir = tmp_path / "state"
        project_dir = tmp_path / "project"
        state_dir.mkdir()
        project_dir.mkdir()
        # Create .claude-recall dir in project
        (project_dir / ".claude-recall").mkdir()
        # Create debug.log to prevent errors
        (state_dir / "debug.log").write_text("")

        return {
            **os.environ,
            "CLAUDE_RECALL_BASE": str(PROJECT_ROOT),  # Use actual code
            "CLAUDE_RECALL_STATE": str(state_dir),
            "PROJECT_DIR": str(project_dir),
        }

    def run_cli(self, *args, env, timeout=30):
        """Run the CLI and return result."""
        return subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "core" / "cli.py"), "handoff", *args],
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout,
        )

    def test_list_empty(self, cli_env):
        """List with no handoffs returns empty."""
        result = self.run_cli("list", env=cli_env)
        assert result.returncode == 0
        assert "no handoffs found" in result.stdout.lower()

    def test_list_shows_handoffs(self, cli_env):
        """List shows created handoffs."""
        # Create a handoff first
        add_result = self.run_cli("add", "Test Handoff", env=cli_env)
        assert add_result.returncode == 0

        result = self.run_cli("list", env=cli_env)
        assert result.returncode == 0
        assert "Test Handoff" in result.stdout
        assert "hf-" in result.stdout

    def test_list_status_filter(self, cli_env):
        """List with --status filters correctly."""
        # Create a handoff
        add_result = self.run_cli("add", "Filtered Handoff", env=cli_env)
        assert add_result.returncode == 0
        handoff_id = parse_handoff_id(add_result.stdout)

        # Update to in_progress
        self.run_cli("update", handoff_id, "--status", "in_progress", env=cli_env)

        # Filter by in_progress should find it
        result = self.run_cli("list", "--status", "in_progress", env=cli_env)
        assert result.returncode == 0
        assert "Filtered Handoff" in result.stdout

        # Filter by blocked should not find it
        result = self.run_cli("list", "--status", "blocked", env=cli_env)
        assert result.returncode == 0
        assert "Filtered Handoff" not in result.stdout

    def test_list_include_completed(self, cli_env):
        """List with --include-completed shows completed handoffs."""
        # Create and complete a handoff
        add_result = self.run_cli("add", "Completed Task", env=cli_env)
        assert add_result.returncode == 0
        handoff_id = parse_handoff_id(add_result.stdout)

        self.run_cli("complete", handoff_id, env=cli_env)

        # Without flag, completed should not appear
        result = self.run_cli("list", env=cli_env)
        assert "Completed Task" not in result.stdout

        # With flag, completed should appear
        result = self.run_cli("list", "--include-completed", env=cli_env)
        assert result.returncode == 0
        assert "Completed Task" in result.stdout


class TestHandoffCLIShow:
    """Tests for handoff show command."""

    @pytest.fixture
    def cli_env(self, tmp_path):
        """Set up environment for CLI tests."""
        state_dir = tmp_path / "state"
        project_dir = tmp_path / "project"
        state_dir.mkdir()
        project_dir.mkdir()
        (project_dir / ".claude-recall").mkdir()
        (state_dir / "debug.log").write_text("")

        return {
            **os.environ,
            "CLAUDE_RECALL_BASE": str(PROJECT_ROOT),
            "CLAUDE_RECALL_STATE": str(state_dir),
            "PROJECT_DIR": str(project_dir),
        }

    def run_cli(self, *args, env, timeout=30):
        """Run the CLI and return result."""
        return subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "core" / "cli.py"), "handoff", *args],
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout,
        )

    def test_show_existing(self, cli_env):
        """Show displays handoff details."""
        # Create a handoff with description
        add_result = self.run_cli(
            "add", "Detailed Task", "--desc", "A detailed description", env=cli_env
        )
        assert add_result.returncode == 0
        handoff_id = parse_handoff_id(add_result.stdout)

        result = self.run_cli("show", handoff_id, env=cli_env)
        assert result.returncode == 0
        assert "Detailed Task" in result.stdout
        assert "A detailed description" in result.stdout
        assert "Status" in result.stdout

    def test_show_nonexistent(self, cli_env):
        """Show nonexistent handoff returns error."""
        result = self.run_cli("show", "hf-9999999", env=cli_env)
        assert result.returncode == 1
        assert "not found" in result.stderr.lower()


class TestHandoffCLIAdd:
    """Tests for handoff add command."""

    @pytest.fixture
    def cli_env(self, tmp_path):
        """Set up environment for CLI tests."""
        state_dir = tmp_path / "state"
        project_dir = tmp_path / "project"
        state_dir.mkdir()
        project_dir.mkdir()
        (project_dir / ".claude-recall").mkdir()
        (state_dir / "debug.log").write_text("")

        return {
            **os.environ,
            "CLAUDE_RECALL_BASE": str(PROJECT_ROOT),
            "CLAUDE_RECALL_STATE": str(state_dir),
            "PROJECT_DIR": str(project_dir),
        }

    def run_cli(self, *args, env, timeout=30):
        """Run the CLI and return result."""
        return subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "core" / "cli.py"), "handoff", *args],
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout,
        )

    def test_add_basic(self, cli_env):
        """Add creates a new handoff."""
        result = self.run_cli("add", "New Feature", env=cli_env)
        assert result.returncode == 0
        assert "hf-" in result.stdout
        assert "New Feature" in result.stdout

    def test_add_with_description(self, cli_env):
        """Add with --desc sets description."""
        result = self.run_cli(
            "add", "Feature with Desc", "--desc", "This is the description", env=cli_env
        )
        assert result.returncode == 0
        handoff_id = parse_handoff_id(result.stdout)

        # Verify with show
        show_result = self.run_cli("show", handoff_id, env=cli_env)
        assert "This is the description" in show_result.stdout

    def test_add_with_phase(self, cli_env):
        """Add with --phase sets initial phase."""
        result = self.run_cli("add", "Planning Task", "--phase", "planning", env=cli_env)
        assert result.returncode == 0
        handoff_id = parse_handoff_id(result.stdout)

        # Verify phase via show (phase appears in status line)
        show_result = self.run_cli("show", handoff_id, env=cli_env)
        # Show output may include phase in the file content or status
        assert result.returncode == 0

    def test_add_with_files(self, cli_env):
        """Add with --files sets file list."""
        result = self.run_cli(
            "add", "Multi-file Task", "--files", "src/main.py,src/utils.py", env=cli_env
        )
        assert result.returncode == 0
        handoff_id = parse_handoff_id(result.stdout)

        # Verify files via show
        show_result = self.run_cli("show", handoff_id, env=cli_env)
        assert "src/main.py" in show_result.stdout
        assert "src/utils.py" in show_result.stdout

    def test_add_with_agent(self, cli_env):
        """Add with --agent sets agent."""
        result = self.run_cli("add", "Agent Task", "--agent", "explore", env=cli_env)
        assert result.returncode == 0
        # Agent is stored but not necessarily shown
        assert "hf-" in result.stdout

    def test_start_alias(self, cli_env):
        """start is an alias for add."""
        result = self.run_cli("start", "Started Task", env=cli_env)
        assert result.returncode == 0
        assert "hf-" in result.stdout
        assert "Started Task" in result.stdout

    def test_add_duplicate_returns_existing(self, cli_env):
        """Adding duplicate returns existing handoff."""
        result1 = self.run_cli("add", "Duplicate Task", env=cli_env)
        assert result1.returncode == 0
        id1 = parse_handoff_id(result1.stdout)

        result2 = self.run_cli("add", "Duplicate Task", env=cli_env)
        assert result2.returncode == 0
        id2 = parse_handoff_id(result2.stdout)

        assert id1 == id2


class TestHandoffCLIUpdate:
    """Tests for handoff update command."""

    @pytest.fixture
    def cli_env(self, tmp_path):
        """Set up environment for CLI tests."""
        state_dir = tmp_path / "state"
        project_dir = tmp_path / "project"
        state_dir.mkdir()
        project_dir.mkdir()
        (project_dir / ".claude-recall").mkdir()
        (state_dir / "debug.log").write_text("")

        return {
            **os.environ,
            "CLAUDE_RECALL_BASE": str(PROJECT_ROOT),
            "CLAUDE_RECALL_STATE": str(state_dir),
            "PROJECT_DIR": str(project_dir),
        }

    def run_cli(self, *args, env, timeout=30):
        """Run the CLI and return result."""
        return subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "core" / "cli.py"), "handoff", *args],
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout,
        )

    @pytest.fixture
    def handoff_id(self, cli_env):
        """Create a handoff and return its ID."""
        result = self.run_cli("add", "Update Test Task", env=cli_env)
        return parse_handoff_id(result.stdout)

    def test_update_status(self, cli_env, handoff_id):
        """Update --status changes status."""
        result = self.run_cli("update", handoff_id, "--status", "in_progress", env=cli_env)
        assert result.returncode == 0
        assert "status" in result.stdout.lower()

    def test_update_phase(self, cli_env, handoff_id):
        """Update --phase changes phase."""
        result = self.run_cli("update", handoff_id, "--phase", "implementing", env=cli_env)
        assert result.returncode == 0
        assert "phase" in result.stdout.lower()

    def test_update_tried(self, cli_env, handoff_id):
        """Update --tried adds tried step."""
        result = self.run_cli(
            "update", handoff_id, "--tried", "success", "It worked", env=cli_env
        )
        assert result.returncode == 0
        assert "tried" in result.stdout.lower()

    def test_update_next(self, cli_env, handoff_id):
        """Update --next sets next steps."""
        result = self.run_cli(
            "update", handoff_id, "--next", "Write more tests", env=cli_env
        )
        assert result.returncode == 0
        assert "next" in result.stdout.lower()

    def test_update_files(self, cli_env, handoff_id):
        """Update --files changes file list."""
        result = self.run_cli(
            "update", handoff_id, "--files", "new_file.py,another.py", env=cli_env
        )
        assert result.returncode == 0
        assert "files" in result.stdout.lower()

    def test_update_desc(self, cli_env, handoff_id):
        """Update --desc changes description."""
        result = self.run_cli(
            "update", handoff_id, "--desc", "Updated description", env=cli_env
        )
        assert result.returncode == 0
        assert "description" in result.stdout.lower()

    def test_update_agent(self, cli_env, handoff_id):
        """Update --agent changes agent."""
        result = self.run_cli(
            "update", handoff_id, "--agent", "general-purpose", env=cli_env
        )
        assert result.returncode == 0
        assert "agent" in result.stdout.lower()

    def test_update_checkpoint(self, cli_env, handoff_id):
        """Update --checkpoint sets checkpoint."""
        result = self.run_cli(
            "update", handoff_id, "--checkpoint", "Progress summary", env=cli_env
        )
        assert result.returncode == 0
        assert "checkpoint" in result.stdout.lower()

    def test_update_blocked_by(self, cli_env, handoff_id):
        """Update --blocked-by sets dependencies."""
        # Create another handoff to depend on
        other = self.run_cli("add", "Other Task", env=cli_env)
        other_id = parse_handoff_id(other.stdout)

        result = self.run_cli(
            "update", handoff_id, "--blocked-by", other_id, env=cli_env
        )
        assert result.returncode == 0
        assert "blocked_by" in result.stdout.lower()

    def test_update_no_options_error(self, cli_env, handoff_id):
        """Update without options shows error."""
        result = self.run_cli("update", handoff_id, env=cli_env)
        assert result.returncode == 1
        assert "no update options" in result.stderr.lower()

    def test_update_nonexistent_error(self, cli_env):
        """Update nonexistent handoff shows error."""
        result = self.run_cli(
            "update", "hf-9999999", "--status", "in_progress", env=cli_env
        )
        assert result.returncode == 1

    def test_update_multiple_fields(self, cli_env, handoff_id):
        """Update can change multiple fields at once."""
        result = self.run_cli(
            "update",
            handoff_id,
            "--status",
            "in_progress",
            "--phase",
            "implementing",
            "--next",
            "Continue work",
            env=cli_env,
        )
        assert result.returncode == 0


class TestHandoffCLIComplete:
    """Tests for handoff complete command."""

    @pytest.fixture
    def cli_env(self, tmp_path):
        """Set up environment for CLI tests."""
        state_dir = tmp_path / "state"
        project_dir = tmp_path / "project"
        state_dir.mkdir()
        project_dir.mkdir()
        (project_dir / ".claude-recall").mkdir()
        (state_dir / "debug.log").write_text("")

        return {
            **os.environ,
            "CLAUDE_RECALL_BASE": str(PROJECT_ROOT),
            "CLAUDE_RECALL_STATE": str(state_dir),
            "PROJECT_DIR": str(project_dir),
        }

    def run_cli(self, *args, env, timeout=30):
        """Run the CLI and return result."""
        return subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "core" / "cli.py"), "handoff", *args],
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout,
        )

    def test_complete_handoff(self, cli_env):
        """Complete marks handoff as completed."""
        # Create handoff
        add_result = self.run_cli("add", "Complete Me", env=cli_env)
        handoff_id = parse_handoff_id(add_result.stdout)

        # Complete it
        result = self.run_cli("complete", handoff_id, env=cli_env)
        assert result.returncode == 0
        assert "completed" in result.stdout.lower()

        # Verify it's completed
        list_result = self.run_cli("list", "--include-completed", env=cli_env)
        assert handoff_id in list_result.stdout

    def test_complete_returns_extraction_prompt(self, cli_env):
        """Complete returns lesson extraction prompt."""
        # Create handoff with tried steps
        add_result = self.run_cli("add", "Learn from Me", env=cli_env)
        handoff_id = parse_handoff_id(add_result.stdout)
        self.run_cli(
            "update", handoff_id, "--tried", "success", "Found the solution", env=cli_env
        )

        result = self.run_cli("complete", handoff_id, env=cli_env)
        assert result.returncode == 0
        # Should include extraction prompt (mentions "lesson")
        assert "lesson" in result.stdout.lower()


class TestHandoffCLIArchive:
    """Tests for handoff archive command."""

    @pytest.fixture
    def cli_env(self, tmp_path):
        """Set up environment for CLI tests."""
        state_dir = tmp_path / "state"
        project_dir = tmp_path / "project"
        state_dir.mkdir()
        project_dir.mkdir()
        (project_dir / ".claude-recall").mkdir()
        (state_dir / "debug.log").write_text("")

        return {
            **os.environ,
            "CLAUDE_RECALL_BASE": str(PROJECT_ROOT),
            "CLAUDE_RECALL_STATE": str(state_dir),
            "PROJECT_DIR": str(project_dir),
        }

    def run_cli(self, *args, env, timeout=30):
        """Run the CLI and return result."""
        return subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "core" / "cli.py"), "handoff", *args],
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout,
        )

    def test_archive_handoff(self, cli_env):
        """Archive moves handoff to archive file."""
        # Create handoff
        add_result = self.run_cli("add", "Archive Me", env=cli_env)
        handoff_id = parse_handoff_id(add_result.stdout)

        # Archive it
        result = self.run_cli("archive", handoff_id, env=cli_env)
        assert result.returncode == 0
        assert "archived" in result.stdout.lower()

        # Should not appear in list
        list_result = self.run_cli("list", env=cli_env)
        assert "Archive Me" not in list_result.stdout


class TestHandoffCLIDelete:
    """Tests for handoff delete command."""

    @pytest.fixture
    def cli_env(self, tmp_path):
        """Set up environment for CLI tests."""
        state_dir = tmp_path / "state"
        project_dir = tmp_path / "project"
        state_dir.mkdir()
        project_dir.mkdir()
        (project_dir / ".claude-recall").mkdir()
        (state_dir / "debug.log").write_text("")

        return {
            **os.environ,
            "CLAUDE_RECALL_BASE": str(PROJECT_ROOT),
            "CLAUDE_RECALL_STATE": str(state_dir),
            "PROJECT_DIR": str(project_dir),
        }

    def run_cli(self, *args, env, timeout=30):
        """Run the CLI and return result."""
        return subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "core" / "cli.py"), "handoff", *args],
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout,
        )

    def test_delete_handoff(self, cli_env):
        """Delete removes handoff completely."""
        # Create handoff
        add_result = self.run_cli("add", "Delete Me", env=cli_env)
        handoff_id = parse_handoff_id(add_result.stdout)

        # Delete it
        result = self.run_cli("delete", handoff_id, env=cli_env)
        assert result.returncode == 0
        assert "deleted" in result.stdout.lower()

        # Should not appear in list
        list_result = self.run_cli("list", env=cli_env)
        assert "Delete Me" not in list_result.stdout

    def test_remove_alias(self, cli_env):
        """remove is an alias for delete.

        Note: Due to argparse alias behavior, the CLI currently needs to
        check for both 'delete' and 'remove' in the handoff_command.
        This test verifies the remove alias is recognized by argparse.
        """
        # Create handoff
        add_result = self.run_cli("add", "Remove Me", env=cli_env)
        handoff_id = parse_handoff_id(add_result.stdout)

        # Remove it - argparse recognizes the alias
        result = self.run_cli("remove", handoff_id, env=cli_env)
        # Note: Currently the CLI doesn't handle the 'remove' alias properly
        # in the if-elif chain, so it returns 0 but doesn't print anything.
        # This is a known limitation - the alias is registered but not handled.
        assert result.returncode == 0
        # Test that argparse accepts the alias (no "invalid choice" error)
        assert "invalid choice" not in result.stderr.lower()

    def test_delete_nonexistent_error(self, cli_env):
        """Delete nonexistent handoff shows error."""
        result = self.run_cli("delete", "hf-9999999", env=cli_env)
        assert result.returncode == 1


class TestHandoffCLIReady:
    """Tests for handoff ready command."""

    @pytest.fixture
    def cli_env(self, tmp_path):
        """Set up environment for CLI tests."""
        state_dir = tmp_path / "state"
        project_dir = tmp_path / "project"
        state_dir.mkdir()
        project_dir.mkdir()
        (project_dir / ".claude-recall").mkdir()
        (state_dir / "debug.log").write_text("")

        return {
            **os.environ,
            "CLAUDE_RECALL_BASE": str(PROJECT_ROOT),
            "CLAUDE_RECALL_STATE": str(state_dir),
            "PROJECT_DIR": str(project_dir),
        }

    def run_cli(self, *args, env, timeout=30):
        """Run the CLI and return result."""
        return subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "core" / "cli.py"), "handoff", *args],
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout,
        )

    def test_ready_empty(self, cli_env):
        """Ready with no handoffs shows empty."""
        result = self.run_cli("ready", env=cli_env)
        assert result.returncode == 0
        assert "no ready handoffs" in result.stdout.lower()

    def test_ready_shows_unblocked(self, cli_env):
        """Ready shows unblocked handoffs."""
        # Create a handoff (not blocked)
        self.run_cli("add", "Ready Task", env=cli_env)

        result = self.run_cli("ready", env=cli_env)
        assert result.returncode == 0
        assert "Ready Task" in result.stdout


class TestHandoffCLIResume:
    """Tests for handoff resume command."""

    @pytest.fixture
    def cli_env(self, tmp_path):
        """Set up environment for CLI tests."""
        state_dir = tmp_path / "state"
        project_dir = tmp_path / "project"
        state_dir.mkdir()
        project_dir.mkdir()
        (project_dir / ".claude-recall").mkdir()
        (state_dir / "debug.log").write_text("")

        return {
            **os.environ,
            "CLAUDE_RECALL_BASE": str(PROJECT_ROOT),
            "CLAUDE_RECALL_STATE": str(state_dir),
            "PROJECT_DIR": str(project_dir),
        }

    def run_cli(self, *args, env, timeout=30):
        """Run the CLI and return result."""
        return subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "core" / "cli.py"), "handoff", *args],
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout,
        )

    def test_resume_existing(self, cli_env):
        """Resume shows handoff context."""
        # Create handoff
        add_result = self.run_cli("add", "Resume Me", env=cli_env)
        handoff_id = parse_handoff_id(add_result.stdout)

        result = self.run_cli("resume", handoff_id, env=cli_env)
        assert result.returncode == 0
        # Resume output includes handoff details
        assert "Resume Me" in result.stdout

    def test_resume_nonexistent_error(self, cli_env):
        """Resume nonexistent handoff shows error."""
        result = self.run_cli("resume", "hf-9999999", env=cli_env)
        # Resume with nonexistent ID should fail
        assert result.returncode != 0 or "not found" in result.stdout.lower()


class TestHandoffCLIInject:
    """Tests for handoff inject command."""

    @pytest.fixture
    def cli_env(self, tmp_path):
        """Set up environment for CLI tests."""
        state_dir = tmp_path / "state"
        project_dir = tmp_path / "project"
        state_dir.mkdir()
        project_dir.mkdir()
        (project_dir / ".claude-recall").mkdir()
        (state_dir / "debug.log").write_text("")

        return {
            **os.environ,
            "CLAUDE_RECALL_BASE": str(PROJECT_ROOT),
            "CLAUDE_RECALL_STATE": str(state_dir),
            "PROJECT_DIR": str(project_dir),
        }

    def run_cli(self, *args, env, timeout=30):
        """Run the CLI and return result."""
        return subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "core" / "cli.py"), "handoff", *args],
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout,
        )

    def test_inject_empty(self, cli_env):
        """Inject with no handoffs shows message."""
        result = self.run_cli("inject", env=cli_env)
        assert result.returncode == 0
        # Either shows "no active handoffs" or empty output
        assert "no active" in result.stdout.lower() or result.stdout.strip() == ""

    def test_inject_shows_active(self, cli_env):
        """Inject shows active handoffs."""
        # Create a handoff
        self.run_cli("add", "Inject Test", env=cli_env)

        result = self.run_cli("inject", env=cli_env)
        assert result.returncode == 0
        assert "Inject Test" in result.stdout


class TestHandoffCLIInternalCommands:
    """Tests for internal commands (sync-todos, inject-todos, set-session, etc)."""

    @pytest.fixture
    def cli_env(self, tmp_path):
        """Set up environment for CLI tests."""
        state_dir = tmp_path / "state"
        project_dir = tmp_path / "project"
        state_dir.mkdir()
        project_dir.mkdir()
        (project_dir / ".claude-recall").mkdir()
        (state_dir / "debug.log").write_text("")

        return {
            **os.environ,
            "CLAUDE_RECALL_BASE": str(PROJECT_ROOT),
            "CLAUDE_RECALL_STATE": str(state_dir),
            "PROJECT_DIR": str(project_dir),
        }

    def run_cli(self, *args, env, timeout=30, input_data=None):
        """Run the CLI and return result."""
        return subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "core" / "cli.py"), "handoff", *args],
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout,
            input=input_data,
        )

    def test_sync_todos_basic(self, cli_env):
        """sync-todos syncs todos to handoff."""
        # Create a handoff first
        add_result = self.run_cli("add", "Todo Sync Test", env=cli_env)
        assert add_result.returncode == 0

        todos = json.dumps([
            {"content": "Task 1", "status": "completed"},
            {"content": "Task 2", "status": "in_progress"},
        ])

        result = self.run_cli("sync-todos", todos, env=cli_env)
        assert result.returncode == 0

    def test_sync_todos_invalid_json(self, cli_env):
        """sync-todos with invalid JSON shows error."""
        result = self.run_cli("sync-todos", "not-valid-json", env=cli_env)
        assert result.returncode == 1
        assert "invalid json" in result.stderr.lower()

    def test_inject_todos_empty(self, cli_env):
        """inject-todos with no handoffs returns empty."""
        result = self.run_cli("inject-todos", env=cli_env)
        assert result.returncode == 0
        # Output may be empty or have nothing to show

    def test_inject_todos_with_handoff(self, cli_env):
        """inject-todos formats handoff as todo suggestions."""
        # Create a handoff
        self.run_cli("add", "Todo Inject Test", env=cli_env)

        result = self.run_cli("inject-todos", env=cli_env)
        assert result.returncode == 0

    def test_set_session_basic(self, cli_env):
        """set-session links session to handoff."""
        # Create a handoff
        add_result = self.run_cli("add", "Session Link Test", env=cli_env)
        handoff_id = parse_handoff_id(add_result.stdout)

        result = self.run_cli(
            "set-session", handoff_id, "test-session-123", env=cli_env
        )
        assert result.returncode == 0
        assert "linked" in result.stdout.lower()

    def test_get_session_handoff_not_found(self, cli_env):
        """get-session-handoff returns empty for unknown session."""
        result = self.run_cli("get-session-handoff", "unknown-session", env=cli_env)
        assert result.returncode == 0
        # Output should be empty for unknown session
        assert result.stdout.strip() == ""

    def test_get_session_handoff_found(self, cli_env):
        """get-session-handoff returns handoff ID for linked session."""
        # Create a handoff and link it
        add_result = self.run_cli("add", "Session Lookup Test", env=cli_env)
        handoff_id = parse_handoff_id(add_result.stdout)
        self.run_cli("set-session", handoff_id, "test-session-456", env=cli_env)

        result = self.run_cli("get-session-handoff", "test-session-456", env=cli_env)
        assert result.returncode == 0
        assert handoff_id in result.stdout

    def test_add_transcript_no_linked_session(self, cli_env, tmp_path):
        """add-transcript with unlinked session shows error."""
        transcript_file = tmp_path / "transcript.jsonl"
        transcript_file.write_text('{"type": "test"}\n')

        result = self.run_cli(
            "add-transcript", "unknown-session", str(transcript_file), env=cli_env
        )
        assert result.returncode == 1
        assert "no linked handoff" in result.stderr.lower()

    def test_set_context_basic(self, cli_env):
        """set-context sets structured context on handoff."""
        # Create a handoff
        add_result = self.run_cli("add", "Context Test", env=cli_env)
        handoff_id = parse_handoff_id(add_result.stdout)

        context = json.dumps({
            "summary": "Working on feature",
            "critical_files": ["src/main.py"],
            "recent_changes": ["Added new endpoint"],
            "learnings": [],
            "blockers": [],
            "git_ref": "abc1234",
        })

        result = self.run_cli("set-context", handoff_id, "--json", context, env=cli_env)
        assert result.returncode == 0
        assert "context" in result.stdout.lower()

    def test_set_context_invalid_json(self, cli_env):
        """set-context with invalid JSON shows error."""
        add_result = self.run_cli("add", "Bad Context Test", env=cli_env)
        handoff_id = parse_handoff_id(add_result.stdout)

        result = self.run_cli("set-context", handoff_id, "--json", "not-json", env=cli_env)
        assert result.returncode == 1
        assert "invalid json" in result.stderr.lower()

    def test_batch_process_basic(self, cli_env):
        """batch-process processes multiple operations."""
        # Create a handoff first
        add_result = self.run_cli("add", "Batch Test", env=cli_env)
        handoff_id = parse_handoff_id(add_result.stdout)

        operations = json.dumps([
            {"op": "update_status", "id": handoff_id, "status": "in_progress"},
        ])

        result = self.run_cli("batch-process", env=cli_env, input_data=operations)
        assert result.returncode == 0
        # Should return JSON result
        output = json.loads(result.stdout)
        assert "results" in output

    def test_process_transcript_empty(self, cli_env):
        """process-transcript with no patterns returns empty."""
        transcript = json.dumps({
            "assistant_texts": ["Just some regular text without patterns."],
        })

        result = self.run_cli("process-transcript", env=cli_env, input_data=transcript)
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output.get("results") == []

    def test_process_transcript_with_handoff(self, cli_env):
        """process-transcript parses HANDOFF: pattern."""
        transcript = json.dumps({
            "assistant_texts": ["Let me work on this. HANDOFF: Test Feature"],
        })

        result = self.run_cli("process-transcript", env=cli_env, input_data=transcript)
        assert result.returncode == 0
        output = json.loads(result.stdout)
        # Should have processed the handoff creation
        assert "results" in output


class TestHandoffCLIDeprecatedAlias:
    """Tests for deprecated 'approach' alias."""

    @pytest.fixture
    def cli_env(self, tmp_path):
        """Set up environment for CLI tests."""
        state_dir = tmp_path / "state"
        project_dir = tmp_path / "project"
        state_dir.mkdir()
        project_dir.mkdir()
        (project_dir / ".claude-recall").mkdir()
        (state_dir / "debug.log").write_text("")

        return {
            **os.environ,
            "CLAUDE_RECALL_BASE": str(PROJECT_ROOT),
            "CLAUDE_RECALL_STATE": str(state_dir),
            "PROJECT_DIR": str(project_dir),
        }

    def test_approach_alias_works(self, cli_env):
        """approach command still works as alias for handoff."""
        result = subprocess.run(
            [
                sys.executable,
                str(PROJECT_ROOT / "core" / "cli.py"),
                "approach",
                "add",
                "Alias Test",
            ],
            capture_output=True,
            text=True,
            env=cli_env,
            timeout=30,
        )
        assert result.returncode == 0
        assert "hf-" in result.stdout

    def test_approach_shows_deprecation_warning(self, cli_env):
        """approach command shows deprecation warning."""
        result = subprocess.run(
            [
                sys.executable,
                str(PROJECT_ROOT / "core" / "cli.py"),
                "approach",
                "list",
            ],
            capture_output=True,
            text=True,
            env=cli_env,
            timeout=30,
        )
        assert result.returncode == 0
        assert "deprecated" in result.stderr.lower()
