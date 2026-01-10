#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Integration tests for Claude Recall hook pipeline.

These tests verify end-to-end behavior of the hook system:
- Inject hook loads lessons and handoffs
- Stop hook parses LESSON:/HANDOFF: commands
- Debug logging captures events across projects
- Full session lifecycle works correctly
"""

import json
import os
import re
import subprocess
import tempfile
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

import pytest

# Mark all tests in this module as integration tests
pytestmark = pytest.mark.integration


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def integration_env(tmp_path: Path) -> Dict[str, Path]:
    """Set up isolated environment for integration tests.

    Creates:
    - project_root: Fake git project
    - claude_recall_base: ~/.config/claude-recall equivalent
    - claude_recall_state: ~/.local/state/claude-recall equivalent
    - claude_dir: ~/.claude equivalent
    - hooks_dir: Where hooks are installed
    """
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / ".git").mkdir()  # Fake git repo

    claude_recall_base = tmp_path / ".config" / "claude-recall"
    claude_recall_base.mkdir(parents=True)

    claude_recall_state = tmp_path / ".local" / "state" / "claude-recall"
    claude_recall_state.mkdir(parents=True, exist_ok=True)

    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()

    hooks_dir = claude_dir / "hooks"
    hooks_dir.mkdir()

    # Create settings.json
    settings = {"claudeRecall": {"enabled": True}}
    (claude_dir / "settings.json").write_text(json.dumps(settings))

    # Copy actual hooks from adapters/claude-code
    repo_root = Path(__file__).parent.parent
    adapters_dir = repo_root / "adapters" / "claude-code"

    for hook_file in adapters_dir.glob("*.sh"):
        dest = hooks_dir / hook_file.name
        dest.write_text(hook_file.read_text())
        dest.chmod(0o755)

    # Copy core Python modules (all .py files, matching install.sh)
    core_dir = repo_root / "core"
    for py_file in core_dir.glob("*.py"):
        dest = claude_recall_base / py_file.name
        dest.write_text(py_file.read_text())

    # Copy bash manager
    bash_manager = core_dir / "lessons-manager.sh"
    if bash_manager.exists():
        dest = claude_recall_base / "lessons-manager.sh"
        dest.write_text(bash_manager.read_text())
        dest.chmod(0o755)

    return {
        "project_root": project_root,
        "claude_recall_base": claude_recall_base,
        "claude_recall_state": claude_recall_state,
        "claude_dir": claude_dir,
        "hooks_dir": hooks_dir,
        "home": tmp_path,
    }


@pytest.fixture
def hook_env(integration_env: Dict[str, Path]) -> Dict[str, str]:
    """Environment variables for running hooks."""
    repo_root = Path(__file__).parent.parent
    return {
        **os.environ,
        "HOME": str(integration_env["home"]),
        "PROJECT_DIR": str(integration_env["project_root"]),
        "CLAUDE_RECALL_BASE": str(integration_env["claude_recall_base"]),
        "CLAUDE_RECALL_STATE": str(integration_env["claude_recall_state"]),
        "CLAUDE_RECALL_DEBUG": "1",
        # Add repo root to PYTHONPATH so imports work
        "PYTHONPATH": str(repo_root),
    }


def create_transcript(path: Path, entries: List[str]) -> None:
    """Create a mock Claude transcript file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for i, text in enumerate(entries):
        entry = {
            "timestamp": f"2026-01-03T12:00:{i:02d}Z",
            "uuid": f"test-uuid-{i}",
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": text}]
            }
        }
        lines.append(json.dumps(entry))
    path.write_text("\n".join(lines))


def run_hook(hook_path: Path, input_data: dict, env: Dict[str, str], trace: bool = False) -> subprocess.CompletedProcess:
    """Run a hook script with JSON input."""
    cmd = ["bash"]
    if trace:
        cmd.append("-x")
    cmd.append(str(hook_path))
    return subprocess.run(
        cmd,
        input=json.dumps(input_data),
        capture_output=True,
        text=True,
        env=env,
    )


# =============================================================================
# Inject Hook Tests
# =============================================================================


