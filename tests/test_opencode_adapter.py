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


class TestPluginStructure:
    """Tests for plugin file structure and Go CLI delegation."""

    def test_plugin_uses_go_cli_not_old_bash_script(self, plugin_content):
        """Verify plugin doesn't reference old bash script path."""
        assert "lessons-manager.sh" not in plugin_content, \
            "Plugin still references old bash script path"

    def test_plugin_has_exec_go_function(self, plugin_content):
        """Verify plugin has execGo function for Go CLI delegation."""
        assert "async function execGo" in plugin_content, \
            "Plugin should have execGo function"
        assert "ALLOWED_GO_COMMANDS" in plugin_content, \
            "Plugin should have ALLOWED_GO_COMMANDS whitelist"

    def test_plugin_allowed_go_commands(self, plugin_content):
        """Verify plugin has correct Go command whitelist."""
        expected_commands = ["session-start", "session-idle", "pre-compact", "post-compact", "session-end"]
        for cmd in expected_commands:
            assert f"'{cmd}'" in plugin_content or f'"{cmd}"' in plugin_content, \
                f"Plugin should have '{cmd}' in ALLOWED_GO_COMMANDS"

    def test_lifecycle_uses_single_event_hook(self, plugin_content):
        """In 1.17.5 lifecycle events arrive via the single `event` hook."""
        assert re.search(r'^\s*event:\s*async', plugin_content, re.MULTILINE), \
            "Plugin should register the single `event` hook"

    def test_no_stale_top_level_lifecycle_hooks(self, plugin_content):
        """Stale 1.1.x top-level lifecycle hooks must be gone."""
        for stale in ("session.created", "session.deleted", "session.idle",
                      "session.compacted", "message.created", "command.executed"):
            assert not top_level_hook(plugin_content, stale), \
                f"'{stale}' is not a top-level hook in 1.17.5 - use the event hook"

    def test_event_hook_handles_lifecycle_events(self, plugin_content):
        """Verify the event hook switches on the SDK Event union members."""
        for event_type in ('case "session.created"', 'case "session.deleted"',
                           'case "session.idle"', 'case "session.compacted"',
                           'case "todo.updated"'):
            assert event_type in plugin_content, \
                f"event hook should handle {event_type}"

    def test_plugin_calls_session_start_on_session_created(self, plugin_content):
        """Verify session initialization calls Go session-start."""
        assert 'execGo("session-start"' in plugin_content, \
            "Session initialization should call execGo('session-start')"

    def test_plugin_calls_session_idle_for_processing(self, plugin_content):
        """Verify session.idle handling calls Go session-idle."""
        assert 'execGo("session-idle"' in plugin_content, \
            "session.idle should call execGo('session-idle')"

    def test_plugin_has_dispose_hook(self, plugin_content):
        """Verify plugin cleans up its interval via the dispose hook."""
        assert "dispose" in plugin_content, \
            "Plugin should implement dispose to clear timers"
        assert "clearInterval" in plugin_content, \
            "dispose should clear the stale-session cleanup interval"


# =============================================================================
# Session-start injection via experimental.chat.system.transform
# =============================================================================


class TestSessionStartInjection:
    """Session-start context is injected through the system-prompt channel."""

    def test_system_transform_hook_exists(self, plugin_content):
        """Verify experimental.chat.system.transform hook is registered."""
        assert '"experimental.chat.system.transform"' in plugin_content, \
            "Plugin should register experimental.chat.system.transform"

    def test_system_transform_pushes_to_system_array(self, plugin_content):
        """Verify injection appends to output.system (not synthetic prompts)."""
        assert "output.system.push" in plugin_content, \
            "Session-start context should be pushed to output.system"

    def test_session_start_context_includes_all_sources(self, plugin_content):
        """Verify lessons, handoffs, todos and duty reminders are injected."""
        for key in ("lessons_context", "handoffs_context", "todos_prompt", "duty_reminders"):
            assert key in plugin_content, \
                f"Session-start injection should include {key}"

    def test_no_synthetic_prompt_injection(self, plugin_content):
        """client.session.prompt({noReply}) hacks must be gone."""
        code = code_only(plugin_content)
        assert "noReply" not in code, \
            "noReply synthetic-message injection is obsolete - use system.transform"
        assert "client.session.prompt" not in code, \
            "client.session.prompt is obsolete for context injection"


