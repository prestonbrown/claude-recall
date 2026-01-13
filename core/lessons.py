#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Lessons mixin for the LessonsManager class.

This module contains all lesson-related methods as a mixin class.
"""

import hashlib
import json
import os
import re
import string
import subprocess
import time
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Tuple

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


# =============================================================================
# Relevance Cache Configuration
# =============================================================================

RELEVANCE_CACHE_FILE = "relevance-cache.json"
RELEVANCE_CACHE_TTL_DAYS = 7
RELEVANCE_CACHE_SIMILARITY_THRESHOLD = 0.7


# =============================================================================
# Relevance Cache Helper Functions
# =============================================================================


def _normalize_query(query: str) -> str:
    """Normalize query for cache key generation.

    - Lowercase
    - Remove punctuation
    - Sort words alphabetically

    Args:
        query: The raw query string

    Returns:
        Normalized query string
    """
    # Lowercase
    normalized = query.lower()
    # Remove punctuation
    for char in string.punctuation:
        normalized = normalized.replace(char, " ")
    # Split, filter empty, sort, and join
    words = sorted(word for word in normalized.split() if word)
    return " ".join(words)


def _query_hash(query: str) -> str:
    """Generate a hash of the normalized query for cache lookup.

    Args:
        query: The raw query string (will be normalized internally)

    Returns:
        SHA-256 hash of the normalized query (first 16 chars)
    """
    normalized = _normalize_query(query)
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def _jaccard_similarity(a: str, b: str) -> float:
    """Calculate Jaccard similarity between two normalized query strings.

    Jaccard similarity = |intersection| / |union|

    Args:
        a: First normalized query string
        b: Second normalized query string

    Returns:
        Similarity score between 0.0 and 1.0
    """
    words_a = set(a.split())
    words_b = set(b.split())

    if not words_a and not words_b:
        return 1.0
    if not words_a or not words_b:
        return 0.0

    intersection = words_a & words_b
    union = words_a | words_b

    return len(intersection) / len(union)


def _get_relevance_cache_path() -> Path:
    """Get the path to the relevance cache file.

    Uses the same state directory resolution as other state files.

    Returns:
        Path to the relevance cache JSON file
    """
    # Use environment variable or default location
    state = os.environ.get("CLAUDE_RECALL_STATE")
    if state:
        state_dir = Path(state)
    else:
        xdg_state = os.environ.get("XDG_STATE_HOME")
        if xdg_state:
            state_dir = Path(xdg_state) / "claude-recall"
        else:
            state_dir = Path.home() / ".local" / "state" / "claude-recall"

    return state_dir / RELEVANCE_CACHE_FILE


def _load_relevance_cache() -> Dict:
    """Load the relevance cache from disk.

    Returns:
        Cache dictionary with structure:
        {
            "entries": {
                "<query_hash>": {
                    "normalized_query": str,
                    "scores": {"L001": 8, "L002": 3, ...},
                    "timestamp": float (epoch seconds)
                },
                ...
            }
        }
    """
    cache_path = _get_relevance_cache_path()
    if not cache_path.exists():
        return {"entries": {}}

    try:
        with open(cache_path) as f:
            cache = json.load(f)
        # Ensure structure
        if "entries" not in cache:
            cache["entries"] = {}
        return cache
    except (OSError, json.JSONDecodeError, ValueError):
        return {"entries": {}}


def _save_relevance_cache(cache: Dict) -> None:
    """Save the relevance cache to disk.

    Args:
        cache: The cache dictionary to save
    """
    # Evict expired entries before saving
    now = time.time()
    ttl_seconds = RELEVANCE_CACHE_TTL_DAYS * 24 * 60 * 60
    if "entries" in cache:
        cache["entries"] = {
            k: v for k, v in cache["entries"].items()
            if now - v.get("timestamp", 0) < ttl_seconds
        }

    cache_path = _get_relevance_cache_path()
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with FileLock(cache_path):
            with open(cache_path, "w") as f:
                json.dump(cache, f, indent=2)
    except OSError:
        # Silently fail - caching is best-effort
        pass


def _find_cache_hit(
    query: str, cache: Dict, ttl_days: int = RELEVANCE_CACHE_TTL_DAYS
) -> Optional[Tuple[str, Dict[str, int]]]:
    """Find a cache hit for the given query.

    Checks for exact hash match first, then looks for similar queries
    using Jaccard similarity.

    Args:
        query: The raw query string
        cache: The loaded cache dictionary
        ttl_days: TTL in days for cache entries

    Returns:
        Tuple of (cache_key, scores_dict) if hit found, None otherwise
    """
    normalized = _normalize_query(query)
    query_key = _query_hash(query)
    now = time.time()
    ttl_seconds = ttl_days * 24 * 60 * 60

    entries = cache.get("entries", {})

    # Check for exact hash match
    if query_key in entries:
        entry = entries[query_key]
        if now - entry.get("timestamp", 0) < ttl_seconds:
            return (query_key, entry.get("scores", {}))

    # Look for similar queries via Jaccard similarity
    best_key = None
    best_similarity = 0.0

    for key, entry in entries.items():
        if now - entry.get("timestamp", 0) >= ttl_seconds:
            # Entry expired
            continue

        cached_normalized = entry.get("normalized_query", "")
        similarity = _jaccard_similarity(normalized, cached_normalized)

        if similarity > best_similarity and similarity >= RELEVANCE_CACHE_SIMILARITY_THRESHOLD:
            best_similarity = similarity
            best_key = key

    if best_key:
        return (best_key, entries[best_key].get("scores", {}))

    return None


def _update_cache(query: str, scores: Dict[str, int], cache: Dict) -> None:
    """Update the cache with new scores.

    Args:
        query: The raw query string
        scores: Dictionary of lesson_id -> score
        cache: The cache dictionary to update (modified in place)
    """
    normalized = _normalize_query(query)
    query_key = _query_hash(query)

    if "entries" not in cache:
        cache["entries"] = {}

    cache["entries"][query_key] = {
        "normalized_query": normalized,
        "scores": scores,
        "timestamp": time.time(),
    }


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
        level = self._get_level_from_id(lesson_id)
        file_path = self._get_file_path_for_id(lesson_id)

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

        level = self._get_level_from_id(lesson_id)
        file_path = self._get_file_path_for_id(lesson_id)

        if not file_path.exists():
            raise ValueError(f"Lesson {lesson_id} not found")

        # State to capture values from update function
        state = {
            "found": False,
            "uses_before": 0,
            "velocity_before": 0,
            "new_uses": 0,
            "new_velocity": 0,
            "promotable": True,
        }

        def update_fn(lessons):
            for lesson in lessons:
                if lesson.id == lesson_id:
                    # Capture old values for logging
                    state["uses_before"] = lesson.uses
                    state["velocity_before"] = lesson.velocity
                    state["promotable"] = lesson.promotable

                    # Update metrics (cap uses at 100)
                    state["new_uses"] = min(lesson.uses + 1, MAX_USES)
                    state["new_velocity"] = lesson.velocity + 1

                    lesson.uses = state["new_uses"]
                    lesson.velocity = state["new_velocity"]
                    lesson.last_used = date.today()

                    state["found"] = True
                    break

        self._atomic_update_lessons_file(file_path, update_fn, level)

        if not state["found"]:
            raise ValueError(f"Lesson {lesson_id} not found")

        # Use configurable threshold from settings (default: 50)
        threshold = getattr(self, "promotion_threshold", SYSTEM_PROMOTION_THRESHOLD)
        promotion_ready = (
            lesson_id.startswith("L")
            and state["new_uses"] >= threshold
            and state["promotable"]
        )

        # Log citation
        logger = get_logger()
        logger.citation(
            lesson_id=lesson_id,
            uses_before=state["uses_before"],
            uses_after=state["new_uses"],
            velocity_before=state["velocity_before"],
            velocity_after=state["new_velocity"],
            promotion_ready=promotion_ready,
        )

        return CitationResult(
            success=True,
            lesson_id=lesson_id,
            uses=state["new_uses"],
            velocity=state["new_velocity"],
            promotion_ready=promotion_ready,
            message="OK" if not promotion_ready else f"PROMOTION_READY:{lesson_id}:{state['new_uses']}",
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
        level = self._get_level_from_id(lesson_id)
        file_path = self._get_file_path_for_id(lesson_id)

        if not file_path.exists():
            raise ValueError(f"Lesson {lesson_id} not found")

        # Capture old_len in closure for logging
        state = {"old_len": 0, "found": False}

        def update_fn(lessons):
            for lesson in lessons:
                if lesson.id == lesson_id:
                    state["old_len"] = len(lesson.content)
                    lesson.content = new_content
                    state["found"] = True
                    break

        self._atomic_update_lessons_file(file_path, update_fn, level)

        if not state["found"]:
            raise ValueError(f"Lesson {lesson_id} not found")

        logger = get_logger()
        logger.mutation("edit", lesson_id, {"old_len": state["old_len"], "new_len": len(new_content)})

    def delete_lesson(self, lesson_id: str) -> None:
        """
        Delete a lesson.

        Args:
            lesson_id: The lesson ID to delete

        Raises:
            ValueError: If the lesson is not found
        """
        level = self._get_level_from_id(lesson_id)
        file_path = self._get_file_path_for_id(lesson_id)

        if not file_path.exists():
            raise ValueError(f"Lesson {lesson_id} not found")

        state = {"found": False}

        def update_fn(lessons):
            # Find and remove the lesson by index
            for i, lesson in enumerate(lessons):
                if lesson.id == lesson_id:
                    del lessons[i]
                    state["found"] = True
                    break

        self._atomic_update_lessons_file(file_path, update_fn, level)

        if not state["found"]:
            raise ValueError(f"Lesson {lesson_id} not found")

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

        # Capture new_id in closure for return value
        state = {"new_id": ""}

        # Step 1: Add to system file (separate lock to avoid nested locks)
        def add_to_system(system_lessons):
            state["new_id"] = self._get_next_id(self.system_lessons_file, "S")
            new_lesson = Lesson(
                id=state["new_id"],
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
            system_lessons.append(new_lesson)

        self._atomic_update_lessons_file(
            self.system_lessons_file, add_to_system, level="system"
        )

        # Step 2: Remove from project file (separate lock)
        def remove_from_project(project_lessons):
            for i, l in enumerate(project_lessons):
                if l.id == lesson_id:
                    del project_lessons[i]
                    break

        self._atomic_update_lessons_file(
            self.project_lessons_file, remove_from_project, level="project"
        )

        logger = get_logger()
        logger.mutation("promote", lesson_id, {"new_id": state["new_id"]})

        return state["new_id"]

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

        # Sort by weighted score (uses * 0.7 + velocity * 0.3) descending
        # This balances lifetime value (uses) with recent activity (velocity)
        # Tiebreakers: uses (lifetime value), then id (determinism)
        if all_lessons:
            all_lessons.sort(key=lambda l: (l.uses * 0.7 + l.velocity * 0.3, l.uses, l.id), reverse=True)

        top_lessons = all_lessons[:top_n]
        system_count = len([l for l in all_lessons if l.level == "system"])
        project_count = len([l for l in all_lessons if l.level == "project"])
        total_tokens = sum(l.tokens for l in all_lessons)

        # Log session start BEFORE any early returns (for observability)
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

        Uses a hybrid caching strategy:
        1. Check cache for exact query hash match
        2. Check cache for similar queries (Jaccard similarity > 0.7)
        3. Fall back to Haiku API call on cache miss
        4. Cache results for future use (7-day TTL)

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

        # Build lesson map for score construction
        lesson_map = {l.id: l for l in all_lessons}

        # Check cache first
        cache = _load_relevance_cache()
        cache_hit = _find_cache_hit(query_text, cache)

        if cache_hit:
            cache_key, cached_scores = cache_hit
            # Reconstruct scored_lessons from cached scores
            scored_lessons = []
            for lesson_id, score in cached_scores.items():
                if lesson_id in lesson_map:
                    scored_lessons.append(
                        ScoredLesson(lesson=lesson_map[lesson_id], score=score)
                    )

            # Sort by score descending, then by uses descending
            scored_lessons.sort(key=lambda sl: (-sl.score, -sl.lesson.uses))

            duration_ms = int((time.time() - start_time) * 1000)
            top_scores = [(sl.lesson.id, sl.score) for sl in scored_lessons[:3]]
            logger.relevance_score(
                query_len, lesson_count, duration_ms, top_scores, cache_hit=True
            )

            return RelevanceResult(
                scored_lessons=scored_lessons,
                query_text=query_text,
            )

        # Cache miss - call Haiku
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
            scored_lessons = []
            scores_dict = {}  # For caching
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
                        scores_dict[lesson_id] = score

            # Sort by score descending, then by uses descending
            scored_lessons.sort(key=lambda sl: (-sl.score, -sl.lesson.uses))

            # Cache the results
            _update_cache(query_text, scores_dict, cache)
            _save_relevance_cache(cache)

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
    # Level/ID Parser Helpers
    # -------------------------------------------------------------------------

    def _get_level_from_id(self, lesson_id: str) -> str:
        """Extract level from lesson ID (S###=system, L###=project)."""
        return "system" if lesson_id.startswith("S") else "project"

    def _get_file_path_for_id(self, lesson_id: str) -> Path:
        """Get lesson file path from ID."""
        level = self._get_level_from_id(lesson_id)
        return self.system_lessons_file if level == "system" else self.project_lessons_file

    # -------------------------------------------------------------------------
    # Helper Methods for Testing
    # -------------------------------------------------------------------------

    def _update_lesson_date(self, lesson_id: str, last_used: date) -> None:
        """Update a lesson's last-used date (for testing)."""
        level = self._get_level_from_id(lesson_id)
        file_path = self._get_file_path_for_id(lesson_id)

        if not file_path.exists():
            return

        def update_fn(lessons):
            for lesson in lessons:
                if lesson.id == lesson_id:
                    lesson.last_used = last_used
                    break

        self._atomic_update_lessons_file(file_path, update_fn, level)

    def _set_lesson_uses(self, lesson_id: str, uses: int) -> None:
        """Set a lesson's uses count (for testing)."""
        level = self._get_level_from_id(lesson_id)
        file_path = self._get_file_path_for_id(lesson_id)

        if not file_path.exists():
            return

        def update_fn(lessons):
            for lesson in lessons:
                if lesson.id == lesson_id:
                    lesson.uses = uses
                    break

        self._atomic_update_lessons_file(file_path, update_fn, level)

    def _set_lesson_velocity(self, lesson_id: str, velocity: float) -> None:
        """Set a lesson's velocity (for testing)."""
        level = self._get_level_from_id(lesson_id)
        file_path = self._get_file_path_for_id(lesson_id)

        if not file_path.exists():
            return

        def update_fn(lessons):
            for lesson in lessons:
                if lesson.id == lesson_id:
                    lesson.velocity = velocity
                    break

        self._atomic_update_lessons_file(file_path, update_fn, level)

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

    def _atomic_update_lessons_file(
        self,
        file_path: Path,
        update_fn: Callable[[List[Lesson]], None],
        level: str = "project"
    ) -> None:
        """Atomically update a lessons file with locking.

        This helper consolidates the common pattern of:
        1. Acquire file lock
        2. Parse lessons from file
        3. Modify lessons list (via update_fn)
        4. Write lessons back to file

        Args:
            file_path: Path to the lessons file
            update_fn: Function that modifies the lessons list in-place
            level: "system" or "project"
        """
        with FileLock(file_path):
            lessons = self._parse_lessons_file(file_path, level)
            update_fn(lessons)
            self._write_lessons_file(file_path, lessons, level)

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
                    # Log parse failures - prevents silent data loss
                    logger = get_logger()
                    logger.error(
                        operation="parse_lesson",
                        error=f"Failed to parse at line {idx + 1}",
                        context={"line": lines[idx][:60]},
                    )
                    idx += 1
            else:
                idx += 1

        return lessons

    def _write_lessons_file(self, file_path: Path, lessons: List[Lesson], level: str) -> None:
        """Write lessons back to file."""
        # Sort lessons by numerical ID for consistent ordering
        def lesson_sort_key(lesson: Lesson) -> int:
            try:
                return int(lesson.id[1:])  # L001 -> 1, S042 -> 42
            except ValueError:
                return 9999  # Put malformed IDs at end
        lessons = sorted(lessons, key=lesson_sort_key)

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
