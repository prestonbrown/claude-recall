#!/usr/bin/env python3
"""Tests for transcript_reader module - reads Claude session transcripts."""

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest


# Sample transcript data matching Claude's actual format
SAMPLE_USER_MESSAGE = {
    "type": "user",
    "uuid": "msg-user-001",
    "parentUuid": None,
    "timestamp": "2026-01-07T10:15:23.000Z",
    "sessionId": "eb3513a8-77ea-41c9-94fd-e8cdf700a4dd",
    "cwd": "/Users/test/code/myproject",
    "message": {
        "role": "user",
        "content": "Help me fix the session panel display in the TUI. It's not showing sessions properly."
    },
    "userType": "external"
}

SAMPLE_ASSISTANT_MESSAGE_WITH_TOOLS = {
    "type": "assistant",
    "uuid": "msg-asst-001",
    "parentUuid": "msg-user-001",
    "timestamp": "2026-01-07T10:15:25.000Z",
    "sessionId": "eb3513a8-77ea-41c9-94fd-e8cdf700a4dd",
    "message": {
        "role": "assistant",
        "id": "msg_01ABC123",
        "model": "claude-opus-4-5-20251101",
        "stop_reason": "tool_use",
        "usage": {
            "input_tokens": 1500,
            "output_tokens": 250,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 1000
        },
        "content": [
            {"type": "text", "text": "Let me look at the TUI code."},
            {
                "type": "tool_use",
                "id": "toolu_001",
                "name": "Read",
                "input": {"file_path": "/Users/test/code/myproject/core/tui/app.py"}
            }
        ]
    }
}

SAMPLE_ASSISTANT_MESSAGE_TEXT_ONLY = {
    "type": "assistant",
    "uuid": "msg-asst-002",
    "parentUuid": "msg-asst-001",
    "timestamp": "2026-01-07T10:15:30.000Z",
    "sessionId": "eb3513a8-77ea-41c9-94fd-e8cdf700a4dd",
    "message": {
        "role": "assistant",
        "id": "msg_01ABC124",
        "model": "claude-opus-4-5-20251101",
        "stop_reason": "end_turn",
        "usage": {
            "input_tokens": 2000,
            "output_tokens": 100,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 1500
        },
        "content": [
            {"type": "text", "text": "I found the issue. The session tab is reading from the wrong source."}
        ]
    }
}

SAMPLE_FILE_HISTORY = {
    "type": "file-history-snapshot",
    "timestamp": "2026-01-07T10:15:20.000Z",
    "sessionId": "eb3513a8-77ea-41c9-94fd-e8cdf700a4dd"
}


@pytest.fixture
def temp_claude_home(tmp_path):
    """Create a temporary ~/.claude structure with sample transcripts."""
    claude_home = tmp_path / ".claude"
    projects_dir = claude_home / "projects"

    # Create project directory with URL-encoded path
    # /Users/test/code/myproject -> -Users-test-code-myproject
    project_dir = projects_dir / "-Users-test-code-myproject"
    project_dir.mkdir(parents=True)

    # Create a sample transcript
    transcript_path = project_dir / "eb3513a8-77ea-41c9-94fd-e8cdf700a4dd.jsonl"
    with open(transcript_path, "w") as f:
        f.write(json.dumps(SAMPLE_FILE_HISTORY) + "\n")
        f.write(json.dumps(SAMPLE_USER_MESSAGE) + "\n")
        f.write(json.dumps(SAMPLE_ASSISTANT_MESSAGE_WITH_TOOLS) + "\n")
        f.write(json.dumps(SAMPLE_ASSISTANT_MESSAGE_TEXT_ONLY) + "\n")

    # Create another transcript (older)
    older_transcript = project_dir / "older-session-id.jsonl"
    older_msg = SAMPLE_USER_MESSAGE.copy()
    older_msg["timestamp"] = "2026-01-06T09:00:00.000Z"
    older_msg["message"] = {"role": "user", "content": "This is an older session about something else."}
    with open(older_transcript, "w") as f:
        f.write(json.dumps(older_msg) + "\n")

    # Create a second project
    project2_dir = projects_dir / "-Users-test-code-other-project"
    project2_dir.mkdir(parents=True)

    transcript2 = project2_dir / "other-session.jsonl"
    other_msg = SAMPLE_USER_MESSAGE.copy()
    other_msg["sessionId"] = "other-session"
    other_msg["message"] = {"role": "user", "content": "Working on a different project."}
    with open(transcript2, "w") as f:
        f.write(json.dumps(other_msg) + "\n")

    return claude_home


class TestTranscriptReaderImport:
    """Test that transcript_reader module exists and is importable."""

    def test_module_importable(self):
        """TranscriptReader should be importable from core.tui."""
        from core.tui.transcript_reader import TranscriptReader
        assert TranscriptReader is not None

    def test_dataclasses_importable(self):
        """TranscriptMessage and TranscriptSummary should be importable."""
        from core.tui.transcript_reader import TranscriptMessage, TranscriptSummary
        assert TranscriptMessage is not None
        assert TranscriptSummary is not None


class TestProjectPathEncoding:
    """Test URL-encoding of project paths to match Claude's directory naming."""

    def test_encode_simple_path(self, temp_claude_home):
        """Simple path should be encoded with leading dash and slashes replaced."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home)
        encoded = reader.encode_project_path("/Users/test/code/myproject")
        assert encoded == "-Users-test-code-myproject"

    def test_encode_path_with_dots(self, temp_claude_home):
        """Path with dots should encode dots as dashes."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home)
        # Claude encodes .local as --local (double dash for dot)
        encoded = reader.encode_project_path("/Users/test/.local/state")
        assert encoded == "-Users-test--local-state"

    def test_get_project_dir(self, temp_claude_home):
        """get_project_dir should return correct path for project."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home)
        project_dir = reader.get_project_dir("/Users/test/code/myproject")

        assert project_dir.exists()
        assert project_dir.name == "-Users-test-code-myproject"


class TestListSessions:
    """Test listing sessions from a project directory."""

    def test_list_sessions_returns_summaries(self, temp_claude_home):
        """list_sessions should return TranscriptSummary objects."""
        from core.tui.transcript_reader import TranscriptReader, TranscriptSummary

        reader = TranscriptReader(claude_home=temp_claude_home)
        sessions = reader.list_sessions("/Users/test/code/myproject")

        assert len(sessions) == 2
        assert all(isinstance(s, TranscriptSummary) for s in sessions)

    def test_list_sessions_sorted_by_time(self, temp_claude_home):
        """Sessions should be sorted by most recent first."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home)
        sessions = reader.list_sessions("/Users/test/code/myproject")

        # First session should be the more recent one
        assert sessions[0].session_id == "eb3513a8-77ea-41c9-94fd-e8cdf700a4dd"
        assert sessions[1].session_id == "older-session-id"

    def test_list_sessions_respects_limit(self, temp_claude_home):
        """list_sessions should respect the limit parameter."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home)
        sessions = reader.list_sessions("/Users/test/code/myproject", limit=1)

        assert len(sessions) == 1

    def test_list_sessions_extracts_first_prompt(self, temp_claude_home):
        """Each session should have first_prompt populated."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home)
        sessions = reader.list_sessions("/Users/test/code/myproject")

        # Find the session with the known prompt
        session = next(s for s in sessions if s.session_id == "eb3513a8-77ea-41c9-94fd-e8cdf700a4dd")
        assert "session panel" in session.first_prompt.lower()

    def test_list_sessions_counts_tools(self, temp_claude_home):
        """Session summary should include tool breakdown."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home)
        sessions = reader.list_sessions("/Users/test/code/myproject")

        session = next(s for s in sessions if s.session_id == "eb3513a8-77ea-41c9-94fd-e8cdf700a4dd")
        assert "Read" in session.tool_breakdown
        assert session.tool_breakdown["Read"] == 1

    def test_list_sessions_nonexistent_project(self, temp_claude_home):
        """Nonexistent project should return empty list."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home)
        sessions = reader.list_sessions("/nonexistent/project")

        assert sessions == []


