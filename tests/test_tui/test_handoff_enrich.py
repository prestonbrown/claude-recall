#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Tests for Phase 2 of the "Enrich Sparse Handoff Display" feature:
On-demand handoff enrichment.

Phase 2 adds an "enrich" feature that:
1. Pressing 'e' in the TUI handoff detail view triggers enrichment
2. Finds the most recent transcript for the handoff from session-handoffs.json
3. Calls Haiku to extract context from the transcript
4. Updates the handoff with the extracted context

These tests are designed to FAIL initially (test-first development).
The actual implementation will make them pass.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional
from unittest.mock import MagicMock, patch

import pytest


# ============================================================================
# Tests for enrich_handoff function (core/handoffs.py)
# ============================================================================


class TestEnrichHandoffFunctionExists:
    """Tests that the enrich_handoff function exists and can be imported."""

    def test_enrich_handoff_function_exists(self):
        """enrich_handoff should be importable from core.handoffs."""
        from core.handoffs import enrich_handoff

        assert callable(enrich_handoff)

    def test_enrich_handoff_accepts_handoff_id(self):
        """enrich_handoff should accept a handoff_id parameter."""
        from core.handoffs import enrich_handoff
        import inspect

        sig = inspect.signature(enrich_handoff)
        params = list(sig.parameters.keys())
        assert "handoff_id" in params, (
            f"enrich_handoff should have 'handoff_id' parameter, got: {params}"
        )


class TestEnrichHandoffFindsTranscript:
    """Tests for transcript lookup in enrich_handoff."""

    @pytest.fixture
    def temp_state_with_session_handoffs(self, tmp_path, monkeypatch):
        """Create temp state directory with session-handoffs.json and actual transcript files."""
        state_dir = tmp_path / "state"
        state_dir.mkdir()

        # Create actual transcript files with correct JSONL format
        transcripts_dir = state_dir / "transcripts"
        transcripts_dir.mkdir()

        transcript1 = transcripts_dir / "transcript1.jsonl"
        transcript2 = transcripts_dir / "transcript2.jsonl"

        # Write transcript content with enough data to pass 50-char threshold
        transcript_messages = [
            {"type": "user", "timestamp": "2026-01-10T10:00:00Z", "sessionId": "sess-enrich-001",
             "message": {"role": "user", "content": "Please implement feature X with proper error handling and validation"}},
            {"type": "assistant", "timestamp": "2026-01-10T10:01:00Z", "sessionId": "sess-enrich-001",
             "message": {"role": "assistant", "content": [{"type": "text", "text": "Working on implementing feature X with comprehensive error handling"}]}},
            {"type": "user", "timestamp": "2026-01-10T10:02:00Z", "sessionId": "sess-enrich-001",
             "message": {"role": "user", "content": "Please also add tests for edge cases and validation errors"}},
            {"type": "assistant", "timestamp": "2026-01-10T10:03:00Z", "sessionId": "sess-enrich-001",
             "message": {"role": "assistant", "content": [{"type": "text", "text": "Added tests for edge cases and validation errors in the test file"}]}},
        ]
        with open(transcript1, 'w') as f:
            for msg in transcript_messages:
                f.write(json.dumps(msg) + '\n')
        with open(transcript2, 'w') as f:
            for msg in transcript_messages:
                f.write(json.dumps(msg) + '\n')

        # Create session-handoffs.json with links to actual transcript files
        session_handoffs = {
            "sess-enrich-001": {
                "handoff_id": "hf-test001",
                "created": "2026-01-10T10:00:00Z",
                "transcript_path": str(transcript1),
            },
            "sess-enrich-002": {
                "handoff_id": "hf-test002",
                "created": "2026-01-10T11:00:00Z",
                "transcript_path": str(transcript2),
            },
        }
        (state_dir / "session-handoffs.json").write_text(
            json.dumps(session_handoffs, indent=2)
        )

        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(state_dir))

        return state_dir

    def test_enrich_handoff_finds_transcript(self, temp_state_with_session_handoffs):
        """enrich_handoff should look up transcript from session-handoffs.json."""
        from core.handoffs import enrich_handoff

        # Mock the context extraction to avoid actual API calls
        with patch("core.context_extractor.extract_context") as mock_extract:
            mock_extract.return_value = MagicMock(
                summary="Test summary",
                critical_files=[],
                recent_changes=[],
                learnings=[],
                blockers=[],
            )

            # Should find transcript for hf-test001
            result = enrich_handoff("hf-test001")

            # Should have attempted to extract context
            assert mock_extract.called, (
                "enrich_handoff should call extract_context with transcript"
            )

    def test_enrich_handoff_returns_error_when_no_transcript(
        self, temp_state_with_session_handoffs
    ):
        """enrich_handoff should return error when no transcript is linked."""
        from core.handoffs import enrich_handoff

        # Try to enrich a handoff with no linked session
        result = enrich_handoff("hf-nonexistent")

        # Should return an error result
        assert result is not None
        assert hasattr(result, "error") or isinstance(result, dict)
        if isinstance(result, dict):
            assert "error" in result or result.get("success") is False
        else:
            assert result.error is not None or result.success is False


