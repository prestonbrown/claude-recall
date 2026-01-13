#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Handoffs mixin for the LessonsManager class.

This module contains all handoff-related methods as a mixin class.
Handoffs track multi-step work across sessions (formerly called "approaches").
"""

import hashlib
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

# Handle both module import and direct script execution
try:
    from core.debug_logger import get_logger
    from core.file_lock import FileLock
    from core.paths import PathResolver
    from core.models import (
        # Constants
        HANDOFF_MAX_COMPLETED,
        HANDOFF_MAX_AGE_DAYS,
        HANDOFF_STALE_DAYS,
        HANDOFF_COMPLETED_ARCHIVE_DAYS,
        HANDOFF_ORPHAN_DAYS,
        # Dataclasses
        TriedStep,
        Handoff,
        HandoffContext,
        HandoffCompleteResult,
        ValidationResult,
        HandoffResumeResult,
        # ============================================================
        # DEPRECATED ALIASES (remove after 2025-06-01)
        # These exist for backward compatibility with external code
        # ============================================================
        TriedApproach,
        Approach,
        ApproachCompleteResult,
        APPROACH_MAX_COMPLETED,
        APPROACH_MAX_AGE_DAYS,
        APPROACH_STALE_DAYS,
        APPROACH_COMPLETED_ARCHIVE_DAYS,
    )
except ImportError:
    from debug_logger import get_logger
    from file_lock import FileLock
    from paths import PathResolver
    from models import (
        # Constants
        HANDOFF_MAX_COMPLETED,
        HANDOFF_MAX_AGE_DAYS,
        HANDOFF_STALE_DAYS,
        HANDOFF_COMPLETED_ARCHIVE_DAYS,
        HANDOFF_ORPHAN_DAYS,
        # Dataclasses
        TriedStep,
        Handoff,
        HandoffContext,
        HandoffCompleteResult,
        ValidationResult,
        HandoffResumeResult,
        # ============================================================
        # DEPRECATED ALIASES (remove after 2025-06-01)
        # These exist for backward compatibility with external code
        # ============================================================
        TriedApproach,
        Approach,
        ApproachCompleteResult,
        APPROACH_MAX_COMPLETED,
        APPROACH_MAX_AGE_DAYS,
        APPROACH_STALE_DAYS,
        APPROACH_COMPLETED_ARCHIVE_DAYS,
    )


def _validate_ref(ref: str) -> bool:
    """
    Validate file:line or file:start-end reference format.

    Valid formats:
    - path/to/file.py:42        (single line)
    - path/to/file.py:50-75     (line range)

    Args:
        ref: Reference string to validate

    Returns:
        True if valid format, False otherwise
    """
    # Pattern: path:line or path:start-end
    # Path must have at least one character, line must be digits, optional -end
    pattern = r'^[^\s:]+:\d+(-\d+)?$'
    return bool(re.match(pattern, ref))


# ============================================================================
# Enrichment Types and Functions
# ============================================================================

from dataclasses import dataclass
import os
import json as json_mod


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
    """Get the state directory path.

    Returns:
        Path to state directory (from env or default)
    """
    state_dir = os.environ.get("CLAUDE_RECALL_STATE")
    if state_dir:
        return Path(state_dir)
    return Path.home() / ".local" / "state" / "claude-recall"


def _load_session_handoffs_global(state_dir: Optional[str] = None) -> dict:
    """Load session-handoffs mapping from JSON file.

    Args:
        state_dir: State directory path (default: from environment)

    Returns:
        Dict mapping session_id -> session data
    """
    if state_dir:
        file_path = Path(state_dir) / "session-handoffs.json"
    else:
        file_path = _get_state_dir() / "session-handoffs.json"

    if not file_path.exists():
        return {}

    try:
        return json_mod.loads(file_path.read_text())
    except (json_mod.JSONDecodeError, OSError):
        return {}


def get_transcript_for_handoff(
    handoff_id: str, state_dir: Optional[str] = None
) -> Optional[str]:
    """Find the most recent transcript for a handoff.

    Looks up session-handoffs.json to find linked transcripts.

    Args:
        handoff_id: The handoff ID (e.g., 'hf-abc1234')
        state_dir: State directory (default: from environment)

    Returns:
        Path to transcript, or None if not found
    """
    data = _load_session_handoffs_global(state_dir)

    # Find all sessions linked to this handoff
    linked_sessions = []
    for session_id, entry in data.items():
        if isinstance(entry, dict) and handoff_id and entry.get("handoff_id") == handoff_id:
            transcript_path = entry.get("transcript_path")
            created = entry.get("created", "")
            if transcript_path:
                linked_sessions.append((created, transcript_path))

    if not linked_sessions:
        return None

    # Sort by created time (most recent first) and return the most recent transcript
    linked_sessions.sort(key=lambda x: x[0], reverse=True)
    return linked_sessions[0][1]


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

    # Import extract_context lazily to avoid circular imports
    try:
        from core.context_extractor import extract_context
    except ImportError:
        # For installed flat package, add parent dir to path
        import sys
        _parent = str(Path(__file__).parent)
        if _parent not in sys.path:
            sys.path.insert(0, _parent)
        from context_extractor import extract_context

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
    context = extract_context(transcript_path)
    if context is None:
        return EnrichmentResult(
            success=False,
            error="Failed to extract context from transcript",
        )

    # Update handoff with extracted context
    # Import LessonsManager lazily to avoid circular imports
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


class HandoffsMixin:
    """
    Mixin containing handoff-related methods.

    This mixin expects the following attributes to be set on the class:
    - self.project_root: Path to project root
    """

    # Valid status and outcome values
    VALID_STATUSES = {"not_started", "in_progress", "blocked", "ready_for_review", "completed"}
    VALID_OUTCOMES = {"success", "fail", "partial"}
    VALID_PHASES = {"research", "planning", "implementing", "review"}
    VALID_AGENTS = {"explore", "general-purpose", "plan", "review", "user"}

    # -------------------------------------------------------------------------
    # Handoffs Tracking
    # -------------------------------------------------------------------------

    def _get_project_data_dir(self) -> Path:
        """Get the project data directory, preferring .claude-recall/ over legacy paths.

        Checks for directories in order of precedence:
        .claude-recall/ → .recall/ → .coding-agent-lessons/ → default (.claude-recall/)
        """
        return PathResolver.project_data_dir(self.project_root)

    @property
    def project_handoffs_file(self) -> Path:
        """Path to the project handoffs file."""
        data_dir = self._get_project_data_dir()
        # Check for new name first
        new_path = data_dir / "HANDOFFS.md"
        old_path = data_dir / "APPROACHES.md"
        if new_path.exists():
            return new_path
        elif old_path.exists():
            return old_path
        else:
            # Default to new name for new files in .claude-recall/
            return self.project_root / ".claude-recall" / "HANDOFFS.md"

    @property
    def project_handoffs_archive(self) -> Path:
        """Path to the project handoffs archive file."""
        data_dir = self._get_project_data_dir()
        # Check for new name first
        new_path = data_dir / "HANDOFFS_ARCHIVE.md"
        old_path = data_dir / "APPROACHES_ARCHIVE.md"
        if new_path.exists():
            return new_path
        elif old_path.exists():
            return old_path
        else:
            # Default to new name for new files in .claude-recall/
            return self.project_root / ".claude-recall" / "HANDOFFS_ARCHIVE.md"

    @property
    def project_stealth_handoffs_file(self) -> Path:
        """Path to the stealth/local handoffs file (not committed to git)."""
        data_dir = self._get_project_data_dir()
        return data_dir / "HANDOFFS_LOCAL.md"

    @property
    def project_stealth_handoffs_archive(self) -> Path:
        """Path to the stealth/local handoffs archive file (not committed to git)."""
        data_dir = self._get_project_data_dir()
        return data_dir / "HANDOFFS_LOCAL_ARCHIVE.md"

    def _init_handoffs_file(self) -> None:
        """Initialize handoffs file with standard header if it doesn't exist.

        Creates parent directories as needed. File header includes the H1 title.
        """
        file_path = self.project_handoffs_file
        file_path.parent.mkdir(parents=True, exist_ok=True)

        if file_path.exists():
            return

        header = """# HANDOFFS.md - Active Work Tracking

> Track ongoing work with tried steps and next steps.
> When completed, review for lessons to extract.

## Active Handoffs

