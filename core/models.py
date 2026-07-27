#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Data models for the lessons manager.

Contains all dataclasses, enums, and constants used by the lessons system.
"""

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import List, Optional


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

# Injection display constants
INJECTION_REMAINING_CAP = 10  # Max remaining lessons to show titles for
INJECTION_TITLE_TRUNCATE = 30  # Truncate lesson titles in remaining list

# Relevance scoring constants
SCORE_RELEVANCE_TIMEOUT = 30  # 30 seconds is enough for Haiku to score ~100 lessons
SCORE_RELEVANCE_MAX_QUERY_LEN = 5000  # Truncate query to prevent huge prompts

# Regex patterns for parsing lessons.
#
# Two on-disk shapes are supported, matching go/internal/lessons/parser.go:
#
#   current: ### [L001] Title
#            - **Learned**: 2026-01-01 | **Category**: pattern
#   legacy:  ### [L001] [***--|****-] Title
#            - **Uses**: 12 | **Velocity**: 3.6 | **Learned**: ... | **Last**: ... | **Category**: pattern
#
# The rating is derived from Uses/Velocity and now renders at display time, and
# the volatile counters live in the stats.json sidecar, so current files carry
# neither. Both are optional here so either shape loads. The star-rating group
# only accepts rating characters, so a title starting with '[' is not mistaken
# for a rating.
LESSON_HEADER_PATTERN_FLEXIBLE = re.compile(
    r"^###\s*\[([LS]\d{3})\]\s*(?:\[([*+\-|/\ ]+)\]\s*)?(.*)$"
)

# A lesson metadata line, identified by shape rather than by a fixed field
# order. Fields are pulled out individually below, so a line carrying only
# durable fields parses the same as a legacy line that still has counters.
METADATA_PATTERN = re.compile(r"^\s*-\s*\*\*\w+\*\*:")

# Individual metadata fields. Uses/Velocity/Last appear only in legacy files.
META_USES_PATTERN = re.compile(r"\*\*Uses\*\*:\s*(\d+)")
META_VELOCITY_PATTERN = re.compile(r"\*\*Velocity\*\*:\s*([\d.]+)")
META_LEARNED_PATTERN = re.compile(r"\*\*Learned\*\*:\s*(\d{4}-\d{2}-\d{2})")
META_LAST_PATTERN = re.compile(r"\*\*Last\*\*:\s*(\d{4}-\d{2}-\d{2})")
META_CATEGORY_PATTERN = re.compile(r"\*\*Category\*\*:\s*(\w+)")
META_SOURCE_PATTERN = re.compile(r"\*\*Source\*\*:\s*(\w+)")
META_TYPE_PATTERN = re.compile(r"\*\*Type\*\*:\s*(\w+)")

# Retired-lesson marker: a replacement ID, or "deleted". A tombstoned lesson
# keeps its ID so existing [L###] citations in source still resolve.
META_SUPERSEDED_PATTERN = re.compile(r"\*\*Superseded\*\*:\s*(\S+)")

CONTENT_PATTERN = re.compile(r"^>\s*(.*)$")


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
# Abstract Base Classes
# =============================================================================


class FormattableResult(ABC):
    """Base class for all result types that can be formatted for display.

    All result dataclasses that have a format() method should inherit from this
    to ensure a consistent interface for formatting results.
    """

    @abstractmethod
    def format(self) -> str:
        """Format the result for display.

        Returns:
            Human-readable string representation of the result.
        """
        pass


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
    lesson_type: str = ""  # constraint|informational|preference (empty = auto-classify)
    triggers: List[str] = field(default_factory=list)  # Keywords for matching relevance
    superseded: str = ""  # Replacement ID, or "deleted"; empty = active

    @property
    def is_tombstone(self) -> bool:
        """True when the lesson has been retired.

        Retired lessons keep their ID so existing [L###] citations resolve to a
        redirect, but they are excluded from listing, injection, and scoring.
        """
        return bool(self.superseded)

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
    """Lesson rating display using star emojis."""
    uses: int
    velocity: float  # Kept for backward compatibility but not displayed

    def format(self) -> str:
        """Format the rating as emoji stars (uses only)."""
        return self._uses_to_emoji_stars()

    def format_legacy(self) -> str:
        """Format the rating as [total|velocity] for file storage."""
        left = self._uses_to_ascii_stars()
        right = self._velocity_to_indicator()
        return f"[{left}|{right}]"

    def _uses_to_emoji_stars(self) -> str:
        """Convert uses to emoji star scale (1-5 stars)."""
        # 1-2=★, 3-5=★★, 6-12=★★★, 13-30=★★★★, 31+=★★★★★
        filled = "★"
        empty = "☆"
        if self.uses >= 31:
            count = 5
        elif self.uses >= 13:
            count = 4
        elif self.uses >= 6:
            count = 3
        elif self.uses >= 3:
            count = 2
        elif self.uses >= 1:
            count = 1
        else:
            count = 0
        return filled * count + empty * (5 - count)

    def _uses_to_ascii_stars(self) -> str:
        """Convert uses to ASCII star scale for file storage."""
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
        """Convert velocity to activity indicator for file storage."""
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
class CitationResult(FormattableResult):
    """Result of citing a lesson."""
    success: bool
    lesson_id: str
    uses: int
    velocity: float
    promotion_ready: bool = False
    message: str = ""

    def format(self) -> str:
        """Format citation result for display."""
        if not self.success:
            return self.message or f"Failed to cite {self.lesson_id}"
        rating = LessonRating.calculate(self.uses, self.velocity)
        result = f"Cited [{self.lesson_id}] {rating} (uses: {self.uses})"
        if self.promotion_ready:
            result += " - Ready for promotion to system level!"
        return result


@dataclass
class InjectionResult(FormattableResult):
    """Result of context injection."""
    top_lessons: List[Lesson]
    all_lessons: List[Lesson]
    total_count: int
    system_count: int
    project_count: int

    def format(self) -> str:
        """Format injection result for display (condensed format)."""
        # Late import to avoid circular dependency
        try:
            from core.parsing import frame_lesson_content
        except ImportError:
            from parsing import frame_lesson_content

        if not self.all_lessons:
            return ""

        # Calculate total tokens
        total_tokens = sum(lesson.tokens for lesson in self.all_lessons)

        lines = [
            f"LESSONS ({self.system_count}S, {self.project_count}L | ~{total_tokens:,} tokens)"
        ]

        # Top lessons - inline format with framed content preview
        for lesson in self.top_lessons:
            rating = LessonRating.calculate(lesson.uses, lesson.velocity)
            prefix = f"{ROBOT_EMOJI} " if lesson.source == "ai" else ""
            # Use framed content (NEVER/ALWAYS prefix for constraints)
            framed_content = frame_lesson_content(lesson)
            content_preview = framed_content[:80] + "..." if len(framed_content) > 80 else framed_content
            lines.append(f"  [{lesson.id}] {rating} {prefix}{lesson.title} - {content_preview}")

        # Remaining lessons - grouped by category with triggers
        remaining = [l for l in self.all_lessons if l not in self.top_lessons]
        if remaining:
            lines.append("")  # Blank line before section
            lines.append("  --- More (read if relevant) ---")

            # Group by category
            from collections import defaultdict
            by_category = defaultdict(list)
            for lesson in remaining:
                by_category[lesson.category].append(lesson)

            # Output each category (sorted for consistency)
            cap = INJECTION_REMAINING_CAP
            displayed = 0
            for category in sorted(by_category.keys()):
                if displayed >= cap:
                    break
                lessons_in_cat = by_category[category]
                # First lesson in category: "category: [ID] Title -> kw1|kw2|kw3"
                # Subsequent: "        | [ID] Title2 -> kw4|kw5"
                first = True
                for lesson in lessons_in_cat:
                    if displayed >= cap:
                        break

                    # Format title (truncated)
                    title = lesson.title[:INJECTION_TITLE_TRUNCATE]
                    if len(lesson.title) > INJECTION_TITLE_TRUNCATE:
                        title += "..."

                    # Format triggers (max 3)
                    triggers_str = ""
                    if lesson.triggers:
                        triggers_to_show = lesson.triggers[:3]
                        triggers_str = f" -> {'|'.join(triggers_to_show)}"

                    if first:
                        lines.append(f"  {category}: [{lesson.id}] {title}{triggers_str}")
                        first = False
                    else:
                        lines.append(f"        | [{lesson.id}] {title}{triggers_str}")

                    displayed += 1

            undisplayed = len(remaining) - displayed
            if undisplayed > 0:
                lines.append(f"  (+{undisplayed} more)")
            lines.append("  ⚡ `show L###` when relevant")

        # Simplified footer - explicit about output pattern (no shell commands!)
        lines.append("Cite [ID] when applying. LESSON: [category:] title - content to add (output only, no shell commands).")

        return "\n".join(lines)


@dataclass
class DecayResult(FormattableResult):
    """Result of decay operation."""
    decayed_uses: int
    decayed_velocity: int
    sessions_since_last: int
    skipped: bool = False
    message: str = ""

    def format(self) -> str:
        """Format decay result for display."""
        if self.skipped:
            return self.message or "Decay skipped"
        if self.decayed_uses == 0 and self.decayed_velocity == 0:
            return f"No lessons decayed (sessions since last: {self.sessions_since_last})"
        return f"Decayed {self.decayed_uses} uses, {self.decayed_velocity} velocity (sessions since last: {self.sessions_since_last})"


@dataclass
class ScoredLesson:
    """A lesson with a relevance score."""
    lesson: Lesson
    score: int  # 0-10 relevance score


@dataclass
class RelevanceResult(FormattableResult):
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


@dataclass
class ValidationResult(FormattableResult):
    """Result of a validation pass, as a list of warnings and hard errors."""
    valid: bool
    warnings: List[str] = field(default_factory=list)  # e.g., "Codebase changed"
    errors: List[str] = field(default_factory=list)    # e.g., "File no longer exists: foo.py"

    def format(self) -> str:
        """Format validation result for display."""
        if self.valid and not self.warnings:
            return "Validation passed"

        lines = []
        if self.errors:
            lines.append("Errors:")
            for error in self.errors:
                lines.append(f"  - {error}")
        if self.warnings:
            lines.append("Warnings:")
            for warning in self.warnings:
                lines.append(f"  - {warning}")

        status = "INVALID" if not self.valid else "VALID (with warnings)"
        lines.insert(0, f"Validation: {status}")
        return "\n".join(lines)
