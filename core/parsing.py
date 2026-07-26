#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Parsing utilities for lesson markdown format.

This module provides functions to parse and format lessons stored in markdown format.
"""

import json
import re
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

# Handle both module import and direct script execution
try:
    from core.models import (
        LESSON_HEADER_PATTERN_FLEXIBLE,
        METADATA_PATTERN,
        META_CATEGORY_PATTERN,
        META_LAST_PATTERN,
        META_LEARNED_PATTERN,
        META_SOURCE_PATTERN,
        META_SUPERSEDED_PATTERN,
        META_TYPE_PATTERN,
        META_USES_PATTERN,
        META_VELOCITY_PATTERN,
        CONTENT_PATTERN,
        ROBOT_EMOJI,
        Lesson,
        LessonRating,
    )
except ImportError:
    from models import (
        LESSON_HEADER_PATTERN_FLEXIBLE,
        METADATA_PATTERN,
        META_CATEGORY_PATTERN,
        META_LAST_PATTERN,
        META_LEARNED_PATTERN,
        META_SOURCE_PATTERN,
        META_SUPERSEDED_PATTERN,
        META_TYPE_PATTERN,
        META_USES_PATTERN,
        META_VELOCITY_PATTERN,
        CONTENT_PATTERN,
        ROBOT_EMOJI,
        Lesson,
        LessonRating,
    )


# =============================================================================
# Stats sidecar
# =============================================================================
#
# Uses/Velocity/Last change on every injection, so they live beside LESSONS.md
# rather than inside it - otherwise the lessons file is permanently dirty in git
# and counter bumps interleave with real edits. Mirrors
# go/internal/lessons/stats.go; both implementations read and write the same
# sidecar, so whichever one runs is irrelevant to the file's shape.

STATS_FILENAME = "stats.json"


def stats_path(lessons_path: Union[str, Path]) -> Path:
    """Return the stats sidecar path for a given LESSONS.md path."""
    return Path(lessons_path).parent / STATS_FILENAME


def load_stats(path: Union[str, Path]) -> Dict[str, dict]:
    """Read the sidecar.

    A missing or unreadable sidecar is not an error: callers fall back to
    whatever inline values the markdown still carries, which is what lets a
    pre-split file load correctly.
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def apply_stats(lessons: List[Lesson], stats: Dict[str, dict]) -> None:
    """Overlay sidecar counters onto parsed lessons, in place.

    Lessons absent from the sidecar keep whatever the markdown supplied, so a
    half-migrated store - some entries moved, some still inline - resolves
    correctly either way.
    """
    for lesson in lessons:
        entry = stats.get(lesson.id)
        if not isinstance(entry, dict):
            continue
        if isinstance(entry.get("uses"), (int, float)):
            lesson.uses = int(entry["uses"])
        if isinstance(entry.get("velocity"), (int, float)):
            lesson.velocity = float(entry["velocity"])
        last = entry.get("last")
        if last:
            try:
                lesson.last_used = date.fromisoformat(last)
            except (ValueError, TypeError):
                pass


def extract_stats(lessons: List[Lesson]) -> Dict[str, dict]:
    """Pull volatile counters out of a lesson set for persisting."""
    return {
        lesson.id: {
            "uses": lesson.uses,
            "velocity": lesson.velocity,
            "last": lesson.last_used.isoformat() if lesson.last_used else "",
        }
        for lesson in lessons
    }


def save_stats(path: Union[str, Path], stats: Dict[str, dict]) -> None:
    """Write the sidecar atomically.

    A crash mid-write must not leave a truncated file, which would silently
    reset every counter to zero.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


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
    if not METADATA_PATTERN.match(meta_line):
        return None

    # Fields are extracted individually rather than as one fixed sequence, so a
    # current-format line (durable fields only) and a legacy line (counters
    # inline) both parse. Learned and Category are written by every serializer;
    # their absence means this is not a lesson metadata line.
    learned_match = META_LEARNED_PATTERN.search(meta_line)
    category_match = META_CATEGORY_PATTERN.search(meta_line)
    if not learned_match or not category_match:
        return None

    try:
        learned = date.fromisoformat(learned_match.group(1))
    except ValueError:
        return None  # Malformed date, skip this lesson

    category = category_match.group(1)

    # Volatile counters: present only in legacy files. When absent they default
    # to zero here and the stats sidecar supplies the real values.
    uses_match = META_USES_PATTERN.search(meta_line)
    uses = int(uses_match.group(1)) if uses_match else 0

    velocity_match = META_VELOCITY_PATTERN.search(meta_line)
    velocity = float(velocity_match.group(1)) if velocity_match else 0.0

    last_match = META_LAST_PATTERN.search(meta_line)
    if last_match:
        try:
            last_used = date.fromisoformat(last_match.group(1))
        except ValueError:
            return None  # Malformed date, skip this lesson
    else:
        last_used = learned

    source_match = META_SOURCE_PATTERN.search(meta_line)
    source = source_match.group(1) if source_match else "human"

    type_match = META_TYPE_PATTERN.search(meta_line)
    stored_type = type_match.group(1) if type_match else ""

    superseded_match = META_SUPERSEDED_PATTERN.search(meta_line)
    superseded = superseded_match.group(1) if superseded_match else ""

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
        superseded=superseded,
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
    # Add robot emoji for AI lessons
    title_display = f"{ROBOT_EMOJI} {lesson.title}" if lesson.source == "ai" else lesson.title

    # The rating is derived from Uses/Velocity and rendered at display time, so
    # it is not stored - writing it here would reintroduce exactly the churn the
    # stats sidecar exists to remove.
    header = f"### [{lesson.id}] {title_display}"

    # Metadata line: durable fields only. Uses/Velocity/Last live in stats.json.
    meta_parts = [
        f"**Learned**: {lesson.learned.isoformat()}",
        f"**Category**: {lesson.category}",
    ]
    if lesson.superseded:
        meta_parts.append(f"**Superseded**: {lesson.superseded}")
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
