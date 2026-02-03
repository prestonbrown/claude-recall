#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
TUI helper functions extracted from handoffs.py and context_extractor.py.

These functions support the TUI's handoff enrichment and context extraction features.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

# Import HandoffContext from models (used by LessonsManager)
try:
    from core.models import HandoffContext
except ImportError:
    from models import HandoffContext


# ============================================================================
# Lightweight Context Extraction (no API calls)
# ============================================================================


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


# ============================================================================
# Handoff Enrichment (uses Haiku API)
# ============================================================================


@dataclass
class EnrichmentResult:
    """Result of enrichment operation.

    Attributes:
        success: True if enrichment completed successfully
        error: Error message if enrichment failed
        context: The extracted HandoffContext, if successful
    """

    success: bool
    error: Optional[str] = None
    context: Optional[HandoffContext] = None


def _get_state_dir() -> Path:
    """Get the state directory path."""
    state_dir = os.environ.get("CLAUDE_RECALL_STATE")
    if state_dir:
        return Path(state_dir)
    return Path.home() / ".local" / "state" / "claude-recall"


def _load_session_handoffs_global(state_dir: Optional[str] = None) -> dict:
    """Load session-handoffs mapping from JSON file."""
    if state_dir:
        file_path = Path(state_dir) / "session-handoffs.json"
    else:
        file_path = _get_state_dir() / "session-handoffs.json"

    if not file_path.exists():
        return {}

    try:
        return json.loads(file_path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def get_transcript_for_handoff(
    handoff_id: str, state_dir: Optional[str] = None
) -> Optional[str]:
    """Find the most recent transcript for a handoff."""
    data = _load_session_handoffs_global(state_dir)

    linked_sessions = []
    for session_id, entry in data.items():
        if isinstance(entry, dict) and handoff_id and entry.get("handoff_id") == handoff_id:
            transcript_path = entry.get("transcript_path")
            created = entry.get("created", "")
            if transcript_path:
                linked_sessions.append((created, transcript_path))

    if not linked_sessions:
        return None

    linked_sessions.sort(key=lambda x: x[0], reverse=True)
    return linked_sessions[0][1]


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


def _validate_summary(summary: str) -> bool:
    """Check if a summary is valid or garbage."""
    if not summary or len(summary.strip()) < 10:
        return False
    summary_lower = summary.lower()
    for phrase in GARBAGE_SUMMARY_PHRASES:
        if phrase in summary_lower:
            return False
    return True


def _format_tool_use(tool_name: str, tool_input: dict) -> str:
    """Format a tool_use block concisely for context extraction."""
    if tool_name == "Read":
        file_path = tool_input.get("file_path", "")
        if file_path:
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
        return f"[Used {tool_name}]"


def _read_transcript_messages(transcript_path: Path, max_messages: int = MAX_MESSAGES) -> str:
    """Read recent messages from transcript file for context extraction."""
    if not transcript_path.exists():
        return ""

    entries = []
    try:
        with open(transcript_path, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except (OSError, IOError):
        return ""

    # Take last N entries
    recent = entries[-max_messages:] if len(entries) > max_messages else entries

    # Format messages for context
    formatted = []
    for entry in recent:
        entry_type = entry.get("type", "")
        if entry_type == "user":
            content = entry.get("message", {}).get("content", "")
            if isinstance(content, str) and content.strip():
                formatted.append(f"User: {content.strip()}")
        elif entry_type == "assistant":
            msg_content = entry.get("message", {}).get("content", [])
            if isinstance(msg_content, list):
                parts = []
                for block in msg_content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            text = block.get("text", "").strip()
                            if text:
                                parts.append(text)
                        elif block.get("type") == "tool_use":
                            tool_name = block.get("name", "unknown")
                            tool_input = block.get("input", {})
                            parts.append(_format_tool_use(tool_name, tool_input))
                if parts:
                    formatted.append(f"Assistant: {' '.join(parts)}")

    return "\n\n".join(formatted)


def _call_haiku(prompt: str) -> Optional[str]:
    """Call Haiku API for context extraction."""
    try:
        import anthropic
        client = anthropic.Anthropic()
        message = client.messages.create(
            model="claude-3-5-haiku-latest",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        if message.content:
            return message.content[0].text
        return None
    except Exception:
        return None


def _get_git_ref() -> str:
    """Get current git commit hash."""
    import subprocess
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ""


@dataclass
class ExtractedContext:
    """Context extracted from transcript via Haiku.

    Used internally before converting to HandoffContext.
    """
    summary: str = ""
    critical_files: List[str] = field(default_factory=list)
    recent_changes: List[str] = field(default_factory=list)
    learnings: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    git_ref: str = ""


def _extract_context(transcript_path: str | Path) -> Optional[ExtractedContext]:
    """Extract handoff context from a transcript using Haiku."""
    transcript_path = Path(transcript_path)

    messages = _read_transcript_messages(transcript_path)
    if not messages or len(messages) < 50:
        return None

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

    response = _call_haiku(prompt)
    if not response:
        return None

    # Strip any markdown code block markers
    response = response.strip()
    if response.startswith("```json"):
        response = response[7:]
    if response.startswith("```"):
        response = response[3:]
    if response.endswith("```"):
        response = response[:-3]
    response = response.strip()

    try:
        data = json.loads(response)
    except json.JSONDecodeError:
        return None

    summary = data.get("summary", "")
    if not _validate_summary(summary):
        return None

    git_ref = _get_git_ref()

    return ExtractedContext(
        summary=summary,
        critical_files=data.get("critical_files", []),
        recent_changes=data.get("recent_changes", []),
        learnings=data.get("learnings", []),
        blockers=data.get("blockers", []),
        git_ref=git_ref,
    )


def enrich_handoff(
    handoff_id: str,
    state_dir: Optional[str] = None,
    project_dir: Optional[str] = None,
) -> EnrichmentResult:
    """Enrich a handoff by extracting context from its transcript.

    Args:
        handoff_id: The handoff ID to enrich
        state_dir: State directory (default: from environment)
        project_dir: Project directory (default: from environment)

    Returns:
        EnrichmentResult with success/error status
    """
    # Validate handoff_id format
    if not handoff_id or not handoff_id.startswith("hf-"):
        return EnrichmentResult(
            success=False,
            error=f"Invalid handoff ID format: {handoff_id}",
        )

    # Find transcript for handoff
    transcript_path = get_transcript_for_handoff(handoff_id, state_dir)
    if not transcript_path:
        return EnrichmentResult(
            success=False,
            error=f"No transcript found for handoff {handoff_id}",
        )

    # Verify transcript exists
    if not Path(transcript_path).exists():
        return EnrichmentResult(
            success=False,
            error=f"Transcript file not found: {transcript_path}",
        )

    # Extract context from transcript
    context = _extract_context(transcript_path)
    if context is None:
        return EnrichmentResult(
            success=False,
            error="Failed to extract context from transcript",
        )

    # Update handoff with extracted context
    try:
        from core.manager import LessonsManager
    except ImportError:
        from manager import LessonsManager

    # Get lessons base directory
    base_path = (
        os.environ.get("CLAUDE_RECALL_BASE")
        or os.environ.get("RECALL_BASE")
        or os.environ.get("LESSONS_BASE")
    )
    lessons_base = Path(base_path) if base_path else Path.home() / ".config" / "claude-recall"

    # Get project root from environment or parameter
    if project_dir:
        project_root = Path(project_dir)
    else:
        project_dir_env = os.environ.get("PROJECT_DIR")
        if project_dir_env:
            project_root = Path(project_dir_env)
        else:
            project_root = Path.cwd()
            while project_root != project_root.parent:
                if (project_root / ".git").exists():
                    break
                project_root = project_root.parent
            else:
                project_root = Path.cwd()

    try:
        mgr = LessonsManager(lessons_base, project_root)

        # Convert extracted context to HandoffContext from models
        handoff_context = HandoffContext(
            summary=context.summary,
            critical_files=context.critical_files,
            recent_changes=context.recent_changes,
            learnings=context.learnings,
            blockers=context.blockers,
            git_ref=context.git_ref,
        )

        # Update handoff with context
        mgr.handoff_update_context(handoff_id, handoff_context)

        return EnrichmentResult(
            success=True,
            context=handoff_context,
        )
    except Exception as e:
        return EnrichmentResult(
            success=False,
            error=f"Failed to update handoff: {str(e)}",
        )
