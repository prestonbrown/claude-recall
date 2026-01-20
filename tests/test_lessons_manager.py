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

    def test_cli_cite_multiple_lessons(self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path):
        """CLI cite command should accept multiple lesson IDs and cite all of them."""
        from core import LessonsManager

        # Create some lessons first
        manager = LessonsManager(temp_lessons_base, temp_project_root)
        manager.add_lesson("project", "pattern", "First", "Content 1")
        manager.add_lesson("project", "pattern", "Second", "Content 2")
        manager.add_lesson("project", "pattern", "Third", "Content 3")

        # Cite multiple lessons in one CLI call
        result = subprocess.run(
            ["python3", "core/cli.py", "cite", "L001", "L002", "L003"],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "CLAUDE_RECALL_BASE": str(temp_lessons_base),
                "CLAUDE_RECALL_STATE": str(temp_state_dir),
                "PROJECT_DIR": str(temp_project_root),
            },
        )

        assert result.returncode == 0, f"CLI failed: {result.stderr}"

        # Should have output for all three citations
        assert result.stdout.count("OK:") == 3, f"Expected 3 OK outputs, got: {result.stdout}"

        # Verify all lessons were cited
        manager2 = LessonsManager(temp_lessons_base, temp_project_root)
        for lesson_id in ["L001", "L002", "L003"]:
            lesson = manager2.get_lesson(lesson_id)
            assert lesson.uses == 2, f"{lesson_id} should have 2 uses (1 initial + 1 cite)"

    def test_cli_cite_batch_with_invalid_id(self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path):
        """CLI cite should continue processing valid IDs when one is invalid."""
        from core import LessonsManager

        manager = LessonsManager(temp_lessons_base, temp_project_root)
        manager.add_lesson("project", "pattern", "First", "Content 1")
        manager.add_lesson("project", "pattern", "Second", "Content 2")

        result = subprocess.run(
            ["python3", "core/cli.py", "cite", "L001", "L999", "L002"],  # L999 doesn't exist
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "CLAUDE_RECALL_BASE": str(temp_lessons_base),
                "CLAUDE_RECALL_STATE": str(temp_state_dir),
                "PROJECT_DIR": str(temp_project_root),
            },
        )

        # Valid citations should succeed (2 out of 3)
        assert result.stdout.count("OK:") == 2, f"Expected 2 OK outputs, got: {result.stdout}"
        # Error should be reported for invalid ID
        assert "Error:L999" in result.stderr, f"Expected error for L999, got: {result.stderr}"


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

    def test_inject_uses_velocity_weighted_ranking(self, manager: "LessonsManager"):
        """Injection should sort by weighted score: uses * 0.7 + velocity * 0.3.

        High-velocity lessons can outrank high-uses lessons when the weighted
        score favors recent activity over lifetime popularity.
        """
        # Add two lessons
        manager.add_lesson("project", "pattern", "Old popular", "Content")  # L001
        manager.add_lesson("project", "pattern", "Recent active", "Content")  # L002

        # Set up:
        # L001: uses=10, velocity=1 -> score = 10 * 0.7 + 1 * 0.3 = 7.3
        # L002: uses=5, velocity=30 -> score = 5 * 0.7 + 30 * 0.3 = 12.5
        # L002 should rank higher despite fewer uses
        manager._set_lesson_uses("L001", 10)
        manager._set_lesson_velocity("L001", 1)
        manager._set_lesson_uses("L002", 5)
        manager._set_lesson_velocity("L002", 30)

        result = manager.inject_context(top_n=2)

        # L002 should be first due to higher weighted score
        assert len(result.top_lessons) == 2
        assert result.top_lessons[0].id == "L002", (
            f"Expected L002 (score=12.5) to rank above L001 (score=7.3), "
            f"but got {result.top_lessons[0].id} first"
        )
        assert result.top_lessons[1].id == "L001"

    def test_inject_zero_velocity_ranks_by_uses(self, manager: "LessonsManager"):
        """When velocity is zero, lessons rank by uses alone."""
        manager.add_lesson("project", "pattern", "High uses", "Content")
        manager.add_lesson("project", "pattern", "Low uses", "Content")

        manager._set_lesson_uses("L001", 20)
        manager._set_lesson_velocity("L001", 0)
        manager._set_lesson_uses("L002", 5)
        manager._set_lesson_velocity("L002", 0)

        result = manager.inject_context(top_n=2)
        assert result.top_lessons[0].id == "L001"
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

    def test_cli_inject_from_different_cwd(
        self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path, monkeypatch
    ):
        """CLI inject should work when run from a different working directory.

        This catches import errors that only manifest when running the CLI
        as a subprocess from a directory other than the repo root.
        """
        from core import LessonsManager

        # Set state dir for manager
        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))

        manager = LessonsManager(temp_lessons_base, temp_project_root)
        manager.add_lesson(
            level="project", category="pattern",
            title="Import Test", content="Testing imports work from different cwd"
        )

        # Get absolute path to cli.py
        cli_path = Path(__file__).parent.parent / "core" / "cli.py"

        # Run from /tmp (different directory than repo root)
        # This is what hooks do - they call python3 /full/path/to/cli.py
        result = subprocess.run(
            ["python3", str(cli_path), "inject", "3"],
            capture_output=True,
            text=True,
            cwd="/tmp",  # KEY: Run from different directory
            env={
                **os.environ,
                "CLAUDE_RECALL_BASE": str(temp_lessons_base),
                "CLAUDE_RECALL_STATE": str(temp_state_dir),
                "PROJECT_DIR": str(temp_project_root),
            },
        )

        assert result.returncode == 0, f"inject failed: {result.stderr}"
        assert "LESSONS" in result.stdout
        assert "Import Test" in result.stdout


# =============================================================================
# Shell Hook Tests
# =============================================================================


class TestCaptureHook:
    """Tests for capture-hook.sh parsing."""

    def test_capture_hook_parses_no_promote(self, temp_lessons_base: Path, temp_project_root: Path, isolated_subprocess_env):
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
                **isolated_subprocess_env,
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

    def test_capture_hook_normal_lesson_is_promotable(self, temp_lessons_base: Path, temp_project_root: Path, isolated_subprocess_env):
        """capture-hook.sh without (no-promote) should create promotable lesson."""

        hook_path = Path("adapters/claude-code/capture-hook.sh")
        if not hook_path.exists():
            pytest.skip("capture-hook.sh not found")

        input_data = json.dumps({
            "prompt": "LESSON: pattern: Normal Test - Normal lesson",
            "cwd": str(temp_project_root),
        })

        # Use isolated environment with whitelist approach
        env = {
            **isolated_subprocess_env,
            "CLAUDE_RECALL_BASE": str(temp_lessons_base),
            "PROJECT_DIR": str(temp_project_root),
        }

        result = subprocess.run(
            ["bash", str(hook_path)],
            input=input_data,
            capture_output=True,
            text=True,
            env=env,
        )

        assert result.returncode == 0

        from core import LessonsManager
        manager = LessonsManager(temp_lessons_base, temp_project_root)
        lesson = manager.get_lesson("L001")
        assert lesson is not None
        assert lesson.promotable is True


class TestHookPathResolution:
    """Tests for hook Python manager path resolution."""

    def test_hook_uses_installed_path_when_available(self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path, monkeypatch, isolated_subprocess_env):
        """Hooks should use $CLAUDE_RECALL_BASE/cli.py when it exists (installed mode)."""
        import shutil
        from core import LessonsManager

        # Copy Python manager and all modules to CLAUDE_RECALL_BASE (simulating installed state)
        core_dir = Path(__file__).parent.parent / "core"
        modules = [
            "cli.py",
            "commands.py",
            "manager.py",
            "debug_logger.py",
            "models.py",
            "parsing.py",
            "file_lock.py",
            "lessons.py",
            "handoffs.py",  # Renamed from approaches.py
            "paths.py",
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
                **isolated_subprocess_env,
                "CLAUDE_RECALL_BASE": str(temp_lessons_base),
                "CLAUDE_RECALL_STATE": str(temp_state_dir),
                "PROJECT_DIR": str(temp_project_root),
            },
        )

        # Hook should succeed and output lesson context
        assert result.returncode == 0
        assert "LESSONS ACTIVE" in result.stdout or "S001" in result.stdout

    def test_hook_falls_back_to_dev_path(self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path, monkeypatch, isolated_subprocess_env):
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
                **isolated_subprocess_env,
                "CLAUDE_RECALL_BASE": str(temp_lessons_base),
                "CLAUDE_RECALL_STATE": str(temp_state_dir),
                "PROJECT_DIR": str(temp_project_root),
            },
        )

        # Hook should succeed using dev path
        assert result.returncode == 0


class TestInjectHookHandoffs:
    """Tests for inject-hook.sh handling of handoffs, especially edge cases."""

    def test_inject_hook_no_crash_on_missing_review_ids(
        self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path, monkeypatch, isolated_subprocess_env
    ):
        """Inject hook should not crash when grep for review IDs finds no matches.

        With pipefail enabled, grep returning no matches (exit 1) could kill
        the script if not handled properly.
        """
        import shutil
        from core import LessonsManager

        # Copy Python modules
        core_dir = Path(__file__).parent.parent / "core"
        modules = [
            "cli.py", "commands.py", "manager.py", "debug_logger.py", "models.py",
            "parsing.py", "file_lock.py", "lessons.py", "handoffs.py",
            "paths.py", "__init__.py", "_version.py",
        ]
        for module in modules:
            src = core_dir / module
            if src.exists():
                shutil.copy(src, temp_lessons_base / module)

        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        manager = LessonsManager(temp_lessons_base, temp_project_root)
        manager.add_lesson(level="project", category="pattern", title="Test", content="Content")

        # Create a handoff that is NOT ready_for_review (should trigger the grep but find nothing)
        handoffs_file = temp_project_root / ".claude-recall" / "HANDOFFS.md"
        handoffs_file.parent.mkdir(parents=True, exist_ok=True)
        handoffs_file.write_text("""# HANDOFFS.md

## Active Handoffs

### [hf-abc123] Test handoff in progress
- **Status**: in_progress | **Phase**: implementing | **Last**: 2026-01-05
- **Tried** (1 step):
  - [success] Working on it
""")

        hook_path = Path(__file__).parent.parent / "adapters" / "claude-code" / "inject-hook.sh"
        if not hook_path.exists():
            pytest.skip("inject-hook.sh not found")

        result = subprocess.run(
            ["bash", str(hook_path)],
            input=json.dumps({"cwd": str(temp_project_root)}),
            capture_output=True,
            text=True,
            cwd="/tmp",
            env={
                **isolated_subprocess_env,
                "CLAUDE_RECALL_BASE": str(temp_lessons_base),
                "CLAUDE_RECALL_STATE": str(temp_state_dir),
                "PROJECT_DIR": str(temp_project_root),
            },
        )

        # Hook should succeed even without any ready_for_review handoffs
        assert result.returncode == 0, f"Hook failed: {result.stderr}"
        assert "LESSONS" in result.stdout