class TestListAllSessions:
    """Test listing sessions from all projects."""

    def test_list_all_sessions(self, temp_claude_home):
        """list_all_sessions should return sessions from all projects."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home)
        sessions = reader.list_all_sessions()

        # Should have sessions from both projects
        assert len(sessions) == 3

    def test_list_all_sessions_sorted_by_time(self, temp_claude_home):
        """All sessions should be sorted by most recent first."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home)
        sessions = reader.list_all_sessions()

        # Should be in descending time order
        times = [s.last_activity for s in sessions]
        assert times == sorted(times, reverse=True)

    def test_list_all_sessions_includes_project(self, temp_claude_home):
        """Each session should have project field populated."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home)
        sessions = reader.list_all_sessions()

        projects = {s.project for s in sessions}
        assert "myproject" in projects or "-Users-test-code-myproject" in projects


class TestLoadSession:
    """Test loading full session transcript."""

    def test_load_session_returns_messages(self, temp_claude_home):
        """load_session should return list of TranscriptMessage."""
        from core.tui.transcript_reader import TranscriptReader, TranscriptMessage

        reader = TranscriptReader(claude_home=temp_claude_home)
        project_dir = reader.get_project_dir("/Users/test/code/myproject")
        session_path = project_dir / "eb3513a8-77ea-41c9-94fd-e8cdf700a4dd.jsonl"

        messages = reader.load_session(session_path)

        assert len(messages) >= 2  # At least user + assistant
        assert all(isinstance(m, TranscriptMessage) for m in messages)

    def test_load_session_includes_user_messages(self, temp_claude_home):
        """User messages should be parsed with content."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home)
        project_dir = reader.get_project_dir("/Users/test/code/myproject")
        session_path = project_dir / "eb3513a8-77ea-41c9-94fd-e8cdf700a4dd.jsonl"

        messages = reader.load_session(session_path)
        user_msgs = [m for m in messages if m.type == "user"]

        assert len(user_msgs) >= 1
        assert "session panel" in user_msgs[0].content.lower()

    def test_load_session_includes_tool_usage(self, temp_claude_home):
        """Assistant messages should have tools_used populated."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home)
        project_dir = reader.get_project_dir("/Users/test/code/myproject")
        session_path = project_dir / "eb3513a8-77ea-41c9-94fd-e8cdf700a4dd.jsonl"

        messages = reader.load_session(session_path)
        tool_msgs = [m for m in messages if m.tools_used]

        assert len(tool_msgs) >= 1
        assert "Read" in tool_msgs[0].tools_used

    def test_load_session_skips_file_history(self, temp_claude_home):
        """file-history-snapshot messages should be skipped."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home)
        project_dir = reader.get_project_dir("/Users/test/code/myproject")
        session_path = project_dir / "eb3513a8-77ea-41c9-94fd-e8cdf700a4dd.jsonl"

        messages = reader.load_session(session_path)
        types = {m.type for m in messages}

        assert "file-history-snapshot" not in types