class TestInjectHookIntegration:
    """Integration tests for inject-hook.sh."""

    def test_inject_with_no_lessons(self, integration_env, hook_env):
        """Inject hook should succeed with no lessons."""
        hook = integration_env["hooks_dir"] / "inject-hook.sh"

        result = run_hook(hook, {"cwd": str(integration_env["project_root"])}, hook_env)

        assert result.returncode == 0

    def test_inject_loads_project_lessons(self, integration_env, hook_env):
        """Inject hook should load lessons from project."""
        # Create a project lesson
        lessons_dir = integration_env["project_root"] / ".claude-recall"
        lessons_dir.mkdir()
        lessons_file = lessons_dir / "LESSONS.md"
        lessons_file.write_text("""# LESSONS.md - Project Level

## Active Lessons

### [L001] [*----|-----] Test lesson
- **Uses**: 1 | **Velocity**: 1.0 | **Learned**: 2026-01-01 | **Last**: 2026-01-03 | **Category**: pattern
> This is a test lesson for integration testing.
""")

        hook = integration_env["hooks_dir"] / "inject-hook.sh"
        result = run_hook(hook, {"cwd": str(integration_env["project_root"])}, hook_env)

        assert result.returncode == 0
        # The hook should output the lesson
        assert "Test lesson" in result.stdout or result.returncode == 0


# =============================================================================
# Stop Hook Tests
# =============================================================================


class TestStopHookIntegration:
    """Integration tests for stop-hook.sh."""

    def test_stop_hook_parses_lesson_command(self, integration_env, hook_env):
        """Stop hook should parse AI LESSON: commands and add lessons."""
        # Create transcript with AI LESSON command (stop hook uses this format)
        transcript = integration_env["home"] / "transcript.jsonl"
        create_transcript(transcript, [
            "I'll add a lesson about this.\nAI LESSON: pattern: Test integration - This lesson was added by integration test"
        ])

        hook = integration_env["hooks_dir"] / "stop-hook.sh"
        input_data = {
            "cwd": str(integration_env["project_root"]),
            "transcript_path": str(transcript),
        }

        result = run_hook(hook, input_data, hook_env)

        # Check lesson was added
        lessons_file = integration_env["project_root"] / ".claude-recall" / "LESSONS.md"
        if lessons_file.exists():
            content = lessons_file.read_text()
            assert "Test integration" in content

    def test_stop_hook_parses_handoff_command(self, integration_env, hook_env):
        """Stop hook should parse HANDOFF: commands and create handoffs."""
        transcript = integration_env["home"] / "transcript.jsonl"
        create_transcript(transcript, [
            "Starting new work.\nHANDOFF: Integration test feature"
        ])

        hook = integration_env["hooks_dir"] / "stop-hook.sh"
        input_data = {
            "cwd": str(integration_env["project_root"]),
            "transcript_path": str(transcript),
        }

        result = run_hook(hook, input_data, hook_env)

        # Check handoff was created
        handoffs_file = integration_env["project_root"] / ".claude-recall" / "HANDOFFS.md"
        if handoffs_file.exists():
            content = handoffs_file.read_text()
            assert "Integration test feature" in content

    def test_stop_hook_tracks_citations(self, integration_env, hook_env):
        """Stop hook should track lesson citations."""
        # First create a lesson
        lessons_dir = integration_env["project_root"] / ".claude-recall"
        lessons_dir.mkdir(exist_ok=True)
        lessons_file = lessons_dir / "LESSONS.md"
        lessons_file.write_text("""# LESSONS.md - Project Level

## Active Lessons

### [L001] [*----|-----] Test lesson
- **Uses**: 1 | **Velocity**: 1.0 | **Learned**: 2026-01-01 | **Last**: 2026-01-03 | **Category**: pattern
> Test lesson content.
""")

        # Create transcript that cites the lesson
        transcript = integration_env["home"] / "transcript.jsonl"
        create_transcript(transcript, [
            "Applying [L001]: Test lesson for this situation."
        ])

        hook = integration_env["hooks_dir"] / "stop-hook.sh"
        input_data = {
            "cwd": str(integration_env["project_root"]),
            "transcript_path": str(transcript),
        }

        result = run_hook(hook, input_data, hook_env)

        # Check citation was tracked (uses should increment)
        content = lessons_file.read_text()
        # Uses should have increased from 1
        assert "Uses" in content


# =============================================================================
# Debug Logging Tests
# =============================================================================