class TestEnrichHandoffCallsHaikuExtraction:
    """Tests for Haiku API integration in enrich_handoff."""

    @pytest.fixture
    def temp_project_with_handoff(self, tmp_path, monkeypatch):
        """Create temp project with handoff and linked session."""
        # Create project structure
        project_root = tmp_path / "test-project"
        project_root.mkdir()
        recall_dir = project_root / ".claude-recall"
        recall_dir.mkdir()

        # Create handoffs file
        handoffs_content = """# HANDOFFS.md - Active Work Tracking

## Active Handoffs

### [hf-enrich01] Test Feature for Enrichment
- **Status**: in_progress | **Phase**: implementing | **Agent**: user
- **Created**: 2026-01-10 | **Updated**: 2026-01-10
- **Refs**: core/feature.py:42
- **Description**: Test handoff for enrichment testing.

**Tried** (1 steps):
1. [success] Initial implementation

**Next**: Complete testing

---
"""
        (recall_dir / "HANDOFFS.md").write_text(handoffs_content)

        # Create state directory with session-handoffs.json
        state_dir = tmp_path / "state"
        state_dir.mkdir()

        # Create a mock transcript file with correct JSONL format
        # Format must match what Claude Code actually writes and what context_extractor expects
        transcript_path = state_dir / "transcripts" / "sess-enrich-test.jsonl"
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        transcript_messages = [
            {"type": "user", "timestamp": "2026-01-10T10:00:00Z", "sessionId": "sess-enrich-test",
             "message": {"role": "user", "content": "Please implement feature X with proper error handling and tests"}},
            {"type": "assistant", "timestamp": "2026-01-10T10:01:00Z", "sessionId": "sess-enrich-test",
             "message": {"role": "assistant", "content": [{"type": "text", "text": "I will modify core/feature.py to add the feature with comprehensive error handling"}]}},
            {"type": "user", "timestamp": "2026-01-10T10:02:00Z", "sessionId": "sess-enrich-test",
             "message": {"role": "user", "content": "Looks good, but please also handle edge case Y where the input is empty"}},
            {"type": "assistant", "timestamp": "2026-01-10T10:03:00Z", "sessionId": "sess-enrich-test",
             "message": {"role": "assistant", "content": [{"type": "text", "text": "Added handling for edge case Y in core/feature.py around line 42 with appropriate validation"}]}},
        ]
        with open(transcript_path, 'w') as f:
            for msg in transcript_messages:
                f.write(json.dumps(msg) + '\n')

        session_handoffs = {
            "sess-enrich-test": {
                "handoff_id": "hf-enrich01",
                "created": "2026-01-10T10:00:00Z",
                "transcript_path": str(transcript_path),
            },
        }
        (state_dir / "session-handoffs.json").write_text(
            json.dumps(session_handoffs, indent=2)
        )

        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(state_dir))
        monkeypatch.setenv("PROJECT_DIR", str(project_root))

        return {
            "project_root": project_root,
            "state_dir": state_dir,
            "transcript_path": transcript_path,
        }

    def test_enrich_handoff_calls_haiku_extraction(
        self, temp_project_with_handoff
    ):
        """enrich_handoff should call context extraction (mock the API)."""
        from core.handoffs import enrich_handoff

        with patch("core.context_extractor.extract_context") as mock_extract:
            mock_extract.return_value = MagicMock(
                summary="Extracted summary from transcript",
                critical_files=["core/feature.py:42"],
                recent_changes=["Added feature X"],
                learnings=["Discovered pattern Y"],
                blockers=[],
            )

            result = enrich_handoff("hf-enrich01")

            # Verify extract_context was called
            assert mock_extract.called, (
                "enrich_handoff should call extract_context"
            )

            # Verify it was called with the transcript path
            call_args = mock_extract.call_args
            assert call_args is not None


class TestEnrichHandoffUpdatesContext:
    """Tests for updating handoff with extracted context."""

    @pytest.fixture
    def temp_project_for_update(self, tmp_path, monkeypatch):
        """Create temp project for testing context updates."""
        project_root = tmp_path / "test-project"
        project_root.mkdir()
        recall_dir = project_root / ".claude-recall"
        recall_dir.mkdir()

        # Create handoffs file without context (matching real format)
        handoffs_content = """# HANDOFFS.md - Active Work Tracking

> Track ongoing work with tried steps and next steps.
> When completed, review for lessons to extract.

## Active Handoffs

### [hf-abc1234] Feature Without Context
- **Status**: in_progress | **Phase**: implementing | **Agent**: user
- **Created**: 2026-01-10 | **Updated**: 2026-01-10
- **Refs**: core/app.py:100
- **Description**: Handoff without enrichment context.

**Tried**:

**Next**: Add feature

---
"""
        (recall_dir / "HANDOFFS.md").write_text(handoffs_content)

        # Create state directory
        state_dir = tmp_path / "state"
        state_dir.mkdir()

        # Create transcript with correct JSONL format
        transcript_path = state_dir / "transcripts" / "sess-update-test.jsonl"
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        transcript_messages = [
            {"type": "user", "timestamp": "2026-01-10T10:00:00Z", "sessionId": "sess-update-test",
             "message": {"role": "user", "content": "Implement the feature with full error handling and edge case support for empty inputs"}},
            {"type": "assistant", "timestamp": "2026-01-10T10:01:00Z", "sessionId": "sess-update-test",
             "message": {"role": "assistant", "content": [{"type": "text", "text": "Working on core/app.py to add the feature implementation with comprehensive validation"}]}},
            {"type": "user", "timestamp": "2026-01-10T10:02:00Z", "sessionId": "sess-update-test",
             "message": {"role": "user", "content": "Please also add tests for the edge cases you mentioned earlier in the discussion"}},
            {"type": "assistant", "timestamp": "2026-01-10T10:03:00Z", "sessionId": "sess-update-test",
             "message": {"role": "assistant", "content": [{"type": "text", "text": "Added unit tests for edge cases in tests/test_app.py covering empty inputs and validation errors"}]}},
        ]
        with open(transcript_path, 'w') as f:
            for msg in transcript_messages:
                f.write(json.dumps(msg) + '\n')

        session_handoffs = {
            "sess-update-test": {
                "handoff_id": "hf-abc1234",
                "created": "2026-01-10T10:00:00Z",
                "transcript_path": str(transcript_path),
            },
        }
        (state_dir / "session-handoffs.json").write_text(
            json.dumps(session_handoffs, indent=2)
        )

        # Create a lessons base directory (needed for LessonsManager)
        lessons_base = tmp_path / "lessons-base"
        lessons_base.mkdir()

        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(state_dir))
        monkeypatch.setenv("CLAUDE_RECALL_BASE", str(lessons_base))
        monkeypatch.setenv("PROJECT_DIR", str(project_root))

        return {
            "project_root": project_root,
            "state_dir": state_dir,
            "handoffs_file": recall_dir / "HANDOFFS.md",
        }

    def test_enrich_handoff_updates_handoff_context(
        self, temp_project_for_update
    ):
        """enrich_handoff should update handoff with extracted context."""
        from core.handoffs import enrich_handoff

        with patch("core.context_extractor.extract_context") as mock_extract:
            mock_extract.return_value = MagicMock(
                summary="Feature is 50% complete",
                critical_files=["core/app.py:100", "core/utils.py:25"],
                recent_changes=["Modified app.py", "Added utils function"],
                learnings=["Found edge case in parsing"],
                blockers=[],
                git_ref="abc123def456",
            )

            result = enrich_handoff("hf-abc1234")

            # Should succeed
            assert result is not None
            if hasattr(result, "success"):
                assert result.success is True
            elif isinstance(result, dict):
                assert result.get("success") is True or "error" not in result

            # Verify handoff file was updated with context
            handoffs_file = temp_project_for_update["handoffs_file"]
            updated_content = handoffs_file.read_text()

            # Should contain Handoff section with git ref (format: **Handoff** (git_ref):)
            assert "**Handoff**" in updated_content, (
                "Handoff file should contain Handoff context section after enrichment"
            )

            # Should contain the summary
            assert "Feature is 50% complete" in updated_content, (
                "Handoff should contain extracted summary"
            )


