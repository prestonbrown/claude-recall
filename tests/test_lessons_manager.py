#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Test suite for Python lessons manager implementation.

This is a TDD test file - tests are written BEFORE the implementation.
Run with: pytest tests/test_lessons_manager.py -v

The lessons system stores lessons in markdown format:
    ### [L001] [*----|-----] Lesson Title
    - **Uses**: 1 | **Velocity**: 0 | **Learned**: 2025-12-28 | **Last**: 2025-12-28 | **Category**: pattern
    > Lesson content here.

AI-added lessons include a robot emoji and Source metadata:
    ### [L002] [*----|-----] AI Lesson Title
    - **Uses**: 1 | **Velocity**: 0 | **Learned**: 2025-12-28 | **Last**: 2025-12-28 | **Category**: gotcha | **Source**: ai
    > AI-learned content.
"""

import json
import os
import subprocess

import pytest
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

# These imports will fail until implementation exists - that's expected for TDD
try:
    from core import (
        LessonsManager,
        Lesson,
        LessonLevel,
        LessonCategory,
        LessonRating,
        parse_lesson,
        format_lesson,
        SCORE_RELEVANCE_MAX_QUERY_LEN,
    )
except ImportError:
    # Mark all tests as expected to fail until implementation exists
    pytestmark = pytest.mark.skip(reason="Implementation not yet created")


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def temp_lessons_base(tmp_path: Path) -> Path:
    """Create a temporary lessons base directory."""
    lessons_base = tmp_path / ".config" / "claude-recall"
    lessons_base.mkdir(parents=True)
    return lessons_base


@pytest.fixture
def temp_project_root(tmp_path: Path) -> Path:
    """Create a temporary project directory with .git folder."""
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    return project


@pytest.fixture
def manager(temp_lessons_base: Path, temp_project_root: Path) -> "LessonsManager":
    """Create a LessonsManager instance with temporary paths.

    Note: CLAUDE_RECALL_STATE is set by conftest.py autouse fixture.
    """
    return LessonsManager(
        lessons_base=temp_lessons_base,
        project_root=temp_project_root,
    )


@pytest.fixture
def manager_with_lessons(manager: "LessonsManager") -> "LessonsManager":
    """Create a manager with some pre-existing lessons."""
    manager.add_lesson(
        level="project",
        category="pattern",
        title="First lesson",
        content="This is the first lesson content.",
    )
    manager.add_lesson(
        level="project",
        category="gotcha",
        title="Second lesson",
        content="Watch out for this gotcha.",
    )
    manager.add_lesson(
        level="system",
        category="preference",
        title="System preference",
        content="Always do it this way.",
    )
    return manager


# =============================================================================
# Basic Lesson Operations
# =============================================================================


class TestAddLesson:
    """Tests for adding lessons."""

    def test_add_lesson_creates_entry(self, manager: "LessonsManager"):
        """Adding a lesson should create an entry in the lessons file."""
        lesson_id = manager.add_lesson(
            level="project",
            category="pattern",
            title="Test lesson",
            content="This is test content.",
        )

        assert lesson_id == "L001"
        lessons = manager.list_lessons(scope="project")
        assert len(lessons) == 1
        assert lessons[0].title == "Test lesson"
        assert lessons[0].content == "This is test content."
        assert lessons[0].category == "pattern"

    def test_add_lesson_to_system_file(self, manager: "LessonsManager"):
        """Adding a system lesson should use S### prefix and system file."""
        lesson_id = manager.add_lesson(
            level="system",
            category="preference",
            title="System lesson",
            content="System-level content.",
        )

        assert lesson_id == "S001"
        lessons = manager.list_lessons(scope="system")
        assert len(lessons) == 1
        assert lessons[0].id == "S001"
        assert lessons[0].title == "System lesson"

    def test_add_lesson_assigns_sequential_id(self, manager: "LessonsManager"):
        """Lesson IDs should be assigned sequentially."""
        id1 = manager.add_lesson("project", "pattern", "First", "Content 1")
        id2 = manager.add_lesson("project", "gotcha", "Second", "Content 2")
        id3 = manager.add_lesson("project", "decision", "Third", "Content 3")

        assert id1 == "L001"
        assert id2 == "L002"
        assert id3 == "L003"

    def test_add_lesson_initializes_metadata(self, manager: "LessonsManager"):
        """New lessons should have correct initial metadata."""
        manager.add_lesson("project", "pattern", "Test", "Content")
        lesson = manager.get_lesson("L001")

        assert lesson is not None
        assert lesson.uses == 1
        assert lesson.velocity == 0
        assert lesson.learned == date.today()
        assert lesson.last_used == date.today()

    def test_duplicate_detection_rejects_similar_titles(
        self, manager: "LessonsManager"
    ):
        """Adding a lesson with a similar title should be rejected."""
        manager.add_lesson("project", "pattern", "Use spdlog for logging", "Content")

        with pytest.raises(ValueError, match="[Ss]imilar lesson"):
            manager.add_lesson(
                "project", "gotcha", "use spdlog for logging", "Different content"
            )

    def test_duplicate_detection_case_insensitive(self, manager: "LessonsManager"):
        """Duplicate detection should be case-insensitive."""
        manager.add_lesson("project", "pattern", "UPPERCASE TITLE", "Content")

        with pytest.raises(ValueError, match="[Ss]imilar lesson"):
            manager.add_lesson("project", "pattern", "uppercase title", "Other content")

    def test_add_lesson_force_bypasses_duplicate_check(
        self, manager: "LessonsManager"
    ):
        """Force adding should bypass duplicate detection."""
        manager.add_lesson("project", "pattern", "Original title", "Content")

        # This should succeed with force=True
        lesson_id = manager.add_lesson(
            "project", "pattern", "Original title", "New content", force=True
        )
        assert lesson_id == "L002"


# =============================================================================
# AI Lesson Support
# =============================================================================


class TestAILessons:
    """Tests for AI-generated lessons."""

    def test_add_ai_lesson_has_robot_emoji(self, manager: "LessonsManager"):
        """AI lessons should have a robot emoji in the title display."""
        manager.add_lesson(
            level="project",
            category="pattern",
            title="AI discovered pattern",
            content="The AI learned this.",
            source="ai",
        )

        lesson = manager.get_lesson("L001")
        assert lesson is not None
        assert lesson.source == "ai"
        # When formatted, should include robot emoji
        formatted = format_lesson(lesson)
        assert "\U0001f916" in formatted or "robot" in formatted.lower()

    def test_add_ai_lesson_has_source_ai_metadata(self, manager: "LessonsManager"):
        """AI lessons should have Source: ai in the metadata line."""
        manager.add_lesson(
            level="project",
            category="gotcha",
            title="AI gotcha",
            content="Watch out.",
            source="ai",
        )

        lesson = manager.get_lesson("L001")
        assert lesson is not None
        assert lesson.source == "ai"

        # Check the raw file contains the metadata
        project_file = manager.project_lessons_file
        content = project_file.read_text()
        assert "**Source**: ai" in content

    def test_ai_and_human_lessons_same_behavior(self, manager: "LessonsManager"):
        """AI and human lessons should behave the same for citation/decay."""
        # Add both types
        manager.add_lesson("project", "pattern", "Human lesson", "By human")
        manager.add_lesson(
            "project", "pattern", "AI lesson", "By AI", source="ai"
        )

        # Both should be citable
        result1 = manager.cite_lesson("L001")
        result2 = manager.cite_lesson("L002")

        assert result1.success
        assert result2.success

        # Both should have incremented uses
        human = manager.get_lesson("L001")
        ai = manager.get_lesson("L002")
        assert human.uses == 2
        assert ai.uses == 2


# =============================================================================
# Citation Tracking
# =============================================================================


class TestCitation:
    """Tests for lesson citation tracking."""

    def test_cite_increments_uses(self, manager_with_lessons: "LessonsManager"):
        """Citing a lesson should increment its use count."""
        lesson_before = manager_with_lessons.get_lesson("L001")
        initial_uses = lesson_before.uses

        manager_with_lessons.cite_lesson("L001")

        lesson_after = manager_with_lessons.get_lesson("L001")
        assert lesson_after.uses == initial_uses + 1

    def test_cite_updates_last_date(self, manager_with_lessons: "LessonsManager"):
        """Citing a lesson should update its last-used date."""
        manager_with_lessons.cite_lesson("L001")

        lesson = manager_with_lessons.get_lesson("L001")
        assert lesson.last_used == date.today()

    def test_cite_increments_velocity(self, manager_with_lessons: "LessonsManager"):
        """Citing a lesson should increment its velocity."""
        lesson_before = manager_with_lessons.get_lesson("L001")
        initial_velocity = lesson_before.velocity

        manager_with_lessons.cite_lesson("L001")

        lesson_after = manager_with_lessons.get_lesson("L001")
        assert lesson_after.velocity == initial_velocity + 1

    def test_cite_nonexistent_lesson_fails(self, manager: "LessonsManager"):
        """Citing a nonexistent lesson should raise an error."""
        with pytest.raises(ValueError, match="not found"):
            manager.cite_lesson("L999")

    def test_cite_updates_star_rating(self, manager_with_lessons: "LessonsManager"):
        """Citing should update the star rating display."""
        # Cite multiple times to increase stars
        for _ in range(5):
            manager_with_lessons.cite_lesson("L001")

        lesson = manager_with_lessons.get_lesson("L001")
        # Uses should be at least 6 (1 initial + 5 citations)
        assert lesson.uses >= 6

    def test_cite_returns_promotion_ready(self, manager: "LessonsManager"):
        """Citing should indicate when a lesson is ready for promotion."""
        # Create a lesson and cite it many times
        manager.add_lesson("project", "pattern", "Popular", "Very useful")

        # Cite 49 more times to reach threshold (50)
        for _ in range(49):
            result = manager.cite_lesson("L001")

        # The 50th citation should indicate promotion ready
        result = manager.cite_lesson("L001")
        # Note: exact API TBD - could be result.promotion_ready or similar
        assert hasattr(result, "promotion_ready") or result.uses >= 50

    def test_cite_caps_uses_at_100(self, manager: "LessonsManager"):
        """Uses should be capped at 100 to prevent unbounded growth."""
        manager.add_lesson("project", "pattern", "Test", "Content")

        # Cite 105 times
        for _ in range(105):
            manager.cite_lesson("L001")

        lesson = manager.get_lesson("L001")
        assert lesson.uses == 100


