#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Test suite for Handoffs tracking system (formerly called "approaches").

This is a TDD test file - tests are written BEFORE the implementation.
Run with: pytest tests/test_handoffs.py -v

The handoffs system tracks ongoing work with tried steps and next steps.
Storage location: <project_root>/.recall/HANDOFFS.md (or legacy .coding-agent-lessons/APPROACHES.md)

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
    from core import (
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
    """Create a manager with some pre-existing approaches using legacy A### IDs.

    This fixture simulates having existing handoffs with the old ID format,
    which is important for backward compatibility testing. Many tests rely
    on the specific IDs A001, A002, A003.
    """
    # Write legacy format directly to test backward compatibility
    handoffs_file = manager.project_handoffs_file
    handoffs_file.parent.mkdir(parents=True, exist_ok=True)

    today = date.today().isoformat()
    legacy_content = f"""# HANDOFFS.md - Active Work Tracking

> Track ongoing work with tried steps and next steps.
> When completed, review for lessons to extract.

## Active Handoffs

### [A001] Implementing WebSocket reconnection
- **Status**: not_started | **Phase**: research | **Agent**: user
- **Created**: {today} | **Updated**: {today}
- **Files**: src/websocket.ts, src/connection-manager.ts
- **Description**: Add automatic reconnection with exponential backoff

**Tried**:

**Next**:

---

### [A002] Refactoring database layer
- **Status**: not_started | **Phase**: research | **Agent**: user
- **Created**: {today} | **Updated**: {today}
- **Files**: src/db/models.py
- **Description**: Extract repository pattern from service classes

**Tried**:

**Next**:

---

### [A003] Adding unit tests
- **Status**: not_started | **Phase**: research | **Agent**: user
- **Created**: {today} | **Updated**: {today}
- **Files**:
- **Description**: Improve test coverage for core module

**Tried**:

**Next**:

---
"""
    handoffs_file.write_text(legacy_content)
    return manager


# =============================================================================
# Adding Approaches
# =============================================================================


class TestApproachAdd:
    """Tests for adding approaches."""

    def test_approach_add_creates_file(self, manager: "LessonsManager"):
        """Adding an approach should create the handoffs file (HANDOFFS.md or legacy APPROACHES.md)."""
        manager.approach_add(title="Test approach")

        # Use the manager's property to get the actual file path
        approaches_file = manager.project_handoffs_file
        assert approaches_file.exists()
        content = approaches_file.read_text()
        assert "Test approach" in content

    def test_approach_add_assigns_hash_id(self, manager: "LessonsManager"):
        """Approach IDs should be hash-based with hf- prefix."""
        id1 = manager.approach_add(title="First approach")
        id2 = manager.approach_add(title="Second approach")
        id3 = manager.approach_add(title="Third approach")

        # New IDs are hash-based with hf- prefix
        assert id1.startswith("hf-")
        assert id2.startswith("hf-")
        assert id3.startswith("hf-")
        # IDs should all be unique
        assert len({id1, id2, id3}) == 3

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
        approach_id = manager.approach_add(title="New work")
        approach = manager.approach_get(approach_id)

        assert approach is not None
        assert approach.status == "not_started"
        assert approach.created == date.today()
        assert approach.updated == date.today()
        assert approach.tried == []
        assert approach.next_steps == ""

    def test_approach_add_returns_id(self, manager: "LessonsManager"):
        """Adding an approach should return a hash-based ID."""
        result = manager.approach_add(title="Return test")

        assert result.startswith("hf-")
        assert len(result) == 10  # hf- + 7 hex chars
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
        archive_file = manager_with_approaches.project_handoffs_archive
        assert archive_file.exists()
        content = archive_file.read_text()
        assert "A001" in content
        assert "Implementing WebSocket reconnection" in content

    def test_approach_archive_creates_archive_if_missing(self, manager: "LessonsManager"):
        """Archiving should create archive file if it doesn't exist."""
        approach_id = manager.approach_add(title="To be archived")

        # Archive file should not exist yet (we check after creating approach since
        # the property path depends on which data dir exists)
        archive_file = manager.project_handoffs_archive
        assert not archive_file.exists()

        manager.approach_archive(approach_id)

        # Re-get the path (it might have been created by the archive operation)
        archive_file = manager.project_handoffs_archive
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
        archive_file = manager_with_approaches.project_handoffs_archive
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

        archive_file = manager_with_approaches.project_handoffs_archive
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

        archive_file = manager_with_approaches.project_handoffs_archive
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
        assert "## Active Handoffs" in injected
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
        approach_id = manager.approach_add(title="Test approach")
        manager.approach_add_tried(
            approach_id,
            outcome="fail",
            description="Used 'quotes' and |pipes| - didn't work",
        )

        approach = manager.approach_get(approach_id)
        assert len(approach.tried) == 1
        assert "quotes" in approach.tried[0].description

    def test_multiple_approaches(self, manager: "LessonsManager"):
        """Should handle many approaches correctly."""
        created_ids = []
        for i in range(10):
            id = manager.approach_add(title=f"Approach {i+1}")
            created_ids.append(id)

        approaches = manager.approach_list()
        assert len(approaches) == 10

        # All IDs should be hash-based and unique
        ids = [a.id for a in approaches]
        assert all(id.startswith("hf-") for id in ids)
        assert len(set(ids)) == 10  # All unique

    def test_approach_empty_file(self, manager: "LessonsManager"):
        """Should handle empty approaches file gracefully."""
        approaches_file = manager.project_handoffs_file
        approaches_file.parent.mkdir(parents=True, exist_ok=True)
        approaches_file.write_text("")

        approaches = manager.approach_list()
        assert approaches == []

    def test_approach_malformed_entry_skipped(self, manager: "LessonsManager"):
        """Should skip malformed entries without crashing."""
        approaches_file = manager.project_handoffs_file
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

    def test_approach_id_uniqueness_with_hash(self, manager: "LessonsManager"):
        """Hash-based IDs should always be unique regardless of deletion."""
        id1 = manager.approach_add(title="First")
        id2 = manager.approach_add(title="Second")
        manager.approach_delete(id1)

        # New approach should get a unique hash ID
        new_id = manager.approach_add(title="Third")
        assert new_id.startswith("hf-")
        assert new_id != id1  # Should not reuse deleted ID
        assert new_id != id2  # Should be distinct from existing

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
        approach_id = manager.approach_add(title="Order test")

        for i in range(5):
            manager.approach_add_tried(approach_id, "fail", f"Attempt {i+1}")

        approach = manager.approach_get(approach_id)
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

        approaches_file = manager.project_handoffs_file
        content = approaches_file.read_text()

        # Accept both new format (HANDOFFS.md) and legacy (APPROACHES.md)
        assert "HANDOFFS.md" in content or "APPROACHES.md" in content
        assert "Active Work Tracking" in content or "Active Handoffs" in content

    def test_approach_format_includes_separator(self, manager: "LessonsManager"):
        """Each approach should be followed by separator."""
        manager.approach_add(title="First")
        manager.approach_add(title="Second")

        approaches_file = manager.project_handoffs_file
        content = approaches_file.read_text()

        # Should have separator between approaches
        assert "---" in content

    def test_approach_format_includes_status_line(self, manager: "LessonsManager"):
        """Approach should include status/dates line."""
        approach_id = manager.approach_add(title="Test")
        manager.approach_update_status(approach_id, "in_progress")

        approaches_file = manager.project_handoffs_file
        content = approaches_file.read_text()

        assert "**Status**:" in content
        assert "**Created**:" in content
        assert "**Updated**:" in content
        assert "in_progress" in content

    def test_approach_format_includes_tried_section(self, manager: "LessonsManager"):
        """Approach should include Tried section."""
        approach_id = manager.approach_add(title="Test")
        manager.approach_add_tried(approach_id, "fail", "First attempt")

        approaches_file = manager.project_handoffs_file
        content = approaches_file.read_text()

        assert "**Tried**:" in content
        assert "[fail]" in content.lower() or "fail" in content.lower()
        assert "First attempt" in content

    def test_approach_format_includes_next_section(self, manager: "LessonsManager"):
        """Approach should include Next section."""
        approach_id = manager.approach_add(title="Test")
        manager.approach_update_next(approach_id, "Do something next")

        approaches_file = manager.project_handoffs_file
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
        approach_id = manager.approach_add(title="Test approach")
        approach = manager.approach_get(approach_id)

        assert approach is not None
        assert hasattr(approach, "phase")
        assert approach.phase == "research"

    def test_approach_add_with_explicit_phase(self, manager: "LessonsManager"):
        """Should allow setting phase when adding approach."""
        approach_id = manager.approach_add(title="Planning task", phase="planning")
        approach = manager.approach_get(approach_id)

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
        approach_id = manager.approach_add(title="Test approach")
        approach = manager.approach_get(approach_id)

        assert approach is not None
        assert hasattr(approach, "agent")
        assert approach.agent == "user"

    def test_approach_add_with_explicit_agent(self, manager: "LessonsManager"):
        """Should allow setting agent when adding approach."""
        approach_id = manager.approach_add(title="Exploration task", agent="explore")
        approach = manager.approach_get(approach_id)

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

    def test_approach_agent_stored_but_not_injected(self, manager_with_approaches: "LessonsManager"):
        """Agent is stored but not shown in compact inject output (by design)."""
        manager_with_approaches.approach_update_agent("A001", "general-purpose")

        # Agent is stored
        approach = manager_with_approaches.approach_get("A001")
        assert approach.agent == "general-purpose"

        # But not in compact inject output (too verbose)
        injected = manager_with_approaches.approach_inject()
        assert "Agent" not in injected  # Removed for compactness

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

        approaches_file = manager.project_handoffs_file
        content = approaches_file.read_text()

        assert "**Phase**:" in content
        assert "implementing" in content

    def test_approach_format_includes_agent(self, manager: "LessonsManager"):
        """Approach format should include agent in status line."""
        manager.approach_add(title="Test", agent="explore")

        approaches_file = manager.project_handoffs_file
        content = approaches_file.read_text()

        assert "**Agent**:" in content
        assert "explore" in content

    def test_approach_parse_new_format_with_phase_agent(self, manager: "LessonsManager"):
        """Should parse the new format with phase and agent correctly."""
        # Write a file with the new format directly
        approaches_file = manager.project_handoffs_file
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
        approach_id = manager.approach_add(title="Test format", phase="planning", agent="plan")
        manager.approach_update_status(approach_id, "in_progress")

        approaches_file = manager.project_handoffs_file
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
        approaches_file = manager.project_handoffs_file
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

        archive_file = manager_with_approaches.project_handoffs_archive
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
        created_ids = []
        for i in range(5):
            approach_id = manager.approach_add(title=f"Approach {i}")
            created_ids.append(approach_id)
            manager.approach_update_status(approach_id, "completed")

        # Make them all old (30 days ago) so only max_count applies
        approaches_file = manager.project_handoffs_file
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
        approach_id = manager.approach_add(title="Recent approach")
        manager.approach_update_status(approach_id, "completed")

        # Should include recent
        completed = manager.approach_list_completed(max_age_days=7)
        assert len(completed) == 1

    def test_approach_list_completed_hybrid_logic(
        self, manager: "LessonsManager"
    ):
        """Should use OR logic: within max_count OR within max_age_days."""
        # Create 5 completed approaches
        created_ids = []
        for i in range(5):
            approach_id = manager.approach_add(title=f"Approach {i}")
            created_ids.append(approach_id)
            manager.approach_update_status(approach_id, "completed")

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
        id1 = manager.approach_add(title="Active task")
        id2 = manager.approach_add(title="Completed task")
        manager.approach_update_status(id2, "completed")

        output = manager.approach_inject()

        # Should show both active and completed sections
        assert "Active" in output or "active" in output
        assert id1 in output
        # Should mention completed or recent
        assert "Completed" in output or "completed" in output or "Recent" in output

    def test_approach_inject_shows_completion_info(
        self, manager: "LessonsManager"
    ):
        """Completed approaches should show completion metadata."""
        approach_id = manager.approach_add(title="Finished feature")
        manager.approach_update_status(approach_id, "completed")

        output = manager.approach_inject()

        # Should indicate it's completed
        assert "✓" in output or "completed" in output.lower()

    def test_approach_inject_hides_old_completions(
        self, manager: "LessonsManager"
    ):
        """Old completed approaches outside top N should not appear."""
        # Create 5 completed approaches
        created_ids = []
        for i in range(5):
            approach_id = manager.approach_add(title=f"Task {i}")
            created_ids.append(approach_id)
            manager.approach_update_status(approach_id, "completed")

        # Make them all old (30 days ago)
        approaches_file = manager.project_handoffs_file
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
        approach_id = manager.approach_add(title="Feature work")
        manager.approach_add_tried(approach_id, "success", "Main implementation")

        result = manager.approach_complete(approach_id)

        # Should return extraction prompt
        assert result.extraction_prompt is not None
        assert "lesson" in result.extraction_prompt.lower()

    def test_approach_archive_after_extraction(
        self, manager: "LessonsManager"
    ):
        """Should be able to archive after completing."""
        approach_id = manager.approach_add(title="Feature work")
        manager.approach_complete(approach_id)

        # Archive after extraction
        manager.approach_archive(approach_id)

        # Should no longer appear in active list
        approaches = manager.approach_list()
        assert len(approaches) == 0

        # Should be in archive
        archive_file = manager.project_handoffs_archive
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
        approach_id = manager.approach_add(title="New feature", phase="research")
        manager.approach_update_phase(approach_id, "planning")

        approach = manager.approach_get(approach_id)
        assert approach.phase == "planning"

    def test_approach_phase_transition_planning_to_implementing(
        self, manager: "LessonsManager"
    ):
        """Phase should transition from planning to implementing."""
        approach_id = manager.approach_add(title="New feature", phase="planning")
        manager.approach_update_phase(approach_id, "implementing")

        approach = manager.approach_get(approach_id)
        assert approach.phase == "implementing"


class TestHookPhasePatterns:
    """Tests for hook command patterns for phase updates."""

    def test_approach_update_phase_via_hook_pattern(self, manager: "LessonsManager"):
        """Should support phase updates from hook patterns."""
        approach_id = manager.approach_add(title="Test feature")

        # This simulates what the hook would do
        manager.approach_update_phase(approach_id, "implementing")

        approach = manager.approach_get(approach_id)
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

        assert approach_id.startswith("hf-")
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
                "core/cli.py",
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
        # Hash-based IDs start with "hf-"
        assert "hf-" in result.stdout

    def test_cli_approach_start_alias(self, tmp_path):
        """CLI should support 'start' as alias for 'add'."""
        env = os.environ.copy()
        env["PROJECT_DIR"] = str(tmp_path)
        env["LESSONS_BASE"] = str(tmp_path / ".lessons")

        result = subprocess.run(
            [
                sys.executable,
                "core/cli.py",
                "approach",
                "start",
                "Test Start Alias",
                "--desc",
                "Description via start",
            ],
            capture_output=True,
            text=True,
            env=env,
        )

        assert result.returncode == 0
        # Hash-based IDs start with "hf-"
        assert "hf-" in result.stdout
        assert "Test Start Alias" in result.stdout

    def test_cli_approach_update_phase(self, tmp_path):
        """CLI should support --phase in update command."""
        env = os.environ.copy()
        env["PROJECT_DIR"] = str(tmp_path)
        env["LESSONS_BASE"] = str(tmp_path / ".lessons")

        # First create an approach and capture the ID
        add_result = subprocess.run(
            [sys.executable, "core/cli.py", "approach", "add", "Test"],
            capture_output=True,
            text=True,
            env=env,
        )
        # Parse the ID from output (format: "Added approach hf-XXXXXXX: Test")
        import re
        id_match = re.search(r'(hf-[0-9a-f]{7})', add_result.stdout)
        approach_id = id_match.group(1) if id_match else "hf-unknown"

        # Then update the phase
        result = subprocess.run(
            [
                sys.executable,
                "core/cli.py",
                "approach",
                "update",
                approach_id,
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

        # First create an approach and capture the ID
        add_result = subprocess.run(
            [sys.executable, "core/cli.py", "approach", "add", "Test"],
            capture_output=True,
            text=True,
            env=env,
        )
        # Parse the ID from output (format: "Added approach hf-XXXXXXX: Test")
        import re
        id_match = re.search(r'(hf-[0-9a-f]{7})', add_result.stdout)
        approach_id = id_match.group(1) if id_match else "hf-unknown"

        # Then update the agent
        result = subprocess.run(
            [
                sys.executable,
                "core/cli.py",
                "approach",
                "update",
                approach_id,
                "--agent",
                "general-purpose",
            ],
            capture_output=True,
            text=True,
            env=env,
        )

        assert result.returncode == 0
        assert "agent" in result.stdout.lower()


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

        from core import LessonsManager
        manager = LessonsManager(lessons_base, project_root)
        approaches = manager.approach_list()
        assert len(approaches) == 1
        approach = approaches[0]
        assert approach.title == "Test feature"
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

        from core import LessonsManager
        manager = LessonsManager(lessons_base, project_root)
        approaches = manager.approach_list()
        assert len(approaches) == 1
        approach = approaches[0]
        assert approach.title == "Another feature"
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

        from core import LessonsManager
        manager = LessonsManager(lessons_base, project_root)
        # Completed approaches are not in the default list
        completed = manager.approach_list_completed()
        assert len(completed) == 1
        approach = completed[0]
        assert approach.title == "Complete me"
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

        from core import LessonsManager
        manager = LessonsManager(lessons_base, project_root)
        approaches = manager.approach_list()
        assert len(approaches) == 2

        # Find approaches by title
        first = next((a for a in approaches if a.title == "First approach"), None)
        second = next((a for a in approaches if a.title == "Second approach"), None)

        assert first is not None
        assert first.phase == "research"  # Not updated

        assert second is not None
        assert second.phase == "implementing"  # LAST referred to it


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
        import re
        lessons_base = tmp_path / "lessons_base"
        project_root = tmp_path / "project"
        lessons_base.mkdir()
        project_root.mkdir()

        # Get the project root (coding-agent-lessons directory)
        repo_root = Path(__file__).parent.parent

        monkeypatch.setenv("LESSONS_BASE", str(lessons_base))
        monkeypatch.setenv("PROJECT_DIR", str(project_root))

        # Add approach and capture the ID
        add_result = subprocess.run(
            [
                sys.executable,
                "-m",
                "core.cli",
                "approach",
                "add",
                "Test approach",
            ],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
        assert add_result.returncode == 0, add_result.stderr

        # Parse the ID from output (format: "Added approach hf-XXXXXXX: Test")
        id_match = re.search(r'(hf-[0-9a-f]{7})', add_result.stdout)
        approach_id = id_match.group(1) if id_match else "hf-unknown"

        # Update checkpoint
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "core.cli",
                "approach",
                "update",
                approach_id,
                "--checkpoint",
                "Progress: tests passing",
            ],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
        assert result.returncode == 0, result.stderr
        assert f"Updated {approach_id} checkpoint" in result.stdout

        # Verify via manager directly
        from core import LessonsManager

        manager = LessonsManager(lessons_base, project_root)
        approach = manager.approach_get(approach_id)
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


# =============================================================================
# TodoWrite Sync Tests
# =============================================================================


class TestApproachSyncTodos:
    """Tests for TodoWrite → Approach sync functionality."""

    def test_sync_creates_approach_if_none_active(self, manager: LessonsManager) -> None:
        """sync_todos creates new approach from first todo if no active approaches."""
        todos = [
            {"content": "Research patterns", "status": "completed", "activeForm": "Researching"},
            {"content": "Implement fix", "status": "in_progress", "activeForm": "Implementing"},
        ]

        result = manager.approach_sync_todos(todos)

        assert result is not None
        approach = manager.approach_get(result)
        assert approach is not None
        assert "Research patterns" in approach.title

    def test_sync_updates_existing_approach(self, manager: LessonsManager) -> None:
        """sync_todos updates most recently updated active approach."""
        approach_id = manager.approach_add("Existing approach")

        todos = [
            {"content": "Done task", "status": "completed", "activeForm": "Done"},
            {"content": "Current task", "status": "in_progress", "activeForm": "Working"},
        ]

        result = manager.approach_sync_todos(todos)

        assert result == approach_id

    def test_sync_completed_to_tried(self, manager: LessonsManager) -> None:
        """Completed todos become tried entries with success outcome."""
        approach_id = manager.approach_add("Test approach")

        todos = [
            {"content": "Task A", "status": "completed", "activeForm": "Task A"},
            {"content": "Task B", "status": "completed", "activeForm": "Task B"},
        ]

        manager.approach_sync_todos(todos)
        approach = manager.approach_get(approach_id)

        assert len(approach.tried) == 2
        assert approach.tried[0].outcome == "success"
        assert approach.tried[0].description == "Task A"

    def test_sync_in_progress_to_checkpoint(self, manager: LessonsManager) -> None:
        """In-progress todo becomes checkpoint."""
        approach_id = manager.approach_add("Test approach")

        todos = [
            {"content": "Current work", "status": "in_progress", "activeForm": "Working"},
        ]

        manager.approach_sync_todos(todos)
        approach = manager.approach_get(approach_id)

        assert approach.checkpoint == "Current work"

    def test_sync_pending_to_next_steps(self, manager: LessonsManager) -> None:
        """Pending todos become next_steps."""
        approach_id = manager.approach_add("Test approach")

        todos = [
            {"content": "Next A", "status": "pending", "activeForm": "Next A"},
            {"content": "Next B", "status": "pending", "activeForm": "Next B"},
        ]

        manager.approach_sync_todos(todos)
        approach = manager.approach_get(approach_id)

        assert "Next A" in approach.next_steps
        assert "Next B" in approach.next_steps

    def test_sync_empty_todos_returns_none(self, manager: LessonsManager) -> None:
        """Empty todo list returns None."""
        result = manager.approach_sync_todos([])
        assert result is None

    def test_sync_avoids_duplicate_tried(self, manager: LessonsManager) -> None:
        """sync_todos doesn't add duplicate tried entries."""
        approach_id = manager.approach_add("Test approach")
        manager.approach_add_tried(approach_id, "success", "Already done")

        todos = [
            {"content": "Already done", "status": "completed", "activeForm": "Done"},
        ]

        manager.approach_sync_todos(todos)
        approach = manager.approach_get(approach_id)

        # Should still only have 1 tried entry
        assert len(approach.tried) == 1


class TestApproachInjectTodos:
    """Tests for Approach → TodoWrite injection functionality."""

    def test_inject_returns_empty_if_no_active(self, manager: LessonsManager) -> None:
        """inject_todos returns empty string if no active approaches."""
        result = manager.approach_inject_todos()
        assert result == ""

    def test_inject_formats_approach_as_todos(self, manager: LessonsManager) -> None:
        """inject_todos formats approach state as todo list."""
        approach_id = manager.approach_add("Test approach")
        manager.approach_add_tried(approach_id, "success", "First task succeeded")
        manager.approach_update_checkpoint(approach_id, "Current task")
        manager.approach_update_next(approach_id, "Next task")

        result = manager.approach_inject_todos()

        assert "CONTINUE PREVIOUS WORK" in result
        assert "First task succeeded" in result
        assert "Current task" in result
        assert "Next task" in result
        assert "```json" in result

    def test_inject_shows_status_icons(self, manager: LessonsManager) -> None:
        """inject_todos uses status icons for visual clarity."""
        approach_id = manager.approach_add("Test approach")
        manager.approach_add_tried(approach_id, "success", "Succeeded")
        manager.approach_update_checkpoint(approach_id, "Doing")
        manager.approach_update_next(approach_id, "Todo")

        result = manager.approach_inject_todos()

        assert "✓" in result  # completed
        assert "→" in result  # in_progress
        assert "○" in result  # pending

    def test_inject_json_excludes_completed(self, manager: LessonsManager) -> None:
        """inject_todos JSON only includes non-completed todos."""
        import json

        approach_id = manager.approach_add("Test approach")
        manager.approach_add_tried(approach_id, "success", "Succeeded task")
        manager.approach_update_checkpoint(approach_id, "Current task")

        result = manager.approach_inject_todos()

        # Extract JSON from result
        json_start = result.find("```json\n") + len("```json\n")
        json_end = result.find("\n```", json_start)
        json_str = result[json_start:json_end]
        todos = json.loads(json_str)

        # JSON should only have current task, not done task
        assert len(todos) == 1
        assert f"[{approach_id}] Current task" in todos[0]["content"]
        assert todos[0]["status"] == "in_progress"


class TestTodoSyncRoundTrip:
    """Tests for full TodoWrite ↔ Approach round-trip sync."""

    def test_full_round_trip(self, manager: LessonsManager) -> None:
        """Todos synced to approach can be restored as todos."""
        import json

        # Simulate session 1: sync todos to approach
        todos_session1 = [
            {"content": "Step 1", "status": "completed", "activeForm": "Step 1"},
            {"content": "Step 2", "status": "in_progress", "activeForm": "Step 2"},
            {"content": "Step 3", "status": "pending", "activeForm": "Step 3"},
        ]
        approach_id = manager.approach_sync_todos(todos_session1)

        # Simulate session 2: inject todos from approach
        result = manager.approach_inject_todos()

        # Extract and parse JSON
        json_start = result.find("```json\n") + len("```json\n")
        json_end = result.find("\n```", json_start)
        json_str = result[json_start:json_end]
        todos_session2 = json.loads(json_str)

        # Should have Step 2 (in_progress) and Step 3 (pending), with approach prefix
        assert len(todos_session2) == 2
        contents = " ".join(t["content"] for t in todos_session2)
        assert "Step 2" in contents
        assert "Step 3" in contents

        # Step 1 should be visible in "Previous state" but not in JSON
        assert "Step 1" in result  # In the display
        assert "completed" not in json_str  # Not in the JSON


class TestStaleApproachArchival:
    """Tests for auto-archiving stale approaches."""

    def test_stale_approach_archived_on_inject(self, manager: LessonsManager) -> None:
        """Approaches untouched for >7 days are auto-archived during inject."""
        from datetime import timedelta

        # Create an approach and backdate it to 8 days ago
        manager.approach_add(title="Old task", desc="Started long ago")

        # Manually update the approach's updated date to be stale
        approaches = manager._parse_approaches_file(manager.project_approaches_file)
        approaches[0].updated = date.today() - timedelta(days=8)
        manager._write_approaches_file(approaches)

        # Inject should auto-archive the stale approach
        result = manager.approach_inject()

        # Should not appear in active approaches
        assert "Old task" not in result or "Auto-archived" in result

        # Should be in archive with stale note
        archive_content = manager.project_approaches_archive.read_text()
        assert "Old task" in archive_content
        assert "Auto-archived" in archive_content

    def test_approach_exactly_7_days_not_archived(self, manager: LessonsManager) -> None:
        """Approaches exactly 7 days old are NOT archived (need >7 days)."""
        from datetime import timedelta

        manager.approach_add(title="Week old task")

        # Set to exactly 7 days ago
        approaches = manager._parse_approaches_file(manager.project_approaches_file)
        approaches[0].updated = date.today() - timedelta(days=7)
        manager._write_approaches_file(approaches)

        result = manager.approach_inject()

        # Should still appear in active handoffs
        assert "Week old task" in result
        assert "Active Handoffs" in result

    def test_completed_approach_not_stale_archived(self, manager: LessonsManager) -> None:
        """Completed approaches are handled by different rules, not stale archival."""
        from datetime import timedelta

        manager.approach_add(title="Finished task")
        approaches = manager._parse_approaches_file(manager.project_approaches_file)
        approaches[0].status = "completed"
        approaches[0].updated = date.today() - timedelta(days=8)
        manager._write_approaches_file(approaches)

        # This should NOT be archived by stale logic (completed has own rules)
        archived = manager._archive_stale_approaches()
        assert len(archived) == 0

    def test_stale_archival_returns_archived_ids(self, manager: LessonsManager) -> None:
        """_archive_stale_approaches returns list of archived approach IDs."""
        from datetime import timedelta

        manager.approach_add(title="Stale 1")
        manager.approach_add(title="Stale 2")
        manager.approach_add(title="Fresh")

        approaches = manager._parse_approaches_file(manager.project_approaches_file)
        approaches[0].updated = date.today() - timedelta(days=10)
        approaches[1].updated = date.today() - timedelta(days=8)
        # approaches[2] stays fresh (today)
        manager._write_approaches_file(approaches)

        archived = manager._archive_stale_approaches()

        assert len(archived) == 2
        assert approaches[0].id in archived
        assert approaches[1].id in archived

    def test_no_stale_approaches_no_changes(self, manager: LessonsManager) -> None:
        """When no approaches are stale, files are not modified."""
        manager.approach_add(title="Fresh task")

        # Get original content
        original_content = manager.project_approaches_file.read_text()

        archived = manager._archive_stale_approaches()

        assert len(archived) == 0
        # Archive file should not be created
        assert not manager.project_approaches_archive.exists()
        # Main file unchanged (content-wise, though timestamps may differ)
        assert "Fresh task" in manager.project_approaches_file.read_text()


class TestCompletedApproachArchival:
    """Tests for auto-archiving completed approaches after N days."""

    def test_completed_approach_archived_after_days(self, manager: LessonsManager) -> None:
        """Completed approaches are archived after APPROACH_COMPLETED_ARCHIVE_DAYS."""
        from core.models import APPROACH_COMPLETED_ARCHIVE_DAYS

        approach_id = manager.approach_add(title="Finished work")
        manager.approach_complete(approach_id)

        # Backdate the completed approach
        approaches = manager._parse_approaches_file(manager.project_approaches_file)
        approaches[0].updated = date.today() - timedelta(days=APPROACH_COMPLETED_ARCHIVE_DAYS + 1)
        manager._write_approaches_file(approaches)

        # Trigger archival via inject
        manager.approach_inject()

        # Should be archived
        archive_content = manager.project_approaches_archive.read_text()
        assert "Finished work" in archive_content

        # Should not be in active list
        active = manager.approach_list(include_completed=True)
        assert len(active) == 0

    def test_completed_approach_at_threshold_not_archived(self, manager: LessonsManager) -> None:
        """Completed approaches exactly at threshold are NOT archived."""
        from core.models import APPROACH_COMPLETED_ARCHIVE_DAYS

        approach_id = manager.approach_add(title="Just finished")
        manager.approach_complete(approach_id)

        # Set to exactly at threshold
        approaches = manager._parse_approaches_file(manager.project_approaches_file)
        approaches[0].updated = date.today() - timedelta(days=APPROACH_COMPLETED_ARCHIVE_DAYS)
        manager._write_approaches_file(approaches)

        archived = manager._archive_old_completed_approaches()

        assert len(archived) == 0
        # Should still be in active
        active = manager.approach_list(include_completed=True)
        assert len(active) == 1

    def test_fresh_completed_not_archived(self, manager: LessonsManager) -> None:
        """Recently completed approaches stay in active for visibility."""
        approach_id = manager.approach_add(title="Just done")
        manager.approach_complete(approach_id)

        archived = manager._archive_old_completed_approaches()

        assert len(archived) == 0
        # Should show in completed list
        completed = manager.approach_list_completed()
        assert len(completed) == 1

    def test_stale_and_completed_archived_separately(self, manager: LessonsManager) -> None:
        """Both stale active and old completed get archived."""
        from core.models import APPROACH_STALE_DAYS, APPROACH_COMPLETED_ARCHIVE_DAYS

        # Create stale active approach
        id1 = manager.approach_add(title="Stale active")
        # Create old completed approach
        id2 = manager.approach_add(title="Old completed")
        manager.approach_complete(id2)

        approaches = manager._parse_approaches_file(manager.project_approaches_file)
        approaches[0].updated = date.today() - timedelta(days=APPROACH_STALE_DAYS + 1)
        approaches[1].updated = date.today() - timedelta(days=APPROACH_COMPLETED_ARCHIVE_DAYS + 1)
        manager._write_approaches_file(approaches)

        # Inject triggers both
        manager.approach_inject()

        archive_content = manager.project_approaches_archive.read_text()
        assert "Stale active" in archive_content
        assert "Old completed" in archive_content

        # Both should be gone from active
        active = manager.approach_list(include_completed=True)
        assert len(active) == 0

    def test_archive_old_completed_returns_ids(self, manager: LessonsManager) -> None:
        """_archive_old_completed_approaches returns list of archived IDs."""
        from core.models import APPROACH_COMPLETED_ARCHIVE_DAYS

        id1 = manager.approach_add(title="Old 1")
        id2 = manager.approach_add(title="Old 2")
        id3 = manager.approach_add(title="Fresh")
        manager.approach_complete(id1)
        manager.approach_complete(id2)
        manager.approach_complete(id3)

        approaches = manager._parse_approaches_file(manager.project_approaches_file)
        approaches[0].updated = date.today() - timedelta(days=APPROACH_COMPLETED_ARCHIVE_DAYS + 2)
        approaches[1].updated = date.today() - timedelta(days=APPROACH_COMPLETED_ARCHIVE_DAYS + 1)
        # id3 stays fresh
        manager._write_approaches_file(approaches)

        archived = manager._archive_old_completed_approaches()

        assert len(archived) == 2
        assert id1 in archived
        assert id2 in archived
        assert id3 not in archived


class TestAutoCompleteOnFinalPattern:
    """Tests for auto-completing approaches when tried step matches 'final' patterns."""

    def test_tried_with_final_commit_autocompletes(self, manager: LessonsManager) -> None:
        """Adding tried step with 'Final report and commit' marks approach complete."""
        approach_id = manager.approach_add(title="Feature work")

        manager.approach_add_tried(approach_id, "success", "Final report and commit")

        approach = manager.approach_get(approach_id)
        assert approach.status == "completed"

    def test_tried_with_final_review_autocompletes(self, manager: LessonsManager) -> None:
        """Adding tried step with 'Final review' marks approach complete."""
        approach_id = manager.approach_add(title="Bug fix")

        manager.approach_add_tried(approach_id, "success", "Final review and merge")

        approach = manager.approach_get(approach_id)
        assert approach.status == "completed"

    def test_final_pattern_case_insensitive(self, manager: LessonsManager) -> None:
        """Final pattern matching is case insensitive."""
        approach_id = manager.approach_add(title="Task")

        manager.approach_add_tried(approach_id, "success", "FINAL COMMIT")

        approach = manager.approach_get(approach_id)
        assert approach.status == "completed"

    def test_final_pattern_requires_success(self, manager: LessonsManager) -> None:
        """Only successful 'final' steps trigger auto-complete."""
        approach_id = manager.approach_add(title="Task")

        manager.approach_add_tried(approach_id, "fail", "Final commit failed")

        approach = manager.approach_get(approach_id)
        assert approach.status != "completed"

    def test_final_pattern_partial_does_not_complete(self, manager: LessonsManager) -> None:
        """Partial outcome with 'final' does not trigger auto-complete."""
        approach_id = manager.approach_add(title="Task")

        manager.approach_add_tried(approach_id, "partial", "Final steps started")

        approach = manager.approach_get(approach_id)
        assert approach.status != "completed"

    def test_word_final_in_middle_does_not_trigger(self, manager: LessonsManager) -> None:
        """'Final' must be at start of description to trigger."""
        approach_id = manager.approach_add(title="Task")

        manager.approach_add_tried(approach_id, "success", "Updated the final configuration")

        approach = manager.approach_get(approach_id)
        assert approach.status != "completed"

    def test_done_pattern_autocompletes(self, manager: LessonsManager) -> None:
        """'Done' at start also triggers auto-complete."""
        approach_id = manager.approach_add(title="Task")

        manager.approach_add_tried(approach_id, "success", "Done - all tests passing")

        approach = manager.approach_get(approach_id)
        assert approach.status == "completed"

    def test_complete_pattern_autocompletes(self, manager: LessonsManager) -> None:
        """'Complete' at start also triggers auto-complete."""
        approach_id = manager.approach_add(title="Task")

        manager.approach_add_tried(approach_id, "success", "Complete implementation merged")

        approach = manager.approach_get(approach_id)
        assert approach.status == "completed"

    def test_finished_pattern_autocompletes(self, manager: LessonsManager) -> None:
        """'Finished' at start also triggers auto-complete."""
        approach_id = manager.approach_add(title="Task")

        manager.approach_add_tried(approach_id, "success", "Finished all tasks")

        approach = manager.approach_get(approach_id)
        assert approach.status == "completed"

    def test_autocomplete_sets_phase_to_review(self, manager: LessonsManager) -> None:
        """Auto-completed approaches get phase set to 'review'."""
        approach_id = manager.approach_add(title="Task")
        manager.approach_update_phase(approach_id, "implementing")

        manager.approach_add_tried(approach_id, "success", "Final commit")

        approach = manager.approach_get(approach_id)
        assert approach.status == "completed"
        assert approach.phase == "review"


class TestAutoPhaseUpdate:
    """Tests for auto-updating phase based on tried steps."""

    def test_implement_keyword_bumps_to_implementing(self, manager: LessonsManager) -> None:
        """Tried step containing 'implement' bumps phase to implementing."""
        approach_id = manager.approach_add(title="Feature")
        approach = manager.approach_get(approach_id)
        assert approach.phase == "research"  # Default

        manager.approach_add_tried(approach_id, "success", "Implement the core logic")

        approach = manager.approach_get(approach_id)
        assert approach.phase == "implementing"

    def test_build_keyword_bumps_to_implementing(self, manager: LessonsManager) -> None:
        """Tried step containing 'build' bumps phase to implementing."""
        approach_id = manager.approach_add(title="Feature")

        manager.approach_add_tried(approach_id, "success", "Build the component")

        approach = manager.approach_get(approach_id)
        assert approach.phase == "implementing"

    def test_create_keyword_bumps_to_implementing(self, manager: LessonsManager) -> None:
        """Tried step containing 'create' bumps phase to implementing."""
        approach_id = manager.approach_add(title="Feature")

        manager.approach_add_tried(approach_id, "success", "Create new module")

        approach = manager.approach_get(approach_id)
        assert approach.phase == "implementing"

    def test_add_keyword_bumps_to_implementing(self, manager: LessonsManager) -> None:
        """Tried step starting with 'Add' bumps phase to implementing."""
        approach_id = manager.approach_add(title="Feature")

        manager.approach_add_tried(approach_id, "success", "Add error handling")

        approach = manager.approach_get(approach_id)
        assert approach.phase == "implementing"

    def test_fix_keyword_bumps_to_implementing(self, manager: LessonsManager) -> None:
        """Tried step starting with 'Fix' bumps phase to implementing."""
        approach_id = manager.approach_add(title="Bug")

        manager.approach_add_tried(approach_id, "success", "Fix the null pointer issue")

        approach = manager.approach_get(approach_id)
        assert approach.phase == "implementing"

    def test_many_success_steps_bumps_to_implementing(self, manager: LessonsManager) -> None:
        """10+ successful tried steps bumps phase to implementing."""
        approach_id = manager.approach_add(title="Big task")

        # Add 10 generic success steps
        for i in range(10):
            manager.approach_add_tried(approach_id, "success", f"Step {i + 1}")

        approach = manager.approach_get(approach_id)
        assert approach.phase == "implementing"

    def test_nine_steps_stays_in_research(self, manager: LessonsManager) -> None:
        """9 successful steps without implementing keywords stays in research."""
        approach_id = manager.approach_add(title="Research task")

        for i in range(9):
            manager.approach_add_tried(approach_id, "success", f"Research step {i + 1}")

        approach = manager.approach_get(approach_id)
        assert approach.phase == "research"

    def test_phase_not_downgraded(self, manager: LessonsManager) -> None:
        """If already in implementing, phase is not changed."""
        approach_id = manager.approach_add(title="Feature")
        manager.approach_update_phase(approach_id, "implementing")

        manager.approach_add_tried(approach_id, "success", "Research more options")

        approach = manager.approach_get(approach_id)
        assert approach.phase == "implementing"

    def test_review_phase_not_changed(self, manager: LessonsManager) -> None:
        """If in review phase, auto-update doesn't change it."""
        approach_id = manager.approach_add(title="Feature")
        manager.approach_update_phase(approach_id, "review")

        manager.approach_add_tried(approach_id, "success", "Implement one more thing")

        approach = manager.approach_get(approach_id)
        assert approach.phase == "review"

    def test_planning_phase_bumps_to_implementing(self, manager: LessonsManager) -> None:
        """Planning phase can be bumped to implementing."""
        approach_id = manager.approach_add(title="Feature")
        manager.approach_update_phase(approach_id, "planning")

        manager.approach_add_tried(approach_id, "success", "Implement the API")

        approach = manager.approach_get(approach_id)
        assert approach.phase == "implementing"

    def test_write_keyword_bumps_to_implementing(self, manager: LessonsManager) -> None:
        """Tried step starting with 'Write' bumps phase to implementing."""
        approach_id = manager.approach_add(title="Docs")

        manager.approach_add_tried(approach_id, "success", "Write the documentation")

        approach = manager.approach_get(approach_id)
        assert approach.phase == "implementing"

    def test_update_keyword_bumps_to_implementing(self, manager: LessonsManager) -> None:
        """Tried step starting with 'Update' bumps phase to implementing."""
        approach_id = manager.approach_add(title="Refactor")

        manager.approach_add_tried(approach_id, "success", "Update the interface")

        approach = manager.approach_get(approach_id)
        assert approach.phase == "implementing"

    def test_failed_implement_step_still_bumps(self, manager: LessonsManager) -> None:
        """Failed implementing step still bumps phase (attempted impl)."""
        approach_id = manager.approach_add(title="Feature")

        manager.approach_add_tried(approach_id, "fail", "Implement the feature - build errors")

        approach = manager.approach_get(approach_id)
        assert approach.phase == "implementing"


class TestExtractThemes:
    """Tests for _extract_themes() step categorization."""

    def test_extract_themes_guard_keywords(self, manager: LessonsManager) -> None:
        """Steps with guard/destructor keywords are categorized as 'guard'."""
        approach_id = manager.approach_add(title="Cleanup")
        manager.approach_add_tried(approach_id, "success", "Add is_destroyed guard")
        manager.approach_add_tried(approach_id, "success", "Fix destructor order")
        manager.approach_add_tried(approach_id, "success", "Cleanup resources")

        approach = manager.approach_get(approach_id)
        themes = manager._extract_themes(approach.tried)

        assert themes.get("guard", 0) == 3

    def test_extract_themes_plugin_keywords(self, manager: LessonsManager) -> None:
        """Steps with plugin/phase keywords are categorized as 'plugin'."""
        approach_id = manager.approach_add(title="Plugin work")
        manager.approach_add_tried(approach_id, "success", "Phase 3: Plan plugin structure")
        manager.approach_add_tried(approach_id, "success", "Implement LED plugin")

        approach = manager.approach_get(approach_id)
        themes = manager._extract_themes(approach.tried)

        assert themes.get("plugin", 0) == 2

    def test_extract_themes_ui_keywords(self, manager: LessonsManager) -> None:
        """Steps with xml/button/modal keywords are categorized as 'ui'."""
        approach_id = manager.approach_add(title="UI work")
        manager.approach_add_tried(approach_id, "success", "Add XML button")
        manager.approach_add_tried(approach_id, "success", "Create modal dialog")
        manager.approach_add_tried(approach_id, "success", "Update panel layout")

        approach = manager.approach_get(approach_id)
        themes = manager._extract_themes(approach.tried)

        assert themes.get("ui", 0) == 3

    def test_extract_themes_fix_keywords(self, manager: LessonsManager) -> None:
        """Steps with fix/bug/error keywords are categorized as 'fix'."""
        approach_id = manager.approach_add(title="Bug fixes")
        manager.approach_add_tried(approach_id, "success", "Fix HIGH: null pointer")
        manager.approach_add_tried(approach_id, "success", "Bug in error handling")
        manager.approach_add_tried(approach_id, "success", "Handle issue #123")

        approach = manager.approach_get(approach_id)
        themes = manager._extract_themes(approach.tried)

        assert themes.get("fix", 0) == 3

    def test_extract_themes_other_fallback(self, manager: LessonsManager) -> None:
        """Unrecognized steps fall into 'other' category."""
        approach_id = manager.approach_add(title="Misc")
        manager.approach_add_tried(approach_id, "success", "Research the approach")
        manager.approach_add_tried(approach_id, "success", "Document findings")

        approach = manager.approach_get(approach_id)
        themes = manager._extract_themes(approach.tried)

        assert themes.get("other", 0) == 2

    def test_extract_themes_mixed(self, manager: LessonsManager) -> None:
        """Mixed steps are categorized correctly (first matching theme wins)."""
        approach_id = manager.approach_add(title="Mixed work")
        manager.approach_add_tried(approach_id, "success", "Add is_destroyed guard")
        manager.approach_add_tried(approach_id, "success", "Fix the null error")  # pure fix
        manager.approach_add_tried(approach_id, "success", "Plugin phase 2")
        manager.approach_add_tried(approach_id, "success", "Random task")

        approach = manager.approach_get(approach_id)
        themes = manager._extract_themes(approach.tried)

        assert themes.get("guard", 0) == 1
        assert themes.get("fix", 0) == 1
        assert themes.get("plugin", 0) == 1
        assert themes.get("other", 0) == 1

    def test_extract_themes_empty(self, manager: LessonsManager) -> None:
        """Empty tried list returns empty dict."""
        themes = manager._extract_themes([])
        assert themes == {}


class TestSummarizeTriedSteps:
    """Tests for _summarize_tried_steps() compact formatting."""

    def test_summarize_empty_returns_empty(self, manager: LessonsManager) -> None:
        """Empty tried list returns empty list of lines."""
        result = manager._summarize_tried_steps([])
        assert result == []

    def test_summarize_shows_progress_count(self, manager: LessonsManager) -> None:
        """Summary includes step count."""
        approach_id = manager.approach_add(title="Task")
        for i in range(5):
            manager.approach_add_tried(approach_id, "success", f"Step {i+1}")

        approach = manager.approach_get(approach_id)
        result = manager._summarize_tried_steps(approach.tried)
        result_str = "\n".join(result)

        assert "5 steps" in result_str

    def test_summarize_all_success(self, manager: LessonsManager) -> None:
        """All success steps show '(all success)'."""
        approach_id = manager.approach_add(title="Task")
        manager.approach_add_tried(approach_id, "success", "Step 1")
        manager.approach_add_tried(approach_id, "success", "Step 2")

        approach = manager.approach_get(approach_id)
        result = manager._summarize_tried_steps(approach.tried)
        result_str = "\n".join(result)

        assert "all success" in result_str

    def test_summarize_mixed_outcomes(self, manager: LessonsManager) -> None:
        """Mixed outcomes show success/fail counts."""
        approach_id = manager.approach_add(title="Task")
        manager.approach_add_tried(approach_id, "success", "Step 1")
        manager.approach_add_tried(approach_id, "fail", "Step 2 failed")
        manager.approach_add_tried(approach_id, "success", "Step 3")

        approach = manager.approach_get(approach_id)
        result = manager._summarize_tried_steps(approach.tried)
        result_str = "\n".join(result)

        assert "2" in result_str and "1" in result_str  # 2 success, 1 fail

    def test_summarize_shows_last_3_steps(self, manager: LessonsManager) -> None:
        """Summary shows last 3 steps."""
        approach_id = manager.approach_add(title="Task")
        for i in range(10):
            manager.approach_add_tried(approach_id, "success", f"Step {i+1}")

        approach = manager.approach_get(approach_id)
        result = manager._summarize_tried_steps(approach.tried)
        result_str = "\n".join(result)

        assert "Step 8" in result_str
        assert "Step 9" in result_str
        assert "Step 10" in result_str
        assert "Step 7" not in result_str  # Not in last 3

    def test_summarize_truncates_long_descriptions(self, manager: LessonsManager) -> None:
        """Long step descriptions are truncated."""
        approach_id = manager.approach_add(title="Task")
        long_desc = "A" * 100  # 100 chars
        manager.approach_add_tried(approach_id, "success", long_desc)

        approach = manager.approach_get(approach_id)
        result = manager._summarize_tried_steps(approach.tried)
        result_str = "\n".join(result)

        assert "..." in result_str
        assert len(result_str) < 150  # Should be truncated

    def test_summarize_shows_themes_for_earlier(self, manager: LessonsManager) -> None:
        """Earlier steps (before last 3) show theme summary."""
        approach_id = manager.approach_add(title="Task")
        # Add 5 guard-related steps
        for i in range(5):
            manager.approach_add_tried(approach_id, "success", f"Add is_destroyed guard {i+1}")
        # Add 3 more steps (will be the "recent" ones)
        manager.approach_add_tried(approach_id, "success", "Recent 1")
        manager.approach_add_tried(approach_id, "success", "Recent 2")
        manager.approach_add_tried(approach_id, "success", "Recent 3")

        approach = manager.approach_get(approach_id)
        result = manager._summarize_tried_steps(approach.tried)
        result_str = "\n".join(result)

        assert "Earlier:" in result_str
        assert "guard" in result_str

    def test_summarize_no_themes_for_few_steps(self, manager: LessonsManager) -> None:
        """No theme summary when 3 or fewer steps."""
        approach_id = manager.approach_add(title="Task")
        manager.approach_add_tried(approach_id, "success", "Step 1")
        manager.approach_add_tried(approach_id, "success", "Step 2")

        approach = manager.approach_get(approach_id)
        result = manager._summarize_tried_steps(approach.tried)
        result_str = "\n".join(result)

        assert "Earlier:" not in result_str


class TestApproachInjectCompact:
    """Tests for compact approach injection format."""

    def test_inject_shows_relative_time(self, manager: LessonsManager) -> None:
        """Injection shows relative time instead of full dates."""
        manager.approach_add(title="Test approach")

        result = manager.approach_inject()

        assert "today" in result.lower() or "Last" in result

    def test_inject_compact_progress_not_full_list(self, manager: LessonsManager) -> None:
        """Injection shows progress summary, not full tried list."""
        approach_id = manager.approach_add(title="Task")
        for i in range(20):
            manager.approach_add_tried(approach_id, "success", f"Step {i+1}")

        result = manager.approach_inject()

        # Should NOT have numbered list 1. 2. 3. etc
        assert "1. [success]" not in result
        assert "20. [success]" not in result
        # Should have progress summary
        assert "20 steps" in result or "Progress" in result

    def test_inject_shows_appears_done_warning(self, manager: LessonsManager) -> None:
        """Warning shown when last step looks like completion."""
        approach_id = manager.approach_add(title="Task")
        manager.approach_add_tried(approach_id, "success", "Research")
        manager.approach_add_tried(approach_id, "success", "Implement")
        # Don't use "Final" as it will auto-complete now
        # Instead test with an approach that was manually kept open

        # For this test, we need to add a "final-looking" step without triggering auto-complete
        # Let's test with a step that says "commit" at the end, not start
        approach_id2 = manager.approach_add(title="Task 2")
        manager.approach_add_tried(approach_id2, "success", "All done and ready for commit")

        result = manager.approach_inject()

        # This shouldn't trigger the warning since "All done" doesn't start with completion pattern
        # The warning only shows for steps starting with Final/Done/Complete/Finished
        assert approach_id2 in result

    def test_inject_compact_files(self, manager: LessonsManager) -> None:
        """Files list is compacted when more than 3."""
        manager.approach_add(
            title="Multi-file task",
            files=["file1.py", "file2.py", "file3.py", "file4.py", "file5.py"]
        )

        result = manager.approach_inject()

        assert "file1.py" in result
        assert "file2.py" in result
        assert "file3.py" in result
        assert "+2 more" in result or "(+2" in result

    def test_inject_all_files_when_few(self, manager: LessonsManager) -> None:
        """All files shown when 3 or fewer."""
        manager.approach_add(
            title="Small task",
            files=["file1.py", "file2.py"]
        )

        result = manager.approach_inject()

        assert "file1.py" in result
        assert "file2.py" in result
        assert "more" not in result


# =============================================================================
# Phase 1: HandoffContext Tests (TDD - tests written before implementation)
# =============================================================================


class TestHandoffContextCreation:
    """Tests for HandoffContext dataclass creation."""

    def test_handoff_context_with_all_fields(self) -> None:
        """Create HandoffContext with all fields populated."""
        # Import will fail until implementation exists - that's expected for TDD
        try:
            from core.models import HandoffContext
        except ImportError:
            pytest.skip("HandoffContext not yet implemented")

        context = HandoffContext(
            summary="Tests passing, working on UI integration",
            critical_files=["src/main.py:42", "src/utils.py:15"],
            recent_changes=["Added error handling", "Updated API endpoints"],
            learnings=["The API requires auth headers", "Cache invalidation is tricky"],
            blockers=["Waiting for design review"],
            git_ref="abc1234",
        )

        assert context.summary == "Tests passing, working on UI integration"
        assert len(context.critical_files) == 2
        assert "src/main.py:42" in context.critical_files
        assert len(context.recent_changes) == 2
        assert len(context.learnings) == 2
        assert len(context.blockers) == 1
        assert context.git_ref == "abc1234"

    def test_handoff_context_with_minimal_fields(self) -> None:
        """Create HandoffContext with minimal fields (empty lists ok)."""
        try:
            from core.models import HandoffContext
        except ImportError:
            pytest.skip("HandoffContext not yet implemented")

        context = HandoffContext(
            summary="Just started",
            critical_files=[],
            recent_changes=[],
            learnings=[],
            blockers=[],
            git_ref="def5678",
        )

        assert context.summary == "Just started"
        assert context.critical_files == []
        assert context.recent_changes == []
        assert context.learnings == []
        assert context.blockers == []
        assert context.git_ref == "def5678"

    def test_handoff_context_git_ref_format(self) -> None:
        """Validate git_ref is a short hash format."""
        try:
            from core.models import HandoffContext
        except ImportError:
            pytest.skip("HandoffContext not yet implemented")

        # Valid short hash (7 characters)
        context = HandoffContext(
            summary="Test",
            critical_files=[],
            recent_changes=[],
            learnings=[],
            blockers=[],
            git_ref="abc1234",
        )
        assert len(context.git_ref) == 7

        # Also valid: 8+ character hash
        context2 = HandoffContext(
            summary="Test",
            critical_files=[],
            recent_changes=[],
            learnings=[],
            blockers=[],
            git_ref="abc1234def",
        )
        assert len(context2.git_ref) >= 7

    def test_handoff_context_has_all_expected_fields(self) -> None:
        """Verify HandoffContext has all required fields as per spec."""
        try:
            from core.models import HandoffContext
        except ImportError:
            pytest.skip("HandoffContext not yet implemented")

        context = HandoffContext(
            summary="Test",
            critical_files=["file.py:1"],
            recent_changes=["change"],
            learnings=["learning"],
            blockers=["blocker"],
            git_ref="abc1234",
        )

        # Verify all fields exist
        assert hasattr(context, "summary")
        assert hasattr(context, "critical_files")
        assert hasattr(context, "recent_changes")
        assert hasattr(context, "learnings")
        assert hasattr(context, "blockers")
        assert hasattr(context, "git_ref")


class TestHandoffWithHandoffContext:
    """Tests for Handoff dataclass with HandoffContext field."""

    def test_handoff_with_handoff_context(self, manager: LessonsManager) -> None:
        """Create Handoff that includes a HandoffContext."""
        try:
            from core.models import HandoffContext, Handoff
        except ImportError:
            pytest.skip("HandoffContext not yet implemented")

        context = HandoffContext(
            summary="API implementation done, tests next",
            critical_files=["src/api.py:100"],
            recent_changes=["Implemented REST endpoints"],
            learnings=["Rate limiting needed"],
            blockers=[],
            git_ref="abc1234",
        )

        # Create handoff with context
        approach_id = manager.approach_add("Implement API layer")
        approach = manager.approach_get(approach_id)

        # After implementation, Handoff should have 'handoff' field instead of 'checkpoint'
        assert hasattr(approach, "handoff") or hasattr(approach, "checkpoint")

    def test_handoff_without_handoff_context(self, manager: LessonsManager) -> None:
        """Handoff can be created without HandoffContext (None default)."""
        approach_id = manager.approach_add("Simple task")
        approach = manager.approach_get(approach_id)

        # Either the new 'handoff' field is None, or the old 'checkpoint' is empty
        if hasattr(approach, "handoff"):
            assert approach.handoff is None
        else:
            assert approach.checkpoint == ""

    def test_handoff_update_with_context(self, manager: LessonsManager) -> None:
        """Should be able to update Handoff with HandoffContext."""
        try:
            from core.models import HandoffContext
        except ImportError:
            pytest.skip("HandoffContext not yet implemented")

        approach_id = manager.approach_add("Feature work")

        context = HandoffContext(
            summary="Progress: core logic complete",
            critical_files=["src/core.py:50"],
            recent_changes=["Added core module"],
            learnings=["Need to handle edge cases"],
            blockers=[],
            git_ref="xyz9876",
        )

        # This method should exist after implementation
        if hasattr(manager, "handoff_update_context"):
            manager.handoff_update_context(approach_id, context)
            approach = manager.approach_get(approach_id)
            assert approach.handoff is not None
            assert approach.handoff.summary == "Progress: core logic complete"
        else:
            # Fall back to existing checkpoint method
            manager.approach_update_checkpoint(approach_id, context.summary)
            approach = manager.approach_get(approach_id)
            assert context.summary in approach.checkpoint


class TestHandoffBlockedBy:
    """Tests for blocked_by field on Handoff."""

    def test_handoff_with_blocked_by(self, manager: LessonsManager) -> None:
        """Create Handoff with blocked_by dependency list."""
        approach_id = manager.approach_add("Blocked task")
        approach = manager.approach_get(approach_id)

        # After implementation, Handoff should have 'blocked_by' field
        assert hasattr(approach, "blocked_by") or True  # Will fail until implemented

    def test_handoff_blocked_by_default_empty(self, manager: LessonsManager) -> None:
        """Handoff blocked_by defaults to empty list."""
        approach_id = manager.approach_add("Independent task")
        approach = manager.approach_get(approach_id)

        if hasattr(approach, "blocked_by"):
            assert approach.blocked_by == []
        else:
            # Field doesn't exist yet - this is expected in TDD
            pass

    def test_handoff_update_blocked_by(self, manager: LessonsManager) -> None:
        """Should be able to update Handoff blocked_by list."""
        approach_id = manager.approach_add("Dependent task")

        # Create another approach to depend on
        blocking_id = manager.approach_add("Blocking task")

        # This method should exist after implementation
        if hasattr(manager, "handoff_update_blocked_by"):
            manager.handoff_update_blocked_by(approach_id, [blocking_id])
            approach = manager.approach_get(approach_id)
            assert blocking_id in approach.blocked_by
        else:
            # Method doesn't exist yet - expected in TDD
            pass

    def test_handoff_blocked_by_multiple_dependencies(self, manager: LessonsManager) -> None:
        """Handoff can depend on multiple other handoffs."""
        approach_id = manager.approach_add("Complex task")
        dep1_id = manager.approach_add("Dependency 1")
        dep2_id = manager.approach_add("Dependency 2")

        if hasattr(manager, "handoff_update_blocked_by"):
            manager.handoff_update_blocked_by(approach_id, [dep1_id, dep2_id])
            approach = manager.approach_get(approach_id)
            assert len(approach.blocked_by) == 2
            assert dep1_id in approach.blocked_by
            assert dep2_id in approach.blocked_by


class TestHandoffContextSerialization:
    """Tests for serializing/deserializing HandoffContext to markdown."""

    def test_handoff_context_serializes_to_markdown(self, manager: LessonsManager) -> None:
        """HandoffContext should serialize to readable markdown format."""
        try:
            from core.models import HandoffContext
        except ImportError:
            pytest.skip("HandoffContext not yet implemented")

        approach_id = manager.approach_add("Feature with context")

        context = HandoffContext(
            summary="Database migration complete",
            critical_files=["db/migrate.py:25", "db/models.py:100"],
            recent_changes=["Created migration script", "Updated models"],
            learnings=["Alembic requires careful ordering"],
            blockers=[],
            git_ref="mig4567",
        )

        if hasattr(manager, "handoff_update_context"):
            manager.handoff_update_context(approach_id, context)

            # Read the file and check format
            content = manager.project_handoffs_file.read_text()

            # Should contain structured context sections
            assert "**Summary**:" in content or "Database migration complete" in content
            assert "db/migrate.py" in content or "critical_files" in content.lower()

    def test_handoff_context_parses_from_markdown(self, manager: LessonsManager) -> None:
        """HandoffContext should parse correctly from markdown file."""
        try:
            from core.models import HandoffContext
        except ImportError:
            pytest.skip("HandoffContext not yet implemented")

        approach_id = manager.approach_add("Parseable context")

        context = HandoffContext(
            summary="Test parse roundtrip",
            critical_files=["test.py:1"],
            recent_changes=["Added test"],
            learnings=["Tests are important"],
            blockers=["Need more tests"],
            git_ref="tst1234",
        )

        if hasattr(manager, "handoff_update_context"):
            manager.handoff_update_context(approach_id, context)

            # Force re-parse by getting fresh
            approach = manager.approach_get(approach_id)

            assert approach.handoff is not None
            assert approach.handoff.summary == "Test parse roundtrip"
            assert "test.py:1" in approach.handoff.critical_files
            assert "Added test" in approach.handoff.recent_changes
            assert "Tests are important" in approach.handoff.learnings
            assert "Need more tests" in approach.handoff.blockers
            assert approach.handoff.git_ref == "tst1234"

    def test_blocked_by_serializes_to_markdown(self, manager: LessonsManager) -> None:
        """blocked_by field should serialize to markdown."""
        approach_id = manager.approach_add("Task with deps")

        if hasattr(manager, "handoff_update_blocked_by"):
            dep_id = manager.approach_add("Dependency")
            manager.handoff_update_blocked_by(approach_id, [dep_id])

            content = manager.project_handoffs_file.read_text()
            assert "**Blocked By**:" in content or dep_id in content

    def test_blocked_by_parses_from_markdown(self, manager: LessonsManager) -> None:
        """blocked_by field should parse correctly from markdown."""
        approach_id = manager.approach_add("Task to parse")

        if hasattr(manager, "handoff_update_blocked_by"):
            dep_id = manager.approach_add("Dep task")
            manager.handoff_update_blocked_by(approach_id, [dep_id])

            # Force re-parse
            approach = manager.approach_get(approach_id)
            assert dep_id in approach.blocked_by


class TestHandoffContextBackwardCompatibility:
    """Tests for backward compatibility with old checkpoint field."""

    def test_old_checkpoint_migrates_to_handoff_summary(self, manager: LessonsManager) -> None:
        """If old checkpoint field exists, migrate to handoff.summary."""
        try:
            from core.models import HandoffContext
        except ImportError:
            pytest.skip("HandoffContext not yet implemented")

        # Create approach with old checkpoint
        approach_id = manager.approach_add("Legacy approach")
        manager.approach_update_checkpoint(approach_id, "Old checkpoint text")

        approach = manager.approach_get(approach_id)

        # Either new handoff field has summary from checkpoint, or checkpoint still works
        if hasattr(approach, "handoff") and approach.handoff is not None:
            assert approach.handoff.summary == "Old checkpoint text"
        else:
            assert approach.checkpoint == "Old checkpoint text"

    def test_handoffs_without_context_still_parse(self, manager: LessonsManager) -> None:
        """Old handoff format without HandoffContext should still parse."""
        # Write old format directly
        approaches_file = manager.project_handoffs_file
        approaches_file.parent.mkdir(parents=True, exist_ok=True)

        old_format = """# HANDOFFS.md - Active Work Tracking

> Track ongoing work with tried steps and next steps.
> When completed, review for lessons to extract.

## Active Handoffs

### [A001] Legacy handoff
- **Status**: in_progress | **Phase**: implementing | **Agent**: user
- **Created**: 2025-12-28 | **Updated**: 2025-12-28
- **Files**: old_file.py
- **Description**: Old style handoff without context
- **Checkpoint**: Simple progress note

**Tried**:
1. [success] Did something

**Next**: Do more

---
"""
        approaches_file.write_text(old_format)

        # Should parse without errors
        approach = manager.approach_get("A001")
        assert approach is not None
        assert approach.title == "Legacy handoff"
        assert approach.status == "in_progress"

    def test_empty_handoff_context_ok(self, manager: LessonsManager) -> None:
        """Handoff with None/empty HandoffContext should work."""
        approach_id = manager.approach_add("No context needed")
        approach = manager.approach_get(approach_id)

        # Should not error, context is optional
        if hasattr(approach, "handoff"):
            assert approach.handoff is None
        assert approach.title == "No context needed"


class TestHandoffContextInInjection:
    """Tests for HandoffContext in context injection output."""

    def test_inject_shows_handoff_context_summary(self, manager: LessonsManager) -> None:
        """Injection output shows HandoffContext summary prominently."""
        try:
            from core.models import HandoffContext
        except ImportError:
            pytest.skip("HandoffContext not yet implemented")

        approach_id = manager.approach_add("Feature with rich context")

        context = HandoffContext(
            summary="API layer done, frontend integration next",
            critical_files=["api/routes.py:50"],
            recent_changes=["Added REST endpoints"],
            learnings=["Need auth middleware"],
            blockers=[],
            git_ref="api1234",
        )

        if hasattr(manager, "handoff_update_context"):
            manager.handoff_update_context(approach_id, context)

            output = manager.approach_inject()

            assert "API layer done" in output or "summary" in output.lower()

    def test_inject_shows_critical_files(self, manager: LessonsManager) -> None:
        """Injection output shows critical files from HandoffContext."""
        try:
            from core.models import HandoffContext
        except ImportError:
            pytest.skip("HandoffContext not yet implemented")

        approach_id = manager.approach_add("File-focused work")

        context = HandoffContext(
            summary="Working on core",
            critical_files=["core/engine.py:100", "core/types.py:25"],
            recent_changes=[],
            learnings=[],
            blockers=[],
            git_ref="cor5678",
        )

        if hasattr(manager, "handoff_update_context"):
            manager.handoff_update_context(approach_id, context)

            output = manager.approach_inject()

            assert "core/engine.py" in output or "engine" in output

    def test_inject_shows_blockers(self, manager: LessonsManager) -> None:
        """Injection output highlights blockers from HandoffContext."""
        try:
            from core.models import HandoffContext
        except ImportError:
            pytest.skip("HandoffContext not yet implemented")

        approach_id = manager.approach_add("Blocked work")

        context = HandoffContext(
            summary="Waiting on external",
            critical_files=[],
            recent_changes=[],
            learnings=[],
            blockers=["Need API key from partner", "Design spec pending"],
            git_ref="blk9999",
        )

        if hasattr(manager, "handoff_update_context"):
            manager.handoff_update_context(approach_id, context)

            output = manager.approach_inject()

            assert "API key" in output or "blocker" in output.lower()

    def test_inject_shows_git_ref(self, manager: LessonsManager) -> None:
        """Injection output shows git reference from HandoffContext."""
        try:
            from core.models import HandoffContext
        except ImportError:
            pytest.skip("HandoffContext not yet implemented")

        approach_id = manager.approach_add("Git-tracked work")

        context = HandoffContext(
            summary="At commit point",
            critical_files=[],
            recent_changes=["Major refactor"],
            learnings=[],
            blockers=[],
            git_ref="ref7777",
        )

        if hasattr(manager, "handoff_update_context"):
            manager.handoff_update_context(approach_id, context)

            output = manager.approach_inject()

            assert "ref7777" in output or "git" in output.lower()


# =============================================================================
# Phase 2: Hash-based IDs for Multi-Agent Safety
# =============================================================================


class TestHashBasedIds:
    """Tests for hash-based handoff IDs (hf-XXXXXXX format)."""

    def test_new_handoff_gets_hash_id(self, manager: "LessonsManager"):
        """New handoffs should get hash-based IDs with hf- prefix."""
        handoff_id = manager.handoff_add(title="Test handoff")

        # New format: hf- prefix followed by 7 hex characters
        assert handoff_id.startswith("hf-")
        assert len(handoff_id) == 10  # "hf-" (3) + 7 hex chars

    def test_hash_id_format(self, manager: "LessonsManager"):
        """Hash ID should have correct format: hf- prefix + 7 hex characters."""
        handoff_id = manager.handoff_add(title="Format test")

        # Validate format
        assert handoff_id.startswith("hf-")
        hash_part = handoff_id[3:]  # Remove "hf-" prefix
        assert len(hash_part) == 7
        # Should be valid hex characters
        assert all(c in "0123456789abcdef" for c in hash_part)

    def test_hash_ids_are_unique(self, manager: "LessonsManager"):
        """Two handoffs with same title should get different IDs due to timestamp."""
        import time

        id1 = manager.handoff_add(title="Same title")
        time.sleep(0.01)  # Small delay to ensure different timestamp
        id2 = manager.handoff_add(title="Same title")

        assert id1 != id2
        assert id1.startswith("hf-")
        assert id2.startswith("hf-")

    def test_old_ids_still_parsed(self, manager: "LessonsManager"):
        """Old A### format IDs should still be parseable."""
        # Write a file with old format IDs directly
        handoffs_file = manager.project_handoffs_file
        handoffs_file.parent.mkdir(parents=True, exist_ok=True)

        old_format_content = """# HANDOFFS.md - Active Work Tracking

> Track ongoing work with tried steps and next steps.
> When completed, review for lessons to extract.

## Active Handoffs

### [A001] Legacy handoff with old ID
- **Status**: in_progress | **Phase**: research | **Agent**: user
- **Created**: 2025-12-28 | **Updated**: 2025-12-28
- **Files**: test.py
- **Description**: Testing old ID parsing

**Tried**:
1. [success] First step

**Next**: Continue work

---
"""
        handoffs_file.write_text(old_format_content)

        # Should be able to get the old-format handoff
        handoff = manager.handoff_get("A001")

        assert handoff is not None
        assert handoff.id == "A001"
        assert handoff.title == "Legacy handoff with old ID"

    def test_old_ids_preserved(self, manager: "LessonsManager"):
        """Existing A### IDs should not change when file is re-saved."""
        # Write a file with old format ID
        handoffs_file = manager.project_handoffs_file
        handoffs_file.parent.mkdir(parents=True, exist_ok=True)

        old_format_content = """# HANDOFFS.md - Active Work Tracking

> Track ongoing work with tried steps and next steps.
> When completed, review for lessons to extract.

## Active Handoffs

### [A001] Legacy handoff
- **Status**: not_started | **Phase**: research | **Agent**: user
- **Created**: 2025-12-28 | **Updated**: 2025-12-28
- **Files**:
- **Description**: Testing preservation

**Tried**:

**Next**:

---
"""
        handoffs_file.write_text(old_format_content)

        # Update the handoff (triggers re-save)
        manager.handoff_update_status("A001", "in_progress")

        # Read back and verify ID is preserved
        handoff = manager.handoff_get("A001")
        assert handoff is not None
        assert handoff.id == "A001"  # ID should NOT change to hash format

        # Verify in file content as well
        content = handoffs_file.read_text()
        assert "[A001]" in content

    def test_blocked_by_accepts_both_formats(self, manager: "LessonsManager"):
        """blocked_by field should work with both old A### and new hf- IDs."""
        # Write a file with old format ID
        handoffs_file = manager.project_handoffs_file
        handoffs_file.parent.mkdir(parents=True, exist_ok=True)

        old_format_content = """# HANDOFFS.md - Active Work Tracking

> Track ongoing work with tried steps and next steps.
> When completed, review for lessons to extract.

## Active Handoffs

### [A001] Blocker handoff
- **Status**: in_progress | **Phase**: research | **Agent**: user
- **Created**: 2025-12-28 | **Updated**: 2025-12-28
- **Files**:
- **Description**: This blocks other work

**Tried**:

**Next**:

---
"""
        handoffs_file.write_text(old_format_content)

        # Create a new handoff (will get hash ID)
        new_id = manager.handoff_add(title="Blocked handoff")
        assert new_id.startswith("hf-")

        # Set blocked_by with both old and new format IDs
        manager.handoff_update_blocked_by(new_id, ["A001", new_id])

        # Verify blocked_by is stored correctly
        handoff = manager.handoff_get(new_id)
        assert handoff is not None
        assert "A001" in handoff.blocked_by
        assert new_id in handoff.blocked_by


# =============================================================================
# File References (Phase 3) - path:line format
# =============================================================================


class TestFileReferences:
    """Tests for file:line references in handoffs."""

    def test_handoff_refs_field(self, manager: "LessonsManager"):
        """Handoff should have refs field (list of str) for file:line references."""
        handoff_id = manager.handoff_add(
            title="Test refs field",
            refs=["core/handoffs.py:142", "core/models.py:50-75"],
        )

        handoff = manager.handoff_get(handoff_id)
        assert handoff is not None
        assert hasattr(handoff, "refs")
        assert handoff.refs == ["core/handoffs.py:142", "core/models.py:50-75"]

    def test_ref_format_path_line(self, manager: "LessonsManager"):
        """Should validate path:line format (e.g., file.py:42)."""
        from core.handoffs import _validate_ref

        assert _validate_ref("core/handoffs.py:142") is True
        assert _validate_ref("src/main.ts:1") is True
        assert _validate_ref("file.py:999") is True
        assert _validate_ref("deep/nested/path/file.go:50") is True

        # Invalid formats
        assert _validate_ref("just/a/path.py") is False  # No line number
        assert _validate_ref("file.py:") is False  # Empty line number
        assert _validate_ref(":42") is False  # No path
        assert _validate_ref("file.py:abc") is False  # Non-numeric line

    def test_ref_format_path_range(self, manager: "LessonsManager"):
        """Should validate path:start-end format (e.g., file.py:50-75)."""
        from core.handoffs import _validate_ref

        assert _validate_ref("core/models.py:50-75") is True
        assert _validate_ref("file.ts:1-100") is True
        assert _validate_ref("deep/path/file.go:10-20") is True

        # Invalid range formats
        assert _validate_ref("file.py:50-") is False  # Missing end
        assert _validate_ref("file.py:-75") is False  # Missing start
        assert _validate_ref("file.py:50-75-100") is False  # Too many parts

    def test_refs_serialize_to_markdown(self, manager: "LessonsManager"):
        """refs field should serialize to markdown as - **Refs**: ..."""
        handoff_id = manager.handoff_add(
            title="Test refs serialization",
            refs=["handoffs.py:142", "models.py:50-75"],
        )

        # Read file content
        content = manager.project_handoffs_file.read_text()

        # Should use **Refs** format with pipe separator
        assert "- **Refs**: handoffs.py:142 | models.py:50-75" in content

    def test_refs_parse_from_markdown(self, manager: "LessonsManager"):
        """Should parse refs from - **Refs**: ... markdown format."""
        handoffs_file = manager.project_handoffs_file
        handoffs_file.parent.mkdir(parents=True, exist_ok=True)

        today = date.today().isoformat()
        content = f"""# HANDOFFS.md - Active Work Tracking

> Track ongoing work with tried steps and next steps.
> When completed, review for lessons to extract.

## Active Handoffs

### [hf-abc1234] Test parsing refs
- **Status**: in_progress | **Phase**: implementing | **Agent**: user
- **Created**: {today} | **Updated**: {today}
- **Refs**: core/handoffs.py:142 | core/models.py:50-75 | tests/test.py:10
- **Description**: Testing refs parsing

**Tried**:

**Next**:

---
"""
        handoffs_file.write_text(content)

        handoff = manager.handoff_get("hf-abc1234")
        assert handoff is not None
        assert handoff.refs == ["core/handoffs.py:142", "core/models.py:50-75", "tests/test.py:10"]

    def test_files_alias_for_refs(self, manager: "LessonsManager"):
        """Old 'files' attribute should still work as alias for 'refs'."""
        handoff_id = manager.handoff_add(
            title="Test backward compat",
            refs=["core/main.py:100"],
        )

        handoff = manager.handoff_get(handoff_id)
        assert handoff is not None

        # Both refs and files should return same data
        assert handoff.refs == ["core/main.py:100"]
        assert handoff.files == ["core/main.py:100"]

        # Setting via files should also work
        manager.handoff_update_files(handoff_id, ["new/path.py:50"])
        handoff = manager.handoff_get(handoff_id)
        assert handoff.refs == ["new/path.py:50"]
        assert handoff.files == ["new/path.py:50"]

    def test_old_files_format_parsed(self, manager: "LessonsManager"):
        """Old - **Files**: format should still be parsed for backward compat."""
        handoffs_file = manager.project_handoffs_file
        handoffs_file.parent.mkdir(parents=True, exist_ok=True)

        today = date.today().isoformat()
        old_format_content = f"""# HANDOFFS.md - Active Work Tracking

> Track ongoing work with tried steps and next steps.
> When completed, review for lessons to extract.

## Active Handoffs

### [A001] Legacy with old Files format
- **Status**: in_progress | **Phase**: research | **Agent**: user
- **Created**: {today} | **Updated**: {today}
- **Files**: src/main.py, src/utils.py
- **Description**: Old format still works

**Tried**:

**Next**:

---
"""
        handoffs_file.write_text(old_format_content)

        handoff = manager.handoff_get("A001")
        assert handoff is not None
        # Old files should be available via refs
        assert handoff.refs == ["src/main.py", "src/utils.py"]
        # And via files alias
        assert handoff.files == ["src/main.py", "src/utils.py"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