# =============================================================================
# chat.message: first-prompt relevance + periodic reminders
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

    def test_periodic_reminders_on_nth_prompt(self, plugin_content):
        """Verify periodic reminders show high-star lessons every N prompts."""
        assert "promptCount" in plugin_content, \
            "Plugin should track prompt count for periodic reminders"
        assert "CONFIG.remindEvery" in plugin_content, \
            "Plugin should use CONFIG.remindEvery for reminder frequency"

    def test_periodic_reminders_inject_top_lessons(self, plugin_content):
        """Verify periodic reminders inject top lessons by stars."""
        assert "inject" in plugin_content, \
            "Plugin should call inject CLI command for periodic reminders"
        assert "CONFIG.topLessonsToShow" in plugin_content, \
            "Plugin should use CONFIG.topLessonsToShow for reminders"

    def test_injections_append_synthetic_parts(self, plugin_content):
        """Verify per-prompt injections append synthetic parts to the message."""
        assert "output.parts.push" in plugin_content, \
            "chat.message injections should append to output.parts"
        assert "synthetic: true" in plugin_content, \
            "Injected parts should be marked synthetic"


# =============================================================================
# Compaction handling
# =============================================================================


class TestCompactionHandlers:
    """Tests for pre/post compaction handling."""

    def test_compacting_hook_uses_output_context(self, plugin_content):
        """Verify pre-compact context goes to output.context (new signature)."""
        assert '"experimental.session.compacting"' in plugin_content, \
            "Plugin should handle experimental.session.compacting"
        assert "output.context.push" in plugin_content, \
            "Pre-compact context should be pushed to output.context"
        assert 'execGo("pre-compact"' in plugin_content, \
            "compacting handler should call execGo('pre-compact')"

    def test_session_compacted_event_calls_post_compact(self, plugin_content):
        """Verify session.compacted event calls Go post-compact."""
        assert 'case "session.compacted"' in plugin_content, \
            "event hook should handle session.compacted"
        assert 'execGo("post-compact"' in plugin_content, \
            "compacted handler should call execGo('post-compact')"

    def test_post_compact_tracks_compaction_occurred(self, plugin_content):
        """Verify post-compact tracks that compaction occurred."""
        assert "compactionOccurred" in plugin_content, \
            "Plugin should track compactionOccurred in session state"

    def test_compaction_handlers_handle_errors_gracefully(self, plugin_content):
        """Verify compaction handlers handle errors gracefully."""
        assert plugin_content.count("try {") >= 5, \
            "Plugin should wrap handlers in try-catch for error handling"
        assert ("log('error'" in plugin_content or 'log("error"' in plugin_content or
                "log('debug'" in plugin_content or 'log("debug"' in plugin_content), \
            "Plugin should log errors"


# =============================================================================
# Todo sync via the native todo.updated event
# =============================================================================


class TestTodoSync:
    """OpenCode's todo tool is `todowrite`; the SDK emits todo.updated with the
    full list, so sync hooks the event instead of sniffing tool executions."""

    def test_todo_sync_uses_todo_updated_event(self, plugin_content):
        """Verify todo sync is driven by the todo.updated event."""
        assert 'case "todo.updated"' in plugin_content, \
            "Plugin should handle the todo.updated event"

    def test_todo_sync_calls_cli_sync_todos(self, plugin_content):
        """Verify todo sync calls handoff sync-todos CLI command."""
        assert "sync-todos" in plugin_content, \
            "Plugin should call handoff sync-todos CLI command"
        assert "--session-id" in plugin_content, \
            "sync-todos should be scoped to the current session"

    def test_no_tool_execute_after_hook(self, plugin_content):
        """The old tool.execute.after/TodoWrite coupling must be gone."""
        assert '"tool.execute.after"' not in plugin_content, \
            "tool.execute.after is unnecessary - todo.updated carries the full list"
        assert "TodoWrite" not in plugin_content, \
            "TodoWrite is Claude Code's tool name; OpenCode's is `todowrite`"