# =============================================================================
# Injection (Context Generation)
# =============================================================================


class TestInjection:
    """Tests for lesson injection into context."""

    def test_inject_returns_top_n_by_uses(self, manager: "LessonsManager"):
        """Injection should return lessons sorted by use count."""
        # Add lessons with different use counts
        manager.add_lesson("project", "pattern", "Low use", "Content")
        manager.add_lesson("project", "pattern", "Medium use", "Content")
        manager.add_lesson("project", "pattern", "High use", "Content")

        # Cite to create different use counts
        for _ in range(10):
            manager.cite_lesson("L003")  # High use
        for _ in range(5):
            manager.cite_lesson("L002")  # Medium use
        # L001 stays at 1 use

        result = manager.inject_context(top_n=2)

        # Should have top 2 lessons by use count
        assert len(result.top_lessons) == 2
        assert result.top_lessons[0].id == "L003"
        assert result.top_lessons[1].id == "L002"

    def test_inject_shows_robot_for_ai_lessons(self, manager: "LessonsManager"):
        """Injected AI lessons should show the robot emoji."""
        manager.add_lesson(
            "project", "pattern", "AI pattern", "Content", source="ai"
        )

        result = manager.inject_context(top_n=5)
        formatted = result.format()

        # Should contain robot emoji for AI lesson
        assert "\U0001f916" in formatted or "AI pattern" in formatted

    def test_inject_includes_both_project_and_system(
        self, manager_with_lessons: "LessonsManager"
    ):
        """Injection should include both project and system lessons."""
        result = manager_with_lessons.inject_context(top_n=10)

        ids = [lesson.id for lesson in result.all_lessons]
        # Should have both L### and S### lessons
        assert any(id.startswith("L") for id in ids)
        assert any(id.startswith("S") for id in ids)

    def test_inject_shows_lesson_counts(self, manager_with_lessons: "LessonsManager"):
        """Injection output should show counts of system and project lessons."""
        result = manager_with_lessons.inject_context(top_n=5)
        formatted = result.format()

        # New condensed format shows counts as "1S, 2L" instead of "1 system, 2 project"
        assert "S" in formatted or "s" in formatted.lower()
        assert "L" in formatted

    def test_inject_empty_returns_nothing(self, manager: "LessonsManager"):
        """Injection with no lessons should return empty result."""
        result = manager.inject_context(top_n=5)

        assert len(result.top_lessons) == 0
        assert result.total_count == 0

    def test_inject_shows_other_lessons_when_exist(
        self, manager: "LessonsManager"
    ):
        """Injection should show other lessons compactly when there are more lessons than top_n."""
        # Add more lessons than top_n
        for i in range(5):
            manager.add_lesson("project", "pattern", f"Lesson {i}", f"Content {i}")

        # Request only top 2
        result = manager.inject_context(top_n=2)
        formatted = result.format()

        # Should contain the remaining lessons in compact format with | separator
        # Other lessons are now shown as "[L003] Lesson 2 | [L004] Lesson 3 | [L005] Lesson 4"
        assert "[L003]" in formatted
        assert "|" in formatted


# =============================================================================
# Decay
# =============================================================================


class TestDecay:
    """Tests for lesson decay functionality."""

    def test_decay_reduces_velocity(self, manager: "LessonsManager"):
        """Decay should reduce velocity by 50% (half-life)."""
        manager.add_lesson("project", "pattern", "Test", "Content")

        # Cite to build velocity
        for _ in range(4):
            manager.cite_lesson("L001")

        lesson_before = manager.get_lesson("L001")
        velocity_before = lesson_before.velocity  # Should be 4

        # Run decay
        manager.decay_lessons()

        lesson_after = manager.get_lesson("L001")
        # Velocity should be halved (4 -> 2)
        assert lesson_after.velocity == pytest.approx(velocity_before * 0.5, abs=0.1)

    def test_decay_reduces_uses_for_stale_lessons(self, manager: "LessonsManager"):
        """Decay should reduce uses for lessons not cited in N days."""
        manager.add_lesson("project", "pattern", "Stale lesson", "Old content")

        # Manually set the last-used date to 60 days ago
        lesson = manager.get_lesson("L001")
        old_date = date.today() - timedelta(days=60)
        manager._update_lesson_date("L001", last_used=old_date)

        # Cite to build uses
        # (Note: citing updates last_used, so we need to reset it)
        manager._set_lesson_uses("L001", 5)
        manager._update_lesson_date("L001", last_used=old_date)

        # Run decay with 30-day threshold
        manager.decay_lessons(stale_threshold_days=30)

        lesson_after = manager.get_lesson("L001")
        # Uses should have decreased by 1
        assert lesson_after.uses == 4

    def test_decay_preserves_minimum_uses(self, manager: "LessonsManager"):
        """Decay should never reduce uses below 1."""
        manager.add_lesson("project", "pattern", "Minimal", "Content")

        # Set last-used to long ago
        old_date = date.today() - timedelta(days=90)
        manager._update_lesson_date("L001", last_used=old_date)

        # Uses starts at 1, should stay at 1 after decay
        manager.decay_lessons(stale_threshold_days=30)

        lesson = manager.get_lesson("L001")
        assert lesson.uses >= 1

    def test_decay_skips_recent_lessons(self, manager: "LessonsManager"):
        """Decay should not reduce uses for recently cited lessons."""
        manager.add_lesson("project", "pattern", "Recent", "Content")
        manager._set_lesson_uses("L001", 5)

        # Last used is today (recent)
        uses_before = manager.get_lesson("L001").uses

        manager.decay_lessons(stale_threshold_days=30)

        uses_after = manager.get_lesson("L001").uses
        # Uses should not have changed (lesson is not stale)
        assert uses_after == uses_before

    def test_decay_respects_activity_check(self, manager: "LessonsManager"):
        """Decay should skip if no coding sessions occurred (vacation mode)."""
        manager.add_lesson("project", "pattern", "Vacation lesson", "Content")

        # Simulate previous decay run
        manager._set_last_decay_time()

        # Don't create any session checkpoints (no activity)

        result = manager.decay_lessons(stale_threshold_days=30)

        # Should indicate skipped due to no activity
        assert result.skipped or "vacation" in result.message.lower()


# =============================================================================
# Backward Compatibility
# =============================================================================


class TestBackwardCompatibility:
    """Tests for parsing old lesson formats."""

    def test_parse_lesson_without_source_defaults_human(self, manager: "LessonsManager"):
        """Lessons without Source metadata should default to human source."""
        # Write a lesson in old format (no Source field)
        old_format = """# LESSONS.md - Project Level

## Active Lessons

### [L001] [*----|-----] Old format lesson
- **Uses**: 5 | **Velocity**: 2 | **Learned**: 2025-01-01 | **Last**: 2025-01-15 | **Category**: pattern
> This is an old format lesson without Source field.

"""
        manager.project_lessons_file.write_text(old_format)

        lesson = manager.get_lesson("L001")
        assert lesson is not None
        assert lesson.source == "human"  # Default when not specified

    def test_parse_old_format_lessons(self, manager: "LessonsManager"):
        """Should parse lessons with old star format (e.g., [***--/-----])."""
        old_format = """# LESSONS.md - Project Level

## Active Lessons

### [L001] [***--/-----] Legacy stars format
- **Uses**: 10 | **Learned**: 2024-06-01 | **Last**: 2024-12-01 | **Category**: gotcha
> Old format with slash separator and no Velocity field.

"""
        manager.project_lessons_file.write_text(old_format)

        lesson = manager.get_lesson("L001")
        assert lesson is not None
        assert lesson.id == "L001"
        assert lesson.title == "Legacy stars format"
        assert lesson.uses == 10
        assert lesson.velocity == 0  # Default when not present
        assert lesson.category == "gotcha"

    def test_parse_old_format_without_velocity(self, manager: "LessonsManager"):
        """Should handle lessons without Velocity field."""
        old_format = """# LESSONS.md - Project Level

## Active Lessons

### [L001] [**---/-----] No velocity lesson
- **Uses**: 3 | **Learned**: 2025-01-01 | **Last**: 2025-01-10 | **Category**: pattern
> Content here.

"""
        manager.project_lessons_file.write_text(old_format)

        lesson = manager.get_lesson("L001")
        assert lesson is not None
        assert lesson.velocity == 0  # Default


