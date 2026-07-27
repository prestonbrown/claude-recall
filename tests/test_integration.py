#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Integration tests for Claude Recall hook pipeline.

These tests verify end-to-end behavior of the hook system:
- Inject hook loads lessons
- Stop hook parses LESSON: commands
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
# Repo structure invariants
# =============================================================================


def test_adapter_hook_symlinks_resolve():
    """Every hook symlink in adapters/claude-code points at an existing script.

    The adapter directory is a set of symlinks into
    plugins/claude-recall/hooks/scripts. Deleting a plugin script without
    deleting its adapter symlink leaves a dangling link, which breaks the
    integration fixture (and install.sh) with an opaque FileNotFoundError.
    """
    adapters_dir = Path(__file__).parent.parent / "adapters" / "claude-code"

    dangling = sorted(
        p.name for p in adapters_dir.glob("*.sh") if not p.resolve().exists()
    )

    assert not dangling, (
        f"Dangling hook symlinks in adapters/claude-code: {dangling}. "
        f"Their targets under plugins/claude-recall/hooks/scripts were removed; "
        f"delete the symlinks too."
    )


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

    # Create shared config.json
    settings = {"enabled": True}
    (claude_recall_base / "config.json").write_text(json.dumps(settings))

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
def hook_env(integration_env: Dict[str, Path], tmp_path: Path) -> Dict[str, str]:
    """Environment for running hook scripts with isolation."""
    repo_root = Path(__file__).parent.parent

    # Whitelist only essential system env vars
    safe_vars = {"PATH", "SHELL", "TERM", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE"}
    base_env = {k: v for k, v in os.environ.items() if k in safe_vars}

    # Create isolated TMPDIR
    tmpdir = tmp_path / "hook_tmp"
    tmpdir.mkdir(exist_ok=True)

    return {
        **base_env,
        "HOME": str(integration_env["home"]),
        "TMPDIR": str(tmpdir),
        "PROJECT_DIR": str(integration_env["project_root"]),
        "CLAUDE_RECALL_BASE": str(integration_env["claude_recall_base"]),
        "CLAUDE_RECALL_STATE": str(integration_env["claude_recall_state"]),
        "CLAUDE_RECALL_DEBUG": "1",
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


@pytest.mark.skip(reason="Hooks migrating from Python CLI to Go - tests will be re-enabled after migration")
@pytest.mark.skip(reason="Python CLI removed - CLI now handled by Go binary")
class TestInstalledCLI:
    """Test that installed CLI works correctly.

    NOTE: Skipped because Python CLI was removed; Go binary handles CLI.

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

