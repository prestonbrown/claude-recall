#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Parsing utilities for lesson markdown format.

This module provides functions to parse and format lessons stored in markdown format.
"""

import re
from datetime import date
from typing import List, Optional, Tuple

# Handle both module import and direct script execution
try:
    from core.models import (
        LESSON_HEADER_PATTERN_FLEXIBLE,
        METADATA_PATTERN,
        CONTENT_PATTERN,
        ROBOT_EMOJI,
        Lesson,
        LessonRating,
    )
except ImportError:
    from models import (
        LESSON_HEADER_PATTERN_FLEXIBLE,
        METADATA_PATTERN,
        CONTENT_PATTERN,
        ROBOT_EMOJI,
        Lesson,
        LessonRating,
    )


# Constraint signals - content keywords that indicate NEVER/ALWAYS rules
# Note: These are matched with word boundaries (\b) to avoid false positives like "debug" matching "bug"
CONSTRAINT_SIGNALS = [
    "crash", "deadlock", "bug", "break", "destroy", "corrupt",
    "never", "always", "must", "sacred", "critical", "causes",
    "will fail", "data loss", "security", "wip", "uncommitted",
]

# Preference signals - content keywords that indicate soft preferences
PREFERENCE_SIGNALS = ["prefer", "better to", "recommend", "style", "convention"]

# Categories that imply constraint type
CONSTRAINT_CATEGORIES = ("correction", "gotcha")


def classify_lesson(content: str, category: str) -> str:
    """Classify lesson type based on content signals and category.

    Args:
        content: The lesson content text
        category: The lesson category (pattern, correction, gotcha, etc.)

    Returns:
        One of: "constraint", "informational", "preference"
    """
    content_lower = content.lower()

    # Category hints - corrections and gotchas are constraints
    if category in CONSTRAINT_CATEGORIES:
        return "constraint"

    # Check for constraint signals in content (using word boundaries to avoid false positives)
    if any(re.search(rf'\b{signal}\b', content_lower) for signal in CONSTRAINT_SIGNALS):
        return "constraint"

    # Check for preference signals
    if any(signal in content_lower for signal in PREFERENCE_SIGNALS):
        return "preference"

    return "informational"


def frame_lesson_content(lesson: "Lesson") -> str:
    """Add framing to lesson content based on type.

    Args:
        lesson: The Lesson object

    Returns:
        Content with appropriate framing prefix for constraint/preference types,
        or original content for informational types.
    """
    content = lesson.content

    # Guard against double-framing
    if content.startswith(("NEVER:", "ALWAYS:", "Prefer:")):
        return content  # Already framed

    lesson_type = lesson.lesson_type or classify_lesson(content, lesson.category)

    if lesson_type == "constraint":
        # Detect ALWAYS vs NEVER from content
        if "always" in content.lower():
            return f"ALWAYS: {content}. Ask user before skipping."
        else:
            return f"NEVER: {content}. Ask user if exception needed."
    elif lesson_type == "preference":
        return f"Prefer: {content}. Ask user before deviating."
    else:
        return content  # informational - as-is


# Pattern for parsing old metadata format (without Velocity field)
OLD_METADATA_PATTERN = re.compile(
    r"^\s*-\s*\*\*Uses\*\*:\s*(\d+)"
    r"\s*\|\s*\*\*Learned\*\*:\s*(\d{4}-\d{2}-\d{2})"
    r"\s*\|\s*\*\*Last\*\*:\s*(\d{4}-\d{2}-\d{2})"
    r"\s*\|\s*\*\*Category\*\*:\s*(\w+)"
    r"(?:\s*\|\s*\*\*Source\*\*:\s*(\w+))?"
)


def parse_lesson(lines: List[str], start_idx: int, level: str) -> Optional[Tuple[Lesson, int]]:
    """
    Parse a lesson from a list of lines starting at start_idx.

    Args:
        lines: List of lines from the lessons file
        start_idx: Index to start parsing from
        level: 'project' or 'system'

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
        old_match = OLD_METADATA_PATTERN.match(meta_line)
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
        stored_type = ""
    else:
        try:
            uses = int(meta_match.group(1))
            velocity = float(meta_match.group(2)) if meta_match.group(2) else 0.0
            learned = date.fromisoformat(meta_match.group(3))
            last_used = date.fromisoformat(meta_match.group(4))
            category = meta_match.group(5)
            source = meta_match.group(6) or "human"
            stored_type = meta_match.group(7) or ""
        except ValueError:
            return None  # Malformed data, skip this lesson

    # Check for promotable flag (defaults to True if not present)
    promotable = "**Promotable**: no" not in meta_line

    # Extract triggers (optional, defaults to empty list)
    triggers = []
    triggers_match = re.search(r'\|\s*\*\*Triggers\*\*:\s*(.+?)(?:\||$)', meta_line)
    if triggers_match:
        triggers_str = triggers_match.group(1).strip()
        triggers = [t.strip() for t in triggers_str.split(",") if t.strip()]

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

    # Classify lesson type: use stored type if present, otherwise auto-classify
    lesson_type = stored_type if stored_type else classify_lesson(content, category)

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
        lesson_type=lesson_type,
        triggers=triggers,
    )

    return (lesson, end_idx)


def format_lesson(lesson: Lesson) -> str:
    """
    Format a lesson for markdown storage.

    Args:
        lesson: The Lesson object to format

    Returns:
        Formatted markdown string for the lesson
    """
    # Use legacy ASCII format for file storage (parseable by regex)
    rating = LessonRating(lesson.uses, lesson.velocity).format_legacy()

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
    # Only store type if explicitly set (not auto-classified)
    if lesson.lesson_type:
        meta_parts.append(f"**Type**: {lesson.lesson_type}")
    # Only store triggers if non-empty
    if lesson.triggers:
        meta_parts.append(f"**Triggers**: {', '.join(lesson.triggers)}")

    meta_line = f"- {' | '.join(meta_parts)}"
    content_line = f"> {lesson.content}"

    return f"{header}\n{meta_line}\n{content_line}\n"