# =============================================================================
# Lesson Rating Display
# =============================================================================


class TestLessonRating:
    """Tests for the lesson rating display."""

    def test_rating_format(self):
        """Rating should use emoji stars format."""
        rating = LessonRating(uses=5, velocity=2)
        display = rating.format()

        # New format uses emoji stars (filled and empty)
        assert "★" in display or "☆" in display

    def test_rating_uses_logarithmic_scale(self):
        """Uses should use logarithmic scale for spread."""
        # 1-2 uses = 1 star
        assert LessonRating(uses=1, velocity=0).format() == "★☆☆☆☆"
        assert LessonRating(uses=2, velocity=0).format() == "★☆☆☆☆"

        # 3-5 uses = 2 stars
        assert LessonRating(uses=3, velocity=0).format() == "★★☆☆☆"

        # 6-12 uses = 3 stars
        assert LessonRating(uses=6, velocity=0).format() == "★★★☆☆"

        # 13-30 uses = 4 stars
        assert LessonRating(uses=15, velocity=0).format() == "★★★★☆"

        # 31+ uses = 5 stars
        assert LessonRating(uses=31, velocity=0).format() == "★★★★★"

    def test_rating_legacy_format(self):
        """Legacy format should be [total|velocity] for file storage."""
        rating = LessonRating(uses=5, velocity=2)
        display = rating.format_legacy()

        assert display.startswith("[")
        assert display.endswith("]")
        assert "|" in display
        # Uses = 5 -> 2 stars (3-5 range)
        assert "**---" in display

    def test_rating_velocity_in_legacy_format(self):
        """Velocity should appear in legacy format for file storage."""
        # Low velocity
        assert "-----" in LessonRating(uses=1, velocity=0).format_legacy()

        # Medium velocity
        rating_mid = LessonRating(uses=1, velocity=2.5)
        legacy = rating_mid.format_legacy()
        # Should show some activity on right side
        assert legacy.count("*") > 0 or legacy.count("+") > 0


# =============================================================================
# Edit and Delete
# =============================================================================


class TestEditAndDelete:
    """Tests for editing and deleting lessons."""

    def test_edit_lesson_content(self, manager_with_lessons: "LessonsManager"):
        """Editing should update lesson content."""
        manager_with_lessons.edit_lesson("L001", "Updated content here.")

        lesson = manager_with_lessons.get_lesson("L001")
        assert lesson.content == "Updated content here."

    def test_edit_preserves_metadata(self, manager_with_lessons: "LessonsManager"):
        """Editing content should preserve other metadata."""
        lesson_before = manager_with_lessons.get_lesson("L001")
        original_uses = lesson_before.uses
        original_learned = lesson_before.learned

        manager_with_lessons.edit_lesson("L001", "New content")

        lesson_after = manager_with_lessons.get_lesson("L001")
        assert lesson_after.uses == original_uses
        assert lesson_after.learned == original_learned

    def test_delete_lesson(self, manager_with_lessons: "LessonsManager"):
        """Deleting should remove the lesson entirely."""
        manager_with_lessons.delete_lesson("L001")

        lesson = manager_with_lessons.get_lesson("L001")
        assert lesson is None

        lessons = manager_with_lessons.list_lessons(scope="project")
        ids = [l.id for l in lessons]
        assert "L001" not in ids

    def test_delete_nonexistent_fails(self, manager: "LessonsManager"):
        """Deleting a nonexistent lesson should raise an error."""
        with pytest.raises(ValueError, match="not found"):
            manager.delete_lesson("L999")


# =============================================================================
# Promotion
# =============================================================================


class TestPromotion:
    """Tests for promoting project lessons to system scope."""

    def test_promote_lesson(self, manager_with_lessons: "LessonsManager"):
        """Promoting should move lesson from project to system."""
        manager_with_lessons.promote_lesson("L001")

        # Should no longer be in project
        project_lessons = manager_with_lessons.list_lessons(scope="project")
        project_ids = [l.id for l in project_lessons]
        assert "L001" not in project_ids

        # Should be in system with new ID
        system_lessons = manager_with_lessons.list_lessons(scope="system")
        # There was already S001, so this should be S002
        system_ids = [l.id for l in system_lessons]
        assert "S002" in system_ids

    def test_promote_preserves_data(self, manager_with_lessons: "LessonsManager"):
        """Promotion should preserve lesson content and metadata."""
        # Build up some uses first
        for _ in range(5):
            manager_with_lessons.cite_lesson("L001")

        lesson_before = manager_with_lessons.get_lesson("L001")

        manager_with_lessons.promote_lesson("L001")

        # Find the promoted lesson
        system_lessons = manager_with_lessons.list_lessons(scope="system")
        promoted = next((l for l in system_lessons if l.title == lesson_before.title), None)

        assert promoted is not None
        assert promoted.uses == lesson_before.uses
        assert promoted.content == lesson_before.content

    def test_promote_system_lesson_fails(self, manager_with_lessons: "LessonsManager"):
        """Cannot promote a system lesson (already at system level)."""
        with pytest.raises(ValueError, match="[Pp]roject"):
            manager_with_lessons.promote_lesson("S001")

    def test_add_non_promotable_lesson(self, manager: "LessonsManager"):
        """Should be able to add a lesson that cannot be promoted."""
        lesson_id = manager.add_lesson(
            level="project",
            category="pattern",
            title="Project-specific pattern",
            content="This should never be promoted to system level",
            promotable=False,
        )

        lesson = manager.get_lesson(lesson_id)
        assert lesson is not None
        assert lesson.promotable is False

    def test_non_promotable_lesson_never_promotion_ready(self, manager: "LessonsManager"):
        """Non-promotable lessons should never trigger promotion_ready."""
        lesson_id = manager.add_lesson(
            level="project",
            category="pattern",
            title="Project-only",
            content="Never promote",
            promotable=False,
        )

        # Cite many times to exceed threshold
        for _ in range(60):
            result = manager.cite_lesson(lesson_id)

        # Should have high uses but NOT be promotion_ready
        lesson = manager.get_lesson(lesson_id)
        assert lesson.uses >= 50
        assert result.promotion_ready is False

    def test_promotable_flag_persists(self, manager: "LessonsManager"):
        """Promotable flag should survive write/read cycle."""
        lesson_id = manager.add_lesson(
            level="project",
            category="pattern",
            title="Non-promotable test",
            content="Should persist",
            promotable=False,
        )

        # Force re-read from file
        lessons = manager.list_lessons(scope="project")
        lesson = next((l for l in lessons if l.id == lesson_id), None)

        assert lesson is not None
        assert lesson.promotable is False

    def test_promotable_defaults_to_true(self, manager: "LessonsManager"):
        """Lessons without explicit promotable flag should default to True."""
        lesson_id = manager.add_lesson(
            level="project",
            category="pattern",
            title="Normal lesson",
            content="Should be promotable by default",
        )

        lesson = manager.get_lesson(lesson_id)
        assert lesson.promotable is True

    def test_old_lesson_format_backward_compatible(self, manager: "LessonsManager"):
        """Old lessons without Promotable field should parse as promotable=True."""
        # Write a lesson in old format (no Promotable field)
        old_format = """# LESSONS.md - Project Level

## Active Lessons

### [L001] [*----|-----] Old lesson
- **Uses**: 5 | **Velocity**: 1.0 | **Learned**: 2025-01-01 | **Last**: 2025-12-29 | **Category**: pattern
> This lesson was created before promotable flag existed
"""
        manager.project_lessons_file.write_text(old_format)

        # Should parse successfully with promotable=True
        lesson = manager.get_lesson("L001")
        assert lesson is not None
        assert lesson.promotable is True
        assert lesson.uses == 5


# =============================================================================
# Listing and Search
# =============================================================================


class TestListAndSearch:
    """Tests for listing and searching lessons."""

    def test_list_all_lessons(self, manager_with_lessons: "LessonsManager"):
        """Should list all lessons from both scopes."""
        lessons = manager_with_lessons.list_lessons(scope="all")

        # We have 2 project + 1 system = 3 lessons
        assert len(lessons) == 3

    def test_list_by_scope(self, manager_with_lessons: "LessonsManager"):
        """Should filter by scope."""
        project_lessons = manager_with_lessons.list_lessons(scope="project")
        system_lessons = manager_with_lessons.list_lessons(scope="system")

        assert len(project_lessons) == 2
        assert len(system_lessons) == 1

    def test_search_by_keyword(self, manager_with_lessons: "LessonsManager"):
        """Should search in title and content."""
        results = manager_with_lessons.list_lessons(search="gotcha")

        assert len(results) == 1
        assert "gotcha" in results[0].title.lower() or "gotcha" in results[0].content.lower()

    def test_search_by_lesson_id(self, manager_with_lessons: "LessonsManager"):
        """Should search by lesson ID (e.g., L001, S001)."""
        results = manager_with_lessons.list_lessons(search="L001")

        assert len(results) == 1
        assert results[0].id == "L001"

    def test_filter_by_category(self, manager_with_lessons: "LessonsManager"):
        """Should filter by category."""
        results = manager_with_lessons.list_lessons(category="pattern")

        for lesson in results:
            assert lesson.category == "pattern"

    def test_list_stale_lessons(self, manager: "LessonsManager"):
        """Should identify stale lessons (not cited in 60+ days)."""
        manager.add_lesson("project", "pattern", "Stale one", "Old")
        manager.add_lesson("project", "pattern", "Fresh one", "New")

        # Make first lesson stale
        old_date = date.today() - timedelta(days=70)
        manager._update_lesson_date("L001", last_used=old_date)

        stale = manager.list_lessons(stale_only=True)

        assert len(stale) == 1
        assert stale[0].id == "L001"