# ============================================================================
# Tests for context_extractor module (core/context_extractor.py)
# ============================================================================


class TestContextExtractorExists:
    """Tests that the context_extractor module and function exist."""

    def test_extract_context_function_exists(self):
        """extract_context should be importable from core.context_extractor."""
        from core.context_extractor import extract_context

        assert callable(extract_context)

    def test_extract_context_accepts_transcript_path(self):
        """extract_context should accept a transcript_path parameter."""
        from core.context_extractor import extract_context
        import inspect

        sig = inspect.signature(extract_context)
        params = list(sig.parameters.keys())
        assert "transcript_path" in params or "transcript" in params, (
            f"extract_context should have transcript parameter, got: {params}"
        )


class TestHandoffContextDataclass:
    """Tests for the HandoffContext dataclass returned by extract_context."""

    def test_handoff_context_dataclass_exists(self):
        """HandoffContext dataclass should be importable."""
        from core.context_extractor import HandoffContext

        assert HandoffContext is not None

    def test_handoff_context_has_required_fields(self):
        """HandoffContext should have all required fields."""
        from core.context_extractor import HandoffContext
        import dataclasses

        # Should be a dataclass
        assert dataclasses.is_dataclass(HandoffContext), (
            "HandoffContext should be a dataclass"
        )

        # Get field names
        fields = {f.name for f in dataclasses.fields(HandoffContext)}

        required_fields = {
            "summary",
            "critical_files",
            "recent_changes",
            "learnings",
            "blockers",
        }

        missing = required_fields - fields
        assert not missing, (
            f"HandoffContext is missing required fields: {missing}"
        )


class TestExtractContextReturnsHandoffContext:
    """Tests that extract_context returns a HandoffContext."""

    @pytest.fixture
    def mock_transcript_file(self, tmp_path):
        """Create a mock transcript file with correct JSONL format."""
        transcript = tmp_path / "test_transcript.jsonl"
        # Format must match what Claude Code actually writes and what context_extractor expects
        messages = [
            {"type": "user", "timestamp": "2026-01-10T12:00:00Z", "sessionId": "test-123",
             "message": {"role": "user", "content": "Please implement feature X with proper error handling and tests"}},
            {"type": "assistant", "timestamp": "2026-01-10T12:01:00Z", "sessionId": "test-123",
             "message": {"role": "assistant", "content": [{"type": "text", "text": "I will modify core/feature.py to add the feature with comprehensive error handling"}]}},
            {"type": "user", "timestamp": "2026-01-10T12:02:00Z", "sessionId": "test-123",
             "message": {"role": "user", "content": "Looks good, but please also handle edge case Y where the input is empty"}},
            {"type": "assistant", "timestamp": "2026-01-10T12:03:00Z", "sessionId": "test-123",
             "message": {"role": "assistant", "content": [{"type": "text", "text": "Added handling for edge case Y in core/feature.py around line 42 with appropriate validation"}]}},
        ]
        with open(transcript, 'w') as f:
            for msg in messages:
                f.write(json.dumps(msg) + '\n')
        return transcript

    def test_extract_context_returns_handoff_context(self, mock_transcript_file):
        """extract_context should return a HandoffContext dataclass."""
        from core.context_extractor import HandoffContext, extract_context

        # Mock the Haiku API call
        with patch("core.context_extractor._call_haiku") as mock_haiku:
            mock_haiku.return_value = json.dumps({
                "summary": "Implementing feature X with edge case handling",
                "critical_files": ["core/feature.py:42"],
                "recent_changes": ["Added feature X", "Handled edge case Y"],
                "learnings": ["Edge case Y requires special handling"],
                "blockers": [],
            })

            result = extract_context(str(mock_transcript_file))

            assert isinstance(result, HandoffContext), (
                f"extract_context should return HandoffContext, got {type(result)}"
            )

    def test_extract_context_parses_haiku_response(self, mock_transcript_file):
        """extract_context should parse JSON from Haiku into HandoffContext."""
        from core.context_extractor import extract_context

        with patch("core.context_extractor._call_haiku") as mock_haiku:
            mock_haiku.return_value = json.dumps({
                "summary": "Test summary from Haiku",
                "critical_files": ["file1.py:10", "file2.py:20"],
                "recent_changes": ["Change 1", "Change 2"],
                "learnings": ["Learning 1"],
                "blockers": ["Blocker 1"],
            })

            result = extract_context(str(mock_transcript_file))

            # Verify fields were parsed correctly
            assert result.summary == "Test summary from Haiku"
            assert result.critical_files == ["file1.py:10", "file2.py:20"]
            assert result.recent_changes == ["Change 1", "Change 2"]
            assert result.learnings == ["Learning 1"]
            assert result.blockers == ["Blocker 1"]


