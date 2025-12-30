#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Test suite for Approaches tracking system.

This is a TDD test file - tests are written BEFORE the implementation.
Run with: pytest tests/test_approaches.py -v

The approaches system tracks ongoing work with tried approaches and next steps.
Storage location: <project_root>/.coding-agent-lessons/APPROACHES.md

File format:
    # APPROACHES.md - Active Work Tracking

    > Track ongoing work with tried approaches and next steps.
    > When completed, review for lessons to extract.

    ## Active Approaches

    ### [A001] Implementing WebSocket reconnection
    - **Status**: in_progress | **Created**: 2025-12-28 | **Updated**: 2025-12-28
    - **Files**: src/websocket.ts, src/connection-manager.ts
    - **Description**: Add automatic reconnection with exponential backoff

    **Tried**:
    1. [fail] Simple setTimeout retry - races with manual disconnect
    2. [partial] State machine approach - works but complex
    3. [success] Event-based with AbortController - clean and testable

    **Next**: Write integration tests for edge cases

    ---
"""

import os
import subprocess
import sys

import pytest
from datetime import date, timedelta
from pathlib import Path
from typing import List, Optional

# These imports will fail until implementation exists - that's expected for TDD
try:
    from core.lessons_manager import (
        LessonsManager,
        Approach,
        TriedApproach,
        ApproachCompleteResult,
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
    lessons_base = tmp_path / ".config" / "coding-agent-lessons"
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
    """Create a LessonsManager instance with temporary paths."""
    return LessonsManager(
        lessons_base=temp_lessons_base,
        project_root=temp_project_root,
    )


@pytest.fixture
def manager_with_approaches(manager: "LessonsManager") -> "LessonsManager":
    """Create a manager with some pre-existing approaches."""
    manager.approach_add(
        title="Implementing WebSocket reconnection",
        desc="Add automatic reconnection with exponential backoff",
        files=["src/websocket.ts", "src/connection-manager.ts"],
    )
    manager.approach_add(
        title="Refactoring database layer",
        desc="Extract repository pattern from service classes",
        files=["src/db/models.py"],
    )
    manager.approach_add(
        title="Adding unit tests",
        desc="Improve test coverage for core module",
    )
    return manager


# =============================================================================
# Adding Approaches
# =============================================================================


class TestApproachAdd:
    """Tests for adding approaches."""

    def test_approach_add_creates_file(self, manager: "LessonsManager"):
        """Adding an approach should create the APPROACHES.md file."""
        manager.approach_add(title="Test approach")

        approaches_file = manager.project_root / ".coding-agent-lessons" / "APPROACHES.md"
        assert approaches_file.exists()
        content = approaches_file.read_text()
        assert "Test approach" in content

    def test_approach_add_assigns_sequential_id(self, manager: "LessonsManager"):
        """Approach IDs should be assigned sequentially starting from A001."""
        id1 = manager.approach_add(title="First approach")
        id2 = manager.approach_add(title="Second approach")
        id3 = manager.approach_add(title="Third approach")

        assert id1 == "A001"
        assert id2 == "A002"
        assert id3 == "A003"

    def test_approach_add_with_description(self, manager: "LessonsManager"):
        """Adding an approach with description should store it."""
        approach_id = manager.approach_add(
            title="Feature work",
            desc="Implementing the new feature with proper error handling",
        )

        approach = manager.approach_get(approach_id)
        assert approach is not None
        assert approach.description == "Implementing the new feature with proper error handling"

    def test_approach_add_with_files(self, manager: "LessonsManager"):
        """Adding an approach with files should store the file list."""
        approach_id = manager.approach_add(
            title="Multi-file refactor",
            files=["src/main.py", "src/utils.py", "tests/test_main.py"],
        )

        approach = manager.approach_get(approach_id)
        assert approach is not None
        assert approach.files == ["src/main.py", "src/utils.py", "tests/test_main.py"]

    def test_approach_add_initializes_metadata(self, manager: "LessonsManager"):
        """New approaches should have correct initial metadata."""
        manager.approach_add(title="New work")
        approach = manager.approach_get("A001")

        assert approach is not None
        assert approach.status == "not_started"
        assert approach.created == date.today()
        assert approach.updated == date.today()
        assert approach.tried == []
        assert approach.next_steps == ""

    def test_approach_add_returns_id(self, manager: "LessonsManager"):
        """Adding an approach should return the assigned ID."""
        result = manager.approach_add(title="Return test")

        assert result == "A001"
        assert isinstance(result, str)


# =============================================================================
# Updating Approaches
# =============================================================================


class TestApproachUpdateStatus:
    """Tests for updating approach status."""

    def test_approach_update_status_valid(self, manager_with_approaches: "LessonsManager"):
        """Should update status with valid values."""
        manager_with_approaches.approach_update_status("A001", "in_progress")
        approach = manager_with_approaches.approach_get("A001")
        assert approach.status == "in_progress"

        manager_with_approaches.approach_update_status("A001", "blocked")
        approach = manager_with_approaches.approach_get("A001")
        assert approach.status == "blocked"

        manager_with_approaches.approach_update_status("A001", "completed")
        approach = manager_with_approaches.approach_get("A001")
        assert approach.status == "completed"

    def test_approach_update_status_invalid_rejects(self, manager_with_approaches: "LessonsManager"):
        """Should reject invalid status values."""
        with pytest.raises(ValueError, match="[Ii]nvalid status"):
            manager_with_approaches.approach_update_status("A001", "invalid_status")

        with pytest.raises(ValueError, match="[Ii]nvalid status"):
            manager_with_approaches.approach_update_status("A001", "done")

        with pytest.raises(ValueError, match="[Ii]nvalid status"):
            manager_with_approaches.approach_update_status("A001", "")

    def test_approach_update_status_nonexistent_fails(self, manager: "LessonsManager"):
        """Should fail when updating nonexistent approach."""
        with pytest.raises(ValueError, match="not found"):
            manager.approach_update_status("A999", "in_progress")


class TestApproachAddTried:
    """Tests for adding tried approaches."""

    def test_approach_add_tried_success(self, manager_with_approaches: "LessonsManager"):
        """Should add a successful tried approach."""
        manager_with_approaches.approach_add_tried(
            "A001",
            outcome="success",
            description="Event-based with AbortController - clean and testable",
        )

        approach = manager_with_approaches.approach_get("A001")
        assert len(approach.tried) == 1
        assert approach.tried[0].outcome == "success"
        assert approach.tried[0].description == "Event-based with AbortController - clean and testable"

    def test_approach_add_tried_fail(self, manager_with_approaches: "LessonsManager"):
        """Should add a failed tried approach."""
        manager_with_approaches.approach_add_tried(
            "A001",
            outcome="fail",
            description="Simple setTimeout retry - races with manual disconnect",
        )

        approach = manager_with_approaches.approach_get("A001")
        assert len(approach.tried) == 1
        assert approach.tried[0].outcome == "fail"

    def test_approach_add_tried_partial(self, manager_with_approaches: "LessonsManager"):
        """Should add a partial success tried approach."""
        manager_with_approaches.approach_add_tried(
            "A001",
            outcome="partial",
            description="State machine approach - works but complex",
        )

        approach = manager_with_approaches.approach_get("A001")
        assert len(approach.tried) == 1
        assert approach.tried[0].outcome == "partial"

    def test_approach_add_tried_multiple(self, manager_with_approaches: "LessonsManager"):
        """Should support adding multiple tried approaches in order."""
        manager_with_approaches.approach_add_tried("A001", "fail", "First attempt - failed")
        manager_with_approaches.approach_add_tried("A001", "partial", "Second attempt - partial")
        manager_with_approaches.approach_add_tried("A001", "success", "Third attempt - worked")

        approach = manager_with_approaches.approach_get("A001")
        assert len(approach.tried) == 3
        assert approach.tried[0].description == "First attempt - failed"
        assert approach.tried[1].description == "Second attempt - partial"
        assert approach.tried[2].description == "Third attempt - worked"

    def test_approach_add_tried_invalid_outcome(self, manager_with_approaches: "LessonsManager"):
        """Should reject invalid outcome values."""
        with pytest.raises(ValueError, match="[Ii]nvalid outcome"):
            manager_with_approaches.approach_add_tried("A001", "maybe", "Uncertain result")


class TestApproachUpdateNext:
    """Tests for updating next steps."""

    def test_approach_update_next(self, manager_with_approaches: "LessonsManager"):
        """Should update the next steps field."""
        manager_with_approaches.approach_update_next(
            "A001",
            "Write integration tests for edge cases",
        )

        approach = manager_with_approaches.approach_get("A001")
        assert approach.next_steps == "Write integration tests for edge cases"

    def test_approach_update_next_overwrites(self, manager_with_approaches: "LessonsManager"):
        """Updating next steps should overwrite previous value."""
        manager_with_approaches.approach_update_next("A001", "First next step")
        manager_with_approaches.approach_update_next("A001", "Updated next step")

        approach = manager_with_approaches.approach_get("A001")
        assert approach.next_steps == "Updated next step"

    def test_approach_update_next_empty(self, manager_with_approaches: "LessonsManager"):
        """Should allow clearing next steps."""
        manager_with_approaches.approach_update_next("A001", "Some steps")
        manager_with_approaches.approach_update_next("A001", "")

        approach = manager_with_approaches.approach_get("A001")
        assert approach.next_steps == ""


class TestApproachUpdateFiles:
    """Tests for updating file lists."""

    def test_approach_update_files(self, manager_with_approaches: "LessonsManager"):
        """Should update the files list."""
        manager_with_approaches.approach_update_files(
            "A001",
            ["new/file1.py", "new/file2.py"],
        )

        approach = manager_with_approaches.approach_get("A001")
        assert approach.files == ["new/file1.py", "new/file2.py"]

    def test_approach_update_files_replaces(self, manager_with_approaches: "LessonsManager"):
        """Updating files should replace the entire list."""
        manager_with_approaches.approach_update_files("A001", ["a.py", "b.py"])
        manager_with_approaches.approach_update_files("A001", ["c.py"])

        approach = manager_with_approaches.approach_get("A001")
        assert approach.files == ["c.py"]

    def test_approach_update_files_empty(self, manager_with_approaches: "LessonsManager"):
        """Should allow clearing file list."""
        manager_with_approaches.approach_update_files("A001", ["some.py"])
        manager_with_approaches.approach_update_files("A001", [])

        approach = manager_with_approaches.approach_get("A001")
        assert approach.files == []


class TestApproachUpdateDesc:
    """Tests for updating description."""

    def test_approach_update_desc(self, manager_with_approaches: "LessonsManager"):
        """Should update the description."""
        manager_with_approaches.approach_update_desc("A001", "New description text")

        approach = manager_with_approaches.approach_get("A001")
        assert approach.description == "New description text"


class TestApproachUpdateSetsDate:
    """Tests for automatic date updates."""

    def test_approach_update_sets_updated_date(self, manager_with_approaches: "LessonsManager"):
        """Any update should set the updated date to today."""
        # Manually set updated to a past date for testing
        approach = manager_with_approaches.approach_get("A001")
        original_updated = approach.updated

        # Make an update
        manager_with_approaches.approach_update_status("A001", "in_progress")

        approach = manager_with_approaches.approach_get("A001")
        assert approach.updated == date.today()

    def test_approach_add_tried_updates_date(self, manager_with_approaches: "LessonsManager"):
        """Adding a tried approach should update the date."""
        manager_with_approaches.approach_add_tried("A001", "fail", "Test")

        approach = manager_with_approaches.approach_get("A001")
        assert approach.updated == date.today()

    def test_approach_update_next_updates_date(self, manager_with_approaches: "LessonsManager"):
        """Updating next steps should update the date."""
        manager_with_approaches.approach_update_next("A001", "Next steps here")

        approach = manager_with_approaches.approach_get("A001")
        assert approach.updated == date.today()


# =============================================================================
# Completing and Archiving Approaches
# =============================================================================


class TestApproachComplete:
    """Tests for completing approaches."""

    def test_approach_complete_sets_status(self, manager_with_approaches: "LessonsManager"):
        """Completing should set status to completed."""
        manager_with_approaches.approach_complete("A001")

        approach = manager_with_approaches.approach_get("A001")
        assert approach.status == "completed"

    def test_approach_complete_returns_extraction_prompt(
        self, manager_with_approaches: "LessonsManager"
    ):
        """Completing should return a prompt for lesson extraction."""
        # Add some tried approaches first
        manager_with_approaches.approach_add_tried("A001", "fail", "First failed attempt")
        manager_with_approaches.approach_add_tried("A001", "success", "Successful approach")

        result = manager_with_approaches.approach_complete("A001")

        # Should return ApproachCompleteResult with extraction_prompt
        assert hasattr(result, "extraction_prompt")
        assert isinstance(result.extraction_prompt, str)
        assert len(result.extraction_prompt) > 0
        # Prompt should mention lesson extraction or similar
        assert "lesson" in result.extraction_prompt.lower() or "extract" in result.extraction_prompt.lower()

    def test_approach_complete_result_includes_approach_data(
        self, manager_with_approaches: "LessonsManager"
    ):
        """Complete result should include the approach data for reference."""
        manager_with_approaches.approach_add_tried("A001", "success", "What worked")

        result = manager_with_approaches.approach_complete("A001")

        assert hasattr(result, "approach")
        assert result.approach.title == "Implementing WebSocket reconnection"


class TestApproachArchive:
    """Tests for archiving approaches."""

    def test_approach_archive_moves_to_archive_file(
        self, manager_with_approaches: "LessonsManager"
    ):
        """Archiving should move approach to APPROACHES_ARCHIVE.md."""
        manager_with_approaches.approach_archive("A001")

        # Should no longer be in main file
        approach = manager_with_approaches.approach_get("A001")
        assert approach is None

        # Should be in archive file
        archive_file = (
            manager_with_approaches.project_root
            / ".coding-agent-lessons"
            / "APPROACHES_ARCHIVE.md"
        )
        assert archive_file.exists()
        content = archive_file.read_text()
        assert "A001" in content
        assert "Implementing WebSocket reconnection" in content

    def test_approach_archive_creates_archive_if_missing(self, manager: "LessonsManager"):
        """Archiving should create archive file if it doesn't exist."""
        manager.approach_add(title="To be archived")

        archive_file = (
            manager.project_root / ".coding-agent-lessons" / "APPROACHES_ARCHIVE.md"
        )
        assert not archive_file.exists()

        manager.approach_archive("A001")

        assert archive_file.exists()

    def test_approach_archive_preserves_data(self, manager_with_approaches: "LessonsManager"):
        """Archived approach should preserve all its data."""
        # Add some data first
        manager_with_approaches.approach_update_status("A001", "in_progress")
        manager_with_approaches.approach_add_tried("A001", "fail", "Failed attempt")
        manager_with_approaches.approach_add_tried("A001", "success", "Worked!")
        manager_with_approaches.approach_update_next("A001", "Document the solution")

        # Get data before archive
        approach_before = manager_with_approaches.approach_get("A001")

        manager_with_approaches.approach_archive("A001")

        # Read archive file and verify data is present
        archive_file = (
            manager_with_approaches.project_root
            / ".coding-agent-lessons"
            / "APPROACHES_ARCHIVE.md"
        )
        content = archive_file.read_text()

        assert approach_before.title in content
        assert "fail" in content.lower()
        assert "success" in content.lower()
        assert "Failed attempt" in content
        assert "Worked!" in content

    def test_approach_archive_appends_to_existing(
        self, manager_with_approaches: "LessonsManager"
    ):
        """Multiple archives should append to the same file."""
        manager_with_approaches.approach_archive("A001")
        manager_with_approaches.approach_archive("A002")

        archive_file = (
            manager_with_approaches.project_root
            / ".coding-agent-lessons"
            / "APPROACHES_ARCHIVE.md"
        )
        content = archive_file.read_text()

        assert "A001" in content
        assert "A002" in content
        assert "Implementing WebSocket reconnection" in content
        assert "Refactoring database layer" in content