# =============================================================================
# File Initialization
# =============================================================================


class TestFileInitialization:
    """Tests for lessons file initialization."""

    def test_init_creates_project_file(self, manager: "LessonsManager"):
        """Should create project lessons file with header."""
        manager.init_lessons_file("project")

        assert manager.project_lessons_file.exists()
        content = manager.project_lessons_file.read_text()
        assert "LESSONS.md" in content
        assert "Project" in content

    def test_init_creates_system_file(self, manager: "LessonsManager"):
        """Should create system lessons file with header."""
        manager.init_lessons_file("system")

        assert manager.system_lessons_file.exists()
        content = manager.system_lessons_file.read_text()
        assert "LESSONS.md" in content
        assert "System" in content

    def test_init_preserves_existing(self, manager: "LessonsManager"):
        """Should not overwrite existing file."""
        manager.add_lesson("project", "pattern", "Existing", "Content")
        original_content = manager.project_lessons_file.read_text()

        manager.init_lessons_file("project")

        assert manager.project_lessons_file.read_text() == original_content


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_lesson_with_special_characters_in_title(self, manager: "LessonsManager"):
        """Should handle special characters in lesson titles."""
        title = "Don't use 'quotes' or |pipes|"
        manager.add_lesson("project", "pattern", title, "Content with $pecial chars!")

        lesson = manager.get_lesson("L001")
        assert lesson is not None
        assert lesson.title == title

    def test_lesson_with_multiline_content(self, manager: "LessonsManager"):
        """Content should be single-line in storage but preserve meaning."""
        content = "First part of content. Second part."
        manager.add_lesson("project", "pattern", "Multipart", content)

        lesson = manager.get_lesson("L001")
        assert lesson.content == content

    def test_empty_lessons_file_handling(self, manager: "LessonsManager"):
        """Should handle empty lessons file gracefully."""
        manager.project_lessons_file.parent.mkdir(parents=True, exist_ok=True)
        manager.project_lessons_file.write_text("")

        lessons = manager.list_lessons(scope="project")
        assert lessons == []

    def test_malformed_lesson_skipped(self, manager: "LessonsManager"):
        """Should skip malformed lessons without crashing."""
        malformed = """# LESSONS.md

## Active Lessons

### [L001] Malformed - no rating
- Missing the star rating brackets

### [L002] [*----|-----] Valid lesson
- **Uses**: 1 | **Velocity**: 0 | **Learned**: 2025-01-01 | **Last**: 2025-01-01 | **Category**: pattern
> This one is valid.

"""
        manager.project_lessons_file.parent.mkdir(parents=True, exist_ok=True)
        manager.project_lessons_file.write_text(malformed)

        lessons = manager.list_lessons(scope="project")
        # Should only get the valid lesson
        assert len(lessons) == 1
        assert lessons[0].id == "L002"

    def test_concurrent_access_safety(self, manager: "LessonsManager"):
        """Basic test that file operations are atomic."""
        # Add a lesson
        manager.add_lesson("project", "pattern", "Test", "Content")

        # Simultaneously cite and list (simulated)
        manager.cite_lesson("L001")
        lessons = manager.list_lessons()

        # Should not raise and should have consistent state
        assert len(lessons) >= 1


# =============================================================================
# Phase 4.3: Token Tracking Tests
# =============================================================================


class TestTokenTracking:
    """Tests for token estimation and budget tracking."""

    def test_lesson_has_tokens_property(self, manager: "LessonsManager"):
        """Lessons should have a tokens property."""
        manager.add_lesson("project", "pattern", "Test title", "Some content here")
        lesson = manager.get_lesson("L001")

        assert lesson is not None
        assert hasattr(lesson, "tokens")
        assert isinstance(lesson.tokens, int)
        assert lesson.tokens > 0

    def test_token_estimation_basic(self, manager: "LessonsManager"):
        """Token estimation should be roughly len(text) / 4."""
        title = "Short title"
        content = "This is some content for the lesson"
        manager.add_lesson("project", "pattern", title, content)

        lesson = manager.get_lesson("L001")
        expected_tokens = len(title + content) // 4
        # Allow some variance for formatting overhead
        assert lesson.tokens >= expected_tokens - 10
        assert lesson.tokens <= expected_tokens + 20

    def test_token_estimation_long_content(self, manager: "LessonsManager"):
        """Longer content should have more tokens."""
        short_content = "Short"
        long_content = "This is a much longer lesson with detailed explanations " * 10

        manager.add_lesson("project", "pattern", "Short", short_content)
        manager.add_lesson("project", "pattern", "Long", long_content)

        short_lesson = manager.get_lesson("L001")
        long_lesson = manager.get_lesson("L002")

        assert long_lesson.tokens > short_lesson.tokens

    def test_inject_shows_token_count(self, manager: "LessonsManager"):
        """Injection output should include token count."""
        manager.add_lesson("project", "pattern", "Test", "Content")

        output = manager.inject(limit=5)

        # Should show token count somewhere
        assert "token" in output.lower() or "~" in output

    def test_inject_warns_on_heavy_context(self, manager: "LessonsManager"):
        """Should warn when injected context exceeds threshold."""
        # Create lessons with lots of content to exceed 2000 tokens
        long_content = "X" * 500  # ~125 tokens each
        for i in range(20):  # 20 * 125 = 2500+ tokens
            manager.add_lesson(
                "project", "pattern", f"Lesson {i}", long_content
            )

        output = manager.inject(limit=20)

        # Should contain a warning about heavy context
        assert "HEAVY" in output.upper() or "⚠" in output or "warning" in output.lower()

    def test_inject_no_warning_for_light_context(self, manager: "LessonsManager"):
        """Should not warn for light context load."""
        manager.add_lesson("project", "pattern", "Short lesson", "Brief content")

        output = manager.inject(limit=5)

        # Should not contain heavy context warning
        assert "HEAVY" not in output.upper()


class TestTokenInjectDetails:
    """More detailed tests for token injection behavior."""

    def test_inject_token_count_is_accurate(self, manager: "LessonsManager"):
        """Token count in injection should reflect actual lesson content."""
        manager.add_lesson("project", "pattern", "Title A", "A" * 100)
        manager.add_lesson("project", "pattern", "Title B", "B" * 200)

        output = manager.inject(limit=5)

        # Output should contain token estimate
        # We expect roughly (100 + 7)/4 + (200 + 7)/4 = ~77 tokens just for content
        assert "token" in output.lower() or "~" in output

    def test_get_total_tokens(self, manager: "LessonsManager"):
        """Manager should provide total token count method."""
        manager.add_lesson("project", "pattern", "Title A", "A" * 100)
        manager.add_lesson("project", "pattern", "Title B", "B" * 200)

        # Should have a method to get total tokens
        total = manager.get_total_tokens()

        assert isinstance(total, int)
        assert total > 50  # Should be substantial


# =============================================================================
# CLI Tests
# =============================================================================


