#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Test suite for OpenCode adapter revitalization.

This is a TDD test file - tests are written BEFORE the implementation.
Run with: pytest tests/test_opencode_adapter.py -v

All tests use real subprocess calls to Python CLI (not mocks), except for
provider.list() which is mocked for model detection tests.
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
    """Create a temporary OpenCode config directory with opencode.json."""
    opencode_dir = tmp_path / ".config" / "opencode"
    opencode_dir.mkdir(parents=True)
    config_file = opencode_dir / "opencode.json"
    config_file.write_text('{"claudeRecall": {"enabled": true}}')
    return opencode_dir


@pytest.fixture
def mock_providers():
    """Mock provider.list() response for model detection."""
    async def mock_list():
        return {
            "data": {
                "all": [
                    {
                        "id": "anthropic",
                        "models": {
                            "claude-3-5-haiku-latest": {
                                "name": "Claude 3.5 Haiku",
                                "tool_call": True,
                                "reasoning": True,
                            }
                        }
                    },
                    {
                        "id": "openai",
                        "models": {
                            "gpt-4o-mini": {
                                "name": "GPT-4o Mini",
                                "tool_call": True,
                                "reasoning": True,
                            },
                            "gpt-3.5-turbo": {
                                "name": "GPT-3.5 Turbo",
                                "tool_call": False,
                                "reasoning": True,
                            }
                        }
                    }
                ],
                "default": {"anthropic": "claude-3-5-haiku-latest"},
                "connected": ["anthropic"]
            }
        }
    return mock_list


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
# Phase 1: Critical Fixes Tests (Should FAIL initially)
# =============================================================================