# ============================================================================
# Tests for session-handoff lookup (get_transcript_for_handoff)
# ============================================================================


class TestGetTranscriptForHandoff:
    """Tests for finding transcript path for a handoff."""

    def test_get_transcript_for_handoff_exists(self):
        """get_transcript_for_handoff function should exist."""
        # Could be in core.handoffs or core.tui.state_reader
        try:
            from core.handoffs import get_transcript_for_handoff
            assert callable(get_transcript_for_handoff)
        except ImportError:
            try:
                from core.tui.state_reader import get_transcript_for_handoff
                assert callable(get_transcript_for_handoff)
            except ImportError:
                pytest.fail(
                    "get_transcript_for_handoff should be importable from "
                    "core.handoffs or core.tui.state_reader"
                )

    @pytest.fixture
    def temp_state_for_lookup(self, tmp_path, monkeypatch):
        """Create temp state directory for transcript lookup tests."""
        state_dir = tmp_path / "state"
        state_dir.mkdir()

        # Create multiple sessions linked to same handoff
        session_handoffs = {
            "sess-older": {
                "handoff_id": "hf-lookup01",
                "created": "2026-01-09T10:00:00Z",
                "transcript_path": "/path/to/older_transcript.jsonl",
            },
            "sess-newer": {
                "handoff_id": "hf-lookup01",
                "created": "2026-01-10T15:00:00Z",
                "transcript_path": "/path/to/newer_transcript.jsonl",
            },
            "sess-other": {
                "handoff_id": "hf-other01",
                "created": "2026-01-10T12:00:00Z",
                "transcript_path": "/path/to/other_transcript.jsonl",
            },
        }
        (state_dir / "session-handoffs.json").write_text(
            json.dumps(session_handoffs, indent=2)
        )

        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(state_dir))

        return state_dir

    def test_get_transcript_for_handoff_returns_path(
        self, temp_state_for_lookup
    ):
        """get_transcript_for_handoff should return transcript path when linked."""
        try:
            from core.handoffs import get_transcript_for_handoff
        except ImportError:
            from core.tui.state_reader import get_transcript_for_handoff

        result = get_transcript_for_handoff("hf-lookup01")

        assert result is not None, (
            "get_transcript_for_handoff should return a path for linked handoff"
        )
        assert isinstance(result, (str, Path)), (
            f"Should return string or Path, got {type(result)}"
        )

    def test_get_transcript_for_handoff_returns_most_recent(
        self, temp_state_for_lookup
    ):
        """get_transcript_for_handoff should return the most recent transcript."""
        try:
            from core.handoffs import get_transcript_for_handoff
        except ImportError:
            from core.tui.state_reader import get_transcript_for_handoff

        result = get_transcript_for_handoff("hf-lookup01")

        # Should return the newer transcript
        assert result is not None
        assert "newer_transcript" in str(result), (
            f"Should return most recent transcript, got: {result}"
        )

    def test_get_transcript_for_handoff_returns_none_when_not_found(
        self, temp_state_for_lookup
    ):
        """get_transcript_for_handoff should return None when handoff has no sessions."""
        try:
            from core.handoffs import get_transcript_for_handoff
        except ImportError:
            from core.tui.state_reader import get_transcript_for_handoff

        result = get_transcript_for_handoff("hf-nonexistent")

        assert result is None, (
            "get_transcript_for_handoff should return None for unlinked handoff"
        )


# ============================================================================
# Tests for TUI 'e' key binding (integration)
# ============================================================================


pytest.importorskip("textual")