class TestTranscriptSummaryFields:
    """Test that TranscriptSummary has all required fields."""

    def test_summary_has_session_id(self, temp_claude_home):
        """Summary should have session_id field."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home)
        sessions = reader.list_sessions("/Users/test/code/myproject")

        assert all(hasattr(s, "session_id") for s in sessions)
        assert all(s.session_id for s in sessions)

    def test_summary_has_path(self, temp_claude_home):
        """Summary should have path to transcript file."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home)
        sessions = reader.list_sessions("/Users/test/code/myproject")

        assert all(hasattr(s, "path") for s in sessions)
        assert all(s.path.exists() for s in sessions)

    def test_summary_has_timestamps(self, temp_claude_home):
        """Summary should have start_time and last_activity."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home)
        sessions = reader.list_sessions("/Users/test/code/myproject")

        for s in sessions:
            assert hasattr(s, "start_time")
            assert hasattr(s, "last_activity")
            assert isinstance(s.start_time, datetime)
            assert isinstance(s.last_activity, datetime)

    def test_summary_has_message_count(self, temp_claude_home):
        """Summary should have message_count."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home)
        sessions = reader.list_sessions("/Users/test/code/myproject")

        session = next(s for s in sessions if s.session_id == "eb3513a8-77ea-41c9-94fd-e8cdf700a4dd")
        assert session.message_count >= 2

    def test_summary_has_total_tokens(self, temp_claude_home):
        """Summary should have total_tokens from usage data."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home)
        sessions = reader.list_sessions("/Users/test/code/myproject")

        session = next(s for s in sessions if s.session_id == "eb3513a8-77ea-41c9-94fd-e8cdf700a4dd")
        assert session.total_tokens > 0


class TestTranscriptMessageFields:
    """Test that TranscriptMessage has all required fields."""

    def test_message_has_type(self, temp_claude_home):
        """Message should have type field (user/assistant)."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home)
        project_dir = reader.get_project_dir("/Users/test/code/myproject")
        session_path = project_dir / "eb3513a8-77ea-41c9-94fd-e8cdf700a4dd.jsonl"

        messages = reader.load_session(session_path)

        assert all(m.type in ("user", "assistant") for m in messages)

    def test_message_has_timestamp(self, temp_claude_home):
        """Message should have timestamp as datetime."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home)
        project_dir = reader.get_project_dir("/Users/test/code/myproject")
        session_path = project_dir / "eb3513a8-77ea-41c9-94fd-e8cdf700a4dd.jsonl"

        messages = reader.load_session(session_path)

        assert all(isinstance(m.timestamp, datetime) for m in messages)

    def test_message_has_content(self, temp_claude_home):
        """Message should have content field."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home)
        project_dir = reader.get_project_dir("/Users/test/code/myproject")
        session_path = project_dir / "eb3513a8-77ea-41c9-94fd-e8cdf700a4dd.jsonl"

        messages = reader.load_session(session_path)

        # User messages should have full content
        user_msgs = [m for m in messages if m.type == "user"]
        assert all(m.content for m in user_msgs)

    def test_message_has_tools_used_list(self, temp_claude_home):
        """Message should have tools_used as list."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home)
        project_dir = reader.get_project_dir("/Users/test/code/myproject")
        session_path = project_dir / "eb3513a8-77ea-41c9-94fd-e8cdf700a4dd.jsonl"

        messages = reader.load_session(session_path)

        assert all(isinstance(m.tools_used, list) for m in messages)


# Sample transcript data with lesson citations for citation tests
ASSISTANT_WITH_CITATIONS = {
    "type": "assistant",
    "uuid": "msg-asst-cite-001",
    "parentUuid": "msg-user-001",
    "timestamp": "2026-01-07T10:16:00.000Z",
    "sessionId": "citation-session-id",
    "message": {
        "role": "assistant",
        "id": "msg_cite_001",
        "model": "claude-opus-4-5-20251101",
        "stop_reason": "end_turn",
        "usage": {
            "input_tokens": 1000,
            "output_tokens": 200,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 500
        },
        "content": [
            {"type": "text", "text": "Based on [L001]: Test-first development, I'll write tests first. Also referencing [S002]: System lesson about patterns."}
        ]
    }
}

ASSISTANT_WITH_DUPLICATE_CITATIONS = {
    "type": "assistant",
    "uuid": "msg-asst-cite-002",
    "parentUuid": "msg-asst-cite-001",
    "timestamp": "2026-01-07T10:17:00.000Z",
    "sessionId": "citation-session-id",
    "message": {
        "role": "assistant",
        "id": "msg_cite_002",
        "model": "claude-opus-4-5-20251101",
        "stop_reason": "end_turn",
        "usage": {
            "input_tokens": 1200,
            "output_tokens": 150,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 600
        },
        "content": [
            {"type": "text", "text": "As mentioned in [L001]: this is important. Also [L003]: another lesson and [L001] again."}
        ]
    }
}

USER_WITH_CITATION = {
    "type": "user",
    "uuid": "msg-user-cite-001",
    "parentUuid": None,
    "timestamp": "2026-01-07T10:15:00.000Z",
    "sessionId": "citation-session-id",
    "cwd": "/Users/test/code/myproject",
    "message": {
        "role": "user",
        "content": "Please use [L999]: this lesson in your response."
    },
    "userType": "external"
}

ASSISTANT_WITHOUT_CITATIONS = {
    "type": "assistant",
    "uuid": "msg-asst-nocite-001",
    "parentUuid": "msg-user-001",
    "timestamp": "2026-01-07T10:16:30.000Z",
    "sessionId": "no-citation-session-id",
    "message": {
        "role": "assistant",
        "id": "msg_nocite_001",
        "model": "claude-opus-4-5-20251101",
        "stop_reason": "end_turn",
        "usage": {
            "input_tokens": 800,
            "output_tokens": 100,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 400
        },
        "content": [
            {"type": "text", "text": "Here is a response without any lesson citations."}
        ]
    }
}


@pytest.fixture
def temp_claude_home_with_citations(tmp_path):
    """Create a temporary ~/.claude structure with transcripts containing citations."""
    claude_home = tmp_path / ".claude"
    projects_dir = claude_home / "projects"

    project_dir = projects_dir / "-Users-test-code-myproject"
    project_dir.mkdir(parents=True)

    # Create transcript with citations in assistant messages
    citation_transcript = project_dir / "citation-session-id.jsonl"
    with open(citation_transcript, "w") as f:
        f.write(json.dumps(USER_WITH_CITATION) + "\n")
        f.write(json.dumps(ASSISTANT_WITH_CITATIONS) + "\n")
        f.write(json.dumps(ASSISTANT_WITH_DUPLICATE_CITATIONS) + "\n")

    # Create transcript without citations
    no_citation_transcript = project_dir / "no-citation-session-id.jsonl"
    with open(no_citation_transcript, "w") as f:
        f.write(json.dumps(SAMPLE_USER_MESSAGE) + "\n")
        f.write(json.dumps(ASSISTANT_WITHOUT_CITATIONS) + "\n")

    return claude_home


class TestLessonCitationExtraction:
    """Test extraction of lesson citations [L###] and [S###] from transcripts."""

    def test_extract_citations_from_assistant_messages(self, temp_claude_home_with_citations):
        """Transcript with citations should populate lesson_citations field."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home_with_citations)
        sessions = reader.list_sessions("/Users/test/code/myproject")

        # Find the session with citations
        session = next(s for s in sessions if s.session_id == "citation-session-id")

        # This should fail because lesson_citations field doesn't exist yet
        assert hasattr(session, "lesson_citations"), "TranscriptSummary should have lesson_citations field"
        assert "L001" in session.lesson_citations
        assert "S002" in session.lesson_citations

    def test_citations_are_unique_and_sorted(self, temp_claude_home_with_citations):
        """Duplicate citations should be deduplicated and sorted."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home_with_citations)
        sessions = reader.list_sessions("/Users/test/code/myproject")

        session = next(s for s in sessions if s.session_id == "citation-session-id")

        # This should fail because lesson_citations field doesn't exist yet
        assert hasattr(session, "lesson_citations"), "TranscriptSummary should have lesson_citations field"

        # Citations should be unique (L001 appears multiple times but should only be listed once)
        # and sorted alphabetically: L001, L003, S002
        assert session.lesson_citations == ["L001", "L003", "S002"]

    def test_citations_ignore_user_messages(self, temp_claude_home_with_citations):
        """Citations in user messages should be ignored."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home_with_citations)
        sessions = reader.list_sessions("/Users/test/code/myproject")

        session = next(s for s in sessions if s.session_id == "citation-session-id")

        # This should fail because lesson_citations field doesn't exist yet
        assert hasattr(session, "lesson_citations"), "TranscriptSummary should have lesson_citations field"

        # L999 is in user message, should NOT be extracted
        assert "L999" not in session.lesson_citations

    def test_no_citations_returns_empty_list(self, temp_claude_home_with_citations):
        """Transcript without citations should have empty lesson_citations list."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home_with_citations)
        sessions = reader.list_sessions("/Users/test/code/myproject")

        session = next(s for s in sessions if s.session_id == "no-citation-session-id")

        # This should fail because lesson_citations field doesn't exist yet
        assert hasattr(session, "lesson_citations"), "TranscriptSummary should have lesson_citations field"
        assert session.lesson_citations == []


# ============================================================================
# Origin Detection Tests
# ============================================================================

# Sample transcript data for different session types
EXPLORE_AGENT_MESSAGE = {
    "type": "user",
    "uuid": "msg-explore-001",
    "parentUuid": None,
    "timestamp": "2026-01-07T10:00:00.000Z",
    "sessionId": "explore-session-id",
    "cwd": "/Users/test/code/myproject",
    "message": {
        "role": "user",
        "content": "Explore the codebase to find files related to authentication. Look for login handlers and session management."
    },
    "userType": "external"
}

PLAN_AGENT_MESSAGE = {
    "type": "user",
    "uuid": "msg-plan-001",
    "parentUuid": None,
    "timestamp": "2026-01-07T10:01:00.000Z",
    "sessionId": "plan-session-id",
    "cwd": "/Users/test/code/myproject",
    "message": {
        "role": "user",
        "content": "Plan the implementation approach for adding OAuth2 support. Design a strategy that integrates with existing auth."
    },
    "userType": "external"
}

GENERAL_AGENT_MESSAGE = {
    "type": "user",
    "uuid": "msg-general-001",
    "parentUuid": None,
    "timestamp": "2026-01-07T10:02:00.000Z",
    "sessionId": "general-session-id",
    "cwd": "/Users/test/code/myproject",
    "message": {
        "role": "user",
        "content": "Implement the OAuth2 authentication flow according to the plan. Fix any type errors and refactor the token storage."
    },
    "userType": "external"
}

USER_SESSION_MESSAGE = {
    "type": "user",
    "uuid": "msg-user-session-001",
    "parentUuid": None,
    "timestamp": "2026-01-07T10:03:00.000Z",
    "sessionId": "user-session-id",
    "cwd": "/Users/test/code/myproject",
    "message": {
        "role": "user",
        "content": "How do I add a new feature to handle user preferences? I'm not sure where to start."
    },
    "userType": "external"
}

UNKNOWN_SYSTEM_MESSAGE = {
    "type": "user",
    "uuid": "msg-unknown-001",
    "parentUuid": None,
    "timestamp": "2026-01-07T10:04:00.000Z",
    "sessionId": "unknown-session-id",
    "cwd": "/Users/test/code/myproject",
    "message": {
        "role": "user",
        "content": "<local-command-caveat>Warmup session for model initialization</local-command-caveat>"
    },
    "userType": "external"
}

EMPTY_PROMPT_MESSAGE = {
    "type": "user",
    "uuid": "msg-empty-001",
    "parentUuid": None,
    "timestamp": "2026-01-07T10:05:00.000Z",
    "sessionId": "empty-session-id",
    "cwd": "/Users/test/code/myproject",
    "message": {
        "role": "user",
        "content": ""
    },
    "userType": "external"
}


@pytest.fixture
def temp_claude_home_with_origins(tmp_path):
    """Create a temporary ~/.claude structure with various session types."""
    claude_home = tmp_path / ".claude"
    projects_dir = claude_home / "projects"

    project_dir = projects_dir / "-Users-test-code-myproject"
    project_dir.mkdir(parents=True)

    # Create transcripts for each session type
    sessions = [
        ("explore-session-id.jsonl", EXPLORE_AGENT_MESSAGE),
        ("plan-session-id.jsonl", PLAN_AGENT_MESSAGE),
        ("general-session-id.jsonl", GENERAL_AGENT_MESSAGE),
        ("user-session-id.jsonl", USER_SESSION_MESSAGE),
        ("unknown-session-id.jsonl", UNKNOWN_SYSTEM_MESSAGE),
        ("empty-session-id.jsonl", EMPTY_PROMPT_MESSAGE),
    ]

    for filename, user_msg in sessions:
        transcript_path = project_dir / filename
        with open(transcript_path, "w") as f:
            f.write(json.dumps(user_msg) + "\n")
            # Add a simple assistant response
            assistant_msg = {
                "type": "assistant",
                "uuid": f"msg-asst-{filename}",
                "parentUuid": user_msg["uuid"],
                "timestamp": "2026-01-07T10:10:00.000Z",
                "sessionId": user_msg["sessionId"],
                "message": {
                    "role": "assistant",
                    "id": f"msg_{filename}",
                    "model": "claude-opus-4-5-20251101",
                    "stop_reason": "end_turn",
                    "usage": {"input_tokens": 100, "output_tokens": 50},
                    "content": [{"type": "text", "text": "Response text."}]
                }
            }
            f.write(json.dumps(assistant_msg) + "\n")

    return claude_home


class TestOriginDetectionFunction:
    """Test the detect_origin() function for classifying session types."""

    def test_detect_origin_function_exists(self):
        """detect_origin function should be importable."""
        from core.tui.transcript_reader import detect_origin
        assert callable(detect_origin)

    def test_detect_explore_starts_with_explore(self):
        """Prompts starting with 'Explore' should return 'Explore'."""
        from core.tui.transcript_reader import detect_origin
        assert detect_origin("Explore the codebase for authentication code") == "Explore"

    def test_detect_explore_starts_with_search(self):
        """Prompts starting with 'Search' should return 'Explore'."""
        from core.tui.transcript_reader import detect_origin
        assert detect_origin("Search for files containing login logic") == "Explore"

    def test_detect_explore_starts_with_find(self):
        """Prompts starting with 'Find' should return 'Explore'."""
        from core.tui.transcript_reader import detect_origin
        assert detect_origin("Find all test files in the project") == "Explore"

    def test_detect_explore_starts_with_investigate(self):
        """Prompts starting with 'Investigate' should return 'Explore'."""
        from core.tui.transcript_reader import detect_origin
        assert detect_origin("Investigate the error handling in api.py") == "Explore"

    def test_detect_explore_contains_in_codebase(self):
        """Prompts containing 'in the codebase' should return 'Explore'."""
        from core.tui.transcript_reader import detect_origin
        assert detect_origin("Look at how auth works in the codebase") == "Explore"

    def test_detect_plan_starts_with_plan(self):
        """Prompts starting with 'Plan' should return 'Plan'."""
        from core.tui.transcript_reader import detect_origin
        assert detect_origin("Plan the implementation of OAuth2 support") == "Plan"

    def test_detect_plan_starts_with_design(self):
        """Prompts starting with 'Design' should return 'Plan'."""
        from core.tui.transcript_reader import detect_origin
        assert detect_origin("Design a strategy for migrating the database") == "Plan"

    def test_detect_plan_contains_implementation_plan(self):
        """Prompts containing 'implementation plan' should return 'Plan'."""
        from core.tui.transcript_reader import detect_origin
        assert detect_origin("Create an implementation plan for the new feature") == "Plan"

    def test_detect_general_starts_with_implement(self):
        """Prompts starting with 'Implement' should return 'General'."""
        from core.tui.transcript_reader import detect_origin
        assert detect_origin("Implement the login form validation") == "General"

    def test_detect_general_starts_with_fix(self):
        """Prompts starting with 'Fix' should return 'General'."""
        from core.tui.transcript_reader import detect_origin
        assert detect_origin("Fix the bug in the session handler") == "General"

    def test_detect_general_starts_with_refactor(self):
        """Prompts starting with 'Refactor' should return 'General'."""
        from core.tui.transcript_reader import detect_origin
        assert detect_origin("Refactor the database connection code") == "General"

    def test_detect_general_starts_with_review(self):
        """Prompts starting with 'Review' should return 'General'."""
        from core.tui.transcript_reader import detect_origin
        assert detect_origin("Review the pull request changes") == "General"

    def test_detect_user_local_command_caveat(self):
        """Prompts containing '<local-command-caveat>' should return 'User' (these are user commands)."""
        from core.tui.transcript_reader import detect_origin
        assert detect_origin("<local-command-caveat>User ran a local command</local-command-caveat>") == "User"

    def test_detect_system_analyze_conversation(self):
        """Prompts starting with 'Analyze this conversation' should return 'System'."""
        from core.tui.transcript_reader import detect_origin
        assert detect_origin("Analyze this conversation and extract key information") == "System"

    def test_detect_system_score_relevance(self):
        """Prompts about scoring lesson relevance should return 'System'."""
        from core.tui.transcript_reader import detect_origin
        assert detect_origin("Score each lesson's relevance to the current task") == "System"
        assert detect_origin("Score the relevance of each lesson below") == "System"

    def test_detect_system_summarize_key_points(self):
        """Prompts starting with 'Summarize the key points' should return 'System'."""
        from core.tui.transcript_reader import detect_origin
        assert detect_origin("Summarize the key points from this session") == "System"

    def test_detect_system_case_insensitive(self):
        """System pattern detection should be case-insensitive."""
        from core.tui.transcript_reader import detect_origin
        assert detect_origin("ANALYZE THIS CONVERSATION for patterns") == "System"
        assert detect_origin("analyze this conversation for patterns") == "System"

    def test_detect_warmup(self):
        """Prompts starting with 'Warmup' should return 'Warmup'."""
        from core.tui.transcript_reader import detect_origin
        assert detect_origin("Warmup session initializing") == "Warmup"
        assert detect_origin("Warmup") == "Warmup"

    def test_detect_unknown_empty_prompt(self):
        """Empty prompts should return 'Unknown'."""
        from core.tui.transcript_reader import detect_origin
        assert detect_origin("") == "Unknown"

    def test_detect_unknown_very_short_prompt(self):
        """Very short prompts (< 3 chars) should return 'Unknown'."""
        from core.tui.transcript_reader import detect_origin
        assert detect_origin("Hi") == "Unknown"

    def test_detect_user_natural_question(self):
        """Natural language questions should return 'User'."""
        from core.tui.transcript_reader import detect_origin
        assert detect_origin("How do I add a new feature?") == "User"

    def test_detect_user_help_request(self):
        """Help requests should return 'User'."""
        from core.tui.transcript_reader import detect_origin
        assert detect_origin("Can you help me understand the codebase?") == "User"

    def test_detect_user_default(self):
        """Unrecognized patterns should default to 'User'."""
        from core.tui.transcript_reader import detect_origin
        assert detect_origin("Just a random message that doesn't match patterns") == "User"

    def test_detect_case_insensitive(self):
        """Detection should be case-insensitive."""
        from core.tui.transcript_reader import detect_origin
        assert detect_origin("explore the files") == "Explore"
        assert detect_origin("EXPLORE THE FILES") == "Explore"
        assert detect_origin("Explore The Files") == "Explore"


class TestOriginFieldInSummary:
    """Test that TranscriptSummary includes origin field."""

    def test_summary_has_origin_field(self, temp_claude_home_with_origins):
        """TranscriptSummary should have origin field."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home_with_origins)
        sessions = reader.list_sessions("/Users/test/code/myproject")

        assert all(hasattr(s, "origin") for s in sessions)

    def test_explore_session_detected(self, temp_claude_home_with_origins):
        """Explore agent session should have origin='Explore'."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home_with_origins)
        sessions = reader.list_sessions("/Users/test/code/myproject")

        session = next(s for s in sessions if s.session_id == "explore-session-id")
        assert session.origin == "Explore"

    def test_plan_session_detected(self, temp_claude_home_with_origins):
        """Plan agent session should have origin='Plan'."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home_with_origins)
        sessions = reader.list_sessions("/Users/test/code/myproject")

        session = next(s for s in sessions if s.session_id == "plan-session-id")
        assert session.origin == "Plan"

    def test_general_session_detected(self, temp_claude_home_with_origins):
        """General agent session should have origin='General'."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home_with_origins)
        sessions = reader.list_sessions("/Users/test/code/myproject")

        session = next(s for s in sessions if s.session_id == "general-session-id")
        assert session.origin == "General"

    def test_user_session_detected(self, temp_claude_home_with_origins):
        """User session should have origin='User'."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home_with_origins)
        sessions = reader.list_sessions("/Users/test/code/myproject")

        session = next(s for s in sessions if s.session_id == "user-session-id")
        assert session.origin == "User"

    def test_local_command_caveat_session_detected_as_user(self, temp_claude_home_with_origins):
        """Session with <local-command-caveat> should have origin='User' (user commands)."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home_with_origins)
        sessions = reader.list_sessions("/Users/test/code/myproject")

        session = next(s for s in sessions if s.session_id == "unknown-session-id")
        assert session.origin == "User"


# ============================================================================
# Parent-Child Session Linking Tests
# ============================================================================

# Create sessions with overlapping time ranges for parent-child linking
PARENT_SESSION_START = {
    "type": "user",
    "uuid": "msg-parent-001",
    "parentUuid": None,
    "timestamp": "2026-01-07T10:00:00.000Z",
    "sessionId": "parent-session-id",
    "cwd": "/Users/test/code/myproject",
    "message": {
        "role": "user",
        "content": "Help me implement a new authentication system."
    },
    "userType": "external"
}

PARENT_SESSION_MIDDLE = {
    "type": "assistant",
    "uuid": "msg-parent-002",
    "parentUuid": "msg-parent-001",
    "timestamp": "2026-01-07T10:05:00.000Z",
    "sessionId": "parent-session-id",
    "message": {
        "role": "assistant",
        "id": "msg_parent_001",
        "model": "claude-opus-4-5-20251101",
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 100, "output_tokens": 200},
        "content": [{"type": "text", "text": "I'll help you with that. Let me explore the codebase first."}]
    }
}