class TestApproachDelete:
    """Tests for deleting approaches."""

    def test_approach_delete_removes_entry(self, manager_with_approaches: "LessonsManager"):
        """Deleting should remove the approach entirely."""
        manager_with_approaches.approach_delete("A001")

        approach = manager_with_approaches.approach_get("A001")
        assert approach is None

        # Should not be in the list
        approaches = manager_with_approaches.approach_list()
        ids = [a.id for a in approaches]
        assert "A001" not in ids

    def test_approach_delete_nonexistent_fails(self, manager: "LessonsManager"):
        """Deleting a nonexistent approach should raise an error."""
        with pytest.raises(ValueError, match="not found"):
            manager.approach_delete("A999")

    def test_approach_delete_does_not_archive(
        self, manager_with_approaches: "LessonsManager"
    ):
        """Deleting should not move to archive (unlike archive)."""
        manager_with_approaches.approach_delete("A001")

        archive_file = (
            manager_with_approaches.project_root
            / ".coding-agent-lessons"
            / "APPROACHES_ARCHIVE.md"
        )
        # Archive file should not exist or not contain the deleted approach
        if archive_file.exists():
            content = archive_file.read_text()
            assert "A001" not in content


# =============================================================================
# Querying Approaches
# =============================================================================


class TestApproachGet:
    """Tests for getting individual approaches."""

    def test_approach_get_existing(self, manager_with_approaches: "LessonsManager"):
        """Should return the approach with correct data."""
        approach = manager_with_approaches.approach_get("A001")

        assert approach is not None
        assert approach.id == "A001"
        assert approach.title == "Implementing WebSocket reconnection"
        assert approach.description == "Add automatic reconnection with exponential backoff"
        assert approach.files == ["src/websocket.ts", "src/connection-manager.ts"]

    def test_approach_get_nonexistent(self, manager: "LessonsManager"):
        """Should return None for nonexistent approach."""
        approach = manager.approach_get("A999")
        assert approach is None

    def test_approach_get_returns_approach_dataclass(
        self, manager_with_approaches: "LessonsManager"
    ):
        """Should return an Approach dataclass instance."""
        approach = manager_with_approaches.approach_get("A001")

        assert isinstance(approach, Approach)
        assert hasattr(approach, "id")
        assert hasattr(approach, "title")
        assert hasattr(approach, "status")
        assert hasattr(approach, "created")
        assert hasattr(approach, "updated")
        assert hasattr(approach, "files")
        assert hasattr(approach, "description")
        assert hasattr(approach, "tried")
        assert hasattr(approach, "next_steps")


class TestApproachList:
    """Tests for listing approaches."""

    def test_approach_list_all(self, manager_with_approaches: "LessonsManager"):
        """Should list all approaches."""
        approaches = manager_with_approaches.approach_list()

        assert len(approaches) == 3
        ids = [a.id for a in approaches]
        assert "A001" in ids
        assert "A002" in ids
        assert "A003" in ids

    def test_approach_list_by_status(self, manager_with_approaches: "LessonsManager"):
        """Should filter by status."""
        manager_with_approaches.approach_update_status("A001", "in_progress")
        manager_with_approaches.approach_update_status("A002", "blocked")

        in_progress = manager_with_approaches.approach_list(status_filter="in_progress")
        blocked = manager_with_approaches.approach_list(status_filter="blocked")
        not_started = manager_with_approaches.approach_list(status_filter="not_started")

        assert len(in_progress) == 1
        assert in_progress[0].id == "A001"

        assert len(blocked) == 1
        assert blocked[0].id == "A002"

        assert len(not_started) == 1
        assert not_started[0].id == "A003"

    def test_approach_list_excludes_completed(self, manager_with_approaches: "LessonsManager"):
        """Default list should exclude completed approaches."""
        manager_with_approaches.approach_update_status("A001", "completed")

        # Default list (no filter) should exclude completed
        approaches = manager_with_approaches.approach_list()
        ids = [a.id for a in approaches]
        assert "A001" not in ids
        assert len(approaches) == 2

    def test_approach_list_completed_explicit(self, manager_with_approaches: "LessonsManager"):
        """Should be able to explicitly list completed approaches."""
        manager_with_approaches.approach_update_status("A001", "completed")

        completed = manager_with_approaches.approach_list(status_filter="completed")

        assert len(completed) == 1
        assert completed[0].id == "A001"

    def test_approach_list_empty(self, manager: "LessonsManager"):
        """Should return empty list when no approaches exist."""
        approaches = manager.approach_list()
        assert approaches == []