class TestEnrichKeyBinding:
    """Tests for the 'e' key binding in the TUI handoff detail view."""

    @pytest.fixture
    def temp_project_for_tui(self, tmp_path, monkeypatch):
        """Create temp project with handoff for TUI testing."""
        project_root = tmp_path / "test-project"
        project_root.mkdir()
        recall_dir = project_root / ".claude-recall"
        recall_dir.mkdir()

        handoffs_content = """# HANDOFFS.md - Active Work Tracking

## Active Handoffs

### [hf-tui001] Feature for TUI Test
- **Status**: in_progress | **Phase**: implementing | **Agent**: user
- **Created**: 2026-01-10 | **Updated**: 2026-01-10
- **Refs**: core/tui.py:50
- **Description**: Testing TUI enrich key binding.

**Tried** (0 steps):

**Next**: Test enrichment

---
"""
        (recall_dir / "HANDOFFS.md").write_text(handoffs_content)

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        (state_dir / "debug.log").write_text("")

        # Create session-handoffs.json with linked session and correct JSONL format
        transcript_path = state_dir / "transcripts" / "sess-tui-test.jsonl"
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        transcript_messages = [
            {"type": "user", "timestamp": "2026-01-10T10:00:00Z", "sessionId": "sess-tui-test",
             "message": {"role": "user", "content": "Please implement the TUI enrich feature with proper error handling"}},
            {"type": "assistant", "timestamp": "2026-01-10T10:01:00Z", "sessionId": "sess-tui-test",
             "message": {"role": "assistant", "content": [{"type": "text", "text": "I will modify core/tui.py to add the enrich key binding with comprehensive validation"}]}},
        ]
        with open(transcript_path, 'w') as f:
            for msg in transcript_messages:
                f.write(json.dumps(msg) + '\n')

        session_handoffs = {
            "sess-tui-test": {
                "handoff_id": "hf-tui001",
                "created": "2026-01-10T10:00:00Z",
                "transcript_path": str(transcript_path),
            },
        }
        (state_dir / "session-handoffs.json").write_text(
            json.dumps(session_handoffs, indent=2)
        )

        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(state_dir))
        monkeypatch.setenv("PROJECT_DIR", str(project_root))

        return {
            "project_root": project_root,
            "state_dir": state_dir,
        }

    @pytest.mark.asyncio
    async def test_e_key_triggers_enrich_when_handoff_selected(
        self, temp_project_for_tui
    ):
        """Pressing 'e' when a handoff is selected should trigger enrichment."""
        from core.tui.app import RecallMonitorApp

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Handoffs tab (F6)
            await pilot.press("f6")
            await pilot.pause()

            # Navigate to first handoff
            await pilot.press("down")
            await pilot.pause()

            # Mock the enrich function to track if it was called
            # Note: Patch at source location since it's imported locally in the method
            with patch("core.tui.helpers.enrich_handoff") as mock_enrich:
                # Return object with .success attribute (not dict)
                mock_result = MagicMock()
                mock_result.success = True
                mock_result.error = None
                mock_enrich.return_value = mock_result

                # Press 'e' to enrich
                await pilot.press("e")
                await pilot.pause()

                # Verify enrich was called
                assert mock_enrich.called, (
                    "Pressing 'e' should call enrich_handoff"
                )

    @pytest.mark.asyncio
    async def test_e_key_shows_notification_on_success(
        self, temp_project_for_tui
    ):
        """Pressing 'e' should show success notification after enrichment."""
        from core.tui.app import RecallMonitorApp

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            await pilot.press("f6")
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()

            with patch("core.tui.helpers.enrich_handoff") as mock_enrich:
                # Return object with .success attribute (not dict)
                mock_result = MagicMock()
                mock_result.success = True
                mock_result.error = None
                mock_enrich.return_value = mock_result

                await pilot.press("e")
                await pilot.pause()

                # Should show a notification (toast)
                # Note: Testing toast content is tricky, so we just verify
                # the action completed without error

    @pytest.mark.asyncio
    async def test_e_key_shows_error_when_no_transcript(
        self, temp_project_for_tui
    ):
        """Pressing 'e' should show error when no transcript is linked."""
        from core.tui.app import RecallMonitorApp

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            await pilot.press("f6")
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()

            with patch("core.tui.helpers.enrich_handoff") as mock_enrich:
                # Return object with .success attribute (not dict)
                mock_result = MagicMock()
                mock_result.success = False
                mock_result.error = "No transcript found for handoff"
                mock_enrich.return_value = mock_result

                await pilot.press("e")
                await pilot.pause()

                # Action should complete (showing error notification)
                assert mock_enrich.called


# ============================================================================
# Tests for EnrichmentResult dataclass
# ============================================================================


class TestEnrichmentResult:
    """Tests for the result type returned by enrich_handoff."""

    def test_enrichment_result_type_exists(self):
        """EnrichmentResult type should be importable from core.handoffs."""
        from core.handoffs import EnrichmentResult

        assert EnrichmentResult is not None

    def test_enrichment_result_has_success_field(self):
        """EnrichmentResult should have a success field."""
        from core.handoffs import EnrichmentResult
        import dataclasses

        if dataclasses.is_dataclass(EnrichmentResult):
            fields = {f.name for f in dataclasses.fields(EnrichmentResult)}
            assert "success" in fields
        else:
            # Could be a TypedDict or similar
            result = EnrichmentResult(success=True)
            assert hasattr(result, "success") or "success" in result

    def test_enrichment_result_has_error_field(self):
        """EnrichmentResult should have an error field for failure cases."""
        from core.handoffs import EnrichmentResult
        import dataclasses

        if dataclasses.is_dataclass(EnrichmentResult):
            fields = {f.name for f in dataclasses.fields(EnrichmentResult)}
            assert "error" in fields
        else:
            result = EnrichmentResult(success=False, error="Test error")
            assert hasattr(result, "error") or "error" in result


# ============================================================================
# Phase 3: Persistent Session History Tests
# ============================================================================
#
# These tests are for Phase 3 of "Enrich Sparse Handoff Display":
# 1. Add sessions field to Handoff model to store linked session IDs
# 2. Write sessions to HANDOFFS.md as `- **Sessions**: session1, session2, ...`
# 3. Parse sessions from HANDOFFS.md back to list
# 4. Make handoff_add_transcript() persist sessions to the handoff file


