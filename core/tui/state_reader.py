#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
State reader for the TUI debug viewer.

Provides reading of lessons, handoffs, and decay state from their
respective files. Reuses parsing patterns from core modules.
"""

import os
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------

# Data directory names in order of precedence
DATA_DIRS: Tuple[str, ...] = (".claude-recall", ".recall", ".coding-agent-lessons")

# Standard filenames
LESSONS_FILENAME = "LESSONS.md"
HANDOFFS_FILENAME = "HANDOFFS.md"
LEGACY_HANDOFFS_FILENAME = "APPROACHES.md"
DECAY_STATE_FILENAME = "decay_state"

try:
    from core.tui.analytics import HandoffAnalytics
    from core.tui.models import (
        DecayInfo,
        HandoffContextSummary,
        HandoffSummary,
        LessonSummary,
        TriedStep,
    )
except ImportError:
    from .analytics import HandoffAnalytics
    from .models import (
        DecayInfo,
        HandoffContextSummary,
        HandoffSummary,
        LessonSummary,
        TriedStep,
    )


def get_state_dir() -> Path:
    """
    Get the state directory for claude-recall.

    Uses CLAUDE_RECALL_STATE env var if set, otherwise falls back
    to XDG state directory (~/.local/state/claude-recall).

    Returns:
        Path to the state directory
    """
    explicit_state = os.environ.get("CLAUDE_RECALL_STATE")
    if explicit_state:
        return Path(explicit_state)

    xdg_state = os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state")
    return Path(xdg_state) / "claude-recall"


def get_lessons_base() -> Path:
    """
    Get the lessons base directory.

    Uses CLAUDE_RECALL_BASE env var if set, otherwise falls back
    to XDG config directory (~/.config/claude-recall).

    Returns:
        Path to the lessons base directory
    """
    explicit_base = os.environ.get("CLAUDE_RECALL_BASE")
    if explicit_base:
        return Path(explicit_base)

    xdg_config = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(xdg_config) / "claude-recall"


def get_project_root() -> Optional[Path]:
    """
    Get the project root directory.

    Uses PROJECT_DIR env var if set, otherwise attempts to find
    git root directory.

    Returns:
        Path to project root, or None if not determinable
    """
    explicit_root = os.environ.get("PROJECT_DIR")
    if explicit_root:
        return Path(explicit_root)

    # Try to find git root
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return Path(result.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return None


class StateReader:
    """
    Reader for lessons and handoffs state files.

    Parses LESSONS.md and HANDOFFS.md files to extract summary information
    for the TUI dashboard.

    Attributes:
        state_dir: Path to state directory (for decay info, system lessons)
        project_root: Path to project root (for project lessons/handoffs)
    """

    # Regex patterns for parsing lessons (from core/models.py)
    LESSON_HEADER_PATTERN = re.compile(
        r"^###\s*\[([LS]\d{3})\]\s*\[([*+\-|/\ ]+)\]\s*(.*)$"
    )
    METADATA_PATTERN = re.compile(
        r"^\s*-\s*\*\*Uses\*\*:\s*(\d+)"
        r"(?:\s*\|\s*\*\*Velocity\*\*:\s*([\d.]+))?"
    )

    # Regex patterns for parsing handoffs
    # Match both legacy format (A001) and new format (hf-xxxxxxx with any alphanumeric)
    HANDOFF_HEADER_PATTERN = re.compile(
        r"^###\s*\[([A-Z]\d{3}|hf-\w+)\]\s*(.+)$"
    )
    HANDOFF_STATUS_PATTERN = re.compile(
        r"^\s*-\s*\*\*Status\*\*:\s*(\w+)"
        r"\s*\|\s*\*\*Phase\*\*:\s*([\w-]+)"
        r"(?:\s*\|\s*\*\*Agent\*\*:\s*([\w-]+))?"
    )
    # Match dates with optional time component (YYYY-MM-DD or YYYY-MM-DD HH:MM or YYYY-MM-DD HH:MM:SS)
    HANDOFF_DATES_PATTERN = re.compile(
        r"\*\*Created\*\*:\s*(\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}(?::\d{2})?)?)\s*\|\s*"
        r"\*\*Updated\*\*:\s*(\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}(?::\d{2})?)?)"
    )
    HANDOFF_DESCRIPTION_PATTERN = re.compile(r"^\*\*Description\*\*:\s*(.+)$")
    HANDOFF_TRIED_HEADER_PATTERN = re.compile(r"^\*\*Tried\*\*\s*\(\d+\s*steps?\):")
    HANDOFF_TRIED_STEP_PATTERN = re.compile(
        r"^\s*\d+\.\s*\[(success|fail|partial)\]\s*(.+)$"
    )
    HANDOFF_NEXT_HEADER_PATTERN = re.compile(r"^\*\*Next\*\*:\s*(.*)$")
    # Match bullet items starting with dash, exclude separator lines (---, ----, etc.)
    HANDOFF_NEXT_STEP_PATTERN = re.compile(r"^\s*-\s*(?!-+\s*$)(.+)$")
    HANDOFF_REFS_PATTERN = re.compile(r"^\*\*Refs\*\*:\s*(.*)$")
    HANDOFF_CHECKPOINT_PATTERN = re.compile(r"^\*\*Checkpoint\*\*:\s*(.+)$")
    HANDOFF_BLOCKED_BY_PATTERN = re.compile(r"^\s*-\s*\*\*Blocked By\*\*:\s*(.+)$")
    # Handoff Context section patterns
    HANDOFF_CONTEXT_HEADER_PATTERN = re.compile(r"^\*\*Handoff Context\*\*:")
    HANDOFF_CONTEXT_GIT_REF_PATTERN = re.compile(r"^\s*-\s*\*\*Git Ref\*\*:\s*(.+)$")
    HANDOFF_CONTEXT_SUMMARY_PATTERN = re.compile(r"^\s*-\s*\*\*Summary\*\*:\s*(.+)$")
    HANDOFF_CONTEXT_CRITICAL_FILES_PATTERN = re.compile(
        r"^\s*-\s*\*\*Critical Files\*\*:\s*(.*)$"
    )
    HANDOFF_CONTEXT_RECENT_CHANGES_PATTERN = re.compile(
        r"^\s*-\s*\*\*Recent Changes\*\*:\s*(.*)$"
    )
    HANDOFF_CONTEXT_LEARNINGS_PATTERN = re.compile(
        r"^\s*-\s*\*\*Learnings\*\*:\s*(.*)$"
    )
    HANDOFF_CONTEXT_BLOCKERS_PATTERN = re.compile(
        r"^\s*-\s*\*\*Blockers\*\*:\s*(.*)$"
    )

    def __init__(
        self,
        state_dir: Optional[Path] = None,
        project_root: Optional[Path] = None,
    ) -> None:
        """
        Initialize the state reader.

        Args:
            state_dir: Path to state directory. If None, uses default.
            project_root: Path to project root. If None, attempts to detect.
        """
        self.state_dir = state_dir or get_state_dir()
        self.project_root = project_root or get_project_root()
        self._analytics = HandoffAnalytics()

    @property
    def system_lessons_file(self) -> Path:
        """Path to system lessons file."""
        return self.state_dir / LESSONS_FILENAME

    @property
    def project_lessons_file(self) -> Optional[Path]:
        """Path to project lessons file, or None if no project root."""
        if self.project_root is None:
            return None
        return self._find_lessons_file(self.project_root)

    @property
    def project_handoffs_file(self) -> Optional[Path]:
        """Path to project handoffs file, or None if no project root."""
        if self.project_root is None:
            return None
        return self._find_handoffs_file(self.project_root)

    @property
    def decay_state_file(self) -> Path:
        """Path to decay state file."""
        return self.state_dir / DECAY_STATE_FILENAME

    def _find_data_dir(self, project_root: Path) -> Optional[Path]:
        """
        Find data directory in order of precedence.

        Args:
            project_root: Project root to search in

        Returns:
            Path to existing data directory, or None if none exists
        """
        for dir_name in DATA_DIRS:
            data_dir = project_root / dir_name
            if data_dir.exists():
                return data_dir
        return None

    def _find_lessons_file(self, project_root: Path) -> Path:
        """
        Find lessons file in project, checking data dirs in precedence order.

        Args:
            project_root: Project root to search in

        Returns:
            Path to existing lessons file, or default path if none exists
        """
        for dir_name in DATA_DIRS:
            lessons_file = project_root / dir_name / LESSONS_FILENAME
            if lessons_file.exists():
                return lessons_file
        return project_root / DATA_DIRS[0] / LESSONS_FILENAME

    def _find_handoffs_file(self, project_root: Path) -> Path:
        """
        Find handoffs file in project, checking data dirs and legacy names.

        Args:
            project_root: Project root to search in

        Returns:
            Path to existing handoffs file, or default path if none exists
        """
        for dir_name in DATA_DIRS:
            data_dir = project_root / dir_name
            for filename in (HANDOFFS_FILENAME, LEGACY_HANDOFFS_FILENAME):
                handoffs_file = data_dir / filename
                if handoffs_file.exists():
                    return handoffs_file
        return project_root / DATA_DIRS[0] / HANDOFFS_FILENAME

    def _parse_lessons_file(self, file_path: Path, level: str) -> List[LessonSummary]:
        """
        Parse lessons from a LESSONS.md file.

        Args:
            file_path: Path to the lessons file
            level: 'project' or 'system'

        Returns:
            List of LessonSummary objects
        """
        if not file_path.exists():
            return []

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []

        lessons = []
        lines = content.split("\n")

        idx = 0
        while idx < len(lines):
            header_match = self.LESSON_HEADER_PATTERN.match(lines[idx])
            if not header_match:
                idx += 1
                continue

            lesson_id = header_match.group(1)
            title = header_match.group(3).strip()

            # Remove robot emoji if present
            if title.startswith("\U0001f916"):
                title = title[2:].strip()

            # Parse metadata line
            if idx + 1 >= len(lines):
                idx += 1
                continue

            meta_match = self.METADATA_PATTERN.match(lines[idx + 1])
            if meta_match:
                uses = int(meta_match.group(1))
                velocity = float(meta_match.group(2)) if meta_match.group(2) else 0.0
            else:
                uses = 0
                velocity = 0.0

            lessons.append(LessonSummary(
                id=lesson_id,
                title=title,
                uses=uses,
                velocity=velocity,
                level=level,
            ))

            idx += 1

        return lessons

    def _parse_handoffs_file(
        self, file_path: Path, project_path: str = ""
    ) -> List[HandoffSummary]:
        """
        Parse handoffs from a HANDOFFS.md file.

        Args:
            file_path: Path to the handoffs file
            project_path: Project path to set on each handoff

        Returns:
            List of HandoffSummary objects
        """
        if not file_path.exists():
            return []

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []

        handoffs = []
        lines = content.split("\n")

        idx = 0
        while idx < len(lines):
            header_match = self.HANDOFF_HEADER_PATTERN.match(lines[idx])
            if not header_match:
                idx += 1
                continue

            handoff_id = header_match.group(1)
            title = header_match.group(2).strip()

            # Parse status line
            status = "unknown"
            phase = "unknown"
            agent = "user"
            created = ""
            updated = ""
            description = ""
            tried_steps: List[TriedStep] = []
            next_steps: List[str] = []
            refs: List[str] = []
            checkpoint = ""
            blocked_by: List[str] = []

            # Handoff context fields
            in_context_section = False
            context_git_ref = ""
            context_summary = ""
            context_critical_files: List[str] = []
            context_recent_changes: List[str] = []
            context_learnings: List[str] = []
            context_blockers: List[str] = []

            # Current parsing section
            in_tried_section = False
            in_next_section = False

            # Scan lines until next header or end of file
            scan_idx = idx + 1
            while scan_idx < len(lines):
                line = lines[scan_idx]

                # Check if we hit the next handoff header
                if self.HANDOFF_HEADER_PATTERN.match(line):
                    break

                # Parse status line (includes agent)
                status_match = self.HANDOFF_STATUS_PATTERN.match(line)
                if status_match:
                    status = status_match.group(1)
                    phase = status_match.group(2)
                    if status_match.group(3):
                        agent = status_match.group(3)
                    in_tried_section = False
                    in_next_section = False
                    in_context_section = False
                    scan_idx += 1
                    continue

                # Parse dates
                dates_match = self.HANDOFF_DATES_PATTERN.search(line)
                if dates_match:
                    created = dates_match.group(1)
                    updated = dates_match.group(2)
                    scan_idx += 1
                    continue

                # Parse blocked_by
                blocked_by_match = self.HANDOFF_BLOCKED_BY_PATTERN.match(line)
                if blocked_by_match:
                    blocked_by_str = blocked_by_match.group(1).strip()
                    if blocked_by_str:
                        blocked_by = [
                            b.strip() for b in blocked_by_str.split(",") if b.strip()
                        ]
                    scan_idx += 1
                    continue

                # Parse description
                desc_match = self.HANDOFF_DESCRIPTION_PATTERN.match(line)
                if desc_match:
                    description = desc_match.group(1).strip()
                    in_tried_section = False
                    in_next_section = False
                    in_context_section = False
                    scan_idx += 1
                    continue

                # Parse tried header
                if self.HANDOFF_TRIED_HEADER_PATTERN.match(line):
                    in_tried_section = True
                    in_next_section = False
                    in_context_section = False
                    scan_idx += 1
                    continue

                # Parse tried step
                if in_tried_section:
                    step_match = self.HANDOFF_TRIED_STEP_PATTERN.match(line)
                    if step_match:
                        tried_steps.append(TriedStep(
                            outcome=step_match.group(1),
                            description=step_match.group(2).strip(),
                        ))
                        scan_idx += 1
                        continue
                    # Empty line or non-step line ends tried section
                    if line.strip() and not line.startswith(" "):
                        in_tried_section = False

                # Parse next header (may have inline text after colon)
                next_header_match = self.HANDOFF_NEXT_HEADER_PATTERN.match(line)
                if next_header_match:
                    in_tried_section = False
                    in_next_section = True
                    in_context_section = False
                    # Capture inline text if present (e.g., "**Next**: Do this thing")
                    inline_text = next_header_match.group(1).strip()
                    if inline_text and inline_text not in ("-", "--", "---"):
                        next_steps.append(inline_text)
                    scan_idx += 1
                    continue

                # Parse next step
                if in_next_section:
                    next_match = self.HANDOFF_NEXT_STEP_PATTERN.match(line)
                    if next_match:
                        next_steps.append(next_match.group(1).strip())
                        scan_idx += 1
                        continue
                    # Empty line or non-step line ends next section
                    if line.strip() and not line.startswith(" "):
                        in_next_section = False

                # Parse refs
                refs_match = self.HANDOFF_REFS_PATTERN.match(line)
                if refs_match:
                    refs_str = refs_match.group(1).strip()
                    if refs_str:
                        # Split by comma and clean up
                        refs = [r.strip() for r in refs_str.split(",") if r.strip()]
                    in_tried_section = False
                    in_next_section = False
                    in_context_section = False
                    scan_idx += 1
                    continue

                # Parse checkpoint
                chk_match = self.HANDOFF_CHECKPOINT_PATTERN.match(line)
                if chk_match:
                    checkpoint = chk_match.group(1).strip()
                    in_tried_section = False
                    in_next_section = False
                    in_context_section = False
                    scan_idx += 1
                    continue

                # Parse Handoff Context header
                if self.HANDOFF_CONTEXT_HEADER_PATTERN.match(line):
                    in_tried_section = False
                    in_next_section = False
                    in_context_section = True
                    scan_idx += 1
                    continue

                # Parse Handoff Context fields when in context section
                if in_context_section:
                    # Git Ref
                    git_ref_match = self.HANDOFF_CONTEXT_GIT_REF_PATTERN.match(line)
                    if git_ref_match:
                        context_git_ref = git_ref_match.group(1).strip()
                        scan_idx += 1
                        continue

                    # Summary
                    summary_match = self.HANDOFF_CONTEXT_SUMMARY_PATTERN.match(line)
                    if summary_match:
                        context_summary = summary_match.group(1).strip()
                        scan_idx += 1
                        continue

                    # Critical Files
                    cf_match = self.HANDOFF_CONTEXT_CRITICAL_FILES_PATTERN.match(line)
                    if cf_match:
                        cf_str = cf_match.group(1).strip()
                        if cf_str:
                            context_critical_files = [
                                f.strip() for f in cf_str.split(",") if f.strip()
                            ]
                        scan_idx += 1
                        continue

                    # Recent Changes
                    rc_match = self.HANDOFF_CONTEXT_RECENT_CHANGES_PATTERN.match(line)
                    if rc_match:
                        rc_str = rc_match.group(1).strip()
                        if rc_str:
                            context_recent_changes = [
                                c.strip() for c in rc_str.split(",") if c.strip()
                            ]
                        scan_idx += 1
                        continue

                    # Learnings
                    learn_match = self.HANDOFF_CONTEXT_LEARNINGS_PATTERN.match(line)
                    if learn_match:
                        learn_str = learn_match.group(1).strip()
                        if learn_str:
                            context_learnings = [
                                l.strip() for l in learn_str.split(",") if l.strip()
                            ]
                        scan_idx += 1
                        continue

                    # Blockers (within context)
                    blk_match = self.HANDOFF_CONTEXT_BLOCKERS_PATTERN.match(line)
                    if blk_match:
                        blk_str = blk_match.group(1).strip()
                        if blk_str:
                            context_blockers = [
                                b.strip() for b in blk_str.split(",") if b.strip()
                            ]
                        scan_idx += 1
                        continue

                    # Non-context line ends context section
                    if line.strip() and not line.startswith(" ") and not line.startswith("-"):
                        in_context_section = False

                scan_idx += 1

            # Build HandoffContext if we have any context data
            handoff_context: Optional[HandoffContextSummary] = None
            if context_git_ref or context_summary:
                handoff_context = HandoffContextSummary(
                    summary=context_summary,
                    critical_files=context_critical_files,
                    recent_changes=context_recent_changes,
                    learnings=context_learnings,
                    blockers=context_blockers,
                    git_ref=context_git_ref,
                )

            handoffs.append(HandoffSummary(
                id=handoff_id,
                title=title,
                status=status,
                phase=phase,
                created=created,
                updated=updated,
                project=project_path,
                agent=agent,
                description=description,
                tried_steps=tried_steps,
                next_steps=next_steps,
                refs=refs,
                checkpoint=checkpoint,
                blocked_by=blocked_by,
                handoff=handoff_context,
            ))

            idx = scan_idx

        return handoffs

    def get_lessons(self, project_root: Optional[Path] = None) -> List[LessonSummary]:
        """
        Get all lessons (system + project).

        Args:
            project_root: Override project root (for testing)

        Returns:
            List of LessonSummary objects
        """
        lessons = []

        # System lessons
        lessons.extend(self._parse_lessons_file(self.system_lessons_file, "system"))

        # Project lessons
        project_file = (
            self._find_lessons_file(project_root)
            if project_root
            else self.project_lessons_file
        )

        if project_file:
            lessons.extend(self._parse_lessons_file(project_file, "project"))

        return lessons

    def get_system_lessons(self) -> List[LessonSummary]:
        """
        Get system-level lessons only.

        Returns:
            List of system LessonSummary objects
        """
        return self._parse_lessons_file(self.system_lessons_file, "system")

    def get_project_lessons(self, project_root: Optional[Path] = None) -> List[LessonSummary]:
        """
        Get project-level lessons only.

        Args:
            project_root: Override project root (for testing)

        Returns:
            List of project LessonSummary objects
        """
        project_file = (
            self._find_lessons_file(project_root)
            if project_root
            else self.project_lessons_file
        )

        if not project_file:
            return []

        return self._parse_lessons_file(project_file, "project")

    def get_handoffs(self, project_root: Optional[Path] = None) -> List[HandoffSummary]:
        """
        Get all handoffs from the project.

        Args:
            project_root: Override project root (for testing)

        Returns:
            List of HandoffSummary objects
        """
        handoffs_file = (
            self._find_handoffs_file(project_root)
            if project_root
            else self.project_handoffs_file
        )

        if not handoffs_file:
            return []

        return self._parse_handoffs_file(handoffs_file)

    def get_active_handoffs(self, project_root: Optional[Path] = None) -> List[HandoffSummary]:
        """
        Get active (non-completed) handoffs.

        Args:
            project_root: Override project root (for testing)

        Returns:
            List of active HandoffSummary objects
        """
        handoffs = self.get_handoffs(project_root)
        return [h for h in handoffs if h.is_active]

    def get_decay_info(self) -> DecayInfo:
        """
        Get decay state information.

        Returns:
            DecayInfo with last decay date and session count
        """
        if not self.decay_state_file.exists():
            return DecayInfo(decay_state_exists=False)

        try:
            content = self.decay_state_file.read_text(encoding="utf-8", errors="replace").strip()
            last_decay_date = content if content else None

            # Count sessions since last decay
            sessions_since = 0
            session_state_dir = self.state_dir / "sessions"
            if session_state_dir.exists() and self.decay_state_file.exists():
                decay_mtime = self.decay_state_file.stat().st_mtime
                for session_file in session_state_dir.iterdir():
                    if session_file.stat().st_mtime > decay_mtime:
                        sessions_since += 1

            return DecayInfo(
                last_decay_date=last_decay_date,
                sessions_since_decay=sessions_since,
                decay_state_exists=True,
            )

        except OSError:
            return DecayInfo(decay_state_exists=False)

    def get_lesson_counts(self, project_root: Optional[Path] = None) -> dict:
        """
        Get counts of lessons by level.

        Args:
            project_root: Override project root (for testing)

        Returns:
            Dict with 'system', 'project', and 'total' counts
        """
        lessons = self.get_lessons(project_root)
        return self._analytics.compute_lesson_counts(lessons)

    def get_handoff_counts(self, project_root: Optional[Path] = None) -> dict:
        """
        Get counts of handoffs by status.

        Args:
            project_root: Override project root (for testing)

        Returns:
            Dict with status counts and 'total'
        """
        handoffs = self.get_handoffs(project_root)

        counts = {
            "not_started": 0,
            "in_progress": 0,
            "blocked": 0,
            "ready_for_review": 0,
            "completed": 0,
            "total": len(handoffs),
        }

        for h in handoffs:
            if h.status in counts:
                counts[h.status] += 1

        return counts

    def get_all_handoffs(
        self, project_roots: Optional[List[Path]] = None
    ) -> List[HandoffSummary]:
        """
        Get all handoffs from multiple projects.

        Args:
            project_roots: List of project root paths to scan.
                          If None, returns empty list.

        Returns:
            List of HandoffSummary objects from all projects,
            with project field populated.
        """
        if not project_roots:
            return []

        all_handoffs = []

        for project_root in project_roots:
            handoffs_file = self._find_handoffs_file(project_root)
            if handoffs_file and handoffs_file.exists():
                handoffs = self._parse_handoffs_file(
                    handoffs_file, project_path=str(project_root)
                )
                all_handoffs.extend(handoffs)

        return all_handoffs

    def get_handoff_stats(self, handoffs: List[HandoffSummary]) -> dict:
        """
        Compute statistics from a list of handoffs.

        Args:
            handoffs: List of HandoffSummary objects

        Returns:
            Dict with computed statistics:
            - total_count: Total number of handoffs
            - active_count: Number of non-completed handoffs
            - blocked_count: Number of blocked handoffs
            - stale_count: Number of handoffs not updated in >7 days
            - by_status: Dict mapping status to count
            - by_phase: Dict mapping phase to count
            - age_stats: Dict with min_age_days, max_age_days, avg_age_days
        """
        return self._analytics.compute_handoff_stats(handoffs)
