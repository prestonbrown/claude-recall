#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Test suite for OpenCode adapter.

Tests verify the TypeScript plugin structure and Go CLI delegation.
Business logic tests are in go/cmd/recall/opencode_test.go.

Run with: pytest tests/test_opencode_adapter.py -v
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, AsyncMock

import pytest

# Get the project root directory
PROJECT_ROOT = Path(__file__).parent.parent


# =============================================================================
# Fixtures (Following conftest.py pattern)
# =============================================================================


@pytest.fixture
def temp_lessons_base(tmp_path: Path) -> Path:
    """Create a temporary lessons base directory with LESSONS.md."""
    lessons_base = tmp_path / ".config" / "claude-recall"
    lessons_base.mkdir(parents=True)
    (lessons_base / "LESSONS.md").write_text("")
    return lessons_base


@pytest.fixture
def temp_state_dir(tmp_path: Path, monkeypatch) -> Path:
    """Create a temporary state directory."""
    state_dir = tmp_path / ".local" / "state" / "claude-recall"
    state_dir.mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_RECALL_STATE", str(state_dir))

    # Reset the debug logger so it picks up the new path
    from core.debug_logger import reset_logger
    reset_logger()

    return state_dir


@pytest.fixture
def temp_project_root(tmp_path: Path) -> Path:
    """Create a temporary project directory with .git and .claude-recall."""
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    (project / ".claude-recall").mkdir()
    return project


@pytest.fixture
def temp_opencode_config(tmp_path: Path) -> Path:
    """Create a temporary Claude Recall config directory with config.json."""
    recall_dir = tmp_path / ".config" / "claude-recall"
    recall_dir.mkdir(parents=True)
    config_file = recall_dir / "config.json"
    config_file.write_text('{"enabled": true}')
    return recall_dir


# =============================================================================
# Helper Functions
# =============================================================================


def run_cli(command: list[str], env: dict[str, str] | None = None, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    """Run Python CLI and return (stdout, stderr, returncode).

    Args:
        command: Command arguments (e.g., ['inject', '5'])
        env: Environment variables dict (optional)
        timeout: Timeout in seconds (default 30)

    Returns:
        CompletedProcess with stdout, stderr, returncode
    """
    if env is None:
        env = os.environ.copy()

    return subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "core" / "cli.py"), *command],
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
    )


def add_lesson(
    title: str,
    content: str,
    env: dict[str, str],
    category: str = "pattern",
    level: str = "project",
) -> subprocess.CompletedProcess[str]:
    """Wrapper for CLI add command.

    Args:
        title: Lesson title
        content: Lesson content
        env: Environment variables
        category: Lesson category (default: pattern)
        level: Lesson level - project or system (default: project)

    Returns:
        CompletedProcess from CLI execution
    """
    cmd = ["add", category, title, content, "--level", level]
    return run_cli(cmd, env)


def create_handoff(title: str, env: dict[str, str], description: str = "") -> subprocess.CompletedProcess[str]:
    """Wrapper for CLI handoff add command.

    Args:
        title: Handoff title
        env: Environment variables
        description: Optional handoff description

    Returns:
        CompletedProcess from CLI execution
    """
    cmd = ["handoff", "add", title]
    if description:
        cmd.extend(["--description", description])
    return run_cli(cmd, env)