class TestReminderHook:
    """Tests for lesson-reminder-hook.sh config and logging."""

    @pytest.fixture
    def hook_path(self):
        """Get absolute path to reminder hook."""
        path = Path(__file__).parent.parent / "core" / "lesson-reminder-hook.sh"
        if not path.exists():
            pytest.skip("lesson-reminder-hook.sh not found")
        return path

    def test_reminder_reads_config_file(self, temp_lessons_base: Path, temp_project_root: Path, hook_path: Path, isolated_subprocess_env):
        """Reminder hook reads remindEvery from config file."""

        # Use HOME from isolated_subprocess_env
        home = Path(isolated_subprocess_env["HOME"])

        # Create config with custom remindEvery
        config_dir = home / ".claude"
        config_dir.mkdir()
        config_file = config_dir / "settings.json"
        config_file.write_text(json.dumps({
            "claudeRecall": {"enabled": True, "remindEvery": 3}
        }))

        # Create state file at count 2 (next will be 3, triggering reminder)
        # State file goes in CLAUDE_RECALL_BASE (temp_lessons_base)
        (temp_lessons_base / ".reminder-state").write_text("2")

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
                **isolated_subprocess_env,
                "CLAUDE_RECALL_BASE": str(temp_lessons_base),
            },
        )

        assert result.returncode == 0
        assert "LESSON CHECK" in result.stdout
        assert "L001" in result.stdout

    def test_reminder_env_var_overrides_config(self, temp_lessons_base: Path, temp_project_root: Path, tmp_path: Path, hook_path: Path, isolated_subprocess_env):
        """LESSON_REMIND_EVERY env var takes precedence over config."""

        # Use HOME from isolated_subprocess_env
        home = Path(isolated_subprocess_env["HOME"])

        # Config says remind every 100
        config_dir = home / ".claude"
        config_dir.mkdir()
        (config_dir / "settings.json").write_text(json.dumps({
            "claudeRecall": {"remindEvery": 100}
        }))

        # State at count 4, env says remind every 5
        # State file goes in CLAUDE_RECALL_BASE (temp_lessons_base)
        (temp_lessons_base / ".reminder-state").write_text("4")

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
                **isolated_subprocess_env,
                "LESSON_REMIND_EVERY": "5",  # Override config
                "CLAUDE_RECALL_BASE": str(temp_lessons_base),
            },
        )

        assert result.returncode == 0
        assert "LESSON CHECK" in result.stdout  # Triggered because 5 % 5 == 0

    def test_reminder_default_when_no_config(self, temp_lessons_base: Path, temp_project_root: Path, tmp_path: Path, hook_path: Path, isolated_subprocess_env):
        """Default remindEvery=12 when no config file exists."""

        # No config file, state at 11
        # State file goes in CLAUDE_RECALL_BASE (temp_lessons_base)
        (temp_lessons_base / ".reminder-state").write_text("11")

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
                **isolated_subprocess_env,
                "CLAUDE_RECALL_BASE": str(temp_lessons_base),
            },
        )

        assert result.returncode == 0
        assert "LESSON CHECK" in result.stdout  # Count 12, default reminder

    def test_reminder_logs_when_debug_enabled(self, temp_lessons_base: Path, temp_project_root: Path, tmp_path: Path, hook_path: Path, isolated_subprocess_env):
        """Reminder logs to debug.log when CLAUDE_RECALL_DEBUG>=1."""

        # State file goes in CLAUDE_RECALL_BASE (temp_lessons_base)
        (temp_lessons_base / ".reminder-state").write_text("11")

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
                **isolated_subprocess_env,
                "CLAUDE_RECALL_BASE": str(temp_lessons_base),
                "CLAUDE_RECALL_DEBUG": "1",
            },
        )

        assert result.returncode == 0
        assert "LESSON CHECK" in result.stdout

        # Check debug log was created (in CLAUDE_RECALL_BASE)
        debug_log = temp_lessons_base / "debug.log"
        assert debug_log.exists()

        log_content = debug_log.read_text()
        log_entry = json.loads(log_content.strip())
        assert log_entry["event"] == "reminder"
        assert "L001" in log_entry["lesson_ids"]
        assert log_entry["prompt_count"] == 12

    def test_reminder_no_log_when_debug_disabled(self, temp_lessons_base: Path, temp_project_root: Path, hook_path: Path, isolated_subprocess_env):
        """No debug log when CLAUDE_RECALL_DEBUG is not set."""

        # State file goes in CLAUDE_RECALL_BASE (temp_lessons_base)
        (temp_lessons_base / ".reminder-state").write_text("11")

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
                **isolated_subprocess_env,
                "CLAUDE_RECALL_BASE": str(temp_lessons_base),
            },
        )

        assert result.returncode == 0
        assert "LESSON CHECK" in result.stdout

        # Debug log should not exist (in CLAUDE_RECALL_BASE)
        debug_log = temp_lessons_base / "debug.log"
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
# Relevance Caching Tests
# =============================================================================