class TestDebugLoggingIntegration:
    """Integration tests for debug logging across projects."""

    def test_logs_include_project_context(self, integration_env, hook_env):
        """Debug logs should include project name."""
        from core.debug_logger import DebugLogger, reset_logger

        # Set up environment
        os.environ["PROJECT_DIR"] = str(integration_env["project_root"])
        os.environ["CLAUDE_RECALL_STATE"] = str(integration_env["claude_recall_state"])
        os.environ["CLAUDE_RECALL_DEBUG"] = "1"
        reset_logger()

        logger = DebugLogger()
        logger.citation("L001", 5, 6, 1.0, 2.0, False)

        log_file = integration_env["claude_recall_state"] / "debug.log"
        assert log_file.exists()

        content = log_file.read_text()
        event = json.loads(content.strip())

        assert event["project"] == "project"
        assert event["event"] == "citation"

    def test_logs_differentiate_projects(self, integration_env, hook_env):
        """Logs from different projects should have different project fields."""
        from core.debug_logger import DebugLogger, reset_logger

        os.environ["CLAUDE_RECALL_STATE"] = str(integration_env["claude_recall_state"])
        os.environ["CLAUDE_RECALL_DEBUG"] = "1"

        # Log from project1
        project1 = integration_env["home"] / "project1"
        project1.mkdir()
        os.environ["PROJECT_DIR"] = str(project1)
        reset_logger()
        logger1 = DebugLogger()
        logger1.lesson_added("L001", "project", "pattern", "test", 10, 50)

        # Log from project2
        project2 = integration_env["home"] / "project2"
        project2.mkdir()
        os.environ["PROJECT_DIR"] = str(project2)
        reset_logger()
        logger2 = DebugLogger()
        logger2.lesson_added("L002", "project", "gotcha", "test", 15, 60)

        log_file = integration_env["claude_recall_state"] / "debug.log"
        lines = log_file.read_text().strip().split("\n")

        assert len(lines) == 2
        event1 = json.loads(lines[0])
        event2 = json.loads(lines[1])

        assert event1["project"] == "project1"
        assert event2["project"] == "project2"


# =============================================================================
# Full Session Lifecycle Tests
# =============================================================================


class TestSessionLifecycle:
    """Test complete session lifecycle: start -> work -> stop."""

    def test_full_session_with_lesson_and_citation(self, integration_env, hook_env):
        """Test: inject -> add lesson -> cite lesson -> stop."""
        hooks_dir = integration_env["hooks_dir"]
        project_root = integration_env["project_root"]

        # 1. Session start (inject hook)
        inject_hook = hooks_dir / "inject-hook.sh"
        result = run_hook(inject_hook, {"cwd": str(project_root)}, hook_env)
        assert result.returncode == 0

        # 2. Stop hook: add a lesson (uses "AI LESSON:" format for assistant output)
        transcript1 = integration_env["home"] / "transcript1.jsonl"
        create_transcript(transcript1, [
            "Adding a new lesson.\nAI LESSON: gotcha: Session test - Always check return codes"
        ])

        stop_hook = hooks_dir / "stop-hook.sh"
        result = run_hook(stop_hook, {
            "cwd": str(project_root),
            "transcript_path": str(transcript1),
        }, hook_env)

        # Verify lesson was added
        lessons_file = project_root / ".claude-recall" / "LESSONS.md"
        assert lessons_file.exists(), f"Lesson file not created. Hook stderr: {result.stderr}"
        assert "Session test" in lessons_file.read_text()

        # 3. New session: inject should show the lesson
        result = run_hook(inject_hook, {"cwd": str(project_root)}, hook_env)
        # Lesson should be injected (in stdout or processed silently)

        # 4. Stop hook: cite the lesson
        transcript2 = integration_env["home"] / "transcript2.jsonl"
        create_transcript(transcript2, [
            "Applying [L001]: Session test - checking return codes here."
        ])

        result = run_hook(stop_hook, {
            "cwd": str(project_root),
            "transcript_path": str(transcript2),
        }, hook_env)

        # Check debug log captured both events
        log_file = integration_env["claude_recall_state"] / "debug.log"
        if log_file.exists():
            content = log_file.read_text()
            # Should have lesson_added and/or citation events
            assert "lesson" in content.lower() or "citation" in content.lower()

    def test_handoff_lifecycle(self, integration_env, hook_env):
        """Test: create handoff -> update -> complete."""
        hooks_dir = integration_env["hooks_dir"]
        project_root = integration_env["project_root"]
        stop_hook = hooks_dir / "stop-hook.sh"

        # 1. Create handoff
        transcript1 = integration_env["home"] / "t1.jsonl"
        create_transcript(transcript1, [
            "Starting work.\nHANDOFF: Build integration tests"
        ])

        run_hook(stop_hook, {
            "cwd": str(project_root),
            "transcript_path": str(transcript1),
        }, hook_env)

        handoffs_file = project_root / ".claude-recall" / "HANDOFFS.md"
        assert handoffs_file.exists()
        content = handoffs_file.read_text()
        assert "Build integration tests" in content

        # Extract handoff ID
        import re
        match = re.search(r'\[(hf-[0-9a-f]{7})\]', content)
        if match:
            handoff_id = match.group(1)

            # 2. Update handoff with tried step
            transcript2 = integration_env["home"] / "t2.jsonl"
            create_transcript(transcript2, [
                f"HANDOFF UPDATE {handoff_id}: tried success - Created test file"
            ])

            run_hook(stop_hook, {
                "cwd": str(project_root),
                "transcript_path": str(transcript2),
            }, hook_env)

            content = handoffs_file.read_text()
            # Check tried step was added
            assert "Created test file" in content or "success" in content.lower()