PARENT_SESSION_END = {
    "type": "assistant",
    "uuid": "msg-parent-003",
    "parentUuid": "msg-parent-002",
    "timestamp": "2026-01-07T10:30:00.000Z",
    "sessionId": "parent-session-id",
    "message": {
        "role": "assistant",
        "id": "msg_parent_002",
        "model": "claude-opus-4-5-20251101",
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 150, "output_tokens": 100},
        "content": [{"type": "text", "text": "Done!"}]
    }
}

# Child session starts during parent's active time (10:10, between 10:00 and 10:30)
CHILD_EXPLORE_SESSION = {
    "type": "user",
    "uuid": "msg-child-explore-001",
    "parentUuid": None,
    "timestamp": "2026-01-07T10:10:00.000Z",
    "sessionId": "child-explore-session-id",
    "cwd": "/Users/test/code/myproject",
    "message": {
        "role": "user",
        "content": "Explore the authentication module and find how sessions are handled."
    },
    "userType": "external"
}

CHILD_EXPLORE_END = {
    "type": "assistant",
    "uuid": "msg-child-explore-002",
    "parentUuid": "msg-child-explore-001",
    "timestamp": "2026-01-07T10:15:00.000Z",
    "sessionId": "child-explore-session-id",
    "message": {
        "role": "assistant",
        "id": "msg_child_explore",
        "model": "claude-opus-4-5-20251101",
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 100, "output_tokens": 150},
        "content": [{"type": "text", "text": "Found the session handling code."}]
    }
}

# Another child session starts at 10:20
CHILD_GENERAL_SESSION = {
    "type": "user",
    "uuid": "msg-child-general-001",
    "parentUuid": None,
    "timestamp": "2026-01-07T10:20:00.000Z",
    "sessionId": "child-general-session-id",
    "cwd": "/Users/test/code/myproject",
    "message": {
        "role": "user",
        "content": "Implement the token refresh logic based on the exploration results."
    },
    "userType": "external"
}

CHILD_GENERAL_END = {
    "type": "assistant",
    "uuid": "msg-child-general-002",
    "parentUuid": "msg-child-general-001",
    "timestamp": "2026-01-07T10:25:00.000Z",
    "sessionId": "child-general-session-id",
    "message": {
        "role": "assistant",
        "id": "msg_child_general",
        "model": "claude-opus-4-5-20251101",
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 100, "output_tokens": 200},
        "content": [{"type": "text", "text": "Token refresh implemented."}]
    }
}