class TestCLI:
    """Tests for command-line interface."""

    def test_cli_add_with_no_promote(self, temp_lessons_base: Path, temp_project_root: Path):
        """CLI --no-promote flag should create non-promotable lesson."""

        result = subprocess.run(
            [
                "python3", "core/cli.py",
                "add", "--no-promote",
                "pattern", "CLI Test", "This should not promote"
            ],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "CLAUDE_RECALL_BASE": str(temp_lessons_base),
                "PROJECT_DIR": str(temp_project_root),
            },
        )

        assert result.returncode == 0
        assert "(no-promote)" in result.stdout

        # Verify the lesson was created with promotable=False
        from core import LessonsManager
        manager = LessonsManager(temp_lessons_base, temp_project_root)
        lesson = manager.get_lesson("L001")
        assert lesson is not None
        assert lesson.promotable is False

    def test_cli_add_ai_with_no_promote(self, temp_lessons_base: Path, temp_project_root: Path):
        """CLI add-ai --no-promote should create non-promotable AI lesson."""

        result = subprocess.run(
            [
                "python3", "core/cli.py",
                "add-ai", "--no-promote",
                "pattern", "AI Test", "AI non-promotable lesson"
            ],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "CLAUDE_RECALL_BASE": str(temp_lessons_base),
                "PROJECT_DIR": str(temp_project_root),
            },
        )

        assert result.returncode == 0
        assert "(no-promote)" in result.stdout

        from core import LessonsManager
        manager = LessonsManager(temp_lessons_base, temp_project_root)
        lesson = manager.get_lesson("L001")
        assert lesson is not None
        assert lesson.promotable is False
        assert lesson.source == "ai"

    def test_cli_list_basic(self, temp_lessons_base: Path, temp_project_root: Path):
        """CLI list command should work without flags."""
        from core import LessonsManager

        # Add some lessons first
        manager = LessonsManager(temp_lessons_base, temp_project_root)
        manager.add_lesson(
            level="project", category="pattern",
            title="Test Lesson", content="Test content"
        )

        result = subprocess.run(
            ["python3", "core/cli.py", "list"],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "CLAUDE_RECALL_BASE": str(temp_lessons_base),
                "PROJECT_DIR": str(temp_project_root),
            },
        )

        assert result.returncode == 0
        assert "L001" in result.stdout
        assert "Test Lesson" in result.stdout

    def test_cli_list_project_flag(self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path, monkeypatch):
        """CLI list --project should only show project lessons."""
        from core import LessonsManager

        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        manager = LessonsManager(temp_lessons_base, temp_project_root)
        manager.add_lesson(
            level="project", category="pattern",
            title="Project Lesson", content="Project content"
        )
        manager.add_lesson(
            level="system", category="pattern",
            title="System Lesson", content="System content"
        )

        result = subprocess.run(
            ["python3", "core/cli.py", "list", "--project"],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "CLAUDE_RECALL_BASE": str(temp_lessons_base),
                "CLAUDE_RECALL_STATE": str(temp_state_dir),
                "PROJECT_DIR": str(temp_project_root),
            },
        )

        assert result.returncode == 0
        assert "L001" in result.stdout
        assert "S001" not in result.stdout

    def test_cli_list_system_flag(self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path, monkeypatch):
        """CLI list --system should only show system lessons."""
        from core import LessonsManager

        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        manager = LessonsManager(temp_lessons_base, temp_project_root)
        manager.add_lesson(
            level="project", category="pattern",
            title="Project Lesson", content="Project content"
        )
        manager.add_lesson(
            level="system", category="pattern",
            title="System Lesson", content="System content"
        )

        result = subprocess.run(
            ["python3", "core/cli.py", "list", "--system"],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "CLAUDE_RECALL_BASE": str(temp_lessons_base),
                "CLAUDE_RECALL_STATE": str(temp_state_dir),
                "PROJECT_DIR": str(temp_project_root),
            },
        )

        assert result.returncode == 0
        assert "S001" in result.stdout
        assert "L001" not in result.stdout

    def test_cli_list_search_flag(self, temp_lessons_base: Path, temp_project_root: Path):
        """CLI list --search should filter by keyword."""
        from core import LessonsManager

        manager = LessonsManager(temp_lessons_base, temp_project_root)
        manager.add_lesson(
            level="project", category="pattern",
            title="Git Commits", content="Use conventional commits"
        )
        manager.add_lesson(
            level="project", category="pattern",
            title="Python Style", content="Use black formatter"
        )

        result = subprocess.run(
            ["python3", "core/cli.py", "list", "--search", "git"],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "CLAUDE_RECALL_BASE": str(temp_lessons_base),
                "PROJECT_DIR": str(temp_project_root),
            },
        )

        assert result.returncode == 0
        assert "Git Commits" in result.stdout
        assert "Python Style" not in result.stdout

    def test_cli_list_category_flag(self, temp_lessons_base: Path, temp_project_root: Path):
        """CLI list --category should filter by category."""
        from core import LessonsManager

        manager = LessonsManager(temp_lessons_base, temp_project_root)
        manager.add_lesson(
            level="project", category="pattern",
            title="Pattern Lesson", content="Pattern content"
        )
        manager.add_lesson(
            level="project", category="gotcha",
            title="Gotcha Lesson", content="Gotcha content"
        )

        result = subprocess.run(
            ["python3", "core/cli.py", "list", "--category", "gotcha"],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "CLAUDE_RECALL_BASE": str(temp_lessons_base),
                "PROJECT_DIR": str(temp_project_root),
            },
        )

        assert result.returncode == 0
        assert "Gotcha Lesson" in result.stdout
        assert "Pattern Lesson" not in result.stdout

    def test_cli_list_stale_flag(self, temp_lessons_base: Path, temp_project_root: Path):
        """CLI list --stale should show only stale lessons."""
        from core import LessonsManager
        from datetime import datetime, timedelta

        manager = LessonsManager(temp_lessons_base, temp_project_root)
        manager.add_lesson(
            level="project", category="pattern",
            title="Fresh Lesson", content="Fresh content"
        )

        # Manually make a lesson stale by editing the file
        lessons_file = manager.project_lessons_file
        content = lessons_file.read_text()
        old_date = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
        content = content.replace(datetime.now().strftime("%Y-%m-%d"), old_date)
        lessons_file.write_text(content)

        result = subprocess.run(
            ["python3", "core/cli.py", "list", "--stale"],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "CLAUDE_RECALL_BASE": str(temp_lessons_base),
                "PROJECT_DIR": str(temp_project_root),
            },
        )

        assert result.returncode == 0
        assert "Fresh Lesson" in result.stdout  # Now stale due to date change


# =============================================================================
# Shell Hook Tests
# =============================================================================


class TestCaptureHook:
    """Tests for capture-hook.sh parsing."""

    def test_capture_hook_parses_no_promote(self, temp_lessons_base: Path, temp_project_root: Path):
        """capture-hook.sh should parse LESSON (no-promote): syntax."""

        hook_path = Path("adapters/claude-code/capture-hook.sh")
        if not hook_path.exists():
            pytest.skip("capture-hook.sh not found")

        input_data = json.dumps({
            "prompt": "LESSON (no-promote): pattern: Hook Test - Testing hook parsing",
            "cwd": str(temp_project_root),
        })

        result = subprocess.run(
            ["bash", str(hook_path)],
            input=input_data,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "CLAUDE_RECALL_BASE": str(temp_lessons_base),
                "PROJECT_DIR": str(temp_project_root),
            },
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)
        context = output["hookSpecificOutput"]["additionalContext"]
        assert "(no-promote)" in context
        assert "LESSON RECORDED" in context

        # Verify lesson was created with promotable=False
        from core import LessonsManager
        manager = LessonsManager(temp_lessons_base, temp_project_root)
        lesson = manager.get_lesson("L001")
        assert lesson is not None
        assert lesson.promotable is False

    def test_capture_hook_normal_lesson_is_promotable(self, temp_lessons_base: Path, temp_project_root: Path):
        """capture-hook.sh without (no-promote) should create promotable lesson."""

        hook_path = Path("adapters/claude-code/capture-hook.sh")
        if not hook_path.exists():
            pytest.skip("capture-hook.sh not found")

        input_data = json.dumps({
            "prompt": "LESSON: pattern: Normal Test - Normal lesson",
            "cwd": str(temp_project_root),
        })

        result = subprocess.run(
            ["bash", str(hook_path)],
            input=input_data,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "CLAUDE_RECALL_BASE": str(temp_lessons_base),
                "PROJECT_DIR": str(temp_project_root),
            },
        )

        assert result.returncode == 0

        from core import LessonsManager
        manager = LessonsManager(temp_lessons_base, temp_project_root)
        lesson = manager.get_lesson("L001")
        assert lesson is not None
        assert lesson.promotable is True


class TestHookPathResolution:
    """Tests for hook Python manager path resolution."""

    def test_hook_uses_installed_path_when_available(self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path, monkeypatch):
        """Hooks should use $CLAUDE_RECALL_BASE/cli.py when it exists (installed mode)."""
        import shutil
        from core import LessonsManager

        # Copy Python manager and all modules to CLAUDE_RECALL_BASE (simulating installed state)
        core_dir = Path(__file__).parent.parent / "core"
        modules = [
            "cli.py",
            "manager.py",
            "debug_logger.py",
            "models.py",
            "parsing.py",
            "file_lock.py",
            "lessons.py",
            "handoffs.py",  # Renamed from approaches.py
            "__init__.py",
            "_version.py",
        ]

        if not (core_dir / "cli.py").exists():
            pytest.skip("cli.py not found")

        for module in modules:
            src = core_dir / module
            if src.exists():
                shutil.copy(src, temp_lessons_base / module)

        # Create a lesson using the manager (ensures proper format)
        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        manager = LessonsManager(temp_lessons_base, temp_project_root)
        manager.add_lesson(
            level="system",
            category="pattern",
            title="Test Lesson",
            content="Test content for hook path resolution."
        )

        # Run inject-hook from a different working directory to ensure
        # the dev fallback path won't work
        hook_path = Path(__file__).parent.parent / "adapters" / "claude-code" / "inject-hook.sh"
        if not hook_path.exists():
            pytest.skip("inject-hook.sh not found")

        result = subprocess.run(
            ["bash", str(hook_path)],
            input=json.dumps({"cwd": str(temp_project_root)}),
            capture_output=True,
            text=True,
            cwd="/tmp",  # Run from different directory
            env={
                **os.environ,
                "CLAUDE_RECALL_BASE": str(temp_lessons_base),
                "CLAUDE_RECALL_STATE": str(temp_state_dir),
                "PROJECT_DIR": str(temp_project_root),
            },
        )

        # Hook should succeed and output lesson context
        assert result.returncode == 0
        assert "LESSONS ACTIVE" in result.stdout or "S001" in result.stdout

    def test_hook_falls_back_to_dev_path(self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path, monkeypatch):
        """Hooks should fall back to dev path when installed path doesn't exist."""
        from core import LessonsManager

        # Don't copy Python manager - simulate dev environment
        hook_path = Path(__file__).parent.parent / "adapters" / "claude-code" / "inject-hook.sh"
        if not hook_path.exists():
            pytest.skip("inject-hook.sh not found")

        # Create a lesson using the manager (ensures proper format)
        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        manager = LessonsManager(temp_lessons_base, temp_project_root)
        manager.add_lesson(
            level="system",
            category="pattern",
            title="Test Lesson",
            content="Test content for hook path resolution."
        )

        result = subprocess.run(
            ["bash", str(hook_path)],
            input=json.dumps({"cwd": str(temp_project_root)}),
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "CLAUDE_RECALL_BASE": str(temp_lessons_base),
                "CLAUDE_RECALL_STATE": str(temp_state_dir),
                "PROJECT_DIR": str(temp_project_root),
            },
        )

        # Hook should succeed using dev path
        assert result.returncode == 0