"""
        file_path.write_text(header)

    def _init_stealth_handoffs_file(self) -> None:
        """Initialize stealth handoffs file with header if it doesn't exist."""
        file_path = self.project_stealth_handoffs_file
        file_path.parent.mkdir(parents=True, exist_ok=True)

        if file_path.exists():
            return

        header = """# HANDOFFS_LOCAL.md - Local/Stealth Work Tracking

> Local-only handoffs not committed to git.
> For personal work on shared repos.

## Active Handoffs

"""
        file_path.write_text(header)

    def _parse_handoffs_file(self, file_path: Path, stealth: bool = False) -> List[Handoff]:
        """Parse all handoffs from a file.

        Args:
            file_path: Path to the handoffs markdown file
            stealth: If True, mark all parsed handoffs as stealth=True
        """
        if not file_path.exists():
            return []

        content = file_path.read_text()
        if not content.strip():
            return []

        handoffs = []
        lines = content.split("\n")

        # Pattern for handoff header: ### [A001] Title or ### [hf-a1b2c3d] Title
        # Matches both legacy A### format and new hf-XXXXXXX format
        header_pattern = re.compile(r"^###\s*\[([A-Z]\d{3}|hf-[0-9a-f]{7})\]\s*(.+)$")
        # New format status line: - **Status**: status | **Phase**: phase | **Agent**: agent
        status_pattern_new = re.compile(
            r"^\s*-\s*\*\*Status\*\*:\s*(\w+)"
            r"\s*\|\s*\*\*Phase\*\*:\s*([\w-]+)"
            r"\s*\|\s*\*\*Agent\*\*:\s*([\w-]+)"
        )
        # Old format status line: - **Status**: status | **Created**: date | **Updated**: date
        status_pattern_old = re.compile(
            r"^\s*-\s*\*\*Status\*\*:\s*(\w+)"
            r"\s*\|\s*\*\*Created\*\*:\s*(\d{4}-\d{2}-\d{2})"
            r"\s*\|\s*\*\*Updated\*\*:\s*(\d{4}-\d{2}-\d{2})"
        )
        # Pattern for dates line: - **Created**: date | **Updated**: date
        dates_pattern = re.compile(
            r"^\s*-\s*\*\*Created\*\*:\s*(\d{4}-\d{2}-\d{2})"
            r"\s*\|\s*\*\*Updated\*\*:\s*(\d{4}-\d{2}-\d{2})"
        )
        # Pattern for refs line: - **Refs**: file:line | file:line (new format, pipe-separated)
        refs_pattern = re.compile(r"^\s*-\s*\*\*Refs\*\*:\s*(.*)$")
        # Pattern for files line: - **Files**: file1, file2 (legacy format, comma-separated)
        files_pattern = re.compile(r"^\s*-\s*\*\*Files\*\*:\s*(.*)$")
        # Pattern for description line: - **Description**: desc
        desc_pattern = re.compile(r"^\s*-\s*\*\*Description\*\*:\s*(.*)$")
        # Pattern for tried item: N. [outcome] description
        tried_pattern = re.compile(r"^\s*\d+\.\s*\[(\w+)\]\s*(.+)$")

        idx = 0
        while idx < len(lines):
            header_match = header_pattern.match(lines[idx])
            if not header_match:
                idx += 1
                continue

            handoff_id = header_match.group(1)
            title = header_match.group(2).strip()
            idx += 1

            # Parse status line - try new format first, then old format
            if idx >= len(lines):
                continue

            status = None
            phase = "research"  # default
            agent = "user"  # default
            created = None
            updated = None

            status_match_new = status_pattern_new.match(lines[idx])
            status_match_old = status_pattern_old.match(lines[idx])

            if status_match_new:
                # New format: status, phase, agent on first line
                status = status_match_new.group(1)
                phase = status_match_new.group(2)
                agent = status_match_new.group(3)
                idx += 1

                # Parse dates from next line
                if idx < len(lines):
                    dates_match = dates_pattern.match(lines[idx])
                    if dates_match:
                        try:
                            created = date.fromisoformat(dates_match.group(1))
                            updated = date.fromisoformat(dates_match.group(2))
                        except ValueError:
                            continue
                        idx += 1
                    else:
                        # Malformed - skip
                        continue
                else:
                    continue
            elif status_match_old:
                # Old format: status, created, updated on same line
                status = status_match_old.group(1)
                try:
                    created = date.fromisoformat(status_match_old.group(2))
                    updated = date.fromisoformat(status_match_old.group(3))
                except ValueError:
                    continue
                idx += 1
            else:
                # Malformed - skip this handoff
                continue

            # Parse refs/files line - try new Refs format first, then legacy Files format
            refs = []
            if idx < len(lines):
                refs_match = refs_pattern.match(lines[idx])
                files_match = files_pattern.match(lines[idx])
                if refs_match:
                    # New format: pipe-separated refs
                    refs_str = refs_match.group(1).strip()
                    if refs_str:
                        refs = [r.strip() for r in refs_str.split("|") if r.strip()]
                    idx += 1
                elif files_match:
                    # Legacy format: comma-separated files
                    files_str = files_match.group(1).strip()
                    if files_str:
                        refs = [f.strip() for f in files_str.split(",") if f.strip()]
                    idx += 1

            # Parse description line
            description = ""
            if idx < len(lines):
                desc_match = desc_pattern.match(lines[idx])
                if desc_match:
                    description = desc_match.group(1).strip()
                    idx += 1

            # Parse checkpoint line (optional)
            checkpoint = ""
            checkpoint_pattern = re.compile(r"^\s*-\s*\*\*Checkpoint\*\*:\s*(.*)$")
            if idx < len(lines):
                checkpoint_match = checkpoint_pattern.match(lines[idx])
                if checkpoint_match:
                    checkpoint = checkpoint_match.group(1).strip()
                    idx += 1

            # Parse last session line (optional)
            last_session = None
            last_session_pattern = re.compile(r"^\s*-\s*\*\*Last Session\*\*:\s*(\d{4}-\d{2}-\d{2})$")
            if idx < len(lines):
                last_session_match = last_session_pattern.match(lines[idx])
                if last_session_match:
                    try:
                        last_session = date.fromisoformat(last_session_match.group(1))
                    except ValueError:
                        pass
                    idx += 1

            # Parse HandoffContext (new format with structured context)
            handoff_context = None
            handoff_pattern = re.compile(r"^\s*-\s*\*\*Handoff\*\*\s*\(([^)]+)\):\s*$")
            if idx < len(lines):
                handoff_match = handoff_pattern.match(lines[idx])
                if handoff_match:
                    git_ref = handoff_match.group(1).strip()
                    idx += 1
                    # Parse sub-fields
                    context_summary = ""
                    context_refs = []
                    context_changes = []
                    context_learnings = []
                    context_blockers = []

                    while idx < len(lines):
                        line = lines[idx].strip()
                        if not line.startswith("- "):
                            break
                        # Check for sub-items (indented with "  - ")
                        if line.startswith("- Summary:"):
                            context_summary = line[len("- Summary:"):].strip()
                        elif line.startswith("- Refs:"):
                            refs_str = line[len("- Refs:"):].strip()
                            if refs_str:
                                context_refs = [r.strip() for r in refs_str.split("|") if r.strip()]
                        elif line.startswith("- Changes:"):
                            changes_str = line[len("- Changes:"):].strip()
                            if changes_str:
                                context_changes = [c.strip() for c in changes_str.split("|") if c.strip()]
                        elif line.startswith("- Learnings:"):
                            learnings_str = line[len("- Learnings:"):].strip()
                            if learnings_str:
                                context_learnings = [l.strip() for l in learnings_str.split("|") if l.strip()]
                        elif line.startswith("- Blockers:"):
                            blockers_str = line[len("- Blockers:"):].strip()
                            if blockers_str:
                                context_blockers = [b.strip() for b in blockers_str.split("|") if b.strip()]
                        else:
                            break
                        idx += 1

                    if context_summary or context_refs or context_changes or context_learnings or context_blockers:
                        handoff_context = HandoffContext(
                            summary=context_summary,
                            critical_files=context_refs,
                            recent_changes=context_changes,
                            learnings=context_learnings,
                            blockers=context_blockers,
                            git_ref=git_ref,
                        )

            # Parse blocked_by field (optional)
            blocked_by = []
            blocked_by_pattern = re.compile(r"^\s*-\s*\*\*Blocked By\*\*:\s*(.*)$")
            if idx < len(lines):
                blocked_by_match = blocked_by_pattern.match(lines[idx])
                if blocked_by_match:
                    blocked_str = blocked_by_match.group(1).strip()
                    if blocked_str:
                        blocked_by = [b.strip() for b in blocked_str.split(",") if b.strip()]
                    idx += 1

            # Parse sessions field (optional)
            sessions = []
            sessions_pattern = re.compile(r"^\s*-\s*\*\*Sessions\*\*:\s*(.*)$")
            if idx < len(lines):
                sessions_match = sessions_pattern.match(lines[idx])
                if sessions_match:
                    sessions_str = sessions_match.group(1).strip()
                    if sessions_str:
                        sessions = [s.strip() for s in sessions_str.split(",") if s.strip()]
                    idx += 1

            # Parse tried section
            tried = []
            # Look for **Tried**: header
            while idx < len(lines) and not lines[idx].strip().startswith("**Tried**"):
                idx += 1
            if idx < len(lines) and "**Tried**:" in lines[idx]:
                idx += 1
                while idx < len(lines):
                    line = lines[idx].strip()
                    if not line or line.startswith("**Next**:") or line == "---":
                        break
                    tried_match = tried_pattern.match(lines[idx])
                    if tried_match:
                        tried.append(TriedStep(
                            outcome=tried_match.group(1),
                            description=tried_match.group(2).strip()
                        ))
                    idx += 1

            # Parse next steps
            next_steps = ""
            while idx < len(lines) and not lines[idx].strip().startswith("**Next**"):
                idx += 1
            if idx < len(lines) and "**Next**:" in lines[idx]:
                # Extract text after **Next**:
                next_match = re.match(r"^\*\*Next\*\*:\s*(.*)$", lines[idx].strip())
                if next_match:
                    next_steps = next_match.group(1).strip()
                idx += 1

            # Skip to separator or next handoff
            while idx < len(lines) and lines[idx].strip() != "---":
                idx += 1
            idx += 1  # Skip the separator

            handoffs.append(Handoff(
                id=handoff_id,
                title=title,
                status=status,
                created=created,
                updated=updated,
                refs=refs,
                description=description,
                tried=tried,
                next_steps=next_steps,
                phase=phase,
                agent=agent,
                checkpoint=checkpoint,
                last_session=last_session,
                handoff=handoff_context,
                blocked_by=blocked_by,
                stealth=stealth,
                sessions=sessions,
            ))

        return handoffs

    def _format_handoff(self, handoff: Handoff) -> str:
        """Format a handoff for markdown storage."""
        lines = [
            f"### [{handoff.id}] {handoff.title}",
            f"- **Status**: {handoff.status} | **Phase**: {handoff.phase} | **Agent**: {handoff.agent}",
            f"- **Created**: {handoff.created.isoformat()} | **Updated**: {handoff.updated.isoformat()}",
            f"- **Refs**: {' | '.join(handoff.refs)}",
            f"- **Description**: {handoff.description}",
        ]

        # Add checkpoint if present (legacy format, kept for backward compatibility)
        if handoff.checkpoint:
            session_str = handoff.last_session.isoformat() if handoff.last_session else ""
            lines.append(f"- **Checkpoint**: {handoff.checkpoint}")
            if session_str:
                lines.append(f"- **Last Session**: {session_str}")

        # Add HandoffContext if present (new format)
        if handoff.handoff is not None:
            ctx = handoff.handoff
            lines.append(f"- **Handoff** ({ctx.git_ref}):")
            lines.append(f"  - Summary: {ctx.summary}")
            if ctx.critical_files:
                lines.append(f"  - Refs: {' | '.join(ctx.critical_files)}")
            if ctx.recent_changes:
                lines.append(f"  - Changes: {' | '.join(ctx.recent_changes)}")
            if ctx.learnings:
                lines.append(f"  - Learnings: {' | '.join(ctx.learnings)}")
            if ctx.blockers:
                lines.append(f"  - Blockers: {' | '.join(ctx.blockers)}")

        # Add blocked_by if present
        if handoff.blocked_by:
            lines.append(f"- **Blocked By**: {', '.join(handoff.blocked_by)}")

        # Add sessions if present
        if handoff.sessions:
            lines.append(f"- **Sessions**: {', '.join(handoff.sessions)}")

        lines.append("")

        lines.append("**Tried**:")
        for i, tried in enumerate(handoff.tried, 1):
            lines.append(f"{i}. [{tried.outcome}] {tried.description}")

        lines.append("")
        lines.append(f"**Next**: {handoff.next_steps}")
        lines.append("")
        lines.append("---")

        return "\n".join(lines)

    def _write_handoffs_file(self, handoffs: List[Handoff]) -> None:
        """Write handoffs back to file."""
        self._init_handoffs_file()

        header = """# HANDOFFS.md - Active Work Tracking

> Track ongoing work with tried steps and next steps.
> When completed, review for lessons to extract.

## Active Handoffs

"""
        parts = [header]
        for handoff in handoffs:
            parts.append(self._format_handoff(handoff))
            parts.append("")

        self.project_handoffs_file.write_text("\n".join(parts))

    def _write_stealth_handoffs_file(self, handoffs: List[Handoff]) -> None:
        """Write stealth handoffs back to local file."""
        self._init_stealth_handoffs_file()

        header = """# HANDOFFS_LOCAL.md - Local/Stealth Work Tracking

> Local-only handoffs not committed to git.
> For personal work on shared repos.

## Active Handoffs

"""
        parts = [header]
        for handoff in handoffs:
            parts.append(self._format_handoff(handoff))
            parts.append("")

        self.project_stealth_handoffs_file.write_text("\n".join(parts))

    def _generate_handoff_id(self, title: str) -> str:
        """Generate hash-based ID like hf-a1b2c3d for multi-agent safety."""
        seed = f"{title}:{datetime.now().isoformat()}"
        hash_hex = hashlib.sha256(seed.encode()).hexdigest()[:7]
        return f"hf-{hash_hex}"

    def _find_active_handoff_by_title(
        self, title: str, stealth: bool = False
    ) -> Optional[Handoff]:
        """
        Find an active (non-completed) handoff with the same title.

        Used for duplicate detection - if a handoff with the same title
        already exists and is not completed, return it instead of creating
        a new one.

        Args:
            title: The title to search for (case-insensitive)
            stealth: Whether to search stealth handoffs

        Returns:
            The existing handoff if found, None otherwise
        """
        title_lower = title.lower().strip()

        # Check the appropriate file based on stealth flag
        if stealth:
            if not self.project_stealth_handoffs_file.exists():
                return None
            handoffs = self._parse_handoffs_file(
                self.project_stealth_handoffs_file, stealth=True
            )
        else:
            if not self.project_handoffs_file.exists():
                return None
            handoffs = self._parse_handoffs_file(self.project_handoffs_file)

        for h in handoffs:
            if h.status != "completed" and h.title.lower().strip() == title_lower:
                return h

        return None

    def _get_next_handoff_id(self) -> str:
        """Get the next available handoff ID (legacy sequential format)."""
        max_id = 0

        # Check main file
        if self.project_handoffs_file.exists():
            handoffs = self._parse_handoffs_file(self.project_handoffs_file)
            for handoff in handoffs:
                try:
                    num = int(handoff.id[1:])
                    max_id = max(max_id, num)
                except ValueError:
                    pass

        # Also check archive to prevent ID reuse
        if self.project_handoffs_archive.exists():
            content = self.project_handoffs_archive.read_text()
            for match in re.finditer(r"\[A(\d{3})\]", content):
                try:
                    num = int(match.group(1))
                    max_id = max(max_id, num)
                except ValueError:
                    pass

        return f"A{max_id + 1:03d}"

    def handoff_add(
        self,
        title: str,
        desc: Optional[str] = None,
        files: Optional[List[str]] = None,
        refs: Optional[List[str]] = None,
        phase: str = "research",
        agent: str = "user",
        stealth: bool = False,
    ) -> str:
        """
        Add a new handoff.

        Args:
            title: Handoff title
            desc: Optional description
            files: Optional list of files (deprecated, use refs)
            refs: Optional list of file:line refs (e.g., ["core/main.py:50"])
            phase: Initial phase (research, planning, implementing, review)
            agent: Agent working on this (explore, general-purpose, plan, review, user)
            stealth: If True, store in HANDOFFS_LOCAL.md (not committed to git)

        Returns:
            The assigned handoff ID (e.g., 'hf-a1b2c3d')

        Raises:
            ValueError: If invalid phase or agent
        """
        if phase not in self.VALID_PHASES:
            raise ValueError(f"Invalid phase: {phase}")
        if agent not in self.VALID_AGENTS:
            raise ValueError(f"Invalid agent: {agent}")

        # Check for duplicate - return existing handoff if active one with same title exists
        existing = self._find_active_handoff_by_title(title, stealth)
        if existing:
            return existing.id

        # refs takes precedence, files is for backward compat
        ref_list = refs if refs is not None else (files or [])

        handoff_id = self._generate_handoff_id(title)
        today = date.today()

        handoff = Handoff(
            id=handoff_id,
            title=title,
            status="not_started",
            created=today,
            updated=today,
            refs=ref_list,
            description=desc or "",
            tried=[],
            next_steps="",
            phase=phase,
            agent=agent,
            stealth=stealth,
        )

        if stealth:
            self._init_stealth_handoffs_file()
            with FileLock(self.project_stealth_handoffs_file):
                handoffs = self._parse_handoffs_file(self.project_stealth_handoffs_file, stealth=True)
                handoffs.append(handoff)
                self._write_stealth_handoffs_file(handoffs)
        else:
            self._init_handoffs_file()
            with FileLock(self.project_handoffs_file):
                handoffs = self._parse_handoffs_file(self.project_handoffs_file)
                handoffs.append(handoff)
                self._write_handoffs_file(handoffs)

        # Log handoff created
        logger = get_logger()
        logger.handoff_created(
            handoff_id=handoff_id,
            title=title,
            phase=phase,
            agent=agent,
        )

        return handoff_id

    def _load_all_handoffs(self) -> List[Handoff]:
        """Load all handoffs from both regular and stealth files."""
        handoffs = []
        if self.project_handoffs_file.exists():
            handoffs.extend(self._parse_handoffs_file(self.project_handoffs_file, stealth=False))
        if self.project_stealth_handoffs_file.exists():
            handoffs.extend(self._parse_handoffs_file(self.project_stealth_handoffs_file, stealth=True))
        return handoffs

    def _find_handoff_file(self, handoff_id: str) -> Optional[Path]:
        """
        Find which file contains a handoff by ID.

        Args:
            handoff_id: The handoff ID to search for

        Returns:
            Path to the file containing the handoff, or None if not found
        """
        # Check regular file first
        if self.project_handoffs_file.exists():
            handoffs = self._parse_handoffs_file(self.project_handoffs_file)
            for h in handoffs:
                if h.id == handoff_id:
                    return self.project_handoffs_file

        # Check stealth file
        if self.project_stealth_handoffs_file.exists():
            handoffs = self._parse_handoffs_file(self.project_stealth_handoffs_file, stealth=True)
            for h in handoffs:
                if h.id == handoff_id:
                    return self.project_stealth_handoffs_file

        return None

    def _is_stealth_handoff(self, handoff_id: str) -> bool:
        """Check if a handoff ID belongs to a stealth handoff."""
        file_path = self._find_handoff_file(handoff_id)
        return file_path == self.project_stealth_handoffs_file if file_path else False

    def _update_handoff_in_file(
        self,
        handoff_id: str,
        update_fn,
    ) -> Optional[Handoff]:
        """
        Generic helper to update a handoff in whichever file it's stored.

        Args:
            handoff_id: The handoff ID to update
            update_fn: Callable that takes a Handoff and modifies it in place

        Returns:
            The updated Handoff, or None if not found

        Raises:
            ValueError: If handoff not found
        """
        # Try regular file first
        if self.project_handoffs_file.exists():
            with FileLock(self.project_handoffs_file):
                handoffs = self._parse_handoffs_file(self.project_handoffs_file)
                for handoff in handoffs:
                    if handoff.id == handoff_id:
                        update_fn(handoff)
                        handoff.updated = date.today()
                        self._write_handoffs_file(handoffs)
                        return handoff

        # Try stealth file
        if self.project_stealth_handoffs_file.exists():
            with FileLock(self.project_stealth_handoffs_file):
                handoffs = self._parse_handoffs_file(self.project_stealth_handoffs_file, stealth=True)
                for handoff in handoffs:
                    if handoff.id == handoff_id:
                        update_fn(handoff)
                        handoff.updated = date.today()
                        self._write_stealth_handoffs_file(handoffs)
                        return handoff

        raise ValueError(f"Handoff {handoff_id} not found")

    def _update_handoff_field(self, handoff_id: str, field: str, value: Any) -> None:
        """
        Update a single field on a handoff.

        This is a generic helper that simplifies field updates by using setattr.
        It delegates to _update_handoff_in_file for the actual file manipulation.

        Args:
            handoff_id: The handoff ID
            field: Field name (e.g., "status", "phase", "agent", "next_steps")
            value: New value for the field

        Raises:
            ValueError: If handoff not found
        """
        def update_fn(h: Handoff) -> None:
            setattr(h, field, value)
        self._update_handoff_in_file(handoff_id, update_fn)

    def handoff_update_status(self, handoff_id: str, status: str) -> None:
        """
        Update a handoff's status.

        Args:
            handoff_id: The handoff ID
            status: New status (not_started, in_progress, blocked, completed)

        Raises:
            ValueError: If handoff not found or invalid status
        """
        if status not in self.VALID_STATUSES:
            raise ValueError(f"Invalid status: {status}")

        old_status = [None]  # Use list to allow modification in closure

        def update_fn(h: Handoff) -> None:
            old_status[0] = h.status
            h.status = status

        self._update_handoff_in_file(handoff_id, update_fn)

        # Log status change
        logger = get_logger()
        logger.handoff_change(
            handoff_id=handoff_id,
            action="status_change",
            old_value=old_status[0],
            new_value=status,
        )

    def handoff_update_phase(self, handoff_id: str, phase: str) -> None:
        """
        Update a handoff's phase.

        Args:
            handoff_id: The handoff ID
            phase: New phase (research, planning, implementing, review)

        Raises:
            ValueError: If handoff not found or invalid phase
        """
        if phase not in self.VALID_PHASES:
            raise ValueError(f"Invalid phase: {phase}")

        old_phase = [None]

        def update_fn(h: Handoff) -> None:
            old_phase[0] = h.phase
            h.phase = phase

        self._update_handoff_in_file(handoff_id, update_fn)

        # Log phase change
        logger = get_logger()
        logger.handoff_change(
            handoff_id=handoff_id,
            action="phase_change",
            old_value=old_phase[0],
            new_value=phase,
        )

    def handoff_update_agent(self, handoff_id: str, agent: str) -> None:
        """
        Update a handoff's agent.

        Args:
            handoff_id: The handoff ID
            agent: New agent (explore, general-purpose, plan, review, user)

        Raises:
            ValueError: If handoff not found or invalid agent
        """
        if agent not in self.VALID_AGENTS:
            raise ValueError(f"Invalid agent: {agent}")

        old_agent = [None]

        def update_fn(h: Handoff) -> None:
            old_agent[0] = h.agent
            h.agent = agent

        self._update_handoff_in_file(handoff_id, update_fn)

        # Log agent change
        logger = get_logger()
        logger.handoff_change(
            handoff_id=handoff_id,
            action="agent_change",
            old_value=old_agent[0],
            new_value=agent,
        )

    # Patterns that indicate work is complete (must be at start, case-insensitive)
    COMPLETION_PATTERNS = ("final", "done", "complete", "finished", "commit")

    # Keywords that indicate implementing phase (case-insensitive)
    IMPLEMENTING_KEYWORDS = (
        "implement", "build", "create", "add", "fix", "write", "update",
        "refactor", "remove", "delete", "rename", "move", "extract",
    )

    # Phases that should not be changed by auto-update (already past implementing)
    PROTECTED_PHASES = ("implementing", "review")

    # Number of successful steps that triggers auto-bump to implementing
    IMPLEMENTING_STEP_THRESHOLD = 10

    # Keywords for categorizing tried steps by theme
    STEP_THEMES = {
        "guard": ["guard", "is_destroyed", "destructor", "cleanup"],
        "plugin": ["plugin", "phase"],
        "ui": ["xml", "button", "modal", "panel", "ui_"],
        "fix": ["fix", "bug", "issue", "error"],
        "refactor": ["refactor", "move", "rename", "extract"],
        "test": ["test", "verify", "build"],
    }

    def _extract_themes(self, tried: List[TriedStep]) -> Dict[str, int]:
        """
        Count tried steps by theme based on keyword matching.

        Args:
            tried: List of tried steps

        Returns:
            Dict mapping theme names to counts
        """
        if not tried:
            return {}

        counts: Dict[str, int] = defaultdict(int)
        for t in tried:
            desc_lower = t.description.lower()
            matched = False
            for theme, keywords in self.STEP_THEMES.items():
                if any(kw in desc_lower for kw in keywords):
                    counts[theme] += 1
                    matched = True
                    break
            if not matched:
                counts["other"] += 1
        return dict(counts)

    def _summarize_tried_steps(
        self, tried: List[TriedStep], max_recent: int = 3
    ) -> List[str]:
        """
        Summarize tried steps compactly for injection.

        Args:
            tried: List of tried steps
            max_recent: Number of recent steps to show (default 3)

        Returns:
            List of formatted lines for the summary
        """
        if not tried:
            return []

        lines = []
        total = len(tried)
        success = sum(1 for t in tried if t.outcome == "success")
        fail = sum(1 for t in tried if t.outcome == "fail")

        # Outcome summary
        if fail == 0:
            outcome_str = f"{total} steps (all success)"
        else:
            outcome_str = f"{total} steps ({success}✓ {fail}✗)"

        lines.append(f"- **Progress**: {outcome_str}")

        # Last N steps
        recent = tried[-max_recent:]
        for t in recent:
            desc = t.description[:50] + "..." if len(t.description) > 50 else t.description
            lines.append(f"  → {desc}")

        # Theme summary for earlier steps (if more than max_recent)
        if len(tried) > max_recent:
            earlier = tried[:-max_recent]
            themes = self._extract_themes(earlier)
            if themes:
                theme_strs = [f"{v} {k}" for k, v in sorted(themes.items(), key=lambda x: -x[1])]
                lines.append(f"  Earlier: {', '.join(theme_strs[:4])}")  # Top 4 themes

        return lines

    def handoff_add_tried(
        self,
        handoff_id: str,
        outcome: str,
        description: str,
    ) -> None:
        """
        Add a tried step.

        Auto-completes handoff if description starts with a completion pattern
        (e.g., "Final commit", "Done", "Finished") and outcome is "success".

        Auto-updates phase to "implementing" if:
        - Description contains implementing keywords (implement, build, create, etc.)
        - OR there are 10+ successful tried steps

        Args:
            handoff_id: The handoff ID
            outcome: success, fail, or partial
            description: Description of what was tried

        Raises:
            ValueError: If handoff not found or invalid outcome
        """
        if outcome not in self.VALID_OUTCOMES:
            raise ValueError(f"Invalid outcome: {outcome}")

        def update_fn(h: Handoff) -> None:
            h.tried.append(TriedStep(
                outcome=outcome,
                description=description,
            ))

            # Auto-complete on final pattern with success outcome
            if outcome == "success":
                desc_lower = description.lower().strip()
                if any(desc_lower.startswith(p) for p in self.COMPLETION_PATTERNS):
                    h.status = "completed"
                    h.phase = "review"

            # Auto-update phase to implementing (if not already in a later phase)
            if h.phase not in self.PROTECTED_PHASES:
                should_bump = False

                # Check for implementing keywords in description
                desc_lower = description.lower()
                if any(kw in desc_lower for kw in self.IMPLEMENTING_KEYWORDS):
                    should_bump = True

                # Check for 10+ successful steps
                if not should_bump:
                    success_count = sum(
                        1 for t in h.tried if t.outcome == "success"
                    )
                    if success_count >= self.IMPLEMENTING_STEP_THRESHOLD:
                        should_bump = True

                if should_bump:
                    h.phase = "implementing"

        self._update_handoff_in_file(handoff_id, update_fn)

    def handoff_update_next(self, handoff_id: str, text: str) -> None:
        """
        Update a handoff's next steps.

        Args:
            handoff_id: The handoff ID
            text: Next steps text

        Raises:
            ValueError: If handoff not found
        """
        self._update_handoff_field(handoff_id, "next_steps", text)

    def handoff_update_refs(self, handoff_id: str, refs_list: List[str]) -> None:
        """
        Update a handoff's refs list.

        Args:
            handoff_id: The handoff ID
            refs_list: List of file:line refs

        Raises:
            ValueError: If handoff not found
        """
        self._update_handoff_field(handoff_id, "refs", refs_list)

    def handoff_update_files(self, handoff_id: str, files_list: List[str]) -> None:
        """
        Update a handoff's file list (deprecated, use handoff_update_refs).

        Args:
            handoff_id: The handoff ID
            files_list: List of files/refs

        Raises:
            ValueError: If handoff not found
        """
        return self.handoff_update_refs(handoff_id, files_list)

    def handoff_update_desc(self, handoff_id: str, description: str) -> None:
        """
        Update a handoff's description.

        Args:
            handoff_id: The handoff ID
            description: New description

        Raises:
            ValueError: If handoff not found
        """
        self._update_handoff_field(handoff_id, "description", description)

    def handoff_update_checkpoint(self, handoff_id: str, checkpoint: str) -> None:
        """
        Update a handoff's checkpoint (progress summary from PreCompact hook).

        Args:
            handoff_id: The handoff ID
            checkpoint: Progress summary text

        Raises:
            ValueError: If handoff not found
        """
        def update_fn(h: Handoff) -> None:
            h.checkpoint = checkpoint
            h.last_session = date.today()

        self._update_handoff_in_file(handoff_id, update_fn)

    def handoff_update_context(self, handoff_id: str, context: HandoffContext) -> None:
        """
        Update a handoff's context (rich structured context for session handoffs).

        Also populates the description field with the summary if the description
        is empty, so that the summary is visible in the handoff list.

        Args:
            handoff_id: The handoff ID
            context: HandoffContext with summary, critical_files, etc.

        Raises:
            ValueError: If handoff not found
        """
        def update_fn(h: Handoff) -> None:
            h.handoff = context
            h.last_session = date.today()
            # Populate description from summary if description is empty
            if context.summary and not h.description:
                h.description = context.summary

        self._update_handoff_in_file(handoff_id, update_fn)

    def handoff_update_blocked_by(self, handoff_id: str, blocked_by: List[str]) -> None:
        """
        Update a handoff's blocked_by dependency list.

        Args:
            handoff_id: The handoff ID
            blocked_by: List of handoff IDs that this handoff is blocked by

        Raises:
            ValueError: If handoff not found
        """
        self._update_handoff_field(handoff_id, "blocked_by", blocked_by)

    def handoff_complete(self, handoff_id: str) -> HandoffCompleteResult:
        """
        Mark a handoff as completed and return extraction prompt.

        Args:
            handoff_id: The handoff ID

        Returns:
            HandoffCompleteResult with handoff data and extraction prompt

        Raises:
            ValueError: If handoff not found
        """
        target = [None]

        def update_fn(h: Handoff) -> None:
            h.status = "completed"
            target[0] = h

        self._update_handoff_in_file(handoff_id, update_fn)
        target = target[0]

        # Generate extraction prompt
        tried_summary = ""
        if target.tried:
            tried_lines = []
            for tried in target.tried:
                tried_lines.append(f"- [{tried.outcome}] {tried.description}")
            tried_summary = "\n".join(tried_lines)

        extraction_prompt = f"""Review this completed handoff for potential lessons to extract:

**Title**: {target.title}
**Description**: {target.description}

**Tried steps**:
{tried_summary if tried_summary else "(none)"}

**Files affected**: {', '.join(target.files) if target.files else "(none)"}

Consider extracting lessons about:
1. What worked and why
2. What didn't work and why
3. Patterns or gotchas discovered
4. Decisions made and their rationale
"""

        # Log handoff completed
        duration_days = (date.today() - target.created).days if target.created else None
        logger = get_logger()
        logger.handoff_completed(
            handoff_id=handoff_id,
            tried_count=len(target.tried),
            duration_days=duration_days,
        )

        return HandoffCompleteResult(
            handoff=target,
            extraction_prompt=extraction_prompt,
        )

    def handoff_archive(self, handoff_id: str) -> None:
        """
        Archive a handoff to HANDOFFS_ARCHIVE.md (or HANDOFFS_LOCAL_ARCHIVE.md for stealth).

        Args:
            handoff_id: The handoff ID

        Raises:
            ValueError: If handoff not found
        """
        # Determine if stealth
        is_stealth = self._is_stealth_handoff(handoff_id)

        if is_stealth:
            file_path = self.project_stealth_handoffs_file
            archive_file = self.project_stealth_handoffs_archive
            archive_header = """# HANDOFFS_LOCAL_ARCHIVE.md - Archived Local Handoffs

> Previously completed or archived local/stealth handoffs.

"""
        else:
            file_path = self.project_handoffs_file
            archive_file = self.project_handoffs_archive
            archive_header = """# HANDOFFS_ARCHIVE.md - Archived Handoffs

> Previously completed or archived handoffs.

"""

        with FileLock(file_path):
            handoffs = self._parse_handoffs_file(file_path, stealth=is_stealth)

            target = None
            remaining = []
            for handoff in handoffs:
                if handoff.id == handoff_id:
                    target = handoff
                else:
                    remaining.append(handoff)

            if target is None:
                raise ValueError(f"Handoff {handoff_id} not found")

            # Append to archive file
            archive_file.parent.mkdir(parents=True, exist_ok=True)

            if archive_file.exists():
                archive_content = archive_file.read_text()
            else:
                archive_content = archive_header

            archive_content += "\n" + self._format_handoff(target) + "\n"
            archive_file.write_text(archive_content)

            # Remove from main file
            if is_stealth:
                self._write_stealth_handoffs_file(remaining)
            else:
                self._write_handoffs_file(remaining)

    def handoff_delete(self, handoff_id: str) -> None:
        """
        Delete a handoff permanently (no archive).

        Args:
            handoff_id: The handoff ID

        Raises:
            ValueError: If handoff not found
        """
        # Determine if stealth
        is_stealth = self._is_stealth_handoff(handoff_id)

        if is_stealth:
            file_path = self.project_stealth_handoffs_file
        else:
            file_path = self.project_handoffs_file

        if not file_path.exists():
            raise ValueError(f"Handoff {handoff_id} not found")

        with FileLock(file_path):
            handoffs = self._parse_handoffs_file(file_path, stealth=is_stealth)

            original_count = len(handoffs)
            handoffs = [h for h in handoffs if h.id != handoff_id]

            if len(handoffs) == original_count:
                raise ValueError(f"Handoff {handoff_id} not found")

            if is_stealth:
                self._write_stealth_handoffs_file(handoffs)
            else:
                self._write_handoffs_file(handoffs)

    def _auto_complete_orphan_handoffs(self) -> List[str]:
        """
        Auto-complete orphan handoffs that appear done but weren't closed out.

        Criteria for auto-completion:
        - Status is 'ready_for_review'
        - Has at least one tried step
        - All tried steps have 'success' outcome
        - Updated more than HANDOFF_ORPHAN_DAYS ago

        Returns:
            List of auto-completed handoff IDs
        """
        cutoff = date.today() - timedelta(days=HANDOFF_ORPHAN_DAYS)
        completed_ids = []

        with FileLock(self.project_handoffs_file):
            if not self.project_handoffs_file.exists():
                return []

            handoffs = self._parse_handoffs_file(self.project_handoffs_file)
            modified = False

            for handoff in handoffs:
                # Check all orphan criteria
                if (
                    handoff.status == "ready_for_review"
                    and handoff.tried  # Has at least one tried step
                    and all(step.outcome == "success" for step in handoff.tried)
                    and handoff.updated < cutoff
                ):
                    # Mark as completed
                    handoff.status = "completed"
                    handoff.updated = date.today()
                    # Add note to description
                    orphan_note = "[Auto-completed: orphan handoff with all success steps]"
                    if handoff.description:
                        handoff.description = f"{orphan_note} {handoff.description}"
                    else:
                        handoff.description = orphan_note
                    completed_ids.append(handoff.id)
                    modified = True
                    logger = get_logger()
                    logger.handoff_change(
                        handoff_id=handoff.id,
                        action="auto_completed",
                        old_value="ready_for_review",
                        new_value="completed",
                    )

            if modified:
                self._write_handoffs_file(handoffs)

        return completed_ids

    def _archive_stale_handoffs(self) -> List[str]:
        """
        Auto-archive active handoffs that haven't been updated in HANDOFF_STALE_DAYS.

        Returns:
            List of archived handoff IDs
        """
        cutoff = date.today() - timedelta(days=HANDOFF_STALE_DAYS)
        archived_ids = []

        with FileLock(self.project_handoffs_file):
            if not self.project_handoffs_file.exists():
                return []

            handoffs = self._parse_handoffs_file(self.project_handoffs_file)
            stale = []
            remaining = []

            for handoff in handoffs:
                # Only archive active (non-completed) handoffs that are stale
                if handoff.status != "completed" and handoff.updated < cutoff:
                    # Add stale note to description
                    stale_note = f"[Auto-archived: stale after {HANDOFF_STALE_DAYS} days]"
                    if handoff.description:
                        handoff.description = f"{stale_note} {handoff.description}"
                    else:
                        handoff.description = stale_note
                    stale.append(handoff)
                    archived_ids.append(handoff.id)
                else:
                    remaining.append(handoff)

            if not stale:
                return []

            # Archive stale handoffs
            archive_file = self.project_handoffs_archive
            archive_file.parent.mkdir(parents=True, exist_ok=True)

            if archive_file.exists():
                archive_content = archive_file.read_text()
            else:
                archive_content = """# HANDOFFS_ARCHIVE.md - Archived Handoffs

> Previously completed or archived handoffs.

"""

            for handoff in stale:
                archive_content += "\n" + self._format_handoff(handoff) + "\n"

            archive_file.write_text(archive_content)
            self._write_handoffs_file(remaining)

        return archived_ids

    def _archive_old_completed_handoffs(self) -> List[str]:
        """
        Auto-archive completed handoffs older than HANDOFF_COMPLETED_ARCHIVE_DAYS.

        Returns:
            List of archived handoff IDs
        """
        cutoff = date.today() - timedelta(days=HANDOFF_COMPLETED_ARCHIVE_DAYS)
        archived_ids = []

        with FileLock(self.project_handoffs_file):
            if not self.project_handoffs_file.exists():
                return []

            handoffs = self._parse_handoffs_file(self.project_handoffs_file)

            old_completed = []
            remaining = []

            for handoff in handoffs:
                # Only archive completed handoffs older than cutoff
                if handoff.status == "completed" and handoff.updated < cutoff:
                    old_completed.append(handoff)
                    archived_ids.append(handoff.id)
                else:
                    remaining.append(handoff)

            if not old_completed:
                return []

            # Archive old completed handoffs
            archive_file = self.project_handoffs_archive
            archive_file.parent.mkdir(parents=True, exist_ok=True)

            if archive_file.exists():
                archive_content = archive_file.read_text()
            else:
                archive_content = """# HANDOFFS_ARCHIVE.md - Archived Handoffs

> Previously completed or archived handoffs.

"""

            for handoff in old_completed:
                archive_content += "\n" + self._format_handoff(handoff) + "\n"

            archive_file.write_text(archive_content)
            self._write_handoffs_file(remaining)

        return archived_ids

    def handoff_get(self, handoff_id: str) -> Optional[Handoff]:
        """
        Get a handoff by ID (searches both regular and stealth files).

        Args:
            handoff_id: The handoff ID

        Returns:
            The Handoff object, or None if not found
        """
        # Search all handoffs from both files
        all_handoffs = self._load_all_handoffs()
        for handoff in all_handoffs:
            if handoff.id == handoff_id:
                return handoff

        return None

    def handoff_list(
        self,
        status_filter: Optional[str] = None,
        include_completed: bool = False,
    ) -> List[Handoff]:
        """
        List handoffs with optional filtering (includes both regular and stealth).

        Args:
            status_filter: Filter by specific status
            include_completed: Include completed handoffs (default False)

        Returns:
            List of matching handoffs
        """
        # Load all handoffs from both files
        handoffs = self._load_all_handoffs()

        if status_filter:
            handoffs = [h for h in handoffs if h.status == status_filter]
        elif not include_completed:
            handoffs = [h for h in handoffs if h.status != "completed"]

        return handoffs

    def handoff_list_completed(
        self,
        max_count: Optional[int] = None,
        max_age_days: Optional[int] = None,
    ) -> List[Handoff]:
        """
        List completed handoffs with hybrid visibility rules (includes stealth).

        Uses OR logic: shows handoffs that are either:
        - Within the last max_count completions, OR
        - Completed within max_age_days

        Args:
            max_count: Max number of recent completions to show (default: HANDOFF_MAX_COMPLETED)
            max_age_days: Max age in days for completed handoffs (default: HANDOFF_MAX_AGE_DAYS)

        Returns:
            List of visible completed handoffs, sorted by updated date (newest first)
        """
        if max_count is None:
            max_count = HANDOFF_MAX_COMPLETED
        if max_age_days is None:
            max_age_days = HANDOFF_MAX_AGE_DAYS

        # Load all handoffs from both files
        handoffs = self._load_all_handoffs()

        # Filter to completed only
        completed = [h for h in handoffs if h.status == "completed"]

        if not completed:
            return []

        # Sort by updated date (newest first)
        completed.sort(key=lambda h: h.updated, reverse=True)

        # Calculate cutoff date
        cutoff_date = date.today() - timedelta(days=max_age_days)

        # Apply hybrid logic: keep if in top N OR recent enough
        visible = []
        for i, handoff in enumerate(completed):
            # In top N by recency
            in_top_n = i < max_count
            # Updated within age limit
            is_recent = handoff.updated >= cutoff_date

            if in_top_n or is_recent:
                visible.append(handoff)

        return visible

    def handoff_inject(
        self,
        max_completed: Optional[int] = None,
        max_completed_age: Optional[int] = None,
    ) -> str:
        """
        Generate context injection string with active and recent completed handoffs.

        Args:
            max_completed: Max completed handoffs to show (default: HANDOFF_MAX_COMPLETED)
            max_completed_age: Max age in days for completed (default: HANDOFF_MAX_AGE_DAYS)

        Returns:
            Formatted string for context injection, empty if no handoffs
        """
        # Auto-maintenance before listing
        self._auto_complete_orphan_handoffs()
        self._archive_stale_handoffs()
        self._archive_old_completed_handoffs()

        active_handoffs = self.handoff_list(include_completed=False)
        completed_handoffs = self.handoff_list_completed(
            max_count=max_completed,
            max_age_days=max_completed_age,
        )

        if not active_handoffs and not completed_handoffs:
            return ""

        lines = []

        # Calculate ready count for header
        all_handoffs = self._load_all_handoffs()
        ready_count = sum(
            1 for h in active_handoffs
            if self._is_handoff_ready(h, all_handoffs)
        )

        # Active handoffs section
        if active_handoffs:
            # Show ready status in header
            if ready_count > 0:
                lines.append(f"## Active Handoffs (Ready: {ready_count})")
            else:
                lines.append("## Active Handoffs (All blocked)")
            lines.append("")

            for handoff in active_handoffs:
                lines.append(f"### [{handoff.id}] {handoff.title}")

                # Check if work appears done (last tried step is completion pattern)
                appears_done = False
                if handoff.tried and handoff.status != "completed":
                    last_desc = handoff.tried[-1].description.lower().strip()
                    if any(last_desc.startswith(p) for p in self.COMPLETION_PATTERNS):
                        appears_done = True

                # Status with relative time
                days_ago = (date.today() - handoff.updated).days
                if days_ago == 0:
                    time_str = "today"
                elif days_ago == 1:
                    time_str = "1d ago"
                else:
                    time_str = f"{days_ago}d ago"

                status_str = handoff.status
                if appears_done:
                    status_str = f"{handoff.status} → completing"

                lines.append(f"- **Status**: {status_str} | **Phase**: {handoff.phase} | **Last**: {time_str}")

                # Compact refs display (first 3 + count) with pipe separator
                if handoff.refs:
                    if len(handoff.refs) <= 3:
                        refs_str = " | ".join(handoff.refs)
                    else:
                        refs_str = " | ".join(handoff.refs[:3]) + f" (+{len(handoff.refs) - 3} more)"
                    lines.append(f"- **Refs**: {refs_str}")

                # Show tried steps - full list for ready_for_review, summary otherwise
                if handoff.tried:
                    if handoff.status == "ready_for_review":
                        # Full list for lesson extraction review
                        lines.append(f"- **Tried** ({len(handoff.tried)} steps):")
                        for step in handoff.tried:
                            lines.append(f"  - [{step.outcome}] {step.description}")
                    else:
                        summary_lines = self._summarize_tried_steps(handoff.tried)
                        lines.extend(summary_lines)

                # Show checkpoint prominently if present (legacy, key for session handoff)
                if handoff.checkpoint:
                    lines.append(f"- **Checkpoint**: {handoff.checkpoint}")

                # Show HandoffContext if present (new structured format)
                if handoff.handoff is not None:
                    ctx = handoff.handoff
                    # Abbreviate git_ref to first 7 characters
                    abbreviated_ref = ctx.git_ref[:7] if len(ctx.git_ref) > 7 else ctx.git_ref
                    lines.append(f"- **Handoff** (from {abbreviated_ref}):")
                    lines.append(f"  - Summary: {ctx.summary}")
                    if ctx.critical_files:
                        refs_str = ", ".join(ctx.critical_files[:3])
                        if len(ctx.critical_files) > 3:
                            refs_str += f" (+{len(ctx.critical_files) - 3} more)"
                        lines.append(f"  - Refs: {refs_str}")
                    if ctx.learnings:
                        lines.append(f"  - Learnings: {', '.join(ctx.learnings)}")
                    if ctx.blockers:
                        lines.append(f"  - Blockers: {', '.join(ctx.blockers)}")

                # Show blocked_by if present
                if handoff.blocked_by:
                    lines.append(f"- **Blocked By**: {', '.join(handoff.blocked_by)}")

                # Appears done warning
                if appears_done:
                    lines.append(f"- ⚠️ **Appears done** - last step was \"{handoff.tried[-1].description[:30]}...\"")

                if handoff.next_steps:
                    lines.append(f"- **Next**: {handoff.next_steps}")

                lines.append("")

        # Recent completions section - show summaries for today's completions
        if completed_handoffs:
            # Check if any completions are from today (may need verification)
            today_count = sum(1 for h in completed_handoffs if (date.today() - h.updated).days == 0)
            if today_count > 0:
                lines.append(f"## Recent Completions ({today_count} today - verify if issues arise)")
            else:
                lines.append("## Recent Completions")
            lines.append("")

            for handoff in completed_handoffs:
                # Calculate days since completion
                days_ago = (date.today() - handoff.updated).days
                if days_ago == 0:
                    time_str = "today"
                elif days_ago == 1:
                    time_str = "1d ago"
                else:
                    time_str = f"{days_ago}d ago"

                lines.append(f"  [{handoff.id}] ✓ {handoff.title} (completed {time_str})")

                # Show summary for today's completions - may need verification
                if days_ago == 0 and handoff.handoff is not None:
                    summary = handoff.handoff.summary
                    if summary:
                        # Truncate long summaries
                        if len(summary) > 150:
                            summary = summary[:147] + "..."
                        lines.append(f"    └─ {summary}")

            lines.append("")

        return "\n".join(lines)

    def handoff_sync_todos(
        self,
        todos: List[dict],
        session_handoff: Optional[str] = None,
    ) -> Optional[str]:
        """
        Sync TodoWrite todos to a handoff.

        Bridges ephemeral TodoWrite with persistent HANDOFFS.md:
        - completed todos → tried entries (outcome=success)
        - in_progress todo → checkpoint (current focus)
        - pending todos → next_steps

        If an active handoff exists, syncs to it regardless of todo count.
        If no active handoff exists, only creates one if 3+ todos (avoids
        noise for small tasks).

        Selection priority:
        1. Session-based: If session_handoff is provided and handoff is active
        2. Explicit prefix: If todos contain [hf-XXXXXXX]
        3. Most recent: Fall back to most recently updated active handoff

        Args:
            todos: List of todo dicts with 'content', 'status', 'activeForm'
            session_handoff: Optional handoff ID from session lookup (highest priority)

        Returns:
            Handoff ID that was updated/created, or None if no todos or
            if < 3 todos and no active handoff
        """
        if not todos:
            return None

        # Categorize todos by status
        completed = [t for t in todos if t.get("status") == "completed"]
        in_progress = [t for t in todos if t.get("status") == "in_progress"]
        pending = [t for t in todos if t.get("status") == "pending"]

        # Extract explicit handoff IDs from todo content (e.g., "[hf-8136b12] Task name")
        # This allows targeting specific handoffs when multiple are active
        explicit_handoff_ids = set()
        handoff_pattern = re.compile(r'\[hf-([0-9a-f]{7})\]')
        for todo in todos:
            content = todo.get("content", "")
            match = handoff_pattern.search(content)
            if match:
                explicit_handoff_ids.add(f"hf-{match.group(1)}")

        # Find or create a handoff
        handoff_id = None

        # Priority 1: Session-based handoff (from session_id lookup)
        if session_handoff:
            handoff = self.handoff_get(session_handoff)
            if handoff and handoff.status != "completed":
                handoff_id = session_handoff

        # Priority 2: Explicitly referenced handoff in todo content
        if not handoff_id and explicit_handoff_ids:
            for hid in explicit_handoff_ids:
                handoff = self.handoff_get(hid)
                if handoff and handoff.status != "completed":
                    handoff_id = hid
                    break

        # Priority 3: Most recently updated active handoff
        if not handoff_id:
            active_handoffs = self.handoff_list(include_completed=False)
            if active_handoffs:
                handoff = max(active_handoffs, key=lambda h: h.updated)
                handoff_id = handoff.id

        # Create new handoff if none found and enough todos
        # BUT: if todos explicitly reference a handoff (even completed), don't create
        # a new one - the work is already tracked under that handoff
        if not handoff_id and len(todos) >= 3 and not explicit_handoff_ids:
            # Only auto-create handoff if 3+ todos (avoid noise for small tasks)
            first_todo = todos[0].get("content", "Work in progress")
            # Truncate title to 100 chars (preserve meaningful info)
            title = first_todo[:100] + ("..." if len(first_todo) > 100 else "")

            # Infer phase from todo content
            combined_content = " ".join(t.get("content", "") for t in todos).lower()
            if any(kw in combined_content for kw in ["implement", "build", "create", "add", "fix", "write", "edit", "update"]):
                phase = "implementing"
            elif any(kw in combined_content for kw in ["research", "investigate", "explore", "understand", "find"]):
                phase = "research"
            elif any(kw in combined_content for kw in ["plan", "design", "architect"]):
                phase = "planning"
            elif any(kw in combined_content for kw in ["review", "test", "verify", "check"]):
                phase = "review"
            else:
                phase = "implementing"  # Default for TodoWrite-created handoffs

            handoff_id = self.handoff_add(title=title, phase=phase)
            # handoff_add already logs creation via debug_logger

        # If still no handoff (< 3 todos and no active handoff), skip
        if not handoff_id:
            return None

        # Sync completed todos as tried entries (success)
        # Only add new ones - check if description already exists
        existing_tried = set()
        handoff = self.handoff_get(handoff_id)
        if handoff and handoff.tried:
            existing_tried = {t.description for t in handoff.tried}

        for todo in completed:
            content = todo.get("content", "")
            if content and content not in existing_tried:
                self.handoff_add_tried(handoff_id, "success", content)

        # Sync in_progress as checkpoint
        if in_progress:
            checkpoint_text = in_progress[0].get("content", "")
            if len(in_progress) > 1:
                checkpoint_text += f" (and {len(in_progress) - 1} more)"
            self.handoff_update_checkpoint(handoff_id, checkpoint_text)

        # Sync pending as next_steps
        if pending:
            next_items = [t.get("content", "") for t in pending[:5]]  # Max 5
            next_text = "; ".join(next_items)
            if len(pending) > 5:
                next_text += f" (and {len(pending) - 5} more)"
            self.handoff_update_next(handoff_id, next_text)

        # Update status based on todo states
        if completed and not pending and not in_progress:
            # All todos completed - auto-complete if commit step succeeded
            has_commit = any(
                "commit" in t.get("content", "").lower()
                for t in completed
            )
            if has_commit:
                self.handoff_update_status(handoff_id, "completed")
            else:
                # No commit step - ready for lesson review
                self.handoff_update_status(handoff_id, "ready_for_review")
        elif completed or in_progress:
            # Work has been done or is in progress - at least in_progress
            self.handoff_update_status(handoff_id, "in_progress")
        elif pending and not completed:
            # Only pending items, no work done yet
            self.handoff_update_status(handoff_id, "not_started")

        logger = get_logger()
        logger.mutation("sync_todos", handoff_id, {
            "completed": len(completed),
            "in_progress": len(in_progress),
            "pending": len(pending),
        })

        return handoff_id

    def handoff_inject_todos(self) -> str:
        """
        Format active handoff as TodoWrite continuation prompt.

        Generates a prompt that helps the agent continue work from a previous session
        by showing the handoff state formatted as suggested todos.

        Returns:
            Formatted string with todo continuation prompt, or empty if no active handoff
        """
        import json as json_module

        active_handoffs = self.handoff_list(include_completed=False)
        if not active_handoffs:
            return ""

        # Use the most recently updated active handoff
        handoff = max(active_handoffs, key=lambda h: h.updated)

        # Build todo list from handoff state
        todos = []
        prefix = f"[{handoff.id}] "  # Prefix to identify handoff-tracked todos

        # Add completed tried entries (already done)
        for tried in handoff.tried:
            if tried.outcome == "success":
                todos.append({
                    "content": prefix + tried.description,
                    "status": "completed",
                    "activeForm": tried.description[:50] + "..." if len(tried.description) > 50 else tried.description
                })

        # Add checkpoint as in_progress
        if handoff.checkpoint:
            todos.append({
                "content": prefix + handoff.checkpoint,
                "status": "in_progress",
                "activeForm": handoff.checkpoint[:50] + "..." if len(handoff.checkpoint) > 50 else handoff.checkpoint
            })

        # Add next_steps as pending (split by semicolon)
        if handoff.next_steps:
            for step in handoff.next_steps.split(";"):
                step = step.strip()
                if step:
                    todos.append({
                        "content": prefix + step,
                        "status": "pending",
                        "activeForm": step[:50] + "..." if len(step) > 50 else step
                    })

        if not todos:
            return ""

        # Calculate session age
        session_ago = ""
        if handoff.last_session:
            days = (date.today() - handoff.last_session).days
            if days == 0:
                session_ago = "today"
            elif days == 1:
                session_ago = "yesterday"
            else:
                session_ago = f"{days}d ago"

        # Format as continuation prompt
        lines = []
        lines.append(f"**CONTINUE PREVIOUS WORK** ({handoff.id}: {handoff.title})")
        if session_ago:
            lines.append(f"Last session: {session_ago}")
        lines.append("")
        lines.append("Previous state:")
        for todo in todos:
            status_icon = {"completed": "✓", "in_progress": "→", "pending": "○"}.get(todo["status"], "?")
            lines.append(f"  {status_icon} {todo['content']}")
        lines.append("")
        lines.append("**Use TodoWrite to resume tracking.** Copy this starting point:")
        lines.append("```json")
        # Only include non-completed todos in the suggested JSON
        active_todos = [t for t in todos if t["status"] != "completed"]
        lines.append(json_module.dumps(active_todos, indent=2))
        lines.append("```")

        return "\n".join(lines)

    def _is_handoff_ready(self, handoff: Handoff, all_handoffs: List[Handoff]) -> bool:
        """
        Check if a handoff is ready to work on.

        A handoff is ready if:
        - It has no blocked_by dependencies, OR
        - All of its blocked_by dependencies are completed

        Args:
            handoff: The handoff to check
            all_handoffs: List of all handoffs (to look up blocker statuses)

        Returns:
            True if the handoff is ready, False if blocked
        """
        # No blockers = ready
        if not handoff.blocked_by:
            return True

        # Build a lookup dict for all handoffs by ID
        handoff_by_id = {h.id: h for h in all_handoffs}

        # Check if all blockers are completed
        for blocker_id in handoff.blocked_by:
            blocker = handoff_by_id.get(blocker_id)
            if blocker is None:
                # Blocker doesn't exist (maybe deleted/archived) - treat as completed
                continue
            if blocker.status != "completed":
                # At least one blocker is not completed
                return False

        # All blockers are completed (or don't exist)
        return True

    def handoff_ready(self) -> List[Handoff]:
        """
        Get list of handoffs that are ready to work on (includes stealth).

        A handoff is ready if:
        - Its status is not 'completed', AND
        - Its blocked_by list is empty OR all blockers are completed

        Returns:
            List of ready handoffs, sorted by:
            1. in_progress first (active work takes priority)
            2. Then by updated date (most recent first)
        """
        # Load all handoffs from both files
        all_handoffs = self._load_all_handoffs()

        ready = []
        for handoff in all_handoffs:
            # Exclude completed handoffs
            if handoff.status == "completed":
                continue

            # Check if ready (no blockers or all blockers completed)
            if self._is_handoff_ready(handoff, all_handoffs):
                ready.append(handoff)

        # Sort: in_progress first, then by updated date (newest first)
        def sort_key(h: Handoff) -> tuple:
            # in_progress gets priority (0), others get 1
            status_priority = 0 if h.status == "in_progress" else 1
            # Negate updated for descending order (most recent first)
            # Using ordinal for date comparison
            updated_ordinal = -h.updated.toordinal() if h.updated else 0
            return (status_priority, updated_ordinal)

        ready.sort(key=sort_key)
        return ready

    def handoff_resume(self, handoff_id: str) -> HandoffResumeResult:
        """
        Resume a handoff with validation of codebase state.

        Validates that:
        - If context has git_ref: current HEAD matches (warns if diverged)
        - If context has critical_files: files still exist (errors if missing)

        Args:
            handoff_id: The handoff ID to resume

        Returns:
            HandoffResumeResult with handoff, validation result, and context

        Raises:
            ValueError: If handoff not found
        """
        import subprocess

        handoff = self.handoff_get(handoff_id)
        if handoff is None:
            raise ValueError(f"Handoff {handoff_id} not found")

        warnings = []
        errors = []

        context = handoff.handoff

        # If no context, return with valid status (legacy mode)
        if context is None:
            validation = ValidationResult(valid=True, warnings=[], errors=[])
            return HandoffResumeResult(
                handoff=handoff,
                validation=validation,
                context=None,
            )

        # Validate git ref if present
        if context.git_ref:
            try:
                result = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=self.project_root,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    current_head = result.stdout.strip()
                    if current_head != context.git_ref:
                        warnings.append(
                            f"Codebase has changed since handoff "
                            f"(was {context.git_ref[:7]}, now {current_head[:7]})"
                        )
            except (subprocess.TimeoutExpired, FileNotFoundError):
                # Git not available or timeout - skip git validation
                pass

        # Validate critical files if present
        if context.critical_files:
            for file_ref in context.critical_files:
                # Extract file path from file:line format
                file_path = file_ref.split(":")[0] if ":" in file_ref else file_ref
                full_path = self.project_root / file_path
                if not full_path.exists():
                    errors.append(f"File no longer exists: {file_path}")

        # Determine validity: valid if no errors (warnings are OK)
        valid = len(errors) == 0

        validation = ValidationResult(valid=valid, warnings=warnings, errors=errors)

        return HandoffResumeResult(
            handoff=handoff,
            validation=validation,
            context=context,
        )

    # -------------------------------------------------------------------------
    # Session-to-Handoff Linking (for automatic todo sync)
    # -------------------------------------------------------------------------

    def _get_session_handoffs_file(self) -> Path:
        """Get the path to the session-handoffs.json file (in state dir)."""
        # Use the state dir from environment or default
        import os
        state_dir = os.environ.get("CLAUDE_RECALL_STATE")
        if state_dir:
            return Path(state_dir) / "session-handoffs.json"
        return Path.home() / ".local" / "state" / "claude-recall" / "session-handoffs.json"

    def _load_session_handoffs(self) -> dict:
        """Load session-handoffs mapping from JSON file."""
        import json as json_mod
        file_path = self._get_session_handoffs_file()
        if not file_path.exists():
            return {}
        try:
            return json_mod.loads(file_path.read_text())
        except (json_mod.JSONDecodeError, OSError):
            return {}

    def _save_session_handoffs(self, data: dict) -> None:
        """Save session-handoffs mapping to JSON file with auto-cleanup."""
        import json as json_mod
        from datetime import datetime, timedelta

        # Auto-cleanup entries older than 24 hours
        cutoff = datetime.now() - timedelta(hours=24)
        cleaned = {}
        for session_id, entry in data.items():
            if isinstance(entry, dict) and "created" in entry:
                try:
                    created = datetime.fromisoformat(entry["created"])
                    if created > cutoff:
                        cleaned[session_id] = entry
                except (ValueError, TypeError):
                    # Invalid date format, skip entry
                    pass
            else:
                # Legacy format or missing created, skip
                pass

        file_path = self._get_session_handoffs_file()
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(json_mod.dumps(cleaned, indent=2))

    def handoff_set_session(
        self,
        handoff_id: str,
        session_id: str,
        transcript_path: Optional[str] = None,
    ) -> None:
        """
        Store session -> handoff mapping.

        Called by post-exitplanmode-hook.sh when creating a handoff,
        to link the session that created the handoff.

        Args:
            handoff_id: The handoff ID (e.g., 'hf-abc1234')
            session_id: The Claude session ID from hook input
            transcript_path: Optional path to the session transcript file
        """
        from datetime import datetime

        data = self._load_session_handoffs()
        data[session_id] = {
            "handoff_id": handoff_id,
            "created": datetime.now().isoformat(),
            "transcript_path": transcript_path,
        }
        self._save_session_handoffs(data)

        logger = get_logger()
        logger.mutation("set_session", session_id, {
            "handoff_id": handoff_id,
            "has_transcript": bool(transcript_path),
        })

    def handoff_set_session_extended(
        self,
        session_id: str,
        handoff_id: Optional[str] = None,
        origin: str = "User",
        parent_session_id: Optional[str] = None,
        is_sub_agent: bool = False,
        transcript_path: Optional[str] = None,
    ) -> None:
        """
        Store session with extended metadata for sub-agent tracking.

        Called by session link command to store origin type and parent relationship.
        Sub-agents (origin != User) should not create handoffs but can update them.

        Args:
            session_id: The Claude session ID
            handoff_id: Optional handoff ID to link to
            origin: Session origin type (User, Explore, Plan, General, etc.)
            parent_session_id: ID of parent session if this is a sub-agent
            is_sub_agent: True if this session was spawned by another session
            transcript_path: Optional path to the session transcript file
        """
        from datetime import datetime

        data = self._load_session_handoffs()
        data[session_id] = {
            "handoff_id": handoff_id,
            "created": datetime.now().isoformat(),
            "transcript_path": transcript_path,
            "origin": origin,
            "parent_session_id": parent_session_id,
            "is_sub_agent": is_sub_agent,
        }
        self._save_session_handoffs(data)

        logger = get_logger()
        logger.mutation("set_session_extended", session_id, {
            "handoff_id": handoff_id,
            "origin": origin,
            "parent_session_id": parent_session_id,
            "is_sub_agent": is_sub_agent,
        })

    def handoff_get_session_info(self, session_id: str) -> Optional[dict]:
        """
        Get session info including origin and parent relationship.

        Args:
            session_id: The Claude session ID

        Returns:
            Dict with session metadata or None if not found
        """
        data = self._load_session_handoffs()
        return data.get(session_id)

    def handoff_get_by_session(self, session_id: str) -> Optional[str]:
        """
        Get active handoff ID for a session.

        Called by post-todowrite-hook.sh to find which handoff
        to sync todos to based on the current session.

        Args:
            session_id: The Claude session ID from hook input

        Returns:
            Handoff ID if found and still active, None otherwise
        """
        data = self._load_session_handoffs()
        entry = data.get(session_id)
        if not entry:
            return None

        handoff_id = entry.get("handoff_id")
        if not handoff_id:
            return None

        # Verify handoff is still active (not completed)
        handoff = self.handoff_get(handoff_id)
        if handoff is None or handoff.status == "completed":
            return None

        return handoff_id

    def handoff_add_transcript(
        self,
        session_id: str,
        transcript_path: str,
        agent_type: Optional[str] = None,
    ) -> Optional[str]:
        """
        Add a transcript file reference to the handoff linked to this session.

        Called by stop-hook.sh on session end to record transcript paths.
        Handles both main sessions and sub-agent sessions.

        Args:
            session_id: The Claude session ID from hook input
            transcript_path: Path to the transcript .jsonl file
            agent_type: Optional agent type (e.g., 'Explore', 'general-purpose')
                        If None, this is the main session transcript

        Returns:
            Handoff ID if transcript was added, None if no linked handoff
        """
        # First, check if this session directly has a linked handoff
        handoff_id = self.handoff_get_by_session(session_id)

        if not handoff_id:
            # This might be a sub-agent session - we don't have parent linking yet
            # For now, sub-agents won't add transcripts automatically
            return None

        # Get handoff and update its transcripts in the handoff context
        handoff = self.handoff_get(handoff_id)
        if not handoff:
            return None

        # Update the handoff's sessions list and persist to file
        def update_fn(h: Handoff) -> None:
            if session_id not in h.sessions:
                h.sessions.append(session_id)

        try:
            self._update_handoff_in_file(handoff_id, update_fn)
        except ValueError:
            # Handoff not found in file - just log and return
            pass

        # Log the transcript addition
        logger = get_logger()
        logger.mutation("add_transcript", handoff_id, {
            "session_id": session_id,
            "transcript_path": transcript_path,
            "agent_type": agent_type,
        })

        return handoff_id

    # -------------------------------------------------------------------------
    # Batch Processing
    # -------------------------------------------------------------------------

    def handoff_batch_process(self, operations: List[dict]) -> dict:
        """
        Process multiple handoff operations in a single batch.

        This method is optimized to parse the file ONCE, apply ALL operations
        in memory, and write the file ONCE at the end. This reduces I/O overhead
        when processing multiple commands from agent output.

        Args:
            operations: List of operation dicts. Supported operations:
                {"op": "add", "title": "...", "desc": "...", "phase": "...", "agent": "..."}
                {"op": "update", "id": "hf-xxx", "status": "in_progress"}
                {"op": "update", "id": "hf-xxx", "tried": ["success", "description"]}
                {"op": "update", "id": "hf-xxx", "next": "..."}
                {"op": "update", "id": "hf-xxx", "checkpoint": "..."}
                {"op": "update", "id": "hf-xxx", "phase": "..."}
                {"op": "update", "id": "hf-xxx", "agent": "..."}
                {"op": "update", "id": "hf-xxx", "desc": "..."}
                {"op": "update", "id": "hf-xxx", "blocked_by": "id1,id2"}
                {"op": "complete", "id": "hf-xxx"}

                When "id" is "LAST", resolves to the most recently created handoff ID.

        Returns:
            {
                "results": [
                    {"ok": True, "id": "hf-abc123"},
                    {"ok": False, "error": "Handoff not found"},
                    ...
                ],
                "last_id": "hf-abc123"  # Last created/used handoff ID, or None
            }
        """
        if not operations:
            return {"results": [], "last_id": None}

        results = []
        last_created_id = None
        today = date.today()

        # Initialize files if they don't exist
        self._init_handoffs_file()

        # Acquire lock once and parse file once
        with FileLock(self.project_handoffs_file):
            handoffs = self._parse_handoffs_file(self.project_handoffs_file)
            handoffs_by_id = {h.id: h for h in handoffs}
            modified = False

            for op in operations:
                op_type = op.get("op")
                op_result = {"ok": False, "error": "Unknown operation"}

                try:
                    if op_type == "add":
                        # Add a new handoff
                        title = op.get("title", "")
                        if not title:
                            op_result = {"ok": False, "error": "Title required for add"}
                        else:
                            # Check for duplicate
                            title_lower = title.lower().strip()
                            existing = None
                            for h in handoffs:
                                if h.status != "completed" and h.title.lower().strip() == title_lower:
                                    existing = h
                                    break

                            if existing:
                                # Return existing ID (duplicate detection)
                                op_result = {"ok": True, "id": existing.id}
                                last_created_id = existing.id
                            else:
                                # Create new handoff
                                new_id = self._generate_handoff_id(title)
                                phase = op.get("phase", "research")
                                agent = op.get("agent", "user")

                                # Validate phase and agent
                                if phase not in self.VALID_PHASES:
                                    phase = "research"
                                if agent not in self.VALID_AGENTS:
                                    agent = "user"

                                new_handoff = Handoff(
                                    id=new_id,
                                    title=title,
                                    status="not_started",
                                    created=today,
                                    updated=today,
                                    refs=[],
                                    description=op.get("desc", ""),
                                    tried=[],
                                    next_steps="",
                                    phase=phase,
                                    agent=agent,
                                    stealth=False,
                                )
                                handoffs.append(new_handoff)
                                handoffs_by_id[new_id] = new_handoff
                                last_created_id = new_id
                                modified = True
                                op_result = {"ok": True, "id": new_id}

                    elif op_type == "update":
                        # Update an existing handoff
                        handoff_id = op.get("id", "")

                        # Resolve LAST reference
                        if handoff_id == "LAST":
                            if last_created_id:
                                handoff_id = last_created_id
                            else:
                                op_result = {"ok": False, "error": "No handoff created yet for LAST reference"}
                                results.append(op_result)
                                continue

                        handoff = handoffs_by_id.get(handoff_id)
                        if not handoff:
                            op_result = {"ok": False, "error": f"Handoff {handoff_id} not found"}
                        else:
                            # Apply updates, tracking if anything changed
                            fields_updated = 0
                            validation_error = None

                            if "status" in op:
                                status = op["status"]
                                if status in self.VALID_STATUSES:
                                    handoff.status = status
                                    handoff.updated = today
                                    modified = True
                                    fields_updated += 1
                                else:
                                    validation_error = f"Invalid status: {status}"

                            if "tried" in op and validation_error is None:
                                tried_data = op["tried"]
                                if isinstance(tried_data, list) and len(tried_data) >= 2:
                                    outcome, description = tried_data[0], tried_data[1]
                                    if outcome in self.VALID_OUTCOMES:
                                        handoff.tried.append(TriedStep(
                                            outcome=outcome,
                                            description=description,
                                        ))
                                        handoff.updated = today
                                        modified = True
                                        fields_updated += 1
                                    else:
                                        validation_error = f"Invalid tried outcome: {outcome}"

                            if "next" in op and validation_error is None:
                                handoff.next_steps = op["next"]
                                handoff.updated = today
                                modified = True
                                fields_updated += 1

                            if "checkpoint" in op and validation_error is None:
                                handoff.checkpoint = op["checkpoint"]
                                handoff.last_session = today
                                handoff.updated = today
                                modified = True
                                fields_updated += 1

                            if "phase" in op and validation_error is None:
                                phase = op["phase"]
                                if phase in self.VALID_PHASES:
                                    handoff.phase = phase
                                    handoff.updated = today
                                    modified = True
                                    fields_updated += 1
                                else:
                                    validation_error = f"Invalid phase: {phase}"

                            if "agent" in op and validation_error is None:
                                agent = op["agent"]
                                if agent in self.VALID_AGENTS:
                                    handoff.agent = agent
                                    handoff.updated = today
                                    modified = True
                                    fields_updated += 1
                                else:
                                    validation_error = f"Invalid agent: {agent}"

                            if "desc" in op and validation_error is None:
                                handoff.description = op["desc"]
                                handoff.updated = today
                                modified = True
                                fields_updated += 1

                            if "blocked_by" in op and validation_error is None:
                                blocked_str = op["blocked_by"]
                                if isinstance(blocked_str, str):
                                    blocked_by = [b.strip() for b in blocked_str.split(",") if b.strip()]
                                elif isinstance(blocked_str, list):
                                    blocked_by = blocked_str
                                else:
                                    blocked_by = []
                                handoff.blocked_by = blocked_by
                                handoff.updated = today
                                modified = True
                                fields_updated += 1

                            if validation_error:
                                op_result = {"ok": False, "error": validation_error}
                            elif fields_updated == 0:
                                op_result = {"ok": True, "id": handoff_id, "warning": "No valid fields to update"}
                            else:
                                op_result = {"ok": True, "id": handoff_id}

                    elif op_type == "complete":
                        # Complete a handoff
                        handoff_id = op.get("id", "")

                        # Resolve LAST reference
                        if handoff_id == "LAST":
                            if last_created_id:
                                handoff_id = last_created_id
                            else:
                                op_result = {"ok": False, "error": "No handoff created yet for LAST reference"}
                                results.append(op_result)
                                continue

                        handoff = handoffs_by_id.get(handoff_id)
                        if not handoff:
                            op_result = {"ok": False, "error": f"Handoff {handoff_id} not found"}
                        else:
                            handoff.status = "completed"
                            handoff.updated = today
                            modified = True
                            op_result = {"ok": True, "id": handoff_id}

                    else:
                        op_result = {"ok": False, "error": f"Unknown operation: {op_type}"}

                except Exception as e:
                    op_result = {"ok": False, "error": str(e)}

                results.append(op_result)

            # Write file once at the end if modified
            if modified:
                self._write_handoffs_file(handoffs)

        return {"results": results, "last_id": last_created_id}

    # -------------------------------------------------------------------------
    # Transcript Parsing (for stop-hook optimization)
    # -------------------------------------------------------------------------

    # Sub-agent session origins that should be blocked from creating handoffs
    SUB_AGENT_ORIGINS = {"Explore", "Plan", "General", "System"}

    @staticmethod
    def _sanitize_text(text: str, max_length: int = 500) -> str:
        """
        Sanitize text for safe storage.

        - Removes control characters (keeps printable + common unicode)
        - Collapses multiple spaces
        - Truncates to max_length
        - Trims whitespace

        Args:
            text: Input text to sanitize
            max_length: Maximum length of output

        Returns:
            Sanitized text
        """
        if not text:
            return ""

        # Remove control characters (keep printable ASCII and common unicode)
        # \x20-\x7E is printable ASCII, \u00A0-\uFFFF covers common unicode
        result = "".join(
            c for c in text
            if c == "\n" or c == "\t" or ("\x20" <= c <= "\x7E") or ("\u00A0" <= c <= "\uFFFF")
        )

        # Collapse multiple spaces (but preserve newlines)
        result = re.sub(r"[ \t]+", " ", result)

        # Truncate to max length
        if len(result) > max_length:
            result = result[:max_length]

        # Trim whitespace
        result = result.strip()

        return result

    @staticmethod
    def _infer_blocked_by(text: str) -> List[str]:
        """
        Infer blocked_by dependencies from natural language patterns in text.

        Patterns detected:
        - "waiting for X" -> blocked_by X
        - "blocked by Y" -> blocked_by Y
        - "depends on Z" -> blocked_by Z
        - "after A completes" -> blocked_by A

        Where X/Y/Z/A are handoff IDs (A### or hf-XXXXXXX format).

        Args:
            text: Text to analyze for dependency patterns

        Returns:
            List of unique blocker handoff IDs, empty if none found
        """
        if not text:
            return []

        blockers = set()

        # Pattern matches hf-1234567 or A001 format IDs
        handoff_id_pattern = r"(hf-[0-9a-f]{7}|[A-Z][0-9]{3})"

        # Pattern: "waiting for <ID>"
        for match in re.finditer(rf"waiting for {handoff_id_pattern}", text, re.IGNORECASE):
            blockers.add(match.group(1))

        # Pattern: "blocked by <ID>"
        for match in re.finditer(rf"blocked by {handoff_id_pattern}", text, re.IGNORECASE):
            blockers.add(match.group(1))

        # Pattern: "depends on <ID>"
        for match in re.finditer(rf"depends on {handoff_id_pattern}", text, re.IGNORECASE):
            blockers.add(match.group(1))

        # Pattern: "after <ID> completes"
        for match in re.finditer(rf"after {handoff_id_pattern} completes", text, re.IGNORECASE):
            blockers.add(match.group(1))

        return list(blockers)

    def _detect_session_origin(self, session_id: str) -> str:
        """
        Detect the origin type of a session.

        Args:
            session_id: The Claude session ID

        Returns:
            Origin type: "User", "Explore", "Plan", "General", "System", or "Unknown"
        """
        try:
            from core.tui.transcript_reader import TranscriptReader
        except ImportError:
            try:
                from tui.transcript_reader import TranscriptReader
            except ImportError:
                return "Unknown"

        try:
            reader = TranscriptReader()
            return reader.get_session_origin_fast(session_id)
        except (OSError, ValueError) as e:
            # Expected failures when reading session files
            return "Unknown"

    def parse_transcript_for_handoffs(
        self,
        transcript_data: dict,
        session_id: str = "",
        project_root: Optional[Path] = None,
    ) -> List[dict]:
        """
        Parse transcript data for handoff-related patterns.

        This method extracts handoff operations from transcript text, performing
        all parsing and sanitization in Python (no subprocess calls).

        Args:
            transcript_data: Dict with 'assistant_texts' and/or 'assistant_texts_new' arrays
            session_id: Optional Claude session ID for sub-agent detection
            project_root: Optional project root (defaults to self.project_root)

        Returns:
            List of operation dicts ready for handoff_batch_process():
                {"op": "add", "title": "...", "desc": "...", "phase": "...", "agent": "..."}
                {"op": "update", "id": "...", "status|phase|agent|desc|tried|next|checkpoint|blocked_by": ...}
                {"op": "complete", "id": "..."}
        """
        import time as time_module
        import os
        debug_timing = os.environ.get("CLAUDE_RECALL_DEBUG", "0") >= "1"
        t_start = time_module.perf_counter()

        operations = []

        # Get text arrays from transcript data
        # Prefer assistant_texts_new (incremental) if available, else use assistant_texts
        texts = transcript_data.get("assistant_texts_new", [])
        if not texts:
            texts = transcript_data.get("assistant_texts", [])

        if not texts:
            return operations

        # Detect if this is a sub-agent session
        is_sub_agent = False
        t_origin_start = time_module.perf_counter()
        if session_id:
            origin = self._detect_session_origin(session_id)
            if origin in self.SUB_AGENT_ORIGINS:
                is_sub_agent = True
        t_origin_end = time_module.perf_counter()
        if debug_timing:
            import sys
            print(f"[timing] _detect_session_origin={int((t_origin_end-t_origin_start)*1000)}ms", file=sys.stderr)

        # Handoff ID pattern (hf-1234567 or legacy A001 format)
        handoff_id_pattern = r"(hf-[0-9a-f]{7}|[A-Z][0-9]{3}|LAST)"

        # Process each text block for handoff patterns
        for text in texts:
            if not isinstance(text, str):
                continue

            # Process line by line to find patterns
            for line in text.split("\n"):
                line = line.strip()
                if not line:
                    continue

                # Skip overly long lines to prevent ReDoS
                if len(line) > 1000:
                    continue

                # Pattern 1: HANDOFF: <title> [- <description>]
                match = re.match(r"^HANDOFF:\s+(.+)$", line)
                if match:
                    if is_sub_agent:
                        # Sub-agents cannot create handoffs
                        continue

                    full_match = match.group(1)
                    # Check for " - " separator
                    sep_match = re.match(r"^(.+?)\s+-\s+(.+)$", full_match)
                    if sep_match:
                        title = self._sanitize_text(sep_match.group(1), 200)
                        desc = self._sanitize_text(sep_match.group(2), 500)
                    else:
                        title = self._sanitize_text(full_match, 200)
                        desc = ""

                    if title:
                        op = {"op": "add", "title": title}
                        if desc:
                            op["desc"] = desc
                        operations.append(op)
                    continue

                # Pattern 1b: PLAN MODE: <title>
                match = re.match(r"^PLAN MODE:\s+(.+)$", line)
                if match:
                    if is_sub_agent:
                        continue

                    title = self._sanitize_text(match.group(1), 200)
                    if title:
                        operations.append({
                            "op": "add",
                            "title": title,
                            "phase": "research",
                            "agent": "plan",
                        })
                    continue

                # Pattern 2: HANDOFF UPDATE <id>: status <status>
                match = re.match(
                    rf"^HANDOFF UPDATE {handoff_id_pattern}:\s+status\s+(.+)$", line
                )
                if match:
                    handoff_id = match.group(1)
                    status = self._sanitize_text(match.group(2), 20)
                    operations.append({
                        "op": "update",
                        "id": handoff_id,
                        "status": status,
                    })
                    continue

                # Pattern 2b: HANDOFF UPDATE <id>: phase <phase>
                match = re.match(
                    rf"^HANDOFF UPDATE {handoff_id_pattern}:\s+phase\s+(.+)$", line
                )
                if match:
                    handoff_id = match.group(1)
                    phase = self._sanitize_text(match.group(2), 20)
                    operations.append({
                        "op": "update",
                        "id": handoff_id,
                        "phase": phase,
                    })
                    continue

                # Pattern 2c: HANDOFF UPDATE <id>: agent <agent>
                match = re.match(
                    rf"^HANDOFF UPDATE {handoff_id_pattern}:\s+agent\s+(.+)$", line
                )
                if match:
                    handoff_id = match.group(1)
                    agent = self._sanitize_text(match.group(2), 30)
                    operations.append({
                        "op": "update",
                        "id": handoff_id,
                        "agent": agent,
                    })
                    continue

                # Pattern 2d: HANDOFF UPDATE <id>: desc <text>
                match = re.match(
                    rf"^HANDOFF UPDATE {handoff_id_pattern}:\s+desc\s+(.+)$", line
                )
                if match:
                    handoff_id = match.group(1)
                    desc = self._sanitize_text(match.group(2), 500)
                    operations.append({
                        "op": "update",
                        "id": handoff_id,
                        "desc": desc,
                    })
                    continue

                # Pattern 3: HANDOFF UPDATE <id>: tried <outcome> - <description>
                match = re.match(
                    rf"^HANDOFF UPDATE {handoff_id_pattern}:\s+tried\s+(\w+)\s+-\s+(.+)$",
                    line,
                )
                if match:
                    handoff_id = match.group(1)
                    outcome = match.group(2).lower()
                    description = self._sanitize_text(match.group(3), 500)

                    # Validate outcome
                    if outcome in ("success", "fail", "partial"):
                        operations.append({
                            "op": "update",
                            "id": handoff_id,
                            "tried": [outcome, description],
                        })
                    continue

                # Pattern 4: HANDOFF UPDATE <id>: next <text>
                match = re.match(
                    rf"^HANDOFF UPDATE {handoff_id_pattern}:\s+next\s+(.+)$", line
                )
                if match:
                    handoff_id = match.group(1)
                    next_text = self._sanitize_text(match.group(2), 500)

                    op = {
                        "op": "update",
                        "id": handoff_id,
                        "next": next_text,
                    }

                    # Infer blocked_by from next text
                    blocked_by = self._infer_blocked_by(next_text)
                    if blocked_by:
                        op["blocked_by"] = ",".join(blocked_by)

                    operations.append(op)
                    continue

                # Pattern 4b: HANDOFF UPDATE <id>: blocked_by <ids>
                match = re.match(
                    rf"^HANDOFF UPDATE {handoff_id_pattern}:\s+blocked_by\s+(.+)$", line
                )
                if match:
                    handoff_id = match.group(1)
                    blocked_ids = self._sanitize_text(match.group(2), 200)
                    operations.append({
                        "op": "update",
                        "id": handoff_id,
                        "blocked_by": blocked_ids,
                    })
                    continue

                # Pattern 4c: HANDOFF UPDATE <id>: checkpoint <text>
                match = re.match(
                    rf"^HANDOFF UPDATE {handoff_id_pattern}:\s+checkpoint\s+(.+)$", line
                )
                if match:
                    handoff_id = match.group(1)
                    checkpoint = self._sanitize_text(match.group(2), 500)
                    operations.append({
                        "op": "update",
                        "id": handoff_id,
                        "checkpoint": checkpoint,
                    })
                    continue

                # Pattern 5: HANDOFF COMPLETE <id>
                match = re.match(rf"^HANDOFF COMPLETE {handoff_id_pattern}$", line)
                if match:
                    handoff_id = match.group(1)
                    operations.append({
                        "op": "complete",
                        "id": handoff_id,
                    })
                    continue

        return operations