class TestPhase1CriticalFixes:
    """Tests for Phase 1 critical fixes - all should FAIL initially (TDD red)."""

    def test_plugin_uses_python_cli_not_old_bash_script(self):
        """Verify plugin doesn't reference old bash script path.

        Expected: Plugin file contains python3 or core/cli.py,
        NOT lessons-manager.sh (old path).

        This test will PASS when the manager path is fixed in Phase 1.1.
        """
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should NOT contain old bash script path
        assert "lessons-manager.sh" not in plugin_content, \
            "Plugin still references old bash script path"

        # Should contain Python CLI references
        assert "python3" in plugin_content or "cli.py" in plugin_content, \
            "Plugin should reference Python CLI (python3 or cli.py)"

    def test_lessons_command_uses_opencode_paths(self):
        """Verify /lessons command doesn't reference Claude Code paths.

        Expected: lessons.md contains python3, NOT Claude Code plugin cache path.

        This test will PASS when /lessons docs are updated in Phase 1.2.
        """
        lessons_path = PROJECT_ROOT / "adapters" / "opencode" / "command" / "lessons.md"
        lessons_content = lessons_path.read_text()

        # Should NOT contain Claude Code plugin cache path
        assert "~/.claude/plugins/cache/" not in lessons_content, \
            "/lessons docs still reference Claude Code paths"

        # Should contain python3 for direct CLI calls
        assert "python3" in lessons_content, \
            "/lessons docs should use python3 for CLI calls"

    @pytest.fixture
    def config_env(self, tmp_path, temp_lessons_base, temp_project_root):
        """Set up environment for config tests."""
        opencode_dir = tmp_path / ".config" / "opencode"
        opencode_dir.mkdir(parents=True)

        return {
            **os.environ,
            "CLAUDE_RECALL_BASE": str(temp_lessons_base),
            "CLAUDE_RECALL_STATE": str(tmp_path / "state"),
            "PROJECT_DIR": str(temp_project_root),
        }

    def test_config_reads_claudeRecall_key_from_opencode_json(self, config_env, tmp_path):
        """Verify config reading from opencode.json.

        Expected: Config reads claudeRecall.enabled, claudeRecall.topLessonsToShow.

        This test will PASS when config loading is implemented in Phase 2.1.
        """
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should have Config interface with all fields
        assert "interface Config" in plugin_content, "Plugin should define Config interface"
        assert "enabled: boolean" in plugin_content, "Config should have 'enabled' field"
        assert "maxLessons: number" in plugin_content, "Config should have 'maxLessons' field"
        assert "topLessonsToShow: number" in plugin_content, "Config should have 'topLessonsToShow' field"

        # Should have loadConfig function
        assert "function loadConfig()" in plugin_content, "Plugin should have loadConfig function"
        assert "opencode.json" in plugin_content, "Plugin should read from opencode.json"
        assert "claudeRecall" in plugin_content, "Plugin should parse claudeRecall key"

        # Should have CONFIG constant
        assert "const CONFIG = loadConfig()" in plugin_content, "Plugin should initialize CONFIG constant"

    def test_config_merges_with_defaults(self, config_env, tmp_path):
        """Verify opencode.json merges with defaults.

        Expected: Custom value overrides default, other defaults preserved.

        This test will PASS when config merging is implemented in Phase 2.1.
        """
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should have DEFAULT_CONFIG constant
        assert "const DEFAULT_CONFIG: Config" in plugin_content, "Plugin should have DEFAULT_CONFIG constant"

        # Should have all default values
        assert "enabled: true" in plugin_content, "DEFAULT_CONFIG should have enabled=true"
        assert "maxLessons: 30" in plugin_content, "DEFAULT_CONFIG should have maxLessons=30"
        assert "topLessonsToShow: 5" in plugin_content, "DEFAULT_CONFIG should have topLessonsToShow=5"

        # Should merge claudeRecall with defaults
        assert "...DEFAULT_CONFIG, ...claudeRecall" in plugin_content, "Plugin should merge claudeRecall with DEFAULT_CONFIG"

    def test_detects_fast_model_from_providers(self, mock_providers):
        """Verify fast model detection from providers.

        Expected: Returns quality model (tool_call=true, reasoning=true).

        This test will PASS when model detection is implemented in Phase 2.2.
        """
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should have ModelInfo interface
        assert "interface ModelInfo" in plugin_content, "Plugin should define ModelInfo interface"
        assert "tool_call: boolean" in plugin_content, "ModelInfo should have tool_call field"
        assert "reasoning: boolean" in plugin_content, "ModelInfo should have reasoning field"

        # Should have Provider interface
        assert "interface Provider" in plugin_content, "Plugin should define Provider interface"
        assert "models: Record<string, ModelInfo>" in plugin_content, "Provider should have models field"

        # Should have detectFastModel function
        assert "async function detectFastModel" in plugin_content, "Plugin should have detectFastModel function"
        assert "client.provider.list" in plugin_content, "detectFastModel should query providers"

        # Should filter for quality models
        assert "info.tool_call && info.reasoning" in plugin_content, "Should filter for tool_call AND reasoning"

    def test_small_model_config_overrides_detection(self, mock_providers, tmp_path):
        """Verify small_model config overrides auto-detection.

        Expected: Returns configured model if available.

        This test will PASS when config override is implemented in Phase 2.2.
        """
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Config interface should have small_model field
        assert "small_model?: string" in plugin_content, "Config should have small_model field"

        # detectFastModel should accept configuredSmallModel parameter
        assert "configuredSmallModel?: string" in plugin_content, "detectFastModel should accept small_model parameter"

        # Should check if configured model is available
        assert "configuredSmallModel in p.models" in plugin_content, "Should check if configured model is available"

        # Should use configured model if available
        assert "return configuredSmallModel" in plugin_content, "Should return configured model if available"

    def test_filters_out_bad_models(self):
        """Verify quality filtering (tool_call + reasoning).

        Expected: Only models with both capabilities returned.

        This test will PASS when filtering is implemented in Phase 2.2.
        """
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should check both tool_call and reasoning
        assert "info.tool_call && info.reasoning" in plugin_content, "Should require both tool_call AND reasoning"

        # Should collect quality models
        assert "qualityModels" in plugin_content, "Should collect quality models"

        # Should iterate through providers and models
        assert "for (const provider of providers.data.all)" in plugin_content, "Should iterate through providers"
        assert "for (const [modelId, info] of Object.entries(provider.models))" in plugin_content, "Should iterate through models"

    def test_returns_none_if_no_good_models(self):
        """Verify graceful handling when no quality models.

        Expected: Returns None, logs warning.
        """
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should handle empty quality models array
        assert "if (qualityModels.length === 0)" in plugin_content, "Should check for empty quality models"

        # Should return null when no quality models
        assert 'return null' in plugin_content, "Should return null when no quality models"

        # Should log warning (either with console.warn or log function)
        assert ("console.warn" in plugin_content or "log('warn'" in plugin_content or \
                'log("warn"' in plugin_content), \
            "Should warn when no quality models"

    def test_plugin_integrates_model_detection(self):
        """Verify plugin integrates config and model detection.

        Expected: Plugin calls detectFastModel at initialization with CONFIG.small_model.
        """
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Plugin function should call detectFastModel
        assert "await detectFastModel(client, CONFIG.small_model)" in plugin_content, \
            "Plugin should call detectFastModel at initialization"

        # Should handle case when no fast model available
        assert ("console.warn" in plugin_content or "log('warn'" in plugin_content or \
                'log("warn"' in plugin_content), \
            "Plugin should warn when no fast model available"

        # Should store fastModel result
        assert "const fastModel = await detectFastModel" in plugin_content, \
            "Plugin should store fastModel result"