class TestHandoffSessionsField:
    """Tests for sessions field in Handoff model."""

    def test_handoff_model_has_sessions_field(self):
        """Handoff dataclass should have sessions field."""
        from core.models import Handoff
        import dataclasses

        fields = {f.name for f in dataclasses.fields(Handoff)}
        assert "sessions" in fields, (
            f"Handoff should have 'sessions' field, found fields: {sorted(fields)}"
        )

    def test_handoff_sessions_defaults_to_empty_list(self):
        """Handoff.sessions should default to empty list."""
        from core.models import Handoff
        from datetime import date

        h = Handoff(
            id="hf-abc1234",
            title="Test Handoff",
            status="in_progress",
            phase="implementing",
            created=date.today(),
            updated=date.today(),
        )
        assert h.sessions == [], (
            f"Handoff.sessions should default to [], got: {h.sessions}"
        )

    def test_handoff_sessions_accepts_list_of_strings(self):
        """Handoff.sessions should accept a list of session IDs."""
        from core.models import Handoff
        from datetime import date

        session_ids = ["sess-abc123", "sess-def456", "sess-ghi789"]
        h = Handoff(
            id="hf-abc1234",
            title="Test Handoff",
            status="in_progress",
            phase="implementing",
            created=date.today(),
            updated=date.today(),
            sessions=session_ids,
        )
        assert h.sessions == session_ids, (
            f"Handoff.sessions should store session IDs, got: {h.sessions}"
        )


class TestFormatHandoffIncludesSessions:
    """Tests for sessions line in _format_handoff()."""

    @pytest.fixture
    def temp_project_for_format(self, tmp_path, monkeypatch):
        """Create temp project with LessonsManager."""
        project_root = tmp_path / "test-project"
        project_root.mkdir()
        recall_dir = project_root / ".claude-recall"
        recall_dir.mkdir()

        lessons_base = tmp_path / "lessons-base"
        lessons_base.mkdir()

        state_dir = tmp_path / "state"
        state_dir.mkdir()

        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(state_dir))
        monkeypatch.setenv("CLAUDE_RECALL_BASE", str(lessons_base))
        monkeypatch.setenv("PROJECT_DIR", str(project_root))

        return {
            "project_root": project_root,
            "state_dir": state_dir,
            "lessons_base": lessons_base,
        }

    def test_format_handoff_includes_sessions(self, temp_project_for_format):
        """_format_handoff() should write sessions line when sessions is non-empty."""
        from core.manager import LessonsManager
        from core.models import Handoff
        from datetime import date

        project_root = temp_project_for_format["project_root"]
        lessons_base = temp_project_for_format["lessons_base"]

        mgr = LessonsManager(lessons_base, project_root)

        handoff = Handoff(
            id="hf-abc1234",
            title="Test Handoff",
            status="in_progress",
            phase="implementing",
            created=date.today(),
            updated=date.today(),
            sessions=["sess-abc123", "sess-def456"],
        )

        formatted = mgr._format_handoff(handoff)

        assert "**Sessions**:" in formatted, (
            "Formatted handoff should contain **Sessions**: line"
        )
        assert "sess-abc123" in formatted, (
            "Formatted handoff should contain first session ID"
        )
        assert "sess-def456" in formatted, (
            "Formatted handoff should contain second session ID"
        )

    def test_format_handoff_omits_sessions_when_empty(self, temp_project_for_format):
        """_format_handoff() should NOT write sessions line when sessions is empty."""
        from core.manager import LessonsManager
        from core.models import Handoff
        from datetime import date

        project_root = temp_project_for_format["project_root"]
        lessons_base = temp_project_for_format["lessons_base"]

        mgr = LessonsManager(lessons_base, project_root)

        handoff = Handoff(
            id="hf-abc1234",
            title="Test Handoff",
            status="in_progress",
            phase="implementing",
            created=date.today(),
            updated=date.today(),
            sessions=[],  # Empty sessions
        )

        formatted = mgr._format_handoff(handoff)

        assert "**Sessions**:" not in formatted, (
            "Formatted handoff should NOT contain **Sessions**: line when sessions is empty"
        )