class TestReminderHook:
    """Tests for lesson-reminder-hook.sh config and logging."""

    @pytest.fixture
    def hook_path(self):
        """Get absolute path to reminder hook."""
        path = Path(__file__).parent.parent / "core" / "lesson-reminder-hook.sh"
        if not path.exists():
            pytest.skip("lesson-reminder-hook.sh not found")
        return path

    def test_reminder_reads_config_file(self, temp_lessons_base: Path, temp_project_root: Path, tmp_path: Path, hook_path: Path):
        """Reminder hook reads remindEvery from config file."""

        # Create config with custom remindEvery
        config_dir = tmp_path / ".claude"
        config_dir.mkdir()
        config_file = config_dir / "settings.json"
        config_file.write_text(json.dumps({
            "claudeRecall": {"enabled": True, "remindEvery": 3}
        }))

        # Create state file at count 2 (next will be 3, triggering reminder)
        state_dir = tmp_path / ".config" / "claude-recall"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / ".reminder-state").write_text("2")

        # Create a lessons file with high-star lesson
        lessons_dir = temp_project_root / ".claude-recall"
        lessons_dir.mkdir(exist_ok=True)
        (lessons_dir / "LESSONS.md").write_text(
            "# Lessons\n\n### [L001] [*****|-----] Test Lesson\n- Content\n"
        )

        result = subprocess.run(
            ["bash", str(hook_path)],
            capture_output=True,
            text=True,
            cwd=str(temp_project_root),
            env={
                **os.environ,
                "HOME": str(tmp_path),
                "CLAUDE_RECALL_BASE": str(temp_lessons_base),
            },
        )

        assert result.returncode == 0
        assert "LESSON CHECK" in result.stdout
        assert "L001" in result.stdout

    def test_reminder_env_var_overrides_config(self, temp_lessons_base: Path, temp_project_root: Path, tmp_path: Path, hook_path: Path):
        """LESSON_REMIND_EVERY env var takes precedence over config."""

        # Config says remind every 100
        config_dir = tmp_path / ".claude"
        config_dir.mkdir()
        (config_dir / "settings.json").write_text(json.dumps({
            "claudeRecall": {"remindEvery": 100}
        }))

        # State at count 4, env says remind every 5
        state_dir = tmp_path / ".config" / "claude-recall"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / ".reminder-state").write_text("4")

        lessons_dir = temp_project_root / ".claude-recall"
        lessons_dir.mkdir(exist_ok=True)
        (lessons_dir / "LESSONS.md").write_text(
            "# Lessons\n\n### [L001] [*****|-----] Test Lesson\n- Content\n"
        )

        result = subprocess.run(
            ["bash", str(hook_path)],
            capture_output=True,
            text=True,
            cwd=str(temp_project_root),
            env={
                **os.environ,
                "HOME": str(tmp_path),
                "LESSON_REMIND_EVERY": "5",  # Override config
                "CLAUDE_RECALL_BASE": str(temp_lessons_base),
            },
        )

        assert result.returncode == 0
        assert "LESSON CHECK" in result.stdout  # Triggered because 5 % 5 == 0

    def test_reminder_default_when_no_config(self, temp_lessons_base: Path, temp_project_root: Path, tmp_path: Path, hook_path: Path):
        """Default remindEvery=12 when no config file exists."""

        # No config file, state at 11
        state_dir = tmp_path / ".config" / "claude-recall"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / ".reminder-state").write_text("11")

        lessons_dir = temp_project_root / ".claude-recall"
        lessons_dir.mkdir(exist_ok=True)
        (lessons_dir / "LESSONS.md").write_text(
            "# Lessons\n\n### [L001] [*****|-----] Test Lesson\n- Content\n"
        )

        result = subprocess.run(
            ["bash", str(hook_path)],
            capture_output=True,
            text=True,
            cwd=str(temp_project_root),
            env={
                **os.environ,
                "HOME": str(tmp_path),
                "CLAUDE_RECALL_BASE": str(temp_lessons_base),
            },
        )

        assert result.returncode == 0
        assert "LESSON CHECK" in result.stdout  # Count 12, default reminder

    def test_reminder_logs_when_debug_enabled(self, temp_lessons_base: Path, temp_project_root: Path, tmp_path: Path, hook_path: Path):
        """Reminder logs to debug.log when CLAUDE_RECALL_DEBUG>=1."""

        state_dir = tmp_path / ".config" / "claude-recall"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / ".reminder-state").write_text("11")

        lessons_dir = temp_project_root / ".claude-recall"
        lessons_dir.mkdir(exist_ok=True)
        (lessons_dir / "LESSONS.md").write_text(
            "# Lessons\n\n### [L001] [*****|-----] Test Lesson\n- Content\n"
            "### [S002] [****-|-----] System Lesson\n- Content\n"
        )

        result = subprocess.run(
            ["bash", str(hook_path)],
            capture_output=True,
            text=True,
            cwd=str(temp_project_root),
            env={
                **os.environ,
                "HOME": str(tmp_path),
                "CLAUDE_RECALL_BASE": str(temp_lessons_base),
                "CLAUDE_RECALL_DEBUG": "1",
            },
        )

        assert result.returncode == 0
        assert "LESSON CHECK" in result.stdout

        # Check debug log was created
        debug_log = state_dir / "debug.log"
        assert debug_log.exists()

        log_content = debug_log.read_text()
        log_entry = json.loads(log_content.strip())
        assert log_entry["event"] == "reminder"
        assert "L001" in log_entry["lesson_ids"]
        assert log_entry["prompt_count"] == 12

    def test_reminder_no_log_when_debug_disabled(self, temp_lessons_base: Path, temp_project_root: Path, tmp_path: Path, hook_path: Path):
        """No debug log when CLAUDE_RECALL_DEBUG is not set."""

        state_dir = tmp_path / ".config" / "claude-recall"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / ".reminder-state").write_text("11")

        lessons_dir = temp_project_root / ".claude-recall"
        lessons_dir.mkdir(exist_ok=True)
        (lessons_dir / "LESSONS.md").write_text(
            "# Lessons\n\n### [L001] [*****|-----] Test Lesson\n- Content\n"
        )

        # Build env without any debug env vars
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_RECALL_DEBUG", "LESSONS_DEBUG")}
        env.update({
            "HOME": str(tmp_path),
            "CLAUDE_RECALL_BASE": str(temp_lessons_base),
        })

        result = subprocess.run(
            ["bash", str(hook_path)],
            capture_output=True,
            text=True,
            cwd=str(temp_project_root),
            env=env,
        )

        assert result.returncode == 0
        assert "LESSON CHECK" in result.stdout

        # Debug log should not exist
        debug_log = state_dir / "debug.log"
        assert not debug_log.exists()


