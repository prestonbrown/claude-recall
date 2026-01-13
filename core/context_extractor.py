#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Context extraction from transcripts using Haiku.

This module provides functions to extract structured handoff context from
Claude session transcripts. It calls the Haiku API to analyze recent messages
and return a HandoffContext dataclass with summary, critical files, changes, etc.
"""

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class HandoffContext:
    """Context extracted from a session for handoff.

    Attributes:
        summary: 1-2 sentence progress summary - what was accomplished and current state
        critical_files: 2-3 most important file:line refs mentioned
        recent_changes: List of changes made this session
        learnings: Discoveries/patterns found
        blockers: Issues blocking progress
        git_ref: Commit hash at extraction time
    """

    summary: str = ""
    critical_files: List[str] = field(default_factory=list)
    recent_changes: List[str] = field(default_factory=list)
    learnings: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    git_ref: str = ""


@dataclass
class LightweightContext:
    """Lightweight context extracted from transcript without LLM.

    Fast extraction of stats and file info directly from transcript parsing.
    No API calls required.

    Attributes:
        files_touched: Unique files accessed via Read/Edit/Write
        files_modified: Files modified via Edit/Write only
        tool_counts: Dict of tool name -> usage count
        last_user_message: Most recent user message (truncated)
        message_count: Total messages in transcript
    """

    files_touched: List[str] = field(default_factory=list)
    files_modified: List[str] = field(default_factory=list)
    tool_counts: dict = field(default_factory=dict)
    last_user_message: str = ""
    message_count: int = 0


# Maximum messages to include in extraction prompt
MAX_MESSAGES = 20

# Timeout for claude call (seconds)
CLAUDE_TIMEOUT = 30

# Phrases that indicate a garbage summary from Haiku
GARBAGE_SUMMARY_PHRASES = [
    "no conversation occurred",
    "empty session",
    "no content to summarize",
    "nothing to summarize",
    "conversation is empty",
    "no work completed",
]


def _format_tool_use(tool_name: str, tool_input: dict) -> str:
    """Format a tool_use block concisely for context extraction.

    Args:
        tool_name: Name of the tool (Read, Edit, Bash, etc.)
        tool_input: Tool input parameters

    Returns:
        Concise description like "Used Read: file.py" or "Used Bash: git status"
    """
    # Extract the most relevant part of the tool input for context
    if tool_name == "Read":
        file_path = tool_input.get("file_path", "")
        if file_path:
            # Just the filename, not full path
            filename = Path(file_path).name if "/" in file_path else file_path
            return f"[Used Read: {filename}]"
        return "[Used Read]"

    elif tool_name == "Edit":
        file_path = tool_input.get("file_path", "")
        if file_path:
            filename = Path(file_path).name if "/" in file_path else file_path
            return f"[Used Edit: {filename}]"
        return "[Used Edit]"

    elif tool_name == "Write":
        file_path = tool_input.get("file_path", "")
        if file_path:
            filename = Path(file_path).name if "/" in file_path else file_path
            return f"[Used Write: {filename}]"
        return "[Used Write]"

    elif tool_name == "Bash":
        command = tool_input.get("command", "")
        if command:
            # Truncate long commands
            if len(command) > 50:
                command = command[:50] + "..."
            return f"[Used Bash: {command}]"
        return "[Used Bash]"

    elif tool_name == "Glob":
        pattern = tool_input.get("pattern", "")
        if pattern:
            return f"[Used Glob: {pattern}]"
        return "[Used Glob]"

    elif tool_name == "Grep":
        pattern = tool_input.get("pattern", "")
        if pattern:
            return f"[Used Grep: {pattern}]"
        return "[Used Grep]"

    elif tool_name == "Task":
        description = tool_input.get("description", "")
        if description:
            if len(description) > 50:
                description = description[:50] + "..."
            return f"[Used Task: {description}]"
        return "[Used Task]"

    else:
        # Generic format for unknown tools
        return f"[Used {tool_name}]"


def _validate_summary(summary: str) -> bool:
    """Check if a summary is valid or garbage.

    Args:
        summary: The summary text to validate

    Returns:
        True if the summary appears valid, False if it contains garbage phrases
    """
    if not summary or not summary.strip():
        return False

    summary_lower = summary.lower()
    for phrase in GARBAGE_SUMMARY_PHRASES:
        if phrase in summary_lower:
            return False

    return True


def _read_transcript_messages(transcript_path: Path, max_messages: int = MAX_MESSAGES) -> str:
    """Read and format recent messages from a transcript JSONL file.

    Args:
        transcript_path: Path to the transcript JSONL file
        max_messages: Maximum number of messages to include

    Returns:
        Formatted conversation string, or empty string if file not readable
    """
    if not transcript_path.exists():
        return ""

    messages = []
    try:
        with open(transcript_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    entry_type = entry.get("type", "")
                    if entry_type == "user":
                        # User message - extract content
                        content = entry.get("message", {}).get("content", "")
                        if content:
                            messages.append(f"User: {content}")
                    elif entry_type == "assistant":
                        # Assistant message - extract text, tool_use, and thinking content
                        msg_content = entry.get("message", {}).get("content", "")
                        if isinstance(msg_content, str):
                            messages.append(f"Assistant: {msg_content}")
                        elif isinstance(msg_content, list):
                            # Content is array of blocks - extract text, tools, and thinking
                            content_parts = []
                            for block in msg_content:
                                if not isinstance(block, dict):
                                    continue
                                block_type = block.get("type", "")
                                if block_type == "text":
                                    text = block.get("text", "")
                                    if text:
                                        content_parts.append(text)
                                elif block_type == "tool_use":
                                    # Format tool use concisely
                                    tool_name = block.get("name", "unknown")
                                    tool_input = block.get("input", {})
                                    tool_desc = _format_tool_use(tool_name, tool_input)
                                    content_parts.append(tool_desc)
                                elif block_type == "thinking":
                                    # Include thinking content (truncated if long)
                                    thinking = block.get("thinking", "")
                                    if thinking:
                                        # Truncate long thinking blocks
                                        if len(thinking) > 200:
                                            thinking = thinking[:200] + "..."
                                        content_parts.append(f"[Thinking: {thinking}]")
                            if content_parts:
                                messages.append(f"Assistant: {' '.join(content_parts)}")
                except json.JSONDecodeError:
                    continue
    except (OSError, IOError):
        return ""

    # Return last N messages
    return "\n".join(messages[-max_messages:])


def _call_haiku(prompt: str) -> Optional[str]:
    """Call Claude Haiku with a prompt.

    Args:
        prompt: The prompt to send to Haiku

    Returns:
        Response text, or None if call fails
    """
    try:
        # Set environment to prevent recursive hook calls
        env = os.environ.copy()
        env["LESSONS_SCORING_ACTIVE"] = "1"

        result = subprocess.run(
            ["claude", "-p", "--model", "haiku"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=CLAUDE_TIMEOUT,
            env=env,
        )

        if result.returncode != 0:
            return None

        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def _get_git_ref(project_dir: Optional[str] = None) -> str:
    """Get current git commit hash.

    Args:
        project_dir: Project directory (default: from environment or cwd)

    Returns:
        Short commit hash, or empty string if not in git repo
    """
    if project_dir is None:
        project_dir = os.environ.get("PROJECT_DIR", os.getcwd())

    try:
        result = subprocess.run(
            ["git", "-C", project_dir, "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    return ""


def extract_context(transcript_path: str | Path) -> Optional[HandoffContext]:
    """Extract handoff context from a transcript using Haiku.

    Args:
        transcript_path: Path to the transcript JSONL file

    Returns:
        HandoffContext with extracted data, or None if extraction fails
    """
    transcript_path = Path(transcript_path)

    # Read recent messages from transcript
    messages = _read_transcript_messages(transcript_path)
    if not messages or len(messages) < 50:
        return None

    # Build extraction prompt (matches precompact-hook.sh format)
    prompt = """Analyze this conversation and extract a structured handoff context for session continuity.