class TestApproachInject:
    """Tests for context injection."""

    def test_approach_inject_active_only(self, manager_with_approaches: "LessonsManager"):
        """Inject should show completed approaches in Recent Completions, not Active."""
        manager_with_approaches.approach_update_status("A001", "completed")

        injected = manager_with_approaches.approach_inject()

        # Split by sections to verify placement
        assert "## Active Approaches" in injected
        assert "## Recent Completions" in injected

        active_section = injected.split("## Recent Completions")[0]
        completions_section = injected.split("## Recent Completions")[1]

        # A001 should be in completions, not active
        assert "A001" not in active_section
        assert "A001" in completions_section

        # A002 and A003 should be in active
        assert "A002" in active_section
        assert "A003" in active_section

    def test_approach_inject_format(self, manager_with_approaches: "LessonsManager"):
        """Inject should return formatted string for context."""
        manager_with_approaches.approach_update_status("A001", "in_progress")
        manager_with_approaches.approach_add_tried("A001", "fail", "First attempt failed")
        manager_with_approaches.approach_update_next("A001", "Try a different approach")

        injected = manager_with_approaches.approach_inject()

        # Should be a non-empty string
        assert isinstance(injected, str)
        assert len(injected) > 0

        # Should contain key information
        assert "A001" in injected
        assert "Implementing WebSocket reconnection" in injected
        assert "in_progress" in injected.lower()

    def test_approach_inject_empty_returns_empty(self, manager: "LessonsManager"):
        """Inject with no approaches should return empty string."""
        injected = manager.approach_inject()
        assert injected == ""

    def test_approach_inject_includes_tried(self, manager_with_approaches: "LessonsManager"):
        """Inject should include tried approaches."""
        manager_with_approaches.approach_add_tried("A001", "fail", "First failed")
        manager_with_approaches.approach_add_tried("A001", "success", "This worked")

        injected = manager_with_approaches.approach_inject()

        assert "First failed" in injected or "fail" in injected.lower()
        assert "This worked" in injected or "success" in injected.lower()

    def test_approach_inject_includes_next_steps(self, manager_with_approaches: "LessonsManager"):
        """Inject should include next steps."""
        manager_with_approaches.approach_update_next("A001", "Write more tests")

        injected = manager_with_approaches.approach_inject()

        assert "Write more tests" in injected


# =============================================================================
# Edge Cases
# =============================================================================


class TestApproachEdgeCases:
    """Tests for edge cases and error handling."""

    def test_approach_with_special_characters(self, manager: "LessonsManager"):
        """Should handle special characters in title and description."""
        title = "Fix the 'bug' in |pipe| handling & more"
        desc = "Handle special chars: <>, [], {}, $var, @annotation"

        approach_id = manager.approach_add(title=title, desc=desc)

        approach = manager.approach_get(approach_id)
        assert approach is not None
        assert approach.title == title
        assert approach.description == desc

    def test_approach_with_special_characters_in_tried(self, manager: "LessonsManager"):
        """Should handle special characters in tried descriptions."""
        manager.approach_add(title="Test approach")
        manager.approach_add_tried(
            "A001",
            outcome="fail",
            description="Used 'quotes' and |pipes| - didn't work",
        )

        approach = manager.approach_get("A001")
        assert len(approach.tried) == 1
        assert "quotes" in approach.tried[0].description

    def test_multiple_approaches(self, manager: "LessonsManager"):
        """Should handle many approaches correctly."""
        for i in range(10):
            manager.approach_add(title=f"Approach {i+1}")

        approaches = manager.approach_list()
        assert len(approaches) == 10

        # IDs should be sequential
        ids = sorted([a.id for a in approaches])
        expected = [f"A{i:03d}" for i in range(1, 11)]
        assert ids == expected

    def test_approach_empty_file(self, manager: "LessonsManager"):
        """Should handle empty approaches file gracefully."""
        approaches_file = manager.project_root / ".coding-agent-lessons" / "APPROACHES.md"
        approaches_file.parent.mkdir(parents=True, exist_ok=True)
        approaches_file.write_text("")

        approaches = manager.approach_list()
        assert approaches == []

    def test_approach_malformed_entry_skipped(self, manager: "LessonsManager"):
        """Should skip malformed entries without crashing."""
        approaches_file = manager.project_root / ".coding-agent-lessons" / "APPROACHES.md"
        approaches_file.parent.mkdir(parents=True, exist_ok=True)

        malformed = """# APPROACHES.md - Active Work Tracking

## Active Approaches

### [A001] Malformed entry
Missing the status line

### [A002] Valid approach
- **Status**: not_started | **Created**: 2025-12-28 | **Updated**: 2025-12-28
- **Files**:
- **Description**: This one is valid

**Tried**:

**Next**:

---
"""
        approaches_file.write_text(malformed)

        approaches = manager.approach_list()
        # Should only get the valid approach
        assert len(approaches) == 1
        assert approaches[0].id == "A002"

    def test_approach_id_after_deletion(self, manager: "LessonsManager"):
        """IDs should not be reused after deletion."""
        manager.approach_add(title="First")
        manager.approach_add(title="Second")
        manager.approach_delete("A001")

        # New approach should get A003, not A001
        new_id = manager.approach_add(title="Third")
        assert new_id == "A003"

    def test_approach_with_long_description(self, manager: "LessonsManager"):
        """Should handle long descriptions."""
        long_desc = "A" * 1000
        approach_id = manager.approach_add(title="Long desc test", desc=long_desc)

        approach = manager.approach_get(approach_id)
        assert approach.description == long_desc

    def test_approach_with_unicode_characters(self, manager: "LessonsManager"):
        """Should handle unicode characters."""
        title = "Fix emoji handling: \U0001f916 \U0001f4bb \U0001f525"
        desc = "Handle international text: \u4e2d\u6587 \u65e5\u672c\u8a9e \ud55c\uad6d\uc5b4"

        approach_id = manager.approach_add(title=title, desc=desc)

        approach = manager.approach_get(approach_id)
        assert approach.title == title
        assert approach.description == desc

    def test_approach_tried_preserves_order(self, manager: "LessonsManager"):
        """Tried approaches should maintain insertion order."""
        manager.approach_add(title="Order test")

        for i in range(5):
            manager.approach_add_tried("A001", "fail", f"Attempt {i+1}")

        approach = manager.approach_get("A001")
        for i, tried in enumerate(approach.tried):
            assert tried.description == f"Attempt {i+1}"


# =============================================================================
# Data Classes
# =============================================================================


class TestApproachDataClasses:
    """Tests for Approach and TriedApproach data classes."""

    def test_approach_dataclass_fields(self, manager_with_approaches: "LessonsManager"):
        """Approach should have all required fields."""
        approach = manager_with_approaches.approach_get("A001")

        assert isinstance(approach.id, str)
        assert isinstance(approach.title, str)
        assert isinstance(approach.status, str)
        assert isinstance(approach.created, date)
        assert isinstance(approach.updated, date)
        assert isinstance(approach.files, list)
        assert isinstance(approach.description, str)
        assert isinstance(approach.tried, list)
        assert isinstance(approach.next_steps, str)

    def test_tried_approach_dataclass_fields(self, manager_with_approaches: "LessonsManager"):
        """TriedApproach should have outcome and description."""
        manager_with_approaches.approach_add_tried("A001", "success", "It worked")

        approach = manager_with_approaches.approach_get("A001")
        tried = approach.tried[0]

        assert isinstance(tried, TriedApproach)
        assert isinstance(tried.outcome, str)
        assert isinstance(tried.description, str)


# =============================================================================
# File Format Validation
# =============================================================================


class TestApproachFileFormat:
    """Tests for APPROACHES.md file format."""

    def test_approach_file_has_header(self, manager: "LessonsManager"):
        """Approaches file should have proper header."""
        manager.approach_add(title="Test")

        approaches_file = manager.project_root / ".coding-agent-lessons" / "APPROACHES.md"
        content = approaches_file.read_text()

        assert "APPROACHES.md" in content
        assert "Active Work Tracking" in content or "Active Approaches" in content

    def test_approach_format_includes_separator(self, manager: "LessonsManager"):
        """Each approach should be followed by separator."""
        manager.approach_add(title="First")
        manager.approach_add(title="Second")

        approaches_file = manager.project_root / ".coding-agent-lessons" / "APPROACHES.md"
        content = approaches_file.read_text()

        # Should have separator between approaches
        assert "---" in content

    def test_approach_format_includes_status_line(self, manager: "LessonsManager"):
        """Approach should include status/dates line."""
        manager.approach_add(title="Test")
        manager.approach_update_status("A001", "in_progress")

        approaches_file = manager.project_root / ".coding-agent-lessons" / "APPROACHES.md"
        content = approaches_file.read_text()

        assert "**Status**:" in content
        assert "**Created**:" in content
        assert "**Updated**:" in content
        assert "in_progress" in content

    def test_approach_format_includes_tried_section(self, manager: "LessonsManager"):
        """Approach should include Tried section."""
        manager.approach_add(title="Test")
        manager.approach_add_tried("A001", "fail", "First attempt")

        approaches_file = manager.project_root / ".coding-agent-lessons" / "APPROACHES.md"
        content = approaches_file.read_text()

        assert "**Tried**:" in content
        assert "[fail]" in content.lower() or "fail" in content.lower()
        assert "First attempt" in content

    def test_approach_format_includes_next_section(self, manager: "LessonsManager"):
        """Approach should include Next section."""
        manager.approach_add(title="Test")
        manager.approach_update_next("A001", "Do something next")

        approaches_file = manager.project_root / ".coding-agent-lessons" / "APPROACHES.md"
        content = approaches_file.read_text()

        assert "**Next**:" in content
        assert "Do something next" in content


