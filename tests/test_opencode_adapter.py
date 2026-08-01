#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Test suite for OpenCode adapter.

Tests verify the TypeScript plugin structure and Go CLI delegation against
@opencode-ai/plugin 1.17.5 (OpenCode 1.18.x). Business logic tests are in
go/cmd/recall/opencode_test.go.

Run with: pytest tests/test_opencode_adapter.py -v
"""

import re
from pathlib import Path

import pytest

# Get the project root directory
PROJECT_ROOT = Path(__file__).parent.parent


# =============================================================================
# Helpers
# =============================================================================


@pytest.fixture
def plugin_content() -> str:
    """Load the TypeScript plugin source."""
    return (PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts").read_text()


@pytest.fixture
def memory_content() -> str:
    """Load the pure MEMORY.md logic module (adapters/opencode/lib/memory.ts)."""
    return (PROJECT_ROOT / "adapters" / "opencode" / "lib" / "memory.ts").read_text()


def top_level_hook(content: str, name: str) -> bool:
    """True if `name` is registered as a top-level plugin hook (key: async fn)."""
    return bool(re.search(rf'^\s*"{re.escape(name)}":\s*async', content, re.MULTILINE))


def code_only(content: str) -> str:
    """Strip comment lines so absence assertions check code, not prose."""
    content = re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL)
    return "\n".join(
        line for line in content.split("\n") if not line.strip().startswith("//")
    )


# =============================================================================
# Plugin Structure Tests - hook surface matches @opencode-ai/plugin 1.17.5
# =============================================================================


class TestChatMessage:
    """Tests for the chat.message hook (per-prompt injections)."""

    def test_chat_message_hook_exists(self, plugin_content):
        """Verify chat.message hook is registered."""
        assert '"chat.message"' in plugin_content, \
            "Plugin should register the chat.message hook"

    def test_smart_injection_calls_score_relevance(self, plugin_content):
        """Verify smart injection calls score-relevance CLI command."""
        assert "score-relevance" in plugin_content, \
            "Plugin should call score-relevance for smart injection"
        assert "CONFIG.relevanceTopN" in plugin_content, \
            "Plugin should use CONFIG.relevanceTopN for relevance scoring"

    def test_smart_injection_on_first_prompt_only(self, plugin_content):
        """Verify smart injection only happens on first prompt."""
        assert "isFirstPrompt" in plugin_content, \
            "Plugin should track isFirstPrompt state"

    def test_no_periodic_reminder_injection(self, plugin_content):
        """Periodic re-injection is gone. Session-start context plus per-prompt
        relevance cover the same ground, and a prompt counter fires on nothing
        that correlates with the model actually losing the lessons."""
        assert "remindEvery" not in plugin_content, \
            "Plugin should not carry a periodic reminder interval"
        assert "promptCount" not in plugin_content, \
            "Plugin should not count prompts for periodic reminders"

    def test_injections_append_synthetic_parts(self, plugin_content):
        """Verify per-prompt injections append synthetic parts to the message."""
        assert "output.parts.push" in plugin_content, \
            "chat.message injections should append to output.parts"
        assert "synthetic: true" in plugin_content, \
            "Injected parts should be marked synthetic"


# =============================================================================
# Compaction handling
# =============================================================================


class TestMemoryInjection:
    """Tests for the Claude Code auto-memory (MEMORY.md) injection feature.

    The pure logic lives in adapters/opencode/lib/memory.ts (a subdirectory
    module) because OpenCode auto-loads every top-level plugins/*.ts file as
    a plugin entry and calls each exported function - exported helpers in the
    entry file would be invoked with PluginInput and crash the load.
    """

    def test_plugin_imports_memory_lib(self, plugin_content):
        """Verify plugin.ts delegates to lib/memory (not inline logic)."""
        assert 'from "./lib/memory"' in plugin_content, \
            "plugin.ts should import MEMORY.md logic from ./lib/memory"
        assert "readMemoryContext" in plugin_content, \
            "plugin.ts should call readMemoryContext"
        assert "CONFIG.memoryMaxBytes" in plugin_content, \
            "plugin.ts should pass CONFIG.memoryMaxBytes as the cap"

    def test_memory_lib_is_not_a_plugin_entry(self, memory_content):
        """lib/memory.ts must not register plugin hooks (import-safe module)."""
        assert "experimental.chat.system.transform" not in memory_content
        assert "chat.message" not in memory_content

    def test_plugin_exports_only_the_plugin(self, plugin_content):
        """Every top-level export is called as a plugin by OpenCode's loader -
        the entry file must export ONLY the plugin function itself."""
        exports = re.findall(r"^export\s+(?:async\s+)?(?:function|const|class)\s+(\w+)",
                             plugin_content, re.MULTILINE)
        assert exports == [] or set(exports) <= {"LessonsPlugin"}, \
            f"plugin.ts exports non-plugin symbols: {exports}"
        assert "export const LessonsPlugin" in plugin_content, \
            "plugin.ts should export LessonsPlugin"

    def test_reads_project_memory_md(self, memory_content):
        """Verify lib reads ~/.claude/projects/<hash>/memory/MEMORY.md."""
        assert ".claude" in memory_content and "projects" in memory_content, \
            "lib should look up ~/.claude/projects"
        assert "MEMORY.md" in memory_content, \
            "lib should read MEMORY.md"

    def test_memory_hash_replaces_separators(self, memory_content):
        """Verify the project hash replaces '/' (and '.') with '-'."""
        assert re.search(r"replace\(/\[/\.\]/g?, '-'\)", memory_content) or \
            re.search(r"replace\(/\\\//g, '-'\)", memory_content), \
            "lib should hash cwd by replacing path separators with '-'"

    def test_memory_hash_has_legacy_fallback(self, memory_content):
        """Verify both hash forms are tried (dotted and legacy slash-only)."""
        assert "dotted" in memory_content and "slashed" in memory_content, \
            "lib should compute both the dotted and slash-only hash forms"
        assert "candidates" in memory_content, \
            "lib should try candidate hash dirs in order"

    def test_handles_global_tier(self, memory_content):
        """Verify global memory tier is read via the memory/global symlink."""
        assert "memory-global" in memory_content, \
            "lib should read ~/.claude/memory-global/MEMORY.md"
        assert "isSymbolicLink" in memory_content, \
            "Global tier should be detected via the memory/global symlink"

    def test_memory_content_is_capped(self, memory_content, plugin_content):
        """Verify injected MEMORY.md content is capped (~8KB) with a skip-note."""
        assert "memoryMaxBytes" in plugin_content, \
            "Plugin should have a configurable memory cap (memoryMaxBytes)"
        assert "8192" in plugin_content, \
            "Default memory cap should be 8192 bytes"
        assert "Read the full file" in memory_content, \
            "Oversized MEMORY.md should include a skip-note pointing at the file"

    def test_missing_memory_files_silently_skipped(self, memory_content):
        """Verify missing MEMORY.md files don't produce output or errors."""
        assert "existsSync" in memory_content, \
            "lib should check file existence before reading"


# =============================================================================
# WRITE BRIDGE: opencode lessons -> Claude Code auto-memory files
# =============================================================================


class TestMemoryWriteBridge:
    """Tests for the write bridge: newly captured opencode lessons are mirrored
    as feedback_<slug>.md memory files plus a bridge-owned MEMORY.md section,
    so Claude Code sessions read them through native auto-memory."""

    def test_lib_has_mirror_functions(self, memory_content):
        """Verify the pure mirror logic lives in lib/memory.ts."""
        for symbol in ("mirrorLessonToMemory", "mirrorLessonsBatch",
                       "upsertBridgeIndexEntry", "slugify", "parseLessonsFile",
                       "memoryDirOrCreate"):
            assert f"export function {symbol}" in memory_content, \
                f"lib should export {symbol}"

    def test_bridge_section_is_dedicated(self, memory_content):
        """Verify the bridge owns a dedicated MEMORY.md section."""
        assert "## From opencode (claude-recall)" in memory_content, \
            "Bridge should own the '## From opencode (claude-recall)' section"

    def test_mirror_file_format_matches_claude_memory(self, memory_content):
        """Verify mirrored files use the feedback frontmatter + provenance."""
        assert "type: feedback" in memory_content, \
            "Mirrored files should use type: feedback frontmatter"
        assert "Source: claude-recall lesson" in memory_content, \
            "Mirrored files should carry a provenance line"
        assert "via opencode" in memory_content, \
            "Provenance should identify the opencode source"

    def test_mirror_collision_suffixing(self, memory_content):
        """Verify filename collisions with different content get -2/-3 suffixes."""
        assert "identical_content" in memory_content, \
            "Identical re-mirrors should be skipped"
        assert "-${i}" in memory_content, \
            "Collisions should suffix the slug with -2, -3, ..."

    def test_plugin_mirrors_on_lessons_added(self, plugin_content):
        """Verify the plugin mirrors lessons reported by Go session-idle."""
        assert "mirrorAddedLessons" in plugin_content, \
            "Plugin should have a mirrorAddedLessons handler"
        assert re.search(r"lessons_added.*\n.*mirrorAddedLessons|"
                         r"result\.lessons_added\?\.length\) \{\n\s*log\('info', 'lessons\.added'.*\n\s*mirrorAddedLessons",
                         plugin_content), \
            "session.idle should mirror when lessons_added is non-empty"

    def test_plugin_mirrors_project_lessons_only(self, plugin_content):
        """Verify system lessons (S###) are never mirrored."""
        assert re.search(r"/\^L\\d\{3\}\$/", plugin_content), \
            "Plugin should restrict mirroring to project lesson IDs (L###)"
        assert "system_lesson_not_mirrored" in plugin_content, \
            "Plugin should log when system lessons are skipped"

    def test_plugin_mirror_config_guards(self, plugin_content):
        """Verify mirrorMemory / mirrorMemoryMaxPerSession config guards."""
        assert "mirrorMemory: true" in plugin_content, \
            "mirrorMemory should default to true"
        assert "mirrorMemoryMaxPerSession: 10" in plugin_content, \
            "mirrorMemoryMaxPerSession should default to 10"
        assert "CONFIG.mirrorMemory" in plugin_content
        assert "CONFIG.mirrorMemoryMaxPerSession" in plugin_content

    def test_plugin_mirror_structured_log_events(self, plugin_content):
        """Verify the three structured log events exist."""
        for event in ("memory.mirror_written", "memory.mirror_skipped", "memory.mirror_error"):
            assert event in plugin_content, f"Plugin should log {event}"

    def test_plugin_mirror_failure_isolated(self, plugin_content):
        """Mirroring must never break the session.idle flow (try/catch + no throw)."""
        assert "session_cap" in plugin_content, \
            "Runaway cap should skip with reason session_cap"
        # mirrorAddedLessons body must be wrapped in try/catch
        m = re.search(r"function mirrorAddedLessons.*?\n  \}\n", plugin_content, re.DOTALL)
        assert m and "try {" in m.group(0) and "catch" in m.group(0), \
            "mirrorAddedLessons should be failure-isolated"

    def test_lib_mirror_failure_isolated(self, memory_content):
        """The lib returns error outcomes instead of throwing."""
        assert "status: 'error'" in memory_content, \
            "mirror outcomes should carry an error status instead of throwing"


# =============================================================================
# DEEP READ: relevance over the full memory dir
# =============================================================================


class TestMemoryDeepRead:
    """Tests for the deep-read feature: the first prompt ranks the actual
    memory files (not just the MEMORY.md index) and injects the top matches."""

    def test_lib_has_relevance_functions(self, memory_content):
        """Verify listing + ranking logic lives in lib/memory.ts."""
        for symbol in ("listMemoryFiles", "rankMemoryFiles"):
            assert f"export function {symbol}" in memory_content, \
                f"lib should export {symbol}"

    def test_lib_excludes_index_and_includes_global_symlink(self, memory_content):
        """MEMORY.md excluded (already injected as index); global/ included."""
        assert "MEMORY.md" in memory_content, \
            "lib should exclude MEMORY.md from candidates"
        assert "global/" in memory_content, \
            "lib should namespace global-tier files as global/<name>"
        assert "isSymbolicLink" in memory_content, \
            "global tier should be detected via the memory/global symlink"

    def test_lib_read_is_byte_capped(self, memory_content):
        """Verify per-file reads use a true byte cap (fd read, not full file)."""
        assert "MEMORY_FILE_READ_CAP" in memory_content
        assert "4096" in memory_content, \
            "Default read cap should be ~4KB"
        assert "openSync" in memory_content and "readSync" in memory_content, \
            "Reads should be byte-capped via fd, not whole-file readFileSync"

    def test_lib_scoring_is_dependency_free(self, memory_content):
        """Verify scoring tokenizes on non-alnum and is deterministic."""
        assert "tokenize" in memory_content, \
            "lib should have a tokenizer"
        assert re.search(r"split\(/\[\^a-z0-9\]\+/\)", memory_content), \
            "Tokenizer should split on non-alphanumeric runs"
        assert "Math.log" in memory_content, \
            "Scoring should use log-based idf/tf weighting"

    def test_plugin_injects_relevant_memory_part(self, plugin_content):
        """Verify <relevant-memory> synthetic part injection on first prompt."""
        assert "<relevant-memory>" in plugin_content, \
            "Plugin should inject a <relevant-memory> part"
        assert "rankMemoryFiles" in plugin_content, \
            "Plugin should call rankMemoryFiles"
        assert "MEMORY_INJECT_FILE_CAP" in plugin_content, \
            "Injected per-file content should be capped"

    def test_plugin_memory_relevance_config(self, plugin_content):
        """Verify memoryRelevance / memoryRelevanceTopN config keys."""
        assert "memoryRelevance: true" in plugin_content, \
            "memoryRelevance should default to true"
        assert "memoryRelevanceTopN: 2" in plugin_content, \
            "memoryRelevanceTopN should default to 2"
        assert "CONFIG.memoryRelevance" in plugin_content
        assert "CONFIG.memoryRelevanceTopN" in plugin_content

    def test_plugin_memory_relevance_log_event(self, plugin_content):
        """Verify chat.memory_relevance_injected logs files + scores."""
        assert "chat.memory_relevance_injected" in plugin_content, \
            "Plugin should log chat.memory_relevance_injected"
        assert re.search(r"memory_relevance_injected'.*\{[^}]*files|files: ranked",
                         plugin_content, re.DOTALL), \
            "The log event should include the ranked file list"


# =============================================================================
# Debug logging
# =============================================================================


class TestDebugLogging:
    """Tests for debug logging infrastructure."""

    def test_logging_utility_exists(self, plugin_content):
        """Verify plugin has logging utility."""
        assert "function log" in plugin_content or "const log" in plugin_content, \
            "Plugin should have log function"
        assert "appendFileSync" in plugin_content, \
            "Plugin should use appendFileSync for log file writes"

    def test_logging_utility_emits_json(self, plugin_content):
        """Verify logging utility emits JSON logs."""
        assert "JSON.stringify" in plugin_content, \
            "Plugin should use JSON.stringify for structured logs"
        for field in ("timestamp", "level", "event"):
            assert field in plugin_content, \
                f"Logs should include {field} field"

    def test_logging_supports_levels(self, plugin_content):
        """Verify logging utility supports debug, info, warn, error levels."""
        assert ("debug" in plugin_content and "info" in plugin_content and
                "warn" in plugin_content and "error" in plugin_content), \
            "Plugin should support debug, info, warn, error levels"
        assert "CONFIG.debugLevel" in plugin_content, \
            "Plugin should check CONFIG.debugLevel for filtering"

    def test_logging_writes_to_debug_log(self, plugin_content):
        """Verify logs are written to debug.log file."""
        assert "debug.log" in plugin_content, \
            "Plugin should write to debug.log file"
        assert ".local" in plugin_content or "state" in plugin_content, \
            "Plugin should use XDG state directory for logs"
        assert "mkdirSync" in plugin_content or "existsSync" in plugin_content, \
            "Plugin should create log directory if it doesn't exist"

    def test_logging_uses_iso_8601_timestamps(self, plugin_content):
        """Verify timestamps are ISO 8601 format."""
        assert ("toISOString()" in plugin_content or "new Date()" in plugin_content), \
            "Plugin should generate ISO 8601 timestamps"

    def test_logging_handles_write_errors(self, plugin_content):
        """Verify logging handles write errors gracefully."""
        assert "try {" in plugin_content and "catch" in plugin_content, \
            "Plugin should handle logging errors with try-catch"

    def test_no_bare_console_calls(self, plugin_content):
        """Verify all logging goes through the log() utility."""
        assert "console.log" not in plugin_content, \
            "Plugin should use log() instead of console.log"
        assert "console.error" not in plugin_content, \
            "Plugin should use log() instead of console.error"

    def test_log_file_path_follows_xdg_spec(self, plugin_content):
        """Verify log file path follows XDG state spec."""
        assert ".local" in plugin_content, \
            "Plugin should use .local directory for XDG state"
        assert "claude-recall" in plugin_content, \
            "Plugin should use claude-recall subdirectory"
        assert "debug.log" in plugin_content, \
            "Plugin should use debug.log as log file name"


# =============================================================================
# Session state management
# =============================================================================


class TestSessionState:
    """Tests for session state management."""

    def test_plugin_tracks_session_state(self, plugin_content):
        """Verify plugin tracks per-session state."""
        assert "new Map" in plugin_content, \
            "Plugin should use Map for session state tracking"
        assert "isFirstPrompt" in plugin_content, \
            "Plugin should track isFirstPrompt state"
        assert "compactionOccurred" in plugin_content, \
            "Plugin should track compactionOccurred state"

    def test_plugin_initializes_state_on_session_created(self, plugin_content):
        """Verify session state is initialized via ensureSession."""
        assert "state.set(" in plugin_content, \
            "Plugin should initialize session state"

    def test_plugin_cleans_up_state_on_session_deleted(self, plugin_content):
        """Verify session state is cleaned up on session.deleted."""
        assert 'case "session.deleted"' in plugin_content, \
            "event hook should handle session.deleted"
        assert ".delete(" in plugin_content, \
            "Plugin should clean up session state on deletion"

    def test_plugin_uses_session_id_for_state_key(self, plugin_content):
        """Verify plugin uses the session id as state key."""
        assert "properties.sessionID" in plugin_content or \
               "properties.info.id" in plugin_content, \
            "Plugin should key state by the SDK session id"


# =============================================================================
# Go CLI integration
# =============================================================================

