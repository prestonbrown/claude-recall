#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Coding Agent Lessons (Recall) - Core module.

A learning system for AI coding agents that captures lessons across sessions
and tracks multi-step work via handoffs (formerly called "approaches").

Usage:
    from core import LessonsManager, Lesson, LessonRating

    manager = LessonsManager(lessons_base, project_root)
    manager.add_lesson("project", "pattern", "Title", "Content")
    manager.cite_lesson("L001")
"""

from core._version import __version__

# Main class
from core.manager import LessonsManager

# Data models - Constants (new names + backward compat aliases)
from core.models import (
    ROBOT_EMOJI,
    SYSTEM_PROMOTION_THRESHOLD,
    STALE_DAYS_DEFAULT,
    MAX_USES,
    VELOCITY_DECAY_FACTOR,
    VELOCITY_EPSILON,
    # New constant names
    HANDOFF_MAX_COMPLETED,
    HANDOFF_MAX_AGE_DAYS,
    HANDOFF_STALE_DAYS,
    HANDOFF_COMPLETED_ARCHIVE_DAYS,
    HANDOFF_COMPLETED_CAP_MULTIPLIER,
    INJECTION_REMAINING_CAP,
    INJECTION_TITLE_TRUNCATE,
    # Backward compat aliases
    APPROACH_MAX_COMPLETED,
    APPROACH_MAX_AGE_DAYS,
    APPROACH_STALE_DAYS,
    APPROACH_COMPLETED_ARCHIVE_DAYS,
    SCORE_RELEVANCE_TIMEOUT,
    SCORE_RELEVANCE_MAX_QUERY_LEN,
)

# Data models - Enums
from core.models import (
    LessonLevel,
    LessonCategory,
)

# Data models - Dataclasses (new names + backward compat aliases)
from core.models import (
    Lesson,
    LessonRating,
    CitationResult,
    InjectionResult,
    DecayResult,
    # New class names
    TriedStep,
    Handoff,
    HandoffContext,
    HandoffCompleteResult,
    # Backward compat aliases
    TriedApproach,
    Approach,
    ApproachCompleteResult,
    ScoredLesson,
    RelevanceResult,
)

# Parsing utilities
from core.parsing import parse_lesson, format_lesson

# File locking
from core.file_lock import FileLock

# CLI entry point
from core.cli import main

__all__ = [
    # Version
    "__version__",
    # Main class
    "LessonsManager",
    # Constants (new names)
    "ROBOT_EMOJI",
    "SYSTEM_PROMOTION_THRESHOLD",
    "STALE_DAYS_DEFAULT",
    "MAX_USES",
    "VELOCITY_DECAY_FACTOR",
    "VELOCITY_EPSILON",
    "HANDOFF_MAX_COMPLETED",
    "HANDOFF_MAX_AGE_DAYS",
    "HANDOFF_STALE_DAYS",
    "HANDOFF_COMPLETED_ARCHIVE_DAYS",
    "HANDOFF_COMPLETED_CAP_MULTIPLIER",
    "INJECTION_REMAINING_CAP",
    "INJECTION_TITLE_TRUNCATE",
    # Constants (backward compat)
    "APPROACH_MAX_COMPLETED",
    "APPROACH_MAX_AGE_DAYS",
    "APPROACH_STALE_DAYS",
    "APPROACH_COMPLETED_ARCHIVE_DAYS",
    "SCORE_RELEVANCE_TIMEOUT",
    "SCORE_RELEVANCE_MAX_QUERY_LEN",
    # Enums
    "LessonLevel",
    "LessonCategory",
    # Dataclasses (new names)
    "Lesson",
    "LessonRating",
    "CitationResult",
    "InjectionResult",
    "DecayResult",
    "TriedStep",
    "Handoff",
    "HandoffContext",
    "HandoffCompleteResult",
    # Dataclasses (backward compat)
    "TriedApproach",
    "Approach",
    "ApproachCompleteResult",
    "ScoredLesson",
    "RelevanceResult",
    # Parsing
    "parse_lesson",
    "format_lesson",
    # File locking
    "FileLock",
    # CLI
    "main",
]