# Independent session (no overlap with parent)
INDEPENDENT_SESSION = {
    "type": "user",
    "uuid": "msg-independent-001",
    "parentUuid": None,
    "timestamp": "2026-01-07T11:00:00.000Z",  # After parent ends
    "sessionId": "independent-session-id",
    "cwd": "/Users/test/code/myproject",
    "message": {
        "role": "user",
        "content": "Help me with something completely different."
    },
    "userType": "external"
}

INDEPENDENT_END = {
    "type": "assistant",
    "uuid": "msg-independent-002",
    "parentUuid": "msg-independent-001",
    "timestamp": "2026-01-07T11:05:00.000Z",
    "sessionId": "independent-session-id",
    "message": {
        "role": "assistant",
        "id": "msg_independent",
        "model": "claude-opus-4-5-20251101",
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 50, "output_tokens": 75},
        "content": [{"type": "text", "text": "Sure!"}]
    }
}


@pytest.fixture
def temp_claude_home_with_parent_child(tmp_path):
    """Create a temporary ~/.claude structure with parent-child session relationships."""
    claude_home = tmp_path / ".claude"
    projects_dir = claude_home / "projects"

    project_dir = projects_dir / "-Users-test-code-myproject"
    project_dir.mkdir(parents=True)

    # Create parent session (10:00 - 10:30)
    parent_transcript = project_dir / "parent-session-id.jsonl"
    with open(parent_transcript, "w") as f:
        f.write(json.dumps(PARENT_SESSION_START) + "\n")
        f.write(json.dumps(PARENT_SESSION_MIDDLE) + "\n")
        f.write(json.dumps(PARENT_SESSION_END) + "\n")

    # Create child explore session (10:10 - 10:15, within parent's range)
    child_explore = project_dir / "child-explore-session-id.jsonl"
    with open(child_explore, "w") as f:
        f.write(json.dumps(CHILD_EXPLORE_SESSION) + "\n")
        f.write(json.dumps(CHILD_EXPLORE_END) + "\n")

    # Create child general session (10:20 - 10:25, within parent's range)
    child_general = project_dir / "child-general-session-id.jsonl"
    with open(child_general, "w") as f:
        f.write(json.dumps(CHILD_GENERAL_SESSION) + "\n")
        f.write(json.dumps(CHILD_GENERAL_END) + "\n")

    # Create independent session (11:00 - 11:05, after parent)
    independent = project_dir / "independent-session-id.jsonl"
    with open(independent, "w") as f:
        f.write(json.dumps(INDEPENDENT_SESSION) + "\n")
        f.write(json.dumps(INDEPENDENT_END) + "\n")

    return claude_home


class TestParentChildLinkingFields:
    """Test that TranscriptSummary includes parent-child linking fields."""

    def test_summary_has_parent_session_id_field(self, temp_claude_home_with_parent_child):
        """TranscriptSummary should have parent_session_id field."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home_with_parent_child)
        sessions = reader.list_sessions("/Users/test/code/myproject")

        assert all(hasattr(s, "parent_session_id") for s in sessions)

    def test_summary_has_child_session_ids_field(self, temp_claude_home_with_parent_child):
        """TranscriptSummary should have child_session_ids field."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home_with_parent_child)
        sessions = reader.list_sessions("/Users/test/code/myproject")

        assert all(hasattr(s, "child_session_ids") for s in sessions)


class TestParentChildLinking:
    """Test parent-child session linking via temporal inference."""

    def test_child_explore_linked_to_parent(self, temp_claude_home_with_parent_child):
        """Explore child session should be linked to parent."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home_with_parent_child)
        sessions = reader.list_sessions("/Users/test/code/myproject")

        child = next(s for s in sessions if s.session_id == "child-explore-session-id")
        assert child.parent_session_id == "parent-session-id"

    def test_child_general_linked_to_parent(self, temp_claude_home_with_parent_child):
        """General child session should be linked to parent."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home_with_parent_child)
        sessions = reader.list_sessions("/Users/test/code/myproject")

        child = next(s for s in sessions if s.session_id == "child-general-session-id")
        assert child.parent_session_id == "parent-session-id"

    def test_parent_has_child_ids(self, temp_claude_home_with_parent_child):
        """Parent session should have child_session_ids populated."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home_with_parent_child)
        sessions = reader.list_sessions("/Users/test/code/myproject")

        parent = next(s for s in sessions if s.session_id == "parent-session-id")
        assert "child-explore-session-id" in parent.child_session_ids
        assert "child-general-session-id" in parent.child_session_ids

    def test_independent_session_no_parent(self, temp_claude_home_with_parent_child):
        """Independent session should have no parent."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home_with_parent_child)
        sessions = reader.list_sessions("/Users/test/code/myproject")

        independent = next(s for s in sessions if s.session_id == "independent-session-id")
        assert independent.parent_session_id is None

    def test_user_session_not_linked_as_child(self, temp_claude_home_with_parent_child):
        """User-origin sessions should not be linked as children even if overlapping."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home_with_parent_child)
        sessions = reader.list_sessions("/Users/test/code/myproject")

        parent = next(s for s in sessions if s.session_id == "parent-session-id")
        # Parent is a User session, should not be listed as a child of anything
        assert parent.parent_session_id is None

    def test_linking_uses_temporal_overlap(self, temp_claude_home_with_parent_child):
        """Child sessions should only link if they start during parent's active window."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home_with_parent_child)
        sessions = reader.list_sessions("/Users/test/code/myproject")

        # Independent session starts after parent ends, should not be linked
        independent = next(s for s in sessions if s.session_id == "independent-session-id")
        assert independent.parent_session_id is None

        parent = next(s for s in sessions if s.session_id == "parent-session-id")
        assert "independent-session-id" not in parent.child_session_ids


# ============================================================================
# Token Counting Tests
# ============================================================================

# Sample transcript data with detailed token usage
TOKEN_SESSION_USER = {
    "type": "user",
    "uuid": "msg-token-user-001",
    "parentUuid": None,
    "timestamp": "2026-01-08T10:00:00.000Z",
    "sessionId": "token-test-session-id",
    "cwd": "/Users/test/code/myproject",
    "message": {
        "role": "user",
        "content": "Help me understand token counting."
    },
    "userType": "external"
}

TOKEN_SESSION_ASSISTANT_1 = {
    "type": "assistant",
    "uuid": "msg-token-asst-001",
    "parentUuid": "msg-token-user-001",
    "timestamp": "2026-01-08T10:00:05.000Z",
    "sessionId": "token-test-session-id",
    "message": {
        "role": "assistant",
        "id": "msg_token_001",
        "model": "claude-opus-4-5-20251101",
        "stop_reason": "end_turn",
        "usage": {
            "input_tokens": 5000,
            "output_tokens": 500,
            "cache_creation_input_tokens": 3000,
            "cache_read_input_tokens": 1500
        },
        "content": [{"type": "text", "text": "I'll explain token counting."}]
    }
}

TOKEN_SESSION_ASSISTANT_2 = {
    "type": "assistant",
    "uuid": "msg-token-asst-002",
    "parentUuid": "msg-token-asst-001",
    "timestamp": "2026-01-08T10:00:10.000Z",
    "sessionId": "token-test-session-id",
    "message": {
        "role": "assistant",
        "id": "msg_token_002",
        "model": "claude-opus-4-5-20251101",
        "stop_reason": "end_turn",
        "usage": {
            "input_tokens": 6000,
            "output_tokens": 800,
            "cache_creation_input_tokens": 500,
            "cache_read_input_tokens": 4000
        },
        "content": [{"type": "text", "text": "Here's more detail on tokens."}]
    }
}

# Session without cache tokens (older format or no caching)
TOKEN_SESSION_NO_CACHE = {
    "type": "assistant",
    "uuid": "msg-token-nocache-001",
    "parentUuid": "msg-token-user-001",
    "timestamp": "2026-01-08T10:01:00.000Z",
    "sessionId": "token-no-cache-session-id",
    "message": {
        "role": "assistant",
        "id": "msg_nocache_001",
        "model": "claude-opus-4-5-20251101",
        "stop_reason": "end_turn",
        "usage": {
            "input_tokens": 1000,
            "output_tokens": 200
            # No cache fields
        },
        "content": [{"type": "text", "text": "Response without cache tokens."}]
    }
}


@pytest.fixture
def temp_claude_home_with_tokens(tmp_path):
    """Create a temporary ~/.claude structure with token-rich transcripts."""
    claude_home = tmp_path / ".claude"
    projects_dir = claude_home / "projects"

    project_dir = projects_dir / "-Users-test-code-myproject"
    project_dir.mkdir(parents=True)

    # Create transcript with full token usage
    token_transcript = project_dir / "token-test-session-id.jsonl"
    with open(token_transcript, "w") as f:
        f.write(json.dumps(TOKEN_SESSION_USER) + "\n")
        f.write(json.dumps(TOKEN_SESSION_ASSISTANT_1) + "\n")
        f.write(json.dumps(TOKEN_SESSION_ASSISTANT_2) + "\n")

    # Create transcript without cache tokens
    user_msg = TOKEN_SESSION_USER.copy()
    user_msg["sessionId"] = "token-no-cache-session-id"
    no_cache_transcript = project_dir / "token-no-cache-session-id.jsonl"
    with open(no_cache_transcript, "w") as f:
        f.write(json.dumps(user_msg) + "\n")
        f.write(json.dumps(TOKEN_SESSION_NO_CACHE) + "\n")

    return claude_home


