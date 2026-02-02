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

# Handoff visibility constants
HANDOFF_MAX_COMPLETED = 3  # Keep last N completed handoffs visible
HANDOFF_MAX_AGE_DAYS = 7  # Or completed within N days
HANDOFF_STALE_DAYS = 7  # Auto-archive active handoffs untouched for N days
HANDOFF_COMPLETED_ARCHIVE_DAYS = 3  # Archive completed handoffs after N days
HANDOFF_ORPHAN_DAYS = 1  # Auto-complete ready_for_review handoffs with all success after N days
HANDOFF_COMPLETED_CAP_MULTIPLIER = 3  # Hard cap completed at N * HANDOFF_MAX_COMPLETED

# Injection display constants
INJECTION_REMAINING_CAP = 10  # Max remaining lessons to show titles for
INJECTION_TITLE_TRUNCATE = 30  # Truncate lesson titles in remaining list

# DEPRECATED (remove after 2025-06-01): Use HANDOFF_* constants instead
APPROACH_MAX_COMPLETED = HANDOFF_MAX_COMPLETED
APPROACH_MAX_AGE_DAYS = HANDOFF_MAX_AGE_DAYS
APPROACH_STALE_DAYS = HANDOFF_STALE_DAYS
APPROACH_COMPLETED_ARCHIVE_DAYS = HANDOFF_COMPLETED_ARCHIVE_DAYS

# Relevance scoring constants
SCORE_RELEVANCE_TIMEOUT = 30  # 30 seconds is enough for Haiku to score ~100 lessons
SCORE_RELEVANCE_MAX_QUERY_LEN = 5000  # Truncate query to prevent huge prompts

# Regex patterns for parsing lessons
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
    r"(?:\s*\|\s*\*\*Type\*\*:\s*(\w+))?"
)
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
class TriedStep:
    """A single tried step within a Handoff.

    Attributes:
        description: What was attempted
        outcome: 'success', 'fail', or 'partial'
    """
    outcome: str  # success|fail|partial
    description: str


# DEPRECATED (remove after 2025-06-01): Use TriedStep instead
TriedApproach = TriedStep


@dataclass
class Handoff:
    """Represents an active handoff being tracked (formerly called Approach)."""
    id: str
    title: str
    status: str  # not_started|in_progress|blocked|completed
    created: date
    updated: date
    description: str = ""
    next_steps: str = ""
    phase: str = "research"  # research|planning|implementing|review
    agent: str = "user"  # explore|general-purpose|plan|review|user
    refs: List[str] = field(default_factory=list)  # file:line refs (e.g., "core/main.py:50")
    tried: List[TriedStep] = field(default_factory=list)
    checkpoint: str = ""  # Progress summary from PreCompact hook (legacy, use handoff instead)
    last_session: Optional[date] = None  # When checkpoint was last updated
    handoff: Optional["HandoffContext"] = None  # Rich context for session handoffs
    blocked_by: List[str] = field(default_factory=list)  # IDs of blocking handoffs
    stealth: bool = False  # If True, stored in HANDOFFS_LOCAL.md (not committed to git)
    sessions: List[str] = field(default_factory=list)  # Session IDs linked to this handoff

    # Backward compatibility: 'files' is an alias for 'refs'
    @property
    def files(self) -> List[str]:
        """Backward compatibility alias for refs."""
        return self.refs

    @files.setter
    def files(self, value: List[str]) -> None:
        """Backward compatibility setter for refs."""
        self.refs = value


# DEPRECATED (remove after 2025-06-01): Use Handoff instead
Approach = Handoff


@dataclass
class LessonSuggestion:
    """A suggested lesson to extract from a completed handoff.

    Attributes:
        category: Lesson category (pattern, gotcha, decision, correction, preference)
        title: Suggested lesson title
        content: Suggested lesson content
        source: Where this suggestion came from (success_pattern, blocker, etc.)
        confidence: How confident we are in this suggestion (low, medium, high)
    """
    category: str
    title: str
    content: str
    source: str = "manual"  # success_pattern|blocker|failure_pattern|manual
    confidence: str = "medium"  # low|medium|high


@dataclass
class HandoffCompleteResult(FormattableResult):
    """Result of completing a handoff."""
    handoff: Handoff
    extraction_prompt: str
    suggested_lessons: List[LessonSuggestion] = field(default_factory=list)

    # Backward compatibility property
    @property
    def approach(self) -> Handoff:
        """Backward compatibility alias for handoff."""
        return self.handoff

    def format(self) -> str:
        """Format handoff completion result for display."""
        lines = [
            f"Completed [{self.handoff.id}] {self.handoff.title}",
            "",
            "Extraction prompt for lessons:",
            self.extraction_prompt
        ]

        if self.suggested_lessons:
            lines.append("")
            lines.append("Suggested lessons to extract:")
            for i, suggestion in enumerate(self.suggested_lessons, 1):
                conf_indicator = {"low": "-", "medium": "", "high": "+"}.get(suggestion.confidence, "?")
                lines.append(f"  {i}. [{suggestion.category}]{conf_indicator} {suggestion.title}")
                lines.append(f"     {suggestion.content}")

        return "\n".join(lines)


# DEPRECATED (remove after 2025-06-01): Use HandoffCompleteResult instead
ApproachCompleteResult = HandoffCompleteResult


@dataclass
class HandoffContext:
    """Rich context for session handoffs."""
    summary: str                    # 1-2 sentence progress summary
    critical_files: List[str]       # 2-3 most important file:line refs
    recent_changes: List[str]       # What was modified this session
    learnings: List[str]            # Discoveries/patterns found
    blockers: List[str]             # What's blocking progress
    git_ref: str                    # Commit hash at handoff time


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
    """Result of handoff resume validation."""
    valid: bool
    warnings: List[str] = field(default_factory=list)  # e.g., "Codebase changed since handoff"
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


@dataclass
class HandoffResumeResult(FormattableResult):
    """Result of resuming a handoff."""
    handoff: Handoff
    validation: ValidationResult
    context: Optional[HandoffContext] = None

    def format(self) -> str:
        """Format resume result for display."""
        lines = [
            f"### [{self.handoff.id}] {self.handoff.title}",
            f"- **Status**: {self.handoff.status} | **Phase**: {self.handoff.phase}",
            "",
            self.validation.format(),
        ]

        if self.context:
            lines.append("")
            lines.append("**Context**:")
            lines.append(f"  - Summary: {self.context.summary}")
            if self.context.critical_files:
                lines.append(f"  - Critical files: {', '.join(self.context.critical_files)}")
            if self.context.blockers:
                lines.append(f"  - Blockers: {', '.join(self.context.blockers)}")

        if self.handoff.next_steps:
            lines.append("")
            lines.append(f"**Next**: {self.handoff.next_steps}")

        return "\n".join(lines)
