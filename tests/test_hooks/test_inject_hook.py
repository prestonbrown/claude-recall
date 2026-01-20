#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Tests for inject-hook.sh session-handoff linking behavior.

Run with: ./run-tests.sh tests/test_hooks/test_inject_hook.py -v
"""

import json
import os
import subprocess
from datetime import date
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
    projects_dir.mkdir(parents=True, exist_ok=True)

    # Create settings.json with lessons enabled
    settings = claude_home / "settings.json"
    settings.write_text('{"claudeRecall":{"enabled":true}}')

    return claude_home


@pytest.fixture
def temp_project_root(tmp_path: Path) -> Path:
    """Create a temporary project root with .git directory."""
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    (project / ".git").mkdir(exist_ok=True)
    (project / ".claude-recall").mkdir(exist_ok=True)
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


# =============================================================================
# Session-Handoff Linking Tests
# =============================================================================


class TestInjectHookSessionLinking:
    """Tests for inject hook session-handoff linking behavior."""

    def test_inject_hook_links_session_to_continuation_handoff(
        self, tmp_path, inject_hook_path, temp_claude_home, temp_project_root
    ):
        """
        When inject-hook identifies a handoff to continue via inject-todos,
        it should link the current session to that handoff.

        Bug: inject-hook.sh does not call 'handoff set-session' after getting
        todo_continuation from 'handoff inject-todos'. This means ready_for_review
        handoffs have no sessions associated with them.

        Expected: After inject-hook.sh runs with an active handoff, the
        session-handoffs.json should contain an entry linking the session_id
        to the handoff_id from the continuation.
        """
        # Setup state directory
        state_dir = tmp_path / ".local" / "state" / "claude-recall"
        state_dir.mkdir(parents=True, exist_ok=True)

        # Create empty debug.log to prevent errors
        (state_dir / "debug.log").write_text("")

        # Create a handoff with in_progress status (using correct format)
        # IMPORTANT: Use today's date to avoid auto-archiving (HANDOFF_STALE_DAYS=7)
        handoffs_file = temp_project_root / ".claude-recall" / "HANDOFFS.md"
        handoff_id = "hf-abc1234"
        today = date.today().isoformat()
        handoffs_content = f"""# HANDOFFS.md - Active Work Tracking

> Track ongoing work with tried steps and next steps.
> When completed, review for lessons to extract.

## Active Handoffs


### [{handoff_id}] Test Feature Implementation
- **Status**: in_progress | **Phase**: implementing | **Agent**: user
- **Created**: {today} | **Updated**: {today}
- **Refs**:
- **Description**:
- **Checkpoint**: Finish implementation
- **Next**: Finish the implementation; Run tests

"""
        handoffs_file.write_text(handoffs_content)

        # Create input JSON for the hook with a session_id
        session_id = "test-session-12345"
        input_json = json.dumps({
            "session_id": session_id,
            "cwd": str(temp_project_root)
        })

        # Build environment for subprocess
        env = {
            **{k: v for k, v in os.environ.items() if k in {"PATH", "SHELL", "TERM", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE"}},
            "HOME": str(tmp_path),
            "CLAUDE_RECALL_STATE": str(state_dir),
            "CLAUDE_RECALL_DEBUG": "0",
            "PROJECT_DIR": str(temp_project_root),
        }

        # Run inject-hook.sh
        result = subprocess.run(
            ["bash", str(inject_hook_path)],
            input=input_json,
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )

        # The hook may succeed or fail based on other factors, but we're checking
        # if it creates the session-handoff link
        # Note: exit code 0 expected if lessons are enabled and hook completes

        # Verify: session-handoffs.json should contain the session -> handoff link
        session_handoffs_file = state_dir / "session-handoffs.json"

        assert session_handoffs_file.exists(), (
            f"session-handoffs.json should exist after inject-hook runs with active handoff.\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}\n"
            f"exit code: {result.returncode}"
        )

        session_data = json.loads(session_handoffs_file.read_text())

        assert session_id in session_data, (
            f"Session {session_id} should be linked to handoff {handoff_id}.\n"
            f"session-handoffs.json content: {json.dumps(session_data, indent=2)}\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )

        linked_handoff = session_data[session_id].get("handoff_id")
        assert linked_handoff == handoff_id, (
            f"Session should be linked to handoff {handoff_id}, but got {linked_handoff}.\n"
            f"session-handoffs.json content: {json.dumps(session_data, indent=2)}"
        )

    def test_inject_hook_links_session_to_ready_for_review_handoff(
        self, tmp_path, inject_hook_path, temp_claude_home, temp_project_root
    ):
        """
        Specifically test ready_for_review handoffs, which is the reported bug case.

        When a handoff is ready_for_review, inject-hook should still link the
        session to it so the TUI can display associated sessions.
        """
        # Setup state directory
        state_dir = tmp_path / ".local" / "state" / "claude-recall"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "debug.log").write_text("")

        # Create a handoff with ready_for_review status (using correct format)
        # IMPORTANT: Use today's date to avoid auto-completion (HANDOFF_ORPHAN_DAYS=1)
        handoffs_file = temp_project_root / ".claude-recall" / "HANDOFFS.md"
        handoff_id = "hf-def5678"
        today = date.today().isoformat()
        handoffs_content = f"""# HANDOFFS.md - Active Work Tracking