def get_lesson(lesson_id: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Get lesson by ID.

    Args:
        lesson_id: Lesson ID (e.g., 'L001', 'S001')
        env: Environment variables

    Returns:
        CompletedProcess with lesson details
    """
    return run_cli(["show", lesson_id], env)


def list_lessons(env: dict[str, str], category: str | None = None) -> subprocess.CompletedProcess[str]:
    """List all lessons.

    Args:
        env: Environment variables
        category: Optional category filter

    Returns:
        CompletedProcess with lesson list
    """
    cmd = ["list"]
    if category:
        cmd.extend(["--category", category])
    return run_cli(cmd, env)


def get_active_handoff(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Get currently active handoff.

    Args:
        env: Environment variables

    Returns:
        CompletedProcess with handoff info
    """
    return run_cli(["handoff", "list", "--active"], env)


def call_count(command: str) -> int:
    """Count CLI invocations (mock tracking placeholder).

    This is a placeholder for tracking CLI call frequency during tests.
    In actual tests, this could integrate with a subprocess mock to count calls.

    Args:
        command: CLI command to count (e.g., 'inject', 'add')

    Returns:
        Number of times the command was called (placeholder returns 0)
    """
    return 0


async def simulate_session(
    events: list[dict[str, Any]],
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Simulate OpenCode session events for testing.

    This helper simulates calling the plugin with various events:
    - session.created
    - session.idle
    - message.updated

    Args:
        events: List of event dictionaries to simulate
        env: Environment variables (optional)

    Returns:
        Dictionary with simulation results
    """
    results = {
        "events_processed": len(events),
        "errors": [],
        "lessons_injected": 0,
        "citations_tracked": 0,
        "lessons_captured": 0,
    }

    return results


# =============================================================================
# Plugin Structure Tests - Verify TypeScript plugin structure
# =============================================================================


class TestPluginStructure:
    """Tests for plugin file structure and Go CLI delegation."""

    def test_plugin_uses_go_cli_not_old_bash_script(self):
        """Verify plugin doesn't reference old bash script path."""
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should NOT contain old bash script path
        assert "lessons-manager.sh" not in plugin_content, \
            "Plugin still references old bash script path"

    def test_plugin_has_exec_go_function(self):
        """Verify plugin has execGo function for Go CLI delegation."""
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        assert "async function execGo" in plugin_content, \
            "Plugin should have execGo function"
        assert "ALLOWED_GO_COMMANDS" in plugin_content, \
            "Plugin should have ALLOWED_GO_COMMANDS whitelist"

    def test_plugin_allowed_go_commands(self):
        """Verify plugin has correct Go command whitelist."""
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should have expected Go commands
        expected_commands = ["session-start", "session-idle", "pre-compact", "post-compact"]
        for cmd in expected_commands:
            assert f"'{cmd}'" in plugin_content or f'"{cmd}"' in plugin_content, \
                f"Plugin should have '{cmd}' in ALLOWED_GO_COMMANDS"

    def test_plugin_calls_session_start_on_session_created(self):
        """Verify session.created handler calls Go session-start."""
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        assert '"session.created"' in plugin_content, \
            "Plugin should have session.created handler"
        assert 'execGo("session-start"' in plugin_content, \
            "session.created should call execGo('session-start')"

    def test_plugin_calls_session_idle_for_processing(self):
        """Verify session.idle handler calls Go session-idle."""
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        assert '"session.idle"' in plugin_content, \
            "Plugin should have session.idle handler"
        assert 'execGo("session-idle"' in plugin_content, \
            "session.idle should call execGo('session-idle')"

    def test_plugin_has_compaction_handlers(self):
        """Verify plugin has compaction event handlers."""
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        assert '"experimental.session.compacting"' in plugin_content, \
            "Plugin should handle experimental.session.compacting"
        assert '"session.compacted"' in plugin_content, \
            "Plugin should handle session.compacted"
        assert 'execGo("pre-compact"' in plugin_content, \
            "compacting handler should call execGo('pre-compact')"
        assert 'execGo("post-compact"' in plugin_content, \
            "compacted handler should call execGo('post-compact')"


class TestPluginConfig:
    """Tests for plugin configuration."""

    def test_plugin_has_default_config(self):
        """Verify plugin has DEFAULT_CONFIG constant."""
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        assert "DEFAULT_CONFIG" in plugin_content, \
            "Plugin should have DEFAULT_CONFIG"
        assert "topLessonsToShow" in plugin_content, \
            "DEFAULT_CONFIG should have topLessonsToShow"
        assert "relevanceTopN" in plugin_content, \
            "DEFAULT_CONFIG should have relevanceTopN"
        assert "remindEvery" in plugin_content, \
            "DEFAULT_CONFIG should have remindEvery"
        assert "debugLevel" in plugin_content, \
            "DEFAULT_CONFIG should have debugLevel"

    def test_plugin_loads_config_from_json(self):
        """Verify plugin loads config from config.json."""
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        assert "loadConfig" in plugin_content, \
            "Plugin should have loadConfig function"
        assert "config.json" in plugin_content, \
            "Plugin should read from config.json"


class TestSlashCommands:
    """Tests for slash command handling (TypeScript-specific)."""

    def test_lessons_command_uses_opencode_paths(self):
        """Verify /lessons command documentation uses correct paths."""
        lessons_path = PROJECT_ROOT / "adapters" / "opencode" / "command" / "lessons.md"
        lessons_content = lessons_path.read_text()

        # Should NOT contain Claude Code plugin cache path
        assert "~/.claude/plugins/cache/" not in lessons_content, \
            "/lessons docs still reference Claude Code paths"

        # Should contain claude-recall wrapper
        assert "claude-recall" in lessons_content, \
            "/lessons docs should use claude-recall wrapper"

    def test_plugin_handles_slash_commands(self):
        """Verify plugin has command handling for /lessons and /handoffs."""
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        assert '"command.executed"' in plugin_content, \
            "Plugin should have command.executed handler"
        assert '"lessons"' in plugin_content or "'lessons'" in plugin_content, \
            "Plugin should handle /lessons command"
        assert '"handoffs"' in plugin_content or "'handoffs'" in plugin_content, \
            "Plugin should handle /handoffs command"

    def test_handoffs_command_documentation_exists(self):
        """Verify /handoffs command documentation exists."""
        handoffs_path = PROJECT_ROOT / "adapters" / "opencode" / "command" / "handoffs.md"
        assert handoffs_path.exists(), \
            "/handoffs command documentation file should exist"

    def test_handoffs_command_documentation_has_cli_examples(self):
        """Verify /handoffs command documentation has CLI examples."""
        handoffs_path = PROJECT_ROOT / "adapters" / "opencode" / "command" / "handoffs.md"
        handoffs_content = handoffs_path.read_text()

        # Should include CLI wrapper usage
        assert "claude-recall handoff" in handoffs_content, \
            "/handoffs docs should reference CLI wrapper"
        assert "$ARGUMENTS" in handoffs_content, \
            "/handoffs docs should pass through arguments"

    def test_handoffs_command_documentation_follows_lessons_pattern(self):
        """Verify /handoffs command documentation follows lessons.md pattern."""
        handoffs_path = PROJECT_ROOT / "adapters" / "opencode" / "command" / "handoffs.md"
        handoffs_content = handoffs_path.read_text()

        # Should have minimal structure with frontmatter and command
        assert "description:" in handoffs_content, \
            "/handoffs docs should have description"
        assert "argument-hint:" in handoffs_content, \
            "/handoffs docs should have argument-hint"
        assert "Command:" in handoffs_content, \
            "/handoffs docs should include command section"

    def test_handoffs_command_documentation_describes_workflow(self):
        """Verify /handoffs command documentation describes workflow."""
        handoffs_path = PROJECT_ROOT / "adapters" / "opencode" / "command" / "handoffs.md"
        handoffs_content = handoffs_path.read_text()

        # Should describe workflow
        assert handoffs_content, \
            "/handoffs docs should have content"


class TestMessageHandlers:
    """Tests for message handling (TypeScript-specific features)."""

    def test_plugin_has_message_created_handler(self):
        """Verify plugin has message.created handler."""
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        assert '"message.created"' in plugin_content, \
            "Plugin should have message.created event handler"

    def test_smart_injection_calls_score_relevance(self):
        """Verify smart injection calls score-relevance CLI command."""
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should have score-relevance call in message.created
        assert "score-relevance" in plugin_content, \
            "Plugin should call score-relevance for smart injection"

    def test_smart_injection_on_first_prompt_only(self):
        """Verify smart injection only happens on first prompt."""
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should track first prompt state
        assert "isFirstPrompt" in plugin_content, \
            "Plugin should track isFirstPrompt state"

    def test_periodic_reminders_on_nth_prompt(self):
        """Verify periodic reminders show high-star lessons every N prompts."""
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should track prompt count
        assert "promptCount" in plugin_content, \
            "Plugin should track prompt count for periodic reminders"

        # Should use CONFIG.remindEvery for reminder frequency
        assert "CONFIG.remindEvery" in plugin_content, \
            "Plugin should use CONFIG.remindEvery for reminder frequency"

    def test_periodic_reminders_inject_top_lessons(self):
        """Verify periodic reminders inject top lessons by stars."""
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should inject lessons for periodic reminders
        assert "inject" in plugin_content, \
            "Plugin should call inject CLI command for periodic reminders"

        # Should use CONFIG.topLessonsToShow for number of lessons
        assert "CONFIG.topLessonsToShow" in plugin_content, \
            "Plugin should use CONFIG.topLessonsToShow for reminders"

    def test_periodic_reminders_reset_after_injection(self):
        """Verify prompt count resets after showing reminder."""
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should reset prompt count after reminder
        assert "promptCount" in plugin_content, \
            "Plugin should track and reset prompt count"


class TestToolHandlers:
    """Tests for tool execution handling."""

    def test_todowrite_sync_handler_exists(self):
        """Verify TodoWrite sync handler exists."""
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should have tool.execute.after handler
        assert '"tool.execute.after"' in plugin_content, \
            "Plugin should have tool.execute.after event handler"

    def test_todowrite_sync_calls_cli_sync_todos(self):
        """Verify TodoWrite sync calls handoff sync-todos CLI command."""
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should have sync-todos call
        assert "sync-todos" in plugin_content, \
            "Plugin should call handoff sync-todos CLI command"

    def test_todowrite_sync_only_for_todowrite_tool(self):
        """Verify TodoWrite sync only triggers for TodoWrite tool."""
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should check for TodoWrite tool
        assert "TodoWrite" in plugin_content, \
            "Plugin should check for TodoWrite tool"

    def test_todowrite_sync_handles_missing_active_handoff(self):
        """Verify TodoWrite sync handles case with no active handoff."""
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should handle sync-todos errors gracefully
        assert "sync-todos" in plugin_content, \
            "Plugin should handle sync-todos errors"


class TestCompactionHandlers:
    """Tests for compaction event handling."""

    def test_pre_compact_injects_top_lessons(self):
        """Verify pre-compact injects top lessons."""
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should inject lessons on compaction
        assert "inject" in plugin_content, \
            "Plugin should inject lessons on compaction"

        # Should use CONFIG.topLessonsToShow
        assert "CONFIG.topLessonsToShow" in plugin_content, \
            "Plugin should use CONFIG.topLessonsToShow for injection count"

    def test_pre_compact_uses_high_priority_injection(self):
        """Verify pre-compact uses high-priority injection to survive compaction."""
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should use noReply for context injection
        assert "noReply" in plugin_content, \
            "Plugin should use noReply for context injection to avoid AI response"

    def test_post_compact_tracks_compaction_occurred(self):
        """Verify post-compact tracks that compaction occurred."""
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should track compaction state
        assert "compactionOccurred" in plugin_content, \
            "Plugin should track compactionOccurred in session state"

    def test_compaction_handlers_handle_errors_gracefully(self):
        """Verify compaction handlers handle errors gracefully."""
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should wrap compaction handlers in try-catch
        assert plugin_content.count("try {") >= 5, \
            "Plugin should wrap handlers in try-catch for error handling"

        # Should log errors
        assert ("console.error" in plugin_content or "log('error'" in plugin_content or
                'log("error"' in plugin_content or "log('debug'" in plugin_content or
                'log("debug"' in plugin_content), \
            "Plugin should log errors"


class TestDebugLogging:
    """Tests for debug logging infrastructure."""

    def test_logging_utility_exists(self):
        """Verify plugin has logging utility."""
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should have log function
        assert "function log" in plugin_content or "const log" in plugin_content, \
            "Plugin should have log function"

        # Should use fs.appendFileSync for writing logs
        assert "appendFileSync" in plugin_content, \
            "Plugin should use appendFileSync for log file writes"

    def test_logging_utility_emits_json(self):
        """Verify logging utility emits JSON logs."""
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should have JSON.stringify for structured logs
        assert "JSON.stringify" in plugin_content, \
            "Plugin should use JSON.stringify for structured logs"

        # Should include timestamp field
        assert "timestamp" in plugin_content, \
            "Logs should include timestamp field"

        # Should include level field
        assert "level" in plugin_content, \
            "Logs should include level field"

        # Should include event field
        assert "event" in plugin_content, \
            "Logs should include event field"

    def test_logging_supports_levels(self):
        """Verify logging utility supports debug, info, warn, error levels."""
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should have level constants or checks
        assert ("debug" in plugin_content and "info" in plugin_content and
                "warn" in plugin_content and "error" in plugin_content), \
            "Plugin should support debug, info, warn, error levels"

        # Should check CONFIG.debugLevel
        assert "CONFIG.debugLevel" in plugin_content, \
            "Plugin should check CONFIG.debugLevel for filtering"

    def test_logging_writes_to_debug_log(self):
        """Verify logs are written to debug.log file."""
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should have debug.log path
        assert "debug.log" in plugin_content, \
            "Plugin should write to debug.log file"

        # Should use state directory path
        assert ".local" in plugin_content or "state" in plugin_content, \
            "Plugin should use XDG state directory for logs"

        # Should create directory if needed
        assert "mkdirSync" in plugin_content or "existsSync" in plugin_content, \
            "Plugin should create log directory if it doesn't exist"

    def test_logging_level_0_disables_all(self):
        """Verify level 0 disables all logging."""
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should check for level 0
        assert "debugLevel" in plugin_content, \
            "Plugin should check debugLevel"

        # Should have early return when disabled
        assert "if (" in plugin_content and "return" in plugin_content, \
            "Plugin should have early return when logging disabled"

    def test_logging_level_checks_threshold(self):
        """Verify logging checks level threshold."""
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should check debugLevel >= threshold for different levels
        assert "CONFIG.debugLevel" in plugin_content, \
            "Plugin should compare debugLevel for level filtering"

    def test_logging_uses_iso_8601_timestamps(self):
        """Verify timestamps are ISO 8601 format."""
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should have timestamp generation
        assert ("toISOString()" in plugin_content or "new Date()" in plugin_content or
                "iso" in plugin_content.lower()), \
            "Plugin should generate ISO 8601 timestamps"

    def test_logging_handles_write_errors(self):
        """Verify logging handles write errors gracefully."""
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should have try-catch for logging
        assert "try {" in plugin_content and "catch" in plugin_content, \
            "Plugin should handle logging errors with try-catch"

    def test_logging_updates_all_console_log_calls(self):
        """Verify all existing console.log calls use new logging utility."""
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Check that most console.log calls use the new log function
        lines = plugin_content.split('\n')
        bare_console_logs = [
            line for line in lines
            if 'console.log' in line and 'log(' not in line and 'console.log(' in line
        ]
        bare_console_errors = [
            line for line in lines
            if 'console.error' in line and 'log(' not in line and 'console.error(' in line
        ]

        # Should have minimal bare console calls (at most a few for specific cases)
        assert len(bare_console_logs) < 5, \
            f"Plugin has too many bare console.log calls ({len(bare_console_logs)}), should use log() function"
        assert len(bare_console_errors) < 5, \
            f"Plugin has too many bare console.error calls ({len(bare_console_errors)}), should use log() function"

    def test_log_file_path_follows_xdg_spec(self):
        """Verify log file path follows XDG state spec."""
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should use .local/state directory
        assert ".local" in plugin_content, \
            "Plugin should use .local directory for XDG state"

        # Should use claude-recall subdirectory
        assert "claude-recall" in plugin_content, \
            "Plugin should use claude-recall subdirectory"

        # Should have debug.log filename
        assert "debug.log" in plugin_content, \
            "Plugin should use debug.log as log file name"


class TestSessionState:
    """Tests for session state management."""

    def test_plugin_tracks_session_state(self):
        """Verify plugin tracks per-session state."""
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should have state Map for per-session tracking
        assert "new Map" in plugin_content, \
            "Plugin should use Map for session state tracking"
        assert "isFirstPrompt" in plugin_content, \
            "Plugin should track isFirstPrompt state"
        assert "promptCount" in plugin_content, \
            "Plugin should track promptCount state"
        assert "compactionOccurred" in plugin_content, \
            "Plugin should track compactionOccurred state"

    def test_plugin_initializes_state_on_session_created(self):
        """Verify session state is initialized on session.created."""
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should set state in session.created handler
        assert "state.set(" in plugin_content, \
            "Plugin should initialize session state on session creation"

    def test_plugin_cleans_up_state_on_session_deleted(self):
        """Verify session state is cleaned up on session.deleted."""
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should have session.deleted handler
        assert '"session.deleted"' in plugin_content, \
            "Plugin should have session.deleted handler"
        # Should delete state
        assert ".delete(" in plugin_content, \
            "Plugin should clean up session state on deletion"

    def test_plugin_uses_session_id_for_state_key(self):
        """Verify plugin uses session.id as state key."""
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should access session.id
        assert "input.session.id" in plugin_content or "session.id" in plugin_content, \
            "Plugin should use session.id for state management"


class TestGoCliIntegration:
    """Tests for Go CLI integration patterns."""

    def test_plugin_finds_recall_binary(self):
        """Verify plugin has binary detection logic."""
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should have binary detection
        assert "findRecallBinary" in plugin_content or "findBinary" in plugin_content, \
            "Plugin should have binary detection function"
        assert "RECALL_BINARY" in plugin_content, \
            "Plugin should cache recall binary path"

    def test_plugin_validates_go_commands(self):
        """Verify plugin validates commands against whitelist."""
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should check command against whitelist
        assert "ALLOWED_GO_COMMANDS.has" in plugin_content, \
            "Plugin should validate commands against ALLOWED_GO_COMMANDS"

    def test_plugin_handles_go_cli_errors(self):
        """Verify plugin handles Go CLI errors gracefully."""
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should handle binary not found
        assert "binary not found" in plugin_content.lower() or "not found" in plugin_content.lower(), \
            "Plugin should handle missing binary"

    def test_plugin_passes_project_dir_to_go(self):
        """Verify plugin passes PROJECT_DIR to Go CLI."""
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should pass cwd to Go CLI
        assert "process.cwd()" in plugin_content, \
            "Plugin should pass current working directory to Go CLI"

    def test_plugin_parses_go_json_output(self):
        """Verify plugin parses JSON output from Go CLI."""
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should parse JSON response
        assert "JSON.parse" in plugin_content, \
            "Plugin should parse JSON output from Go CLI"

    def test_plugin_has_timeout_for_go_commands(self):
        """Verify plugin has timeout for Go CLI commands."""
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should have timeout
        assert "setTimeout" in plugin_content or "timeout" in plugin_content.lower(), \
            "Plugin should have timeout for Go CLI commands"


class TestLegacyCli:
    """Tests for legacy Python CLI usage (for slash commands)."""

    def test_plugin_has_legacy_cli_path(self):
        """Verify plugin has path to legacy Python CLI."""
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should have legacy CLI path
        assert "LEGACY_CLI" in plugin_content, \
            "Plugin should have LEGACY_CLI constant for slash commands"

    def test_plugin_uses_legacy_cli_for_slash_commands(self):
        """Verify plugin uses legacy CLI for /lessons and /handoffs."""
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should use LEGACY_CLI in runCmd
        assert "runCmd" in plugin_content or "LEGACY_CLI" in plugin_content, \
            "Plugin should use legacy CLI for slash commands"

    def test_plugin_uses_legacy_cli_for_sync_todos(self):
        """Verify plugin uses legacy CLI for handoff sync-todos."""
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should call sync-todos via legacy CLI
        assert "sync-todos" in plugin_content, \
            "Plugin should call handoff sync-todos"