class TestTokenCountingFields:
    """Test that TranscriptSummary has separate token counting fields."""

    def test_summary_has_input_tokens_field(self, temp_claude_home_with_tokens):
        """TranscriptSummary should have input_tokens field."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home_with_tokens)
        sessions = reader.list_sessions("/Users/test/code/myproject")

        assert all(hasattr(s, "input_tokens") for s in sessions)

    def test_summary_has_output_tokens_field(self, temp_claude_home_with_tokens):
        """TranscriptSummary should have output_tokens field."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home_with_tokens)
        sessions = reader.list_sessions("/Users/test/code/myproject")

        assert all(hasattr(s, "output_tokens") for s in sessions)

    def test_summary_has_cache_read_tokens_field(self, temp_claude_home_with_tokens):
        """TranscriptSummary should have cache_read_tokens field."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home_with_tokens)
        sessions = reader.list_sessions("/Users/test/code/myproject")

        assert all(hasattr(s, "cache_read_tokens") for s in sessions)

    def test_summary_has_cache_creation_tokens_field(self, temp_claude_home_with_tokens):
        """TranscriptSummary should have cache_creation_tokens field."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home_with_tokens)
        sessions = reader.list_sessions("/Users/test/code/myproject")

        assert all(hasattr(s, "cache_creation_tokens") for s in sessions)


class TestTokenCounting:
    """Test token counting aggregation from transcripts."""

    def test_input_tokens_summed_correctly(self, temp_claude_home_with_tokens):
        """Input tokens should be summed across all assistant messages."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home_with_tokens)
        sessions = reader.list_sessions("/Users/test/code/myproject")

        session = next(s for s in sessions if s.session_id == "token-test-session-id")
        # 5000 + 6000 = 11000
        assert session.input_tokens == 11000

    def test_output_tokens_summed_correctly(self, temp_claude_home_with_tokens):
        """Output tokens should be summed across all assistant messages."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home_with_tokens)
        sessions = reader.list_sessions("/Users/test/code/myproject")

        session = next(s for s in sessions if s.session_id == "token-test-session-id")
        # 500 + 800 = 1300
        assert session.output_tokens == 1300

    def test_cache_read_tokens_summed_correctly(self, temp_claude_home_with_tokens):
        """Cache read tokens should be summed across all assistant messages."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home_with_tokens)
        sessions = reader.list_sessions("/Users/test/code/myproject")

        session = next(s for s in sessions if s.session_id == "token-test-session-id")
        # 1500 + 4000 = 5500
        assert session.cache_read_tokens == 5500

    def test_cache_creation_tokens_summed_correctly(self, temp_claude_home_with_tokens):
        """Cache creation tokens should be summed across all assistant messages."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home_with_tokens)
        sessions = reader.list_sessions("/Users/test/code/myproject")

        session = next(s for s in sessions if s.session_id == "token-test-session-id")
        # 3000 + 500 = 3500
        assert session.cache_creation_tokens == 3500

    def test_total_tokens_is_input_plus_output(self, temp_claude_home_with_tokens):
        """total_tokens should be input_tokens + output_tokens."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home_with_tokens)
        sessions = reader.list_sessions("/Users/test/code/myproject")

        session = next(s for s in sessions if s.session_id == "token-test-session-id")
        # input (11000) + output (1300) = 12300
        assert session.total_tokens == session.input_tokens + session.output_tokens
        assert session.total_tokens == 12300

    def test_missing_cache_fields_default_to_zero(self, temp_claude_home_with_tokens):
        """Missing cache token fields should default to 0."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home_with_tokens)
        sessions = reader.list_sessions("/Users/test/code/myproject")

        session = next(s for s in sessions if s.session_id == "token-no-cache-session-id")
        assert session.cache_read_tokens == 0
        assert session.cache_creation_tokens == 0

    def test_tokens_counted_with_missing_cache(self, temp_claude_home_with_tokens):
        """Input and output tokens should still be counted when cache fields missing."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home_with_tokens)
        sessions = reader.list_sessions("/Users/test/code/myproject")

        session = next(s for s in sessions if s.session_id == "token-no-cache-session-id")
        assert session.input_tokens == 1000
        assert session.output_tokens == 200
        assert session.total_tokens == 1200


class TestTokenCountingBackwardCompatibility:
    """Test that token counting maintains backward compatibility."""

    def test_existing_total_tokens_behavior(self, temp_claude_home):
        """Existing tests using total_tokens should continue to work."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home)
        sessions = reader.list_sessions("/Users/test/code/myproject")

        session = next(s for s in sessions if s.session_id == "eb3513a8-77ea-41c9-94fd-e8cdf700a4dd")
        # total_tokens should still return a positive value for sessions with usage data
        assert session.total_tokens > 0


# ============================================================================
# Session Cache Tests (Performance Optimization)
# ============================================================================


class TestSessionCaching:
    """Test mtime-based caching for session summaries to improve performance."""

    def test_cache_hit_returns_same_summary_without_reparsing(self, temp_claude_home):
        """Second call with unchanged file should return cached result without re-reading file."""
        from core.tui.transcript_reader import TranscriptReader
        from unittest.mock import patch
        import builtins

        reader = TranscriptReader(claude_home=temp_claude_home)

        # First call - should parse file
        sessions1 = reader.list_sessions("/Users/test/code/myproject")
        assert len(sessions1) == 2

        # Track how many times open() is called for JSONL files
        original_open = builtins.open
        open_calls = []

        def tracking_open(path, *args, **kwargs):
            if str(path).endswith(".jsonl"):
                open_calls.append(path)
            return original_open(path, *args, **kwargs)

        with patch.object(builtins, "open", tracking_open):
            # Second call - should use cache, not re-open files
            sessions2 = reader.list_sessions("/Users/test/code/myproject")

        # Should return same number of sessions
        assert len(sessions2) == 2
        # Should NOT have opened any JSONL files (cache hit)
        assert len(open_calls) == 0, f"Expected no file opens, but got {len(open_calls)}: {open_calls}"

    def test_cache_invalidates_when_file_modified(self, temp_claude_home):
        """Modified file should trigger re-parse and return updated content."""
        from core.tui.transcript_reader import TranscriptReader
        import time

        reader = TranscriptReader(claude_home=temp_claude_home)

        # First call - should parse file
        sessions1 = reader.list_sessions("/Users/test/code/myproject")
        original_session = next(s for s in sessions1 if s.session_id == "eb3513a8-77ea-41c9-94fd-e8cdf700a4dd")
        original_count = original_session.message_count

        # Modify the file - add another message
        project_dir = temp_claude_home / "projects" / "-Users-test-code-myproject"
        transcript_path = project_dir / "eb3513a8-77ea-41c9-94fd-e8cdf700a4dd.jsonl"

        # Wait a bit to ensure mtime changes
        time.sleep(0.1)

        # Append a new message
        new_message = {
            "type": "user",
            "uuid": "msg-user-new",
            "parentUuid": "msg-asst-002",
            "timestamp": "2026-01-07T10:16:00.000Z",
            "sessionId": "eb3513a8-77ea-41c9-94fd-e8cdf700a4dd",
            "message": {"role": "user", "content": "Follow-up question."},
            "userType": "external"
        }
        with open(transcript_path, "a") as f:
            f.write(json.dumps(new_message) + "\n")

        # Second call - should detect mtime change and re-parse
        sessions2 = reader.list_sessions("/Users/test/code/myproject")
        updated_session = next(s for s in sessions2 if s.session_id == "eb3513a8-77ea-41c9-94fd-e8cdf700a4dd")

        # Message count should have increased
        assert updated_session.message_count == original_count + 1

    def test_cache_is_thread_safe(self, temp_claude_home):
        """Concurrent access should not corrupt cache or raise exceptions."""
        from core.tui.transcript_reader import TranscriptReader
        import threading
        import concurrent.futures

        reader = TranscriptReader(claude_home=temp_claude_home)
        results = []
        errors = []

        def read_sessions():
            try:
                sessions = reader.list_sessions("/Users/test/code/myproject")
                results.append(len(sessions))
            except Exception as e:
                errors.append(e)

        # Run multiple concurrent reads
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(read_sessions) for _ in range(20)]
            concurrent.futures.wait(futures)

        # Should have no errors
        assert len(errors) == 0, f"Got errors: {errors}"
        # All results should be consistent
        assert all(r == 2 for r in results), f"Inconsistent results: {results}"

    def test_clear_cache_forces_reparse(self, temp_claude_home):
        """clear_cache() should force re-reading files on next call."""
        from core.tui.transcript_reader import TranscriptReader
        from unittest.mock import patch
        import builtins

        reader = TranscriptReader(claude_home=temp_claude_home)

        # First call - populate cache
        reader.list_sessions("/Users/test/code/myproject")

        # Clear the cache
        reader.clear_cache()

        # Track file opens
        original_open = builtins.open
        open_calls = []

        def tracking_open(path, *args, **kwargs):
            if str(path).endswith(".jsonl"):
                open_calls.append(path)
            return original_open(path, *args, **kwargs)

        with patch.object(builtins, "open", tracking_open):
            # This should re-read files since cache was cleared
            reader.list_sessions("/Users/test/code/myproject")

        # Should have opened JSONL files
        assert len(open_calls) >= 2, f"Expected file opens after cache clear, got {len(open_calls)}"

    def test_cache_works_for_list_all_sessions(self, temp_claude_home):
        """Cache should also work for list_all_sessions()."""
        from core.tui.transcript_reader import TranscriptReader
        from unittest.mock import patch
        import builtins

        reader = TranscriptReader(claude_home=temp_claude_home)

        # First call - should parse files
        sessions1 = reader.list_all_sessions()
        assert len(sessions1) == 3

        # Track file opens
        original_open = builtins.open
        open_calls = []

        def tracking_open(path, *args, **kwargs):
            if str(path).endswith(".jsonl"):
                open_calls.append(path)
            return original_open(path, *args, **kwargs)

        with patch.object(builtins, "open", tracking_open):
            # Second call - should use cache
            sessions2 = reader.list_all_sessions()

        assert len(sessions2) == 3
        # Should not have opened any files
        assert len(open_calls) == 0, f"Expected no file opens, but got {len(open_calls)}"