class TestRelevanceCaching:
    """Tests for the hybrid relevance caching system."""

    def test_normalize_query_lowercase(self):
        """Query normalization should lowercase the input."""
        from core.lessons import _normalize_query

        assert _normalize_query("Hello WORLD") == "hello world"
        assert _normalize_query("HOW do I USE git?") == "do git how i use"

    def test_normalize_query_removes_punctuation(self):
        """Query normalization should remove punctuation."""
        from core.lessons import _normalize_query

        assert _normalize_query("hello, world!") == "hello world"
        assert _normalize_query("what's this? (a test)") == "a s test this what"

    def test_normalize_query_sorts_words(self):
        """Query normalization should sort words alphabetically."""
        from core.lessons import _normalize_query

        assert _normalize_query("zebra apple banana") == "apple banana zebra"
        assert _normalize_query("git commit push") == "commit git push"

    def test_normalize_query_handles_empty(self):
        """Query normalization should handle empty strings."""
        from core.lessons import _normalize_query

        assert _normalize_query("") == ""
        assert _normalize_query("   ") == ""
        assert _normalize_query("...") == ""

    def test_query_hash_deterministic(self):
        """Same query should produce same hash."""
        from core.lessons import _query_hash

        hash1 = _query_hash("hello world")
        hash2 = _query_hash("hello world")
        assert hash1 == hash2

    def test_query_hash_normalized(self):
        """Differently formatted but equivalent queries should have same hash."""
        from core.lessons import _query_hash

        hash1 = _query_hash("Hello World!")
        hash2 = _query_hash("hello, world")
        hash3 = _query_hash("WORLD HELLO")
        assert hash1 == hash2 == hash3

    def test_jaccard_similarity_identical(self):
        """Identical queries should have similarity of 1.0."""
        from core.lessons import _jaccard_similarity

        assert _jaccard_similarity("apple banana cherry", "apple banana cherry") == 1.0

    def test_jaccard_similarity_disjoint(self):
        """Completely different queries should have similarity of 0.0."""
        from core.lessons import _jaccard_similarity

        assert _jaccard_similarity("apple banana cherry", "dog cat mouse") == 0.0

    def test_jaccard_similarity_partial(self):
        """Partially overlapping queries should have appropriate similarity."""
        from core.lessons import _jaccard_similarity

        # 2 common words out of 4 unique: 2/4 = 0.5
        sim = _jaccard_similarity("apple banana cherry", "apple banana dog")
        assert 0.4 < sim < 0.6

    def test_jaccard_similarity_empty(self):
        """Empty queries should be handled correctly."""
        from core.lessons import _jaccard_similarity

        assert _jaccard_similarity("", "") == 1.0
        assert _jaccard_similarity("apple", "") == 0.0
        assert _jaccard_similarity("", "banana") == 0.0

    def test_cache_hit_exact_match(self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path, monkeypatch):
        """Cache hit on exact query match should not call Haiku."""
        from core import LessonsManager
        from core.lessons import _save_relevance_cache, _query_hash
        import time

        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        manager = LessonsManager(temp_lessons_base, temp_project_root)
        manager.add_lesson("project", "pattern", "Git Safety", "Never force push")

        # Pre-populate cache
        query = "How do I use git?"
        cache = {
            "entries": {
                _query_hash(query): {
                    "normalized_query": "do git how i use",
                    "scores": {"L001": 8},
                    "timestamp": time.time(),
                }
            }
        }
        _save_relevance_cache(cache)

        # Track if subprocess.run is called
        haiku_called = []

        def mock_run(*args, **kwargs):
            haiku_called.append(True)
            class MockResult:
                returncode = 0
                stdout = "L001: 5\n"  # Different score to verify cache is used
                stderr = ""
            return MockResult()

        monkeypatch.setattr(subprocess, "run", mock_run)

        result = manager.score_relevance(query)

        assert len(haiku_called) == 0, "Haiku should not be called on cache hit"
        assert len(result.scored_lessons) == 1
        assert result.scored_lessons[0].score == 8  # From cache, not mock

    def test_cache_miss_calls_haiku(self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path, monkeypatch):
        """Cache miss should call Haiku and cache the result."""
        from core import LessonsManager
        from core.lessons import _load_relevance_cache

        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        manager = LessonsManager(temp_lessons_base, temp_project_root)
        manager.add_lesson("project", "pattern", "Test Lesson", "Test content")

        # Track if subprocess.run is called
        haiku_called = []

        def mock_run(*args, **kwargs):
            haiku_called.append(True)
            class MockResult:
                returncode = 0
                stdout = "L001: 7\n"
                stderr = ""
            return MockResult()

        monkeypatch.setattr(subprocess, "run", mock_run)

        result = manager.score_relevance("new unique query")

        assert len(haiku_called) == 1, "Haiku should be called on cache miss"
        assert result.scored_lessons[0].score == 7

        # Verify result was cached
        cache = _load_relevance_cache()
        assert len(cache.get("entries", {})) == 1

    def test_cache_ttl_expiration(self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path, monkeypatch):
        """Expired cache entries should trigger Haiku call."""
        from core import LessonsManager
        from core.lessons import _save_relevance_cache, _query_hash, RELEVANCE_CACHE_TTL_DAYS
        import time

        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        manager = LessonsManager(temp_lessons_base, temp_project_root)
        manager.add_lesson("project", "pattern", "Test", "Content")

        # Pre-populate cache with expired entry
        query = "test query"
        expired_time = time.time() - (RELEVANCE_CACHE_TTL_DAYS + 1) * 24 * 60 * 60
        cache = {
            "entries": {
                _query_hash(query): {
                    "normalized_query": "query test",
                    "scores": {"L001": 9},
                    "timestamp": expired_time,
                }
            }
        }
        _save_relevance_cache(cache)

        haiku_called = []

        def mock_run(*args, **kwargs):
            haiku_called.append(True)
            class MockResult:
                returncode = 0
                stdout = "L001: 3\n"
                stderr = ""
            return MockResult()

        monkeypatch.setattr(subprocess, "run", mock_run)

        result = manager.score_relevance(query)

        assert len(haiku_called) == 1, "Haiku should be called for expired cache"
        assert result.scored_lessons[0].score == 3  # From Haiku, not old cache

    def test_cache_similarity_match(self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path, monkeypatch):
        """Similar query should hit cache via Jaccard similarity."""
        from core import LessonsManager
        from core.lessons import _save_relevance_cache, _query_hash
        import time

        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        manager = LessonsManager(temp_lessons_base, temp_project_root)
        manager.add_lesson("project", "pattern", "Git Lesson", "Content")

        # Cache a query
        original_query = "how do I use git branches"
        cache = {
            "entries": {
                _query_hash(original_query): {
                    "normalized_query": "branches do git how i use",
                    "scores": {"L001": 8},
                    "timestamp": time.time(),
                }
            }
        }
        _save_relevance_cache(cache)

        haiku_called = []

        def mock_run(*args, **kwargs):
            haiku_called.append(True)
            class MockResult:
                returncode = 0
                stdout = "L001: 2\n"
                stderr = ""
            return MockResult()

        monkeypatch.setattr(subprocess, "run", mock_run)

        # Similar query - same words with minor variation
        similar_query = "how do I use git branch"
        result = manager.score_relevance(similar_query)

        # Should hit cache due to high Jaccard similarity
        assert len(haiku_called) == 0, "Similar query should hit cache"
        assert result.scored_lessons[0].score == 8

    def test_cache_similarity_below_threshold(self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path, monkeypatch):
        """Dissimilar query should miss cache despite having some overlap."""
        from core import LessonsManager
        from core.lessons import _save_relevance_cache, _query_hash
        import time

        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        manager = LessonsManager(temp_lessons_base, temp_project_root)
        manager.add_lesson("project", "pattern", "Test", "Content")

        # Cache a query
        original_query = "git branch merge"
        cache = {
            "entries": {
                _query_hash(original_query): {
                    "normalized_query": "branch git merge",
                    "scores": {"L001": 9},
                    "timestamp": time.time(),
                }
            }
        }
        _save_relevance_cache(cache)

        haiku_called = []

        def mock_run(*args, **kwargs):
            haiku_called.append(True)
            class MockResult:
                returncode = 0
                stdout = "L001: 4\n"
                stderr = ""
            return MockResult()

        monkeypatch.setattr(subprocess, "run", mock_run)

        # Very different query - should not hit cache
        different_query = "python async await coroutines"
        result = manager.score_relevance(different_query)

        assert len(haiku_called) == 1, "Different query should miss cache"
        assert result.scored_lessons[0].score == 4

    def test_cache_handles_deleted_lessons(self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path, monkeypatch):
        """Cache should gracefully handle references to deleted lessons."""
        from core import LessonsManager
        from core.lessons import _save_relevance_cache, _query_hash
        import time

        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        manager = LessonsManager(temp_lessons_base, temp_project_root)
        manager.add_lesson("project", "pattern", "Test", "Content")

        # Cache has scores for lessons that no longer exist
        query = "test query"
        cache = {
            "entries": {
                _query_hash(query): {
                    "normalized_query": "query test",
                    "scores": {"L001": 8, "L002": 5, "L003": 3},  # L002, L003 don't exist
                    "timestamp": time.time(),
                }
            }
        }
        _save_relevance_cache(cache)

        result = manager.score_relevance(query)

        # Should only return L001 which exists
        assert len(result.scored_lessons) == 1
        assert result.scored_lessons[0].lesson.id == "L001"
        assert result.scored_lessons[0].score == 8

    def test_cache_handles_corrupted_file(
        self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path
    ):
        """Corrupted cache file should be handled gracefully."""
        # Create corrupted cache file
        cache_path = temp_state_dir / "relevance-cache.json"
        cache_path.write_text("{ invalid json here")

        # Import and call the load function
        from core.lessons import _load_relevance_cache
        cache = _load_relevance_cache()

        # Should return empty cache structure
        assert cache == {"entries": {}}


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

    def test_remaining_lessons_show_title_only(self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path, monkeypatch):
        """Remaining lessons (not in top_n) show only title, not content."""
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

        # Remaining lessons only show title, not content (for compactness)
        assert "[L006]" in output  # ID is shown
        assert "Critical Rule" in output  # Title is shown
        assert "dangerous thing" not in output  # Content is NOT shown

    def test_remaining_lessons_capped_at_10(self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path, monkeypatch):
        """Remaining lessons (not in top_n) should be capped at 10 displayed."""
        from core import LessonsManager

        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        manager = LessonsManager(temp_lessons_base, temp_project_root)

        # Add 20 lessons with distinct titles to avoid duplicate detection
        # Using letters to make titles sufficiently different
        alphabet = "ABCDEFGHIJKLMNOPQRST"
        for i in range(20):
            manager.add_lesson("project", "pattern", f"{alphabet[i]} Unique Lesson Title", f"Content for lesson {i}")

        # Cite the first 3 lessons to ensure they're in top_n
        for lesson_id in ["L001", "L002", "L003"]:
            for _ in range(3):
                manager.cite_lesson(lesson_id)

        result = manager.inject(3)  # top 3 by uses
        output = result.format()

        # Count how many remaining lesson IDs appear (L004-L020 are remaining)
        remaining_count = sum(1 for i in range(4, 21) if f"[L{i:03d}]" in output)

        # Should show only 10 remaining lessons, not all 17
        assert remaining_count == 10, f"Expected 10 remaining lessons shown, got {remaining_count}"

        # Verify "+7 more" message appears (17 remaining - 10 shown = 7 more)
        assert "+7 more" in output, "Should show '+7 more' message for remaining lessons beyond cap"

    def test_remaining_lessons_show_read_instruction(self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path, monkeypatch):
        """Remaining lessons section should show emphatic READ instruction."""
        from core import LessonsManager

        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        manager = LessonsManager(temp_lessons_base, temp_project_root)

        # Add 10 lessons (more than top_n so we have remaining)
        for i in range(10):
            manager.add_lesson("project", "pattern", f"Lesson {i}", f"Content {i}")

        # Cite the first 3 lessons to ensure they're in top_n
        for lesson_id in ["L001", "L002", "L003"]:
            for _ in range(3):
                manager.cite_lesson(lesson_id)

        result = manager.inject(3)  # top 3 by uses
        output = result.format()

        # Should show the show command instruction
        assert "`show L###` when relevant" in output


class TestSessionStartLogging:
    """Regression tests for session_start logging.

    These tests ensure that session_start is always logged during inject_context(),
    even when no lessons exist. This was a bug where early return skipped logging.
    """

    def test_inject_context_logs_session_start_even_when_empty(
        self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path, monkeypatch
    ):
        """Ensure session_start is logged even when no lessons exist."""
        from core import LessonsManager

        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        monkeypatch.setenv("CLAUDE_RECALL_DEBUG", "1")

        # Reset logger to pick up new env
        from core.debug_logger import reset_logger
        reset_logger()

        manager = LessonsManager(temp_lessons_base, temp_project_root)

        # Don't add any lessons - should still log session_start
        result = manager.inject_context(top_n=5)

        # Verify empty result
        assert result.total_count == 0

        # Verify session_start was logged
        log_file = temp_state_dir / "debug.log"
        assert log_file.exists(), "Debug log file should be created"
        logs = log_file.read_text()
        assert '"event": "session_start"' in logs, "session_start event should be logged"
        assert '"total_lessons": 0' in logs, "total_lessons should be 0"

    def test_inject_context_logs_session_start_with_lessons(
        self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path, monkeypatch
    ):
        """Ensure session_start is logged when lessons exist."""
        from core import LessonsManager

        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        monkeypatch.setenv("CLAUDE_RECALL_DEBUG", "1")

        # Reset logger to pick up new env
        from core.debug_logger import reset_logger
        reset_logger()

        manager = LessonsManager(temp_lessons_base, temp_project_root)
        manager.add_lesson(level="project", category="test", title="Test", content="Content")

        result = manager.inject_context(top_n=5)

        assert result.total_count == 1

        log_file = temp_state_dir / "debug.log"
        assert log_file.exists(), "Debug log file should be created"
        logs = log_file.read_text()
        assert '"event": "session_start"' in logs, "session_start event should be logged"
        assert '"total_lessons": 1' in logs, "total_lessons should be 1"


