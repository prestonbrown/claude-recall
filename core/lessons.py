#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Lessons mixin for the LessonsManager class.

This module contains all lesson-related methods as a mixin class.
"""

import os
import re
import string
import subprocess
import time
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

# Handle both module import and direct script execution
try:
    from core.debug_logger import get_logger
    from core.parsing import parse_lesson, format_lesson
    from core.file_lock import FileLock
    from core.models import (
        # Constants
        SYSTEM_PROMOTION_THRESHOLD,
        MAX_USES,
        VELOCITY_DECAY_FACTOR,
        VELOCITY_EPSILON,
        SCORE_RELEVANCE_TIMEOUT,
        SCORE_RELEVANCE_MAX_QUERY_LEN,
        # Dataclasses
        Lesson,
        LessonRating,
        CitationResult,
        InjectionResult,
        DecayResult,
        ScoredLesson,
        RelevanceResult,
    )
except ImportError:
    from debug_logger import get_logger
    from parsing import parse_lesson, format_lesson
    from file_lock import FileLock
    from models import (
        # Constants
        SYSTEM_PROMOTION_THRESHOLD,
        MAX_USES,
        VELOCITY_DECAY_FACTOR,
        VELOCITY_EPSILON,
        SCORE_RELEVANCE_TIMEOUT,
        SCORE_RELEVANCE_MAX_QUERY_LEN,
        # Dataclasses
        Lesson,
        LessonRating,
        CitationResult,
        InjectionResult,
        DecayResult,
        ScoredLesson,
        RelevanceResult,
    )


class LessonsMixin:
    """
    Mixin containing lesson-related methods.

    This mixin expects the following attributes to be set on the class:
    - self.lessons_base: Path to system lessons base directory
    - self.project_root: Path to project root
    - self.system_lessons_file: Path to system lessons file
    - self.project_lessons_file: Path to project lessons file
    - self._decay_state_file: Path to decay state file
    - self._session_state_dir: Path to session state directory
    """

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
        lesson_type: str = "",
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
            lesson_type: 'constraint', 'informational', or 'preference' (auto-classified if empty)

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
                lesson_type=lesson_type,
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
        lesson_type: str = "",
    ) -> str:
        """
        Convenience method to add an AI-generated lesson.

        Args:
            level: 'project' or 'system'
            category: Lesson category
            title: Lesson title
            content: Lesson content
            promotable: If False, lesson will never be promoted to system level
            lesson_type: 'constraint', 'informational', or 'preference' (auto-classified if empty)

        Returns:
            The assigned lesson ID
        """
        return self.add_lesson(
            level, category, title, content, source="ai", promotable=promotable,
            lesson_type=lesson_type
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
            ValueError: If the lesson is not found or ID format is invalid
        """
        if not re.match(r'^[LS]\d{3}$', lesson_id):
            raise ValueError(f"Invalid lesson ID format: {lesson_id}")

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

        # Use configurable threshold from settings (default: 50)
        threshold = getattr(self, "promotion_threshold", SYSTEM_PROMOTION_THRESHOLD)
        promotion_ready = (
            lesson_id.startswith("L")
            and new_uses >= threshold
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

        old_len = 0
        with FileLock(file_path):
            lessons = self._parse_lessons_file(file_path, level)

            found = False
            for lesson in lessons:
                if lesson.id == lesson_id:
                    old_len = len(lesson.content)
                    lesson.content = new_content
                    found = True
                    break

            if not found:
                raise ValueError(f"Lesson {lesson_id} not found")

            self._write_lessons_file(file_path, lessons, level)

        logger = get_logger()
        logger.mutation("edit", lesson_id, {"old_len": old_len, "new_len": len(new_content)})

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

        logger = get_logger()
        logger.mutation("delete", lesson_id)

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

        logger = get_logger()
        logger.mutation("promote", lesson_id, {"new_id": new_id})

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
        start_time = time.time()
        logger = get_logger()

        # Truncate query to prevent huge prompts
        query_len = len(query_text)
        if query_len > SCORE_RELEVANCE_MAX_QUERY_LEN:
            query_text = query_text[:SCORE_RELEVANCE_MAX_QUERY_LEN] + "..."

        all_lessons = self.list_lessons(scope="all")
        lesson_count = len(all_lessons)

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
            # LESSONS_SCORING_ACTIVE=1 is a guard to prevent hooks from recursively
            # calling score_relevance on the Haiku subprocess. When set, hooks should
            # skip relevance scoring to avoid infinite recursion and wasted API calls.
            env = os.environ.copy()
            env["LESSONS_SCORING_ACTIVE"] = "1"
            result = subprocess.run(
                ["claude", "-p", "--model", "haiku"],
                input=prompt,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env=env,
            )

            if result.returncode != 0:
                duration_ms = int((time.time() - start_time) * 1000)
                error_msg = f"claude command failed: {result.stderr.strip()}"
                logger.relevance_score(query_len, lesson_count, duration_ms, [], error=error_msg)
                return RelevanceResult(
                    scored_lessons=[],
                    query_text=query_text,
                    error=error_msg,
                )

            output = result.stdout.strip()
            if not output:
                duration_ms = int((time.time() - start_time) * 1000)
                error_msg = "empty response from Haiku"
                logger.relevance_score(query_len, lesson_count, duration_ms, [], error=error_msg)
                return RelevanceResult(
                    scored_lessons=[],
                    query_text=query_text,
                    error=error_msg,
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

            duration_ms = int((time.time() - start_time) * 1000)
            top_scores = [(sl.lesson.id, sl.score) for sl in scored_lessons[:3]]
            logger.relevance_score(query_len, lesson_count, duration_ms, top_scores)

            return RelevanceResult(
                scored_lessons=scored_lessons,
                query_text=query_text,
            )

        except subprocess.TimeoutExpired:
            duration_ms = int((time.time() - start_time) * 1000)
            error_msg = f"Haiku call timed out after {timeout_seconds}s"
            logger.relevance_score(query_len, lesson_count, duration_ms, [], error=error_msg)
            return RelevanceResult(
                scored_lessons=[],
                query_text=query_text,
                error=error_msg,
            )
        except FileNotFoundError:
            duration_ms = int((time.time() - start_time) * 1000)
            error_msg = "claude CLI not found"
            logger.relevance_score(query_len, lesson_count, duration_ms, [], error=error_msg)
            return RelevanceResult(
                scored_lessons=[],
                query_text=query_text,
                error=error_msg,
            )
        except (OSError, ValueError, subprocess.SubprocessError) as e:
            # OSError: permission denied, broken pipe, etc.
            # ValueError: parsing errors
            # SubprocessError: base class for process-related errors
            duration_ms = int((time.time() - start_time) * 1000)
            error_msg = str(e)
            logger.relevance_score(query_len, lesson_count, duration_ms, [], error=error_msg)
            return RelevanceResult(
                scored_lessons=[],
                query_text=query_text,
                error=error_msg,
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

        # Use InjectionResult.format() for the main formatting
        formatted = result.format()

        # Calculate total tokens for warning and logging
        total_tokens = sum(lesson.tokens for lesson in result.all_lessons)

        # Insert token budget warning after header if heavy
        if total_tokens > 2000:
            lines = formatted.split("\n")
            # Insert warning after the header line
            lines.insert(1, "  ⚠️ CONTEXT HEAVY - Consider completing approaches, archiving stale lessons")
            formatted = "\n".join(lines)

        # Log injection generation (level 2)
        other_lessons = result.all_lessons[limit:]
        logger = get_logger()
        logger.injection_generated(
            token_budget=total_tokens,
            lessons_included=len(result.top_lessons),
            lessons_excluded=len(other_lessons),
            included_ids=[l.id for l in result.top_lessons],
        )

        return formatted

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

        # Evict excess lessons if maxLessons is configured
        evicted_count = self._evict_excess_lessons()

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

    def _evict_excess_lessons(self) -> int:
        """
        Evict lessons when count exceeds maxLessons setting.

        Removes oldest lessons (by last_used date) until count is within limit.
        Eviction is per-level (project and system separately).

        Returns:
            Number of lessons evicted
        """
        # Get max_lessons from settings (set in LessonsManager.__init__)
        max_lessons = getattr(self, "max_lessons", None)
        if not max_lessons or max_lessons <= 0:
            return 0

        evicted_count = 0
        logger = get_logger()

        for level, file_path in [
            ("project", self.project_lessons_file),
            ("system", self.system_lessons_file),
        ]:
            if not file_path.exists():
                continue

            with FileLock(file_path):
                lessons = self._parse_lessons_file(file_path, level)

                if len(lessons) <= max_lessons:
                    continue

                # Sort by last_used (oldest first)
                lessons_sorted = sorted(lessons, key=lambda l: l.last_used)
                excess_count = len(lessons) - max_lessons

                # Evict oldest lessons
                to_evict = lessons_sorted[:excess_count]
                remaining = lessons_sorted[excess_count:]

                for lesson in to_evict:
                    logger.mutation(
                        op="evict",
                        target=lesson.id,
                        details={"reason": "maxLessons exceeded", "last_used": str(lesson.last_used)},
                    )
                    evicted_count += 1

                # Write back only the remaining lessons
                self._write_lessons_file(file_path, remaining, level)

        return evicted_count

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