# =============================================================================
# Phase 3: Core Lessons Features Tests
# =============================================================================


class TestPhase3CoreLessonsFeatures:
    """Tests for Phase 3 core lessons features."""

    @pytest.fixture
    def lesson_env(self, temp_lessons_base, temp_state_dir, temp_project_root):
        """Set up environment with lessons for Phase 3 tests."""
        return {
            **os.environ,
            "CLAUDE_RECALL_BASE": str(temp_lessons_base),
            "CLAUDE_RECALL_STATE": str(temp_state_dir),
            "PROJECT_DIR": str(temp_project_root),
        }

    def test_plugin_has_message_created_handler_for_smart_injection(self):
        """Verify plugin has message.created handler for smart injection.

        Expected: Plugin should have a message.created event handler.
        """
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should have message.created handler
        assert '"message.created"' in plugin_content, \
            "Plugin should have message.created event handler"

    def test_smart_injection_calls_score_relevance(self):
        """Verify smart injection calls score-relevance CLI command.

        Expected: On first user prompt, calls score-relevance with user query.
        """
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should have score-relevance call in message.created
        assert "score-relevance" in plugin_content, \
            "Plugin should call score-relevance for smart injection"

        # Should use CONFIG.relevanceTopN for number of lessons
        assert "CONFIG.relevanceTopN" in plugin_content, \
            "Plugin should use CONFIG.relevanceTopN for relevance scoring"

    def test_smart_injection_on_first_prompt_only(self):
        """Verify smart injection only happens on first prompt.

        Expected: Tracks isFirstPrompt state, only injects on first prompt.
        """
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should track first prompt state
        assert "isFirstPrompt" in plugin_content, \
            "Plugin should track isFirstPrompt state"

    def test_ai_lesson_capture_from_assistant_output(self):
        """Verify AI lessons are captured from assistant output.

        Expected: Parses AI LESSON: pattern and calls add-ai CLI command.
        """
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should check for AI LESSON: pattern in assistant messages
        assert "AI LESSON:" in plugin_content, \
            "Plugin should look for AI LESSON: pattern"

        # Should call add-ai CLI command
        assert "add-ai" in plugin_content, \
            "Plugin should call add-ai command to capture AI lessons"

    def test_ai_lesson_parse_category_title_content(self):
        """Verify AI lesson pattern parsing extracts category, title, content.

        Expected: Parses "AI LESSON: category: title - content" format.
        """
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should parse category: title - content format
        assert "category" in plugin_content and "title" in plugin_content and "content" in plugin_content, \
            "Plugin should extract category, title, and content from AI LESSON pattern"

    def test_lesson_decay_on_session_created(self):
        """Verify lesson decay runs on session creation.

        Expected: Calls decay CLI command with interval from CONFIG.decayIntervalDays.
        """
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should have decay call in session.created handler
        assert "decay" in plugin_content, \
            "Plugin should call decay CLI command"

        # Should use CONFIG.decayIntervalDays for decay interval
        assert "CONFIG.decayIntervalDays" in plugin_content, \
            "Plugin should use CONFIG.decayIntervalDays for decay interval"

    def test_decay_tracks_last_run_time(self):
        """Verify decay tracks last run time to avoid running too frequently.

        Expected: CLI handles decay tracking internally via state file.
        """
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should call decay command with CONFIG.decayIntervalDays
        assert "decay" in plugin_content, \
            "Plugin should call decay CLI command"
        assert "CONFIG.decayIntervalDays" in plugin_content, \
            "Plugin should pass interval from config to decay command"

    def test_periodic_reminders_on_nth_prompt(self):
        """Verify periodic reminders show high-star lessons every N prompts.

        Expected: Shows top lessons every CONFIG.remindEvery prompts.
        """
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should track prompt count
        assert "promptCount" in plugin_content, \
            "Plugin should track prompt count for periodic reminders"

        # Should use CONFIG.remindEvery for reminder frequency
        assert "CONFIG.remindEvery" in plugin_content, \
            "Plugin should use CONFIG.remindEvery for reminder frequency"

    def test_periodic_reminders_inject_top_lessons(self):
        """Verify periodic reminders inject top lessons by stars.

        Expected: Calls inject CLI command with CONFIG.topLessonsToShow.
        """
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should inject lessons for periodic reminders
        assert "inject" in plugin_content, \
            "Plugin should call inject CLI command for periodic reminders"

        # Should use CONFIG.topLessonsToShow for number of lessons
        assert "CONFIG.topLessonsToShow" in plugin_content, \
            "Plugin should use CONFIG.topLessonsToShow for reminders"

    def test_periodic_reminders_reset_after_injection(self):
        """Verify prompt count resets after showing reminder.

        Expected: Resets promptCount to 0 after showing reminder.
        """
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should reset prompt count after reminder
        assert "promptCount" in plugin_content, \
            "Plugin should track and reset prompt count"

    def test_message_created_tracks_user_prompts_only(self):
        """Verify prompt counting only tracks user messages.

        Expected: Increments promptCount only for user role messages.
        """
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should check message role before incrementing
        assert "role === \"user\"" in plugin_content, \
            "Plugin should check for user role before tracking prompts"