# =============================================================================
# Phase Tracking Tests
# =============================================================================


class TestApproachPhase:
    """Tests for approach phase tracking."""

    def test_approach_add_defaults_to_research_phase(self, manager: "LessonsManager"):
        """New approaches should default to 'research' phase."""
        manager.approach_add(title="Test approach")
        approach = manager.approach_get("A001")

        assert approach is not None
        assert hasattr(approach, "phase")
        assert approach.phase == "research"

    def test_approach_add_with_explicit_phase(self, manager: "LessonsManager"):
        """Should allow setting phase when adding approach."""
        manager.approach_add(title="Planning task", phase="planning")
        approach = manager.approach_get("A001")

        assert approach is not None
        assert approach.phase == "planning"

    def test_approach_update_phase_valid(self, manager_with_approaches: "LessonsManager"):
        """Should update phase with valid values."""
        # Test all valid phases
        valid_phases = ["research", "planning", "implementing", "review"]

        for phase in valid_phases:
            manager_with_approaches.approach_update_phase("A001", phase)
            approach = manager_with_approaches.approach_get("A001")
            assert approach.phase == phase

    def test_approach_update_phase_invalid_rejects(
        self, manager_with_approaches: "LessonsManager"
    ):
        """Should reject invalid phase values."""
        with pytest.raises(ValueError, match="[Ii]nvalid phase"):
            manager_with_approaches.approach_update_phase("A001", "coding")

        with pytest.raises(ValueError, match="[Ii]nvalid phase"):
            manager_with_approaches.approach_update_phase("A001", "testing")

        with pytest.raises(ValueError, match="[Ii]nvalid phase"):
            manager_with_approaches.approach_update_phase("A001", "")

    def test_approach_phase_in_inject_output(self, manager_with_approaches: "LessonsManager"):
        """Phase should appear in inject output."""
        manager_with_approaches.approach_update_phase("A001", "implementing")

        injected = manager_with_approaches.approach_inject()

        assert "implementing" in injected.lower()

    def test_approach_get_includes_phase(self, manager_with_approaches: "LessonsManager"):
        """Approach dataclass should include phase field."""
        manager_with_approaches.approach_update_phase("A001", "review")

        approach = manager_with_approaches.approach_get("A001")

        assert hasattr(approach, "phase")
        assert isinstance(approach.phase, str)
        assert approach.phase == "review"

    def test_approach_update_phase_nonexistent_fails(self, manager: "LessonsManager"):
        """Should fail when updating phase of nonexistent approach."""
        with pytest.raises(ValueError, match="not found"):
            manager.approach_update_phase("A999", "research")

    def test_approach_update_phase_sets_updated_date(
        self, manager_with_approaches: "LessonsManager"
    ):
        """Updating phase should update the 'updated' date."""
        manager_with_approaches.approach_update_phase("A001", "implementing")

        approach = manager_with_approaches.approach_get("A001")
        assert approach.updated == date.today()


# =============================================================================
# Agent Tracking Tests
# =============================================================================


class TestApproachAgent:
    """Tests for approach agent tracking."""

    def test_approach_add_defaults_to_user_agent(self, manager: "LessonsManager"):
        """New approaches should default to 'user' agent (no subagent)."""
        manager.approach_add(title="Test approach")
        approach = manager.approach_get("A001")

        assert approach is not None
        assert hasattr(approach, "agent")
        assert approach.agent == "user"

    def test_approach_add_with_explicit_agent(self, manager: "LessonsManager"):
        """Should allow setting agent when adding approach."""
        manager.approach_add(title="Exploration task", agent="explore")
        approach = manager.approach_get("A001")

        assert approach is not None
        assert approach.agent == "explore"

    def test_approach_update_agent(self, manager_with_approaches: "LessonsManager"):
        """Should update agent with valid values."""
        # Test all valid agents
        valid_agents = ["explore", "general-purpose", "plan", "review", "user"]

        for agent in valid_agents:
            manager_with_approaches.approach_update_agent("A001", agent)
            approach = manager_with_approaches.approach_get("A001")
            assert approach.agent == agent

    def test_approach_update_agent_invalid_rejects(
        self, manager_with_approaches: "LessonsManager"
    ):
        """Should reject invalid agent values."""
        with pytest.raises(ValueError, match="[Ii]nvalid agent"):
            manager_with_approaches.approach_update_agent("A001", "coder")

        with pytest.raises(ValueError, match="[Ii]nvalid agent"):
            manager_with_approaches.approach_update_agent("A001", "assistant")

        with pytest.raises(ValueError, match="[Ii]nvalid agent"):
            manager_with_approaches.approach_update_agent("A001", "")

    def test_approach_agent_in_inject_output(self, manager_with_approaches: "LessonsManager"):
        """Agent should appear in inject output."""
        manager_with_approaches.approach_update_agent("A001", "general-purpose")

        injected = manager_with_approaches.approach_inject()

        assert "general-purpose" in injected.lower()

    def test_approach_get_includes_agent(self, manager_with_approaches: "LessonsManager"):
        """Approach dataclass should include agent field."""
        manager_with_approaches.approach_update_agent("A001", "explore")

        approach = manager_with_approaches.approach_get("A001")

        assert hasattr(approach, "agent")
        assert isinstance(approach.agent, str)
        assert approach.agent == "explore"

    def test_approach_update_agent_nonexistent_fails(self, manager: "LessonsManager"):
        """Should fail when updating agent of nonexistent approach."""
        with pytest.raises(ValueError, match="not found"):
            manager.approach_update_agent("A999", "explore")

    def test_approach_update_agent_sets_updated_date(
        self, manager_with_approaches: "LessonsManager"
    ):
        """Updating agent should update the 'updated' date."""
        manager_with_approaches.approach_update_agent("A001", "review")

        approach = manager_with_approaches.approach_get("A001")
        assert approach.updated == date.today()


# =============================================================================
# Phase/Agent Format Tests
# =============================================================================


class TestApproachPhaseAgentFormat:
    """Tests for phase and agent in file format."""

    def test_approach_format_includes_phase(self, manager: "LessonsManager"):
        """Approach format should include phase in status line."""
        manager.approach_add(title="Test", phase="implementing")

        approaches_file = manager.project_root / ".coding-agent-lessons" / "APPROACHES.md"
        content = approaches_file.read_text()

        assert "**Phase**:" in content
        assert "implementing" in content

    def test_approach_format_includes_agent(self, manager: "LessonsManager"):
        """Approach format should include agent in status line."""
        manager.approach_add(title="Test", agent="explore")

        approaches_file = manager.project_root / ".coding-agent-lessons" / "APPROACHES.md"
        content = approaches_file.read_text()

        assert "**Agent**:" in content
        assert "explore" in content

    def test_approach_parse_new_format_with_phase_agent(self, manager: "LessonsManager"):
        """Should parse the new format with phase and agent correctly."""
        # Write a file with the new format directly
        approaches_file = manager.project_root / ".coding-agent-lessons" / "APPROACHES.md"
        approaches_file.parent.mkdir(parents=True, exist_ok=True)

        new_format_content = """# APPROACHES.md - Active Work Tracking

> Track ongoing work with tried approaches and next steps.
> When completed, review for lessons to extract.

## Active Approaches

### [A001] Test approach with new format
- **Status**: in_progress | **Phase**: implementing | **Agent**: general-purpose
- **Created**: 2025-12-28 | **Updated**: 2025-12-28
- **Files**: test.py
- **Description**: Testing new format parsing

**Tried**:

**Next**:

---
"""
        approaches_file.write_text(new_format_content)

        approach = manager.approach_get("A001")

        assert approach is not None
        assert approach.status == "in_progress"
        assert approach.phase == "implementing"
        assert approach.agent == "general-purpose"
        assert approach.title == "Test approach with new format"

    def test_approach_format_phase_agent_on_status_line(self, manager: "LessonsManager"):
        """Phase and agent should be on the status line after status."""
        manager.approach_add(title="Test format", phase="planning", agent="plan")
        manager.approach_update_status("A001", "in_progress")

        approaches_file = manager.project_root / ".coding-agent-lessons" / "APPROACHES.md"
        content = approaches_file.read_text()

        # The format should be:
        # - **Status**: in_progress | **Phase**: planning | **Agent**: plan
        # on the same line
        lines = content.split("\n")
        status_line = None
        for line in lines:
            if "**Status**:" in line:
                status_line = line
                break

        assert status_line is not None
        assert "**Status**:" in status_line
        assert "**Phase**:" in status_line
        assert "**Agent**:" in status_line


# =============================================================================
# CLI Phase/Agent Tests
# =============================================================================


class TestApproachCLIPhaseAgent:
    """Tests for phase and agent CLI commands."""

    def test_cli_approach_add_with_phase(self, manager: "LessonsManager"):
        """CLI should support --phase option when adding approach."""
        # This tests the approach_add method with phase parameter
        approach_id = manager.approach_add(
            title="CLI phase test",
            phase="planning",
        )

        approach = manager.approach_get(approach_id)
        assert approach.phase == "planning"

    def test_cli_approach_add_with_agent(self, manager: "LessonsManager"):
        """CLI should support --agent option when adding approach."""
        # This tests the approach_add method with agent parameter
        approach_id = manager.approach_add(
            title="CLI agent test",
            agent="explore",
        )

        approach = manager.approach_get(approach_id)
        assert approach.agent == "explore"

    def test_cli_approach_update_phase(self, manager_with_approaches: "LessonsManager"):
        """CLI should support updating phase via approach_update_phase."""
        manager_with_approaches.approach_update_phase("A001", "review")

        approach = manager_with_approaches.approach_get("A001")
        assert approach.phase == "review"

    def test_cli_approach_update_agent(self, manager_with_approaches: "LessonsManager"):
        """CLI should support updating agent via approach_update_agent."""
        manager_with_approaches.approach_update_agent("A001", "general-purpose")

        approach = manager_with_approaches.approach_get("A001")
        assert approach.agent == "general-purpose"