class TestInjectErrorLogging:
    """Tests for inject_error logging functionality."""

    def test_inject_error_logs_to_debug_file(
        self, temp_state_dir: Path, monkeypatch
    ):
        """Ensure inject_error writes to debug log."""
        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        monkeypatch.setenv("CLAUDE_RECALL_DEBUG", "1")

        from core.debug_logger import get_logger, reset_logger
        reset_logger()

        logger = get_logger()
        logger.inject_error("test_event", "Test error message")

        log_file = temp_state_dir / "debug.log"
        assert log_file.exists(), "Debug log file should be created"
        logs = log_file.read_text()
        assert '"event": "inject_error"' in logs
        assert '"error_event": "test_event"' in logs
        assert "Test error message" in logs

    def test_inject_error_truncates_long_messages(
        self, temp_state_dir: Path, monkeypatch
    ):
        """Ensure inject_error truncates messages over 500 chars."""
        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        monkeypatch.setenv("CLAUDE_RECALL_DEBUG", "1")

        from core.debug_logger import get_logger, reset_logger
        reset_logger()

        logger = get_logger()
        long_message = "X" * 1000  # 1000 chars
        logger.inject_error("truncation_test", long_message)

        log_file = temp_state_dir / "debug.log"
        logs = log_file.read_text()

        # The message should be truncated to 500 chars
        assert logs.count("X") == 500


# =============================================================================
# Level/ID Parser Helpers
# =============================================================================


class TestLevelIdHelpers:
    """Tests for _get_level_from_id and _get_file_path_for_id helper methods."""

    def test_get_level_from_id_system_s001(self, manager: "LessonsManager"):
        """S001 should return 'system' level."""
        assert manager._get_level_from_id("S001") == "system"

    def test_get_level_from_id_system_s999(self, manager: "LessonsManager"):
        """S999 should return 'system' level."""
        assert manager._get_level_from_id("S999") == "system"

    def test_get_level_from_id_project_l001(self, manager: "LessonsManager"):
        """L001 should return 'project' level."""
        assert manager._get_level_from_id("L001") == "project"

    def test_get_level_from_id_project_l999(self, manager: "LessonsManager"):
        """L999 should return 'project' level."""
        assert manager._get_level_from_id("L999") == "project"

    def test_get_file_path_for_id_system(self, manager: "LessonsManager"):
        """S### should return system_lessons_file path."""
        result = manager._get_file_path_for_id("S001")
        assert result == manager.system_lessons_file

    def test_get_file_path_for_id_project(self, manager: "LessonsManager"):
        """L### should return project_lessons_file path."""
        result = manager._get_file_path_for_id("L001")
        assert result == manager.project_lessons_file

    def test_get_file_path_for_id_system_high_number(self, manager: "LessonsManager"):
        """S999 should return system_lessons_file path."""
        result = manager._get_file_path_for_id("S999")
        assert result == manager.system_lessons_file

    def test_get_file_path_for_id_project_high_number(self, manager: "LessonsManager"):
        """L999 should return project_lessons_file path."""
        result = manager._get_file_path_for_id("L999")
        assert result == manager.project_lessons_file


# =============================================================================
# Atomic Update Pattern
# =============================================================================


class TestAtomicUpdatePattern:
    """Tests for the _atomic_update_lessons_file helper method."""

    def test_atomic_update_lessons_modifies_file(self, manager: "LessonsManager"):
        """Given a lesson file, when atomic update modifies it, changes are persisted."""
        # Setup: Create a lesson to modify
        manager.add_lesson(
            level="project",
            category="pattern",
            title="Original title",
            content="Original content",
        )

        # Define an update function that modifies the first lesson's content
        def update_fn(lessons):
            lessons[0].content = "Modified content"

        # Execute the atomic update
        manager._atomic_update_lessons_file(
            manager.project_lessons_file,
            update_fn,
            level="project"
        )

        # Verify: Re-read the lesson and check the content was modified
        lesson = manager.get_lesson("L001")
        assert lesson is not None
        assert lesson.content == "Modified content"

    def test_atomic_update_lessons_uses_file_lock(self, manager: "LessonsManager"):
        """Verify file locking is used during atomic update."""
        from unittest.mock import patch, MagicMock

        # Setup: Create a lesson file
        manager.add_lesson(
            level="project",
            category="pattern",
            title="Test",
            content="Content",
        )

        # Track whether FileLock was called
        lock_called = False
        original_file_lock = None

        # Import FileLock to patch it
        try:
            from core.file_lock import FileLock
            original_file_lock = FileLock
        except ImportError:
            from file_lock import FileLock
            original_file_lock = FileLock

        class MockFileLock:
            def __init__(self, path):
                nonlocal lock_called
                lock_called = True
                self.path = path

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        # Patch FileLock and execute update
        with patch("core.lessons.FileLock", MockFileLock):
            def noop_update(lessons):
                pass

            manager._atomic_update_lessons_file(
                manager.project_lessons_file,
                noop_update,
                level="project"
            )

        assert lock_called, "FileLock should be used during atomic update"

    def test_atomic_update_handles_empty_file(self, manager: "LessonsManager"):
        """Empty file should not crash and update_fn receives empty list."""
        # Setup: Initialize an empty lessons file (just header, no lessons)
        manager.init_lessons_file("project")

        received_lessons = []

        def capture_update(lessons):
            nonlocal received_lessons
            received_lessons = list(lessons)

        # Should not raise an exception
        manager._atomic_update_lessons_file(
            manager.project_lessons_file,
            capture_update,
            level="project"
        )

        # Should receive an empty list
        assert received_lessons == []

    def test_atomic_update_modifies_list_in_place(self, manager: "LessonsManager"):
        """The update_fn should be able to modify the lessons list in-place."""
        # Setup: Create two lessons
        manager.add_lesson(level="project", category="pattern", title="Keep", content="Keep this")
        manager.add_lesson(level="project", category="pattern", title="Remove", content="Delete this")

        def remove_second(lessons):
            # Remove the second lesson in-place
            del lessons[1]

        manager._atomic_update_lessons_file(
            manager.project_lessons_file,
            remove_second,
            level="project"
        )

        # Verify only one lesson remains
        lessons = manager.list_lessons(scope="project")
        assert len(lessons) == 1
        assert lessons[0].title == "Keep"

    def test_atomic_update_appends_new_lesson(self, manager: "LessonsManager"):
        """The update_fn should be able to append new lessons."""
        from datetime import date

        try:
            from core.models import Lesson
        except ImportError:
            from models import Lesson

        manager.add_lesson(level="project", category="pattern", title="Existing", content="Existing content")

        def append_lesson(lessons):
            new_lesson = Lesson(
                id="L002",
                title="New lesson",
                content="New content",
                uses=1,
                velocity=0,
                learned=date.today(),
                last_used=date.today(),
                category="gotcha",
                source="human",
                level="project",
            )
            lessons.append(new_lesson)

        manager._atomic_update_lessons_file(
            manager.project_lessons_file,
            append_lesson,
            level="project"
        )

        # Verify both lessons exist
        lessons = manager.list_lessons(scope="project")
        assert len(lessons) == 2
        assert lessons[0].title == "Existing"
        assert lessons[1].title == "New lesson"


# =============================================================================
# Effectiveness Tracking Tests
# =============================================================================