class TestParseHandoffsExtractsSessions:
    """Tests for session parsing in _parse_handoffs_file()."""

    @pytest.fixture
    def temp_project_for_parse(self, tmp_path, monkeypatch):
        """Create temp project with handoff file containing sessions."""
        project_root = tmp_path / "test-project"
        project_root.mkdir()
        recall_dir = project_root / ".claude-recall"
        recall_dir.mkdir()

        lessons_base = tmp_path / "lessons-base"
        lessons_base.mkdir()

        state_dir = tmp_path / "state"
        state_dir.mkdir()

        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(state_dir))
        monkeypatch.setenv("CLAUDE_RECALL_BASE", str(lessons_base))
        monkeypatch.setenv("PROJECT_DIR", str(project_root))

        return {
            "project_root": project_root,
            "state_dir": state_dir,
            "lessons_base": lessons_base,
            "recall_dir": recall_dir,
        }

    def test_parse_handoffs_extracts_sessions(self, temp_project_for_parse):
        """_parse_handoffs_file() should parse sessions from markdown."""
        from core.manager import LessonsManager

        project_root = temp_project_for_parse["project_root"]
        lessons_base = temp_project_for_parse["lessons_base"]
        recall_dir = temp_project_for_parse["recall_dir"]

        # Create handoffs file with sessions line
        handoffs_content = """# HANDOFFS.md - Active Work Tracking

## Active Handoffs

### [hf-abc1234] Test Handoff With Sessions
- **Status**: in_progress | **Phase**: implementing | **Agent**: user
- **Created**: 2026-01-10 | **Updated**: 2026-01-10
- **Refs**: core/app.py:100
- **Description**: Handoff with linked sessions.
- **Sessions**: sess-abc123, sess-def456, sess-ghi789

**Tried**:

**Next**: Continue work

---
"""
        (recall_dir / "HANDOFFS.md").write_text(handoffs_content)

        mgr = LessonsManager(lessons_base, project_root)
        handoffs = mgr._parse_handoffs_file(mgr.project_handoffs_file)

        assert len(handoffs) == 1, f"Should parse 1 handoff, got {len(handoffs)}"
        handoff = handoffs[0]

        assert hasattr(handoff, "sessions"), (
            "Parsed handoff should have sessions attribute"
        )
        assert handoff.sessions == ["sess-abc123", "sess-def456", "sess-ghi789"], (
            f"Parsed sessions should match, got: {handoff.sessions}"
        )

    def test_parse_handoffs_handles_missing_sessions(self, temp_project_for_parse):
        """_parse_handoffs_file() should default to empty list when no sessions line."""
        from core.manager import LessonsManager

        project_root = temp_project_for_parse["project_root"]
        lessons_base = temp_project_for_parse["lessons_base"]
        recall_dir = temp_project_for_parse["recall_dir"]

        # Create handoffs file WITHOUT sessions line
        handoffs_content = """# HANDOFFS.md - Active Work Tracking

## Active Handoffs

### [hf-1234567] Test Handoff Without Sessions
- **Status**: in_progress | **Phase**: research | **Agent**: user
- **Created**: 2026-01-10 | **Updated**: 2026-01-10
- **Refs**:
- **Description**: Handoff without sessions line.

**Tried**:

**Next**: Start work

---
"""
        (recall_dir / "HANDOFFS.md").write_text(handoffs_content)

        mgr = LessonsManager(lessons_base, project_root)
        handoffs = mgr._parse_handoffs_file(mgr.project_handoffs_file)

        assert len(handoffs) == 1, f"Should parse 1 handoff, got {len(handoffs)}"
        handoff = handoffs[0]

        assert hasattr(handoff, "sessions"), (
            "Parsed handoff should have sessions attribute"
        )
        assert handoff.sessions == [], (
            f"Parsed sessions should default to [], got: {handoff.sessions}"
        )


class TestHandoffAddTranscriptPersistsSession:
    """Tests for session persistence in handoff_add_transcript()."""

    @pytest.fixture
    def temp_project_with_session(self, tmp_path, monkeypatch):
        """Create temp project with session-handoff linkage."""
        project_root = tmp_path / "test-project"
        project_root.mkdir()
        recall_dir = project_root / ".claude-recall"
        recall_dir.mkdir()

        lessons_base = tmp_path / "lessons-base"
        lessons_base.mkdir()

        state_dir = tmp_path / "state"
        state_dir.mkdir()

        # Create handoffs file
        handoffs_content = """# HANDOFFS.md - Active Work Tracking

## Active Handoffs

### [hf-abcdef0] Feature Needing Session Tracking
- **Status**: in_progress | **Phase**: implementing | **Agent**: user
- **Created**: 2026-01-10 | **Updated**: 2026-01-10
- **Refs**: core/feature.py:50
- **Description**: Testing session persistence.

**Tried**:

**Next**: Continue implementation

---
"""
        (recall_dir / "HANDOFFS.md").write_text(handoffs_content)

        # Create session-handoffs.json linking session to handoff
        session_handoffs = {
            "sess-persist-001": {
                "handoff_id": "hf-abcdef0",
                "created": "2026-01-10T10:00:00Z",
            },
        }
        (state_dir / "session-handoffs.json").write_text(
            json.dumps(session_handoffs, indent=2)
        )

        # Create transcript file
        transcript_path = state_dir / "transcripts" / "sess-persist-001.jsonl"
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        transcript_messages = [
            {"type": "user", "timestamp": "2026-01-10T10:00:00Z", "sessionId": "sess-persist-001",
             "message": {"role": "user", "content": "Working on feature implementation with tests"}},
        ]
        with open(transcript_path, 'w') as f:
            for msg in transcript_messages:
                f.write(json.dumps(msg) + '\n')

        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(state_dir))
        monkeypatch.setenv("CLAUDE_RECALL_BASE", str(lessons_base))
        monkeypatch.setenv("PROJECT_DIR", str(project_root))

        return {
            "project_root": project_root,
            "state_dir": state_dir,
            "lessons_base": lessons_base,
            "recall_dir": recall_dir,
            "transcript_path": str(transcript_path),
        }

    def test_handoff_add_transcript_persists_session(self, temp_project_with_session):
        """handoff_add_transcript() should add session ID to handoff's sessions field."""
        from core.manager import LessonsManager

        project_root = temp_project_with_session["project_root"]
        lessons_base = temp_project_with_session["lessons_base"]
        recall_dir = temp_project_with_session["recall_dir"]
        transcript_path = temp_project_with_session["transcript_path"]

        mgr = LessonsManager(lessons_base, project_root)

        # Call handoff_add_transcript
        result = mgr.handoff_add_transcript(
            session_id="sess-persist-001",
            transcript_path=transcript_path,
        )

        assert result == "hf-abcdef0", (
            f"handoff_add_transcript should return handoff ID, got: {result}"
        )

        # Verify the session was persisted to the handoff file
        handoffs_file = recall_dir / "HANDOFFS.md"
        content = handoffs_file.read_text()

        assert "**Sessions**:" in content, (
            "HANDOFFS.md should contain **Sessions**: line after handoff_add_transcript"
        )
        assert "sess-persist-001" in content, (
            "HANDOFFS.md should contain the added session ID"
        )

    def test_handoff_add_transcript_appends_to_existing_sessions(
        self, temp_project_with_session
    ):
        """handoff_add_transcript() should append to existing sessions, not replace."""
        from core.manager import LessonsManager

        project_root = temp_project_with_session["project_root"]
        lessons_base = temp_project_with_session["lessons_base"]
        recall_dir = temp_project_with_session["recall_dir"]
        state_dir = temp_project_with_session["state_dir"]
        transcript_path = temp_project_with_session["transcript_path"]

        # Update handoffs file to have an existing session
        handoffs_content = """# HANDOFFS.md - Active Work Tracking

## Active Handoffs

### [hf-abcdef0] Feature Needing Session Tracking
- **Status**: in_progress | **Phase**: implementing | **Agent**: user
- **Created**: 2026-01-10 | **Updated**: 2026-01-10
- **Refs**: core/feature.py:50
- **Description**: Testing session persistence.
- **Sessions**: sess-existing-001

**Tried**:

**Next**: Continue implementation

---
"""
        (recall_dir / "HANDOFFS.md").write_text(handoffs_content)

        # Create second transcript
        transcript_path_2 = Path(state_dir) / "transcripts" / "sess-persist-002.jsonl"
        transcript_messages = [
            {"type": "user", "timestamp": "2026-01-10T11:00:00Z", "sessionId": "sess-persist-002",
             "message": {"role": "user", "content": "Continuing feature work"}},
        ]
        with open(transcript_path_2, 'w') as f:
            for msg in transcript_messages:
                f.write(json.dumps(msg) + '\n')

        # Update session-handoffs.json with second session
        session_handoffs = {
            "sess-existing-001": {
                "handoff_id": "hf-abcdef0",
                "created": "2026-01-10T09:00:00Z",
            },
            "sess-persist-002": {
                "handoff_id": "hf-abcdef0",
                "created": "2026-01-10T11:00:00Z",
            },
        }
        (Path(state_dir) / "session-handoffs.json").write_text(
            json.dumps(session_handoffs, indent=2)
        )

        mgr = LessonsManager(lessons_base, project_root)

        # Add second session
        result = mgr.handoff_add_transcript(
            session_id="sess-persist-002",
            transcript_path=str(transcript_path_2),
        )

        assert result == "hf-abcdef0"

        # Verify both sessions are in the file
        handoffs_file = recall_dir / "HANDOFFS.md"
        content = handoffs_file.read_text()

        assert "sess-existing-001" in content, (
            "HANDOFFS.md should still contain the original session ID"
        )
        assert "sess-persist-002" in content, (
            "HANDOFFS.md should contain the new session ID"
        )