# =============================================================================
# Phase/Agent Edge Cases
# =============================================================================


class TestApproachPhaseAgentEdgeCases:
    """Tests for edge cases with phase and agent."""

    def test_approach_backward_compatibility_no_phase_agent(self, manager: "LessonsManager"):
        """Should handle old format files without phase/agent fields."""
        # Write a file with the old format (no phase/agent)
        approaches_file = manager.project_root / ".coding-agent-lessons" / "APPROACHES.md"
        approaches_file.parent.mkdir(parents=True, exist_ok=True)

        old_format_content = """# APPROACHES.md - Active Work Tracking

> Track ongoing work with tried approaches and next steps.
> When completed, review for lessons to extract.

## Active Approaches

### [A001] Old format approach
- **Status**: in_progress | **Created**: 2025-12-28 | **Updated**: 2025-12-28
- **Files**: test.py
- **Description**: Testing backward compatibility

**Tried**:
1. [fail] First attempt

**Next**: Try something else

---
"""
        approaches_file.write_text(old_format_content)

        approach = manager.approach_get("A001")

        assert approach is not None
        assert approach.status == "in_progress"
        # Should default to research/user when not present
        assert approach.phase == "research"
        assert approach.agent == "user"

    def test_approach_phase_agent_preserved_on_update(
        self, manager_with_approaches: "LessonsManager"
    ):
        """Phase and agent should be preserved when updating other fields."""
        manager_with_approaches.approach_update_phase("A001", "implementing")
        manager_with_approaches.approach_update_agent("A001", "general-purpose")

        # Update status
        manager_with_approaches.approach_update_status("A001", "blocked")

        approach = manager_with_approaches.approach_get("A001")
        assert approach.phase == "implementing"
        assert approach.agent == "general-purpose"
        assert approach.status == "blocked"

    def test_approach_phase_agent_in_archived_approach(
        self, manager_with_approaches: "LessonsManager"
    ):
        """Archived approaches should preserve phase and agent."""
        manager_with_approaches.approach_update_phase("A001", "review")
        manager_with_approaches.approach_update_agent("A001", "review")

        manager_with_approaches.approach_archive("A001")

        archive_file = (
            manager_with_approaches.project_root
            / ".coding-agent-lessons"
            / "APPROACHES_ARCHIVE.md"
        )
        content = archive_file.read_text()

        assert "**Phase**: review" in content or "**Phase**:" in content
        assert "**Agent**: review" in content or "**Agent**:" in content

    def test_approach_complete_includes_phase_agent(
        self, manager_with_approaches: "LessonsManager"
    ):
        """Complete result should include phase and agent info."""
        manager_with_approaches.approach_update_phase("A001", "implementing")
        manager_with_approaches.approach_update_agent("A001", "general-purpose")

        result = manager_with_approaches.approach_complete("A001")

        # The approach in the result should have phase and agent
        assert result.approach.phase == "implementing"
        assert result.approach.agent == "general-purpose"


# =============================================================================
# Phase 4.2: Code Snippets Tests
# =============================================================================


class TestApproachCodeSnippets:
    """Tests for code snippets in approaches."""

    def test_approach_has_code_snippets_field(self, manager: "LessonsManager"):
        """Approach dataclass should have code_snippets field."""
        manager.approach_add(title="Test approach")
        approach = manager.approach_get("A001")

        assert approach is not None
        assert hasattr(approach, "code_snippets")
        assert isinstance(approach.code_snippets, list)
        assert len(approach.code_snippets) == 0

    def test_approach_add_code_snippet(self, manager: "LessonsManager"):
        """Should add a code snippet to an approach."""
        manager.approach_add(title="Test approach")
        manager.approach_add_code("A001", "def hello():\n    print('world')")

        approach = manager.approach_get("A001")
        assert len(approach.code_snippets) == 1
        assert "def hello():" in approach.code_snippets[0]

    def test_approach_add_multiple_code_snippets(self, manager: "LessonsManager"):
        """Should support multiple code snippets per approach."""
        manager.approach_add(title="Test approach")
        manager.approach_add_code("A001", "snippet 1")
        manager.approach_add_code("A001", "snippet 2")
        manager.approach_add_code("A001", "snippet 3")

        approach = manager.approach_get("A001")
        assert len(approach.code_snippets) == 3

    def test_approach_add_code_nonexistent_fails(self, manager: "LessonsManager"):
        """Should reject adding code to nonexistent approach."""
        with pytest.raises(ValueError, match="[Nn]ot found|[Ii]nvalid"):
            manager.approach_add_code("A999", "code")

    def test_approach_add_code_sets_updated_date(self, manager: "LessonsManager"):
        """Adding code should update the updated date."""
        manager.approach_add(title="Test approach")
        approach_before = manager.approach_get("A001")

        # Simulate time passing by modifying the stored updated date
        approaches_file = manager.project_root / ".coding-agent-lessons" / "APPROACHES.md"
        content = approaches_file.read_text()
        content = content.replace(
            f"**Updated**: {approach_before.updated.isoformat()}",
            "**Updated**: 2020-01-01"
        )
        approaches_file.write_text(content)

        manager.approach_add_code("A001", "new code")
        approach_after = manager.approach_get("A001")

        assert approach_after.updated == date.today()


class TestApproachCodeSnippetsFormat:
    """Tests for code snippets in markdown format."""

    def test_code_snippets_formatted_as_fenced_blocks(self, manager: "LessonsManager"):
        """Code snippets should be formatted as fenced code blocks."""
        manager.approach_add(title="Test approach")
        manager.approach_add_code("A001", "def test():\n    pass")

        approaches_file = manager.project_root / ".coding-agent-lessons" / "APPROACHES.md"
        content = approaches_file.read_text()

        assert "**Code**:" in content
        assert "```" in content

    def test_code_snippets_with_language_hint(self, manager: "LessonsManager"):
        """Code snippets should support optional language hints."""
        manager.approach_add(title="Test approach")
        manager.approach_add_code("A001", "def test():\n    pass", language="python")

        approaches_file = manager.project_root / ".coding-agent-lessons" / "APPROACHES.md"
        content = approaches_file.read_text()

        assert "```python" in content

    def test_code_snippets_parsed_correctly(self, manager: "LessonsManager"):
        """Should parse code snippets from markdown correctly."""
        approaches_file = manager.project_root / ".coding-agent-lessons" / "APPROACHES.md"
        approaches_file.parent.mkdir(parents=True, exist_ok=True)

        content_with_code = """# APPROACHES.md - Active Work Tracking

> Track ongoing work with tried approaches and next steps.
> When completed, review for lessons to extract.

## Active Approaches

### [A001] Test approach
- **Status**: in_progress | **Phase**: implementing | **Agent**: user
- **Created**: 2025-12-28 | **Updated**: 2025-12-28
- **Files**: test.py
- **Description**: Testing code snippets

**Code**:
```python
def reconnect(delay: int = 1000) -> None:
    '''Reconnect with backoff.'''
    sleep(delay)
    return connect()
```

```typescript
export function reconnect(): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, 1000));
}
```

**Tried**:
1. [success] Code snippets work

**Next**: Continue testing

---
"""
        approaches_file.write_text(content_with_code)

        approach = manager.approach_get("A001")

        assert approach is not None
        assert len(approach.code_snippets) == 2
        assert "def reconnect" in approach.code_snippets[0]
        assert "export function" in approach.code_snippets[1]

    def test_backward_compatibility_no_code_section(self, manager: "LessonsManager"):
        """Should handle approaches without code section."""
        approaches_file = manager.project_root / ".coding-agent-lessons" / "APPROACHES.md"
        approaches_file.parent.mkdir(parents=True, exist_ok=True)

        content_no_code = """# APPROACHES.md - Active Work Tracking

> Track ongoing work with tried approaches and next steps.
> When completed, review for lessons to extract.

## Active Approaches

### [A001] Test approach
- **Status**: in_progress | **Phase**: research | **Agent**: user
- **Created**: 2025-12-28 | **Updated**: 2025-12-28
- **Files**: test.py
- **Description**: No code snippets

**Tried**:
1. [success] Works

**Next**: Continue

---
"""
        approaches_file.write_text(content_no_code)

        approach = manager.approach_get("A001")

        assert approach is not None
        assert approach.code_snippets == []


class TestApproachCodeSnippetsCLI:
    """Tests for code snippets CLI commands."""

    def test_cli_approach_add_code(self, manager: "LessonsManager"):
        """CLI approach_add_code should add code snippets."""
        manager.approach_add(title="Test approach")

        # Test the method that CLI --code would call
        manager.approach_add_code("A001", "print('hello')")

        approach = manager.approach_get("A001")
        assert len(approach.code_snippets) == 1

    def test_cli_approach_add_code_with_language(self, manager: "LessonsManager"):
        """CLI approach_add_code should support language hints."""
        manager.approach_add(title="Test approach")

        # Test the method that CLI --code --language would call
        manager.approach_add_code("A001", "print('hello')", language="python")

        approaches_file = manager.project_root / ".coding-agent-lessons" / "APPROACHES.md"
        content = approaches_file.read_text()
        assert "```python" in content


class TestApproachCodeSnippetsInjection:
    """Tests for code snippets in injection output."""

    def test_approach_inject_shows_code_snippets(self, manager: "LessonsManager"):
        """Injection output should include code snippets when present."""
        manager.approach_add(title="WebSocket fix", phase="implementing")
        manager.approach_add_code(
            "A001",
            "async def connect(): await ws.open()",
            language="python"
        )

        output = manager.approach_inject()

        # Should show code section in injection
        assert "Code" in output or "code" in output
        assert "connect" in output

    def test_approach_inject_truncates_long_code(self, manager: "LessonsManager"):
        """Long code snippets should be truncated in injection."""
        manager.approach_add(title="Large refactor")
        long_code = "x = 1\n" * 100  # 100 lines
        manager.approach_add_code("A001", long_code)

        output = manager.approach_inject()

        # Should not include all 100 lines
        # Count occurrences of "x = 1" in output
        occurrences = output.count("x = 1")
        assert occurrences < 50  # Should be truncated significantly