class TestEffectivenessTracking:
    """Tests for lesson effectiveness tracking."""

    def test_track_effectiveness_creates_entry(self, manager: "LessonsManager"):
        """track_effectiveness should create entry for new lesson."""
        manager.add_lesson("project", "pattern", "Test", "Content")

        # Track effectiveness manually
        manager.track_effectiveness("L001", successful=True)

        data = manager.get_effectiveness_data("L001")
        assert data is not None
        assert data["effective_citations"] == 1
        assert data["total_citations_tracked"] == 1
        assert data["effectiveness_rate"] == 1.0

    def test_track_effectiveness_increments(self, manager: "LessonsManager"):
        """track_effectiveness should increment counts correctly."""
        manager.add_lesson("project", "pattern", "Test", "Content")

        # Track multiple times
        manager.track_effectiveness("L001", successful=True)
        manager.track_effectiveness("L001", successful=True)
        manager.track_effectiveness("L001", successful=False)

        data = manager.get_effectiveness_data("L001")
        assert data["effective_citations"] == 2
        assert data["total_citations_tracked"] == 3
        assert abs(data["effectiveness_rate"] - 0.6667) < 0.01

    def test_get_effectiveness_returns_none_for_unknown(self, manager: "LessonsManager"):
        """get_effectiveness should return None for lessons with no data."""
        manager.add_lesson("project", "pattern", "Test", "Content")

        # Don't track any effectiveness
        rate = manager.get_effectiveness("L999")
        assert rate is None

    def test_get_effectiveness_returns_rate(self, manager: "LessonsManager"):
        """get_effectiveness should return the effectiveness rate."""
        manager.add_lesson("project", "pattern", "Test", "Content")

        manager.track_effectiveness("L001", successful=True)
        manager.track_effectiveness("L001", successful=True)
        manager.track_effectiveness("L001", successful=False)
        manager.track_effectiveness("L001", successful=False)

        rate = manager.get_effectiveness("L001")
        assert rate == 0.5

    def test_cite_lesson_tracks_effectiveness(self, manager: "LessonsManager"):
        """cite_lesson should automatically track effectiveness."""
        manager.add_lesson("project", "pattern", "Test", "Content")

        # Citation should track effectiveness
        manager.cite_lesson("L001")

        data = manager.get_effectiveness_data("L001")
        assert data is not None
        assert data["effective_citations"] == 1
        assert data["total_citations_tracked"] == 1

    def test_cite_lesson_multiple_tracks_multiple(self, manager: "LessonsManager"):
        """Multiple citations should accumulate effectiveness tracking."""
        manager.add_lesson("project", "pattern", "Test", "Content")

        for _ in range(5):
            manager.cite_lesson("L001")

        data = manager.get_effectiveness_data("L001")
        assert data["effective_citations"] == 5
        assert data["total_citations_tracked"] == 5
        assert data["effectiveness_rate"] == 1.0

    def test_mark_citation_ineffective(self, manager: "LessonsManager"):
        """mark_citation_ineffective should decrement effective count."""
        manager.add_lesson("project", "pattern", "Test", "Content")

        # Cite (tracks as effective)
        manager.cite_lesson("L001")
        manager.cite_lesson("L001")

        # Mark last one as ineffective
        manager.mark_citation_ineffective("L001")

        data = manager.get_effectiveness_data("L001")
        assert data["effective_citations"] == 1
        assert data["total_citations_tracked"] == 2
        assert data["effectiveness_rate"] == 0.5

    def test_mark_citation_ineffective_no_negative(self, manager: "LessonsManager"):
        """mark_citation_ineffective should not go below 0."""
        manager.add_lesson("project", "pattern", "Test", "Content")

        manager.track_effectiveness("L001", successful=False)

        # Try to decrement already-zero effective count
        manager.mark_citation_ineffective("L001")

        data = manager.get_effectiveness_data("L001")
        assert data["effective_citations"] == 0

    def test_mark_citation_ineffective_unknown_lesson(self, manager: "LessonsManager"):
        """mark_citation_ineffective should handle unknown lessons gracefully."""
        # Should not raise
        manager.mark_citation_ineffective("L999")

    def test_get_low_effectiveness_lessons(self, manager: "LessonsManager"):
        """get_low_effectiveness_lessons should return lessons below threshold."""
        manager.add_lesson("project", "pattern", "Good lesson", "Content")
        manager.add_lesson("project", "pattern", "Bad lesson", "Content")
        manager.add_lesson("project", "pattern", "Okay lesson", "Content")

        # Make L001 highly effective
        for _ in range(5):
            manager.track_effectiveness("L001", successful=True)

        # Make L002 low effectiveness
        for _ in range(5):
            manager.track_effectiveness("L002", successful=False)

        # Make L003 okay effectiveness
        for i in range(5):
            manager.track_effectiveness("L003", successful=(i < 4))

        low_eff = manager.get_low_effectiveness_lessons(threshold=0.6, min_citations=3)

        # Should return L002 (0% effective) and L003 (80% is above 60%, so not included)
        # Wait, L003 is 80% which is >= 60%, so only L002
        assert len(low_eff) == 1
        assert low_eff[0][0] == "L002"
        assert low_eff[0][1] == 0.0
        assert low_eff[0][2] == 5

    def test_get_low_effectiveness_min_citations(self, manager: "LessonsManager"):
        """get_low_effectiveness_lessons should respect min_citations."""
        manager.add_lesson("project", "pattern", "Test", "Content")

        # Only 2 citations, but 0% effective
        manager.track_effectiveness("L001", successful=False)
        manager.track_effectiveness("L001", successful=False)

        # Should not return because min_citations=3 by default
        low_eff = manager.get_low_effectiveness_lessons(threshold=0.6, min_citations=3)
        assert len(low_eff) == 0

        # With lower threshold
        low_eff = manager.get_low_effectiveness_lessons(threshold=0.6, min_citations=2)
        assert len(low_eff) == 1

    def test_get_low_effectiveness_sorted(self, manager: "LessonsManager"):
        """get_low_effectiveness_lessons should be sorted by rate ascending."""
        manager.add_lesson("project", "pattern", "Worst", "Content")
        manager.add_lesson("project", "pattern", "Bad", "Content")
        manager.add_lesson("project", "pattern", "Okay", "Content")

        # L001: 10% effective
        for i in range(10):
            manager.track_effectiveness("L001", successful=(i == 0))

        # L002: 30% effective
        for i in range(10):
            manager.track_effectiveness("L002", successful=(i < 3))

        # L003: 50% effective (still below 60% threshold)
        for i in range(10):
            manager.track_effectiveness("L003", successful=(i < 5))

        low_eff = manager.get_low_effectiveness_lessons(threshold=0.6, min_citations=3)

        assert len(low_eff) == 3
        # Should be sorted: L001 (10%), L002 (30%), L003 (50%)
        assert low_eff[0][0] == "L001"
        assert low_eff[1][0] == "L002"
        assert low_eff[2][0] == "L003"

    def test_effectiveness_persists_across_instances(
        self, temp_lessons_base: Path, temp_project_root: Path
    ):
        """Effectiveness data should persist across manager instances."""
        from core import LessonsManager

        manager1 = LessonsManager(temp_lessons_base, temp_project_root)
        manager1.add_lesson("project", "pattern", "Test", "Content")
        manager1.cite_lesson("L001")
        manager1.cite_lesson("L001")
        manager1.mark_citation_ineffective("L001")

        # Create new manager instance
        manager2 = LessonsManager(temp_lessons_base, temp_project_root)

        data = manager2.get_effectiveness_data("L001")
        assert data is not None
        assert data["effective_citations"] == 1
        assert data["total_citations_tracked"] == 2

    def test_effectiveness_system_lessons(self, manager: "LessonsManager"):
        """Effectiveness should work for system lessons too."""
        manager.add_lesson("system", "pattern", "System Test", "Content")

        manager.cite_lesson("S001")
        manager.track_effectiveness("S001", successful=False)

        data = manager.get_effectiveness_data("S001")
        # cite_lesson adds 1 effective, track_effectiveness adds 1 total (ineffective)
        assert data["effective_citations"] == 1
        assert data["total_citations_tracked"] == 2
        assert data["effectiveness_rate"] == 0.5


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


# =============================================================================
# Pre-scoring Cache Warmup Tests
# =============================================================================


class TestPrescoreCache:
    """Tests for background cache warmup functionality."""

    def test_prescore_extracts_user_messages(
        self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path, monkeypatch
    ):
        """prescore_cache should extract user messages from transcript."""
        from core import LessonsManager

        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        manager = LessonsManager(temp_lessons_base, temp_project_root)
        manager.add_lesson(level="project", category="pattern", title="Git Lesson", content="How to use git")

        # Create a mock transcript with user messages
        transcript_path = temp_state_dir / "test-session.jsonl"
        transcript_entries = [
            {"type": "user", "message": {"role": "user", "content": "How do I use git branches?"}},
            {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "Here's how..."}]}},
            {"type": "user", "message": {"role": "user", "content": "What about rebasing?"}},
        ]
        with open(transcript_path, "w") as f:
            for entry in transcript_entries:
                f.write(json.dumps(entry) + "\n")

        # Track Haiku calls
        haiku_calls = []

        def mock_run(*args, **kwargs):
            haiku_calls.append(args)
            return make_mock_result(stdout="L001: 8\n")

        monkeypatch.setattr(subprocess, "run", mock_run)

        result = manager.prescore_cache(str(transcript_path), max_queries=2)

        # Should have called Haiku for each non-cached query
        assert len(haiku_calls) == 2
        assert len(result) == 2

    def test_prescore_skips_meta_messages(
        self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path, monkeypatch
    ):
        """prescore_cache should skip messages starting with '<' (meta/command output)."""
        from core import LessonsManager

        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        manager = LessonsManager(temp_lessons_base, temp_project_root)
        manager.add_lesson(level="project", category="pattern", title="Test", content="Content")

        # Create transcript with meta messages
        transcript_path = temp_state_dir / "test-session.jsonl"
        transcript_entries = [
            {"type": "user", "message": {"role": "user", "content": "<local-command-stdout>output</local-command-stdout>"}},
            {"type": "user", "message": {"role": "user", "content": "Real user question about testing"}},
            {"type": "user", "message": {"role": "user", "content": "<command-name>/clear</command-name>"}},
        ]
        with open(transcript_path, "w") as f:
            for entry in transcript_entries:
                f.write(json.dumps(entry) + "\n")

        haiku_calls = []

        def mock_run(*args, **kwargs):
            haiku_calls.append(args)
            return make_mock_result(stdout="L001: 7\n")

        monkeypatch.setattr(subprocess, "run", mock_run)

        result = manager.prescore_cache(str(transcript_path), max_queries=3)

        # Should only score the real user message
        assert len(haiku_calls) == 1
        assert len(result) == 1

    def test_prescore_skips_short_queries(
        self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path, monkeypatch
    ):
        """prescore_cache should skip queries shorter than 10 characters."""
        from core import LessonsManager

        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        manager = LessonsManager(temp_lessons_base, temp_project_root)
        manager.add_lesson(level="project", category="pattern", title="Test", content="Content")

        # Create transcript with short messages
        transcript_path = temp_state_dir / "test-session.jsonl"
        transcript_entries = [
            {"type": "user", "message": {"role": "user", "content": "yes"}},
            {"type": "user", "message": {"role": "user", "content": "no way"}},
            {"type": "user", "message": {"role": "user", "content": "This is a longer meaningful query about coding"}},
        ]
        with open(transcript_path, "w") as f:
            for entry in transcript_entries:
                f.write(json.dumps(entry) + "\n")

        haiku_calls = []

        def mock_run(*args, **kwargs):
            haiku_calls.append(args)
            return make_mock_result(stdout="L001: 6\n")

        monkeypatch.setattr(subprocess, "run", mock_run)

        result = manager.prescore_cache(str(transcript_path), max_queries=3)

        # Should only score the longer message
        assert len(haiku_calls) == 1
        assert len(result) == 1

    def test_prescore_skips_already_cached(
        self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path, monkeypatch
    ):
        """prescore_cache should skip queries already in cache."""
        from core import LessonsManager
        from core.lessons import _save_relevance_cache, _query_hash
        import time

        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        manager = LessonsManager(temp_lessons_base, temp_project_root)
        manager.add_lesson(level="project", category="pattern", title="Test", content="Content")

        # Pre-populate cache with existing query
        existing_query = "How do I use git branches?"
        cache = {
            "entries": {
                _query_hash(existing_query): {
                    "normalized_query": "branches do git how i use",
                    "scores": {"L001": 9},
                    "timestamp": time.time(),
                }
            }
        }
        _save_relevance_cache(cache)

        # Create transcript with the cached query
        transcript_path = temp_state_dir / "test-session.jsonl"
        transcript_entries = [
            {"type": "user", "message": {"role": "user", "content": existing_query}},
            {"type": "user", "message": {"role": "user", "content": "What about rebasing branches?"}},
        ]
        with open(transcript_path, "w") as f:
            for entry in transcript_entries:
                f.write(json.dumps(entry) + "\n")

        haiku_calls = []

        def mock_run(*args, **kwargs):
            haiku_calls.append(args)
            return make_mock_result(stdout="L001: 5\n")

        monkeypatch.setattr(subprocess, "run", mock_run)

        result = manager.prescore_cache(str(transcript_path), max_queries=2)

        # Should only call Haiku for the new query
        assert len(haiku_calls) == 1
        assert len(result) == 1

    def test_prescore_respects_max_queries(
        self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path, monkeypatch
    ):
        """prescore_cache should respect max_queries limit."""
        from core import LessonsManager

        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        manager = LessonsManager(temp_lessons_base, temp_project_root)
        manager.add_lesson(level="project", category="pattern", title="Test", content="Content")

        # Create transcript with many user messages
        transcript_path = temp_state_dir / "test-session.jsonl"
        transcript_entries = [
            {"type": "user", "message": {"role": "user", "content": f"Question number {i} about something"}}
            for i in range(10)
        ]
        with open(transcript_path, "w") as f:
            for entry in transcript_entries:
                f.write(json.dumps(entry) + "\n")

        haiku_calls = []

        def mock_run(*args, **kwargs):
            haiku_calls.append(args)
            return make_mock_result(stdout="L001: 4\n")

        monkeypatch.setattr(subprocess, "run", mock_run)

        result = manager.prescore_cache(str(transcript_path), max_queries=3)

        # Should only score first 3 queries
        assert len(haiku_calls) == 3
        assert len(result) == 3

    def test_prescore_handles_missing_transcript(
        self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path, monkeypatch
    ):
        """prescore_cache should handle missing transcript file gracefully."""
        from core import LessonsManager

        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        manager = LessonsManager(temp_lessons_base, temp_project_root)

        result = manager.prescore_cache("/nonexistent/transcript.jsonl")

        assert result == []

    def test_prescore_handles_empty_transcript(
        self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path, monkeypatch
    ):
        """prescore_cache should handle empty transcript gracefully."""
        from core import LessonsManager

        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        manager = LessonsManager(temp_lessons_base, temp_project_root)

        transcript_path = temp_state_dir / "empty.jsonl"
        transcript_path.write_text("")

        result = manager.prescore_cache(str(transcript_path))

        assert result == []

    def test_prescore_handles_malformed_json(
        self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path, monkeypatch
    ):
        """prescore_cache should skip malformed JSON lines."""
        from core import LessonsManager

        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        manager = LessonsManager(temp_lessons_base, temp_project_root)
        manager.add_lesson(level="project", category="pattern", title="Test", content="Content")

        transcript_path = temp_state_dir / "malformed.jsonl"
        with open(transcript_path, "w") as f:
            f.write("{ invalid json }\n")
            f.write(json.dumps({"type": "user", "message": {"role": "user", "content": "Valid query about testing"}}) + "\n")

        haiku_calls = []

        def mock_run(*args, **kwargs):
            haiku_calls.append(args)
            return make_mock_result(stdout="L001: 7\n")

        monkeypatch.setattr(subprocess, "run", mock_run)

        result = manager.prescore_cache(str(transcript_path))

        # Should have processed the valid entry
        assert len(haiku_calls) == 1
        assert len(result) == 1