# =============================================================================
# Slash commands: native OpenCode commands, no interception
# =============================================================================


class TestSlashCommands:
    """Tests for slash command handling (TypeScript-specific)."""

    def test_lessons_command_uses_opencode_paths(self):
        """Verify /lessons command documentation uses correct paths."""
        lessons_path = PROJECT_ROOT / "adapters" / "opencode" / "command" / "lessons.md"
        lessons_content = lessons_path.read_text()

        assert "~/.claude/plugins/cache/" not in lessons_content, \
            "/lessons docs still reference Claude Code paths"
        assert "claude-recall" in lessons_content, \
            "/lessons docs should use claude-recall wrapper"

    def test_no_command_interception_in_plugin(self, plugin_content):
        """Native command/*.md files handle /lessons and /handoffs; the plugin
        must not intercept commands or revert messages."""
        code = code_only(plugin_content)
        assert "command.executed" not in code, \
            "command.executed interception is obsolete - native commands handle it"
        assert "client.session.revert" not in code, \
            "message-revert hack is obsolete with native commands"
        assert '"command.execute.before"' not in code, \
            "command.execute.before is unnecessary - the .md commands run the CLI"

    def test_handoffs_command_documentation_exists(self):
        """Verify /handoffs command documentation exists."""
        handoffs_path = PROJECT_ROOT / "adapters" / "opencode" / "command" / "handoffs.md"
        assert handoffs_path.exists(), \
            "/handoffs command documentation file should exist"

    def test_handoffs_command_documentation_has_cli_examples(self):
        """Verify /handoffs command documentation has CLI examples."""
        handoffs_content = (PROJECT_ROOT / "adapters" / "opencode" / "command" / "handoffs.md").read_text()

        assert "claude-recall handoff" in handoffs_content, \
            "/handoffs docs should reference CLI wrapper"
        assert "$ARGUMENTS" in handoffs_content, \
            "/handoffs docs should pass through arguments"

    def test_handoffs_command_documentation_follows_lessons_pattern(self):
        """Verify /handoffs command documentation follows lessons.md pattern."""
        handoffs_content = (PROJECT_ROOT / "adapters" / "opencode" / "command" / "handoffs.md").read_text()

        assert "description:" in handoffs_content, \
            "/handoffs docs should have description"
        assert "argument-hint:" in handoffs_content, \
            "/handoffs docs should have argument-hint"
        assert "Command:" in handoffs_content, \
            "/handoffs docs should include command section"


# =============================================================================
# MEMORY.md injection (Claude Code auto-memory)
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
        assert "promptCount" in plugin_content, \
            "Plugin should track promptCount state"
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