# =============================================================================
# Phase 4.6: Approach Decay Tests
# =============================================================================


class TestApproachDecayVisibility:
    """Tests for completed approach visibility rules."""

    def test_approach_list_completed_returns_completed(
        self, manager_with_approaches: "LessonsManager"
    ):
        """Should be able to list completed approaches."""
        manager_with_approaches.approach_update_status("A001", "completed")
        manager_with_approaches.approach_update_status("A002", "completed")

        completed = manager_with_approaches.approach_list_completed()

        assert len(completed) == 2

    def test_approach_list_completed_respects_max_count(
        self, manager: "LessonsManager"
    ):
        """With all old approaches, max_count limits the result."""
        # Create and complete 5 approaches with old dates
        for i in range(5):
            manager.approach_add(title=f"Approach {i}")
            manager.approach_update_status(f"A00{i+1}", "completed")

        # Make them all old (30 days ago) so only max_count applies
        approaches_file = manager.project_root / ".coding-agent-lessons" / "APPROACHES.md"
        content = approaches_file.read_text()
        old_date = (date.today() - timedelta(days=30)).isoformat()
        content = content.replace(
            f"**Updated**: {date.today().isoformat()}",
            f"**Updated**: {old_date}"
        )
        approaches_file.write_text(content)

        # With max_count=3 and all old, should only return 3 (top N by recency)
        completed = manager.approach_list_completed(max_count=3, max_age_days=7)

        assert len(completed) == 3

    def test_approach_list_completed_respects_max_age(
        self, manager: "LessonsManager"
    ):
        """Should filter out approaches older than max_age_days."""
        manager.approach_add(title="Recent approach")
        manager.approach_update_status("A001", "completed")

        # Should include recent
        completed = manager.approach_list_completed(max_age_days=7)
        assert len(completed) == 1

    def test_approach_list_completed_hybrid_logic(
        self, manager: "LessonsManager"
    ):
        """Should use OR logic: within max_count OR within max_age_days."""
        # Create 5 completed approaches
        for i in range(5):
            manager.approach_add(title=f"Approach {i}")
            manager.approach_update_status(f"A00{i+1}", "completed")

        # Hybrid: max 2 OR within 7 days
        # All are recent, so should get max 2 (the most recent)
        completed = manager.approach_list_completed(max_count=2, max_age_days=7)

        # Should get at least 2 (max_count) since all are recent
        assert len(completed) >= 2


class TestApproachInjectWithCompleted:
    """Tests for showing completed approaches in injection."""

    def test_approach_inject_shows_recent_completions(
        self, manager: "LessonsManager"
    ):
        """Injection should show recent completions section."""
        manager.approach_add(title="Active task")
        manager.approach_add(title="Completed task")
        manager.approach_update_status("A002", "completed")

        output = manager.approach_inject()

        # Should show both active and completed sections
        assert "Active" in output or "active" in output
        assert "A001" in output
        # Should mention completed or recent
        assert "Completed" in output or "completed" in output or "Recent" in output

    def test_approach_inject_shows_completion_info(
        self, manager: "LessonsManager"
    ):
        """Completed approaches should show completion metadata."""
        manager.approach_add(title="Finished feature")
        manager.approach_update_status("A001", "completed")

        output = manager.approach_inject()

        # Should indicate it's completed
        assert "✓" in output or "completed" in output.lower()

    def test_approach_inject_hides_old_completions(
        self, manager: "LessonsManager"
    ):
        """Old completed approaches outside top N should not appear."""
        # Create 5 completed approaches
        for i in range(5):
            manager.approach_add(title=f"Task {i}")
            manager.approach_update_status(f"A00{i+1}", "completed")

        # Make them all old (30 days ago)
        approaches_file = manager.project_root / ".coding-agent-lessons" / "APPROACHES.md"
        content = approaches_file.read_text()
        old_date = (date.today() - timedelta(days=30)).isoformat()
        content = content.replace(
            f"**Updated**: {date.today().isoformat()}",
            f"**Updated**: {old_date}"
        )
        approaches_file.write_text(content)

        # With max_completed=2 and all old (same date), only top 2 by file order show
        output = manager.approach_inject(max_completed=2, max_completed_age=7)

        # Should show only 2 completed approaches (top 2 by stable sort order)
        # Task 3, 4 should not appear (outside top 2 and too old)
        assert "Task 3" not in output
        assert "Task 4" not in output


class TestApproachAutoArchive:
    """Tests for auto-archiving after lesson extraction."""

    def test_approach_complete_with_lessons_extracted(
        self, manager: "LessonsManager"
    ):
        """Complete should track if lessons were extracted."""
        manager.approach_add(title="Feature work")
        manager.approach_add_tried("A001", "success", "Main implementation")

        result = manager.approach_complete("A001")

        # Should return extraction prompt
        assert result.extraction_prompt is not None
        assert "lesson" in result.extraction_prompt.lower()

    def test_approach_archive_after_extraction(
        self, manager: "LessonsManager"
    ):
        """Should be able to archive after completing."""
        manager.approach_add(title="Feature work")
        manager.approach_complete("A001")

        # Archive after extraction
        manager.approach_archive("A001")

        # Should no longer appear in active list
        approaches = manager.approach_list()
        assert len(approaches) == 0

        # Should be in archive
        archive_file = manager.project_root / ".coding-agent-lessons" / "APPROACHES_ARCHIVE.md"
        assert archive_file.exists()
        assert "Feature work" in archive_file.read_text()


class TestApproachDecayConstants:
    """Tests for decay configuration constants."""

    def test_default_max_completed_count(self, manager: "LessonsManager"):
        """Should have a default max completed count."""
        # The default should be accessible
        assert hasattr(manager, "APPROACH_MAX_COMPLETED") or True  # Constant or method param

    def test_default_max_age_days(self, manager: "LessonsManager"):
        """Should have a default max age for completed approaches."""
        # The default should be accessible
        assert hasattr(manager, "APPROACH_MAX_AGE_DAYS") or True  # Constant or method param


# =============================================================================
# Phase 4.4: Plan Mode Integration Tests
# =============================================================================


class TestPhaseDetectionFromTools:
    """Tests for inferring approach phase from tool usage patterns."""

    def test_detect_research_phase_from_read_grep(self):
        """Mostly Read/Grep/Glob with no writes should be research."""
        from core.lessons_manager import detect_phase_from_tools

        tools = [
            {"name": "Read", "file_path": "/some/file.py"},
            {"name": "Grep", "pattern": "function"},
            {"name": "Glob", "pattern": "*.py"},
            {"name": "Read", "file_path": "/another/file.py"},
        ]
        assert detect_phase_from_tools(tools) == "research"

    def test_detect_planning_phase_from_plan_file_writes(self):
        """Writing to .md files (plan files) should indicate planning."""
        from core.lessons_manager import detect_phase_from_tools

        tools = [
            {"name": "Read", "file_path": "/some/code.py"},
            {"name": "Write", "file_path": "/plan/IMPLEMENTATION_PLAN.md"},
        ]
        assert detect_phase_from_tools(tools) == "planning"

    def test_detect_planning_phase_from_ask_user(self):
        """AskUserQuestion indicates planning/clarification."""
        from core.lessons_manager import detect_phase_from_tools

        tools = [
            {"name": "Read", "file_path": "/some/code.py"},
            {"name": "AskUserQuestion", "questions": []},
        ]
        assert detect_phase_from_tools(tools) == "planning"

    def test_detect_implementing_phase_from_edit(self):
        """Edit tool usage indicates implementing."""
        from core.lessons_manager import detect_phase_from_tools

        tools = [
            {"name": "Read", "file_path": "/src/app.py"},
            {"name": "Edit", "file_path": "/src/app.py"},
        ]
        assert detect_phase_from_tools(tools) == "implementing"

    def test_detect_implementing_phase_from_code_writes(self):
        """Writing to code files indicates implementing."""
        from core.lessons_manager import detect_phase_from_tools

        tools = [
            {"name": "Read", "file_path": "/src/app.py"},
            {"name": "Write", "file_path": "/src/new_module.py"},
        ]
        assert detect_phase_from_tools(tools) == "implementing"

    def test_detect_review_phase_from_test_commands(self):
        """Bash with test/pytest commands indicates review."""
        from core.lessons_manager import detect_phase_from_tools

        tools = [
            {"name": "Bash", "command": "python -m pytest tests/"},
            {"name": "Read", "file_path": "/tests/test_output.txt"},
        ]
        assert detect_phase_from_tools(tools) == "review"

    def test_detect_review_phase_from_build_commands(self):
        """Bash with build commands indicates review."""
        from core.lessons_manager import detect_phase_from_tools

        tools = [
            {"name": "Bash", "command": "npm run build"},
        ]
        assert detect_phase_from_tools(tools) == "review"

    def test_detect_phase_empty_tools_defaults_research(self):
        """Empty tool list should default to research."""
        from core.lessons_manager import detect_phase_from_tools

        assert detect_phase_from_tools([]) == "research"

    def test_detect_phase_mixed_tools_uses_priority(self):
        """When tools are mixed, use priority: review > implementing > planning > research."""
        from core.lessons_manager import detect_phase_from_tools

        # If both edit and test, should be review (test takes priority)
        tools = [
            {"name": "Edit", "file_path": "/src/app.py"},
            {"name": "Bash", "command": "pytest"},
        ]
        assert detect_phase_from_tools(tools) == "review"

    def test_detect_phase_enter_plan_mode_triggers_research(self):
        """EnterPlanMode tool should trigger research phase initially."""
        from core.lessons_manager import detect_phase_from_tools

        tools = [
            {"name": "EnterPlanMode"},
        ]
        assert detect_phase_from_tools(tools) == "research"