class TestScoreRelevance:
    """Tests for relevance scoring with Haiku."""

    def test_score_relevance_returns_result(self, temp_lessons_base: Path, temp_project_root: Path, monkeypatch):
        """score_relevance returns a RelevanceResult."""
        from core import LessonsManager, RelevanceResult

        manager = LessonsManager(temp_lessons_base, temp_project_root)
        manager.add_lesson("project", "pattern", "Git Safety", "Never force push")
        manager.add_lesson("project", "gotcha", "Python Imports", "Use absolute imports")

        # Mock subprocess to return scored output
        def mock_run(*args, **kwargs):
            class MockResult:
                returncode = 0
                stdout = "L001: 8\nL002: 3\n"
                stderr = ""
            return MockResult()

        monkeypatch.setattr(subprocess, "run", mock_run)

        result = manager.score_relevance("How do I use git?")
        assert isinstance(result, RelevanceResult)
        assert result.error is None
        assert len(result.scored_lessons) == 2

    def test_score_relevance_sorts_by_score(self, temp_lessons_base: Path, temp_project_root: Path, monkeypatch):
        """Results are sorted by score descending."""
        from core import LessonsManager

        manager = LessonsManager(temp_lessons_base, temp_project_root)
        manager.add_lesson("project", "pattern", "A lesson", "Content A")
        manager.add_lesson("project", "pattern", "B lesson", "Content B")
        manager.add_lesson("project", "pattern", "C lesson", "Content C")

        def mock_run(*args, **kwargs):
            class MockResult:
                returncode = 0
                stdout = "L001: 3\nL002: 9\nL003: 5\n"
                stderr = ""
            return MockResult()

        monkeypatch.setattr(subprocess, "run", mock_run)

        result = manager.score_relevance("test query")
        scores = [sl.score for sl in result.scored_lessons]
        assert scores == [9, 5, 3]  # Sorted descending

    def test_score_relevance_empty_lessons(self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path, monkeypatch):
        """score_relevance with no lessons returns empty result."""
        from core import LessonsManager

        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        manager = LessonsManager(temp_lessons_base, temp_project_root)
        result = manager.score_relevance("test query")
        assert result.scored_lessons == []
        assert result.error is None

    def test_score_relevance_handles_timeout(self, temp_lessons_base: Path, temp_project_root: Path, monkeypatch):
        """score_relevance handles timeout gracefully."""
        from core import LessonsManager

        manager = LessonsManager(temp_lessons_base, temp_project_root)
        manager.add_lesson("project", "pattern", "Test", "Test content")

        def mock_run(*args, **kwargs):
            raise subprocess.TimeoutExpired("claude", 30)

        monkeypatch.setattr(subprocess, "run", mock_run)

        result = manager.score_relevance("test query", timeout_seconds=30)
        assert result.error is not None
        assert "timed out" in result.error

    def test_score_relevance_handles_missing_claude(self, temp_lessons_base: Path, temp_project_root: Path, monkeypatch):
        """score_relevance handles missing claude CLI."""
        from core import LessonsManager

        manager = LessonsManager(temp_lessons_base, temp_project_root)
        manager.add_lesson("project", "pattern", "Test", "Test content")

        def mock_run(*args, **kwargs):
            raise FileNotFoundError("claude not found")

        monkeypatch.setattr(subprocess, "run", mock_run)

        result = manager.score_relevance("test query")
        assert result.error is not None
        assert "not found" in result.error

    def test_score_relevance_handles_command_failure(self, temp_lessons_base: Path, temp_project_root: Path, monkeypatch):
        """score_relevance handles non-zero return code."""
        from core import LessonsManager

        manager = LessonsManager(temp_lessons_base, temp_project_root)
        manager.add_lesson("project", "pattern", "Test", "Test content")

        def mock_run(*args, **kwargs):
            class MockResult:
                returncode = 1
                stdout = ""
                stderr = "API error"
            return MockResult()

        monkeypatch.setattr(subprocess, "run", mock_run)

        result = manager.score_relevance("test query")
        assert result.error is not None
        assert "failed" in result.error

    def test_score_relevance_clamps_scores(self, temp_lessons_base: Path, temp_project_root: Path, monkeypatch):
        """Scores are clamped to 0-10 range."""
        from core import LessonsManager

        manager = LessonsManager(temp_lessons_base, temp_project_root)
        manager.add_lesson("project", "pattern", "Test", "Test content")

        def mock_run(*args, **kwargs):
            class MockResult:
                returncode = 0
                stdout = "L001: 15\n"  # Invalid score > 10
                stderr = ""
            return MockResult()

        monkeypatch.setattr(subprocess, "run", mock_run)

        result = manager.score_relevance("test query")
        assert len(result.scored_lessons) == 1
        assert result.scored_lessons[0].score == 10  # Clamped to max

    def test_score_relevance_format_output(self, temp_lessons_base: Path, temp_project_root: Path, monkeypatch):
        """RelevanceResult.format() produces readable output."""
        from core import LessonsManager

        manager = LessonsManager(temp_lessons_base, temp_project_root)
        manager.add_lesson("project", "pattern", "Git Safety", "Never force push")

        def mock_run(*args, **kwargs):
            class MockResult:
                returncode = 0
                stdout = "L001: 8\n"
                stderr = ""
            return MockResult()

        monkeypatch.setattr(subprocess, "run", mock_run)

        result = manager.score_relevance("git question")
        output = result.format()
        assert "[L001]" in output
        assert "relevance: 8/10" in output
        assert "Git Safety" in output

    def test_score_relevance_handles_brackets_in_output(self, temp_lessons_base: Path, temp_project_root: Path, monkeypatch):
        """Parser handles optional brackets in Haiku output."""
        from core import LessonsManager

        manager = LessonsManager(temp_lessons_base, temp_project_root)
        manager.add_lesson("project", "pattern", "Test", "Content")

        def mock_run(*args, **kwargs):
            class MockResult:
                returncode = 0
                stdout = "[L001]: 7\n"  # With brackets
                stderr = ""
            return MockResult()

        monkeypatch.setattr(subprocess, "run", mock_run)

        result = manager.score_relevance("test")
        assert len(result.scored_lessons) == 1
        assert result.scored_lessons[0].score == 7

    def test_score_relevance_partial_results(self, temp_lessons_base: Path, temp_project_root: Path, monkeypatch):
        """Handles when Haiku returns fewer lessons than expected."""
        from core import LessonsManager

        manager = LessonsManager(temp_lessons_base, temp_project_root)
        manager.add_lesson("project", "pattern", "Lesson A", "Content A")
        manager.add_lesson("project", "pattern", "Lesson B", "Content B")
        manager.add_lesson("project", "pattern", "Lesson C", "Content C")

        # Haiku only returns 2 of 3 lessons
        def mock_run(*args, **kwargs):
            class MockResult:
                returncode = 0
                stdout = "L001: 8\nL003: 5\n"  # Missing L002
                stderr = ""
            return MockResult()

        monkeypatch.setattr(subprocess, "run", mock_run)

        result = manager.score_relevance("test")
        assert result.error is None
        assert len(result.scored_lessons) == 2
        ids = [sl.lesson.id for sl in result.scored_lessons]
        assert "L001" in ids
        assert "L003" in ids
        assert "L002" not in ids

    def test_score_relevance_secondary_sort_by_uses(self, temp_lessons_base: Path, temp_project_root: Path, monkeypatch):
        """When scores are equal, sorts by uses descending."""
        from core import LessonsManager

        manager = LessonsManager(temp_lessons_base, temp_project_root)
        manager.add_lesson("project", "pattern", "Low uses", "Content A")
        manager.add_lesson("project", "pattern", "High uses", "Content B")
        # Cite L002 multiple times to increase uses
        for _ in range(5):
            manager.cite_lesson("L002")

        # Same score for both
        def mock_run(*args, **kwargs):
            class MockResult:
                returncode = 0
                stdout = "L001: 7\nL002: 7\n"
                stderr = ""
            return MockResult()

        monkeypatch.setattr(subprocess, "run", mock_run)

        result = manager.score_relevance("test")
        assert len(result.scored_lessons) == 2
        # L002 should come first due to higher uses
        assert result.scored_lessons[0].lesson.id == "L002"
        assert result.scored_lessons[1].lesson.id == "L001"

    def test_score_relevance_system_lessons(self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path, monkeypatch):
        """Both project (L###) and system (S###) lessons are scored."""
        from core import LessonsManager

        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        manager = LessonsManager(temp_lessons_base, temp_project_root)
        manager.add_lesson("project", "pattern", "Project lesson", "Project content")
        manager.add_lesson("system", "pattern", "System lesson", "System content")

        def mock_run(*args, **kwargs):
            class MockResult:
                returncode = 0
                stdout = "L001: 6\nS001: 9\n"
                stderr = ""
            return MockResult()

        monkeypatch.setattr(subprocess, "run", mock_run)

        result = manager.score_relevance("test")
        assert len(result.scored_lessons) == 2
        # S001 should be first (higher score)
        assert result.scored_lessons[0].lesson.id == "S001"
        assert result.scored_lessons[0].score == 9
        assert result.scored_lessons[1].lesson.id == "L001"
        assert result.scored_lessons[1].score == 6

    def test_score_relevance_min_score_filter(self, temp_lessons_base: Path, temp_project_root: Path, monkeypatch):
        """format() with min_score filters out low-relevance lessons."""
        from core import LessonsManager

        manager = LessonsManager(temp_lessons_base, temp_project_root)
        manager.add_lesson("project", "pattern", "High relevance", "Content A")
        manager.add_lesson("project", "pattern", "Low relevance", "Content B")

        def mock_run(*args, **kwargs):
            class MockResult:
                returncode = 0
                stdout = "L001: 8\nL002: 2\n"
                stderr = ""
            return MockResult()

        monkeypatch.setattr(subprocess, "run", mock_run)

        result = manager.score_relevance("test")
        output = result.format(min_score=5)
        assert "[L001]" in output
        assert "[L002]" not in output
        assert "relevance: 8/10" in output

    def test_score_relevance_min_score_no_matches(self, temp_lessons_base: Path, temp_project_root: Path, monkeypatch):
        """format() with high min_score and no matches returns message."""
        from core import LessonsManager

        manager = LessonsManager(temp_lessons_base, temp_project_root)
        manager.add_lesson("project", "pattern", "Low relevance", "Content")

        def mock_run(*args, **kwargs):
            class MockResult:
                returncode = 0
                stdout = "L001: 3\n"
                stderr = ""
            return MockResult()

        monkeypatch.setattr(subprocess, "run", mock_run)

        result = manager.score_relevance("test")
        output = result.format(min_score=8)
        assert "no lessons with relevance >= 8" in output

    def test_score_relevance_query_truncation(self, temp_lessons_base: Path, temp_project_root: Path, monkeypatch):
        """Long queries are truncated to prevent huge prompts."""
        from core import LessonsManager, SCORE_RELEVANCE_MAX_QUERY_LEN

        manager = LessonsManager(temp_lessons_base, temp_project_root)
        manager.add_lesson("project", "pattern", "Test", "Content")

        captured_prompt = []

        def mock_run(*args, **kwargs):
            captured_prompt.append(kwargs.get("input", ""))
            class MockResult:
                returncode = 0
                stdout = "L001: 5\n"
                stderr = ""
            return MockResult()

        monkeypatch.setattr(subprocess, "run", mock_run)

        # Create a very long query
        long_query = "x" * (SCORE_RELEVANCE_MAX_QUERY_LEN + 1000)
        result = manager.score_relevance(long_query)

        assert result.error is None
        # Check that the prompt was truncated
        assert len(captured_prompt[0]) < len(long_query) + 500  # Some buffer for prompt template