# =============================================================================
# Triggers Field Tests (TDD - tests written before implementation)
# =============================================================================


class TestTriggersField:
    """Tests for the new triggers field in the Lesson system.

    The triggers field allows lessons to specify keywords that help match
    relevant lessons to the current context. For example, a lesson about
    mutex usage in destructors might have triggers=["destructor", "mutex", "shutdown"].
    """

    def test_lesson_dataclass_accepts_triggers(self, manager: "LessonsManager"):
        """Lesson dataclass should accept a triggers field with a list of keywords.

        The triggers field stores keywords that help identify when this lesson
        is relevant to the current context or query.
        """
        lesson_id = manager.add_lesson(
            level="project",
            category="gotcha",
            title="No mutex in destructors",
            content="Avoid mutex locks in destructors to prevent deadlocks during shutdown.",
            triggers=["destructor", "mutex", "shutdown"],
        )

        lesson = manager.get_lesson(lesson_id)
        assert lesson is not None
        assert hasattr(lesson, "triggers"), "Lesson should have a triggers field"
        assert lesson.triggers == ["destructor", "mutex", "shutdown"]

    def test_parse_lesson_extracts_triggers_from_metadata(
        self, manager: "LessonsManager"
    ):
        """parse_lesson() should extract triggers from the metadata line.

        The triggers are stored in the format:
        | **Triggers**: keyword1, keyword2, keyword3
        """
        # Write a lesson with triggers in the file
        lesson_format = """# LESSONS.md - Project Level

## Active Lessons

### [L011] [****-|-----] No mutex in destructors
- **Uses**: 13 | **Velocity**: 0.5 | **Learned**: 2025-01-01 | **Last**: 2025-01-15 | **Category**: gotcha | **Triggers**: destructor, mutex, shutdown
> Avoid mutex locks in destructors to prevent deadlocks during shutdown.

"""
        manager.project_lessons_file.parent.mkdir(parents=True, exist_ok=True)
        manager.project_lessons_file.write_text(lesson_format)

        lesson = manager.get_lesson("L011")
        assert lesson is not None
        assert hasattr(lesson, "triggers"), "Lesson should have triggers field"
        assert lesson.triggers == ["destructor", "mutex", "shutdown"], (
            f"Expected ['destructor', 'mutex', 'shutdown'], got {lesson.triggers}"
        )

    def test_parse_lesson_handles_missing_triggers(self, manager: "LessonsManager"):
        """parse_lesson() should default to empty list when triggers field is absent.

        Backward compatibility: lessons created before triggers field existed
        should parse correctly with an empty triggers list.
        """
        # Write a lesson WITHOUT triggers
        old_format = """# LESSONS.md - Project Level

## Active Lessons

### [L001] [*----|-----] Legacy lesson
- **Uses**: 1 | **Velocity**: 0 | **Learned**: 2025-01-01 | **Last**: 2025-01-15 | **Category**: pattern
> This is an old lesson without triggers field.

"""
        manager.project_lessons_file.parent.mkdir(parents=True, exist_ok=True)
        manager.project_lessons_file.write_text(old_format)

        lesson = manager.get_lesson("L001")
        assert lesson is not None
        assert hasattr(lesson, "triggers"), "Lesson should have triggers field"
        assert lesson.triggers == [], f"Expected empty list, got {lesson.triggers}"

    def test_format_lesson_writes_triggers_back(self, manager: "LessonsManager"):
        """format_lesson() should include Triggers field when triggers are present.

        When a lesson has triggers, the formatted output should include:
        | **Triggers**: keyword1, keyword2
        """
        # Create a lesson with triggers
        lesson_id = manager.add_lesson(
            level="project",
            category="pattern",
            title="Keyword matching pattern",
            content="Use specific keywords for better matching.",
            triggers=["matching", "keywords"],
        )

        # Read the raw file content
        content = manager.project_lessons_file.read_text()

        assert "**Triggers**:" in content, "Formatted lesson should contain Triggers field"
        assert "matching" in content
        assert "keywords" in content
        # Check the format is comma-separated
        assert "matching, keywords" in content or "keywords, matching" in content

    def test_format_lesson_omits_empty_triggers(self, manager: "LessonsManager"):
        """format_lesson() should NOT include Triggers field when triggers is empty.

        This keeps the file clean and backward compatible - lessons without
        triggers should not have a Triggers field in their metadata.
        """
        # Create a lesson WITHOUT triggers
        lesson_id = manager.add_lesson(
            level="project",
            category="pattern",
            title="Simple lesson",
            content="No triggers needed.",
        )

        # Read the raw file content
        content = manager.project_lessons_file.read_text()

        assert "**Triggers**:" not in content, (
            "Lesson with no triggers should not have Triggers field in file"
        )

    def test_triggers_roundtrip_parse_format_parse(self, manager: "LessonsManager"):
        """Round-trip test: parse -> format -> parse should preserve triggers.

        This ensures that triggers survive a write/read cycle without data loss.
        """
        # Write a lesson with triggers manually
        original_triggers = ["destructor", "mutex", "shutdown", "race_condition"]
        original_format = """# LESSONS.md - Project Level

## Active Lessons

### [L001] [***--|-----] Mutex gotcha
- **Uses**: 8 | **Velocity**: 1.5 | **Learned**: 2025-01-01 | **Last**: 2025-01-10 | **Category**: gotcha | **Triggers**: destructor, mutex, shutdown, race_condition
> Be careful with mutex usage in destructors.

"""
        manager.project_lessons_file.parent.mkdir(parents=True, exist_ok=True)
        manager.project_lessons_file.write_text(original_format)

        # Parse it
        lesson1 = manager.get_lesson("L001")
        assert lesson1 is not None
        assert lesson1.triggers == original_triggers

        # Cite the lesson (this triggers a write cycle)
        manager.cite_lesson("L001")

        # Parse it again
        lesson2 = manager.get_lesson("L001")
        assert lesson2 is not None
        assert lesson2.triggers == original_triggers, (
            f"Triggers changed after cite: expected {original_triggers}, got {lesson2.triggers}"
        )

    def test_add_lesson_with_empty_triggers_list(self, manager: "LessonsManager"):
        """Adding a lesson with explicit empty triggers should work correctly."""
        lesson_id = manager.add_lesson(
            level="project",
            category="pattern",
            title="No triggers lesson",
            content="Explicitly empty triggers.",
            triggers=[],
        )

        lesson = manager.get_lesson(lesson_id)
        assert lesson is not None
        assert lesson.triggers == []

        # Verify file doesn't contain Triggers field
        content = manager.project_lessons_file.read_text()
        assert "**Triggers**:" not in content

    def test_triggers_field_preserves_order(self, manager: "LessonsManager"):
        """Triggers should preserve their original order after round-trip."""
        original_triggers = ["alpha", "beta", "gamma", "delta"]

        lesson_id = manager.add_lesson(
            level="project",
            category="pattern",
            title="Ordered triggers",
            content="Triggers should stay in order.",
            triggers=original_triggers,
        )

        lesson = manager.get_lesson(lesson_id)
        assert lesson is not None
        assert lesson.triggers == original_triggers, (
            f"Order changed: expected {original_triggers}, got {lesson.triggers}"
        )

    def test_triggers_with_special_characters_in_keywords(
        self, manager: "LessonsManager"
    ):
        """Triggers containing hyphens or underscores should be handled correctly."""
        triggers_with_special = ["multi-word", "under_score", "simple"]

        lesson_id = manager.add_lesson(
            level="project",
            category="pattern",
            title="Special char triggers",
            content="Keywords can have hyphens and underscores.",
            triggers=triggers_with_special,
        )

        lesson = manager.get_lesson(lesson_id)
        assert lesson is not None
        assert lesson.triggers == triggers_with_special