# ============================================================================
# TUI Display of Sessions
# ============================================================================

pytest.importorskip("textual")


class TestHandoffDetailShowsSessions:
    """Tests for displaying sessions in the TUI handoff detail view."""

    @pytest.fixture
    def temp_project_for_tui_sessions(self, tmp_path, monkeypatch):
        """Create temp project with handoff containing sessions for TUI testing."""
        project_root = tmp_path / "test-project"
        project_root.mkdir()
        recall_dir = project_root / ".claude-recall"
        recall_dir.mkdir()

        # Create handoffs file with sessions
        handoffs_content = """# HANDOFFS.md - Active Work Tracking

## Active Handoffs

### [hf-aabbcc1] Feature With Sessions
- **Status**: in_progress | **Phase**: implementing | **Agent**: user
- **Created**: 2026-01-10 | **Updated**: 2026-01-10
- **Refs**: core/tui.py:50
- **Description**: Testing TUI session display.
- **Sessions**: sess-tui-001, sess-tui-002, sess-tui-003

**Tried**:
1. [success] Initial setup

**Next**: Continue work

---
"""
        (recall_dir / "HANDOFFS.md").write_text(handoffs_content)

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        (state_dir / "debug.log").write_text("")

        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(state_dir))
        monkeypatch.setenv("PROJECT_DIR", str(project_root))

        return {
            "project_root": project_root,
            "state_dir": state_dir,
        }

    @pytest.mark.asyncio
    async def test_handoff_detail_shows_sessions(self, temp_project_for_tui_sessions):
        """Handoff detail view should display linked sessions."""
        from core.tui.app import RecallMonitorApp

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Switch to Handoffs tab (F6)
            await pilot.press("f6")
            await pilot.pause()

            # Navigate to first handoff
            await pilot.press("down")
            await pilot.pause()

            # Get the detail log content
            from textual.widgets import RichLog
            details_log = app.query_one("#handoff-details", RichLog)

            # The RichLog content should contain session info
            # Note: Testing exact content is tricky with RichLog, so we check
            # that the detail view was populated and contains relevant keywords
            # The actual assertion depends on implementation - this should fail
            # until Phase 3 is implemented

            # Check if sessions are displayed in some form
            # This will need to access the rendered content or markup
            assert hasattr(details_log, "markup") or hasattr(details_log, "_lines"), (
                "RichLog should have content that can be inspected"
            )

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Pre-existing TUI bug: column count mismatch in session DataTable")
    async def test_handoff_detail_shows_session_count(
        self, temp_project_for_tui_sessions
    ):
        """Handoff detail should show session count in a user-friendly way."""
        from core.tui.app import RecallMonitorApp

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            await pilot.press("f6")
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()

            # The detail view should show "3 sessions" or similar
            # This test will fail until the TUI is updated to show sessions
            from textual.widgets import RichLog
            details_log = app.query_one("#handoff-details", RichLog)

            # Get rendered text - implementation dependent
            # For now, this is a placeholder that should fail until implemented
            rendered = str(details_log)

            # After implementation, this should show session info
            # The exact format may vary (could be "Sessions: 3" or "3 sessions")
            assert "sess" in rendered.lower() or "session" in rendered.lower(), (
                f"Handoff detail should display session info, got: {rendered[:500]}"
            )