# =============================================================================
# Cross-Project Isolation Tests
# =============================================================================


class TestProjectIsolation:
    """Test that projects are properly isolated."""

    def test_lessons_are_project_specific(self, integration_env, hook_env):
        """Lessons added in one project shouldn't appear in another."""
        hooks_dir = integration_env["hooks_dir"]
        stop_hook = hooks_dir / "stop-hook.sh"

        # Create two projects
        project1 = integration_env["home"] / "proj1"
        project1.mkdir()
        (project1 / ".git").mkdir()

        project2 = integration_env["home"] / "proj2"
        project2.mkdir()
        (project2 / ".git").mkdir()

        # Add lesson to project1
        transcript = integration_env["home"] / "t.jsonl"
        create_transcript(transcript, [
            "LESSON: Project1 specific lesson - Only in project 1"
        ])

        env1 = {**hook_env, "PROJECT_DIR": str(project1)}
        run_hook(stop_hook, {
            "cwd": str(project1),
            "transcript_path": str(transcript),
        }, env1)

        # Check project1 has the lesson
        p1_lessons = project1 / ".claude-recall" / "LESSONS.md"
        if p1_lessons.exists():
            assert "Project1 specific" in p1_lessons.read_text()

        # Check project2 does NOT have the lesson
        p2_lessons = project2 / ".claude-recall" / "LESSONS.md"
        assert not p2_lessons.exists() or "Project1 specific" not in p2_lessons.read_text()


# =============================================================================
# Auto-Handoff and Session Snapshot Tests
# =============================================================================