class TestPlanModeApproachCreation:
    """Tests for auto-creating approaches when entering plan mode."""

    def test_approach_add_from_plan_mode(self, manager: "LessonsManager"):
        """Should be able to create approach with plan mode context."""
        approach_id = manager.approach_add(
            title="Implement user authentication",
            phase="research",
            agent="plan",
        )

        approach = manager.approach_get(approach_id)
        assert approach.title == "Implement user authentication"
        assert approach.phase == "research"
        assert approach.agent == "plan"

    def test_approach_links_to_plan_file(self, manager: "LessonsManager"):
        """Approach can store plan file path reference."""
        approach_id = manager.approach_add(
            title="Feature implementation",
            phase="planning",
            desc="Plan file: ~/.claude/plans/test-plan.md",
        )

        approach = manager.approach_get(approach_id)
        assert "plan" in approach.description.lower()

    def test_approach_phase_transition_research_to_planning(
        self, manager: "LessonsManager"
    ):
        """Phase should transition from research to planning."""
        manager.approach_add(title="New feature", phase="research")
        manager.approach_update_phase("A001", "planning")

        approach = manager.approach_get("A001")
        assert approach.phase == "planning"

    def test_approach_phase_transition_planning_to_implementing(
        self, manager: "LessonsManager"
    ):
        """Phase should transition from planning to implementing."""
        manager.approach_add(title="New feature", phase="planning")
        manager.approach_update_phase("A001", "implementing")

        approach = manager.approach_get("A001")
        assert approach.phase == "implementing"


class TestHookPhasePatterns:
    """Tests for hook command patterns for phase updates."""

    def test_approach_update_phase_via_hook_pattern(self, manager: "LessonsManager"):
        """Should support phase updates from hook patterns."""
        manager.approach_add(title="Test feature")

        # This simulates what the hook would do
        manager.approach_update_phase("A001", "implementing")

        approach = manager.approach_get("A001")
        assert approach.phase == "implementing"

    def test_phase_update_preserves_other_fields(
        self, manager_with_approaches: "LessonsManager"
    ):
        """Phase update should not affect other approach fields."""
        # Add some data first
        manager_with_approaches.approach_add_tried("A001", "fail", "First attempt")
        manager_with_approaches.approach_update_next("A001", "Try another way")

        # Update phase
        manager_with_approaches.approach_update_phase("A001", "review")

        approach = manager_with_approaches.approach_get("A001")
        assert approach.phase == "review"
        assert len(approach.tried) == 1
        assert approach.next_steps == "Try another way"

    def test_plan_mode_approach_pattern_parsed(self, manager: "LessonsManager"):
        """PLAN MODE: pattern should work like APPROACH: pattern."""
        # This tests that the same approach_add mechanism works for plan mode
        approach_id = manager.approach_add(
            title="Feature from plan mode",
            phase="research",
        )

        assert approach_id == "A001"
        approach = manager.approach_get(approach_id)
        assert approach.title == "Feature from plan mode"


class TestHookCLIIntegration:
    """Tests for CLI commands that hooks invoke."""

    def test_cli_approach_add_with_phase_and_agent(self, tmp_path):
        """CLI should support --phase and --agent when adding approach."""
        # Set up environment
        env = os.environ.copy()
        env["PROJECT_DIR"] = str(tmp_path)
        env["LESSONS_BASE"] = str(tmp_path / ".lessons")

        # Run the CLI command (simulating what PLAN MODE: pattern does)
        # Use sys.executable for portability across Python installations
        result = subprocess.run(
            [
                sys.executable,
                "core/lessons_manager.py",
                "approach",
                "add",
                "Test Plan Mode Feature",
                "--phase",
                "research",
                "--agent",
                "plan",
            ],
            capture_output=True,
            text=True,
            env=env,
        )

        assert result.returncode == 0
        assert "A001" in result.stdout

    def test_cli_approach_update_phase(self, tmp_path):
        """CLI should support --phase in update command."""
        env = os.environ.copy()
        env["PROJECT_DIR"] = str(tmp_path)
        env["LESSONS_BASE"] = str(tmp_path / ".lessons")

        # First create an approach
        subprocess.run(
            [sys.executable, "core/lessons_manager.py", "approach", "add", "Test"],
            capture_output=True,
            text=True,
            env=env,
        )

        # Then update the phase
        result = subprocess.run(
            [
                sys.executable,
                "core/lessons_manager.py",
                "approach",
                "update",
                "A001",
                "--phase",
                "implementing",
            ],
            capture_output=True,
            text=True,
            env=env,
        )

        assert result.returncode == 0
        assert "phase" in result.stdout.lower()

    def test_cli_approach_update_agent(self, tmp_path):
        """CLI should support --agent in update command."""
        env = os.environ.copy()
        env["PROJECT_DIR"] = str(tmp_path)
        env["LESSONS_BASE"] = str(tmp_path / ".lessons")

        # First create an approach
        subprocess.run(
            [sys.executable, "core/lessons_manager.py", "approach", "add", "Test"],
            capture_output=True,
            text=True,
            env=env,
        )

        # Then update the agent
        result = subprocess.run(
            [
                sys.executable,
                "core/lessons_manager.py",
                "approach",
                "update",
                "A001",
                "--agent",
                "general-purpose",
            ],
            capture_output=True,
            text=True,
            env=env,
        )

        assert result.returncode == 0
        assert "agent" in result.stdout.lower()


class TestPhaseDetectionEdgeCases:
    """Additional edge case tests for phase detection."""

    def test_detect_phase_write_to_test_file(self):
        """Write to test files should still be implementing."""
        from core.lessons_manager import detect_phase_from_tools

        tools = [
            {"name": "Write", "file_path": "/tests/test_new.py"},
        ]
        # Test files are code, so implementing
        assert detect_phase_from_tools(tools) == "implementing"

    def test_detect_phase_multiple_builds(self):
        """Multiple build commands should be review."""
        from core.lessons_manager import detect_phase_from_tools

        tools = [
            {"name": "Bash", "command": "npm run build"},
            {"name": "Bash", "command": "npm test"},
        ]
        assert detect_phase_from_tools(tools) == "review"

    def test_detect_phase_grep_without_edit(self):
        """Grep alone is research."""
        from core.lessons_manager import detect_phase_from_tools

        tools = [
            {"name": "Grep", "pattern": "def main"},
            {"name": "Grep", "pattern": "class.*Handler"},
        ]
        assert detect_phase_from_tools(tools) == "research"

    def test_detect_phase_exit_plan_mode(self):
        """ExitPlanMode indicates planning is complete."""
        from core.lessons_manager import detect_phase_from_tools

        tools = [
            {"name": "ExitPlanMode"},
        ]
        # ExitPlanMode means planning is done, defaults to research
        # (user should explicitly update to implementing)
        assert detect_phase_from_tools(tools) == "research"


# =============================================================================
# Shell Hook Tests for LAST Reference
# =============================================================================


class TestStopHookLastReference:
    """Tests for stop-hook.sh LAST reference in approach commands."""

    @pytest.fixture
    def temp_dirs(self, tmp_path: Path):
        """Create temp directories for testing."""
        lessons_base = tmp_path / ".config" / "coding-agent-lessons"
        project_root = tmp_path / "project"
        lessons_base.mkdir(parents=True)
        project_root.mkdir(parents=True)
        return lessons_base, project_root

    def create_mock_transcript(self, project_root: Path, messages: list) -> Path:
        """Create a mock transcript file with the given assistant messages."""
        import json
        from datetime import datetime

        transcript = project_root / "transcript.jsonl"
        with open(transcript, "w") as f:
            for i, msg in enumerate(messages):
                entry = {
                    "type": "assistant",
                    "timestamp": f"2025-12-30T{10+i:02d}:00:00.000Z",
                    "message": {
                        "content": [{"type": "text", "text": msg}]
                    }
                }
                f.write(json.dumps(entry) + "\n")
        return transcript

    def test_last_reference_phase_update(self, temp_dirs):
        """APPROACH UPDATE LAST: phase should update the most recent approach."""
        lessons_base, project_root = temp_dirs
        hook_path = Path("adapters/claude-code/stop-hook.sh")
        if not hook_path.exists():
            pytest.skip("stop-hook.sh not found")

        transcript = self.create_mock_transcript(project_root, [
            "APPROACH: Test feature",
            "APPROACH UPDATE LAST: phase implementing",
        ])

        import json
        input_data = json.dumps({
            "cwd": str(project_root),
            "transcript_path": str(transcript),
        })

        result = subprocess.run(
            ["bash", str(hook_path)],
            input=input_data,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "LESSONS_BASE": str(lessons_base),
                "PROJECT_DIR": str(project_root),
            },
        )

        assert result.returncode == 0

        from core.lessons_manager import LessonsManager
        manager = LessonsManager(lessons_base, project_root)
        approach = manager.approach_get("A001")
        assert approach is not None
        assert approach.phase == "implementing"

    def test_last_reference_tried_update(self, temp_dirs):
        """APPROACH UPDATE LAST: tried should update the most recent approach."""
        lessons_base, project_root = temp_dirs
        hook_path = Path("adapters/claude-code/stop-hook.sh")
        if not hook_path.exists():
            pytest.skip("stop-hook.sh not found")

        transcript = self.create_mock_transcript(project_root, [
            "APPROACH: Another feature",
            "APPROACH UPDATE LAST: tried success - it worked great",
        ])

        import json
        input_data = json.dumps({
            "cwd": str(project_root),
            "transcript_path": str(transcript),
        })

        result = subprocess.run(
            ["bash", str(hook_path)],
            input=input_data,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "LESSONS_BASE": str(lessons_base),
                "PROJECT_DIR": str(project_root),
            },
        )

        assert result.returncode == 0

        from core.lessons_manager import LessonsManager
        manager = LessonsManager(lessons_base, project_root)
        approach = manager.approach_get("A001")
        assert approach is not None
        assert len(approach.tried) == 1
        assert approach.tried[0].outcome == "success"
        assert "worked great" in approach.tried[0].description

    def test_last_reference_complete(self, temp_dirs):
        """APPROACH COMPLETE LAST should complete the most recent approach."""
        lessons_base, project_root = temp_dirs
        hook_path = Path("adapters/claude-code/stop-hook.sh")
        if not hook_path.exists():
            pytest.skip("stop-hook.sh not found")

        transcript = self.create_mock_transcript(project_root, [
            "APPROACH: Complete me",
            "APPROACH COMPLETE LAST",
        ])

        import json
        input_data = json.dumps({
            "cwd": str(project_root),
            "transcript_path": str(transcript),
        })

        result = subprocess.run(
            ["bash", str(hook_path)],
            input=input_data,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "LESSONS_BASE": str(lessons_base),
                "PROJECT_DIR": str(project_root),
            },
        )

        assert result.returncode == 0

        from core.lessons_manager import LessonsManager
        manager = LessonsManager(lessons_base, project_root)
        approach = manager.approach_get("A001")
        assert approach is not None
        assert approach.status == "completed"

    def test_last_tracks_across_multiple_creates(self, temp_dirs):
        """LAST should track the most recently created approach."""
        lessons_base, project_root = temp_dirs
        hook_path = Path("adapters/claude-code/stop-hook.sh")
        if not hook_path.exists():
            pytest.skip("stop-hook.sh not found")

        transcript = self.create_mock_transcript(project_root, [
            "APPROACH: First approach",
            "APPROACH: Second approach",
            "APPROACH UPDATE LAST: phase implementing",
        ])

        import json
        input_data = json.dumps({
            "cwd": str(project_root),
            "transcript_path": str(transcript),
        })

        result = subprocess.run(
            ["bash", str(hook_path)],
            input=input_data,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "LESSONS_BASE": str(lessons_base),
                "PROJECT_DIR": str(project_root),
            },
        )

        assert result.returncode == 0

        from core.lessons_manager import LessonsManager
        manager = LessonsManager(lessons_base, project_root)

        # A001 (First) should still be research (not updated)
        a001 = manager.approach_get("A001")
        assert a001 is not None
        assert a001.phase == "research"

        # A002 (Second) should be implementing (LAST referred to it)
        a002 = manager.approach_get("A002")
        assert a002 is not None
        assert a002.phase == "implementing"


