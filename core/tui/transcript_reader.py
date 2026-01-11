#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Transcript reader for Claude session transcripts.

Reads and parses Claude session transcripts from ~/.claude/projects/*/,
providing structured access to session messages, tool usage, and statistics.
"""

import json
import os
import re
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

CITATION_PATTERN = re.compile(r'\[([LS]\d{3})\]')


# System patterns - these are hook/warmup sessions
SYSTEM_PATTERNS = [
    "analyze this conversation",
    "score each lesson's relevance",
    "score the relevance of each lesson",
    "summarize the key points",
]

# User indicators - these are real user sessions
USER_INDICATORS = [
    "<local-command-caveat>",  # This is a user command!
]


def detect_origin(first_prompt: str) -> str:
    """
    Classify session type based on the first prompt pattern.

    Args:
        first_prompt: The first user message content

    Returns:
        One of: "Unknown", "System", "Warmup", "Explore", "Plan", "General", "User"
    """
    # Handle empty/very short prompts
    if not first_prompt or len(first_prompt) < 3:
        return "Unknown"

    # Normalize for case-insensitive matching
    lower_prompt = first_prompt.lower()

    # Check for system patterns first (hook-triggered sessions)
    for pattern in SYSTEM_PATTERNS:
        if pattern in lower_prompt:
            return "System"

    # Check for user indicators (these are real user sessions)
    for indicator in USER_INDICATORS:
        if indicator in first_prompt:
            return "User"

    # Check for warmup sessions (Claude Code pre-warming sub-agents)
    if lower_prompt.startswith("warmup"):
        return "Warmup"

    # Check for Explore patterns
    explore_prefixes = ("explore", "search", "find", "look for", "investigate", "what files")
    if any(lower_prompt.startswith(prefix) for prefix in explore_prefixes):
        return "Explore"
    explore_contains = ("in the codebase", "find where", "locate")
    if any(phrase in lower_prompt for phrase in explore_contains):
        return "Explore"

    # Check for Plan patterns
    plan_prefixes = ("plan", "design", "create a plan", "outline")
    if any(lower_prompt.startswith(prefix) for prefix in plan_prefixes):
        return "Plan"
    plan_contains = ("implementation plan", "approach for")
    if any(phrase in lower_prompt for phrase in plan_contains):
        return "Plan"

    # Check for General patterns
    general_prefixes = ("implement", "fix", "refactor", "review", "update", "add")
    if any(lower_prompt.startswith(prefix) for prefix in general_prefixes):
        return "General"

    # Default to User (natural language, conversational)
    return "User"


@dataclass
class TranscriptMessage:
    """
    A single message from a Claude session transcript.

    Attributes:
        type: Message type ("user" or "assistant")
        timestamp: Message timestamp as datetime
        content: User prompt text or assistant text content
        tools_used: List of tool names used in this message (empty for user)
        token_usage: Output tokens from assistant message usage.output_tokens
    """

    type: str  # "user" | "assistant"
    timestamp: datetime
    content: str  # User prompt text, or text from assistant
    tools_used: List[str] = field(default_factory=list)
    token_usage: Optional[int] = None


@dataclass
class TranscriptSummary:
    """
    Summary of a Claude session transcript.

    Attributes:
        session_id: Session identifier (UUID)
        path: Path to the transcript JSONL file
        project: Project name (last part of encoded path)
        first_prompt: First user message content (truncated to ~200 chars)
        message_count: Total number of user and assistant messages
        tool_breakdown: Dict mapping tool names to usage counts
        input_tokens: Total input tokens from assistant messages
        output_tokens: Total output tokens from assistant messages
        cache_read_tokens: Total cache_read_input_tokens from assistant messages
        cache_creation_tokens: Total cache_creation_input_tokens from assistant messages
        start_time: Timestamp of first message
        last_activity: Timestamp of last message
        lesson_citations: List of lesson IDs cited in the session
        origin: Session type (User, Explore, Plan, General, Unknown)
        parent_session_id: ID of parent session if this is a sub-agent
        child_session_ids: IDs of spawned sub-agents
    """

    session_id: str
    path: Path
    project: str
    first_prompt: str
    message_count: int
    tool_breakdown: Dict[str, int] = field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_activity: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    lesson_citations: List[str] = field(default_factory=list)
    origin: str = "User"
    parent_session_id: Optional[str] = None
    child_session_ids: List[str] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        """Combined token count (input + output) for display."""
        return self.input_tokens + self.output_tokens


def _parse_timestamp(ts_str: str) -> datetime:
    """Parse ISO timestamp string to datetime with timezone."""
    if not ts_str:
        return datetime.now(timezone.utc)
    try:
        # Handle Z suffix for UTC
        ts_str = ts_str.replace("Z", "+00:00")
        return datetime.fromisoformat(ts_str)
    except ValueError:
        return datetime.now(timezone.utc)


def _link_parent_child_sessions(sessions: List[TranscriptSummary]) -> None:
    """
    Link parent and child sessions based on temporal overlap.

    For each non-User session, find User sessions that were active when this
    session started (parent.start_time < child.start_time < parent.last_activity).
    If multiple candidates exist, prefer the most recently started parent.

    Links are bidirectional: child gets parent_session_id set, parent gets
    child added to child_session_ids.

    Args:
        sessions: List of sessions to link (modified in place)
    """
    # Build lookup for quick access
    sessions_by_id = {s.session_id: s for s in sessions}

    # Only User sessions can be parents
    user_sessions = [s for s in sessions if s.origin == "User"]

    # Only non-User sessions can be children
    child_candidates = [s for s in sessions if s.origin != "User"]

    for child in child_candidates:
        # Find all User sessions that were active when this child started
        parent_candidates = []
        for parent in user_sessions:
            if parent.start_time < child.start_time < parent.last_activity:
                parent_candidates.append(parent)

        if not parent_candidates:
            continue

        # Prefer the most recently started parent (closest temporal match)
        best_parent = max(parent_candidates, key=lambda p: p.start_time)

        # Link bidirectionally
        child.parent_session_id = best_parent.session_id
        best_parent.child_session_ids.append(child.session_id)


def _extract_text_content(content) -> str:
    """Extract text content from message content field."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        # Extract text from content array
        texts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                texts.append(item.get("text", ""))
        return "\n".join(texts)
    return ""


def _extract_tools(content) -> List[str]:
    """Extract tool names from assistant message content."""
    if not isinstance(content, list):
        return []
    tools = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "tool_use":
            name = item.get("name")
            if name:
                tools.append(name)
    return tools


class TranscriptReader:
    """
    Reader for Claude session transcripts.

    Reads transcripts from ~/.claude/projects/*/ directories.
    Each project directory is named with an encoded path, and contains
    JSONL files for each session.
    """

    def __init__(self, claude_home: Optional[Path] = None):
        """
        Initialize with claude home directory.

        Args:
            claude_home: Path to Claude home directory (default ~/.claude)
        """
        if claude_home is None:
            claude_home = Path.home() / ".claude"
        self.claude_home = Path(claude_home)
        self.projects_dir = self.claude_home / "projects"
        # Cache for session summaries: path -> (mtime, summary)
        self._session_cache: Dict[Path, Tuple[float, TranscriptSummary]] = {}
        self._cache_lock = threading.Lock()

    def clear_cache(self) -> None:
        """Clear the session summary cache, forcing re-parsing on next access."""
        with self._cache_lock:
            self._session_cache.clear()

    def encode_project_path(self, project_path: str) -> str:
        """
        Encode project path to match Claude's directory naming.

        Converts absolute path to directory name format:
        - /Users/test/code/myproject -> -Users-test-code-myproject
        - /Users/test/.local/state -> -Users-test--local-state

        Args:
            project_path: Absolute project path

        Returns:
            Encoded directory name
        """
        # Replace slashes with dash first, then dots with dash
        # This results in /. becoming -- (one from /, one from .)
        encoded = project_path.replace("/", "-").replace(".", "-")
        # Ensure leading dash
        if encoded.startswith("-"):
            return encoded
        return "-" + encoded

    def get_project_dir(self, project_path: str) -> Path:
        """
        Get the Claude project directory for a given project path.

        Args:
            project_path: Absolute project path

        Returns:
            Path to the Claude project directory
        """
        encoded = self.encode_project_path(project_path)
        return self.projects_dir / encoded

    def _get_project_name(self, encoded_path: str) -> str:
        """Extract project name from encoded path (last component)."""
        # Decode: replace -- back to ., then split by -
        # The last non-empty segment is the project name
        parts = encoded_path.split("-")
        # Filter empty strings and get last part
        non_empty = [p for p in parts if p]
        if non_empty:
            return non_empty[-1]
        return encoded_path

    def _load_session_summary(self, session_path: Path, project_name: str) -> Optional[TranscriptSummary]:
        """Load a session and return its summary, using cache if available."""
        if not session_path.exists():
            return None

        # Check cache with mtime validation
        try:
            current_mtime = session_path.stat().st_mtime
        except OSError:
            return None

        with self._cache_lock:
            if session_path in self._session_cache:
                cached_mtime, cached_summary = self._session_cache[session_path]
                if cached_mtime == current_mtime:
                    return cached_summary

        # Cache miss or stale - parse the file
        session_id = session_path.stem
        first_prompt = ""
        message_count = 0
        tool_breakdown: Dict[str, int] = defaultdict(int)
        input_tokens = 0
        output_tokens = 0
        cache_read_tokens = 0
        cache_creation_tokens = 0
        start_time: Optional[datetime] = None
        last_activity: Optional[datetime] = None
        citations: set = set()

        try:
            with open(session_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    msg_type = data.get("type")
                    if msg_type not in ("user", "assistant"):
                        continue

                    message_count += 1

                    # Parse timestamp
                    ts = _parse_timestamp(data.get("timestamp", ""))
                    if start_time is None:
                        start_time = ts
                    last_activity = ts

                    message = data.get("message", {})

                    if msg_type == "user":
                        # Capture first prompt
                        if not first_prompt:
                            content = message.get("content", "")
                            if isinstance(content, str):
                                first_prompt = content[:200]
                            elif isinstance(content, list):
                                first_prompt = _extract_text_content(content)[:200]

                    elif msg_type == "assistant":
                        # Extract tool usage
                        content = message.get("content", [])
                        for tool in _extract_tools(content):
                            tool_breakdown[tool] += 1

                        # Extract token usage (all types)
                        usage = message.get("usage", {})
                        input_tokens += usage.get("input_tokens", 0)
                        output_tokens += usage.get("output_tokens", 0)
                        cache_read_tokens += usage.get("cache_read_input_tokens", 0)
                        cache_creation_tokens += usage.get("cache_creation_input_tokens", 0)

                        # Extract lesson citations from assistant messages
                        text_content = _extract_text_content(content)
                        found_citations = CITATION_PATTERN.findall(text_content)
                        citations.update(found_citations)

        except OSError:
            return None

        if start_time is None:
            # Use file mtime as fallback for sessions with no user/assistant messages
            start_time = datetime.fromtimestamp(current_mtime, tz=timezone.utc)
        if last_activity is None:
            last_activity = start_time

        summary = TranscriptSummary(
            session_id=session_id,
            path=session_path,
            project=project_name,
            first_prompt=first_prompt,
            message_count=message_count,
            tool_breakdown=dict(tool_breakdown),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_creation_tokens=cache_creation_tokens,
            start_time=start_time,
            last_activity=last_activity,
            lesson_citations=sorted(citations),
            origin=detect_origin(first_prompt),
        )

        # Update cache
        with self._cache_lock:
            self._session_cache[session_path] = (current_mtime, summary)

        return summary

    def list_sessions(
        self, project_path: str, limit: int = 50, include_empty: bool = False
    ) -> List[TranscriptSummary]:
        """
        List sessions for a project, sorted by most recent first.

        Args:
            project_path: Absolute project path
            limit: Maximum number of sessions to return (default 50)
            include_empty: If False (default), filter out sessions with 0 messages

        Returns:
            List of TranscriptSummary objects, empty if project doesn't exist
        """
        project_dir = self.get_project_dir(project_path)
        if not project_dir.exists():
            return []

        project_name = self._get_project_name(project_dir.name)
        sessions = []

        # Find all JSONL files (skip symlinks for security)
        for session_file in project_dir.glob("*.jsonl"):
            if session_file.is_symlink():
                continue
            summary = self._load_session_summary(session_file, project_name)
            if summary:
                # Filter out empty sessions unless include_empty is True
                if include_empty or summary.message_count > 0:
                    sessions.append(summary)

        # Sort by last_activity descending
        sessions.sort(key=lambda s: s.last_activity, reverse=True)

        # Link parent-child relationships before slicing
        _link_parent_child_sessions(sessions)

        return sessions[:limit]

    def list_all_sessions(
        self, limit: int = 50, include_empty: bool = False
    ) -> List[TranscriptSummary]:
        """
        List sessions from ALL projects, sorted by most recent first.

        Args:
            limit: Maximum number of sessions to return (default 50)
            include_empty: If False (default), filter out sessions with 0 messages

        Returns:
            List of TranscriptSummary objects from all projects
        """
        if not self.projects_dir.exists():
            return []

        sessions = []

        # Iterate through all project directories (skip symlinks for security)
        for project_dir in self.projects_dir.iterdir():
            if not project_dir.is_dir() or project_dir.is_symlink():
                continue

            project_name = self._get_project_name(project_dir.name)

            # Find all JSONL files in this project (skip symlinks for security)
            for session_file in project_dir.glob("*.jsonl"):
                if session_file.is_symlink():
                    continue
                summary = self._load_session_summary(session_file, project_name)
                if summary:
                    # Filter out empty sessions unless include_empty is True
                    if include_empty or summary.message_count > 0:
                        sessions.append(summary)

        # Sort by last_activity descending
        sessions.sort(key=lambda s: s.last_activity, reverse=True)

        # Link parent-child relationships before slicing
        _link_parent_child_sessions(sessions)

        return sessions[:limit]

    def list_all_sessions_fast(
        self,
        limit: int = 20,
        max_age_hours: int = 24,
        include_empty: bool = False,
    ) -> List[TranscriptSummary]:
        """
        Fast session listing that only scans recently modified files.

        Uses file mtime to skip files older than max_age_hours, providing
        much faster initial load while still showing recent sessions.

        Args:
            limit: Maximum number of sessions to return (default 20)
            max_age_hours: Only include files modified within this many hours (default 24)
            include_empty: If False (default), filter out sessions with 0 messages

        Returns:
            List of TranscriptSummary objects, sorted by most recent first
        """
        import time

        if not self.projects_dir.exists():
            return []

        sessions = []
        cutoff_time = time.time() - (max_age_hours * 3600)

        for project_dir in self.projects_dir.iterdir():
            if not project_dir.is_dir() or project_dir.is_symlink():
                continue

            project_name = self._get_project_name(project_dir.name)

            for session_file in project_dir.glob("*.jsonl"):
                if session_file.is_symlink():
                    continue

                # Skip old files based on mtime
                try:
                    if session_file.stat().st_mtime < cutoff_time:
                        continue
                except OSError:
                    continue

                summary = self._load_session_summary(session_file, project_name)
                if summary and (include_empty or summary.message_count > 0):
                    sessions.append(summary)

        # Sort by last_activity descending
        sessions.sort(key=lambda s: s.last_activity, reverse=True)

        # Link parent-child relationships before slicing
        _link_parent_child_sessions(sessions)

        return sessions[:limit]

    def get_session_origin_fast(self, session_id: str) -> str:
        """
        Get session origin by direct file lookup.

        O(1) file read instead of O(N) session enumeration.

        Args:
            session_id: The session UUID to look up

        Returns:
            Origin type: "User", "Explore", "Plan", "General", "System", or "Unknown"
        """
        # Glob for the session file across all projects
        pattern = f"*/{session_id}.jsonl"
        matches = list(self.projects_dir.glob(pattern))

        if not matches:
            return "Unknown"

        session_path = matches[0]
        if session_path.is_symlink():
            return "Unknown"

        # Read only enough to get first user prompt
        first_prompt = ""
        try:
            with open(session_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if data.get("type") == "user":
                        content = data.get("message", {}).get("content", "")
                        if isinstance(content, str):
                            first_prompt = content[:200]
                        elif isinstance(content, list):
                            first_prompt = _extract_text_content(content)[:200]
                        break
        except OSError:
            return "Unknown"

        return detect_origin(first_prompt)

    def load_session(
        self, session_path: Path, max_messages: int = 5000
    ) -> List[TranscriptMessage]:
        """
        Load full transcript, returning user and assistant messages.

        Skips file-history-snapshot and other non-message types.

        Args:
            session_path: Path to the session JSONL file
            max_messages: Maximum messages to load (default 5000, prevents OOM)

        Returns:
            List of TranscriptMessage objects in chronological order
        """
        # Security: reject symlinks and paths outside projects directory
        if session_path.is_symlink():
            return []
        try:
            resolved = session_path.resolve()
            if not str(resolved).startswith(str(self.projects_dir.resolve())):
                return []  # Path outside allowed directory
        except (OSError, ValueError):
            return []

        if not session_path.exists():
            return []

        messages = []

        try:
            with open(session_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if len(messages) >= max_messages:
                        break  # Prevent memory exhaustion
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    msg_type = data.get("type")
                    if msg_type not in ("user", "assistant"):
                        continue

                    # Parse timestamp
                    ts = _parse_timestamp(data.get("timestamp", ""))

                    message = data.get("message", {})
                    content_raw = message.get("content", "")

                    if msg_type == "user":
                        content = _extract_text_content(content_raw)
                        messages.append(TranscriptMessage(
                            type="user",
                            timestamp=ts,
                            content=content,
                            tools_used=[],
                            token_usage=None,
                        ))

                    elif msg_type == "assistant":
                        content = _extract_text_content(content_raw)
                        tools = _extract_tools(content_raw)

                        # Extract token usage
                        usage = message.get("usage", {})
                        output_tokens = usage.get("output_tokens")

                        messages.append(TranscriptMessage(
                            type="assistant",
                            timestamp=ts,
                            content=content,
                            tools_used=tools,
                            token_usage=output_tokens,
                        ))

        except OSError:
            return []

        return messages
