#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Coding Agent Lessons (Recall) - Core module.

A learning system for AI coding agents that captures lessons across sessions

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
    INJECTION_REMAINING_CAP,
    INJECTION_TITLE_TRUNCATE,
    # Backward compat aliases
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
    # Backward compat aliases
    ScoredLesson,
    RelevanceResult,
)

# Parsing utilities
from core.parsing import parse_lesson, format_lesson

# File locking
from core.file_lock import FileLock

# TUI entry point (CLI is now handled by Go)

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
    "INJECTION_REMAINING_CAP",
    "INJECTION_TITLE_TRUNCATE",
    # Constants (backward compat)
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
    # Dataclasses (backward compat)
    "ScoredLesson",
    "RelevanceResult",
    # Parsing
    "parse_lesson",
    "format_lesson",
    # File locking
    "FileLock",
    # CLI
]