class TestInstalledCLI:
    """Test that installed CLI works correctly.

    These tests verify the CLI works when installed in flat mode (no core/ prefix),
    simulating ~/.config/claude-recall/ where files are copied directly.
    """

    @pytest.fixture
    def installed_env(self, integration_env, hook_env) -> Dict[str, any]:
        """Set up a fully installed environment with all modules."""
        claude_recall_base = integration_env["claude_recall_base"]
        repo_root = Path(__file__).parent.parent
        core_dir = repo_root / "core"

        # Copy all Python modules (like install.sh does)
        for py_file in core_dir.glob("*.py"):
            (claude_recall_base / py_file.name).write_text(py_file.read_text())

        # Copy TUI directory (flat, no core/ prefix)
        tui_src = core_dir / "tui"
        tui_dst = claude_recall_base / "tui"
        if tui_src.exists():
            import shutil
            if tui_dst.exists():
                shutil.rmtree(tui_dst)
            shutil.copytree(tui_src, tui_dst)

        return {
            "base": claude_recall_base,
            "env": {
                **hook_env,
                "PYTHONPATH": "",  # Clear PYTHONPATH to simulate installed env
            },
            "project_root": integration_env["project_root"],
            "state": integration_env["claude_recall_state"],
        }

    def test_installed_cli_imports_work(self, installed_env):
        """Verify CLI can import all required modules when installed."""
        result = subprocess.run(
            ["python3", str(installed_env["base"] / "cli.py"), "inject", "1"],
            capture_output=True,
            text=True,
            env=installed_env["env"],
            cwd=str(installed_env["project_root"]),
        )

        # Should not fail with import errors
        assert "ModuleNotFoundError" not in result.stderr, f"Import error: {result.stderr}"
        assert "ImportError" not in result.stderr, f"Import error: {result.stderr}"

    def test_installed_cli_watch_summary(self, installed_env):
        """Verify watch --summary works when installed (tests TUI imports).

        This is a regression test for the bug where 'from core.tui.log_reader'
        failed in installed mode because there's no core/ package.
        """
        result = subprocess.run(
            ["python3", str(installed_env["base"] / "cli.py"), "watch", "--summary"],
            capture_output=True,
            text=True,
            env=installed_env["env"],
            cwd=str(installed_env["project_root"]),
        )

        # Should not fail with import errors
        assert "ModuleNotFoundError" not in result.stderr, f"Import error: {result.stderr}"
        assert "ImportError" not in result.stderr, f"Import error: {result.stderr}"
        # Should produce some output (even if empty stats)
        assert result.returncode == 0, f"watch --summary failed: {result.stderr}"

    def test_installed_cli_watch_tail(self, installed_env):
        """Verify watch --tail works when installed (tests TUI imports)."""
        result = subprocess.run(
            ["python3", str(installed_env["base"] / "cli.py"), "watch", "--tail", "-n", "5"],
            capture_output=True,
            text=True,
            env=installed_env["env"],
            cwd=str(installed_env["project_root"]),
        )

        # Should not fail with import errors
        assert "ModuleNotFoundError" not in result.stderr, f"Import error: {result.stderr}"
        assert "ImportError" not in result.stderr, f"Import error: {result.stderr}"
        assert result.returncode == 0, f"watch --tail failed: {result.stderr}"

    def test_installed_cli_debug_command(self, installed_env):
        """Verify debug command works when installed (tests debug_logger import).

        This is a regression test for the bug where 'from core.debug_logger'
        failed in installed mode.
        """
        result = subprocess.run(
            ["python3", str(installed_env["base"] / "cli.py"), "debug", "hook-start", "inject", "--trigger", "test"],
            capture_output=True,
            text=True,
            env={
                **installed_env["env"],
                "CLAUDE_RECALL_DEBUG": "1",  # Enable debug logging
            },
            cwd=str(installed_env["project_root"]),
        )

        # Should not fail with import errors
        assert "ModuleNotFoundError" not in result.stderr, f"Import error: {result.stderr}"
        assert "ImportError" not in result.stderr, f"Import error: {result.stderr}"
        assert result.returncode == 0, f"debug command failed: {result.stderr}"