# =============================================================================
# InjectionResult.format() Grouped Output with Triggers (TDD)
# =============================================================================


class TestInjectionFormatWithTriggers:
    """Tests for the new InjectionResult.format() grouped output with triggers.

    The new format groups remaining lessons by category and shows triggers inline:

        --- More (read if relevant) ---
        gotcha: [L011] No mutex destruct -> destructor|shutdown|static
              | [L014] Register XML -> component|silent fail
        pattern: [L004] Subject init -> XML|subjects|create order
               | [L008] Design tokens -> colors|spacing|hardcoded
        correction: [L045] Dropdown -> dropdown|bind_options
        (+3 more)
        * `show L###` when relevant
    """

    def test_format_shows_category_groups(
        self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path, monkeypatch
    ):
        """Remaining lessons should be grouped by category with section header.

        Create lessons with different categories (gotcha, pattern, correction).
        After top lessons, remaining should be grouped by category with
        section header '--- More (read if relevant) ---'.
        """
        from core import LessonsManager
        from core.models import Lesson, InjectionResult
        from datetime import date

        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        manager = LessonsManager(temp_lessons_base, temp_project_root)

        # Create lessons with different categories
        # High-uses lessons will be in top_lessons
        manager.add_lesson(
            level="project", category="pattern", title="Top Lesson 1",
            content="This is a top lesson", triggers=["top1"]
        )
        manager.add_lesson(
            level="project", category="gotcha", title="Top Lesson 2",
            content="Another top lesson", triggers=["top2"]
        )

        # Lower-uses lessons will be in "remaining" - different categories
        manager.add_lesson(
            level="project", category="gotcha", title="Gotcha Lesson",
            content="Watch out for this", triggers=["destructor", "shutdown"]
        )
        manager.add_lesson(
            level="project", category="pattern", title="Pattern Lesson",
            content="Use this pattern", triggers=["XML", "subjects"]
        )
        manager.add_lesson(
            level="project", category="correction", title="Correction Lesson",
            content="Fix this way", triggers=["dropdown"]
        )

        # Cite top lessons to ensure they rank higher
        for _ in range(5):
            manager.cite_lesson("L001")
            manager.cite_lesson("L002")

        result = manager.inject_context(top_n=2)
        output = result.format()

        # Should have section header for remaining lessons
        assert "More (read if relevant)" in output, (
            f"Expected section header '--- More (read if relevant) ---' in output:\n{output}"
        )

        # Should have category groups (lowercase)
        assert "gotcha:" in output, f"Expected 'gotcha:' category group in output:\n{output}"
        assert "pattern:" in output, f"Expected 'pattern:' category group in output:\n{output}"
        assert "correction:" in output, f"Expected 'correction:' category group in output:\n{output}"

    def test_format_triggers_appear_with_arrow_separator(
        self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path, monkeypatch
    ):
        """Triggers should appear with arrow separator: [ID] Title -> trigger1|trigger2|trigger3."""
        from core import LessonsManager
        from core.models import Lesson, InjectionResult
        from datetime import date

        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        manager = LessonsManager(temp_lessons_base, temp_project_root)

        # Top lesson with high uses
        manager.add_lesson(
            level="project", category="pattern", title="Top Lesson",
            content="Top content", triggers=["top"]
        )

        # Remaining lesson with triggers
        manager.add_lesson(
            level="project", category="gotcha", title="No mutex destruct",
            content="Watch out", triggers=["destructor", "shutdown", "static"]
        )

        # Cite top lesson
        for _ in range(5):
            manager.cite_lesson("L001")

        result = manager.inject_context(top_n=1)
        output = result.format()

        # Should show triggers with arrow separator
        # Format: [L002] No mutex destruct -> destructor|shutdown|static
        assert "->" in output or "→" in output, (
            f"Expected arrow separator '->' or '→' for triggers in output:\n{output}"
        )
        assert "destructor" in output, f"Expected trigger 'destructor' in output:\n{output}"
        assert "shutdown" in output, f"Expected trigger 'shutdown' in output:\n{output}"
        assert "static" in output, f"Expected trigger 'static' in output:\n{output}"

        # Triggers should be pipe-separated
        assert "destructor|shutdown|static" in output or "destructor|shutdown" in output, (
            f"Expected pipe-separated triggers in output:\n{output}"
        )

    def test_format_triggers_capped_at_three(
        self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path, monkeypatch
    ):
        """Lesson with 5 triggers should only show first 3 in output."""
        from core import LessonsManager
        from core.models import Lesson, InjectionResult
        from datetime import date

        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        manager = LessonsManager(temp_lessons_base, temp_project_root)

        # Top lesson
        manager.add_lesson(
            level="project", category="pattern", title="Top Lesson",
            content="Top content", triggers=[]
        )

        # Remaining lesson with 5 triggers
        manager.add_lesson(
            level="project", category="gotcha", title="Many triggers lesson",
            content="Has many triggers",
            triggers=["first", "second", "third", "fourth", "fifth"]
        )

        # Cite top lesson
        for _ in range(5):
            manager.cite_lesson("L001")

        result = manager.inject_context(top_n=1)
        output = result.format()

        # Should show only first 3 triggers
        assert "first" in output, f"Expected first trigger in output:\n{output}"
        assert "second" in output, f"Expected second trigger in output:\n{output}"
        assert "third" in output, f"Expected third trigger in output:\n{output}"

        # Should NOT show fourth and fifth triggers
        assert "fourth" not in output, f"Expected 'fourth' to be capped out of output:\n{output}"
        assert "fifth" not in output, f"Expected 'fifth' to be capped out of output:\n{output}"

    def test_format_empty_triggers_omitted(
        self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path, monkeypatch
    ):
        """Lesson with no triggers shows just [ID] Title without arrow.

        The new format shows triggers inline. When a lesson has triggers,
        it appears as: gotcha: [L002] Title -> kw1|kw2
        When a lesson has NO triggers, it should omit the arrow and just show:
        gotcha: [L002] Title
        """
        from core import LessonsManager
        from core.models import Lesson, InjectionResult
        from datetime import date

        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        manager = LessonsManager(temp_lessons_base, temp_project_root)

        # Top lesson
        manager.add_lesson(
            level="project", category="pattern", title="Top Lesson",
            content="Top content", triggers=[]
        )

        # Two remaining lessons: one WITH triggers, one WITHOUT
        manager.add_lesson(
            level="project", category="gotcha", title="Has triggers",
            content="Content", triggers=["kw1", "kw2"]
        )
        manager.add_lesson(
            level="project", category="gotcha", title="No triggers lesson",
            content="Has no triggers",
            triggers=[]  # Empty!
        )

        # Cite top lesson
        for _ in range(5):
            manager.cite_lesson("L001")

        result = manager.inject_context(top_n=1)
        output = result.format()

        # The lesson WITH triggers should show arrow and triggers
        assert "kw1" in output, f"Expected triggers 'kw1' for lesson with triggers:\n{output}"
        assert "kw2" in output, f"Expected triggers 'kw2' for lesson with triggers:\n{output}"

        # Find the line with L003 (no triggers lesson)
        lines = output.split("\n")
        l003_lines = [line for line in lines if "[L003]" in line]
        assert len(l003_lines) > 0, f"Expected line with [L003] in output:\n{output}"

        l003_line = l003_lines[0]

        # L003 should show [L003] and title but NO arrow since no triggers
        assert "[L003]" in l003_line
        assert "No triggers" in l003_line
        # Should NOT have arrow since no triggers
        # But L002 (with triggers) should have arrow
        assert "->" in output or "→" in output, (
            f"Expected arrow for lesson WITH triggers in output:\n{output}"
        )

        # Specifically L003 line should NOT have arrow
        # (need to check there's no arrow AFTER [L003] on that line)
        l003_portion = l003_line[l003_line.index("[L003]"):]
        assert "->" not in l003_portion and "→" not in l003_portion, (
            f"Expected no arrow for empty triggers on L003, but found in: {l003_portion}"
        )

    def test_format_category_grouping_format(
        self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path, monkeypatch
    ):
        """Category name lowercase followed by lessons: gotcha: [L001] Title -> kw1|kw2."""
        from core import LessonsManager
        from core.models import Lesson, InjectionResult
        from datetime import date

        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        manager = LessonsManager(temp_lessons_base, temp_project_root)

        # Top lesson
        manager.add_lesson(
            level="project", category="pattern", title="Top Lesson",
            content="Top content", triggers=[]
        )

        # Remaining lesson - gotcha category
        manager.add_lesson(
            level="project", category="gotcha", title="Gotcha Title",
            content="Content", triggers=["kw1", "kw2"]
        )

        # Cite top lesson
        for _ in range(5):
            manager.cite_lesson("L001")

        result = manager.inject_context(top_n=1)
        output = result.format()

        # Should have format: gotcha: [L002] Gotcha Title -> kw1|kw2
        # Category name should be lowercase followed by colon
        assert "gotcha:" in output, f"Expected 'gotcha:' with colon in output:\n{output}"

        # Lesson should be on same line as category or following line
        lines = output.split("\n")
        found_gotcha_format = False
        for line in lines:
            if "gotcha:" in line and "[L002]" in line:
                found_gotcha_format = True
                break

        assert found_gotcha_format, (
            f"Expected category and lesson on same line 'gotcha: [L002] ...' in output:\n{output}"
        )

    def test_format_multiple_lessons_in_category_use_pipe_separator(
        self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path, monkeypatch
    ):
        """Second lesson in same category shows as | [L002] Title2 -> kw3|kw4."""
        from core import LessonsManager
        from core.models import Lesson, InjectionResult
        from datetime import date

        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        manager = LessonsManager(temp_lessons_base, temp_project_root)

        # Top lesson
        manager.add_lesson(
            level="project", category="pattern", title="Top Lesson",
            content="Top content", triggers=[]
        )

        # Two remaining lessons in SAME category (gotcha)
        manager.add_lesson(
            level="project", category="gotcha", title="First Gotcha",
            content="First gotcha content", triggers=["kw1", "kw2"]
        )
        manager.add_lesson(
            level="project", category="gotcha", title="Second Gotcha",
            content="Second gotcha content", triggers=["kw3", "kw4"]
        )

        # Cite top lesson
        for _ in range(5):
            manager.cite_lesson("L001")

        result = manager.inject_context(top_n=1)
        output = result.format()

        # Should have pipe separator for second lesson in category
        # Format: gotcha: [L002] First Gotcha -> kw1|kw2
        #               | [L003] Second Gotcha -> kw3|kw4
        # Or could be on same line with pipe separator

        # Check that both L002 and L003 appear
        assert "[L002]" in output, f"Expected [L002] in output:\n{output}"
        assert "[L003]" in output, f"Expected [L003] in output:\n{output}"

        # Find lines with gotcha content - look for pipe separator between lessons
        # The second lesson in the category should have "| [" prefix (either L002 or L003)
        lines = output.split("\n")
        pipe_separator_found = False
        for line in lines:
            # Second lesson in category should start with pipe (after indent)
            # Format: "        | [L002] Title" or "        | [L003] Title"
            stripped = line.strip()
            if stripped.startswith("| [L002]") or stripped.startswith("| [L003]"):
                pipe_separator_found = True
                break
            # Also check for | followed by [ anywhere in line (more flexible)
            if "| [L002]" in line or "| [L003]" in line:
                pipe_separator_found = True
                break

        assert pipe_separator_found, (
            f"Expected pipe '|' separator before second lesson in same category:\n{output}"
        )

    def test_format_remaining_count_excludes_displayed(
        self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path, monkeypatch
    ):
        """(+N more) should reflect lessons NOT shown (after cap).

        In the NEW format, remaining lessons are grouped by category.
        The (+N more) count should reflect the total number of lessons
        that are not displayed (beyond what's shown in category groups).
        """
        from core import LessonsManager
        from core.models import Lesson, InjectionResult, INJECTION_REMAINING_CAP
        from datetime import date

        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        manager = LessonsManager(temp_lessons_base, temp_project_root)

        # Create one top lesson
        manager.add_lesson(
            level="project", category="pattern", title="Top Lesson",
            content="Top content", triggers=[]
        )

        # Create 15 remaining lessons (more than INJECTION_REMAINING_CAP which is 10)
        # Use different categories to test grouped display
        alphabet = "ABCDEFGHIJKLMNOP"  # 16 letters
        categories = ["gotcha", "pattern", "correction"]
        for i in range(15):
            manager.add_lesson(
                level="project", category=categories[i % 3],
                title=f"Remaining {alphabet[i]}",
                content=f"Content {i}", triggers=[f"trigger{i}"]
            )

        # Cite top lesson
        for _ in range(10):
            manager.cite_lesson("L001")

        result = manager.inject_context(top_n=1)
        output = result.format()

        # The new format should have the section header
        assert "More (read if relevant)" in output, (
            f"Expected section header for remaining lessons:\n{output}"
        )

        # With 15 remaining lessons and cap of 10, should show "+5 more"
        # (15 - 10 = 5 not shown)
        assert "+5 more" in output, (
            f"Expected '(+5 more)' in output with 15 remaining and 10 cap:\n{output}"
        )

        # Should show some triggers in the remaining section
        # At least some of the displayed 10 lessons should have triggers visible
        trigger_count = sum(1 for i in range(10) if f"trigger{i}" in output)
        assert trigger_count > 0, (
            f"Expected at least some triggers to be shown for remaining lessons:\n{output}"
        )