class TestGoCliIntegration:
    """Tests for Go CLI integration patterns."""

    def test_plugin_finds_recall_binary(self, plugin_content):
        """Verify plugin has binary detection logic."""
        assert "findRecallBinary" in plugin_content or "findBinary" in plugin_content, \
            "Plugin should have binary detection function"
        assert "RECALL_BINARY" in plugin_content, \
            "Plugin should cache recall binary path"

    def test_plugin_validates_go_commands(self, plugin_content):
        """Verify plugin validates commands against whitelist."""
        assert "ALLOWED_GO_COMMANDS.has" in plugin_content, \
            "Plugin should validate commands against ALLOWED_GO_COMMANDS"

    def test_plugin_handles_go_cli_errors(self, plugin_content):
        """Verify plugin handles Go CLI errors gracefully."""
        assert "binary not found" in plugin_content.lower() or "not found" in plugin_content.lower(), \
            "Plugin should handle missing binary"

    def test_plugin_passes_project_dir_to_go(self, plugin_content):
        """Verify plugin passes PROJECT_DIR to Go CLI."""
        assert "PROJECT_DIR" in plugin_content, \
            "Plugin should pass PROJECT_DIR env to the Go CLI"
        assert "process.cwd()" in plugin_content, \
            "Plugin should fall back to process.cwd() for the project directory"

    def test_plugin_parses_go_json_output(self, plugin_content):
        """Verify plugin parses JSON output from Go CLI."""
        assert "JSON.parse" in plugin_content, \
            "Plugin should parse JSON output from Go CLI"

    def test_plugin_has_timeout_for_go_commands(self, plugin_content):
        """Verify plugin has timeout for Go CLI commands."""
        assert "setTimeout" in plugin_content or "timeout" in plugin_content.lower(), \
            "Plugin should have timeout for Go CLI commands"

    def test_subprocess_uses_argv_spawn_no_shell(self, plugin_content):
        """Verify subprocesses are spawned with argv arrays (no shell)."""
        assert "spawn" in plugin_content, \
            "Plugin should use spawn for subprocess execution"
        assert "shell: true" not in plugin_content, \
            "Plugin must not spawn through a shell"
        assert "$`" not in plugin_content, \
            "BunShell tagged templates are gone - spawn argv is injection-safe"


# =============================================================================
# Legacy CLI delegation (score-relevance / inject / handoff)
# =============================================================================


class TestLegacyCliDelegation:
    """Tests for non-`opencode` recall CLI commands used by the adapter."""

    def test_plugin_has_cli_command_whitelist(self, plugin_content):
        """Verify plugin whitelists the legacy CLI commands it may spawn."""
        assert "ALLOWED_CLI_COMMANDS" in plugin_content, \
            "Plugin should have ALLOWED_CLI_COMMANDS whitelist"
        for cmd in ("score-relevance", "inject", "handoff"):
            assert f"'{cmd}'" in plugin_content, \
                f"ALLOWED_CLI_COMMANDS should include '{cmd}'"

    def test_plugin_has_exec_cli_function(self, plugin_content):
        """Verify plugin has execCli for legacy CLI delegation."""
        assert "async function execCli" in plugin_content, \
            "Plugin should have execCli function"

    def test_plugin_validates_cli_commands(self, plugin_content):
        """Verify plugin validates CLI commands against the whitelist."""
        assert "ALLOWED_CLI_COMMANDS.has" in plugin_content, \
            "Plugin should validate CLI commands against ALLOWED_CLI_COMMANDS"


# =============================================================================
# Install script
# =============================================================================


class TestInstallScript:
    """Tests for install.sh install_opencode() paths."""

    def test_install_copies_plugin(self):
        """Verify install.sh installs plugin.ts as plugins/lessons.ts."""
        install = (PROJECT_ROOT / "install.sh").read_text()
        assert "adapters/opencode/plugin.ts" in install, \
            "install.sh should copy adapters/opencode/plugin.ts"
        assert "lessons.ts" in install, \
            "install.sh should install the plugin as lessons.ts"

    def test_install_copies_memory_lib(self):
        """Verify install.sh installs lib/memory.ts into plugins/lib/ (a
        subdirectory, so OpenCode's non-recursive plugins/*.ts glob skips it)."""
        install = (PROJECT_ROOT / "install.sh").read_text()
        assert "adapters/opencode/lib/memory.ts" in install, \
            "install.sh should copy adapters/opencode/lib/memory.ts"
        assert 'plugin_dir/lib' in install or "plugins/lib" in install, \
            "install.sh should install memory.ts under plugins/lib/"

    def test_install_copies_commands(self):
        """Verify install.sh installs both native command files."""
        install = (PROJECT_ROOT / "install.sh").read_text()
        assert "adapters/opencode/command/lessons.md" in install, \
            "install.sh should install lessons.md"
        assert "adapters/opencode/command/handoffs.md" in install, \
            "install.sh should install handoffs.md"