# ============================================================================
# Fast Initial Load Tests (Performance Optimization)
# ============================================================================


@pytest.fixture
def temp_claude_home_with_age_variety(tmp_path):
    """Create a temporary ~/.claude structure with files of varying ages."""
    import time

    claude_home = tmp_path / ".claude"
    projects_dir = claude_home / "projects"
    project_dir = projects_dir / "-Users-test-code-myproject"
    project_dir.mkdir(parents=True)

    # Create recent session (modified now)
    recent_transcript = project_dir / "recent-session.jsonl"
    recent_msg = {
        "type": "user",
        "timestamp": "2026-01-09T10:00:00.000Z",
        "sessionId": "recent-session",
        "message": {"role": "user", "content": "Recent session"},
    }
    with open(recent_transcript, "w") as f:
        f.write(json.dumps(recent_msg) + "\n")
        f.write(json.dumps({
            "type": "assistant",
            "timestamp": "2026-01-09T10:01:00.000Z",
            "sessionId": "recent-session",
            "message": {
                "role": "assistant",
                "usage": {"input_tokens": 100, "output_tokens": 50},
                "content": [{"type": "text", "text": "Response"}]
            }
        }) + "\n")

    # Create old session (modified 48 hours ago)
    old_transcript = project_dir / "old-session.jsonl"
    old_msg = {
        "type": "user",
        "timestamp": "2026-01-07T10:00:00.000Z",
        "sessionId": "old-session",
        "message": {"role": "user", "content": "Old session from 2 days ago"},
    }
    with open(old_transcript, "w") as f:
        f.write(json.dumps(old_msg) + "\n")
        f.write(json.dumps({
            "type": "assistant",
            "timestamp": "2026-01-07T10:01:00.000Z",
            "sessionId": "old-session",
            "message": {
                "role": "assistant",
                "usage": {"input_tokens": 100, "output_tokens": 50},
                "content": [{"type": "text", "text": "Old response"}]
            }
        }) + "\n")

    # Set old file's mtime to 48 hours ago
    old_mtime = time.time() - (48 * 3600)
    os.utime(old_transcript, (old_mtime, old_mtime))

    return claude_home


class TestFastInitialLoad:
    """Test fast initial load that skips old files based on mtime."""

    def test_list_all_sessions_fast_method_exists(self, temp_claude_home):
        """TranscriptReader should have list_all_sessions_fast() method."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home)

        assert hasattr(reader, "list_all_sessions_fast"), (
            "TranscriptReader should have list_all_sessions_fast() method for fast loading. "
            "Add: def list_all_sessions_fast(self, limit: int = 20, max_age_hours: int = 24) -> List[TranscriptSummary]"
        )

    def test_fast_load_skips_old_files(self, temp_claude_home_with_age_variety):
        """list_all_sessions_fast() should skip files older than max_age_hours."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home_with_age_variety)

        # With 24 hour cutoff, should only return recent session
        sessions = reader.list_all_sessions_fast(max_age_hours=24)

        session_ids = [s.session_id for s in sessions]
        assert "recent-session" in session_ids, "Recent session should be included"
        assert "old-session" not in session_ids, (
            "Old session (48h ago) should be skipped when max_age_hours=24"
        )

    def test_fast_load_includes_all_with_large_max_age(self, temp_claude_home_with_age_variety):
        """list_all_sessions_fast() with large max_age should include all files."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home_with_age_variety)

        # With 72 hour cutoff, should return both sessions
        sessions = reader.list_all_sessions_fast(max_age_hours=72)

        session_ids = [s.session_id for s in sessions]
        assert "recent-session" in session_ids, "Recent session should be included"
        assert "old-session" in session_ids, "Old session should be included with 72h cutoff"

    def test_fast_load_respects_limit(self, temp_claude_home):
        """list_all_sessions_fast() should respect the limit parameter."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home)

        # Limit to 1 session
        sessions = reader.list_all_sessions_fast(limit=1, max_age_hours=9999)

        assert len(sessions) <= 1, f"Should return at most 1 session, got {len(sessions)}"

    def test_fast_load_sorts_by_recency(self, temp_claude_home_with_age_variety):
        """list_all_sessions_fast() should return most recent sessions first."""
        from core.tui.transcript_reader import TranscriptReader

        reader = TranscriptReader(claude_home=temp_claude_home_with_age_variety)

        # Get all sessions with large max_age
        sessions = reader.list_all_sessions_fast(max_age_hours=9999)

        if len(sessions) >= 2:
            # First session should have more recent last_activity
            assert sessions[0].last_activity >= sessions[1].last_activity, (
                "Sessions should be sorted by recency (most recent first)"
            )

    def test_fast_load_uses_cache(self, temp_claude_home):
        """list_all_sessions_fast() should use the session cache."""
        from core.tui.transcript_reader import TranscriptReader
        from unittest.mock import patch
        import builtins

        reader = TranscriptReader(claude_home=temp_claude_home)

        # First call - populate cache
        reader.list_all_sessions_fast(max_age_hours=9999)

        # Track file opens
        original_open = builtins.open
        open_calls = []

        def tracking_open(path, *args, **kwargs):
            if str(path).endswith(".jsonl"):
                open_calls.append(path)
            return original_open(path, *args, **kwargs)

        with patch.object(builtins, "open", tracking_open):
            # Second call - should use cache
            reader.list_all_sessions_fast(max_age_hours=9999)

        assert len(open_calls) == 0, f"Expected cache hit, but files were opened: {open_calls}"


# ============================================================================
# get_session_origin_fast() Tests (Optimization Method)
# ============================================================================


class TestGetSessionOriginFast:
    """Test the get_session_origin_fast() optimization method."""

    def test_returns_correct_origin_for_existing_session(self, tmp_path):
        """Should return correct origin for a valid session ID."""
        from core.tui.transcript_reader import TranscriptReader

        claude_home = tmp_path / ".claude"
        project_dir = claude_home / "projects" / "-test"
        project_dir.mkdir(parents=True)

        # Create session with "explore" pattern in first prompt
        session_file = project_dir / "explore-session.jsonl"
        with open(session_file, "w") as f:
            f.write(json.dumps({
                "type": "user",
                "timestamp": "2024-01-01T00:00:00Z",
                "message": {"content": "Explore the codebase"}
            }) + "\n")

        reader = TranscriptReader(claude_home=claude_home)
        assert reader.get_session_origin_fast("explore-session") == "Explore"

    def test_returns_unknown_for_nonexistent_session(self, tmp_path):
        """Should return 'Unknown' for session IDs that don't exist."""
        from core.tui.transcript_reader import TranscriptReader

        claude_home = tmp_path / ".claude"
        project_dir = claude_home / "projects" / "-test"
        project_dir.mkdir(parents=True)

        reader = TranscriptReader(claude_home=claude_home)
        assert reader.get_session_origin_fast("nonexistent-session-id") == "Unknown"

    def test_returns_unknown_for_empty_session_id(self, tmp_path):
        """Should return 'Unknown' for empty session ID."""
        from core.tui.transcript_reader import TranscriptReader

        claude_home = tmp_path / ".claude"
        project_dir = claude_home / "projects" / "-test"
        project_dir.mkdir(parents=True)

        reader = TranscriptReader(claude_home=claude_home)
        assert reader.get_session_origin_fast("") == "Unknown"

    def test_handles_malformed_jsonl(self, tmp_path):
        """Should handle corrupted JSONL files gracefully."""
        from core.tui.transcript_reader import TranscriptReader

        claude_home = tmp_path / ".claude"
        project_dir = claude_home / "projects" / "-test"
        project_dir.mkdir(parents=True)

        corrupt_file = project_dir / "corrupt-session.jsonl"
        corrupt_file.write_text("not valid json\n{broken\n")

        reader = TranscriptReader(claude_home=claude_home)
        assert reader.get_session_origin_fast("corrupt-session") == "Unknown"

    def test_handles_file_with_no_user_messages(self, tmp_path):
        """Should return 'Unknown' if file has no user messages."""
        from core.tui.transcript_reader import TranscriptReader

        claude_home = tmp_path / ".claude"
        project_dir = claude_home / "projects" / "-test"
        project_dir.mkdir(parents=True)

        session_file = project_dir / "no-user-session.jsonl"
        with open(session_file, "w") as f:
            f.write(json.dumps({"type": "assistant", "message": {}}) + "\n")

        reader = TranscriptReader(claude_home=claude_home)
        assert reader.get_session_origin_fast("no-user-session") == "Unknown"

    def test_handles_content_as_list(self, tmp_path):
        """Should handle message content as list (multi-part messages)."""
        from core.tui.transcript_reader import TranscriptReader

        claude_home = tmp_path / ".claude"
        project_dir = claude_home / "projects" / "-test"
        project_dir.mkdir(parents=True)

        session_file = project_dir / "list-content-session.jsonl"
        with open(session_file, "w") as f:
            f.write(json.dumps({
                "type": "user",
                "timestamp": "2024-01-01T00:00:00Z",
                "message": {
                    "content": [
                        {"type": "text", "text": "Explore the codebase"}
                    ]
                }
            }) + "\n")

        reader = TranscriptReader(claude_home=claude_home)
        assert reader.get_session_origin_fast("list-content-session") == "Explore"