Return ONLY valid JSON with these fields:
{
  "summary": "1-2 sentence progress summary - what was accomplished and current state",
  "critical_files": ["file.py:42", "other.py:100"],  // 2-3 most important file:line refs mentioned
  "recent_changes": ["Added X", "Fixed Y"],          // list of changes made this session
  "learnings": ["Pattern found", "Gotcha discovered"], // discoveries/patterns found
  "blockers": ["Waiting for Z"]                       // issues blocking progress (empty if none)
}

Important:
- Return ONLY the JSON object, no markdown code blocks, no explanation
- Keep arrays short (2-5 items max)
- Use file:line format for critical_files when line numbers are mentioned
- Leave arrays empty [] if nothing applies

Conversation:
""" + messages

    # Call Haiku for extraction
    response = _call_haiku(prompt)
    if not response:
        return None

    # Strip any markdown code block markers if present
    response = response.strip()
    if response.startswith("```json"):
        response = response[7:]
    if response.startswith("```"):
        response = response[3:]
    if response.endswith("```"):
        response = response[:-3]
    response = response.strip()

    # Parse JSON response
    try:
        data = json.loads(response)
    except json.JSONDecodeError:
        return None

    # Validate summary - reject garbage
    summary = data.get("summary", "")
    if not _validate_summary(summary):
        return None

    # Get git ref
    git_ref = _get_git_ref()

    # Build HandoffContext from parsed data
    return HandoffContext(
        summary=summary,
        critical_files=data.get("critical_files", []),
        recent_changes=data.get("recent_changes", []),
        learnings=data.get("learnings", []),
        blockers=data.get("blockers", []),
        git_ref=git_ref,
    )


def extract_lightweight_context(transcript_path: str | Path) -> Optional[LightweightContext]:
    """Extract lightweight context from transcript without LLM.

    Parses transcript JSONL to extract tool usage stats, files touched,
    and last user message. No API calls - pure file parsing.

    Args:
        transcript_path: Path to the transcript JSONL file

    Returns:
        LightweightContext with stats, or None if file not readable
    """
    transcript_path = Path(transcript_path)
    if not transcript_path.exists():
        return None

    files_touched: set[str] = set()
    files_modified: set[str] = set()
    tool_counts: dict[str, int] = {}
    last_user_message = ""
    message_count = 0

    try:
        with open(transcript_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    entry_type = entry.get("type", "")

                    if entry_type == "user":
                        message_count += 1
                        # Track last user message
                        content = entry.get("message", {}).get("content", "")
                        if isinstance(content, str) and content.strip():
                            last_user_message = content.strip()

                    elif entry_type == "assistant":
                        message_count += 1
                        msg_content = entry.get("message", {}).get("content", [])
                        if isinstance(msg_content, list):
                            for block in msg_content:
                                if not isinstance(block, dict):
                                    continue
                                if block.get("type") == "tool_use":
                                    tool_name = block.get("name", "unknown")
                                    tool_input = block.get("input", {})

                                    # Count tool usage
                                    tool_counts[tool_name] = tool_counts.get(tool_name, 0) + 1

                                    # Extract file paths from file-related tools
                                    file_path = tool_input.get("file_path", "")
                                    if file_path:
                                        # Use just filename for brevity
                                        filename = Path(file_path).name
                                        files_touched.add(filename)
                                        if tool_name in ("Edit", "Write"):
                                            files_modified.add(filename)

                                    # Glob patterns: only add if it's a specific file (no wildcards)
                                    if tool_name == "Glob":
                                        pattern = tool_input.get("pattern", "")
                                        if pattern and "*" not in pattern and "?" not in pattern:
                                            files_touched.add(Path(pattern).name)

                except json.JSONDecodeError:
                    continue

    except (OSError, IOError):
        return None

    # Truncate last user message if too long
    if len(last_user_message) > 100:
        last_user_message = last_user_message[:100] + "..."

    return LightweightContext(
        files_touched=sorted(files_touched)[:15],  # Cap at 15 files
        files_modified=sorted(files_modified)[:10],  # Cap at 10
        tool_counts=tool_counts,
        last_user_message=last_user_message,
        message_count=message_count,
    )