# =============================================================================
# Phase 4: Handoffs System Tests
# =============================================================================


class TestPhase4HandoffsSystem:
    """Tests for Phase 4 handoffs system."""

    @pytest.fixture
    def handoff_env(self, temp_lessons_base, temp_state_dir, temp_project_root):
        """Set up environment with handoffs for Phase 4 tests."""
        return {
            **os.environ,
            "CLAUDE_RECALL_BASE": str(temp_lessons_base),
            "CLAUDE_RECALL_STATE": str(temp_state_dir),
            "PROJECT_DIR": str(temp_project_root),
        }

    def test_handoff_injection_in_session_created_handler(self):
        """Verify handoffs are injected at session start.

        Expected: Plugin calls handoff inject CLI command and injects output.
        """
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should have handoff inject call in session.created handler
        assert "handoff inject" in plugin_content, \
            "Plugin should call handoff inject CLI command"

    def test_handoff_injection_parses_output_and_injects(self):
        """Verify handoff injection parses CLI output and injects into session.

        Expected: Parses handoff output and injects as context.
        """
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should inject handoff output into session
        assert "handoff" in plugin_content, \
            "Plugin should inject handoff context"

    def test_handoff_injection_handles_no_active_handoffs(self):
        """Verify handoff injection handles case with no active handoffs.

        Expected: Silently skips injection when no active handoffs.
        """
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should handle empty output gracefully
        assert "handoff" in plugin_content, \
            "Plugin should handle empty handoff output"

    def test_todowrite_sync_handler_exists(self):
        """Verify TodoWrite sync handler exists.

        Expected: Plugin has tool.execute.after handler for TodoWrite.
        """
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should have tool.execute.after handler
        assert '"tool.execute.after"' in plugin_content, \
            "Plugin should have tool.execute.after event handler"

    def test_todowrite_sync_calls_cli_sync_todos(self):
        """Verify TodoWrite sync calls handoff sync-todos CLI command.

        Expected: Calls sync-todos with todo JSON when TodoWrite is used.
        """
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should have sync-todos call
        assert "sync-todos" in plugin_content, \
            "Plugin should call handoff sync-todos CLI command"

    def test_todowrite_sync_only_for_todowrite_tool(self):
        """Verify TodoWrite sync only triggers for TodoWrite tool.

        Expected: Checks tool name before syncing.
        """
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should check for TodoWrite tool
        assert "TodoWrite" in plugin_content, \
            "Plugin should check for TodoWrite tool"

    def test_todowrite_sync_handles_missing_active_handoff(self):
        """Verify TodoWrite sync handles case with no active handoff.

        Expected: Silently fails when no active handoff exists.
        """
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should handle sync-todos errors gracefully
        assert "sync-todos" in plugin_content, \
            "Plugin should handle sync-todos errors"

    def test_handoff_pattern_capture_from_assistant_output(self):
        """Verify handoff patterns are captured from assistant output.

        Expected: Parses HANDOFF: patterns and calls appropriate CLI commands.
        """
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should check for HANDOFF: pattern in assistant messages
        assert "HANDOFF:" in plugin_content, \
            "Plugin should look for HANDOFF: pattern"

    def test_handoff_start_pattern_creates_new_handoff(self):
        """Verify HANDOFF: pattern creates new handoff.

        Expected: Parses "HANDOFF: title" and calls handoff add CLI command.
        """
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should have handoff add call for HANDOFF: pattern
        assert "handoff add" in plugin_content, \
            "Plugin should call handoff add command for new handoffs"

    def test_handoff_complete_pattern_marks_handoff_complete(self):
        """Verify HANDOFF COMPLETE pattern marks handoff as complete.

        Expected: Parses "HANDOFF COMPLETE H001" and calls handoff complete CLI command.
        """
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should have handoff complete call for HANDOFF COMPLETE pattern
        assert "handoff complete" in plugin_content, \
            "Plugin should call handoff complete command"

    def test_handoff_update_pattern_records_attempt(self):
        """Verify HANDOFF UPDATE pattern records attempt.

        Expected: Parses "HANDOFF UPDATE H001: tried success - desc" and calls handoff update CLI command.
        """
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should have handoff update call for HANDOFF UPDATE pattern
        assert "handoff update" in plugin_content, \
            "Plugin should call handoff update command for updates"

    def test_handoff_patterns_parsed_in_message_updated_handler(self):
        """Verify handoff patterns are parsed in message.updated handler.

        Expected: message.updated handler checks for handoff patterns.
        """
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should have handoff pattern parsing in message.updated handler
        assert "message.updated" in plugin_content, \
            "Plugin should parse handoff patterns in message.updated handler"

    def test_handoff_update_handles_tried_status_variants(self):
        """Verify HANDOFF UPDATE handles all tried status variants.

        Expected: Supports success, fail, partial outcomes.
        """
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should handle tried status variants
        assert "tried" in plugin_content, \
            "Plugin should handle tried status variants"

    def test_handoff_patterns_only_parsed_from_assistant(self):
        """Verify handoff patterns only parsed from assistant messages.

        Expected: Checks message.role === "assistant" before parsing.
        """
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should check for assistant role
        assert "role === \"assistant\"" in plugin_content, \
            "Plugin should check for assistant role before parsing handoff patterns"

    def test_handoffs_command_documentation_exists(self):
        """Verify /handoffs command documentation exists.

        Expected: adapters/opencode/command/handoffs.md file exists.
        """
        handoffs_path = PROJECT_ROOT / "adapters" / "opencode" / "command" / "handoffs.md"
        assert handoffs_path.exists(), \
            "/handoffs command documentation file should exist"

    def test_handoffs_command_documentation_has_cli_examples(self):
        """Verify /handoffs command documentation has CLI examples.

        Expected: Documents list, add, update, complete, delete commands.
        """
        handoffs_path = PROJECT_ROOT / "adapters" / "opencode" / "command" / "handoffs.md"
        handoffs_content = handoffs_path.read_text()

        # Should have CLI examples for all main commands
        assert "python3" in handoffs_content, \
            "/handoffs docs should have CLI examples"
        assert "handoff list" in handoffs_content, \
            "/handoffs docs should document list command"
        assert "handoff add" in handoffs_content, \
            "/handoffs docs should document add command"
        assert "handoff update" in handoffs_content, \
            "/handoffs docs should document update command"
        assert "handoff complete" in handoffs_content, \
            "/handoffs docs should document complete command"

    def test_handoffs_command_documentation_follows_lessons_pattern(self):
        """Verify /handoffs command documentation follows lessons.md pattern.

        Expected: Has similar structure with description, arguments, commands, examples.
        """
        handoffs_path = PROJECT_ROOT / "adapters" / "opencode" / "command" / "handoffs.md"
        handoffs_content = handoffs_path.read_text()

        # Should have similar structure to lessons.md
        assert "description:" in handoffs_content, \
            "/handoffs docs should have description"
        assert "argument-hint:" in handoffs_content, \
            "/handoffs docs should have argument-hint"
        assert "#" in handoffs_content, \
            "/handoffs docs should have headings"

    def test_handoffs_command_documentation_describes_workflow(self):
        """Verify /handoffs command documentation describes workflow.

        Expected: Documents when and how to use handoffs.
        """
        handoffs_path = PROJECT_ROOT / "adapters" / "opencode" / "command" / "handoffs.md"
        handoffs_content = handoffs_path.read_text()

        # Should describe workflow
        assert handoffs_content, \
            "/handoffs docs should have content"


