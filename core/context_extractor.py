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


# Maximum messages to include in extraction prompt
MAX_MESSAGES = 20

# Timeout for claude call (seconds)
CLAUDE_TIMEOUT = 30


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
                        # Assistant message - extract text content
                        msg_content = entry.get("message", {}).get("content", "")
                        if isinstance(msg_content, str):
                            messages.append(f"Assistant: {msg_content}")
                        elif isinstance(msg_content, list):
                            # Content is array of blocks
                            text_parts = []
                            for block in msg_content:
                                if isinstance(block, dict) and block.get("type") == "text":
                                    text_parts.append(block.get("text", ""))
                            if text_parts:
                                messages.append(f"Assistant: {' '.join(text_parts)}")
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

    # Get git ref
    git_ref = _get_git_ref()

    # Build HandoffContext from parsed data
    return HandoffContext(
        summary=data.get("summary", ""),
        critical_files=data.get("critical_files", []),
        recent_changes=data.get("recent_changes", []),
        learnings=data.get("learnings", []),
        blockers=data.get("blockers", []),
        git_ref=git_ref,
    )