# ============================================================================
# get_session_origin_fast() Performance Benchmarks
# ============================================================================


class TestGetSessionOriginFastPerformance:
    """Performance benchmarks for get_session_origin_fast().

    These tests measure actual execution time and warn/fail if performance regresses.
    Thresholds are intentionally generous to avoid flaky CI failures while still
    catching significant regressions.
    """

    def test_lookup_completes_under_100ms(self, tmp_path):
        """Session origin lookup should complete in under 100ms."""
        import time
        import warnings
        from core.tui.transcript_reader import TranscriptReader

        claude_home = tmp_path / ".claude"
        project_dir = claude_home / "projects" / "-test"
        project_dir.mkdir(parents=True)

        # Create a session file
        session_file = project_dir / "perf-test-session.jsonl"
        with open(session_file, "w") as f:
            f.write(json.dumps({
                "type": "user",
                "timestamp": "2024-01-01T00:00:00Z",
                "message": {"content": "Explore the codebase"}
            }) + "\n")

        reader = TranscriptReader(claude_home=claude_home)

        start = time.perf_counter()
        result = reader.get_session_origin_fast("perf-test-session")
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert result == "Explore"  # Sanity check

        # Warn if slow, fail if very slow
        if elapsed_ms > 100:
            warnings.warn(f"get_session_origin_fast took {elapsed_ms:.1f}ms (threshold: 100ms)")
        if elapsed_ms > 1000:
            pytest.fail(f"get_session_origin_fast too slow: {elapsed_ms:.1f}ms (max: 1000ms)")

    def test_nonexistent_session_lookup_fast(self, tmp_path):
        """Looking up nonexistent session should also be fast."""
        import time
        import warnings
        from core.tui.transcript_reader import TranscriptReader

        claude_home = tmp_path / ".claude"
        project_dir = claude_home / "projects" / "-test"
        project_dir.mkdir(parents=True)

        reader = TranscriptReader(claude_home=claude_home)

        start = time.perf_counter()
        result = reader.get_session_origin_fast("nonexistent-session")
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert result == "Unknown"

        if elapsed_ms > 100:
            warnings.warn(f"Nonexistent session lookup took {elapsed_ms:.1f}ms (threshold: 100ms)")
        if elapsed_ms > 1000:
            pytest.fail(f"Nonexistent session lookup too slow: {elapsed_ms:.1f}ms (max: 1000ms)")

    def test_scales_with_multiple_projects(self, tmp_path):
        """Performance should not degrade significantly with many projects."""
        import time
        import warnings
        from core.tui.transcript_reader import TranscriptReader

        claude_home = tmp_path / ".claude"
        projects_dir = claude_home / "projects"

        # Create 20 project directories with sessions
        for i in range(20):
            project_dir = projects_dir / f"-project-{i}"
            project_dir.mkdir(parents=True)
            # Add some sessions to each project
            for j in range(5):
                session_file = project_dir / f"session-{i}-{j}.jsonl"
                with open(session_file, "w") as f:
                    f.write(json.dumps({
                        "type": "user",
                        "timestamp": "2024-01-01T00:00:00Z",
                        "message": {"content": f"User prompt {i}-{j}"}
                    }) + "\n")

        # Add target session in the last project
        target_project = projects_dir / "-project-19"
        target_file = target_project / "target-session.jsonl"
        with open(target_file, "w") as f:
            f.write(json.dumps({
                "type": "user",
                "timestamp": "2024-01-01T00:00:00Z",
                "message": {"content": "Explore the codebase"}
            }) + "\n")

        reader = TranscriptReader(claude_home=claude_home)

        start = time.perf_counter()
        result = reader.get_session_origin_fast("target-session")
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert result == "Explore"

        # With 20 projects and 100 total sessions, should still be fast
        if elapsed_ms > 200:
            warnings.warn(f"Multi-project lookup took {elapsed_ms:.1f}ms (threshold: 200ms)")
        if elapsed_ms > 2000:
            pytest.fail(f"Multi-project lookup too slow: {elapsed_ms:.1f}ms (max: 2000ms)")

    def test_repeated_lookups_are_fast(self, tmp_path):
        """Repeated lookups of same session should be consistently fast."""
        import time
        import warnings
        from core.tui.transcript_reader import TranscriptReader

        claude_home = tmp_path / ".claude"
        project_dir = claude_home / "projects" / "-test"
        project_dir.mkdir(parents=True)

        session_file = project_dir / "repeat-test-session.jsonl"
        with open(session_file, "w") as f:
            f.write(json.dumps({
                "type": "user",
                "timestamp": "2024-01-01T00:00:00Z",
                "message": {"content": "Implement the feature"}
            }) + "\n")

        reader = TranscriptReader(claude_home=claude_home)

        # Warm up with first lookup
        reader.get_session_origin_fast("repeat-test-session")

        # Time 10 repeated lookups
        timings = []
        for _ in range(10):
            start = time.perf_counter()
            result = reader.get_session_origin_fast("repeat-test-session")
            elapsed_ms = (time.perf_counter() - start) * 1000
            timings.append(elapsed_ms)
            assert result == "General"  # Sanity check

        avg_ms = sum(timings) / len(timings)
        max_ms = max(timings)

        # Average should be well under threshold, max should not spike
        if avg_ms > 50:
            warnings.warn(f"Repeated lookup avg: {avg_ms:.1f}ms (threshold: 50ms)")
        if max_ms > 200:
            warnings.warn(f"Repeated lookup max: {max_ms:.1f}ms (threshold: 200ms)")
        if avg_ms > 500:
            pytest.fail(f"Repeated lookups too slow (avg): {avg_ms:.1f}ms (max: 500ms)")

    def test_large_session_file_lookup(self, tmp_path):
        """Lookup should be fast even with larger session files.

        The get_session_origin_fast() method should only read the first few lines
        to find the first user message, not parse the entire file.
        """
        import time
        import warnings
        from core.tui.transcript_reader import TranscriptReader

        claude_home = tmp_path / ".claude"
        project_dir = claude_home / "projects" / "-test"
        project_dir.mkdir(parents=True)

        # Create a session file with many messages (simulating a long session)
        session_file = project_dir / "large-session.jsonl"
        with open(session_file, "w") as f:
            # First message determines origin
            f.write(json.dumps({
                "type": "user",
                "timestamp": "2024-01-01T00:00:00Z",
                "message": {"content": "Plan the implementation approach"}
            }) + "\n")
            # Add 100 more messages to make the file larger
            for i in range(100):
                f.write(json.dumps({
                    "type": "assistant",
                    "timestamp": f"2024-01-01T00:{i:02d}:00Z",
                    "message": {
                        "content": [{"type": "text", "text": f"Response {i} " * 100}],
                        "usage": {"input_tokens": 1000, "output_tokens": 500}
                    }
                }) + "\n")

        reader = TranscriptReader(claude_home=claude_home)

        start = time.perf_counter()
        result = reader.get_session_origin_fast("large-session")
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert result == "Plan"

        # Should still be fast despite large file (only reads first few lines)
        if elapsed_ms > 100:
            warnings.warn(f"Large file lookup took {elapsed_ms:.1f}ms (threshold: 100ms)")
        if elapsed_ms > 1000:
            pytest.fail(f"Large file lookup too slow: {elapsed_ms:.1f}ms (max: 1000ms)")