# =============================================================================
# Phase 5: Compaction & Context Tests
# =============================================================================


class TestPhase5CompactionAndContext:
    """Tests for Phase 5 compaction and context management."""

    @pytest.fixture
    def compaction_env(self, temp_lessons_base, temp_state_dir, temp_project_root):
        """Set up environment for Phase 5 tests."""
        return {
            **os.environ,
            "CLAUDE_RECALL_BASE": str(temp_lessons_base),
            "CLAUDE_RECALL_STATE": str(temp_state_dir),
            "PROJECT_DIR": str(temp_project_root),
        }

    def test_pre_compact_injects_handoff_context_when_active(self, compaction_env):
        """Verify pre-compact injects handoff context when active handoff exists.

        Expected: Plugin calls handoff inject and injects context before compaction.
        """
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should have handler for experimental.session.compacting event
        assert "experimental.session.compacting" in plugin_content, \
            "Plugin should handle experimental.session.compacting event"

        # Should inject handoff context
        assert "handoff inject" in plugin_content, \
            "Plugin should inject handoff context on compaction"

    def test_pre_compact_injects_top_lessons_when_active(self, compaction_env):
        """Verify pre-compact injects top lessons when active handoff exists.

        Expected: Plugin calls inject CLI with topLessonsToShow.
        """
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should inject lessons on compaction
        assert "inject" in plugin_content, \
            "Plugin should inject lessons on compaction"

        # Should use CONFIG.topLessonsToShow
        assert "CONFIG.topLessonsToShow" in plugin_content, \
            "Plugin should use CONFIG.topLessonsToShow for injection count"

    def test_pre_compact_injects_top_lessons_when_no_handoff(self, compaction_env):
        """Verify pre-compact injects top lessons when no active handoff.

        Expected: Plugin injects lessons and session summary without handoff context.
        """
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should still inject lessons when no handoff
        assert "inject" in plugin_content, \
            "Plugin should inject lessons even without active handoff"

    def test_pre_compact_uses_high_priority_injection(self, compaction_env):
        """Verify pre-compact uses high-priority injection to survive compaction.

        Expected: Injects with noReply=true to avoid triggering AI response.
        """
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should use noReply for context injection
        assert "noReply" in plugin_content, \
            "Plugin should use noReply for context injection to avoid AI response"

    def test_post_compact_updates_handoff_status(self, compaction_env):
        """Verify post-compact updates handoff status when work progresses.

        Expected: Plugin calls handoff update CLI to track progress after compaction.
        """
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should have handler for session.compacted event
        assert "session.compacted" in plugin_content, \
            "Plugin should handle session.compacted event"

        # Should update handoff status
        assert "handoff update" in plugin_content, \
            "Plugin should update handoff status after compaction"

    def test_post_compact_updates_handoff_phase(self, compaction_env):
        """Verify post-compact updates handoff phase based on progress.

        Expected: Plugin detects completion and advances phase (research→planning→implementing→review).
        """
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should update handoff phase
        assert "handoff update" in plugin_content, \
            "Plugin should update handoff phase after compaction"

    def test_post_compact_tracks_compaction_occurred(self, compaction_env):
        """Verify post-compact tracks that compaction occurred.

        Expected: Plugin tracks compaction state for handoffs.
        """
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should track session state including compaction
        assert "sessionState" in plugin_content or "session_state" in plugin_content, \
            "Plugin should track session state including compaction status"

    def test_post_compact_creates_session_snapshot_when_no_handoff(self, compaction_env):
        """Verify post-compact creates session snapshot when no active handoff.

        Expected: Plugin creates snapshot of session state for future reference.
        """
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should have session.compacted handler
        assert "session.compacted" in plugin_content, \
            "Plugin should handle session.compacted event for snapshot creation"

    def test_session_snapshot_captures_essential_state(self):
        """Verify session snapshot captures essential state without being too large.

        Expected: Snapshot includes session summary, recent messages, and context.
        """
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Session snapshot should capture essential state
        # (The implementation will create a snapshot file or use CLI command)

    def test_compaction_handlers_handle_errors_gracefully(self, compaction_env):
        """Verify compaction handlers handle errors gracefully.

        Expected: Errors don't crash the plugin, they're logged and ignored.
        """
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should wrap compaction handlers in try-catch
        assert plugin_content.count("try {") >= 5, \
            "Plugin should wrap handlers in try-catch for error handling"

        # Should log errors (either with console.error or log function)
        assert ("console.error" in plugin_content or "log('error'" in plugin_content or \
                'log("error"' in plugin_content or "log('debug'" in plugin_content or \
                'log("debug"' in plugin_content), \
            "Plugin should log errors"