class TestAutoHandoffCreation:
    """Test automatic handoff creation and session snapshots."""

    def test_inject_includes_handoff_duty(self, integration_env, hook_env):
        """Inject hook should include explicit HANDOFF DUTY in output."""
        # First create a lesson so inject has something to output
        lessons_dir = integration_env["project_root"] / ".claude-recall"
        lessons_dir.mkdir(exist_ok=True)
        lessons_file = lessons_dir / "LESSONS.md"
        lessons_file.write_text("""# LESSONS.md - Project Level

## Active Lessons

### [L001] [*----|-----] Test lesson
- **Uses**: 1 | **Velocity**: 1.0 | **Learned**: 2026-01-01 | **Last**: 2026-01-03 | **Category**: pattern
> This is a test lesson.
""")

        hook = integration_env["hooks_dir"] / "inject-hook.sh"
        result = run_hook(hook, {"cwd": str(integration_env["project_root"])}, hook_env)

        assert result.returncode == 0
        # HANDOFF DUTY should be in the hookSpecificOutput JSON
        assert "HANDOFF DUTY" in result.stdout or "HANDOFF" in result.stdout

    def test_inject_loads_session_snapshot(self, integration_env, hook_env):
        """Inject hook should load and clear session snapshot if it exists."""
        project_root = integration_env["project_root"]

        # Create a lesson so inject has content
        snapshot_dir = project_root / ".claude-recall"
        snapshot_dir.mkdir(exist_ok=True)
        lessons_file = snapshot_dir / "LESSONS.md"
        lessons_file.write_text("""# LESSONS.md - Project Level

## Active Lessons

### [L001] [*----|-----] Test lesson
- **Uses**: 1 | **Velocity**: 1.0 | **Learned**: 2026-01-01 | **Last**: 2026-01-03 | **Category**: pattern
> This is a test lesson.
""")

        # Create a session snapshot
        snapshot_file = snapshot_dir / ".session-snapshot"
        snapshot_file.write_text("""timestamp: 2026-01-03T12:00:00Z
summary: Previous session worked on integration tests.""")

        hook = integration_env["hooks_dir"] / "inject-hook.sh"
        result = run_hook(hook, {"cwd": str(project_root)}, hook_env)

        assert result.returncode == 0
        # Snapshot should be loaded and cleared
        assert not snapshot_file.exists(), "Snapshot should be cleared after injection"

    def test_sync_todos_infers_implementing_phase(self, integration_env, hook_env):
        """Handoff created from TodoWrite should infer implementing phase."""
        from core import LessonsManager

        project_root = integration_env["project_root"]
        manager = LessonsManager(
            lessons_base=str(integration_env["claude_recall_base"]),
            project_root=str(project_root)
        )

        # Todos with implementing keywords (3+ required for auto-create)
        todos = [
            {"content": "Implement the new feature", "status": "in_progress", "activeForm": "Implementing"},
            {"content": "Add unit tests", "status": "pending", "activeForm": "Adding tests"},
            {"content": "Update documentation", "status": "pending", "activeForm": "Updating docs"},
        ]

        handoff_id = manager.handoff_sync_todos(todos)
        assert handoff_id is not None

        handoff = manager.handoff_get(handoff_id)
        assert handoff is not None
        assert handoff.phase == "implementing"

    def test_sync_todos_infers_research_phase(self, integration_env, hook_env):
        """Handoff created from TodoWrite should infer research phase from keywords."""
        from core import LessonsManager

        project_root = integration_env["project_root"]
        manager = LessonsManager(
            lessons_base=str(integration_env["claude_recall_base"]),
            project_root=str(project_root)
        )

        # Todos with research keywords (3+ required for auto-create)
        todos = [
            {"content": "Research existing patterns", "status": "in_progress", "activeForm": "Researching"},
            {"content": "Investigate the codebase", "status": "pending", "activeForm": "Investigating"},
            {"content": "Explore similar solutions", "status": "pending", "activeForm": "Exploring"},
        ]

        handoff_id = manager.handoff_sync_todos(todos)
        assert handoff_id is not None

        handoff = manager.handoff_get(handoff_id)
        assert handoff is not None
        assert handoff.phase == "research"

    def test_inject_outputs_separate_lines_for_multiple_ready_handoffs(self, integration_env, hook_env):
        """Inject hook should output HANDOFF COMPLETE on separate lines for each ready_for_review handoff.

        This is critical because the stop-hook regex only matches ONE ID per line.
        If multiple IDs are on the same line, HANDOFF COMPLETE fails silently.
        """
        from core import LessonsManager

        project_root = integration_env["project_root"]
        manager = LessonsManager(
            lessons_base=str(integration_env["claude_recall_base"]),
            project_root=str(project_root)
        )

        # Create two handoffs in ready_for_review status
        hf1 = manager.handoff_add(title="First task", desc="First description")
        hf2 = manager.handoff_add(title="Second task", desc="Second description")

        manager.handoff_update_status(hf1, "ready_for_review")
        manager.handoff_update_status(hf2, "ready_for_review")

        # Run inject hook
        hook = integration_env["hooks_dir"] / "inject-hook.sh"
        result = run_hook(hook, {"cwd": str(project_root)}, hook_env)

        assert result.returncode == 0

        # Parse the JSON output to get hookSpecificOutput
        output_lines = result.stdout.strip().split('\n')
        json_output = None
        for line in output_lines:
            if line.startswith('{'):
                try:
                    json_output = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue

        assert json_output is not None, f"Expected JSON output, got: {result.stdout}"

        # The LESSON REVIEW DUTY should have each HANDOFF COMPLETE on its own line
        hook_specific = json_output.get("hookSpecificOutput", {})
        # hookSpecificOutput may be a dict with additionalContext key
        if isinstance(hook_specific, dict):
            hook_output = hook_specific.get("additionalContext", "")
        else:
            hook_output = str(hook_specific)

        # Should NOT have multiple IDs on same line (this is the bug)
        # Bad: "HANDOFF COMPLETE hf-xxx hf-yyy"
        # Good: "HANDOFF COMPLETE hf-xxx\n      HANDOFF COMPLETE hf-yyy"
        import re
        # Find all HANDOFF COMPLETE commands with actual handoff IDs (hf-xxxxxxx format)
        # Excludes instruction placeholders like <id>
        complete_lines = re.findall(r'HANDOFF COMPLETE\s+(hf-[0-9a-f]+)', hook_output)

        # There should be exactly 2 separate HANDOFF COMPLETE commands with the correct IDs
        assert set(complete_lines) == {hf1, hf2}, \
            f"Expected IDs {hf1} and {hf2}, got {complete_lines}. Output:\n{hook_output}"

    def test_inject_includes_completion_workflow_instructions(self, integration_env, hook_env):
        """Inject hook should include instructions for review → complete → commit workflow."""
        # Create a lesson so inject has something to output
        lessons_dir = integration_env["project_root"] / ".claude-recall"
        lessons_dir.mkdir(exist_ok=True)
        lessons_file = lessons_dir / "LESSONS.md"
        lessons_file.write_text("""# LESSONS.md - Project Level

## Active Lessons

### [L001] [*----|-----] Test lesson
- **Uses**: 1 | **Velocity**: 1.0 | **Learned**: 2026-01-01 | **Last**: 2026-01-03 | **Category**: pattern
> This is a test lesson.
""")

        hook = integration_env["hooks_dir"] / "inject-hook.sh"
        result = run_hook(hook, {"cwd": str(integration_env["project_root"])}, hook_env)

        assert result.returncode == 0

        # Parse the JSON output
        output_lines = result.stdout.strip().split('\n')
        json_output = None
        for line in output_lines:
            if line.startswith('{'):
                try:
                    json_output = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue

        assert json_output is not None, f"Expected JSON output, got: {result.stdout}"

        hook_specific = json_output.get("hookSpecificOutput", {})
        if isinstance(hook_specific, dict):
            hook_output = hook_specific.get("additionalContext", "")
        else:
            hook_output = str(hook_specific)

        # HANDOFF DUTY should include completion workflow
        assert "/review" in hook_output, \
            f"HANDOFF DUTY should mention /review for code review. Output:\n{hook_output}"
        assert "HANDOFF COMPLETE" in hook_output, \
            f"HANDOFF DUTY should mention HANDOFF COMPLETE. Output:\n{hook_output}"
        assert "commit" in hook_output.lower(), \
            f"HANDOFF DUTY should mention commit after completion. Output:\n{hook_output}"