> Track ongoing work with tried steps and next steps.
> When completed, review for lessons to extract.

## Active Handoffs


### [{handoff_id}] Completed Feature
- **Status**: ready_for_review | **Phase**: review | **Agent**: user
- **Created**: {today} | **Updated**: {today}
- **Refs**:
- **Description**:
- **Checkpoint**: Review for lessons
- **Next**: Extract lessons from completed work

**Tried**:
1. [success] Implemented the feature
2. [success] Added tests

"""
        handoffs_file.write_text(handoffs_content)

        session_id = "review-session-67890"
        input_json = json.dumps({
            "session_id": session_id,
            "cwd": str(temp_project_root)
        })

        env = {
            **{k: v for k, v in os.environ.items() if k in {"PATH", "SHELL", "TERM", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE"}},
            "HOME": str(tmp_path),
            "CLAUDE_RECALL_STATE": str(state_dir),
            "CLAUDE_RECALL_DEBUG": "0",
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

        session_handoffs_file = state_dir / "session-handoffs.json"

        assert session_handoffs_file.exists(), (
            f"session-handoffs.json should exist.\n"
            f"stderr: {result.stderr}"
        )

        session_data = json.loads(session_handoffs_file.read_text())

        assert session_id in session_data, (
            f"Session {session_id} should be linked to ready_for_review handoff {handoff_id}.\n"
            f"This is the reported bug: ready_for_review handoffs have no sessions.\n"
            f"session-handoffs.json: {json.dumps(session_data, indent=2)}"
        )

        assert session_data[session_id].get("handoff_id") == handoff_id, (
            f"Session should link to {handoff_id}"
        )

    def test_inject_hook_no_session_link_when_no_handoffs(
        self, tmp_path, inject_hook_path, temp_claude_home, temp_project_root
    ):
        """When there are no active handoffs, inject-hook should not create session links."""
        state_dir = tmp_path / ".local" / "state" / "claude-recall"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "debug.log").write_text("")

        # NO handoffs file - empty project

        session_id = "orphan-session-99999"
        input_json = json.dumps({
            "session_id": session_id,
            "cwd": str(temp_project_root)
        })

        env = {
            **{k: v for k, v in os.environ.items() if k in {"PATH", "SHELL", "TERM", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE"}},
            "HOME": str(tmp_path),
            "CLAUDE_RECALL_STATE": str(state_dir),
            "CLAUDE_RECALL_DEBUG": "0",
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

        session_handoffs_file = state_dir / "session-handoffs.json"

        # Should not exist or should not contain this session
        if session_handoffs_file.exists():
            session_data = json.loads(session_handoffs_file.read_text())
            assert session_id not in session_data, (
                f"Session should NOT be linked when no handoffs exist.\n"
                f"session-handoffs.json: {json.dumps(session_data, indent=2)}"
            )