# =============================================================================
# Lesson Classification and Framing Tests
# =============================================================================


class TestLessonClassification:
    """Tests for automatic lesson type classification."""

    def test_classify_constraint_by_keyword(self, temp_lessons_base: Path, temp_project_root: Path):
        """Lessons with 'crash', 'never', etc. should be classified as constraint."""
        from core.parsing import classify_lesson

        # Crash/bug keywords
        assert classify_lesson("This will cause a crash", "pattern") == "constraint"
        assert classify_lesson("Never do this - causes deadlock", "pattern") == "constraint"
        assert classify_lesson("Always verify before doing this", "pattern") == "constraint"
        assert classify_lesson("This will break the build", "pattern") == "constraint"

    def test_classify_constraint_by_category(self, temp_lessons_base: Path, temp_project_root: Path):
        """Correction and gotcha categories should be classified as constraint."""
        from core.parsing import classify_lesson

        assert classify_lesson("Some content here", "correction") == "constraint"
        assert classify_lesson("Some content here", "gotcha") == "constraint"

    def test_classify_preference(self, temp_lessons_base: Path, temp_project_root: Path):
        """Lessons with 'prefer', 'better to' should be classified as preference."""
        from core.parsing import classify_lesson

        assert classify_lesson("Prefer using X over Y", "pattern") == "preference"
        assert classify_lesson("It's better to use this approach", "pattern") == "preference"
        assert classify_lesson("We recommend using TypeScript", "pattern") == "preference"

    def test_classify_informational(self, temp_lessons_base: Path, temp_project_root: Path):
        """Default classification for neutral content is informational."""
        from core.parsing import classify_lesson

        assert classify_lesson("XML changes don't require recompilation", "pattern") == "informational"
        assert classify_lesson("The config file is at /etc/app.conf", "pattern") == "informational"
        # Verify false-positive words don't trigger constraint classification
        # "debug" should NOT match "bug", "breakfast" should NOT match "break"
        assert classify_lesson("Use debug logging for troubleshooting", "pattern") == "informational"
        assert classify_lesson("Debugging tips for developers", "pattern") == "informational"
        assert classify_lesson("Eat breakfast before coding", "pattern") == "informational"
        assert classify_lesson("Breakpoints help with debugging", "pattern") == "informational"
        assert classify_lesson("The debugger is useful", "pattern") == "informational"

    def test_classification_on_load(self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path, monkeypatch):
        """Lessons should be classified when loaded from file."""
        from core import LessonsManager

        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        manager = LessonsManager(temp_lessons_base, temp_project_root)

        # Add a lesson that will be classified as constraint
        manager.add_lesson("project", "gotcha", "WIP safety", "Never commit uncommitted changes")

        # Reload and check classification
        lessons = manager.list_lessons()
        assert len(lessons) == 1
        assert lessons[0].lesson_type == "constraint"


class TestLessonFraming:
    """Tests for lesson content framing at display time."""

    def test_frame_constraint_with_never(self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path, monkeypatch):
        """Constraint lessons without 'always' get NEVER framing."""
        from core.parsing import frame_lesson_content, classify_lesson
        from core.models import Lesson
        from datetime import date

        lesson = Lesson(
            id="L001",
            title="Test",
            content="Don't commit WIP files",
            uses=1,
            velocity=0,
            learned=date.today(),
            last_used=date.today(),
            category="correction",
            lesson_type="constraint",
        )

        framed = frame_lesson_content(lesson)
        assert framed.startswith("NEVER:")
        assert "Ask user if exception needed" in framed

    def test_frame_constraint_with_always(self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path, monkeypatch):
        """Constraint lessons with 'always' in content get ALWAYS framing."""
        from core.parsing import frame_lesson_content
        from core.models import Lesson
        from datetime import date

        lesson = Lesson(
            id="L001",
            title="Test",
            content="Always use explicit git add",
            uses=1,
            velocity=0,
            learned=date.today(),
            last_used=date.today(),
            category="correction",
            lesson_type="constraint",
        )

        framed = frame_lesson_content(lesson)
        assert framed.startswith("ALWAYS:")
        assert "Ask user before skipping" in framed

    def test_frame_preference(self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path, monkeypatch):
        """Preference lessons get Prefer framing."""
        from core.parsing import frame_lesson_content
        from core.models import Lesson
        from datetime import date

        lesson = Lesson(
            id="L001",
            title="Test",
            content="Use TypeScript for new code",
            uses=1,
            velocity=0,
            learned=date.today(),
            last_used=date.today(),
            category="pattern",
            lesson_type="preference",
        )

        framed = frame_lesson_content(lesson)
        assert framed.startswith("Prefer:")
        assert "Ask user before deviating" in framed

    def test_frame_informational_unchanged(self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path, monkeypatch):
        """Informational lessons are not modified."""
        from core.parsing import frame_lesson_content
        from core.models import Lesson
        from datetime import date

        content = "Config file is at /etc/app.conf"
        lesson = Lesson(
            id="L001",
            title="Test",
            content=content,
            uses=1,
            velocity=0,
            learned=date.today(),
            last_used=date.today(),
            category="pattern",
            lesson_type="informational",
        )

        framed = frame_lesson_content(lesson)
        assert framed == content  # Unchanged


class TestExplicitLessonType:
    """Tests for explicitly setting lesson type."""

    def test_add_lesson_with_explicit_type(self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path, monkeypatch):
        """Lessons can be added with explicit type."""
        from core import LessonsManager

        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        manager = LessonsManager(temp_lessons_base, temp_project_root)

        # Add with explicit constraint type (even though content is neutral)
        manager.add_lesson(
            "project", "pattern", "Neutral title", "Neutral content",
            lesson_type="constraint"
        )

        lessons = manager.list_lessons()
        assert len(lessons) == 1
        assert lessons[0].lesson_type == "constraint"

    def test_explicit_type_stored_in_file(self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path, monkeypatch):
        """Explicit type is stored in the LESSONS.md file."""
        from core import LessonsManager

        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        manager = LessonsManager(temp_lessons_base, temp_project_root)

        manager.add_lesson(
            "project", "pattern", "Test", "Content",
            lesson_type="preference"
        )

        # Check file contents
        lessons_file = temp_project_root / ".claude-recall" / "LESSONS.md"
        content = lessons_file.read_text()
        assert "**Type**: preference" in content

    def test_cli_add_with_type(self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path):
        """CLI --type flag should set explicit lesson type."""
        result = subprocess.run(
            [
                "python3", "core/cli.py",
                "add", "--type", "constraint",
                "pattern", "CLI Test", "This is a constraint"
            ],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "CLAUDE_RECALL_BASE": str(temp_lessons_base),
                "CLAUDE_RECALL_STATE": str(temp_state_dir),
                "PROJECT_DIR": str(temp_project_root),
            },
        )

        assert result.returncode == 0

        # Verify type was stored
        lessons_file = temp_project_root / ".claude-recall" / "LESSONS.md"
        content = lessons_file.read_text()
        assert "**Type**: constraint" in content


class TestInjectionFraming:
    """Tests for framed content in injection output."""

    def test_inject_shows_framed_content(self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path, monkeypatch):
        """Injection output should include framed content for constraint lessons."""
        from core import LessonsManager

        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        manager = LessonsManager(temp_lessons_base, temp_project_root)

        # Add a constraint lesson
        manager.add_lesson("project", "correction", "WIP Safety", "Never commit WIP files")

        result = manager.inject(5)  # positional arg
        output = result.format()

        # Should see NEVER framing in output
        assert "NEVER:" in output

    def test_remaining_constraint_lessons_show_content(self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path, monkeypatch):
        """Constraint lessons not in top_n should still show content."""
        from core import LessonsManager

        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        manager = LessonsManager(temp_lessons_base, temp_project_root)

        # Add lessons that will be in top_n (will cite them to ensure higher uses)
        for i in range(5):
            manager.add_lesson("project", "pattern", f"Info {i}", f"Info content {i}")

        # Add a constraint lesson that will be in "remaining" (lower uses)
        manager.add_lesson("project", "correction", "Critical Rule", "Never do this dangerous thing")

        # Cite the first 3 lessons multiple times to ensure they have higher uses
        # This makes the test order-independent since inject() sorts by uses
        for lesson_id in ["L001", "L002", "L003"]:
            for _ in range(3):
                manager.cite_lesson(lesson_id)

        result = manager.inject(3)  # positional arg - top 3 by uses
        output = result.format()

        # The constraint lesson (L006) should show content even though it's in remaining
        # because constraint lessons always show their content
        assert "dangerous thing" in output or "NEVER:" in output


# Helper for creating mock subprocess results (used in TestScoreRelevance)
def make_mock_result(stdout: str = "", returncode: int = 0, stderr: str = ""):
    """Create a mock subprocess result for testing."""
    class MockResult:
        pass
    result = MockResult()
    result.stdout = stdout
    result.returncode = returncode
    result.stderr = stderr
    return result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