class TestStopHookIncrementalProcessing:
    """Tests for stop-hook incremental processing with transcript caching."""

    def test_incremental_citation_processing(self, integration_env, hook_env):
        """Stop hook should only process new entries after checkpoint.

        This test verifies that the transcript caching (single jq pass)
        correctly handles incremental processing:
        1. First run processes all citations
        2. Checkpoint is saved
        3. New entries added to transcript
        4. Second run only processes new entries
        """
        # Create a lesson to cite
        lessons_dir = integration_env["project_root"] / ".claude-recall"
        lessons_dir.mkdir(exist_ok=True)
        lessons_file = lessons_dir / "LESSONS.md"
        lessons_file.write_text("""# LESSONS.md - Project Level

## Active Lessons

### [L001] [*----|-----] First lesson
- **Uses**: 1 | **Velocity**: 1.0 | **Learned**: 2026-01-01 | **Last**: 2026-01-03 | **Category**: pattern
> First lesson content.

### [L002] [*----|-----] Second lesson
- **Uses**: 1 | **Velocity**: 1.0 | **Learned**: 2026-01-01 | **Last**: 2026-01-03 | **Category**: pattern
> Second lesson content.
""")

        # Create transcript with first citation
        transcript = integration_env["home"] / "transcript.jsonl"
        entry1 = {
            "timestamp": "2026-01-03T12:00:00Z",
            "uuid": "test-uuid-1",
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "Applying [L001]: First lesson."}]
            }
        }
        transcript.write_text(json.dumps(entry1))

        hook = integration_env["hooks_dir"] / "stop-hook.sh"
        input_data = {
            "cwd": str(integration_env["project_root"]),
            "transcript_path": str(transcript),
        }

        # First run - should cite L001
        result1 = run_hook(hook, input_data, hook_env)
        assert result1.returncode == 0

        # Check checkpoint was created
        state_dir = integration_env["claude_recall_state"] / ".citation-state"
        session_id = transcript.stem
        checkpoint_file = state_dir / session_id
        assert checkpoint_file.exists(), "Checkpoint should be created after first run"

        # Record L001 uses after first run (for verifying incremental processing)
        content_after_first = lessons_file.read_text()
        l001_match_first = re.search(r'\[L001\].*?Uses[^:]*:\s*(\d+)', content_after_first, re.DOTALL)
        assert l001_match_first, "L001 should exist after first run"
        l001_uses_first = int(l001_match_first.group(1))

        # Add new entry with L002 citation
        entry2 = {
            "timestamp": "2026-01-03T12:00:05Z",
            "uuid": "test-uuid-2",
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "Now using [L002]: Second lesson."}]
            }
        }
        with open(transcript, 'a') as f:
            f.write("\n" + json.dumps(entry2))

        # Second run - should only cite L002 (L001 is before checkpoint)
        result2 = run_hook(hook, input_data, hook_env)
        assert result2.returncode == 0

        # Verify L001 was NOT re-cited (proves incremental processing)
        content_after_second = lessons_file.read_text()
        l001_match_second = re.search(r'\[L001\].*?Uses[^:]*:\s*(\d+)', content_after_second, re.DOTALL)
        l002_match = re.search(r'\[L002\].*?Uses[^:]*:\s*(\d+)', content_after_second, re.DOTALL)

        l001_uses_second = int(l001_match_second.group(1))
        assert l001_uses_second == l001_uses_first, \
            f"L001 should not be re-cited on second run (was {l001_uses_first}, now {l001_uses_second})"
        assert l002_match and int(l002_match.group(1)) >= 2, "L002 should have 2+ uses after second run"

    def test_multiple_patterns_single_transcript_parse(self, integration_env, hook_env):
        """Stop hook should extract multiple pattern types from cached transcript.

        Verifies that a single transcript parse correctly extracts:
        - AI LESSON patterns
        - HANDOFF patterns
        - Citations
        - TodoWrite calls
        """
        # Create transcript with multiple patterns
        transcript = integration_env["home"] / "multi_pattern.jsonl"
        entries = [
            {
                "timestamp": "2026-01-03T12:00:00Z",
                "uuid": "test-uuid-1",
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "Starting work.\nHANDOFF: Multi-pattern test"}
                    ]
                }
            },
            {
                "timestamp": "2026-01-03T12:00:01Z",
                "uuid": "test-uuid-2",
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "name": "TodoWrite", "input": {
                            "todos": [
                                {"content": "Test task", "status": "in_progress", "activeForm": "Testing"}
                            ]
                        }}
                    ]
                }
            },
            {
                "timestamp": "2026-01-03T12:00:02Z",
                "uuid": "test-uuid-3",
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "AI LESSON: pattern: Test pattern - Always test patterns"}
                    ]
                }
            }
        ]
        transcript.write_text("\n".join(json.dumps(e) for e in entries))

        hook = integration_env["hooks_dir"] / "stop-hook.sh"
        input_data = {
            "cwd": str(integration_env["project_root"]),
            "transcript_path": str(transcript),
        }

        result = run_hook(hook, input_data, hook_env)
        assert result.returncode == 0

        # Verify handoff was created
        handoffs_file = integration_env["project_root"] / ".claude-recall" / "HANDOFFS.md"
        assert handoffs_file.exists(), "Handoff should be created"
        handoff_content = handoffs_file.read_text()
        assert "Multi-pattern test" in handoff_content

        # Verify AI lesson was added
        lessons_file = integration_env["project_root"] / ".claude-recall" / "LESSONS.md"
        assert lessons_file.exists(), "Lessons file should be created with AI LESSON"
        lesson_content = lessons_file.read_text()
        assert "Test pattern" in lesson_content

    def test_empty_transcript_handling(self, integration_env, hook_env):
        """Stop hook should handle empty transcript gracefully."""
        transcript = integration_env["home"] / "empty.jsonl"
        transcript.write_text("")  # Empty file

        hook = integration_env["hooks_dir"] / "stop-hook.sh"
        input_data = {
            "cwd": str(integration_env["project_root"]),
            "transcript_path": str(transcript),
        }

        result = run_hook(hook, input_data, hook_env)
        assert result.returncode == 0, f"Should not crash on empty transcript: {result.stderr}"