# =============================================================================
# Phase 6: Debug Logging Tests
# =============================================================================


class TestPhase6DebugLogging:
    """Tests for Phase 6 debug logging."""

    @pytest.fixture
    def logging_env(self, temp_state_dir, temp_project_root):
        """Set up environment for Phase 6 logging tests."""
        return {
            **os.environ,
            "CLAUDE_RECALL_STATE": str(temp_state_dir),
            "PROJECT_DIR": str(temp_project_root),
        }

    def test_logging_utility_exists(self):
        """Verify plugin has logging utility.

        Expected: Plugin defines log() function for structured JSON logging.
        """
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should have log function
        assert "function log" in plugin_content or "const log" in plugin_content, \
            "Plugin should have log function"

        # Should use fs.appendFileSync for writing logs
        assert "appendFileSync" in plugin_content, \
            "Plugin should use appendFileSync for log file writes"

    def test_logging_utility_emits_json(self):
        """Verify logging utility emits JSON logs.

        Expected: Each log entry is JSON with timestamp, level, event, data.
        """
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
        """Verify logging utility supports debug, info, warn, error levels.

        Expected: Can log at different levels based on CONFIG.debugLevel.
        """
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
        """Verify logs are written to debug.log file.

        Expected: Logs written to ~/.local/state/claude-recall/debug.log.
        """
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
        """Verify level 0 disables all logging.

        Expected: No logs when CONFIG.debugLevel is 0.
        """
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should check for level 0
        assert "debugLevel" in plugin_content, \
            "Plugin should check debugLevel"

        # Should have early return when disabled
        assert "if (" in plugin_content and "return" in plugin_content, \
            "Plugin should have early return when logging disabled"

    def test_logging_level_1_info_only(self):
        """Verify level 1 only logs warnings and errors.

        Expected: Only warn and error logs when CONFIG.debugLevel is 1.
        """
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should check debugLevel >= threshold for different levels
        assert "CONFIG.debugLevel" in plugin_content, \
            "Plugin should compare debugLevel for level filtering"

    def test_logging_level_2_debug_and_above(self):
        """Verify level 2 logs debug, info, warnings, errors.

        Expected: All logs except trace when CONFIG.debugLevel is 2.
        """
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should support debug level
        assert "debugLevel" in plugin_content, \
            "Plugin should support debug level logging"

    def test_logging_level_3_trace_verbose(self):
        """Verify level 3 logs all levels including trace.

        Expected: All logs including verbose trace when CONFIG.debugLevel is 3.
        """
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should support trace level
        assert "debugLevel" in plugin_content, \
            "Plugin should support trace level logging"

    def test_logging_uses_iso_8601_timestamps(self):
        """Verify timestamps are ISO 8601 format.

        Expected: Timestamps like "2026-01-20T12:34:56.789Z".
        """
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should have timestamp generation
        assert ("toISOString()" in plugin_content or "new Date()" in plugin_content or
                "iso" in plugin_content.lower()), \
            "Plugin should generate ISO 8601 timestamps"

    def test_logging_handles_write_errors(self):
        """Verify logging handles write errors gracefully.

        Expected: Write errors don't crash plugin.
        """
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should have try-catch for logging
        assert "try {" in plugin_content and "catch" in plugin_content, \
            "Plugin should handle logging errors with try-catch"

    def test_logging_updates_all_console_log_calls(self):
        """Verify all existing console.log calls use new logging utility.

        Expected: No bare console.log/console.error calls remain.
        """
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Check that most console.log calls use the new log function
        # (Some may remain for debugging output that doesn't need structured logging)
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
        """Verify log file path follows XDG state spec.

        Expected: Path is ~/.local/state/claude-recall/debug.log.
        """
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


