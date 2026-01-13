#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Tests for context extraction from Claude Code transcripts.

These tests verify that context extraction handles tool-heavy conversations
correctly, extracting meaningful content from tool_use blocks, thinking blocks,
and text blocks - not just text blocks alone.

Tests are written TEST-FIRST and should FAIL until the bug is fixed.
"""

import json
import tempfile
from pathlib import Path

import pytest


class TestReadTranscriptMessages:
    """Tests for _read_transcript_messages function."""

    def test_extracts_user_messages(self, tmp_path: Path):
        """Should extract user message content."""
        from core.context_extractor import _read_transcript_messages

        transcript = tmp_path / "test.jsonl"
        transcript.write_text(
            '{"type": "user", "message": {"content": "Hello world"}}\n'
            '{"type": "user", "message": {"content": "How are you?"}}\n'
        )

        result = _read_transcript_messages(transcript)

        assert "User: Hello world" in result
        assert "User: How are you?" in result

    def test_extracts_text_blocks_from_assistant(self, tmp_path: Path):
        """Should extract text blocks from assistant messages."""
        from core.context_extractor import _read_transcript_messages

        transcript = tmp_path / "test.jsonl"
        transcript.write_text(json.dumps({
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": "Here is my response"}
                ]
            }
        }) + "\n")

        result = _read_transcript_messages(transcript)

        assert "Assistant: Here is my response" in result

    def test_extracts_tool_use_blocks(self, tmp_path: Path):
        """FAILING TEST: Should extract tool_use blocks from assistant messages.

        Currently the code only extracts type=="text" blocks, missing tool_use entirely.
        This causes tool-heavy sessions to produce empty assistant content.
        """
        from core.context_extractor import _read_transcript_messages

        transcript = tmp_path / "test.jsonl"
        transcript.write_text(json.dumps({
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Read",
                        "input": {"file_path": "/path/to/file.py"}
                    },
                    {
                        "type": "tool_use",
                        "name": "Edit",
                        "input": {"file_path": "/path/to/file.py", "old_string": "foo", "new_string": "bar"}
                    }
                ]
            }
        }) + "\n")

        result = _read_transcript_messages(transcript)

        # Should mention the tool use, not be empty
        assert "Read" in result or "tool" in result.lower(), (
            f"Tool use should be extracted. Got: {result!r}"
        )

    def test_extracts_thinking_blocks(self, tmp_path: Path):
        """FAILING TEST: Should extract thinking blocks from assistant messages.

        Thinking blocks contain valuable context about reasoning that helps
        understand what was being worked on.
        """
        from core.context_extractor import _read_transcript_messages

        transcript = tmp_path / "test.jsonl"
        transcript.write_text(json.dumps({
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "thinking",
                        "thinking": "I need to fix the bug in the authentication flow"
                    },
                    {
                        "type": "text",
                        "text": "Let me fix that."
                    }
                ]
            }
        }) + "\n")

        result = _read_transcript_messages(transcript)

        # Should include thinking content
        assert "authentication" in result.lower() or "thinking" in result.lower(), (
            f"Thinking blocks should be extracted. Got: {result!r}"
        )

    def test_tool_heavy_conversation_not_empty(self, tmp_path: Path):
        """FAILING TEST: Tool-heavy conversations should produce meaningful output.

        This is the real-world scenario that causes the bug: a session with
        mostly tool calls and minimal text produces empty assistant content,
        leading Haiku to say "No conversation occurred".
        """
        from core.context_extractor import _read_transcript_messages

        transcript = tmp_path / "test.jsonl"
        lines = [
            # User asks to commit
            json.dumps({
                "type": "user",
                "message": {"content": "commit that"}
            }),
            # Assistant does git commands - NO text blocks, only tool_use
            json.dumps({
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "tool_use", "name": "Bash", "input": {"command": "git status"}},
                    ]
                }
            }),
            # Tool result
            json.dumps({
                "type": "tool_result",
                "content": "On branch main..."
            }),
            # More tool use
            json.dumps({
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "tool_use", "name": "Bash", "input": {"command": "git add ."}},
                        {"type": "tool_use", "name": "Bash", "input": {"command": "git commit -m 'fix'"}},
                    ]
                }
            }),
            # User asks about handoff
            json.dumps({
                "type": "user",
                "message": {"content": "looks like we started a handoff"}
            }),
            # Assistant responds with more tools
            json.dumps({
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "tool_use", "name": "Bash", "input": {"command": "python cli.py handoff show"}},
                    ]
                }
            }),
        ]
        transcript.write_text("\n".join(lines) + "\n")

        result = _read_transcript_messages(transcript)

        # Should have SOME assistant content, not just user messages
        assistant_lines = [l for l in result.split("\n") if l.startswith("Assistant:")]
        non_empty_assistant = [l for l in assistant_lines if l.strip() != "Assistant:"]

        assert len(non_empty_assistant) > 0, (
            f"Tool-heavy conversation should have non-empty assistant content. "
            f"Got {len(assistant_lines)} assistant lines, {len(non_empty_assistant)} non-empty. "
            f"Full result:\n{result}"
        )


class TestGarbageSummaryRejection:
    """Tests for rejecting garbage summaries from Haiku."""

    def test_rejects_no_conversation_summary(self):
        """FAILING TEST: Should reject summaries that say 'no conversation occurred'.

        When Haiku receives empty content, it produces garbage like:
        "No conversation occurred - user only requested handoff context analysis..."

        This should be detected and rejected, not stored.
        """
        # This test requires a validation function that doesn't exist yet
        try:
            from core.context_extractor import _validate_summary
        except ImportError:
            pytest.skip("_validate_summary not yet implemented")

        garbage_summaries = [
            "No conversation occurred",
            "No conversation occurred - user only requested handoff context analysis",
            "The conversation is empty",
            "There is no content to summarize",
            "Empty session with no work completed",
        ]

        for summary in garbage_summaries:
            assert not _validate_summary(summary), (
                f"Should reject garbage summary: {summary!r}"
            )

    def test_accepts_valid_summary(self):
        """Should accept summaries that reference actual work."""
        try:
            from core.context_extractor import _validate_summary
        except ImportError:
            pytest.skip("_validate_summary not yet implemented")

        valid_summaries = [
            "Fixed bug in authentication flow by updating token refresh logic",
            "Implemented new API endpoint for user registration",
            "Refactored database connection pooling for better performance",
        ]

        for summary in valid_summaries:
            assert _validate_summary(summary), (
                f"Should accept valid summary: {summary!r}"
            )


class TestExtractContextIntegration:
    """Integration tests for the full extract_context flow."""

    def test_extract_context_with_tool_heavy_transcript(self, tmp_path: Path, monkeypatch):
        """FAILING TEST: Full extraction should work for tool-heavy transcripts.

        This test creates a realistic tool-heavy transcript and verifies
        the full extraction pipeline produces meaningful context.
        """
        from core.context_extractor import extract_context

        # Create a tool-heavy transcript
        transcript = tmp_path / "test.jsonl"
        lines = [
            json.dumps({
                "type": "user",
                "message": {"content": "Fix the bug in core/auth.py"}
            }),
            json.dumps({
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "text", "text": "I'll fix that bug."},
                        {"type": "tool_use", "name": "Read", "input": {"file_path": "core/auth.py"}},
                    ]
                }
            }),
            json.dumps({
                "type": "tool_result",
                "content": "def authenticate(): pass"
            }),
            json.dumps({
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "tool_use", "name": "Edit", "input": {
                            "file_path": "core/auth.py",
                            "old_string": "pass",
                            "new_string": "return True"
                        }},
                    ]
                }
            }),
            json.dumps({
                "type": "user",
                "message": {"content": "Great, now run the tests"}
            }),
            json.dumps({
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "tool_use", "name": "Bash", "input": {"command": "pytest tests/"}},
                    ]
                }
            }),
        ]
        transcript.write_text("\n".join(lines) + "\n")

        # Mock Haiku call to avoid actual API call
        def mock_call_haiku(prompt):
            # Verify prompt contains meaningful content
            if "auth" in prompt.lower() or "Read" in prompt or "Edit" in prompt:
                return json.dumps({
                    "summary": "Fixed bug in core/auth.py authentication function",
                    "critical_files": ["core/auth.py"],
                    "recent_changes": ["Fixed authenticate function"],
                    "learnings": [],
                    "blockers": []
                })
            else:
                # If prompt is empty/garbage, return garbage (simulating real bug)
                return json.dumps({
                    "summary": "No conversation occurred",
                    "critical_files": [],
                    "recent_changes": [],
                    "learnings": [],
                    "blockers": []
                })

        monkeypatch.setattr("core.context_extractor._call_haiku", mock_call_haiku)

        result = extract_context(transcript)

        # Should produce valid context, not garbage
        assert result is not None, "Should return context for valid transcript"
        assert "auth" in result.summary.lower(), (
            f"Summary should reference the actual work. Got: {result.summary!r}"
        )


class TestExtractContextCLI:
    """Tests for the extract-context CLI command."""

    def test_cli_extract_context_outputs_json(self, tmp_path: Path, monkeypatch):
        """CLI extract-context should output valid JSON."""
        import subprocess
        import os

        # Create a simple transcript
        transcript = tmp_path / "test.jsonl"
        lines = [
            json.dumps({
                "type": "user",
                "message": {"content": "Fix the bug in auth.py"}
            }),
            json.dumps({
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "text", "text": "I'll fix the authentication bug."},
                        {"type": "tool_use", "name": "Read", "input": {"file_path": "auth.py"}},
                    ]
                }
            }),
        ]
        transcript.write_text("\n".join(lines) + "\n")

        # Mock the Haiku call via environment/monkeypatch
        def mock_call_haiku(prompt):
            return json.dumps({
                "summary": "Fixed authentication bug in auth.py",
                "critical_files": ["auth.py"],
                "recent_changes": ["Fixed auth function"],
                "learnings": [],
                "blockers": []
            })

        monkeypatch.setattr("core.context_extractor._call_haiku", mock_call_haiku)

        # Run CLI
        from core.cli import main
        import sys
        from io import StringIO

        # Capture stdout
        old_stdout = sys.stdout
        sys.stdout = StringIO()
        old_argv = sys.argv

        try:
            sys.argv = ["cli.py", "extract-context", str(transcript), "--git-ref", "abc1234"]
            main()
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout
            sys.argv = old_argv

        # Parse output as JSON
        result = json.loads(output)
        assert "summary" in result
        assert "auth" in result["summary"].lower()
        assert result["git_ref"] == "abc1234"
        assert "critical_files" in result
        assert "recent_changes" in result

    def test_cli_extract_context_returns_empty_on_failure(self, tmp_path: Path, monkeypatch):
        """CLI extract-context should return {} when extraction fails."""
        # Create a transcript that's too short to extract
        transcript = tmp_path / "test.jsonl"
        transcript.write_text('{"type": "user", "message": {"content": "hi"}}\n')

        from core.cli import main
        import sys
        from io import StringIO

        old_stdout = sys.stdout
        sys.stdout = StringIO()
        old_argv = sys.argv

        try:
            sys.argv = ["cli.py", "extract-context", str(transcript)]
            try:
                main()
            except SystemExit as e:
                # CLI exits with 0 for empty result
                assert e.code == 0
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout
            sys.argv = old_argv

        # Should return empty object
        result = json.loads(output)
        assert result == {}


class TestLightweightContextExtraction:
    """Tests for extract_lightweight_context function (no LLM)."""

    def test_extracts_tool_counts(self, tmp_path: Path):
        """Should count tool usage by type."""
        from core.context_extractor import extract_lightweight_context

        transcript = tmp_path / "test.jsonl"
        transcript.write_text(
            json.dumps({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Read", "input": {"file_path": "/a.py"}},
                {"type": "tool_use", "name": "Read", "input": {"file_path": "/b.py"}},
                {"type": "tool_use", "name": "Edit", "input": {"file_path": "/a.py"}},
            ]}}) + "\n"
        )

        result = extract_lightweight_context(transcript)

        assert result is not None
        assert result.tool_counts.get("Read") == 2
        assert result.tool_counts.get("Edit") == 1

    def test_extracts_files_touched(self, tmp_path: Path):
        """Should extract unique files from Read/Edit/Write tools."""
        from core.context_extractor import extract_lightweight_context

        transcript = tmp_path / "test.jsonl"
        transcript.write_text(
            json.dumps({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Read", "input": {"file_path": "/path/to/foo.py"}},
                {"type": "tool_use", "name": "Read", "input": {"file_path": "/path/to/bar.py"}},
                {"type": "tool_use", "name": "Edit", "input": {"file_path": "/path/to/foo.py"}},
            ]}}) + "\n"
        )

        result = extract_lightweight_context(transcript)

        assert result is not None
        assert "foo.py" in result.files_touched
        assert "bar.py" in result.files_touched
        assert "foo.py" in result.files_modified
        assert "bar.py" not in result.files_modified

    def test_extracts_last_user_message(self, tmp_path: Path):
        """Should capture the last user message."""
        from core.context_extractor import extract_lightweight_context

        transcript = tmp_path / "test.jsonl"
        transcript.write_text(
            '{"type": "user", "message": {"content": "First message"}}\n'
            '{"type": "user", "message": {"content": "Last message"}}\n'
        )

        result = extract_lightweight_context(transcript)

        assert result is not None
        assert result.last_user_message == "Last message"

    def test_counts_messages(self, tmp_path: Path):
        """Should count total messages in transcript."""
        from core.context_extractor import extract_lightweight_context

        transcript = tmp_path / "test.jsonl"
        transcript.write_text(
            '{"type": "user", "message": {"content": "Hello"}}\n'
            '{"type": "assistant", "message": {"content": "Hi there"}}\n'
            '{"type": "user", "message": {"content": "Thanks"}}\n'
        )

        result = extract_lightweight_context(transcript)

        assert result is not None
        assert result.message_count == 3

    def test_truncates_long_user_message(self, tmp_path: Path):
        """Should truncate long user messages to 100 chars."""
        from core.context_extractor import extract_lightweight_context

        long_message = "x" * 200
        transcript = tmp_path / "test.jsonl"
        transcript.write_text(
            json.dumps({"type": "user", "message": {"content": long_message}}) + "\n"
        )

        result = extract_lightweight_context(transcript)

        assert result is not None
        assert len(result.last_user_message) == 103  # 100 + "..."
        assert result.last_user_message.endswith("...")

    def test_returns_none_for_missing_file(self):
        """Should return None for non-existent transcript."""
        from core.context_extractor import extract_lightweight_context

        result = extract_lightweight_context("/nonexistent/path.jsonl")

        assert result is None

    def test_returns_none_for_empty_transcript(self, tmp_path: Path):
        """Should return valid context even for empty/minimal transcript."""
        from core.context_extractor import extract_lightweight_context

        transcript = tmp_path / "empty.jsonl"
        transcript.write_text("")

        result = extract_lightweight_context(transcript)

        # Empty file should return a LightweightContext with zero counts
        assert result is not None
        assert result.message_count == 0
        assert result.files_touched == []
        assert result.tool_counts == {}

    def test_handles_malformed_json_gracefully(self, tmp_path: Path):
        """Should skip malformed JSON lines without crashing."""
        from core.context_extractor import extract_lightweight_context

        transcript = tmp_path / "malformed.jsonl"
        transcript.write_text(
            'not valid json\n'
            '{"type": "user", "message": {"content": "Valid message"}}\n'
            '{broken\n'
        )

        result = extract_lightweight_context(transcript)

        assert result is not None
        assert result.message_count == 1
        assert result.last_user_message == "Valid message"
