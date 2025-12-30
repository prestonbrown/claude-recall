#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Python lessons manager - Tool-agnostic AI coding agent lessons system.

This module provides a LessonsManager class for managing lessons stored in markdown
format. It supports both project-level (L###) and system-level (S###) lessons with
dual-dimension star ratings based on total uses and recent velocity.

Storage locations:
  System:  ~/.config/coding-agent-lessons/LESSONS.md
  Project: <project_root>/.coding-agent-lessons/LESSONS.md

Usage:
  from core.lessons_manager import LessonsManager, Lesson, LessonRating

  manager = LessonsManager(lessons_base, project_root)
  manager.add_lesson("project", "pattern", "Title", "Content")
  manager.cite_lesson("L001")
"""

import argparse
import fcntl
import math
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum
from pathlib import Path
from typing import List, Optional, Union

# Handle both module import and direct script execution
try:
    from core.debug_logger import get_logger
except ImportError:
    from debug_logger import get_logger


# =============================================================================
# Constants
# =============================================================================

SYSTEM_PROMOTION_THRESHOLD = 50
STALE_DAYS_DEFAULT = 60
MAX_USES = 100
ROBOT_EMOJI = "\U0001f916"  # Robot emoji for AI lessons

# Velocity decay constants
VELOCITY_DECAY_FACTOR = 0.5  # 50% half-life per decay cycle
VELOCITY_EPSILON = 0.01  # Below this, treat velocity as zero

# Approach visibility constants
APPROACH_MAX_COMPLETED = 3  # Keep last N completed approaches visible
APPROACH_MAX_AGE_DAYS = 7  # Or completed within N days

# Relevance scoring constants
SCORE_RELEVANCE_TIMEOUT = 30  # Default timeout for Haiku call
SCORE_RELEVANCE_MAX_QUERY_LEN = 5000  # Truncate query to prevent huge prompts


# =============================================================================
# Enums
# =============================================================================


class LessonLevel(str, Enum):
    """Lesson scope level."""
    PROJECT = "project"
    SYSTEM = "system"


class LessonCategory(str, Enum):
    """Lesson category types."""
    PATTERN = "pattern"
    CORRECTION = "correction"
    DECISION = "decision"
    GOTCHA = "gotcha"
    PREFERENCE = "preference"


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class Lesson:
    """Represents a single lesson entry."""
    id: str
    title: str
    content: str
    uses: int
    velocity: float
    learned: date
    last_used: date
    category: str
    source: str = "human"  # 'human' or 'ai'
    level: str = "project"  # 'project' or 'system'
    promotable: bool = True  # False = never promote to system level

    @property
    def tokens(self) -> int:
        """Estimate token count for this lesson (title + content)."""
        # Rough estimate: ~4 characters per token for English text
        # Add some overhead for formatting (metadata, markdown, etc.)
        text_length = len(self.title) + len(self.content)
        overhead = 20  # Approximate overhead for ID, rating, category, etc.
        return (text_length // 4) + overhead

    def is_stale(self, stale_days: int = STALE_DAYS_DEFAULT) -> bool:
        """Check if the lesson is stale (not cited in stale_days)."""
        days_since = (date.today() - self.last_used).days
        return days_since >= stale_days


@dataclass
class LessonRating:
    """Dual-dimension lesson rating display."""
    uses: int
    velocity: float

    def format(self) -> str:
        """Format the rating as [total|velocity]."""
        left = self._uses_to_stars()
        right = self._velocity_to_indicator()
        return f"[{left}|{right}]"

    def _uses_to_stars(self) -> str:
        """Convert uses to logarithmic star scale."""
        # 1-2=*, 3-5=**, 6-12=***, 13-30=****, 31+=*****
        if self.uses >= 31:
            return "*****"
        elif self.uses >= 13:
            return "****-"
        elif self.uses >= 6:
            return "***--"
        elif self.uses >= 3:
            return "**---"
        elif self.uses >= 1:
            return "*----"
        else:
            return "-----"

    def _velocity_to_indicator(self) -> str:
        """Convert velocity to activity indicator."""
        if self.velocity >= 4.5:
            return "****+"
        elif self.velocity >= 3.5:
            return "***--"
        elif self.velocity >= 2.5:
            return "**---"
        elif self.velocity >= 1.5:
            return "*----"
        elif self.velocity >= 0.5:
            return "+----"
        else:
            return "-----"

    @staticmethod
    def calculate(uses: int, velocity: float) -> str:
        """Static method to calculate rating string."""
        return LessonRating(uses=uses, velocity=velocity).format()


@dataclass
class CitationResult:
    """Result of citing a lesson."""
    success: bool
    lesson_id: str
    uses: int
    velocity: float
    promotion_ready: bool = False
    message: str = ""


@dataclass
class InjectionResult:
    """Result of context injection."""
    top_lessons: List[Lesson]
    all_lessons: List[Lesson]
    total_count: int
    system_count: int
    project_count: int

    def format(self) -> str:
        """Format injection result for display."""
        if not self.all_lessons:
            return ""

        lines = [
            f"LESSONS ACTIVE: {self.system_count} system (S###), {self.project_count} project (L###)",
            "Cite with [L###] or [S###] when applying. Type LESSON: to add new.",
            "",
            "TOP LESSONS:"
        ]

        for lesson in self.top_lessons:
            rating = LessonRating.calculate(lesson.uses, lesson.velocity)
            prefix = f"{ROBOT_EMOJI} " if lesson.source == "ai" else ""
            lines.append(f"  [{lesson.id}] {rating} {prefix}{lesson.title}")
            if lesson.content:
                lines.append(f"    -> {lesson.content}")

        remaining = [l for l in self.all_lessons if l not in self.top_lessons]
        if remaining:
            lines.append("")
            lines.append("OTHER LESSONS (cite to use):")
            for lesson in remaining:
                rating = LessonRating.calculate(lesson.uses, lesson.velocity)
                prefix = f"{ROBOT_EMOJI} " if lesson.source == "ai" else ""
                lines.append(f"  [{lesson.id}] {rating} {prefix}{lesson.title}")
            lines.append("")
            lines.append("TIP: If asked about a topic, search all content: lessons list --search <term>")

        return "\n".join(lines)


@dataclass
class DecayResult:
    """Result of decay operation."""
    decayed_uses: int
    decayed_velocity: int
    sessions_since_last: int
    skipped: bool = False
    message: str = ""


@dataclass
class TriedApproach:
    """Represents a tried approach within an Approach."""
    outcome: str  # success|fail|partial
    description: str


@dataclass
class Approach:
    """Represents an active approach being tracked."""
    id: str
    title: str
    status: str  # not_started|in_progress|blocked|completed
    created: date
    updated: date
    description: str = ""
    next_steps: str = ""
    phase: str = "research"  # research|planning|implementing|review
    agent: str = "user"  # explore|general-purpose|plan|review|user
    files: List[str] = field(default_factory=list)
    tried: List[TriedApproach] = field(default_factory=list)
    code_snippets: List[str] = field(default_factory=list)
    checkpoint: str = ""  # Progress summary from PreCompact hook
    last_session: Optional[date] = None  # When checkpoint was last updated


@dataclass
class ApproachCompleteResult:
    """Result of completing an approach."""
    approach: Approach
    extraction_prompt: str


@dataclass
class ScoredLesson:
    """A lesson with a relevance score."""
    lesson: Lesson
    score: int  # 0-10 relevance score


@dataclass
class RelevanceResult:
    """Result of relevance scoring."""
    scored_lessons: List[ScoredLesson]
    query_text: str
    error: Optional[str] = None

    def format(self, top_n: int = 10, min_score: int = 0) -> str:
        """Format scored lessons for display.

        Args:
            top_n: Maximum number of lessons to show
            min_score: Minimum relevance score to include (0-10)
        """
        if self.error:
            return f"Error: {self.error}"
        if not self.scored_lessons:
            return "(no lessons to score)"

        # Filter by min_score, then take top_n
        filtered = [sl for sl in self.scored_lessons if sl.score >= min_score]
        if not filtered:
            return f"(no lessons with relevance >= {min_score})"

        lines = []
        for sl in filtered[:top_n]:
            rating = LessonRating.calculate(sl.lesson.uses, sl.lesson.velocity)
            prefix = f"{ROBOT_EMOJI} " if sl.lesson.source == "ai" else ""
            lines.append(f"[{sl.lesson.id}] {rating} (relevance: {sl.score}/10) {prefix}{sl.lesson.title}")
            lines.append(f"    -> {sl.lesson.content}")
        return "\n".join(lines)


# =============================================================================
# Parsing Functions
# =============================================================================

# Regex patterns for parsing lessons
LESSON_HEADER_PATTERN = re.compile(
    r"^###\s*\[([LS]\d{3})\]\s*\[([^\]]+)\]\s*(.+)$"
)
# Support both old format (/) and new format (|)
LESSON_HEADER_PATTERN_FLEXIBLE = re.compile(
    r"^###\s*\[([LS]\d{3})\]\s*\[([*+\-|/\ ]+)\]\s*(.*)$"
)
METADATA_PATTERN = re.compile(
    r"^\s*-\s*\*\*Uses\*\*:\s*(\d+)"
    r"(?:\s*\|\s*\*\*Velocity\*\*:\s*([\d.]+))?"
    r"\s*\|\s*\*\*Learned\*\*:\s*(\d{4}-\d{2}-\d{2})"
    r"\s*\|\s*\*\*Last\*\*:\s*(\d{4}-\d{2}-\d{2})"
    r"\s*\|\s*\*\*Category\*\*:\s*(\w+)"
    r"(?:\s*\|\s*\*\*Source\*\*:\s*(\w+))?"
)
CONTENT_PATTERN = re.compile(r"^>\s*(.*)$")


def parse_lesson(lines: List[str], start_idx: int, level: str) -> Optional[tuple]:
    """
    Parse a lesson from a list of lines starting at start_idx.

    Returns:
        Tuple of (Lesson, end_idx) or None if parsing fails.
    """
    if start_idx >= len(lines):
        return None

    header_line = lines[start_idx]
    match = LESSON_HEADER_PATTERN_FLEXIBLE.match(header_line)
    if not match:
        return None

    lesson_id = match.group(1)
    title = match.group(3).strip()

    # Remove robot emoji from title if present (it's stored in source field)
    if title.startswith(ROBOT_EMOJI):
        title = title[len(ROBOT_EMOJI):].strip()

    # Parse metadata line
    if start_idx + 1 >= len(lines):
        return None

    meta_line = lines[start_idx + 1]
    meta_match = METADATA_PATTERN.match(meta_line)
    if not meta_match:
        # Try to parse old format without Velocity
        old_meta_pattern = re.compile(
            r"^\s*-\s*\*\*Uses\*\*:\s*(\d+)"
            r"\s*\|\s*\*\*Learned\*\*:\s*(\d{4}-\d{2}-\d{2})"
            r"\s*\|\s*\*\*Last\*\*:\s*(\d{4}-\d{2}-\d{2})"
            r"\s*\|\s*\*\*Category\*\*:\s*(\w+)"
            r"(?:\s*\|\s*\*\*Source\*\*:\s*(\w+))?"
        )
        old_match = old_meta_pattern.match(meta_line)
        if not old_match:
            return None
        try:
            uses = int(old_match.group(1))
            velocity = 0.0
            learned = date.fromisoformat(old_match.group(2))
            last_used = date.fromisoformat(old_match.group(3))
            category = old_match.group(4)
            source = old_match.group(5) or "human"
        except ValueError:
            return None  # Malformed date, skip this lesson
    else:
        try:
            uses = int(meta_match.group(1))
            velocity = float(meta_match.group(2)) if meta_match.group(2) else 0.0
            learned = date.fromisoformat(meta_match.group(3))
            last_used = date.fromisoformat(meta_match.group(4))
            category = meta_match.group(5)
            source = meta_match.group(6) or "human"
        except ValueError:
            return None  # Malformed data, skip this lesson

    # Check for promotable flag (defaults to True if not present)
    promotable = "**Promotable**: no" not in meta_line

    # Parse content line
    content = ""
    end_idx = start_idx + 2
    if end_idx < len(lines):
        content_match = CONTENT_PATTERN.match(lines[end_idx])
        if content_match:
            content = content_match.group(1)
            end_idx += 1

    # Skip blank lines until next lesson or EOF
    while end_idx < len(lines) and not lines[end_idx].strip():
        end_idx += 1

    lesson = Lesson(
        id=lesson_id,
        title=title,
        content=content,
        uses=uses,
        velocity=velocity,
        learned=learned,
        last_used=last_used,
        category=category,
        source=source,
        level=level,
        promotable=promotable,
    )

    return (lesson, end_idx)


def format_lesson(lesson: Lesson) -> str:
    """Format a lesson for markdown storage."""
    rating = LessonRating.calculate(lesson.uses, lesson.velocity)

    # Add robot emoji for AI lessons
    title_display = f"{ROBOT_EMOJI} {lesson.title}" if lesson.source == "ai" else lesson.title

    header = f"### [{lesson.id}] {rating} {title_display}"

    # Build metadata line
    meta_parts = [
        f"**Uses**: {lesson.uses}",
        f"**Velocity**: {lesson.velocity}",
        f"**Learned**: {lesson.learned.isoformat()}",
        f"**Last**: {lesson.last_used.isoformat()}",
        f"**Category**: {lesson.category}",
    ]
    if lesson.source == "ai":
        meta_parts.append("**Source**: ai")
    if not lesson.promotable:
        meta_parts.append("**Promotable**: no")

    meta_line = f"- {' | '.join(meta_parts)}"
    content_line = f"> {lesson.content}"

    return f"{header}\n{meta_line}\n{content_line}\n"


# =============================================================================
# File Locking Context Manager
# =============================================================================


class FileLock:
    """Context manager for file locking."""

    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.lock_path = file_path.with_suffix(file_path.suffix + ".lock")
        self.lock_file = None

    def __enter__(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_file = open(self.lock_path, 'w')
        fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.lock_file:
            fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_UN)
            self.lock_file.close()
            # Note: We don't delete the lock file to avoid race conditions
            # with other processes trying to acquire the lock. The lock file
            # is just an empty marker file, so leaving it is harmless.
        return False


# =============================================================================
# LessonsManager Class
# =============================================================================


class LessonsManager:
    """
    Manager for AI coding agent lessons.

    Provides methods to add, cite, edit, delete, promote, and list lessons
    stored in markdown format.
    """

    def __init__(self, lessons_base: Path, project_root: Path):
        """
        Initialize the lessons manager.

        Args:
            lessons_base: Base directory for system lessons (~/.config/coding-agent-lessons)
            project_root: Root directory of the project (containing .git)
        """
        self.lessons_base = Path(lessons_base)
        self.project_root = Path(project_root)

        self.system_lessons_file = self.lessons_base / "LESSONS.md"
        self.project_lessons_file = self.project_root / ".coding-agent-lessons" / "LESSONS.md"

        self._decay_state_file = self.lessons_base / ".decay-last-run"
        self._session_state_dir = self.lessons_base / ".citation-state"

        # Ensure directories exist for both lessons files
        self.system_lessons_file.parent.mkdir(parents=True, exist_ok=True)
        self.project_lessons_file.parent.mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------------------------------
    # File Initialization
    # -------------------------------------------------------------------------

    def init_lessons_file(self, level: str) -> None:
        """
        Initialize a lessons file with header if it doesn't exist.

        Args:
            level: 'project' or 'system'
        """
        if level == "system":
            file_path = self.system_lessons_file
            prefix = "S"
            level_cap = "System"
        else:
            file_path = self.project_lessons_file
            prefix = "L"
            level_cap = "Project"

        file_path.parent.mkdir(parents=True, exist_ok=True)

        if file_path.exists():
            return

        header = f"""# LESSONS.md - {level_cap} Level

> **Lessons System**: Cite lessons with [{prefix}###] when applying them.
> Stars accumulate with each use. At 50 uses, project lessons promote to system.
>
> **Add lessons**: `LESSON: [category:] title - content`
> **Categories**: pattern, correction, decision, gotcha, preference

## Active Lessons

"""
        file_path.write_text(header)

    # -------------------------------------------------------------------------
    # Lesson Operations
    # -------------------------------------------------------------------------

    def add_lesson(
        self,
        level: str,
        category: str,
        title: str,
        content: str,
        source: str = "human",
        force: bool = False,
        promotable: bool = True,
    ) -> str:
        """
        Add a new lesson.

        Args:
            level: 'project' or 'system'
            category: Lesson category (pattern, correction, decision, gotcha, preference)
            title: Lesson title
            content: Lesson content
            source: 'human' or 'ai'
            force: If True, bypass duplicate detection
            promotable: If False, lesson will never be promoted to system level

        Returns:
            The assigned lesson ID (e.g., 'L001' or 'S001')

        Raises:
            ValueError: If a similar lesson already exists (and force=False)
        """
        if level == "system":
            file_path = self.system_lessons_file
            prefix = "S"
        else:
            file_path = self.project_lessons_file
            prefix = "L"

        self.init_lessons_file(level)

        with FileLock(file_path):
            # Check for duplicates
            if not force:
                duplicate = self._check_duplicate(title, file_path)
                if duplicate:
                    raise ValueError(f"Similar lesson already exists: '{duplicate}'")

            # Get next ID
            lesson_id = self._get_next_id(file_path, prefix)

            # Create lesson
            today = date.today()
            lesson = Lesson(
                id=lesson_id,
                title=title,
                content=content,
                uses=1,
                velocity=0,
                learned=today,
                last_used=today,
                category=category,
                source=source,
                level=level,
                promotable=promotable,
            )

            # Append to file
            formatted = format_lesson(lesson)
            with open(file_path, "a") as f:
                f.write("\n" + formatted + "\n")

        # Log lesson added
        logger = get_logger()
        logger.lesson_added(
            lesson_id=lesson_id,
            level=level,
            category=category,
            source=source,
            title_length=len(title),
            content_length=len(content),
        )

        return lesson_id

    def add_ai_lesson(
        self,
        level: str,
        category: str,
        title: str,
        content: str,
        promotable: bool = True,
    ) -> str:
        """
        Convenience method to add an AI-generated lesson.

        Args:
            level: 'project' or 'system'
            category: Lesson category
            title: Lesson title
            content: Lesson content
            promotable: If False, lesson will never be promoted to system level

        Returns:
            The assigned lesson ID
        """
        return self.add_lesson(
            level, category, title, content, source="ai", promotable=promotable
        )

    def get_lesson(self, lesson_id: str) -> Optional[Lesson]:
        """
        Get a lesson by ID.

        Args:
            lesson_id: The lesson ID (e.g., 'L001' or 'S001')

        Returns:
            The Lesson object, or None if not found.
        """
        level = "system" if lesson_id.startswith("S") else "project"
        file_path = self.system_lessons_file if level == "system" else self.project_lessons_file

        if not file_path.exists():
            return None

        lessons = self._parse_lessons_file(file_path, level)
        for lesson in lessons:
            if lesson.id == lesson_id:
                return lesson

        return None

    def cite_lesson(self, lesson_id: str) -> CitationResult:
        """
        Cite a lesson, incrementing its use count and velocity.

        Args:
            lesson_id: The lesson ID to cite

        Returns:
            CitationResult with updated metrics

        Raises:
            ValueError: If the lesson is not found
        """
        level = "system" if lesson_id.startswith("S") else "project"
        file_path = self.system_lessons_file if level == "system" else self.project_lessons_file

        if not file_path.exists():
            raise ValueError(f"Lesson {lesson_id} not found")

        with FileLock(file_path):
            lessons = self._parse_lessons_file(file_path, level)

            target = None
            for lesson in lessons:
                if lesson.id == lesson_id:
                    target = lesson
                    break

            if target is None:
                raise ValueError(f"Lesson {lesson_id} not found")

            # Capture old values for logging
            uses_before = target.uses
            velocity_before = target.velocity

            # Update metrics (cap uses at 100)
            new_uses = min(target.uses + 1, MAX_USES)
            new_velocity = target.velocity + 1
            today = date.today()

            target.uses = new_uses
            target.velocity = new_velocity
            target.last_used = today

            # Write back all lessons
            self._write_lessons_file(file_path, lessons, level)

        promotion_ready = (
            lesson_id.startswith("L")
            and new_uses >= SYSTEM_PROMOTION_THRESHOLD
            and target.promotable
        )

        # Log citation
        logger = get_logger()
        logger.citation(
            lesson_id=lesson_id,
            uses_before=uses_before,
            uses_after=new_uses,
            velocity_before=velocity_before,
            velocity_after=new_velocity,
            promotion_ready=promotion_ready,
        )

        return CitationResult(
            success=True,
            lesson_id=lesson_id,
            uses=new_uses,
            velocity=new_velocity,
            promotion_ready=promotion_ready,
            message="OK" if not promotion_ready else f"PROMOTION_READY:{lesson_id}:{new_uses}",
        )

    def edit_lesson(self, lesson_id: str, new_content: str) -> None:
        """
        Edit a lesson's content.

        Args:
            lesson_id: The lesson ID to edit
            new_content: The new content

        Raises:
            ValueError: If the lesson is not found
        """
        level = "system" if lesson_id.startswith("S") else "project"
        file_path = self.system_lessons_file if level == "system" else self.project_lessons_file

        if not file_path.exists():
            raise ValueError(f"Lesson {lesson_id} not found")

        with FileLock(file_path):
            lessons = self._parse_lessons_file(file_path, level)

            found = False
            for lesson in lessons:
                if lesson.id == lesson_id:
                    lesson.content = new_content
                    found = True
                    break

            if not found:
                raise ValueError(f"Lesson {lesson_id} not found")

            self._write_lessons_file(file_path, lessons, level)

    def delete_lesson(self, lesson_id: str) -> None:
        """
        Delete a lesson.

        Args:
            lesson_id: The lesson ID to delete

        Raises:
            ValueError: If the lesson is not found
        """
        level = "system" if lesson_id.startswith("S") else "project"
        file_path = self.system_lessons_file if level == "system" else self.project_lessons_file

        if not file_path.exists():
            raise ValueError(f"Lesson {lesson_id} not found")

        with FileLock(file_path):
            lessons = self._parse_lessons_file(file_path, level)

            original_count = len(lessons)
            lessons = [l for l in lessons if l.id != lesson_id]

            if len(lessons) == original_count:
                raise ValueError(f"Lesson {lesson_id} not found")

            self._write_lessons_file(file_path, lessons, level)

    def promote_lesson(self, lesson_id: str) -> str:
        """
        Promote a project lesson to system scope.

        Args:
            lesson_id: The project lesson ID to promote

        Returns:
            The new system lesson ID

        Raises:
            ValueError: If not a project lesson or not found
        """
        if not lesson_id.startswith("L"):
            raise ValueError("Can only promote project lessons (L###)")

        if not self.project_lessons_file.exists():
            raise ValueError(f"Lesson {lesson_id} not found")

        # Get the lesson first
        lesson = self.get_lesson(lesson_id)
        if lesson is None:
            raise ValueError(f"Lesson {lesson_id} not found")

        # Initialize system file
        self.init_lessons_file("system")

        # Step 1: Add to system file (separate lock to avoid nested locks)
        with FileLock(self.system_lessons_file):
            new_id = self._get_next_id(self.system_lessons_file, "S")
            new_lesson = Lesson(
                id=new_id,
                title=lesson.title,
                content=lesson.content,
                uses=lesson.uses,
                velocity=lesson.velocity,
                learned=lesson.learned,
                last_used=lesson.last_used,
                category=lesson.category,
                source=lesson.source,
                level="system",
            )
            system_lessons = self._parse_lessons_file(self.system_lessons_file, "system")
            system_lessons.append(new_lesson)
            self._write_lessons_file(self.system_lessons_file, system_lessons, "system")

        # Step 2: Remove from project file (separate lock)
        with FileLock(self.project_lessons_file):
            project_lessons = self._parse_lessons_file(self.project_lessons_file, "project")
            project_lessons = [l for l in project_lessons if l.id != lesson_id]
            self._write_lessons_file(self.project_lessons_file, project_lessons, "project")

        return new_id

    def list_lessons(
        self,
        scope: str = "all",
        search: Optional[str] = None,
        category: Optional[str] = None,
        stale_only: bool = False,
    ) -> List[Lesson]:
        """
        List lessons with optional filtering.

        Args:
            scope: 'all', 'project', or 'system'
            search: Search term for title/content
            category: Filter by category
            stale_only: Only return stale lessons (60+ days uncited)

        Returns:
            List of matching lessons
        """
        lessons = []

        if scope in ("all", "project") and self.project_lessons_file.exists():
            lessons.extend(self._parse_lessons_file(self.project_lessons_file, "project"))

        if scope in ("all", "system") and self.system_lessons_file.exists():
            lessons.extend(self._parse_lessons_file(self.system_lessons_file, "system"))

        # Apply filters
        if search:
            search_lower = search.lower()
            lessons = [
                l for l in lessons
                if search_lower in l.id.lower()
                or search_lower in l.title.lower()
                or search_lower in l.content.lower()
            ]

        if category:
            lessons = [l for l in lessons if l.category == category]

        if stale_only:
            lessons = [l for l in lessons if l.is_stale()]

        return lessons

    def inject_context(self, top_n: int = 5) -> InjectionResult:
        """
        Generate context injection with top lessons.

        Args:
            top_n: Number of top lessons to include

        Returns:
            InjectionResult with lessons for injection
        """
        all_lessons = self.list_lessons(scope="all")

        if not all_lessons:
            return InjectionResult(
                top_lessons=[],
                all_lessons=[],
                total_count=0,
                system_count=0,
                project_count=0,
            )

        # Sort by uses (descending)
        all_lessons.sort(key=lambda l: l.uses, reverse=True)

        top_lessons = all_lessons[:top_n]

        system_count = len([l for l in all_lessons if l.level == "system"])
        project_count = len([l for l in all_lessons if l.level == "project"])

        # Log session start
        total_tokens = sum(l.tokens for l in all_lessons)
        logger = get_logger()
        logger.session_start(
            project_root=str(self.project_root),
            lessons_base=str(self.lessons_base),
            total_lessons=len(all_lessons),
            system_count=system_count,
            project_count=project_count,
            top_lessons=[{"id": l.id, "uses": l.uses} for l in top_lessons],
            total_tokens=total_tokens,
        )

        return InjectionResult(
            top_lessons=top_lessons,
            all_lessons=all_lessons,
            total_count=len(all_lessons),
            system_count=system_count,
            project_count=project_count,
        )

    def score_relevance(
        self, query_text: str, timeout_seconds: int = SCORE_RELEVANCE_TIMEOUT
    ) -> RelevanceResult:
        """
        Score all lessons by relevance to query text using Haiku.

        Calls `claude -p --model haiku` to evaluate which lessons are most
        relevant to the given text (typically the user's first message).

        Args:
            query_text: Text to score lessons against (e.g., user's question)
            timeout_seconds: Timeout for the Haiku call

        Returns:
            RelevanceResult with lessons sorted by relevance score (descending)
        """
        # Truncate query to prevent huge prompts
        if len(query_text) > SCORE_RELEVANCE_MAX_QUERY_LEN:
            query_text = query_text[:SCORE_RELEVANCE_MAX_QUERY_LEN] + "..."

        all_lessons = self.list_lessons(scope="all")

        if not all_lessons:
            return RelevanceResult(
                scored_lessons=[],
                query_text=query_text,
            )

        # Build the prompt for Haiku
        lessons_text = "\n".join(
            f"[{lesson.id}] {lesson.title}: {lesson.content}"
            for lesson in all_lessons
        )

        prompt = f"""Score each lesson's relevance (0-10) to this query. 10 = highly relevant, 0 = not relevant.

Query: {query_text}

Lessons:
{lessons_text}

Output ONLY lines in format: ID: SCORE
Example:
L001: 8
S002: 3

No explanations, just ID: SCORE lines."""

        try:
            # Call Haiku via claude CLI
            result = subprocess.run(
                ["claude", "-p", "--model", "haiku"],
                input=prompt,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )

            if result.returncode != 0:
                return RelevanceResult(
                    scored_lessons=[],
                    query_text=query_text,
                    error=f"claude command failed: {result.stderr.strip()}",
                )

            output = result.stdout.strip()
            if not output:
                return RelevanceResult(
                    scored_lessons=[],
                    query_text=query_text,
                    error="empty response from Haiku",
                )

            # Parse the output: ID: SCORE
            lesson_map = {l.id: l for l in all_lessons}
            scored_lessons = []
            score_pattern = re.compile(r"^\[?([LS]\d{3})\]?:\s*(\d+)")

            for line in output.splitlines():
                match = score_pattern.match(line.strip())
                if match:
                    lesson_id = match.group(1)
                    score = min(10, max(0, int(match.group(2))))
                    if lesson_id in lesson_map:
                        scored_lessons.append(
                            ScoredLesson(lesson=lesson_map[lesson_id], score=score)
                        )

            # Sort by score descending, then by uses descending
            scored_lessons.sort(key=lambda sl: (-sl.score, -sl.lesson.uses))

            return RelevanceResult(
                scored_lessons=scored_lessons,
                query_text=query_text,
            )

        except subprocess.TimeoutExpired:
            return RelevanceResult(
                scored_lessons=[],
                query_text=query_text,
                error=f"Haiku call timed out after {timeout_seconds}s",
            )
        except FileNotFoundError:
            return RelevanceResult(
                scored_lessons=[],
                query_text=query_text,
                error="claude CLI not found",
            )
        except Exception as e:
            return RelevanceResult(
                scored_lessons=[],
                query_text=query_text,
                error=str(e),
            )

    def get_total_tokens(self, scope: str = "all") -> int:
        """
        Get total token count for all lessons.

        Args:
            scope: 'project', 'system', or 'all'

        Returns:
            Total estimated token count
        """
        lessons = self.list_lessons(scope=scope)
        return sum(lesson.tokens for lesson in lessons)

    def inject(self, limit: int = 5) -> str:
        """
        Generate formatted injection string with token tracking.

        Args:
            limit: Number of top lessons to include in detail

        Returns:
            Formatted string for context injection with token info
        """
        result = self.inject_context(top_n=limit)

        if not result.all_lessons:
            return ""

        # Calculate total tokens
        total_tokens = sum(lesson.tokens for lesson in result.all_lessons)

        lines = []

        # Header with counts
        lines.append(
            f"LESSONS ACTIVE: {result.system_count} system (S###), "
            f"{result.project_count} project (L###)"
        )
        lines.append("Cite with [L###] or [S###] when applying. Type LESSON: to add new.")

        # Token budget info and warning
        if total_tokens > 2000:
            lines.append("")
            lines.append(f"⚠️ CONTEXT HEAVY (~{total_tokens:,} tokens injected)")
            lines.append("Consider: completing approaches, archiving stale lessons")
        else:
            lines.append(f"(~{total_tokens:,} tokens)")

        # Top lessons section
        lines.append("")
        lines.append("TOP LESSONS:")
        for lesson in result.top_lessons:
            prefix = lesson.id[0]  # 'L' or 'S'
            rating = LessonRating(lesson.uses, lesson.velocity).format()
            lines.append(f"  [{lesson.id}] {rating} {lesson.title}")
            # Show content preview for top lessons
            content_preview = lesson.content[:100] + "..." if len(lesson.content) > 100 else lesson.content
            lines.append(f"    -> {content_preview}")

        # Other lessons (just IDs)
        other_lessons = result.all_lessons[limit:]
        if other_lessons:
            lines.append("")
            lines.append("OTHER LESSONS (cite to use):")
            for lesson in other_lessons:
                rating = LessonRating(lesson.uses, lesson.velocity).format()
                lines.append(f"  [{lesson.id}] {rating} {lesson.title}")

        # Search tip
        lines.append("")
        lines.append("TIP: If asked about a topic, search all content: lessons list --search <term>")

        # Log injection generation (level 2)
        logger = get_logger()
        logger.injection_generated(
            token_budget=total_tokens,
            lessons_included=len(result.top_lessons),
            lessons_excluded=len(other_lessons),
            included_ids=[l.id for l in result.top_lessons],
        )

        return "\n".join(lines)

    def decay_lessons(self, stale_threshold_days: int = 30) -> DecayResult:
        """
        Decay lesson metrics.

        - Velocity is halved for all lessons (50% half-life)
        - Uses is decremented by 1 for stale lessons (not cited in stale_threshold_days)
        - Skips if no coding sessions occurred since last decay (vacation mode)

        Args:
            stale_threshold_days: Days of inactivity before uses decay

        Returns:
            DecayResult with decay statistics
        """
        # Check for recent activity
        recent_sessions = self._count_recent_sessions()

        if recent_sessions == 0 and self._decay_state_file.exists():
            self._update_decay_timestamp()
            # Log skipped decay
            logger = get_logger()
            logger.decay_result(
                decayed_uses=0,
                decayed_velocity=0,
                sessions_since_last=0,
                skipped=True,
                lessons_affected=[],
            )
            return DecayResult(
                decayed_uses=0,
                decayed_velocity=0,
                sessions_since_last=0,
                skipped=True,
                message="No sessions since last decay - skipping (vacation mode)",
            )

        decayed_uses = 0
        decayed_velocity = 0

        for level, file_path in [
            ("project", self.project_lessons_file),
            ("system", self.system_lessons_file),
        ]:
            if not file_path.exists():
                continue

            with FileLock(file_path):
                lessons = self._parse_lessons_file(file_path, level)

                for lesson in lessons:
                    # Decay velocity using configured half-life
                    if lesson.velocity > VELOCITY_EPSILON:
                        old_velocity = lesson.velocity
                        lesson.velocity = round(lesson.velocity * VELOCITY_DECAY_FACTOR, 2)
                        if lesson.velocity < VELOCITY_EPSILON:
                            lesson.velocity = 0
                        if lesson.velocity != old_velocity:
                            decayed_velocity += 1

                    # Decay uses for stale lessons
                    days_since = (date.today() - lesson.last_used).days
                    if days_since > stale_threshold_days and lesson.uses > 1:
                        lesson.uses -= 1
                        decayed_uses += 1

                self._write_lessons_file(file_path, lessons, level)

        self._update_decay_timestamp()

        # Log decay result
        logger = get_logger()
        logger.decay_result(
            decayed_uses=decayed_uses,
            decayed_velocity=decayed_velocity,
            sessions_since_last=recent_sessions,
            skipped=False,
            lessons_affected=[],  # Could track individual changes if needed
        )

        return DecayResult(
            decayed_uses=decayed_uses,
            decayed_velocity=decayed_velocity,
            sessions_since_last=recent_sessions,
            skipped=False,
            message=f"Decayed: {decayed_uses} uses, {decayed_velocity} velocities ({recent_sessions} sessions since last run)",
        )

    # -------------------------------------------------------------------------
    # Helper Methods for Testing
    # -------------------------------------------------------------------------

    def _update_lesson_date(self, lesson_id: str, last_used: date) -> None:
        """Update a lesson's last-used date (for testing)."""
        level = "system" if lesson_id.startswith("S") else "project"
        file_path = self.system_lessons_file if level == "system" else self.project_lessons_file

        if not file_path.exists():
            return

        with FileLock(file_path):
            lessons = self._parse_lessons_file(file_path, level)
            for lesson in lessons:
                if lesson.id == lesson_id:
                    lesson.last_used = last_used
                    break
            self._write_lessons_file(file_path, lessons, level)

    def _set_lesson_uses(self, lesson_id: str, uses: int) -> None:
        """Set a lesson's uses count (for testing)."""
        level = "system" if lesson_id.startswith("S") else "project"
        file_path = self.system_lessons_file if level == "system" else self.project_lessons_file

        if not file_path.exists():
            return

        with FileLock(file_path):
            lessons = self._parse_lessons_file(file_path, level)
            for lesson in lessons:
                if lesson.id == lesson_id:
                    lesson.uses = uses
                    break
            self._write_lessons_file(file_path, lessons, level)

    def _set_last_decay_time(self) -> None:
        """Set the last decay timestamp (for testing)."""
        self._update_decay_timestamp()

    # -------------------------------------------------------------------------
    # Private Helper Methods
    # -------------------------------------------------------------------------

    def _normalize_title(self, title: str) -> str:
        """Normalize title for duplicate comparison."""
        import string
        # Lowercase, remove punctuation, normalize whitespace
        normalized = title.lower()
        for char in string.punctuation:
            normalized = normalized.replace(char, "")
        return " ".join(normalized.split())

    def _check_duplicate(self, title: str, file_path: Path) -> Optional[str]:
        """Check if a similar lesson already exists."""
        if not file_path.exists():
            return None

        level = "system" if file_path == self.system_lessons_file else "project"
        lessons = self._parse_lessons_file(file_path, level)

        normalized = self._normalize_title(title)

        for lesson in lessons:
            existing_norm = self._normalize_title(lesson.title)

            # Exact match
            if normalized == existing_norm:
                return lesson.title

            # Substring match (if long enough)
            if len(normalized) > 10 and normalized in existing_norm:
                return lesson.title
            if len(existing_norm) > 10 and existing_norm in normalized:
                return lesson.title

        return None

    def _get_next_id(self, file_path: Path, prefix: str) -> str:
        """Get the next available lesson ID."""
        max_id = 0

        if file_path.exists():
            level = "system" if prefix == "S" else "project"
            lessons = self._parse_lessons_file(file_path, level)
            for lesson in lessons:
                if lesson.id.startswith(prefix):
                    try:
                        num = int(lesson.id[1:])
                        max_id = max(max_id, num)
                    except ValueError:
                        pass

        return f"{prefix}{max_id + 1:03d}"

    def _parse_lessons_file(self, file_path: Path, level: str) -> List[Lesson]:
        """Parse all lessons from a file."""
        if not file_path.exists():
            return []

        content = file_path.read_text()
        lines = content.split("\n")

        lessons = []
        idx = 0

        while idx < len(lines):
            if lines[idx].startswith("### ["):
                result = parse_lesson(lines, idx, level)
                if result:
                    lesson, end_idx = result
                    lessons.append(lesson)
                    idx = end_idx
                else:
                    idx += 1
            else:
                idx += 1

        return lessons

    def _write_lessons_file(self, file_path: Path, lessons: List[Lesson], level: str) -> None:
        """Write lessons back to file."""
        # Read existing header
        header = ""
        if file_path.exists():
            content = file_path.read_text()
            # Find everything before the first lesson
            match = re.search(r"^### \[", content, re.MULTILINE)
            if match:
                header = content[:match.start()].rstrip() + "\n"
            else:
                header = content.rstrip() + "\n"
        else:
            # Generate header
            prefix = "S" if level == "system" else "L"
            level_cap = "System" if level == "system" else "Project"
            header = f"""# LESSONS.md - {level_cap} Level

> **Lessons System**: Cite lessons with [{prefix}###] when applying them.
> Stars accumulate with each use. At 50 uses, project lessons promote to system.
>
> **Add lessons**: `LESSON: [category:] title - content`
> **Categories**: pattern, correction, decision, gotcha, preference

## Active Lessons
"""

        # Build new content
        parts = [header]
        for lesson in lessons:
            parts.append("")
            parts.append(format_lesson(lesson))

        file_path.write_text("\n".join(parts))

    def _count_recent_sessions(self) -> int:
        """Count coding sessions since last decay."""
        if not self._session_state_dir.exists():
            return 0

        if not self._decay_state_file.exists():
            # First run - count all sessions
            return len(list(self._session_state_dir.iterdir()))

        decay_time = self._decay_state_file.stat().st_mtime
        count = 0
        for session_file in self._session_state_dir.iterdir():
            if session_file.stat().st_mtime > decay_time:
                count += 1

        return count

    def _update_decay_timestamp(self) -> None:
        """Update the decay timestamp file."""
        self._decay_state_file.parent.mkdir(parents=True, exist_ok=True)
        self._decay_state_file.write_text(str(date.today().isoformat()))

    # -------------------------------------------------------------------------
    # Approaches Tracking
    # -------------------------------------------------------------------------

    @property
    def project_approaches_file(self) -> Path:
        """Path to the project approaches file."""
        return self.project_root / ".coding-agent-lessons" / "APPROACHES.md"

    @property
    def project_approaches_archive(self) -> Path:
        """Path to the project approaches archive file."""
        return self.project_root / ".coding-agent-lessons" / "APPROACHES_ARCHIVE.md"

    # Valid status and outcome values
    VALID_STATUSES = {"not_started", "in_progress", "blocked", "completed"}
    VALID_OUTCOMES = {"success", "fail", "partial"}
    VALID_PHASES = {"research", "planning", "implementing", "review"}
    VALID_AGENTS = {"explore", "general-purpose", "plan", "review", "user"}

    def _init_approaches_file(self) -> None:
        """Initialize approaches file with header if it doesn't exist."""
        file_path = self.project_approaches_file
        file_path.parent.mkdir(parents=True, exist_ok=True)

        if file_path.exists():
            return

        header = """# APPROACHES.md - Active Work Tracking

> Track ongoing work with tried approaches and next steps.
> When completed, review for lessons to extract.

## Active Approaches

"""
        file_path.write_text(header)

    def _parse_approaches_file(self, file_path: Path) -> List[Approach]:
        """Parse all approaches from a file."""
        if not file_path.exists():
            return []

        content = file_path.read_text()
        if not content.strip():
            return []

        approaches = []
        lines = content.split("\n")

        # Pattern for approach header: ### [A001] Title
        header_pattern = re.compile(r"^###\s*\[([A-Z]\d{3})\]\s*(.+)$")
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
        # Pattern for files line: - **Files**: file1, file2
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

            approach_id = header_match.group(1)
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
                # Malformed - skip this approach
                continue

            # Parse files line
            files = []
            if idx < len(lines):
                files_match = files_pattern.match(lines[idx])
                if files_match:
                    files_str = files_match.group(1).strip()
                    if files_str:
                        files = [f.strip() for f in files_str.split(",") if f.strip()]
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

            # Parse code snippets (between description and **Tried**)
            code_snippets = []
            # Look for **Code**: section
            if idx < len(lines) and lines[idx].strip() == "":
                idx += 1  # Skip empty line after description
            if idx < len(lines) and lines[idx].strip().startswith("**Code**"):
                idx += 1  # Skip the **Code**: header
                # Parse fenced code blocks
                while idx < len(lines):
                    line = lines[idx]
                    if line.strip().startswith("**Tried**") or line.strip() == "---":
                        break
                    if line.startswith("```"):
                        # Start of fenced block - capture language hint
                        lang_hint = line[3:].strip()
                        code_lines = []
                        idx += 1
                        # Read until closing fence
                        while idx < len(lines) and not lines[idx].startswith("```"):
                            code_lines.append(lines[idx])
                            idx += 1
                        if idx < len(lines):
                            idx += 1  # Skip closing fence
                        # Format as fenced block with language
                        if lang_hint:
                            snippet = f"```{lang_hint}\n" + "\n".join(code_lines) + "\n```"
                        else:
                            snippet = "```\n" + "\n".join(code_lines) + "\n```"
                        code_snippets.append(snippet)
                    elif line.strip() == "":
                        idx += 1
                    else:
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
                        tried.append(TriedApproach(
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

            # Skip to separator or next approach
            while idx < len(lines) and lines[idx].strip() != "---":
                idx += 1
            idx += 1  # Skip the separator

            approaches.append(Approach(
                id=approach_id,
                title=title,
                status=status,
                created=created,
                updated=updated,
                files=files,
                description=description,
                tried=tried,
                next_steps=next_steps,
                phase=phase,
                agent=agent,
                code_snippets=code_snippets,
                checkpoint=checkpoint,
                last_session=last_session,
            ))

        return approaches

    def _format_approach(self, approach: Approach) -> str:
        """Format an approach for markdown storage."""
        lines = [
            f"### [{approach.id}] {approach.title}",
            f"- **Status**: {approach.status} | **Phase**: {approach.phase} | **Agent**: {approach.agent}",
            f"- **Created**: {approach.created.isoformat()} | **Updated**: {approach.updated.isoformat()}",
            f"- **Files**: {', '.join(approach.files)}",
            f"- **Description**: {approach.description}",
        ]

        # Add checkpoint if present
        if approach.checkpoint:
            session_str = approach.last_session.isoformat() if approach.last_session else ""
            lines.append(f"- **Checkpoint**: {approach.checkpoint}")
            if session_str:
                lines.append(f"- **Last Session**: {session_str}")

        lines.append("")

        # Add code snippets section if present
        if approach.code_snippets:
            lines.append("**Code**:")
            for snippet in approach.code_snippets:
                lines.append(snippet)
            lines.append("")

        lines.append("**Tried**:")
        for i, tried in enumerate(approach.tried, 1):
            lines.append(f"{i}. [{tried.outcome}] {tried.description}")

        lines.append("")
        lines.append(f"**Next**: {approach.next_steps}")
        lines.append("")
        lines.append("---")

        return "\n".join(lines)

    def _write_approaches_file(self, approaches: List[Approach]) -> None:
        """Write approaches back to file."""
        self._init_approaches_file()

        header = """# APPROACHES.md - Active Work Tracking

> Track ongoing work with tried approaches and next steps.
> When completed, review for lessons to extract.

## Active Approaches

"""
        parts = [header]
        for approach in approaches:
            parts.append(self._format_approach(approach))
            parts.append("")

        self.project_approaches_file.write_text("\n".join(parts))

    def _get_next_approach_id(self) -> str:
        """Get the next available approach ID."""
        max_id = 0

        # Check main file
        if self.project_approaches_file.exists():
            approaches = self._parse_approaches_file(self.project_approaches_file)
            for approach in approaches:
                try:
                    num = int(approach.id[1:])
                    max_id = max(max_id, num)
                except ValueError:
                    pass

        # Also check archive to prevent ID reuse
        if self.project_approaches_archive.exists():
            content = self.project_approaches_archive.read_text()
            for match in re.finditer(r"\[A(\d{3})\]", content):
                try:
                    num = int(match.group(1))
                    max_id = max(max_id, num)
                except ValueError:
                    pass

        return f"A{max_id + 1:03d}"

    def approach_add(
        self,
        title: str,
        desc: Optional[str] = None,
        files: Optional[List[str]] = None,
        phase: str = "research",
        agent: str = "user",
    ) -> str:
        """
        Add a new approach.

        Args:
            title: Approach title
            desc: Optional description
            files: Optional list of files
            phase: Initial phase (research, planning, implementing, review)
            agent: Agent working on this (explore, general-purpose, plan, review, user)

        Returns:
            The assigned approach ID (e.g., 'A001')

        Raises:
            ValueError: If invalid phase or agent
        """
        if phase not in self.VALID_PHASES:
            raise ValueError(f"Invalid phase: {phase}")
        if agent not in self.VALID_AGENTS:
            raise ValueError(f"Invalid agent: {agent}")

        self._init_approaches_file()

        with FileLock(self.project_approaches_file):
            approaches = self._parse_approaches_file(self.project_approaches_file)
            approach_id = self._get_next_approach_id()
            today = date.today()

            approach = Approach(
                id=approach_id,
                title=title,
                status="not_started",
                created=today,
                updated=today,
                files=files or [],
                description=desc or "",
                tried=[],
                next_steps="",
                phase=phase,
                agent=agent,
            )

            approaches.append(approach)
            self._write_approaches_file(approaches)

        # Log approach created
        logger = get_logger()
        logger.approach_created(
            approach_id=approach_id,
            title=title,
            phase=phase,
            agent=agent,
        )

        return approach_id

    def approach_update_status(self, approach_id: str, status: str) -> None:
        """
        Update an approach's status.

        Args:
            approach_id: The approach ID
            status: New status (not_started, in_progress, blocked, completed)

        Raises:
            ValueError: If approach not found or invalid status
        """
        if status not in self.VALID_STATUSES:
            raise ValueError(f"Invalid status: {status}")

        old_status = None
        with FileLock(self.project_approaches_file):
            approaches = self._parse_approaches_file(self.project_approaches_file)

            found = False
            for approach in approaches:
                if approach.id == approach_id:
                    old_status = approach.status
                    approach.status = status
                    approach.updated = date.today()
                    found = True
                    break

            if not found:
                raise ValueError(f"Approach {approach_id} not found")

            self._write_approaches_file(approaches)

        # Log status change
        logger = get_logger()
        logger.approach_change(
            approach_id=approach_id,
            action="status_change",
            old_value=old_status,
            new_value=status,
        )

    def approach_update_phase(self, approach_id: str, phase: str) -> None:
        """
        Update an approach's phase.

        Args:
            approach_id: The approach ID
            phase: New phase (research, planning, implementing, review)

        Raises:
            ValueError: If approach not found or invalid phase
        """
        if phase not in self.VALID_PHASES:
            raise ValueError(f"Invalid phase: {phase}")

        old_phase = None
        with FileLock(self.project_approaches_file):
            approaches = self._parse_approaches_file(self.project_approaches_file)

            found = False
            for approach in approaches:
                if approach.id == approach_id:
                    old_phase = approach.phase
                    approach.phase = phase
                    approach.updated = date.today()
                    found = True
                    break

            if not found:
                raise ValueError(f"Approach {approach_id} not found")

            self._write_approaches_file(approaches)

        # Log phase change
        logger = get_logger()
        logger.approach_change(
            approach_id=approach_id,
            action="phase_change",
            old_value=old_phase,
            new_value=phase,
        )

    def approach_update_agent(self, approach_id: str, agent: str) -> None:
        """
        Update an approach's agent.

        Args:
            approach_id: The approach ID
            agent: New agent (explore, general-purpose, plan, review, user)

        Raises:
            ValueError: If approach not found or invalid agent
        """
        if agent not in self.VALID_AGENTS:
            raise ValueError(f"Invalid agent: {agent}")

        old_agent = None
        with FileLock(self.project_approaches_file):
            approaches = self._parse_approaches_file(self.project_approaches_file)

            found = False
            for approach in approaches:
                if approach.id == approach_id:
                    old_agent = approach.agent
                    approach.agent = agent
                    approach.updated = date.today()
                    found = True
                    break

            if not found:
                raise ValueError(f"Approach {approach_id} not found")

            self._write_approaches_file(approaches)

        # Log agent change
        logger = get_logger()
        logger.approach_change(
            approach_id=approach_id,
            action="agent_change",
            old_value=old_agent,
            new_value=agent,
        )

    def approach_add_code(
        self, approach_id: str, code: str, language: str = ""
    ) -> None:
        """
        Add a code snippet to an approach.

        Args:
            approach_id: The approach ID
            code: The code snippet content
            language: Optional language hint (python, typescript, etc.)

        Raises:
            ValueError: If approach not found
        """
        with FileLock(self.project_approaches_file):
            approaches = self._parse_approaches_file(self.project_approaches_file)

            found = False
            for approach in approaches:
                if approach.id == approach_id:
                    # Format as fenced code block
                    if language:
                        snippet = f"```{language}\n{code}\n```"
                    else:
                        snippet = f"```\n{code}\n```"
                    approach.code_snippets.append(snippet)
                    approach.updated = date.today()
                    found = True
                    break

            if not found:
                raise ValueError(f"Approach {approach_id} not found")

            self._write_approaches_file(approaches)

    def approach_add_tried(
        self,
        approach_id: str,
        outcome: str,
        description: str,
    ) -> None:
        """
        Add a tried approach.

        Args:
            approach_id: The approach ID
            outcome: success, fail, or partial
            description: Description of what was tried

        Raises:
            ValueError: If approach not found or invalid outcome
        """
        if outcome not in self.VALID_OUTCOMES:
            raise ValueError(f"Invalid outcome: {outcome}")

        with FileLock(self.project_approaches_file):
            approaches = self._parse_approaches_file(self.project_approaches_file)

            found = False
            for approach in approaches:
                if approach.id == approach_id:
                    approach.tried.append(TriedApproach(
                        outcome=outcome,
                        description=description,
                    ))
                    approach.updated = date.today()
                    found = True
                    break

            if not found:
                raise ValueError(f"Approach {approach_id} not found")

            self._write_approaches_file(approaches)

    def approach_update_next(self, approach_id: str, text: str) -> None:
        """
        Update an approach's next steps.

        Args:
            approach_id: The approach ID
            text: Next steps text

        Raises:
            ValueError: If approach not found
        """
        with FileLock(self.project_approaches_file):
            approaches = self._parse_approaches_file(self.project_approaches_file)

            found = False
            for approach in approaches:
                if approach.id == approach_id:
                    approach.next_steps = text
                    approach.updated = date.today()
                    found = True
                    break

            if not found:
                raise ValueError(f"Approach {approach_id} not found")

            self._write_approaches_file(approaches)

    def approach_update_files(self, approach_id: str, files_list: List[str]) -> None:
        """
        Update an approach's file list.

        Args:
            approach_id: The approach ID
            files_list: List of files

        Raises:
            ValueError: If approach not found
        """
        with FileLock(self.project_approaches_file):
            approaches = self._parse_approaches_file(self.project_approaches_file)

            found = False
            for approach in approaches:
                if approach.id == approach_id:
                    approach.files = files_list
                    approach.updated = date.today()
                    found = True
                    break

            if not found:
                raise ValueError(f"Approach {approach_id} not found")

            self._write_approaches_file(approaches)

    def approach_update_desc(self, approach_id: str, description: str) -> None:
        """
        Update an approach's description.

        Args:
            approach_id: The approach ID
            description: New description

        Raises:
            ValueError: If approach not found
        """
        with FileLock(self.project_approaches_file):
            approaches = self._parse_approaches_file(self.project_approaches_file)

            found = False
            for approach in approaches:
                if approach.id == approach_id:
                    approach.description = description
                    approach.updated = date.today()
                    found = True
                    break

            if not found:
                raise ValueError(f"Approach {approach_id} not found")

            self._write_approaches_file(approaches)

    def approach_update_checkpoint(self, approach_id: str, checkpoint: str) -> None:
        """
        Update an approach's checkpoint (progress summary from PreCompact hook).

        Args:
            approach_id: The approach ID
            checkpoint: Progress summary text

        Raises:
            ValueError: If approach not found
        """
        with FileLock(self.project_approaches_file):
            approaches = self._parse_approaches_file(self.project_approaches_file)

            found = False
            for approach in approaches:
                if approach.id == approach_id:
                    approach.checkpoint = checkpoint
                    approach.last_session = date.today()
                    approach.updated = date.today()
                    found = True
                    break

            if not found:
                raise ValueError(f"Approach {approach_id} not found")

            self._write_approaches_file(approaches)

    def approach_complete(self, approach_id: str) -> ApproachCompleteResult:
        """
        Mark an approach as completed and return extraction prompt.

        Args:
            approach_id: The approach ID

        Returns:
            ApproachCompleteResult with approach data and extraction prompt

        Raises:
            ValueError: If approach not found
        """
        with FileLock(self.project_approaches_file):
            approaches = self._parse_approaches_file(self.project_approaches_file)

            target = None
            for approach in approaches:
                if approach.id == approach_id:
                    target = approach
                    break

            if target is None:
                raise ValueError(f"Approach {approach_id} not found")

            target.status = "completed"
            target.updated = date.today()
            self._write_approaches_file(approaches)

        # Generate extraction prompt
        tried_summary = ""
        if target.tried:
            tried_lines = []
            for tried in target.tried:
                tried_lines.append(f"- [{tried.outcome}] {tried.description}")
            tried_summary = "\n".join(tried_lines)

        extraction_prompt = f"""Review this completed approach for potential lessons to extract:

**Title**: {target.title}
**Description**: {target.description}

**Tried approaches**:
{tried_summary if tried_summary else "(none)"}

**Files affected**: {', '.join(target.files) if target.files else "(none)"}

Consider extracting lessons about:
1. What worked and why
2. What didn't work and why
3. Patterns or gotchas discovered
4. Decisions made and their rationale
"""

        # Log approach completed
        duration_days = (date.today() - target.created).days if target.created else None
        logger = get_logger()
        logger.approach_completed(
            approach_id=approach_id,
            tried_count=len(target.tried),
            duration_days=duration_days,
        )

        return ApproachCompleteResult(
            approach=target,
            extraction_prompt=extraction_prompt,
        )

    def approach_archive(self, approach_id: str) -> None:
        """
        Archive an approach to APPROACHES_ARCHIVE.md.

        Args:
            approach_id: The approach ID

        Raises:
            ValueError: If approach not found
        """
        with FileLock(self.project_approaches_file):
            approaches = self._parse_approaches_file(self.project_approaches_file)

            target = None
            remaining = []
            for approach in approaches:
                if approach.id == approach_id:
                    target = approach
                else:
                    remaining.append(approach)

            if target is None:
                raise ValueError(f"Approach {approach_id} not found")

            # Append to archive file
            archive_file = self.project_approaches_archive
            archive_file.parent.mkdir(parents=True, exist_ok=True)

            if archive_file.exists():
                archive_content = archive_file.read_text()
            else:
                archive_content = """# APPROACHES_ARCHIVE.md - Archived Approaches

> Previously completed or archived approaches.

"""

            archive_content += "\n" + self._format_approach(target) + "\n"
            archive_file.write_text(archive_content)

            # Remove from main file
            self._write_approaches_file(remaining)

    def approach_delete(self, approach_id: str) -> None:
        """
        Delete an approach permanently (no archive).

        Args:
            approach_id: The approach ID

        Raises:
            ValueError: If approach not found
        """
        with FileLock(self.project_approaches_file):
            approaches = self._parse_approaches_file(self.project_approaches_file)

            original_count = len(approaches)
            approaches = [a for a in approaches if a.id != approach_id]

            if len(approaches) == original_count:
                raise ValueError(f"Approach {approach_id} not found")

            self._write_approaches_file(approaches)

    def approach_get(self, approach_id: str) -> Optional[Approach]:
        """
        Get an approach by ID.

        Args:
            approach_id: The approach ID

        Returns:
            The Approach object, or None if not found
        """
        if not self.project_approaches_file.exists():
            return None

        approaches = self._parse_approaches_file(self.project_approaches_file)
        for approach in approaches:
            if approach.id == approach_id:
                return approach

        return None

    def approach_list(
        self,
        status_filter: Optional[str] = None,
        include_completed: bool = False,
    ) -> List[Approach]:
        """
        List approaches with optional filtering.

        Args:
            status_filter: Filter by specific status
            include_completed: Include completed approaches (default False)

        Returns:
            List of matching approaches
        """
        if not self.project_approaches_file.exists():
            return []

        approaches = self._parse_approaches_file(self.project_approaches_file)

        if status_filter:
            approaches = [a for a in approaches if a.status == status_filter]
        elif not include_completed:
            approaches = [a for a in approaches if a.status != "completed"]

        return approaches

    def approach_list_completed(
        self,
        max_count: Optional[int] = None,
        max_age_days: Optional[int] = None,
    ) -> List[Approach]:
        """
        List completed approaches with hybrid visibility rules.

        Uses OR logic: shows approaches that are either:
        - Within the last max_count completions, OR
        - Completed within max_age_days

        Args:
            max_count: Max number of recent completions to show (default: APPROACH_MAX_COMPLETED)
            max_age_days: Max age in days for completed approaches (default: APPROACH_MAX_AGE_DAYS)

        Returns:
            List of visible completed approaches, sorted by updated date (newest first)
        """
        if max_count is None:
            max_count = APPROACH_MAX_COMPLETED
        if max_age_days is None:
            max_age_days = APPROACH_MAX_AGE_DAYS

        if not self.project_approaches_file.exists():
            return []

        approaches = self._parse_approaches_file(self.project_approaches_file)

        # Filter to completed only
        completed = [a for a in approaches if a.status == "completed"]

        if not completed:
            return []

        # Sort by updated date (newest first)
        completed.sort(key=lambda a: a.updated, reverse=True)

        # Calculate cutoff date
        cutoff_date = date.today() - timedelta(days=max_age_days)

        # Apply hybrid logic: keep if in top N OR recent enough
        visible = []
        for i, approach in enumerate(completed):
            # In top N by recency
            in_top_n = i < max_count
            # Updated within age limit
            is_recent = approach.updated >= cutoff_date

            if in_top_n or is_recent:
                visible.append(approach)

        return visible

    def approach_inject(
        self,
        max_completed: Optional[int] = None,
        max_completed_age: Optional[int] = None,
    ) -> str:
        """
        Generate context injection string with active and recent completed approaches.

        Args:
            max_completed: Max completed approaches to show (default: APPROACH_MAX_COMPLETED)
            max_completed_age: Max age in days for completed (default: APPROACH_MAX_AGE_DAYS)

        Returns:
            Formatted string for context injection, empty if no approaches
        """
        active_approaches = self.approach_list(include_completed=False)
        completed_approaches = self.approach_list_completed(
            max_count=max_completed,
            max_age_days=max_completed_age,
        )

        if not active_approaches and not completed_approaches:
            return ""

        lines = []

        # Active approaches section
        if active_approaches:
            lines.append("## Active Approaches")
            lines.append("")

            for approach in active_approaches:
                lines.append(f"### [{approach.id}] {approach.title}")
                lines.append(f"- **Status**: {approach.status} | **Phase**: {approach.phase} | **Agent**: {approach.agent}")
                if approach.files:
                    lines.append(f"- **Files**: {', '.join(approach.files)}")
                if approach.description:
                    lines.append(f"- **Description**: {approach.description}")

                # Show checkpoint prominently if present (key for session handoff)
                if approach.checkpoint:
                    session_ago = ""
                    if approach.last_session:
                        days = (date.today() - approach.last_session).days
                        if days == 0:
                            session_ago = " (today)"
                        elif days == 1:
                            session_ago = " (yesterday)"
                        else:
                            session_ago = f" ({days}d ago)"
                    lines.append(f"- **Checkpoint{session_ago}**: {approach.checkpoint}")

                # Include code snippets (truncated for injection)
                if approach.code_snippets:
                    lines.append("")
                    lines.append("**Code**:")
                    max_snippet_lines = 10  # Truncate long snippets
                    for snippet in approach.code_snippets[:2]:  # Max 2 snippets in injection
                        snippet_lines = snippet.split("\n")
                        if len(snippet_lines) > max_snippet_lines:
                            # Truncate and add indicator
                            truncated = "\n".join(snippet_lines[:max_snippet_lines])
                            # Find the closing fence if truncated
                            if not truncated.endswith("```"):
                                truncated += "\n... (truncated)\n```"
                            lines.append(truncated)
                        else:
                            lines.append(snippet)
                    if len(approach.code_snippets) > 2:
                        lines.append(f"... and {len(approach.code_snippets) - 2} more snippet(s)")

                if approach.tried:
                    lines.append("")
                    lines.append("**Tried**:")
                    for i, tried in enumerate(approach.tried, 1):
                        lines.append(f"{i}. [{tried.outcome}] {tried.description}")

                if approach.next_steps:
                    lines.append("")
                    lines.append(f"**Next**: {approach.next_steps}")

                lines.append("")

        # Recent completions section
        if completed_approaches:
            lines.append("## Recent Completions")
            lines.append("")

            for approach in completed_approaches:
                # Calculate days since completion
                days_ago = (date.today() - approach.updated).days
                if days_ago == 0:
                    time_str = "today"
                elif days_ago == 1:
                    time_str = "1d ago"
                else:
                    time_str = f"{days_ago}d ago"

                lines.append(f"  [{approach.id}] ✓ {approach.title} (completed {time_str})")

            lines.append("")

        return "\n".join(lines)


# =============================================================================
# Phase Detection Helper
# =============================================================================


def detect_phase_from_tools(tools: list) -> str:
    """
    Detect the approach phase based on tool usage patterns.

    Tool usage patterns:
    - research: Read, Grep, Glob (mostly reading/searching)
    - planning: Write to .md files, AskUserQuestion, EnterPlanMode
    - implementing: Edit, Write to code files
    - review: Bash with test/build commands

    Priority (highest to lowest): review > implementing > planning > research

    Args:
        tools: List of tool usage dicts with 'name' and optional parameters

    Returns:
        Phase string: 'research', 'planning', 'implementing', or 'review'
    """
    if not tools:
        return "research"

    # Track signals for each phase
    has_review = False
    has_implementing = False
    has_planning = False

    # Test/build command patterns
    test_patterns = ["pytest", "test", "npm run test", "npm test", "jest", "mocha"]
    build_patterns = ["npm run build", "make", "cargo build", "go build", "tsc"]

    for tool in tools:
        name = tool.get("name", "")

        # Review phase: test or build commands
        if name == "Bash":
            command = tool.get("command", "").lower()
            for pattern in test_patterns + build_patterns:
                if pattern in command:
                    has_review = True
                    break

        # Implementing phase: Edit or Write to code files
        elif name == "Edit":
            has_implementing = True

        elif name == "Write":
            file_path = tool.get("file_path", "")
            # Writing to .md files is planning, not implementing
            if file_path.endswith(".md"):
                has_planning = True
            else:
                has_implementing = True

        # Planning phase: AskUserQuestion or plan-related tools
        elif name == "AskUserQuestion":
            has_planning = True

        # EnterPlanMode indicates start of planning (research phase initially)
        elif name == "EnterPlanMode":
            # EnterPlanMode starts with research to understand the codebase
            # Don't set any flags - let it default to research
            pass

    # Apply priority: review > implementing > planning > research
    if has_review:
        return "review"
    if has_implementing:
        return "implementing"
    if has_planning:
        return "planning"

    return "research"


# =============================================================================
# CLI Interface
# =============================================================================


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Lessons Manager - Tool-agnostic AI coding agent lessons"
    )
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # add command
    add_parser = subparsers.add_parser("add", help="Add a project lesson")
    add_parser.add_argument("category", help="Lesson category")
    add_parser.add_argument("title", help="Lesson title")
    add_parser.add_argument("content", help="Lesson content")
    add_parser.add_argument("--force", action="store_true", help="Skip duplicate check")
    add_parser.add_argument("--system", action="store_true", help="Add as system lesson")
    add_parser.add_argument(
        "--no-promote", action="store_true", help="Never promote to system level"
    )

    # add-ai command
    add_ai_parser = subparsers.add_parser("add-ai", help="Add an AI-generated lesson")
    add_ai_parser.add_argument("category", help="Lesson category")
    add_ai_parser.add_argument("title", help="Lesson title")
    add_ai_parser.add_argument("content", help="Lesson content")
    add_ai_parser.add_argument("--system", action="store_true", help="Add as system lesson")
    add_ai_parser.add_argument(
        "--no-promote", action="store_true", help="Never promote to system level"
    )

    # add-system command (alias for add --system, for backward compatibility)
    add_system_parser = subparsers.add_parser(
        "add-system", help="Add a system lesson (alias for add --system)"
    )
    add_system_parser.add_argument("category", help="Lesson category")
    add_system_parser.add_argument("title", help="Lesson title")
    add_system_parser.add_argument("content", help="Lesson content")
    add_system_parser.add_argument(
        "--force", action="store_true", help="Skip duplicate check"
    )

    # cite command
    cite_parser = subparsers.add_parser("cite", help="Cite a lesson")
    cite_parser.add_argument("lesson_id", help="Lesson ID (e.g., L001)")

    # inject command
    inject_parser = subparsers.add_parser("inject", help="Output top lessons for injection")
    inject_parser.add_argument("top_n", type=int, nargs="?", default=5, help="Number of top lessons")

    # list command
    list_parser = subparsers.add_parser("list", help="List lessons")
    list_parser.add_argument("--project", action="store_true", help="Project lessons only")
    list_parser.add_argument("--system", action="store_true", help="System lessons only")
    list_parser.add_argument("--search", "-s", help="Search term")
    list_parser.add_argument("--category", "-c", help="Filter by category")
    list_parser.add_argument("--stale", action="store_true", help="Show stale lessons only")

    # decay command
    decay_parser = subparsers.add_parser("decay", help="Decay lesson metrics")
    decay_parser.add_argument("days", type=int, nargs="?", default=30, help="Stale threshold days")

    # edit command
    edit_parser = subparsers.add_parser("edit", help="Edit a lesson")
    edit_parser.add_argument("lesson_id", help="Lesson ID")
    edit_parser.add_argument("content", help="New content")

    # delete command
    delete_parser = subparsers.add_parser("delete", help="Delete a lesson")
    delete_parser.add_argument("lesson_id", help="Lesson ID")

    # promote command
    promote_parser = subparsers.add_parser("promote", help="Promote project lesson to system")
    promote_parser.add_argument("lesson_id", help="Lesson ID")

    # score-relevance command
    score_relevance_parser = subparsers.add_parser(
        "score-relevance", help="Score lessons by relevance to text using Haiku"
    )
    score_relevance_parser.add_argument("text", help="Text to score lessons against")
    score_relevance_parser.add_argument(
        "--top", type=int, default=10, help="Number of top results to show"
    )
    score_relevance_parser.add_argument(
        "--min-score", type=int, default=0, help="Minimum relevance score (0-10)"
    )
    score_relevance_parser.add_argument(
        "--timeout", type=int, default=30, help="Timeout in seconds for Haiku call"
    )

    # approach command (with subcommands)
    approach_parser = subparsers.add_parser("approach", help="Manage approaches")
    approach_subparsers = approach_parser.add_subparsers(dest="approach_command", help="Approach commands")

    # approach add (alias: start)
    approach_add_parser = approach_subparsers.add_parser("add", aliases=["start"], help="Add a new approach")
    approach_add_parser.add_argument("title", help="Approach title")
    approach_add_parser.add_argument("--desc", help="Description")
    approach_add_parser.add_argument("--files", help="Comma-separated list of files")
    approach_add_parser.add_argument("--phase", default="research", help="Initial phase (research, planning, implementing, review)")
    approach_add_parser.add_argument("--agent", default="user", help="Agent working on this (explore, general-purpose, plan, review, user)")

    # approach update
    approach_update_parser = approach_subparsers.add_parser("update", help="Update an approach")
    approach_update_parser.add_argument("id", help="Approach ID (e.g., A001)")
    approach_update_parser.add_argument("--status", help="New status (not_started, in_progress, blocked, completed)")
    approach_update_parser.add_argument("--tried", nargs=2, metavar=("OUTCOME", "DESC"), help="Add tried approach (outcome: success|fail|partial)")
    approach_update_parser.add_argument("--next", help="Update next steps")
    approach_update_parser.add_argument("--files", help="Update files (comma-separated)")
    approach_update_parser.add_argument("--desc", help="Update description")
    approach_update_parser.add_argument("--phase", help="Update phase (research, planning, implementing, review)")
    approach_update_parser.add_argument("--agent", help="Update agent (explore, general-purpose, plan, review, user)")
    approach_update_parser.add_argument("--code", help="Add a code snippet")
    approach_update_parser.add_argument("--language", help="Language hint for code snippet (e.g., python, typescript)")
    approach_update_parser.add_argument("--checkpoint", help="Update checkpoint (progress summary for session handoff)")

    # approach complete
    approach_complete_parser = approach_subparsers.add_parser("complete", help="Mark approach as completed")
    approach_complete_parser.add_argument("id", help="Approach ID")

    # approach archive
    approach_archive_parser = approach_subparsers.add_parser("archive", help="Archive an approach")
    approach_archive_parser.add_argument("id", help="Approach ID")

    # approach delete
    approach_delete_parser = approach_subparsers.add_parser("delete", help="Delete an approach")
    approach_delete_parser.add_argument("id", help="Approach ID")

    # approach list
    approach_list_parser = approach_subparsers.add_parser("list", help="List approaches")
    approach_list_parser.add_argument("--status", help="Filter by status")
    approach_list_parser.add_argument("--include-completed", action="store_true", help="Include completed approaches")

    # approach show
    approach_show_parser = approach_subparsers.add_parser("show", help="Show an approach")
    approach_show_parser.add_argument("id", help="Approach ID")

    # approach inject
    approach_subparsers.add_parser("inject", help="Output approaches for context injection")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Find project root - check env var first, then search for .git
    project_root_env = os.environ.get("PROJECT_DIR")
    if project_root_env:
        project_root = Path(project_root_env)
    else:
        project_root = Path.cwd()
        while project_root != project_root.parent:
            if (project_root / ".git").exists():
                break
            project_root = project_root.parent
        else:
            project_root = Path.cwd()

    # Lessons base - check env var first, then use default
    lessons_base_env = os.environ.get("LESSONS_BASE")
    if lessons_base_env:
        lessons_base = Path(lessons_base_env)
    else:
        lessons_base = Path.home() / ".config" / "coding-agent-lessons"
    manager = LessonsManager(lessons_base, project_root)

    try:
        if args.command == "add":
            level = "system" if args.system else "project"
            promotable = not getattr(args, "no_promote", False)
            lesson_id = manager.add_lesson(
                level=level,
                category=args.category,
                title=args.title,
                content=args.content,
                force=args.force,
                promotable=promotable,
            )
            promo_note = " (no-promote)" if not promotable else ""
            print(f"Added {level} lesson {lesson_id}: {args.title}{promo_note}")

        elif args.command == "add-ai":
            level = "system" if args.system else "project"
            promotable = not getattr(args, "no_promote", False)
            lesson_id = manager.add_ai_lesson(
                level=level,
                category=args.category,
                title=args.title,
                content=args.content,
                promotable=promotable,
            )
            promo_note = " (no-promote)" if not promotable else ""
            print(f"Added AI {level} lesson {lesson_id}: {args.title}{promo_note}")

        elif args.command == "add-system":
            # Alias for add --system (backward compatibility with bash script)
            lesson_id = manager.add_lesson(
                level="system",
                category=args.category,
                title=args.title,
                content=args.content,
                force=args.force,
            )
            print(f"Added system lesson {lesson_id}: {args.title}")

        elif args.command == "cite":
            result = manager.cite_lesson(args.lesson_id)
            if result.promotion_ready:
                print(f"PROMOTION_READY:{result.lesson_id}:{result.uses}")
            else:
                print(f"OK:{result.uses}")

        elif args.command == "inject":
            result = manager.inject_context(args.top_n)
            print(result.format())

        elif args.command == "list":
            scope = "all"
            if args.project:
                scope = "project"
            elif args.system:
                scope = "system"

            lessons = manager.list_lessons(
                scope=scope,
                search=args.search,
                category=args.category,
                stale_only=args.stale,
            )

            if not lessons:
                print("(no lessons found)")
            else:
                for lesson in lessons:
                    rating = LessonRating.calculate(lesson.uses, lesson.velocity)
                    prefix = f"{ROBOT_EMOJI} " if lesson.source == "ai" else ""
                    stale = " [STALE]" if lesson.is_stale() else ""
                    print(f"[{lesson.id}] {rating} {prefix}{lesson.title}{stale}")
                    print(f"    -> {lesson.content}")
                print(f"\nTotal: {len(lessons)} lesson(s)")

        elif args.command == "decay":
            result = manager.decay_lessons(args.days)
            print(result.message)

        elif args.command == "edit":
            manager.edit_lesson(args.lesson_id, args.content)
            print(f"Updated {args.lesson_id} content")

        elif args.command == "delete":
            manager.delete_lesson(args.lesson_id)
            print(f"Deleted {args.lesson_id}")

        elif args.command == "promote":
            new_id = manager.promote_lesson(args.lesson_id)
            print(f"Promoted {args.lesson_id} -> {new_id}")

        elif args.command == "score-relevance":
            result = manager.score_relevance(args.text, timeout_seconds=args.timeout)
            print(result.format(top_n=args.top, min_score=args.min_score))

        elif args.command == "approach":
            if not args.approach_command:
                approach_parser.print_help()
                sys.exit(1)

            if args.approach_command in ("add", "start"):
                files = None
                if args.files:
                    files = [f.strip() for f in args.files.split(",") if f.strip()]
                approach_id = manager.approach_add(
                    title=args.title,
                    desc=args.desc,
                    files=files,
                    phase=args.phase,
                    agent=args.agent,
                )
                print(f"Added approach {approach_id}: {args.title}")

            elif args.approach_command == "update":
                updated = False
                if args.status:
                    manager.approach_update_status(args.id, args.status)
                    print(f"Updated {args.id} status to {args.status}")
                    updated = True
                if args.tried:
                    outcome, desc = args.tried
                    manager.approach_add_tried(args.id, outcome, desc)
                    print(f"Added tried approach to {args.id}")
                    updated = True
                if args.next:
                    manager.approach_update_next(args.id, args.next)
                    print(f"Updated {args.id} next steps")
                    updated = True
                if args.files:
                    files_list = [f.strip() for f in args.files.split(",") if f.strip()]
                    manager.approach_update_files(args.id, files_list)
                    print(f"Updated {args.id} files")
                    updated = True
                if args.desc:
                    manager.approach_update_desc(args.id, args.desc)
                    print(f"Updated {args.id} description")
                    updated = True
                if args.phase:
                    manager.approach_update_phase(args.id, args.phase)
                    print(f"Updated {args.id} phase to {args.phase}")
                    updated = True
                if args.agent:
                    manager.approach_update_agent(args.id, args.agent)
                    print(f"Updated {args.id} agent to {args.agent}")
                    updated = True
                if args.code:
                    language = args.language if args.language else ""
                    manager.approach_add_code(args.id, args.code, language)
                    print(f"Added code snippet to {args.id}")
                    updated = True
                if args.checkpoint:
                    manager.approach_update_checkpoint(args.id, args.checkpoint)
                    print(f"Updated {args.id} checkpoint")
                    updated = True
                if not updated:
                    print("No update options provided", file=sys.stderr)
                    sys.exit(1)

            elif args.approach_command == "complete":
                result = manager.approach_complete(args.id)
                print(f"Completed {args.id}")
                print("\n" + result.extraction_prompt)

            elif args.approach_command == "archive":
                manager.approach_archive(args.id)
                print(f"Archived {args.id}")

            elif args.approach_command == "delete":
                manager.approach_delete(args.id)
                print(f"Deleted {args.id}")

            elif args.approach_command == "list":
                approaches = manager.approach_list(
                    status_filter=args.status,
                    include_completed=args.include_completed,
                )
                if not approaches:
                    print("(no approaches found)")
                else:
                    for approach in approaches:
                        print(f"[{approach.id}] {approach.title}")
                        print(f"    Status: {approach.status} | Created: {approach.created} | Updated: {approach.updated}")
                        if approach.files:
                            print(f"    Files: {', '.join(approach.files)}")
                        if approach.description:
                            print(f"    Description: {approach.description}")
                    print(f"\nTotal: {len(approaches)} approach(es)")

            elif args.approach_command == "show":
                approach = manager.approach_get(args.id)
                if approach is None:
                    print(f"Error: Approach {args.id} not found", file=sys.stderr)
                    sys.exit(1)
                print(f"### [{approach.id}] {approach.title}")
                print(f"- **Status**: {approach.status}")
                print(f"- **Created**: {approach.created}")
                print(f"- **Updated**: {approach.updated}")
                print(f"- **Files**: {', '.join(approach.files) if approach.files else '(none)'}")
                print(f"- **Description**: {approach.description if approach.description else '(none)'}")
                if approach.checkpoint:
                    session_info = f" ({approach.last_session})" if approach.last_session else ""
                    print(f"- **Checkpoint{session_info}**: {approach.checkpoint}")
                print()
                print("**Tried**:")
                if approach.tried:
                    for i, tried in enumerate(approach.tried, 1):
                        print(f"{i}. [{tried.outcome}] {tried.description}")
                else:
                    print("(none)")
                print()
                print(f"**Next**: {approach.next_steps if approach.next_steps else '(none)'}")

            elif args.approach_command == "inject":
                output = manager.approach_inject()
                if output:
                    print(output)
                else:
                    print("(no active approaches)")

    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