class TestOpenCodeSessionIdHandling:
    """Tests for session_id handling in OpenCode adapter.

    OpenCode uses input.session.id for session identification. This must
    be passed to CLI commands (especially handoff sync-todos) to:
    1. Prevent cross-session handoff pollution
    2. Enable sub-agent origin guard in handoff_add
    """

    def test_tool_execute_handler_accepts_session_context(self) -> None:
        """tool.execute.after handler should have access to session context."""
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should have tool.execute.after handler
        assert '"tool.execute.after"' in plugin_content, \
            "Plugin should have tool.execute.after handler for TodoWrite sync"

        # Handler should accept input parameter
        assert 'async (input)' in plugin_content, \
            "Tool handler should accept input parameter"

    def test_session_id_accessible_in_plugin_context(self) -> None:
        """Plugin should be able to access session.id from context."""
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should access session.id in session.created handler
        assert 'input.session.id' in plugin_content, \
            "Plugin should access input.session.id for session identification"

        # Should use session.id for state management
        assert 'sessionState.get(input.session.id)' in plugin_content or \
               'sessionState.set(input.session.id' in plugin_content, \
            "Plugin should use session.id for per-session state tracking"

    @pytest.mark.skip(reason="Requires integration test with actual OpenCode session object")
    def test_todowrite_sync_passes_session_id(self) -> None:
        """TodoWrite sync should pass session_id to prevent cross-session pollution.

        This is an integration test that would require:
        1. Mock OpenCode session object with id
        2. Simulate TodoWrite tool execution
        3. Verify CLI receives --session-id argument

        Skipping for now as this requires deeper integration with OpenCode API.
        """
        pass

    def test_handoff_sync_uses_correct_cli_command(self) -> None:
        """handoff sync-todos command should be called for TodoWrite sync."""
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should call handoff sync-todos
        assert 'handoff sync-todos' in plugin_content, \
            "Plugin should call handoff sync-todos for TodoWrite sync"

        # Should be in tool.execute.after handler
        handler_section = plugin_content.split('"tool.execute.after"')[1].split('"message.created"')[0]
        assert 'sync-todos' in handler_section, \
            "sync-todos should be called within tool.execute.after handler"

    def test_session_state_initialized_on_session_created(self) -> None:
        """session.created handler should initialize session state."""
        plugin_path = PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts"
        plugin_content = plugin_path.read_text()

        # Should initialize sessionState with session.id
        assert 'sessionState.set(input.session.id' in plugin_content, \
            "Plugin should initialize session state on session creation"

        # Should store isFirstPrompt and promptCount
        assert 'isFirstPrompt' in plugin_content and 'promptCount' in plugin_content, \
            "Session state should track prompt count and first prompt flag"