# =============================================================================
# Auto-Generating Triggers on Lesson Add (TDD)
# =============================================================================


class TestAutoTriggers:
    """Tests for auto-generating triggers when adding new lessons.

    When adding a lesson WITHOUT explicit triggers, the system should
    automatically call the Haiku API to generate relevant trigger keywords.
    When explicit triggers are provided, no API call should be made.
    """

    def test_add_lesson_auto_generates_triggers(
        self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path, monkeypatch
    ):
        """When adding a lesson WITHOUT explicit triggers, triggers should be auto-generated via Haiku.

        The system should:
        1. Detect that no triggers were provided
        2. Call the Haiku API to generate triggers based on title/content
        3. Store the auto-generated triggers with the lesson
        """
        from unittest.mock import patch, MagicMock
        from core import LessonsManager

        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        manager = LessonsManager(temp_lessons_base, temp_project_root)

        # First verify the method exists (this is the primary test)
        assert hasattr(manager, "generate_single_lesson_triggers"), (
            "LessonsManager should have generate_single_lesson_triggers method"
        )

        # Mock the Haiku API call to return generated triggers
        with patch.object(manager, "generate_single_lesson_triggers") as mock_gen:
            mock_gen.return_value = ["mutex", "destructor", "deadlock"]

            # Add lesson WITHOUT triggers - should call API
            lesson_id = manager.add_lesson(
                level="project",
                category="gotcha",
                title="Avoid mutex in destructors",
                content="Never acquire a mutex in a destructor as it can cause deadlocks.",
            )

            # Verify the API was called
            mock_gen.assert_called_once()

        # Verify triggers were stored
        lesson = manager.get_lesson(lesson_id)
        assert lesson is not None
        assert lesson.triggers == ["mutex", "destructor", "deadlock"], (
            f"Expected auto-generated triggers, got {lesson.triggers}"
        )

    def test_add_lesson_explicit_triggers_no_api_call(
        self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path, monkeypatch
    ):
        """When adding a lesson WITH explicit triggers, NO API call should be made.

        The explicit triggers should be used as-is without any API overhead.
        """
        from unittest.mock import patch, MagicMock
        from core import LessonsManager

        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        manager = LessonsManager(temp_lessons_base, temp_project_root)

        # First verify the method exists (prerequisite for this test)
        assert hasattr(manager, "generate_single_lesson_triggers"), (
            "LessonsManager should have generate_single_lesson_triggers method"
        )

        with patch.object(manager, "generate_single_lesson_triggers") as mock_gen:
            # Add lesson WITH explicit triggers - should NOT call API
            lesson_id = manager.add_lesson(
                level="project",
                category="pattern",
                title="Use spdlog for logging",
                content="Always use spdlog instead of printf or cout.",
                triggers=["spdlog", "logging", "printf"],
            )

            # Verify the API was NOT called
            mock_gen.assert_not_called()

        # Verify explicit triggers were stored
        lesson = manager.get_lesson(lesson_id)
        assert lesson is not None
        assert lesson.triggers == ["spdlog", "logging", "printf"], (
            f"Expected explicit triggers, got {lesson.triggers}"
        )

    def test_add_command_triggers_flag(
        self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path
    ):
        """The `add` CLI command should accept --triggers "kw1,kw2,kw3" flag.

        When --triggers is provided, those triggers should be used directly
        without calling the API.
        """
        result = subprocess.run(
            [
                "python3", "core/cli.py",
                "add",
                "--triggers", "custom1,custom2,custom3",
                "pattern", "CLI Trigger Test", "Test content with triggers"
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

        assert result.returncode == 0, f"CLI failed: {result.stderr}"

        # Verify the lesson was created with correct triggers
        from core import LessonsManager
        manager = LessonsManager(temp_lessons_base, temp_project_root)
        lesson = manager.get_lesson("L001")
        assert lesson is not None
        assert lesson.triggers == ["custom1", "custom2", "custom3"], (
            f"Expected CLI-provided triggers, got {lesson.triggers}"
        )

    def test_add_command_no_triggers_flag_calls_api(
        self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path, monkeypatch
    ):
        """When --triggers flag is NOT provided, triggers should be auto-generated."""
        from argparse import Namespace
        from core import LessonsManager
        from core.commands import AddCommand, MigrateTriggersCommand

        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        manager = LessonsManager(temp_lessons_base, temp_project_root)

        # Mock the Haiku API call
        def mock_call_haiku_api(prompt):
            return "TRIGGERS: auto1, auto2, auto3"

        monkeypatch.setattr(MigrateTriggersCommand, "call_haiku_api", staticmethod(mock_call_haiku_api))

        # Create args as if from CLI (without --triggers)
        args = Namespace(
            category="pattern",
            title="Auto-trigger test",
            content="This lesson should auto-generate triggers",
            triggers=None,  # No explicit triggers
            source="human",
            force=False,
            promotable=True,
            lesson_type="",
        )

        # Execute command
        cmd = AddCommand()
        exit_code = cmd.execute(args, manager)

        assert exit_code == 0

        # Verify triggers were auto-generated
        lesson = manager.get_lesson("L001")
        assert lesson is not None
        assert len(lesson.triggers) > 0, "Triggers should have been auto-generated"
        assert "auto1" in lesson.triggers

    def test_generate_single_lesson_triggers(
        self, temp_lessons_base: Path, temp_state_dir: Path, temp_project_root: Path, monkeypatch
    ):
        """There should be a method generate_single_lesson_triggers(lesson) for single lessons.

        This method should:
        1. Accept a Lesson object
        2. Call the Haiku API with appropriate prompt
        3. Return a list of trigger keywords
        """
        from unittest.mock import patch
        from core import LessonsManager
        from core.models import Lesson
        from datetime import date

        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))
        manager = LessonsManager(temp_lessons_base, temp_project_root)

        # Create a lesson object to generate triggers for
        lesson = Lesson(
            id="L001",
            title="Avoid global state",
            content="Global variables make testing difficult and introduce hidden dependencies.",
            category="pattern",
            uses=1,
            velocity=0,
            learned=date.today(),
            last_used=date.today(),
            level="project",
            triggers=[],
        )

        # Verify the method exists
        assert hasattr(manager, "generate_single_lesson_triggers"), (
            "LessonsManager should have generate_single_lesson_triggers method"
        )

        # Mock the underlying API call
        with patch("core.commands.MigrateTriggersCommand.call_haiku_api") as mock_api:
            mock_api.return_value = "L001: global, state, testing, dependencies"

            triggers = manager.generate_single_lesson_triggers(lesson)

            # Verify API was called
            mock_api.assert_called_once()

            # Verify triggers were parsed correctly
            assert isinstance(triggers, list), f"Expected list, got {type(triggers)}"
            assert len(triggers) > 0, "Expected at least one trigger"
            assert "global" in triggers or "state" in triggers, (
                f"Expected relevant triggers, got {triggers}"
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