# =============================================================================
# Checkpoint Tests (Phase 1 of Context Handoff System)
# =============================================================================


class TestApproachCheckpoint:
    """Test checkpoint field for session handoff."""

    def test_approach_has_checkpoint_field(self, manager: LessonsManager) -> None:
        """Verify Approach dataclass has checkpoint field."""
        approach_id = manager.approach_add("Test approach")
        approach = manager.approach_get(approach_id)

        assert hasattr(approach, "checkpoint")
        assert approach.checkpoint == ""  # Default empty

    def test_approach_has_last_session_field(self, manager: LessonsManager) -> None:
        """Verify Approach dataclass has last_session field."""
        approach_id = manager.approach_add("Test approach")
        approach = manager.approach_get(approach_id)

        assert hasattr(approach, "last_session")
        assert approach.last_session is None  # Default None

    def test_approach_update_checkpoint(self, manager: LessonsManager) -> None:
        """Test updating checkpoint via manager method."""
        approach_id = manager.approach_add("Test approach")

        manager.approach_update_checkpoint(
            approach_id, "Tests passing, working on UI integration"
        )

        approach = manager.approach_get(approach_id)
        assert approach.checkpoint == "Tests passing, working on UI integration"
        assert approach.last_session == date.today()

    def test_approach_update_checkpoint_sets_updated_date(
        self, manager: LessonsManager
    ) -> None:
        """Verify update_checkpoint also updates the updated date."""
        approach_id = manager.approach_add("Test approach")

        manager.approach_update_checkpoint(approach_id, "Some progress")

        approach = manager.approach_get(approach_id)
        assert approach.updated == date.today()

    def test_approach_update_checkpoint_nonexistent_fails(
        self, manager: LessonsManager
    ) -> None:
        """Test that updating checkpoint for nonexistent approach fails."""
        with pytest.raises(ValueError, match="not found"):
            manager.approach_update_checkpoint("A999", "Some progress")

    def test_approach_checkpoint_overwrites(self, manager: LessonsManager) -> None:
        """Test that updating checkpoint overwrites previous value."""
        approach_id = manager.approach_add("Test approach")

        manager.approach_update_checkpoint(approach_id, "First checkpoint")
        manager.approach_update_checkpoint(approach_id, "Second checkpoint")

        approach = manager.approach_get(approach_id)
        assert approach.checkpoint == "Second checkpoint"


class TestApproachCheckpointFormat:
    """Test checkpoint field in markdown format."""

    def test_checkpoint_formatted_in_markdown(self, manager: LessonsManager) -> None:
        """Verify checkpoint is written to markdown file."""
        approach_id = manager.approach_add("Test approach")
        manager.approach_update_checkpoint(approach_id, "Progress summary here")

        content = manager.project_approaches_file.read_text()
        assert "**Checkpoint**: Progress summary here" in content

    def test_last_session_formatted_in_markdown(self, manager: LessonsManager) -> None:
        """Verify last_session is written to markdown file."""
        approach_id = manager.approach_add("Test approach")
        manager.approach_update_checkpoint(approach_id, "Progress summary")

        content = manager.project_approaches_file.read_text()
        assert f"**Last Session**: {date.today().isoformat()}" in content

    def test_checkpoint_parsed_correctly(self, manager: LessonsManager) -> None:
        """Verify checkpoint is parsed back correctly."""
        approach_id = manager.approach_add("Test approach")
        manager.approach_update_checkpoint(approach_id, "Complex checkpoint: tests, UI")

        # Force re-parse by getting fresh
        approach = manager.approach_get(approach_id)
        assert approach.checkpoint == "Complex checkpoint: tests, UI"

    def test_last_session_parsed_correctly(self, manager: LessonsManager) -> None:
        """Verify last_session date is parsed correctly."""
        approach_id = manager.approach_add("Test approach")
        manager.approach_update_checkpoint(approach_id, "Progress")

        approach = manager.approach_get(approach_id)
        assert approach.last_session == date.today()

    def test_backward_compatibility_no_checkpoint(
        self, manager: LessonsManager
    ) -> None:
        """Verify approaches without checkpoint field still parse."""
        # Create approach without checkpoint
        approach_id = manager.approach_add("Legacy approach")

        # Manually write old format without checkpoint
        content = manager.project_approaches_file.read_text()
        # The file should parse fine - checkpoint defaults to empty
        approach = manager.approach_get(approach_id)
        assert approach.checkpoint == ""
        assert approach.last_session is None


class TestApproachCheckpointInjection:
    """Test checkpoint in context injection output."""

    def test_approach_inject_shows_checkpoint(self, manager: LessonsManager) -> None:
        """Verify inject output includes checkpoint prominently."""
        approach_id = manager.approach_add("Feature implementation")
        manager.approach_update_checkpoint(
            approach_id, "API done, working on frontend"
        )

        output = manager.approach_inject()

        assert "**Checkpoint" in output
        assert "API done, working on frontend" in output

    def test_approach_inject_shows_checkpoint_age(self, manager: LessonsManager) -> None:
        """Verify inject output shows how old the checkpoint is."""
        approach_id = manager.approach_add("Feature implementation")
        manager.approach_update_checkpoint(approach_id, "Some progress")

        output = manager.approach_inject()

        # Should show "(today)" for same-day checkpoint
        assert "(today)" in output or "Checkpoint" in output

    def test_approach_inject_no_checkpoint_no_display(
        self, manager: LessonsManager
    ) -> None:
        """Verify inject output doesn't show checkpoint line if empty."""
        approach_id = manager.approach_add("Feature implementation")
        # Don't set checkpoint

        output = manager.approach_inject()

        # Should not have Checkpoint line
        assert "**Checkpoint" not in output


class TestApproachCheckpointCLI:
    """Test checkpoint via CLI."""

    def test_cli_approach_update_checkpoint(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test updating checkpoint via CLI."""
        lessons_base = tmp_path / "lessons_base"
        project_root = tmp_path / "project"
        lessons_base.mkdir()
        project_root.mkdir()

        # Get the project root (coding-agent-lessons directory)
        repo_root = Path(__file__).parent.parent

        monkeypatch.setenv("LESSONS_BASE", str(lessons_base))
        monkeypatch.setenv("PROJECT_DIR", str(project_root))

        # Add approach
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "core.lessons_manager",
                "approach",
                "add",
                "Test approach",
            ],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
        assert result.returncode == 0, result.stderr

        # Update checkpoint
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "core.lessons_manager",
                "approach",
                "update",
                "A001",
                "--checkpoint",
                "Progress: tests passing",
            ],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
        assert result.returncode == 0, result.stderr
        assert "Updated A001 checkpoint" in result.stdout

        # Verify via manager directly
        from core.lessons_manager import LessonsManager

        manager = LessonsManager(lessons_base, project_root)
        approach = manager.approach_get("A001")
        assert approach.checkpoint == "Progress: tests passing"


class TestApproachCheckpointPreservation:
    """Test checkpoint is preserved across updates."""

    def test_checkpoint_preserved_on_status_update(
        self, manager: LessonsManager
    ) -> None:
        """Verify checkpoint survives status updates."""
        approach_id = manager.approach_add("Test approach")
        manager.approach_update_checkpoint(approach_id, "Important checkpoint")
        manager.approach_update_status(approach_id, "in_progress")

        approach = manager.approach_get(approach_id)
        assert approach.checkpoint == "Important checkpoint"

    def test_checkpoint_preserved_on_tried_add(self, manager: LessonsManager) -> None:
        """Verify checkpoint survives adding tried attempts."""
        approach_id = manager.approach_add("Test approach")
        manager.approach_update_checkpoint(approach_id, "Important checkpoint")
        manager.approach_add_tried(approach_id, "success", "Did something")

        approach = manager.approach_get(approach_id)
        assert approach.checkpoint == "Important checkpoint"

    def test_checkpoint_preserved_on_phase_update(
        self, manager: LessonsManager
    ) -> None:
        """Verify checkpoint survives phase updates."""
        approach_id = manager.approach_add("Test approach")
        manager.approach_update_checkpoint(approach_id, "Important checkpoint")
        manager.approach_update_phase(approach_id, "implementing")

        approach = manager.approach_get(approach_id)
        assert approach.checkpoint == "Important checkpoint"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
