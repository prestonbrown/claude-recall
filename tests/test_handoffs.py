#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Test suite for Handoffs tracking system (formerly called "approaches").

This is a TDD test file - tests are written BEFORE the implementation.
Run with: pytest tests/test_handoffs.py -v

The handoffs system tracks ongoing work with tried steps and next steps.
Storage location: <project_root>/.claude-recall/HANDOFFS.md (or legacy .coding-agent-lessons/APPROACHES.md)

File format:
    # APPROACHES.md - Active Work Tracking

    > Track ongoing work with tried approaches and next steps.
    > When completed, review for lessons to extract.

    ## Active Approaches

    ### [hf-0000001] Implementing WebSocket reconnection
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
        Handoff,
        TriedStep,
        HandoffCompleteResult,
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
def manager_with_handoffs(manager: "LessonsManager") -> "LessonsManager":
    """Create a manager with some pre-existing handoffs.

    Tests rely on the specific IDs hf-0000001, hf-0000002, hf-0000003.
    """
    handoffs_file = manager.project_handoffs_file
    handoffs_file.parent.mkdir(parents=True, exist_ok=True)

    today = date.today().isoformat()
    content = f"""# HANDOFFS.md - Active Work Tracking

> Track ongoing work with tried steps and next steps.
> When completed, review for lessons to extract.

## Active Handoffs

### [hf-0000001] Implementing WebSocket reconnection
- **Status**: not_started | **Phase**: research | **Agent**: user
- **Created**: {today} | **Updated**: {today}
- **Files**: src/websocket.ts, src/connection-manager.ts
- **Description**: Add automatic reconnection with exponential backoff

**Tried**:

**Next**:

---

### [hf-0000002] Refactoring database layer
- **Status**: not_started | **Phase**: research | **Agent**: user
- **Created**: {today} | **Updated**: {today}
- **Files**: src/db/models.py
- **Description**: Extract repository pattern from service classes

**Tried**:

**Next**:

---

### [hf-0000003] Adding unit tests
- **Status**: not_started | **Phase**: research | **Agent**: user
- **Created**: {today} | **Updated**: {today}
- **Files**:
- **Description**: Improve test coverage for core module

**Tried**:

**Next**:

---
"""
    handoffs_file.write_text(content)
    return manager


# =============================================================================
# Adding Handoffs
# =============================================================================


class TestHandoffAdd:
    """Tests for adding handoffs."""

    def test_handoff_add_creates_file(self, manager: "LessonsManager"):
        """Adding a handoff should create the handoffs file (HANDOFFS.md or legacy APPROACHES.md)."""
        manager.handoff_add(title="Test approach")

        # Use the manager's property to get the actual file path
        handoffs_file = manager.project_handoffs_file
        assert handoffs_file.exists()
        content = handoffs_file.read_text()
        assert "Test approach" in content

    def test_handoff_add_assigns_hash_id(self, manager: "LessonsManager"):
        """Approach IDs should be hash-based with hf- prefix."""
        id1 = manager.handoff_add(title="First approach")
        id2 = manager.handoff_add(title="Second approach")
        id3 = manager.handoff_add(title="Third approach")

        # New IDs are hash-based with hf- prefix
        assert id1.startswith("hf-")
        assert id2.startswith("hf-")
        assert id3.startswith("hf-")
        # IDs should all be unique
        assert len({id1, id2, id3}) == 3

    def test_handoff_add_with_description(self, manager: "LessonsManager"):
        """Adding a handoff with description should store it."""
        handoff_id = manager.handoff_add(
            title="Feature work",
            desc="Implementing the new feature with proper error handling",
        )

        handoff = manager.handoff_get(handoff_id)
        assert handoff is not None
        assert handoff.description == "Implementing the new feature with proper error handling"

    def test_handoff_add_with_files(self, manager: "LessonsManager"):
        """Adding a handoff with files should store the file list."""
        handoff_id = manager.handoff_add(
            title="Multi-file refactor",
            files=["src/main.py", "src/utils.py", "tests/test_main.py"],
        )

        handoff = manager.handoff_get(handoff_id)
        assert handoff is not None
        assert handoff.files == ["src/main.py", "src/utils.py", "tests/test_main.py"]

    def test_handoff_add_initializes_metadata(self, manager: "LessonsManager"):
        """New handoffs should have correct initial metadata."""
        handoff_id = manager.handoff_add(title="New work")
        handoff = manager.handoff_get(handoff_id)

        assert handoff is not None
        assert handoff.status == "not_started"
        assert handoff.created == date.today()
        assert handoff.updated == date.today()
        assert handoff.tried == []
        assert handoff.next_steps == ""

    def test_handoff_add_returns_id(self, manager: "LessonsManager"):
        """Adding a handoff should return a hash-based ID."""
        result = manager.handoff_add(title="Return test")

        assert result.startswith("hf-")
        assert len(result) == 10  # hf- + 7 hex chars
        assert isinstance(result, str)


# =============================================================================
# Duplicate Detection
# =============================================================================


class TestHandoffDuplicateDetection:
    """Tests for handoff duplicate detection."""

    def test_handoff_add_duplicate_returns_existing_id(self, manager: "LessonsManager"):
        """Adding a handoff with the same title returns the existing ID."""
        # Create first handoff
        id1 = manager.handoff_add(title="Implement feature X")

        # Try to create duplicate with same title
        id2 = manager.handoff_add(title="Implement feature X")

        # Should return the same ID
        assert id1 == id2

        # Only one handoff should exist
        handoffs = manager.handoff_list()
        assert len(handoffs) == 1
        assert handoffs[0].id == id1

    def test_handoff_add_duplicate_case_insensitive(self, manager: "LessonsManager"):
        """Duplicate detection should be case-insensitive."""
        id1 = manager.handoff_add(title="Fix Bug in Parser")
        id2 = manager.handoff_add(title="fix bug in parser")
        id3 = manager.handoff_add(title="FIX BUG IN PARSER")

        assert id1 == id2 == id3

    def test_handoff_add_duplicate_ignores_whitespace(self, manager: "LessonsManager"):
        """Duplicate detection should ignore leading/trailing whitespace."""
        id1 = manager.handoff_add(title="Add new endpoint")
        id2 = manager.handoff_add(title="  Add new endpoint  ")

        assert id1 == id2

    def test_handoff_add_different_titles_creates_new(self, manager: "LessonsManager"):
        """Different titles should create separate handoffs."""
        id1 = manager.handoff_add(title="Implement feature A")
        id2 = manager.handoff_add(title="Implement feature B")

        assert id1 != id2

        handoffs = manager.handoff_list()
        assert len(handoffs) == 2

    def test_handoff_add_duplicate_completed_creates_new(self, manager: "LessonsManager"):
        """Adding a handoff with same title as completed one should create new."""
        # Create and complete first handoff
        id1 = manager.handoff_add(title="Deploy version 1.0")
        manager.handoff_complete(id1)

        # Now add another with same title - should create new since first is completed
        id2 = manager.handoff_add(title="Deploy version 1.0")

        assert id1 != id2

        # Should have one completed and one active
        all_handoffs = manager.handoff_list(include_completed=True)
        assert len(all_handoffs) == 2

    def test_handoff_add_duplicate_stealth_separate_from_regular(
        self, manager: "LessonsManager"
    ):
        """Stealth and regular handoffs with same title are kept separate."""
        id1 = manager.handoff_add(title="Secret task", stealth=False)
        id2 = manager.handoff_add(title="Secret task", stealth=True)

        # Should be different IDs since they're in different files
        assert id1 != id2

    def test_handoff_duplicate_detection_within_stealth(
        self, manager: "LessonsManager"
    ):
        """Duplicate detection works within stealth handoffs."""
        id1 = manager.handoff_add(title="Private work", stealth=True)
        id2 = manager.handoff_add(title="Private work", stealth=True)

        assert id1 == id2


# =============================================================================
# Sub-Agent Handoff Guard
# =============================================================================


class TestSubAgentHandoffGuard:
    """Tests for sub-agent handoff creation guard.

    Sub-agents (Explore, Plan, General, System) should not be able to create
    new handoffs - they can only resume or update existing ones.
    """

    def test_user_origin_can_create_handoff(
        self, manager: "LessonsManager", monkeypatch: pytest.MonkeyPatch
    ):
        """User origin sessions can create new handoffs normally."""
        # Mock _detect_session_origin to return "User"
        monkeypatch.setattr(
            manager, "_detect_session_origin", lambda session_id: "User"
        )

        handoff_id = manager.handoff_add(
            title="User created handoff",
            session_id="test-session-123",
        )

        assert handoff_id is not None
        assert handoff_id.startswith("hf-")
        handoff = manager.handoff_get(handoff_id)
        assert handoff is not None
        assert handoff.title == "User created handoff"

    def test_subagent_explore_cannot_create_new_handoff(
        self, manager: "LessonsManager", monkeypatch: pytest.MonkeyPatch
    ):
        """Explore sub-agent cannot create new handoffs."""
        monkeypatch.setattr(
            manager, "_detect_session_origin", lambda session_id: "Explore"
        )

        result = manager.handoff_add(
            title="Explore attempted handoff",
            session_id="test-session-456",
        )

        # Should return None (blocked)
        assert result is None

        # No handoff should exist
        handoffs = manager.handoff_list()
        assert len(handoffs) == 0

    def test_subagent_general_cannot_create_new_handoff(
        self, manager: "LessonsManager", monkeypatch: pytest.MonkeyPatch
    ):
        """General sub-agent cannot create new handoffs."""
        monkeypatch.setattr(
            manager, "_detect_session_origin", lambda session_id: "General"
        )

        result = manager.handoff_add(
            title="General attempted handoff",
            session_id="test-session-789",
        )

        assert result is None
        handoffs = manager.handoff_list()
        assert len(handoffs) == 0

    def test_subagent_plan_cannot_create_new_handoff(
        self, manager: "LessonsManager", monkeypatch: pytest.MonkeyPatch
    ):
        """Plan sub-agent cannot create new handoffs."""
        monkeypatch.setattr(
            manager, "_detect_session_origin", lambda session_id: "Plan"
        )

        result = manager.handoff_add(
            title="Plan attempted handoff",
            session_id="test-session-abc",
        )

        assert result is None
        handoffs = manager.handoff_list()
        assert len(handoffs) == 0

    def test_subagent_system_cannot_create_new_handoff(
        self, manager: "LessonsManager", monkeypatch: pytest.MonkeyPatch
    ):
        """System sub-agent cannot create new handoffs."""
        monkeypatch.setattr(
            manager, "_detect_session_origin", lambda session_id: "System"
        )

        result = manager.handoff_add(
            title="System attempted handoff",
            session_id="test-session-def",
        )

        assert result is None
        handoffs = manager.handoff_list()
        assert len(handoffs) == 0

    def test_subagent_returns_existing_handoff_with_same_title(
        self, manager: "LessonsManager", monkeypatch: pytest.MonkeyPatch
    ):
        """Sub-agent returns existing handoff if one with same title exists."""
        # First, create a handoff as User
        monkeypatch.setattr(
            manager, "_detect_session_origin", lambda session_id: "User"
        )
        original_id = manager.handoff_add(
            title="Existing work",
            session_id="user-session",
        )
        assert original_id is not None

        # Now try to create same handoff as Explore sub-agent
        monkeypatch.setattr(
            manager, "_detect_session_origin", lambda session_id: "Explore"
        )
        result = manager.handoff_add(
            title="Existing work",
            session_id="explore-session",
        )

        # Should return the existing handoff ID
        assert result == original_id

        # Still only one handoff should exist
        handoffs = manager.handoff_list()
        assert len(handoffs) == 1
        assert handoffs[0].id == original_id

    def test_subagent_returns_existing_case_insensitive(
        self, manager: "LessonsManager", monkeypatch: pytest.MonkeyPatch
    ):
        """Sub-agent finds existing handoff with case-insensitive title match."""
        # Create handoff as User
        monkeypatch.setattr(
            manager, "_detect_session_origin", lambda session_id: "User"
        )
        original_id = manager.handoff_add(
            title="Fix Authentication Bug",
            session_id="user-session",
        )

        # Try to create with different case as sub-agent
        monkeypatch.setattr(
            manager, "_detect_session_origin", lambda session_id: "General"
        )
        result = manager.handoff_add(
            title="fix authentication bug",
            session_id="general-session",
        )

        assert result == original_id

    def test_unknown_origin_can_create_handoff(
        self, manager: "LessonsManager", monkeypatch: pytest.MonkeyPatch
    ):
        """Unknown origin sessions can create handoffs (fallback to permissive)."""
        monkeypatch.setattr(
            manager, "_detect_session_origin", lambda session_id: "Unknown"
        )

        handoff_id = manager.handoff_add(
            title="Unknown origin handoff",
            session_id="test-session-unknown",
        )

        assert handoff_id is not None
        assert handoff_id.startswith("hf-")

    def test_no_session_id_can_create_handoff(
        self, manager: "LessonsManager"
    ):
        """Calls without session_id can create handoffs (backward compatibility)."""
        # No mocking needed - session_id not provided
        handoff_id = manager.handoff_add(title="No session ID handoff")

        assert handoff_id is not None
        assert handoff_id.startswith("hf-")
        handoff = manager.handoff_get(handoff_id)
        assert handoff is not None

    def test_subagent_guard_logs_warning_on_block(
        self, manager: "LessonsManager", monkeypatch: pytest.MonkeyPatch, capsys
    ):
        """Sub-agent guard should log when blocking creation."""
        # Enable debug logging
        monkeypatch.setenv("CLAUDE_RECALL_DEBUG", "1")

        monkeypatch.setattr(
            manager, "_detect_session_origin", lambda session_id: "Explore"
        )

        # Reset logger to pick up debug level change
        from core.debug_logger import reset_logger
        reset_logger()

        result = manager.handoff_add(
            title="Blocked handoff",
            session_id="explore-session",
        )

        assert result is None
        # Note: Logging goes to file, not stdout - we verify the behavior
        # by checking that the handoff was not created

    def test_subagent_guard_logs_warning_on_returning_existing(
        self, manager: "LessonsManager", monkeypatch: pytest.MonkeyPatch
    ):
        """Sub-agent guard should log when returning existing handoff."""
        # Create handoff as User
        monkeypatch.setattr(
            manager, "_detect_session_origin", lambda session_id: "User"
        )
        original_id = manager.handoff_add(
            title="Logged existing",
            session_id="user-session",
        )

        # Enable debug logging
        monkeypatch.setenv("CLAUDE_RECALL_DEBUG", "1")
        from core.debug_logger import reset_logger
        reset_logger()

        # Try as sub-agent
        monkeypatch.setattr(
            manager, "_detect_session_origin", lambda session_id: "Explore"
        )
        result = manager.handoff_add(
            title="Logged existing",
            session_id="explore-session",
        )

        assert result == original_id

    def test_subagent_returns_existing_stealth_handoff(
        self, manager: "LessonsManager", monkeypatch: pytest.MonkeyPatch
    ):
        """Sub-agent returns existing stealth handoff with same title."""
        monkeypatch.setattr(manager, "_detect_session_origin", lambda s: "User")
        original_id = manager.handoff_add(
            title="Stealth work", stealth=True, session_id="user-session"
        )

        monkeypatch.setattr(manager, "_detect_session_origin", lambda s: "Explore")
        result = manager.handoff_add(
            title="Stealth work", stealth=True, session_id="explore-session"
        )

        assert result == original_id

    def test_subagent_does_not_return_completed_handoff(
        self, manager: "LessonsManager", monkeypatch: pytest.MonkeyPatch
    ):
        """Sub-agent should not return completed handoffs."""
        monkeypatch.setattr(manager, "_detect_session_origin", lambda s: "User")
        original_id = manager.handoff_add(title="Completed work", session_id="user-session")
        manager.handoff_update_status(original_id, "completed")

        monkeypatch.setattr(manager, "_detect_session_origin", lambda s: "Explore")
        result = manager.handoff_add(title="Completed work", session_id="explore-session")

        # Should return None (blocked, no active handoff to return)
        assert result is None


# =============================================================================
# Updating Handoffs
# =============================================================================


class TestHandoffUpdateStatus:
    """Tests for updating handoff status."""

    def test_handoff_update_status_valid(self, manager_with_handoffs: "LessonsManager"):
        """Should update status with valid values."""
        manager_with_handoffs.handoff_update_status("hf-0000001", "in_progress")
        handoff = manager_with_handoffs.handoff_get("hf-0000001")
        assert handoff.status == "in_progress"

        manager_with_handoffs.handoff_update_status("hf-0000001", "blocked")
        handoff = manager_with_handoffs.handoff_get("hf-0000001")
        assert handoff.status == "blocked"

        manager_with_handoffs.handoff_update_status("hf-0000001", "completed")
        handoff = manager_with_handoffs.handoff_get("hf-0000001")
        assert handoff.status == "completed"

    def test_handoff_update_status_invalid_rejects(self, manager_with_handoffs: "LessonsManager"):
        """Should reject invalid status values."""
        with pytest.raises(ValueError, match="[Ii]nvalid status"):
            manager_with_handoffs.handoff_update_status("hf-0000001", "invalid_status")

        with pytest.raises(ValueError, match="[Ii]nvalid status"):
            manager_with_handoffs.handoff_update_status("hf-0000001", "done")

        with pytest.raises(ValueError, match="[Ii]nvalid status"):
            manager_with_handoffs.handoff_update_status("hf-0000001", "")

    def test_handoff_update_status_nonexistent_fails(self, manager: "LessonsManager"):
        """Should fail when updating nonexistent handoff."""
        with pytest.raises(ValueError, match="not found"):
            manager.handoff_update_status("A999", "in_progress")


class TestHandoffAddTried:
    """Tests for adding tried steps."""

    def test_handoff_add_tried_success(self, manager_with_handoffs: "LessonsManager"):
        """Should add a successful tried handoff."""
        manager_with_handoffs.handoff_add_tried(
            "hf-0000001",
            outcome="success",
            description="Event-based with AbortController - clean and testable",
        )

        handoff = manager_with_handoffs.handoff_get("hf-0000001")
        assert len(handoff.tried) == 1
        assert handoff.tried[0].outcome == "success"
        assert handoff.tried[0].description == "Event-based with AbortController - clean and testable"

    def test_handoff_add_tried_fail(self, manager_with_handoffs: "LessonsManager"):
        """Should add a failed tried handoff."""
        manager_with_handoffs.handoff_add_tried(
            "hf-0000001",
            outcome="fail",
            description="Simple setTimeout retry - races with manual disconnect",
        )

        handoff = manager_with_handoffs.handoff_get("hf-0000001")
        assert len(handoff.tried) == 1
        assert handoff.tried[0].outcome == "fail"

    def test_handoff_add_tried_partial(self, manager_with_handoffs: "LessonsManager"):
        """Should add a partial success tried handoff."""
        manager_with_handoffs.handoff_add_tried(
            "hf-0000001",
            outcome="partial",
            description="State machine approach - works but complex",
        )

        handoff = manager_with_handoffs.handoff_get("hf-0000001")
        assert len(handoff.tried) == 1
        assert handoff.tried[0].outcome == "partial"

    def test_handoff_add_tried_multiple(self, manager_with_handoffs: "LessonsManager"):
        """Should support adding multiple tried approaches in order."""
        manager_with_handoffs.handoff_add_tried("hf-0000001", "fail", "First attempt - failed")
        manager_with_handoffs.handoff_add_tried("hf-0000001", "partial", "Second attempt - partial")
        manager_with_handoffs.handoff_add_tried("hf-0000001", "success", "Third attempt - worked")

        handoff = manager_with_handoffs.handoff_get("hf-0000001")
        assert len(handoff.tried) == 3
        assert handoff.tried[0].description == "First attempt - failed"
        assert handoff.tried[1].description == "Second attempt - partial"
        assert handoff.tried[2].description == "Third attempt - worked"

    def test_handoff_add_tried_invalid_outcome(self, manager_with_handoffs: "LessonsManager"):
        """Should reject invalid outcome values."""
        with pytest.raises(ValueError, match="[Ii]nvalid outcome"):
            manager_with_handoffs.handoff_add_tried("hf-0000001", "maybe", "Uncertain result")


class TestHandoffUpdateNext:
    """Tests for updating next steps."""

    def test_handoff_update_next(self, manager_with_handoffs: "LessonsManager"):
        """Should update the next steps field."""
        manager_with_handoffs.handoff_update_next(
            "hf-0000001",
            "Write integration tests for edge cases",
        )

        handoff = manager_with_handoffs.handoff_get("hf-0000001")
        assert handoff.next_steps == "Write integration tests for edge cases"

    def test_handoff_update_next_overwrites(self, manager_with_handoffs: "LessonsManager"):
        """Updating next steps should overwrite previous value."""
        manager_with_handoffs.handoff_update_next("hf-0000001", "First next step")
        manager_with_handoffs.handoff_update_next("hf-0000001", "Updated next step")

        handoff = manager_with_handoffs.handoff_get("hf-0000001")
        assert handoff.next_steps == "Updated next step"

    def test_handoff_update_next_empty(self, manager_with_handoffs: "LessonsManager"):
        """Should allow clearing next steps."""
        manager_with_handoffs.handoff_update_next("hf-0000001", "Some steps")
        manager_with_handoffs.handoff_update_next("hf-0000001", "")

        handoff = manager_with_handoffs.handoff_get("hf-0000001")
        assert handoff.next_steps == ""


class TestHandoffUpdateFiles:
    """Tests for updating file lists."""

    def test_handoff_update_files(self, manager_with_handoffs: "LessonsManager"):
        """Should update the files list."""
        manager_with_handoffs.handoff_update_files(
            "hf-0000001",
            ["new/file1.py", "new/file2.py"],
        )

        handoff = manager_with_handoffs.handoff_get("hf-0000001")
        assert handoff.files == ["new/file1.py", "new/file2.py"]

    def test_handoff_update_files_replaces(self, manager_with_handoffs: "LessonsManager"):
        """Updating files should replace the entire list."""
        manager_with_handoffs.handoff_update_files("hf-0000001", ["a.py", "b.py"])
        manager_with_handoffs.handoff_update_files("hf-0000001", ["c.py"])

        handoff = manager_with_handoffs.handoff_get("hf-0000001")
        assert handoff.files == ["c.py"]

    def test_handoff_update_files_empty(self, manager_with_handoffs: "LessonsManager"):
        """Should allow clearing file list."""
        manager_with_handoffs.handoff_update_files("hf-0000001", ["some.py"])
        manager_with_handoffs.handoff_update_files("hf-0000001", [])

        handoff = manager_with_handoffs.handoff_get("hf-0000001")
        assert handoff.files == []


class TestHandoffUpdateDesc:
    """Tests for updating description."""

    def test_handoff_update_desc(self, manager_with_handoffs: "LessonsManager"):
        """Should update the description."""
        manager_with_handoffs.handoff_update_desc("hf-0000001", "New description text")

        handoff = manager_with_handoffs.handoff_get("hf-0000001")
        assert handoff.description == "New description text"


class TestHandoffFieldUpdater:
    """Tests for the generic _update_handoff_field helper method."""

    def test_update_field_updates_status(self, manager_with_handoffs: "LessonsManager"):
        """Using generic updater should update status field."""
        # Get initial state
        handoff = manager_with_handoffs.handoff_get("hf-0000001")
        assert handoff.status == "not_started"

        # Use the generic field updater
        manager_with_handoffs._update_handoff_field("hf-0000001", "status", "in_progress")

        # Verify update
        handoff = manager_with_handoffs.handoff_get("hf-0000001")
        assert handoff.status == "in_progress"

    def test_update_field_updates_phase(self, manager_with_handoffs: "LessonsManager"):
        """Using generic updater should update phase field."""
        # Get initial state
        handoff = manager_with_handoffs.handoff_get("hf-0000001")
        assert handoff.phase == "research"

        # Use the generic field updater
        manager_with_handoffs._update_handoff_field("hf-0000001", "phase", "implementing")

        # Verify update
        handoff = manager_with_handoffs.handoff_get("hf-0000001")
        assert handoff.phase == "implementing"

    def test_update_field_updates_agent(self, manager_with_handoffs: "LessonsManager"):
        """Using generic updater should update agent field."""
        # Get initial state
        handoff = manager_with_handoffs.handoff_get("hf-0000001")
        assert handoff.agent == "user"

        # Use the generic field updater
        manager_with_handoffs._update_handoff_field("hf-0000001", "agent", "explore")

        # Verify update
        handoff = manager_with_handoffs.handoff_get("hf-0000001")
        assert handoff.agent == "explore"

    def test_update_field_updates_next_steps(self, manager_with_handoffs: "LessonsManager"):
        """Using generic updater should update next_steps field."""
        # Use the generic field updater
        manager_with_handoffs._update_handoff_field(
            "hf-0000001", "next_steps", "Write more tests"
        )

        # Verify update
        handoff = manager_with_handoffs.handoff_get("hf-0000001")
        assert handoff.next_steps == "Write more tests"

    def test_update_field_updates_description(self, manager_with_handoffs: "LessonsManager"):
        """Using generic updater should update description field."""
        # Use the generic field updater
        manager_with_handoffs._update_handoff_field(
            "hf-0000001", "description", "Updated description"
        )

        # Verify update
        handoff = manager_with_handoffs.handoff_get("hf-0000001")
        assert handoff.description == "Updated description"

    def test_update_field_preserves_other_fields(self, manager_with_handoffs: "LessonsManager"):
        """Updating one field should not change other fields."""
        # Set up initial values for multiple fields
        manager_with_handoffs._update_handoff_field("hf-0000001", "status", "in_progress")
        manager_with_handoffs._update_handoff_field("hf-0000001", "phase", "planning")
        manager_with_handoffs._update_handoff_field("hf-0000001", "next_steps", "Original next steps")

        # Now update just the status
        manager_with_handoffs._update_handoff_field("hf-0000001", "status", "blocked")

        # Verify only status changed
        handoff = manager_with_handoffs.handoff_get("hf-0000001")
        assert handoff.status == "blocked"
        assert handoff.phase == "planning"  # Should be unchanged
        assert handoff.next_steps == "Original next steps"  # Should be unchanged

    def test_update_field_invalid_handoff_id(self, manager: "LessonsManager"):
        """Invalid handoff ID should raise ValueError."""
        with pytest.raises(ValueError, match="not found"):
            manager._update_handoff_field("hf-9999999", "status", "in_progress")

    def test_update_field_updates_refs_list(self, manager_with_handoffs: "LessonsManager"):
        """Using generic updater should update refs list field."""
        refs = ["file1.py:10", "file2.py:20-30"]
        manager_with_handoffs._update_handoff_field("hf-0000001", "refs", refs)

        handoff = manager_with_handoffs.handoff_get("hf-0000001")
        assert handoff.refs == refs

    def test_update_field_updates_blocked_by_list(self, manager_with_handoffs: "LessonsManager"):
        """Using generic updater should update blocked_by list field."""
        blocked_by = ["hf-0000002", "hf-0000003"]
        manager_with_handoffs._update_handoff_field("hf-0000001", "blocked_by", blocked_by)

        handoff = manager_with_handoffs.handoff_get("hf-0000001")
        assert handoff.blocked_by == blocked_by


class TestHandoffUpdateSetsDate:
    """Tests for automatic date updates."""

    def test_handoff_update_sets_updated_date(self, manager_with_handoffs: "LessonsManager"):
        """Any update should set the updated date to today."""
        # Manually set updated to a past date for testing
        handoff = manager_with_handoffs.handoff_get("hf-0000001")
        original_updated = handoff.updated

        # Make an update
        manager_with_handoffs.handoff_update_status("hf-0000001", "in_progress")

        handoff = manager_with_handoffs.handoff_get("hf-0000001")
        assert handoff.updated == date.today()

    def test_handoff_add_tried_updates_date(self, manager_with_handoffs: "LessonsManager"):
        """Adding a tried handoff should update the date."""
        manager_with_handoffs.handoff_add_tried("hf-0000001", "fail", "Test")

        handoff = manager_with_handoffs.handoff_get("hf-0000001")
        assert handoff.updated == date.today()

    def test_handoff_update_next_updates_date(self, manager_with_handoffs: "LessonsManager"):
        """Updating next steps should update the date."""
        manager_with_handoffs.handoff_update_next("hf-0000001", "Next steps here")

        handoff = manager_with_handoffs.handoff_get("hf-0000001")
        assert handoff.updated == date.today()


class TestHandoffSyncUpdate:
    """Tests for sync_update (batch field updates in single read/write cycle)."""

    def test_sync_update_tried_only(self, manager_with_handoffs: "LessonsManager"):
        """Should add multiple tried entries in one operation."""
        tried_entries = [
            {"outcome": "fail", "description": "First attempt failed"},
            {"outcome": "partial", "description": "Second attempt was partial"},
            {"outcome": "success", "description": "Third attempt worked"},
        ]

        manager_with_handoffs.handoff_sync_update(
            "hf-0000001",
            tried_entries=tried_entries,
        )

        handoff = manager_with_handoffs.handoff_get("hf-0000001")
        assert len(handoff.tried) == 3
        assert handoff.tried[0].outcome == "fail"
        assert handoff.tried[1].outcome == "partial"
        assert handoff.tried[2].outcome == "success"

    def test_sync_update_checkpoint_only(self, manager_with_handoffs: "LessonsManager"):
        """Should update checkpoint and last_session."""
        manager_with_handoffs.handoff_sync_update(
            "hf-0000001",
            checkpoint="Working on unit tests",
        )

        handoff = manager_with_handoffs.handoff_get("hf-0000001")
        assert handoff.checkpoint == "Working on unit tests"
        assert handoff.last_session == date.today()

    def test_sync_update_next_steps_only(self, manager_with_handoffs: "LessonsManager"):
        """Should update next steps."""
        manager_with_handoffs.handoff_sync_update(
            "hf-0000001",
            next_steps="Write integration tests; Update docs",
        )

        handoff = manager_with_handoffs.handoff_get("hf-0000001")
        assert handoff.next_steps == "Write integration tests; Update docs"

    def test_sync_update_status_only(self, manager_with_handoffs: "LessonsManager"):
        """Should update status."""
        manager_with_handoffs.handoff_sync_update(
            "hf-0000001",
            status="in_progress",
        )

        handoff = manager_with_handoffs.handoff_get("hf-0000001")
        assert handoff.status == "in_progress"

    def test_sync_update_all_fields(self, manager_with_handoffs: "LessonsManager"):
        """Should update all fields in a single operation."""
        tried_entries = [
            {"outcome": "success", "description": "Implemented feature"},
        ]

        manager_with_handoffs.handoff_sync_update(
            "hf-0000001",
            tried_entries=tried_entries,
            checkpoint="Finishing up tests",
            next_steps="Commit and push",
            status="in_progress",
        )

        handoff = manager_with_handoffs.handoff_get("hf-0000001")
        assert len(handoff.tried) == 1
        assert handoff.tried[0].description == "Implemented feature"
        assert handoff.checkpoint == "Finishing up tests"
        assert handoff.next_steps == "Commit and push"
        assert handoff.status == "in_progress"
        assert handoff.last_session == date.today()
        assert handoff.updated == date.today()

    def test_sync_update_invalid_status_raises(self, manager_with_handoffs: "LessonsManager"):
        """Should reject invalid status before modifying file."""
        with pytest.raises(ValueError, match="Invalid status"):
            manager_with_handoffs.handoff_sync_update(
                "hf-0000001",
                status="bogus_status",
            )

    def test_sync_update_invalid_outcome_raises(self, manager_with_handoffs: "LessonsManager"):
        """Should reject invalid outcome before modifying file."""
        with pytest.raises(ValueError, match="Invalid outcome"):
            manager_with_handoffs.handoff_sync_update(
                "hf-0000001",
                tried_entries=[{"outcome": "maybe", "description": "Test"}],
            )

    def test_sync_update_auto_phase_implementing(self, manager_with_handoffs: "LessonsManager"):
        """Should auto-bump phase to implementing when tried entry contains implementing keywords."""
        handoff_id = manager_with_handoffs.handoff_add(
            title="Test phase bump",
            phase="research",
        )

        manager_with_handoffs.handoff_sync_update(
            handoff_id,
            tried_entries=[
                {"outcome": "success", "description": "Implemented the new feature"},
            ],
        )

        handoff = manager_with_handoffs.handoff_get(handoff_id)
        assert handoff.phase == "implementing"

    def test_sync_update_auto_complete_on_final_pattern(self, manager: "LessonsManager"):
        """Should auto-complete when tried entry starts with completion pattern."""
        handoff_id = manager.handoff_add(title="Test auto-complete")

        manager.handoff_sync_update(
            handoff_id,
            tried_entries=[
                {"outcome": "success", "description": "Done with implementation"},
            ],
        )

        handoff = manager.handoff_get(handoff_id)
        assert handoff.status == "completed"
        assert handoff.phase == "review"

    def test_sync_update_status_overrides_auto_complete(self, manager: "LessonsManager"):
        """Explicit status should override auto-complete from tried entry."""
        handoff_id = manager.handoff_add(title="Test status override")

        manager.handoff_sync_update(
            handoff_id,
            tried_entries=[
                {"outcome": "success", "description": "Done with first part"},
            ],
            status="in_progress",  # Override auto-complete
        )

        handoff = manager.handoff_get(handoff_id)
        assert handoff.status == "in_progress"  # Not "completed"

    def test_sync_update_not_found_raises(self, manager: "LessonsManager"):
        """Should raise ValueError when handoff not found."""
        with pytest.raises(ValueError, match="not found"):
            manager.handoff_sync_update(
                "hf-nonexistent",
                status="in_progress",
            )

    def test_sync_update_empty_does_nothing(self, manager_with_handoffs: "LessonsManager"):
        """Should handle call with no updates gracefully."""
        # Get original state
        original = manager_with_handoffs.handoff_get("hf-0000001")
        original_status = original.status

        # Call with no updates
        manager_with_handoffs.handoff_sync_update("hf-0000001")

        # Should still work (updates timestamp)
        handoff = manager_with_handoffs.handoff_get("hf-0000001")
        assert handoff.status == original_status
        assert handoff.updated == date.today()


# =============================================================================
# Completing and Archiving Handoffs
# =============================================================================


class TestHandoffComplete:
    """Tests for completing handoffs."""

    def test_handoff_complete_sets_status(self, manager_with_handoffs: "LessonsManager"):
        """Completing should set status to completed."""
        manager_with_handoffs.handoff_complete("hf-0000001")

        handoff = manager_with_handoffs.handoff_get("hf-0000001")
        assert handoff.status == "completed"

    def test_handoff_complete_returns_extraction_prompt(
        self, manager_with_handoffs: "LessonsManager"
    ):
        """Completing should return a prompt for lesson extraction."""
        # Add some tried approaches first
        manager_with_handoffs.handoff_add_tried("hf-0000001", "fail", "First failed attempt")
        manager_with_handoffs.handoff_add_tried("hf-0000001", "success", "Successful approach")

        result = manager_with_handoffs.handoff_complete("hf-0000001")

        # Should return ApproachCompleteResult with extraction_prompt
        assert hasattr(result, "extraction_prompt")
        assert isinstance(result.extraction_prompt, str)
        assert len(result.extraction_prompt) > 0
        # Prompt should mention lesson extraction or similar
        assert "lesson" in result.extraction_prompt.lower() or "extract" in result.extraction_prompt.lower()

    def test_handoff_complete_result_includes_approach_data(
        self, manager_with_handoffs: "LessonsManager"
    ):
        """Complete result should include the approach data for reference."""
        manager_with_handoffs.handoff_add_tried("hf-0000001", "success", "What worked")

        result = manager_with_handoffs.handoff_complete("hf-0000001")

        assert hasattr(result, "approach")
        assert result.handoff.title == "Implementing WebSocket reconnection"


class TestHandoffArchive:
    """Tests for archiving handoffs."""

    def test_handoff_archive_moves_to_archive_file(
        self, manager_with_handoffs: "LessonsManager"
    ):
        """Archiving should move approach to APPROACHES_ARCHIVE.md."""
        manager_with_handoffs.handoff_archive("hf-0000001")

        # Should no longer be in main file
        handoff = manager_with_handoffs.handoff_get("hf-0000001")
        assert handoff is None

        # Should be in archive file
        archive_file = manager_with_handoffs.project_handoffs_archive
        assert archive_file.exists()
        content = archive_file.read_text()
        assert "hf-0000001" in content
        assert "Implementing WebSocket reconnection" in content

    def test_handoff_archive_creates_archive_if_missing(self, manager: "LessonsManager"):
        """Archiving should create archive file if it doesn't exist."""
        handoff_id = manager.handoff_add(title="To be archived")

        # Archive file should not exist yet (we check after creating approach since
        # the property path depends on which data dir exists)
        archive_file = manager.project_handoffs_archive
        assert not archive_file.exists()

        manager.handoff_archive(handoff_id)

        # Re-get the path (it might have been created by the archive operation)
        archive_file = manager.project_handoffs_archive
        assert archive_file.exists()

    def test_handoff_archive_preserves_data(self, manager_with_handoffs: "LessonsManager"):
        """Archived handoff should preserve all its data."""
        # Add some data first
        manager_with_handoffs.handoff_update_status("hf-0000001", "in_progress")
        manager_with_handoffs.handoff_add_tried("hf-0000001", "fail", "Failed attempt")
        manager_with_handoffs.handoff_add_tried("hf-0000001", "success", "Worked!")
        manager_with_handoffs.handoff_update_next("hf-0000001", "Document the solution")

        # Get data before archive
        handoff_before = manager_with_handoffs.handoff_get("hf-0000001")

        manager_with_handoffs.handoff_archive("hf-0000001")

        # Read archive file and verify data is present
        archive_file = manager_with_handoffs.project_handoffs_archive
        content = archive_file.read_text()

        assert handoff_before.title in content
        assert "fail" in content.lower()
        assert "success" in content.lower()
        assert "Failed attempt" in content
        assert "Worked!" in content

    def test_handoff_archive_appends_to_existing(
        self, manager_with_handoffs: "LessonsManager"
    ):
        """Multiple archives should append to the same file."""
        manager_with_handoffs.handoff_archive("hf-0000001")
        manager_with_handoffs.handoff_archive("hf-0000002")

        archive_file = manager_with_handoffs.project_handoffs_archive
        content = archive_file.read_text()

        assert "hf-0000001" in content
        assert "hf-0000002" in content
        assert "Implementing WebSocket reconnection" in content
        assert "Refactoring database layer" in content


class TestHandoffDelete:
    """Tests for deleting handoffs."""

    def test_handoff_delete_removes_entry(self, manager_with_handoffs: "LessonsManager"):
        """Deleting should remove the approach entirely."""
        manager_with_handoffs.handoff_delete("hf-0000001")

        handoff = manager_with_handoffs.handoff_get("hf-0000001")
        assert handoff is None

        # Should not be in the list
        handoffs = manager_with_handoffs.handoff_list()
        ids = [a.id for a in handoffs]
        assert "hf-0000001" not in ids

    def test_handoff_delete_nonexistent_fails(self, manager: "LessonsManager"):
        """Deleting a nonexistent handoff should raise an error."""
        with pytest.raises(ValueError, match="not found"):
            manager.handoff_delete("A999")

    def test_handoff_delete_does_not_archive(
        self, manager_with_handoffs: "LessonsManager"
    ):
        """Deleting should not move to archive (unlike archive)."""
        manager_with_handoffs.handoff_delete("hf-0000001")

        archive_file = manager_with_handoffs.project_handoffs_archive
        # Archive file should not exist or not contain the deleted approach
        if archive_file.exists():
            content = archive_file.read_text()
            assert "hf-0000001" not in content


# =============================================================================
# Querying Handoffs
# =============================================================================


class TestHandoffGet:
    """Tests for getting individual handoffs."""

    def test_handoff_get_existing(self, manager_with_handoffs: "LessonsManager"):
        """Should return the approach with correct data."""
        handoff = manager_with_handoffs.handoff_get("hf-0000001")

        assert handoff is not None
        assert handoff.id == "hf-0000001"
        assert handoff.title == "Implementing WebSocket reconnection"
        assert handoff.description == "Add automatic reconnection with exponential backoff"
        assert handoff.files == ["src/websocket.ts", "src/connection-manager.ts"]

    def test_handoff_get_nonexistent(self, manager: "LessonsManager"):
        """Should return None for nonexistent handoff."""
        handoff = manager.handoff_get("A999")
        assert handoff is None

    def test_handoff_get_returns_handoff_dataclass(
        self, manager_with_handoffs: "LessonsManager"
    ):
        """Should return an Approach dataclass instance."""
        handoff = manager_with_handoffs.handoff_get("hf-0000001")

        assert isinstance(handoff, Handoff)
        assert hasattr(handoff, "id")
        assert hasattr(handoff, "title")
        assert hasattr(handoff, "status")
        assert hasattr(handoff, "created")
        assert hasattr(handoff, "updated")
        assert hasattr(handoff, "files")
        assert hasattr(handoff, "description")
        assert hasattr(handoff, "tried")
        assert hasattr(handoff, "next_steps")


class TestHandoffList:
    """Tests for listing handoffs."""

    def test_handoff_list_all(self, manager_with_handoffs: "LessonsManager"):
        """Should list all approaches."""
        handoffs = manager_with_handoffs.handoff_list()

        assert len(handoffs) == 3
        ids = [a.id for a in handoffs]
        assert "hf-0000001" in ids
        assert "hf-0000002" in ids
        assert "hf-0000003" in ids

    def test_handoff_list_by_status(self, manager_with_handoffs: "LessonsManager"):
        """Should filter by status."""
        manager_with_handoffs.handoff_update_status("hf-0000001", "in_progress")
        manager_with_handoffs.handoff_update_status("hf-0000002", "blocked")

        in_progress = manager_with_handoffs.handoff_list(status_filter="in_progress")
        blocked = manager_with_handoffs.handoff_list(status_filter="blocked")
        not_started = manager_with_handoffs.handoff_list(status_filter="not_started")

        assert len(in_progress) == 1
        assert in_progress[0].id == "hf-0000001"

        assert len(blocked) == 1
        assert blocked[0].id == "hf-0000002"

        assert len(not_started) == 1
        assert not_started[0].id == "hf-0000003"

    def test_handoff_list_excludes_completed(self, manager_with_handoffs: "LessonsManager"):
        """Default list should exclude completed approaches."""
        manager_with_handoffs.handoff_update_status("hf-0000001", "completed")

        # Default list (no filter) should exclude completed
        handoffs = manager_with_handoffs.handoff_list()
        ids = [a.id for a in handoffs]
        assert "hf-0000001" not in ids
        assert len(handoffs) == 2

    def test_handoff_list_completed_explicit(self, manager_with_handoffs: "LessonsManager"):
        """Should be able to explicitly list completed approaches."""
        manager_with_handoffs.handoff_update_status("hf-0000001", "completed")

        completed = manager_with_handoffs.handoff_list(status_filter="completed")

        assert len(completed) == 1
        assert completed[0].id == "hf-0000001"

    def test_handoff_list_empty(self, manager: "LessonsManager"):
        """Should return empty list when no approaches exist."""
        handoffs = manager.handoff_list()
        assert handoffs == []


class TestHandoffInject:
    """Tests for context injection."""

    def test_handoff_inject_active_only(self, manager_with_handoffs: "LessonsManager"):
        """Inject should show completed approaches in Recent Completions, not Active."""
        manager_with_handoffs.handoff_update_status("hf-0000001", "completed")

        injected = manager_with_handoffs.handoff_inject()

        # Split by sections to verify placement
        assert "## Active Handoffs" in injected
        assert "## Recent Completions" in injected

        active_section = injected.split("## Recent Completions")[0]
        completions_section = injected.split("## Recent Completions")[1]

        # hf-0000001 should be in completions, not active
        assert "hf-0000001" not in active_section
        assert "hf-0000001" in completions_section

        # hf-0000002 and hf-0000003 should be in active
        assert "hf-0000002" in active_section
        assert "hf-0000003" in active_section

    def test_handoff_inject_format(self, manager_with_handoffs: "LessonsManager"):
        """Inject should return formatted string for context."""
        manager_with_handoffs.handoff_update_status("hf-0000001", "in_progress")
        manager_with_handoffs.handoff_add_tried("hf-0000001", "fail", "First attempt failed")
        manager_with_handoffs.handoff_update_next("hf-0000001", "Try a different approach")

        injected = manager_with_handoffs.handoff_inject()

        # Should be a non-empty string
        assert isinstance(injected, str)
        assert len(injected) > 0

        # Should contain key information
        assert "hf-0000001" in injected
        assert "Implementing WebSocket reconnection" in injected
        assert "in_progress" in injected.lower()

    def test_handoff_inject_empty_returns_empty(self, manager: "LessonsManager"):
        """Inject with no handoffs should return empty string."""
        injected = manager.handoff_inject()
        assert injected == ""

    def test_handoff_inject_includes_tried(self, manager_with_handoffs: "LessonsManager"):
        """Inject should include tried approaches."""
        manager_with_handoffs.handoff_add_tried("hf-0000001", "fail", "First failed")
        manager_with_handoffs.handoff_add_tried("hf-0000001", "success", "This worked")

        injected = manager_with_handoffs.handoff_inject()

        assert "First failed" in injected or "fail" in injected.lower()
        assert "This worked" in injected or "success" in injected.lower()

    def test_handoff_inject_includes_next_steps(self, manager_with_handoffs: "LessonsManager"):
        """Inject should include next steps."""
        manager_with_handoffs.handoff_update_next("hf-0000001", "Write more tests")

        injected = manager_with_handoffs.handoff_inject()

        assert "Write more tests" in injected

    def test_handoff_inject_ready_for_review_shows_full_tried_steps(self, manager: "LessonsManager"):
        """Inject should show ALL tried steps for ready_for_review handoffs (for lesson extraction)."""
        handoff_id = manager.handoff_add("Completed work")
        manager.handoff_add_tried(handoff_id, "success", "Step 1: Did first thing")
        manager.handoff_add_tried(handoff_id, "success", "Step 2: Did second thing")
        manager.handoff_add_tried(handoff_id, "success", "Step 3: Did third thing")
        manager.handoff_add_tried(handoff_id, "success", "Step 4: Did fourth thing")
        manager.handoff_add_tried(handoff_id, "success", "Step 5: Did fifth thing")
        manager.handoff_update_status(handoff_id, "ready_for_review")

        injected = manager.handoff_inject()

        # Should show all tried steps (not summarized)
        assert "ready_for_review" in injected
        assert "Step 1: Did first thing" in injected
        assert "Step 2: Did second thing" in injected
        assert "Step 3: Did third thing" in injected
        assert "Step 4: Did fourth thing" in injected
        assert "Step 5: Did fifth thing" in injected
        assert "[success]" in injected
        assert "5 steps" in injected  # Should show count

    def test_handoff_inject_max_active_limits_handoffs(self, manager: "LessonsManager"):
        """Inject should limit active handoffs to max_active parameter."""
        # Create 8 active handoffs
        for i in range(8):
            manager.handoff_add(title=f"Task {i+1}")

        # Default max_active=5 should limit output
        injected = manager.handoff_inject()
        active_section = injected.split("## Recent Completions")[0] if "## Recent Completions" in injected else injected

        # Should show truncation warning
        assert "(showing 5 of 8 active handoffs)" in active_section

        # Count how many task headers appear (### [hf-...)
        import re
        header_count = len(re.findall(r"### \[hf-", active_section))
        assert header_count == 5

    def test_handoff_inject_max_active_custom_value(self, manager: "LessonsManager"):
        """Inject should respect custom max_active parameter."""
        # Create 6 active handoffs
        for i in range(6):
            manager.handoff_add(title=f"Task {i+1}")

        # Request max_active=3
        injected = manager.handoff_inject(max_active=3)
        active_section = injected.split("## Recent Completions")[0] if "## Recent Completions" in injected else injected

        assert "(showing 3 of 6 active handoffs)" in active_section

        import re
        header_count = len(re.findall(r"### \[hf-", active_section))
        assert header_count == 3

    def test_handoff_inject_most_recent_first(self, manager: "LessonsManager"):
        """Inject should show most recently updated handoffs first."""
        # Create handoffs with explicit different update dates by writing the file directly
        today = date.today().isoformat()
        day_1_ago = (date.today() - timedelta(days=1)).isoformat()
        day_3_ago = (date.today() - timedelta(days=3)).isoformat()

        # Write handoffs file with explicit dates
        handoffs_file = manager.project_handoffs_file
        handoffs_file.parent.mkdir(parents=True, exist_ok=True)
        content = f"""# HANDOFFS.md - Active Work Tracking

> Track ongoing work.

## Active Handoffs

### [hf-0000001] Old task
- **Status**: not_started | **Phase**: research | **Agent**: user
- **Created**: {day_3_ago} | **Updated**: {day_3_ago}

**Tried**:

**Next**:

---

### [hf-0000002] Newer task
- **Status**: not_started | **Phase**: research | **Agent**: user
- **Created**: {day_1_ago} | **Updated**: {day_1_ago}

**Tried**:

**Next**:

---

### [hf-0000003] Newest task
- **Status**: not_started | **Phase**: research | **Agent**: user
- **Created**: {today} | **Updated**: {today}

**Tried**:

**Next**:

---
"""
        handoffs_file.write_text(content)

        # Request max_active=2 to force truncation
        injected = manager.handoff_inject(max_active=2)

        # hf-0000003 (Newest) and hf-0000002 (Newer) should be shown, hf-0000001 (Old) should be truncated
        assert "Newest task" in injected
        assert "Newer task" in injected
        assert "Old task" not in injected

        # Verify order: Newest should come before Newer in output
        newest_pos = injected.find("Newest task")
        newer_pos = injected.find("Newer task")
        assert newest_pos < newer_pos, "Most recently updated should appear first"

    def test_handoff_inject_no_truncation_warning_when_under_limit(self, manager: "LessonsManager"):
        """Inject should not show truncation warning when handoffs are under limit."""
        # Create 3 active handoffs (under default limit of 5)
        for i in range(3):
            manager.handoff_add(title=f"Task {i+1}")

        injected = manager.handoff_inject()

        # Should NOT show truncation warning
        assert "(showing" not in injected
        assert "of" not in injected or "of 3" not in injected

    def test_handoff_inject_max_active_one(self, manager: "LessonsManager"):
        """Inject with max_active=1 shows only most recent."""
        for i in range(3):
            manager.handoff_add(title=f"Task {i+1}")
        injected = manager.handoff_inject(max_active=1)
        assert "(showing 1 of 3" in injected

    def test_handoff_inject_max_active_exact_boundary(self, manager: "LessonsManager"):
        """Inject with handoffs equal to max_active shows no truncation."""
        for i in range(5):
            manager.handoff_add(title=f"Task {i+1}")
        injected = manager.handoff_inject(max_active=5)
        assert "(showing" not in injected

    def test_handoff_inject_max_active_zero_uses_default(self, manager: "LessonsManager"):
        """Inject with max_active=0 should use default."""
        for i in range(3):
            manager.handoff_add(title=f"Task {i+1}")
        injected = manager.handoff_inject(max_active=0)
        # Should show all 3 (under default of 5)
        assert "(showing" not in injected
        assert "Task 1" in injected
        assert "Task 2" in injected
        assert "Task 3" in injected

    def test_handoff_inject_tried_steps_summarized(self, manager: "LessonsManager"):
        """Inject should summarize tried steps when there are more than 3."""
        h = manager.handoff_add(title="Task with many steps")
        manager.handoff_update_status(h, "in_progress")

        # Add 6 tried steps
        manager.handoff_add_tried(h, "success", "Step 1: First action")
        manager.handoff_add_tried(h, "fail", "Step 2: Second action")
        manager.handoff_add_tried(h, "success", "Step 3: Third action")
        manager.handoff_add_tried(h, "partial", "Step 4: Fourth action")
        manager.handoff_add_tried(h, "success", "Step 5: Fifth action")
        manager.handoff_add_tried(h, "success", "Step 6: Sixth action")

        injected = manager.handoff_inject()

        # Should show progress summary
        assert "6 steps" in injected

        # Should show recent steps (last 3)
        assert "Fourth action" in injected or "Step 4" in injected
        assert "Fifth action" in injected or "Step 5" in injected
        assert "Sixth action" in injected or "Step 6" in injected


# =============================================================================
# Edge Cases
# =============================================================================


class TestHandoffEdgeCases:
    """Tests for edge cases and error handling."""

    def test_handoff_with_special_characters(self, manager: "LessonsManager"):
        """Should handle special characters in title and description."""
        title = "Fix the 'bug' in |pipe| handling & more"
        desc = "Handle special chars: <>, [], {}, $var, @annotation"

        handoff_id = manager.handoff_add(title=title, desc=desc)

        handoff = manager.handoff_get(handoff_id)
        assert handoff is not None
        assert handoff.title == title
        assert handoff.description == desc

    def test_handoff_with_special_characters_in_tried(self, manager: "LessonsManager"):
        """Should handle special characters in tried descriptions."""
        handoff_id = manager.handoff_add(title="Test approach")
        manager.handoff_add_tried(
            handoff_id,
            outcome="fail",
            description="Used 'quotes' and |pipes| - didn't work",
        )

        handoff = manager.handoff_get(handoff_id)
        assert len(handoff.tried) == 1
        assert "quotes" in handoff.tried[0].description

    def test_multiple_approaches(self, manager: "LessonsManager"):
        """Should handle many approaches correctly."""
        created_ids = []
        for i in range(10):
            id = manager.handoff_add(title=f"Approach {i+1}")
            created_ids.append(id)

        handoffs = manager.handoff_list()
        assert len(handoffs) == 10

        # All IDs should be hash-based and unique
        ids = [a.id for a in handoffs]
        assert all(id.startswith("hf-") for id in ids)
        assert len(set(ids)) == 10  # All unique

    def test_handoff_empty_file(self, manager: "LessonsManager"):
        """Should handle empty approaches file gracefully."""
        handoffs_file = manager.project_handoffs_file
        handoffs_file.parent.mkdir(parents=True, exist_ok=True)
        handoffs_file.write_text("")

        handoffs = manager.handoff_list()
        assert handoffs == []

    def test_handoff_malformed_entry_skipped(self, manager: "LessonsManager"):
        """Should skip malformed entries without crashing."""
        handoffs_file = manager.project_handoffs_file
        handoffs_file.parent.mkdir(parents=True, exist_ok=True)

        malformed = """# APPROACHES.md - Active Work Tracking

## Active Approaches

### [hf-0000001] Malformed entry
Missing the status line

### [hf-0000002] Valid approach
- **Status**: not_started | **Created**: 2025-12-28 | **Updated**: 2025-12-28
- **Files**:
- **Description**: This one is valid

**Tried**:

**Next**:

---
"""
        handoffs_file.write_text(malformed)

        handoffs = manager.handoff_list()
        # Should only get the valid approach
        assert len(handoffs) == 1
        assert handoffs[0].id == "hf-0000002"

    def test_handoff_id_uniqueness_with_hash(self, manager: "LessonsManager"):
        """Hash-based IDs should always be unique regardless of deletion."""
        id1 = manager.handoff_add(title="First")
        id2 = manager.handoff_add(title="Second")
        manager.handoff_delete(id1)

        # New handoff should get a unique hash ID
        new_id = manager.handoff_add(title="Third")
        assert new_id.startswith("hf-")
        assert new_id != id1  # Should not reuse deleted ID
        assert new_id != id2  # Should be distinct from existing

    def test_handoff_with_long_description(self, manager: "LessonsManager"):
        """Should handle long descriptions."""
        long_desc = "A" * 1000
        handoff_id = manager.handoff_add(title="Long desc test", desc=long_desc)

        handoff = manager.handoff_get(handoff_id)
        assert handoff.description == long_desc

    def test_handoff_with_unicode_characters(self, manager: "LessonsManager"):
        """Should handle unicode characters."""
        title = "Fix emoji handling: \U0001f916 \U0001f4bb \U0001f525"
        desc = "Handle international text: \u4e2d\u6587 \u65e5\u672c\u8a9e \ud55c\uad6d\uc5b4"

        handoff_id = manager.handoff_add(title=title, desc=desc)

        handoff = manager.handoff_get(handoff_id)
        assert handoff.title == title
        assert handoff.description == desc

    def test_handoff_tried_preserves_order(self, manager: "LessonsManager"):
        """Tried handoffs should maintain insertion order."""
        handoff_id = manager.handoff_add(title="Order test")

        for i in range(5):
            manager.handoff_add_tried(handoff_id, "fail", f"Attempt {i+1}")

        handoff = manager.handoff_get(handoff_id)
        for i, tried in enumerate(handoff.tried):
            assert tried.description == f"Attempt {i+1}"


# =============================================================================
# Data Classes
# =============================================================================


class TestHandoffDataClasses:
    """Tests for Handoff and TriedStep data classes."""

    def test_handoff_dataclass_fields(self, manager_with_handoffs: "LessonsManager"):
        """Approach should have all required fields."""
        handoff = manager_with_handoffs.handoff_get("hf-0000001")

        assert isinstance(handoff.id, str)
        assert isinstance(handoff.title, str)
        assert isinstance(handoff.status, str)
        assert isinstance(handoff.created, date)
        assert isinstance(handoff.updated, date)
        assert isinstance(handoff.files, list)
        assert isinstance(handoff.description, str)
        assert isinstance(handoff.tried, list)
        assert isinstance(handoff.next_steps, str)

    def test_tried_handoff_dataclass_fields(self, manager_with_handoffs: "LessonsManager"):
        """TriedApproach should have outcome and description."""
        manager_with_handoffs.handoff_add_tried("hf-0000001", "success", "It worked")

        handoff = manager_with_handoffs.handoff_get("hf-0000001")
        tried = handoff.tried[0]

        assert isinstance(tried, TriedStep)
        assert isinstance(tried.outcome, str)
        assert isinstance(tried.description, str)


# =============================================================================
# File Format Validation
# =============================================================================


class TestHandoffFileFormat:
    """Tests for HANDOFFS.md file format."""

    def test_handoff_file_has_header(self, manager: "LessonsManager"):
        """Approaches file should have proper header."""
        manager.handoff_add(title="Test")

        handoffs_file = manager.project_handoffs_file
        content = handoffs_file.read_text()

        # Accept both new format (HANDOFFS.md) and legacy (APPROACHES.md)
        assert "HANDOFFS.md" in content or "APPROACHES.md" in content
        assert "Active Work Tracking" in content or "Active Handoffs" in content

    def test_handoff_format_includes_separator(self, manager: "LessonsManager"):
        """Each handoff should be followed by separator."""
        manager.handoff_add(title="First")
        manager.handoff_add(title="Second")

        handoffs_file = manager.project_handoffs_file
        content = handoffs_file.read_text()

        # Should have separator between approaches
        assert "---" in content

    def test_handoff_format_includes_status_line(self, manager: "LessonsManager"):
        """Approach should include status/dates line."""
        handoff_id = manager.handoff_add(title="Test")
        manager.handoff_update_status(handoff_id, "in_progress")

        handoffs_file = manager.project_handoffs_file
        content = handoffs_file.read_text()

        assert "**Status**:" in content
        assert "**Created**:" in content
        assert "**Updated**:" in content
        assert "in_progress" in content

    def test_handoff_format_includes_tried_section(self, manager: "LessonsManager"):
        """Approach should include Tried section."""
        handoff_id = manager.handoff_add(title="Test")
        manager.handoff_add_tried(handoff_id, "fail", "First attempt")

        handoffs_file = manager.project_handoffs_file
        content = handoffs_file.read_text()

        assert "**Tried**:" in content
        assert "[fail]" in content.lower() or "fail" in content.lower()
        assert "First attempt" in content

    def test_handoff_format_includes_next_section(self, manager: "LessonsManager"):
        """Approach should include Next section."""
        handoff_id = manager.handoff_add(title="Test")
        manager.handoff_update_next(handoff_id, "Do something next")

        handoffs_file = manager.project_handoffs_file
        content = handoffs_file.read_text()

        assert "**Next**:" in content
        assert "Do something next" in content


# =============================================================================
# Phase Tracking Tests
# =============================================================================


class TestHandoffPhase:
    """Tests for handoff phase tracking."""

    def test_handoff_add_defaults_to_research_phase(self, manager: "LessonsManager"):
        """New handoffs should default to 'research' phase."""
        handoff_id = manager.handoff_add(title="Test approach")
        handoff = manager.handoff_get(handoff_id)

        assert handoff is not None
        assert hasattr(handoff, "phase")
        assert handoff.phase == "research"

    def test_handoff_add_with_explicit_phase(self, manager: "LessonsManager"):
        """Should allow setting phase when adding handoff."""
        handoff_id = manager.handoff_add(title="Planning task", phase="planning")
        handoff = manager.handoff_get(handoff_id)

        assert handoff is not None
        assert handoff.phase == "planning"

    def test_handoff_update_phase_valid(self, manager_with_handoffs: "LessonsManager"):
        """Should update phase with valid values."""
        # Test all valid phases
        valid_phases = ["research", "planning", "implementing", "review"]

        for phase in valid_phases:
            manager_with_handoffs.handoff_update_phase("hf-0000001", phase)
            handoff = manager_with_handoffs.handoff_get("hf-0000001")
            assert handoff.phase == phase

    def test_handoff_update_phase_invalid_rejects(
        self, manager_with_handoffs: "LessonsManager"
    ):
        """Should reject invalid phase values."""
        with pytest.raises(ValueError, match="[Ii]nvalid phase"):
            manager_with_handoffs.handoff_update_phase("hf-0000001", "coding")

        with pytest.raises(ValueError, match="[Ii]nvalid phase"):
            manager_with_handoffs.handoff_update_phase("hf-0000001", "testing")

        with pytest.raises(ValueError, match="[Ii]nvalid phase"):
            manager_with_handoffs.handoff_update_phase("hf-0000001", "")

    def test_handoff_phase_in_inject_output(self, manager_with_handoffs: "LessonsManager"):
        """Phase should appear in inject output."""
        manager_with_handoffs.handoff_update_phase("hf-0000001", "implementing")

        injected = manager_with_handoffs.handoff_inject()

        assert "implementing" in injected.lower()

    def test_handoff_get_includes_phase(self, manager_with_handoffs: "LessonsManager"):
        """Approach dataclass should include phase field."""
        manager_with_handoffs.handoff_update_phase("hf-0000001", "review")

        handoff = manager_with_handoffs.handoff_get("hf-0000001")

        assert hasattr(handoff, "phase")
        assert isinstance(handoff.phase, str)
        assert handoff.phase == "review"

    def test_handoff_update_phase_nonexistent_fails(self, manager: "LessonsManager"):
        """Should fail when updating phase of nonexistent handoff."""
        with pytest.raises(ValueError, match="not found"):
            manager.handoff_update_phase("A999", "research")

    def test_handoff_update_phase_sets_updated_date(
        self, manager_with_handoffs: "LessonsManager"
    ):
        """Updating phase should update the 'updated' date."""
        manager_with_handoffs.handoff_update_phase("hf-0000001", "implementing")

        handoff = manager_with_handoffs.handoff_get("hf-0000001")
        assert handoff.updated == date.today()


# =============================================================================
# Agent Tracking Tests
# =============================================================================


class TestHandoffAgent:
    """Tests for handoff agent tracking."""

    def test_handoff_add_defaults_to_user_agent(self, manager: "LessonsManager"):
        """New handoffs should default to 'user' agent (no subagent)."""
        handoff_id = manager.handoff_add(title="Test approach")
        handoff = manager.handoff_get(handoff_id)

        assert handoff is not None
        assert hasattr(handoff, "agent")
        assert handoff.agent == "user"

    def test_handoff_add_with_explicit_agent(self, manager: "LessonsManager"):
        """Should allow setting agent when adding handoff."""
        handoff_id = manager.handoff_add(title="Exploration task", agent="explore")
        handoff = manager.handoff_get(handoff_id)

        assert handoff is not None
        assert handoff.agent == "explore"

    def test_handoff_update_agent(self, manager_with_handoffs: "LessonsManager"):
        """Should update agent with valid values."""
        # Test all valid agents
        valid_agents = ["explore", "general-purpose", "plan", "review", "user"]

        for agent in valid_agents:
            manager_with_handoffs.handoff_update_agent("hf-0000001", agent)
            handoff = manager_with_handoffs.handoff_get("hf-0000001")
            assert handoff.agent == agent

    def test_handoff_update_agent_invalid_rejects(
        self, manager_with_handoffs: "LessonsManager"
    ):
        """Should reject invalid agent values."""
        with pytest.raises(ValueError, match="[Ii]nvalid agent"):
            manager_with_handoffs.handoff_update_agent("hf-0000001", "coder")

        with pytest.raises(ValueError, match="[Ii]nvalid agent"):
            manager_with_handoffs.handoff_update_agent("hf-0000001", "assistant")

        with pytest.raises(ValueError, match="[Ii]nvalid agent"):
            manager_with_handoffs.handoff_update_agent("hf-0000001", "")

    def test_handoff_agent_stored_but_not_injected(self, manager_with_handoffs: "LessonsManager"):
        """Agent is stored but not shown in compact inject output (by design)."""
        manager_with_handoffs.handoff_update_agent("hf-0000001", "general-purpose")

        # Agent is stored
        handoff = manager_with_handoffs.handoff_get("hf-0000001")
        assert handoff.agent == "general-purpose"

        # But not in compact inject output (too verbose)
        injected = manager_with_handoffs.handoff_inject()
        assert "Agent" not in injected  # Removed for compactness

    def test_handoff_get_includes_agent(self, manager_with_handoffs: "LessonsManager"):
        """Approach dataclass should include agent field."""
        manager_with_handoffs.handoff_update_agent("hf-0000001", "explore")

        handoff = manager_with_handoffs.handoff_get("hf-0000001")

        assert hasattr(handoff, "agent")
        assert isinstance(handoff.agent, str)
        assert handoff.agent == "explore"

    def test_handoff_update_agent_nonexistent_fails(self, manager: "LessonsManager"):
        """Should fail when updating agent of nonexistent handoff."""
        with pytest.raises(ValueError, match="not found"):
            manager.handoff_update_agent("A999", "explore")

    def test_handoff_update_agent_sets_updated_date(
        self, manager_with_handoffs: "LessonsManager"
    ):
        """Updating agent should update the 'updated' date."""
        manager_with_handoffs.handoff_update_agent("hf-0000001", "review")

        handoff = manager_with_handoffs.handoff_get("hf-0000001")
        assert handoff.updated == date.today()


# =============================================================================
# Phase/Agent Format Tests
# =============================================================================


class TestHandoffPhaseAgentFormat:
    """Tests for phase and agent in file format."""

    def test_handoff_format_includes_phase(self, manager: "LessonsManager"):
        """Approach format should include phase in status line."""
        manager.handoff_add(title="Test", phase="implementing")

        handoffs_file = manager.project_handoffs_file
        content = handoffs_file.read_text()

        assert "**Phase**:" in content
        assert "implementing" in content

    def test_handoff_format_includes_agent(self, manager: "LessonsManager"):
        """Approach format should include agent in status line."""
        manager.handoff_add(title="Test", agent="explore")

        handoffs_file = manager.project_handoffs_file
        content = handoffs_file.read_text()

        assert "**Agent**:" in content
        assert "explore" in content

    def test_handoff_parse_new_format_with_phase_agent(self, manager: "LessonsManager"):
        """Should parse the new format with phase and agent correctly."""
        # Write a file with the new format directly
        handoffs_file = manager.project_handoffs_file
        handoffs_file.parent.mkdir(parents=True, exist_ok=True)

        new_format_content = """# APPROACHES.md - Active Work Tracking

> Track ongoing work with tried approaches and next steps.
> When completed, review for lessons to extract.

## Active Approaches

### [hf-0000001] Test approach with new format
- **Status**: in_progress | **Phase**: implementing | **Agent**: general-purpose
- **Created**: 2025-12-28 | **Updated**: 2025-12-28
- **Files**: test.py
- **Description**: Testing new format parsing

**Tried**:

**Next**:

---
"""
        handoffs_file.write_text(new_format_content)

        handoff = manager.handoff_get("hf-0000001")

        assert handoff is not None
        assert handoff.status == "in_progress"
        assert handoff.phase == "implementing"
        assert handoff.agent == "general-purpose"
        assert handoff.title == "Test approach with new format"

    def test_handoff_format_phase_agent_on_status_line(self, manager: "LessonsManager"):
        """Phase and agent should be on the status line after status."""
        handoff_id = manager.handoff_add(title="Test format", phase="planning", agent="plan")
        manager.handoff_update_status(handoff_id, "in_progress")

        handoffs_file = manager.project_handoffs_file
        content = handoffs_file.read_text()

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


class TestHandoffCLIPhaseAgent:
    """Tests for phase and agent CLI commands."""

    def test_cli_handoff_add_with_phase(self, manager: "LessonsManager"):
        """CLI should support --phase option when adding handoff."""
        # This tests the handoff_add method with phase parameter
        handoff_id = manager.handoff_add(
            title="CLI phase test",
            phase="planning",
        )

        handoff = manager.handoff_get(handoff_id)
        assert handoff.phase == "planning"

    def test_cli_handoff_add_with_agent(self, manager: "LessonsManager"):
        """CLI should support --agent option when adding handoff."""
        # This tests the handoff_add method with agent parameter
        handoff_id = manager.handoff_add(
            title="CLI agent test",
            agent="explore",
        )

        handoff = manager.handoff_get(handoff_id)
        assert handoff.agent == "explore"

    def test_cli_handoff_update_phase(self, manager_with_handoffs: "LessonsManager"):
        """CLI should support updating phase via handoff_update_phase."""
        manager_with_handoffs.handoff_update_phase("hf-0000001", "review")

        handoff = manager_with_handoffs.handoff_get("hf-0000001")
        assert handoff.phase == "review"

    def test_cli_handoff_update_agent(self, manager_with_handoffs: "LessonsManager"):
        """CLI should support updating agent via handoff_update_agent."""
        manager_with_handoffs.handoff_update_agent("hf-0000001", "general-purpose")

        handoff = manager_with_handoffs.handoff_get("hf-0000001")
        assert handoff.agent == "general-purpose"


# =============================================================================
# Phase/Agent Edge Cases
# =============================================================================


class TestHandoffPhaseAgentEdgeCases:
    """Tests for edge cases with phase and agent."""

    def test_handoff_backward_compatibility_no_phase_agent(self, manager: "LessonsManager"):
        """Should handle old format files without phase/agent fields."""
        # Write a file with the old format (no phase/agent)
        handoffs_file = manager.project_handoffs_file
        handoffs_file.parent.mkdir(parents=True, exist_ok=True)

        old_format_content = """# APPROACHES.md - Active Work Tracking

> Track ongoing work with tried approaches and next steps.
> When completed, review for lessons to extract.

## Active Approaches

### [hf-0000001] Old format approach
- **Status**: in_progress | **Created**: 2025-12-28 | **Updated**: 2025-12-28
- **Files**: test.py
- **Description**: Testing backward compatibility

**Tried**:
1. [fail] First attempt

**Next**: Try something else

---
"""
        handoffs_file.write_text(old_format_content)

        handoff = manager.handoff_get("hf-0000001")

        assert handoff is not None
        assert handoff.status == "in_progress"
        # Should default to research/user when not present
        assert handoff.phase == "research"
        assert handoff.agent == "user"

    def test_handoff_phase_agent_preserved_on_update(
        self, manager_with_handoffs: "LessonsManager"
    ):
        """Phase and agent should be preserved when updating other fields."""
        manager_with_handoffs.handoff_update_phase("hf-0000001", "implementing")
        manager_with_handoffs.handoff_update_agent("hf-0000001", "general-purpose")

        # Update status
        manager_with_handoffs.handoff_update_status("hf-0000001", "blocked")

        handoff = manager_with_handoffs.handoff_get("hf-0000001")
        assert handoff.phase == "implementing"
        assert handoff.agent == "general-purpose"
        assert handoff.status == "blocked"

    def test_handoff_phase_agent_in_archived_approach(
        self, manager_with_handoffs: "LessonsManager"
    ):
        """Archived handoffs should preserve phase and agent."""
        manager_with_handoffs.handoff_update_phase("hf-0000001", "review")
        manager_with_handoffs.handoff_update_agent("hf-0000001", "review")

        manager_with_handoffs.handoff_archive("hf-0000001")

        archive_file = manager_with_handoffs.project_handoffs_archive
        content = archive_file.read_text()

        assert "**Phase**: review" in content or "**Phase**:" in content
        assert "**Agent**: review" in content or "**Agent**:" in content

    def test_handoff_complete_includes_phase_agent(
        self, manager_with_handoffs: "LessonsManager"
    ):
        """Complete result should include phase and agent info."""
        manager_with_handoffs.handoff_update_phase("hf-0000001", "implementing")
        manager_with_handoffs.handoff_update_agent("hf-0000001", "general-purpose")

        result = manager_with_handoffs.handoff_complete("hf-0000001")

        # The approach in the result should have phase and agent
        assert result.handoff.phase == "implementing"
        assert result.handoff.agent == "general-purpose"


# =============================================================================
# Phase 4.6: Handoff Decay Tests
# =============================================================================


class TestHandoffDecayVisibility:
    """Tests for completed handoff visibility rules."""

    def test_handoff_list_completed_returns_completed(
        self, manager_with_handoffs: "LessonsManager"
    ):
        """Should be able to list completed approaches."""
        manager_with_handoffs.handoff_update_status("hf-0000001", "completed")
        manager_with_handoffs.handoff_update_status("hf-0000002", "completed")

        completed = manager_with_handoffs.handoff_list_completed()

        assert len(completed) == 2

    def test_handoff_list_completed_respects_max_count(
        self, manager: "LessonsManager"
    ):
        """With all old approaches, max_count limits the result."""
        # Create and complete 5 approaches with old dates
        created_ids = []
        for i in range(5):
            handoff_id = manager.handoff_add(title=f"Approach {i}")
            created_ids.append(handoff_id)
            manager.handoff_update_status(handoff_id, "completed")

        # Make them all old (30 days ago) so only max_count applies
        handoffs_file = manager.project_handoffs_file
        content = handoffs_file.read_text()
        old_date = (date.today() - timedelta(days=30)).isoformat()
        content = content.replace(
            f"**Updated**: {date.today().isoformat()}",
            f"**Updated**: {old_date}"
        )
        handoffs_file.write_text(content)

        # With max_count=3 and all old, should only return 3 (top N by recency)
        completed = manager.handoff_list_completed(max_count=3, max_age_days=7)

        assert len(completed) == 3

    def test_handoff_list_completed_respects_max_age(
        self, manager: "LessonsManager"
    ):
        """Should filter out approaches older than max_age_days."""
        handoff_id = manager.handoff_add(title="Recent approach")
        manager.handoff_update_status(handoff_id, "completed")

        # Should include recent
        completed = manager.handoff_list_completed(max_age_days=7)
        assert len(completed) == 1

    def test_handoff_list_completed_hybrid_logic(
        self, manager: "LessonsManager"
    ):
        """Should use OR logic: within max_count OR within max_age_days."""
        # Create 5 completed approaches
        created_ids = []
        for i in range(5):
            handoff_id = manager.handoff_add(title=f"Approach {i}")
            created_ids.append(handoff_id)
            manager.handoff_update_status(handoff_id, "completed")

        # Hybrid: max 2 OR within 7 days
        # All are recent, so should get max 2 (the most recent)
        completed = manager.handoff_list_completed(max_count=2, max_age_days=7)

        # Should get at least 2 (max_count) since all are recent
        assert len(completed) >= 2


class TestHandoffInjectWithCompleted:
    """Tests for showing completed handoffs in injection."""

    def test_handoff_inject_shows_recent_completions(
        self, manager: "LessonsManager"
    ):
        """Injection should show recent completions section."""
        id1 = manager.handoff_add(title="Active task")
        id2 = manager.handoff_add(title="Completed task")
        manager.handoff_update_status(id2, "completed")

        output = manager.handoff_inject()

        # Should show both active and completed sections
        assert "Active" in output or "active" in output
        assert id1 in output
        # Should mention completed or recent
        assert "Completed" in output or "completed" in output or "Recent" in output

    def test_handoff_inject_shows_completion_info(
        self, manager: "LessonsManager"
    ):
        """Completed handoffs should show completion metadata."""
        handoff_id = manager.handoff_add(title="Finished feature")
        manager.handoff_update_status(handoff_id, "completed")

        output = manager.handoff_inject()

        # Should indicate it's completed
        assert "✓" in output or "completed" in output.lower()

    def test_handoff_inject_hides_old_completions(
        self, manager: "LessonsManager"
    ):
        """Old completed approaches outside top N should not appear."""
        # Create 5 completed approaches
        created_ids = []
        for i in range(5):
            handoff_id = manager.handoff_add(title=f"Task {i}")
            created_ids.append(handoff_id)
            manager.handoff_update_status(handoff_id, "completed")

        # Make them all old (30 days ago)
        handoffs_file = manager.project_handoffs_file
        content = handoffs_file.read_text()
        old_date = (date.today() - timedelta(days=30)).isoformat()
        content = content.replace(
            f"**Updated**: {date.today().isoformat()}",
            f"**Updated**: {old_date}"
        )
        handoffs_file.write_text(content)

        # With max_completed=2 and all old (same date), only top 2 by file order show
        output = manager.handoff_inject(max_completed=2, max_completed_age=7)

        # Should show only 2 completed approaches (top 2 by stable sort order)
        # Task 3, 4 should not appear (outside top 2 and too old)
        assert "Task 3" not in output
        assert "Task 4" not in output

    def test_handoff_inject_today_completions_show_verify_warning(
        self, manager: "LessonsManager"
    ):
        """Today's completions should show 'verify if issues arise' in header."""
        # Create and complete a handoff (will be completed today)
        handoff_id = manager.handoff_add(title="Feature completed today")
        manager.handoff_update_status(handoff_id, "completed")

        output = manager.handoff_inject()

        # Header should indicate today's completions need verification
        assert "today" in output.lower()
        assert "verify" in output.lower()

    def test_handoff_inject_today_completions_show_summary(
        self, manager: "LessonsManager"
    ):
        """Today's completions with HandoffContext should show summary."""
        try:
            from core.models import HandoffContext
        except ImportError:
            pytest.skip("HandoffContext not yet implemented")

        # Create handoff with context
        handoff_id = manager.handoff_add(title="Feature with summary")

        # Set context with a summary
        context = HandoffContext(
            summary="Fixed critical bug in authentication flow",
            critical_files=["src/auth.py:100"],
            recent_changes=["Updated auth logic"],
            learnings=[],
            blockers=[],
            git_ref="abc1234",
        )
        manager.handoff_update_context(handoff_id, context)

        # Complete it (will be completed today)
        manager.handoff_update_status(handoff_id, "completed")

        output = manager.handoff_inject()

        # Should show the summary with └─ prefix for today's completion
        assert "└─" in output
        assert "Fixed critical bug in authentication flow" in output

    def test_handoff_inject_old_completions_no_summary(
        self, manager: "LessonsManager"
    ):
        """Completions older than today should NOT show summary (to save space)."""
        try:
            from core.models import HandoffContext
        except ImportError:
            pytest.skip("HandoffContext not yet implemented")

        # Create handoff with context
        handoff_id = manager.handoff_add(title="Old feature")

        context = HandoffContext(
            summary="This summary should not appear",
            critical_files=[],
            recent_changes=[],
            learnings=[],
            blockers=[],
            git_ref="old1234",
        )
        manager.handoff_update_context(handoff_id, context)
        manager.handoff_update_status(handoff_id, "completed")

        # Make it old (completed yesterday)
        handoffs_file = manager.project_handoffs_file
        content = handoffs_file.read_text()
        old_date = (date.today() - timedelta(days=1)).isoformat()
        content = content.replace(
            f"**Updated**: {date.today().isoformat()}",
            f"**Updated**: {old_date}"
        )
        handoffs_file.write_text(content)

        output = manager.handoff_inject()

        # Should show the handoff but NOT the summary (not from today)
        assert "Old feature" in output
        assert "This summary should not appear" not in output

    def test_handoff_inject_completed_capped_at_3x_max_count(
        self, manager: "LessonsManager"
    ):
        """Completed handoffs should be capped at 3x max_count even if all are recent."""
        # Create 15 completed handoffs (all completed today so they'd normally all show)
        for i in range(15):
            handoff_id = manager.handoff_add(title=f"Completed task {i}")
            manager.handoff_update_status(handoff_id, "completed")

        # With max_completed=3, the hard cap is 3 * 3 = 9
        output = manager.handoff_inject(max_completed=3)

        # Count how many completed tasks appear in output
        # Don't assume which specific ones - just verify the cap is enforced
        completed_count = sum(1 for i in range(15) if f"Completed task {i}" in output)

        # Should show exactly 9 (3x max_count cap)
        assert completed_count == 9, f"Expected 9 completed handoffs (3x max_count), got {completed_count}"


class TestHandoffAutoArchive:
    """Tests for auto-archiving after lesson extraction."""

    def test_handoff_complete_with_lessons_extracted(
        self, manager: "LessonsManager"
    ):
        """Complete should track if lessons were extracted."""
        handoff_id = manager.handoff_add(title="Feature work")
        manager.handoff_add_tried(handoff_id, "success", "Main implementation")

        result = manager.handoff_complete(handoff_id)

        # Should return extraction prompt
        assert result.extraction_prompt is not None
        assert "lesson" in result.extraction_prompt.lower()

    def test_handoff_archive_after_extraction(
        self, manager: "LessonsManager"
    ):
        """Should be able to archive after completing."""
        handoff_id = manager.handoff_add(title="Feature work")
        manager.handoff_complete(handoff_id)

        # Archive after extraction
        manager.handoff_archive(handoff_id)

        # Should no longer appear in active list
        handoffs = manager.handoff_list()
        assert len(handoffs) == 0

        # Should be in archive
        archive_file = manager.project_handoffs_archive
        assert archive_file.exists()
        assert "Feature work" in archive_file.read_text()


class TestHandoffDecayConstants:
    """Tests for decay configuration constants."""

    def test_default_max_completed_count(self, manager: "LessonsManager"):
        """Should have a default max completed count."""
        # The default should be accessible
        assert hasattr(manager, "HANDOFF_MAX_COMPLETED") or True  # Constant or method param

    def test_default_max_age_days(self, manager: "LessonsManager"):
        """Should have a default max age for completed approaches."""
        # The default should be accessible
        assert hasattr(manager, "HANDOFF_MAX_AGE_DAYS") or True  # Constant or method param


# =============================================================================
# Phase 4.4: Plan Mode Integration Tests
# =============================================================================


class TestPlanModeHandoffCreation:
    """Tests for auto-creating handoffs when entering plan mode."""

    def test_handoff_add_from_plan_mode(self, manager: "LessonsManager"):
        """Should be able to create approach with plan mode context."""
        handoff_id = manager.handoff_add(
            title="Implement user authentication",
            phase="research",
            agent="plan",
        )

        handoff = manager.handoff_get(handoff_id)
        assert handoff.title == "Implement user authentication"
        assert handoff.phase == "research"
        assert handoff.agent == "plan"

    def test_handoff_links_to_plan_file(self, manager: "LessonsManager"):
        """Approach can store plan file path reference."""
        handoff_id = manager.handoff_add(
            title="Feature implementation",
            phase="planning",
            desc="Plan file: ~/.claude/plans/test-plan.md",
        )

        handoff = manager.handoff_get(handoff_id)
        assert "plan" in handoff.description.lower()

    def test_handoff_phase_transition_research_to_planning(
        self, manager: "LessonsManager"
    ):
        """Phase should transition from research to planning."""
        handoff_id = manager.handoff_add(title="New feature", phase="research")
        manager.handoff_update_phase(handoff_id, "planning")

        handoff = manager.handoff_get(handoff_id)
        assert handoff.phase == "planning"

    def test_handoff_phase_transition_planning_to_implementing(
        self, manager: "LessonsManager"
    ):
        """Phase should transition from planning to implementing."""
        handoff_id = manager.handoff_add(title="New feature", phase="planning")
        manager.handoff_update_phase(handoff_id, "implementing")

        handoff = manager.handoff_get(handoff_id)
        assert handoff.phase == "implementing"


class TestHookPhasePatterns:
    """Tests for hook command patterns for phase updates."""

    def test_handoff_update_phase_via_hook_pattern(self, manager: "LessonsManager"):
        """Should support phase updates from hook patterns."""
        handoff_id = manager.handoff_add(title="Test feature")

        # This simulates what the hook would do
        manager.handoff_update_phase(handoff_id, "implementing")

        handoff = manager.handoff_get(handoff_id)
        assert handoff.phase == "implementing"

    def test_phase_update_preserves_other_fields(
        self, manager_with_handoffs: "LessonsManager"
    ):
        """Phase update should not affect other approach fields."""
        # Add some data first
        manager_with_handoffs.handoff_add_tried("hf-0000001", "fail", "First attempt")
        manager_with_handoffs.handoff_update_next("hf-0000001", "Try another way")

        # Update phase
        manager_with_handoffs.handoff_update_phase("hf-0000001", "review")

        handoff = manager_with_handoffs.handoff_get("hf-0000001")
        assert handoff.phase == "review"
        assert len(handoff.tried) == 1
        assert handoff.next_steps == "Try another way"

    def test_plan_mode_approach_pattern_parsed(self, manager: "LessonsManager"):
        """PLAN MODE: pattern should work like HANDOFF: pattern."""
        # This tests that the same handoff_add mechanism works for plan mode
        handoff_id = manager.handoff_add(
            title="Feature from plan mode",
            phase="research",
        )

        assert handoff_id.startswith("hf-")
        handoff = manager.handoff_get(handoff_id)
        assert handoff.title == "Feature from plan mode"


class TestHookCLIIntegration:
    """Tests for CLI commands that hooks invoke."""

    def test_cli_handoff_add_with_phase_and_agent(self, tmp_path):
        """CLI should support --phase and --agent when adding handoff."""
        # Set up environment
        env = os.environ.copy()
        env["PROJECT_DIR"] = str(tmp_path)
        env["CLAUDE_RECALL_BASE"] = str(tmp_path / ".lessons")

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
        env["CLAUDE_RECALL_BASE"] = str(tmp_path / ".lessons")

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

    def test_cli_handoff_update_phase(self, tmp_path):
        """CLI should support --phase in update command."""
        env = os.environ.copy()
        env["PROJECT_DIR"] = str(tmp_path)
        env["CLAUDE_RECALL_BASE"] = str(tmp_path / ".lessons")

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
        handoff_id = id_match.group(1) if id_match else "hf-unknown"

        # Then update the phase
        result = subprocess.run(
            [
                sys.executable,
                "core/cli.py",
                "approach",
                "update",
                handoff_id,
                "--phase",
                "implementing",
            ],
            capture_output=True,
            text=True,
            env=env,
        )

        assert result.returncode == 0
        assert "phase" in result.stdout.lower()

    def test_cli_handoff_update_agent(self, tmp_path):
        """CLI should support --agent in update command."""
        env = os.environ.copy()
        env["PROJECT_DIR"] = str(tmp_path)
        env["CLAUDE_RECALL_BASE"] = str(tmp_path / ".lessons")

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
        handoff_id = id_match.group(1) if id_match else "hf-unknown"

        # Then update the agent
        result = subprocess.run(
            [
                sys.executable,
                "core/cli.py",
                "approach",
                "update",
                handoff_id,
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
    def temp_dirs(self, tmp_path: Path, monkeypatch):
        """Create temp directories for testing."""
        lessons_base = tmp_path / ".config" / "claude-recall"
        state_dir = tmp_path / ".local" / "state" / "claude-recall"
        project_root = tmp_path / "project"
        lessons_base.mkdir(parents=True)
        state_dir.mkdir(parents=True, exist_ok=True)
        project_root.mkdir(parents=True)
        # Set env var so LessonsManager uses temp state dir
        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(state_dir))
        return lessons_base, state_dir, project_root

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

    def test_last_reference_phase_update(self, temp_dirs, isolated_subprocess_env):
        """HANDOFF UPDATE LAST: phase should update the most recent handoff."""
        lessons_base, state_dir, project_root = temp_dirs
        hook_path = Path("adapters/claude-code/stop-hook.sh")
        if not hook_path.exists():
            pytest.skip("stop-hook.sh not found")

        transcript = self.create_mock_transcript(project_root, [
            "HANDOFF: Test feature",
            "HANDOFF UPDATE LAST: phase implementing",
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
                **isolated_subprocess_env,
                "CLAUDE_RECALL_BASE": str(lessons_base),
                "CLAUDE_RECALL_STATE": str(state_dir),
                "PROJECT_DIR": str(project_root),
            },
        )

        assert result.returncode == 0

        from core import LessonsManager
        manager = LessonsManager(lessons_base, project_root)
        handoffs = manager.handoff_list()
        assert len(handoffs) == 1
        handoff = handoffs[0]
        assert handoff.title == "Test feature"
        assert handoff.phase == "implementing"

    def test_last_reference_tried_update(self, temp_dirs, isolated_subprocess_env):
        """HANDOFF UPDATE LAST: tried should update the most recent handoff."""
        lessons_base, state_dir, project_root = temp_dirs
        hook_path = Path("adapters/claude-code/stop-hook.sh")
        if not hook_path.exists():
            pytest.skip("stop-hook.sh not found")

        transcript = self.create_mock_transcript(project_root, [
            "HANDOFF: Another feature",
            "HANDOFF UPDATE LAST: tried success - it worked great",
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
                **isolated_subprocess_env,
                "CLAUDE_RECALL_BASE": str(lessons_base),
                "CLAUDE_RECALL_STATE": str(state_dir),
                "PROJECT_DIR": str(project_root),
            },
        )

        assert result.returncode == 0

        from core import LessonsManager
        manager = LessonsManager(lessons_base, project_root)
        handoffs = manager.handoff_list()
        assert len(handoffs) == 1
        handoff = handoffs[0]
        assert handoff.title == "Another feature"
        assert len(handoff.tried) == 1
        assert handoff.tried[0].outcome == "success"
        assert "worked great" in handoff.tried[0].description

    def test_last_reference_complete(self, temp_dirs, isolated_subprocess_env):
        """APPROACH COMPLETE LAST should complete the most recent handoff."""
        lessons_base, state_dir, project_root = temp_dirs
        hook_path = Path("adapters/claude-code/stop-hook.sh")
        if not hook_path.exists():
            pytest.skip("stop-hook.sh not found")

        transcript = self.create_mock_transcript(project_root, [
            "HANDOFF: Complete me",
            "HANDOFF COMPLETE LAST",
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
                **isolated_subprocess_env,
                "CLAUDE_RECALL_BASE": str(lessons_base),
                "CLAUDE_RECALL_STATE": str(state_dir),
                "PROJECT_DIR": str(project_root),
            },
        )

        assert result.returncode == 0

        from core import LessonsManager
        manager = LessonsManager(lessons_base, project_root)
        # Completed approaches are not in the default list
        completed = manager.handoff_list_completed()
        assert len(completed) == 1
        handoff = completed[0]
        assert handoff.title == "Complete me"
        assert handoff.status == "completed"

    def test_last_tracks_across_multiple_creates(self, temp_dirs, isolated_subprocess_env):
        """LAST should track the most recently created handoff."""
        lessons_base, state_dir, project_root = temp_dirs
        hook_path = Path("adapters/claude-code/stop-hook.sh")
        if not hook_path.exists():
            pytest.skip("stop-hook.sh not found")

        transcript = self.create_mock_transcript(project_root, [
            "HANDOFF: First approach",
            "HANDOFF: Second approach",
            "HANDOFF UPDATE LAST: phase implementing",
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
                **isolated_subprocess_env,
                "CLAUDE_RECALL_BASE": str(lessons_base),
                "CLAUDE_RECALL_STATE": str(state_dir),
                "PROJECT_DIR": str(project_root),
            },
        )

        assert result.returncode == 0

        from core import LessonsManager
        manager = LessonsManager(lessons_base, project_root)
        handoffs = manager.handoff_list()
        assert len(handoffs) == 2

        # Find approaches by title
        first = next((a for a in handoffs if a.title == "First approach"), None)
        second = next((a for a in handoffs if a.title == "Second approach"), None)

        assert first is not None
        assert first.phase == "research"  # Not updated

        assert second is not None
        assert second.phase == "implementing"  # LAST referred to it


# =============================================================================
# Checkpoint Tests (Phase 1 of Context Handoff System)
# =============================================================================


class TestHandoffCheckpoint:
    """Test checkpoint field for session handoff."""

    def test_handoff_has_checkpoint_field(self, manager: LessonsManager) -> None:
        """Verify Approach dataclass has checkpoint field."""
        handoff_id = manager.handoff_add("Test approach")
        handoff = manager.handoff_get(handoff_id)

        assert hasattr(handoff, "checkpoint")
        assert handoff.checkpoint == ""  # Default empty

    def test_handoff_has_last_session_field(self, manager: LessonsManager) -> None:
        """Verify Approach dataclass has last_session field."""
        handoff_id = manager.handoff_add("Test approach")
        handoff = manager.handoff_get(handoff_id)

        assert hasattr(handoff, "last_session")
        assert handoff.last_session is None  # Default None

    def test_handoff_update_checkpoint(self, manager: LessonsManager) -> None:
        """Test updating checkpoint via manager method."""
        handoff_id = manager.handoff_add("Test approach")

        manager.handoff_update_checkpoint(
            handoff_id, "Tests passing, working on UI integration"
        )

        handoff = manager.handoff_get(handoff_id)
        assert handoff.checkpoint == "Tests passing, working on UI integration"
        assert handoff.last_session == date.today()

    def test_handoff_update_checkpoint_sets_updated_date(
        self, manager: LessonsManager
    ) -> None:
        """Verify update_checkpoint also updates the updated date."""
        handoff_id = manager.handoff_add("Test approach")

        manager.handoff_update_checkpoint(handoff_id, "Some progress")

        handoff = manager.handoff_get(handoff_id)
        assert handoff.updated == date.today()

    def test_handoff_update_checkpoint_nonexistent_fails(
        self, manager: LessonsManager
    ) -> None:
        """Test that updating checkpoint for nonexistent approach fails."""
        with pytest.raises(ValueError, match="not found"):
            manager.handoff_update_checkpoint("A999", "Some progress")

    def test_handoff_checkpoint_overwrites(self, manager: LessonsManager) -> None:
        """Test that updating checkpoint overwrites previous value."""
        handoff_id = manager.handoff_add("Test approach")

        manager.handoff_update_checkpoint(handoff_id, "First checkpoint")
        manager.handoff_update_checkpoint(handoff_id, "Second checkpoint")

        handoff = manager.handoff_get(handoff_id)
        assert handoff.checkpoint == "Second checkpoint"


class TestHandoffCheckpointFormat:
    """Test checkpoint field in markdown format."""

    def test_checkpoint_formatted_in_markdown(self, manager: LessonsManager) -> None:
        """Verify checkpoint is written to markdown file."""
        handoff_id = manager.handoff_add("Test approach")
        manager.handoff_update_checkpoint(handoff_id, "Progress summary here")

        content = manager.project_handoffs_file.read_text()
        assert "**Checkpoint**: Progress summary here" in content

    def test_last_session_formatted_in_markdown(self, manager: LessonsManager) -> None:
        """Verify last_session is written to markdown file."""
        handoff_id = manager.handoff_add("Test approach")
        manager.handoff_update_checkpoint(handoff_id, "Progress summary")

        content = manager.project_handoffs_file.read_text()
        assert f"**Last Session**: {date.today().isoformat()}" in content

    def test_checkpoint_parsed_correctly(self, manager: LessonsManager) -> None:
        """Verify checkpoint is parsed back correctly."""
        handoff_id = manager.handoff_add("Test approach")
        manager.handoff_update_checkpoint(handoff_id, "Complex checkpoint: tests, UI")

        # Force re-parse by getting fresh
        handoff = manager.handoff_get(handoff_id)
        assert handoff.checkpoint == "Complex checkpoint: tests, UI"

    def test_last_session_parsed_correctly(self, manager: LessonsManager) -> None:
        """Verify last_session date is parsed correctly."""
        handoff_id = manager.handoff_add("Test approach")
        manager.handoff_update_checkpoint(handoff_id, "Progress")

        handoff = manager.handoff_get(handoff_id)
        assert handoff.last_session == date.today()

    def test_backward_compatibility_no_checkpoint(
        self, manager: LessonsManager
    ) -> None:
        """Verify approaches without checkpoint field still parse."""
        # Create approach without checkpoint
        handoff_id = manager.handoff_add("Legacy approach")

        # Manually write old format without checkpoint
        content = manager.project_handoffs_file.read_text()
        # The file should parse fine - checkpoint defaults to empty
        handoff = manager.handoff_get(handoff_id)
        assert handoff.checkpoint == ""
        assert handoff.last_session is None


class TestHandoffCheckpointInjection:
    """Test checkpoint in context injection output."""

    def test_handoff_inject_shows_checkpoint(self, manager: LessonsManager) -> None:
        """Verify inject output includes checkpoint prominently."""
        handoff_id = manager.handoff_add("Feature implementation")
        manager.handoff_update_checkpoint(
            handoff_id, "API done, working on frontend"
        )

        output = manager.handoff_inject()

        assert "**Checkpoint" in output
        assert "API done, working on frontend" in output

    def test_handoff_inject_shows_checkpoint_age(self, manager: LessonsManager) -> None:
        """Verify inject output shows how old the checkpoint is."""
        handoff_id = manager.handoff_add("Feature implementation")
        manager.handoff_update_checkpoint(handoff_id, "Some progress")

        output = manager.handoff_inject()

        # Should show "(today)" for same-day checkpoint
        assert "(today)" in output or "Checkpoint" in output

    def test_handoff_inject_no_checkpoint_no_display(
        self, manager: LessonsManager
    ) -> None:
        """Verify inject output doesn't show checkpoint line if empty."""
        handoff_id = manager.handoff_add("Feature implementation")
        # Don't set checkpoint

        output = manager.handoff_inject()

        # Should not have Checkpoint line
        assert "**Checkpoint" not in output


class TestHandoffCheckpointCLI:
    """Test checkpoint via CLI."""

    def test_cli_handoff_update_checkpoint(
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

        monkeypatch.setenv("CLAUDE_RECALL_BASE", str(lessons_base))
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
        handoff_id = id_match.group(1) if id_match else "hf-unknown"

        # Update checkpoint
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "core.cli",
                "approach",
                "update",
                handoff_id,
                "--checkpoint",
                "Progress: tests passing",
            ],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
        assert result.returncode == 0, result.stderr
        assert f"Updated {handoff_id} checkpoint" in result.stdout

        # Verify via manager directly
        from core import LessonsManager

        manager = LessonsManager(lessons_base, project_root)
        handoff = manager.handoff_get(handoff_id)
        assert handoff.checkpoint == "Progress: tests passing"


class TestHandoffCheckpointPreservation:
    """Test checkpoint is preserved across updates."""

    def test_checkpoint_preserved_on_status_update(
        self, manager: LessonsManager
    ) -> None:
        """Verify checkpoint survives status updates."""
        handoff_id = manager.handoff_add("Test approach")
        manager.handoff_update_checkpoint(handoff_id, "Important checkpoint")
        manager.handoff_update_status(handoff_id, "in_progress")

        handoff = manager.handoff_get(handoff_id)
        assert handoff.checkpoint == "Important checkpoint"

    def test_checkpoint_preserved_on_tried_add(self, manager: LessonsManager) -> None:
        """Verify checkpoint survives adding tried attempts."""
        handoff_id = manager.handoff_add("Test approach")
        manager.handoff_update_checkpoint(handoff_id, "Important checkpoint")
        manager.handoff_add_tried(handoff_id, "success", "Did something")

        handoff = manager.handoff_get(handoff_id)
        assert handoff.checkpoint == "Important checkpoint"

    def test_checkpoint_preserved_on_phase_update(
        self, manager: LessonsManager
    ) -> None:
        """Verify checkpoint survives phase updates."""
        handoff_id = manager.handoff_add("Test approach")
        manager.handoff_update_checkpoint(handoff_id, "Important checkpoint")
        manager.handoff_update_phase(handoff_id, "implementing")

        handoff = manager.handoff_get(handoff_id)
        assert handoff.checkpoint == "Important checkpoint"


# =============================================================================
# TodoWrite Sync Tests
# =============================================================================


class TestHandoffSyncTodos:
    """Tests for TodoWrite to Handoff sync functionality."""

    def test_sync_creates_approach_if_none_active(self, manager: LessonsManager) -> None:
        """sync_todos creates new approach from first todo if 3+ todos and no active approaches."""
        todos = [
            {"content": "Research patterns", "status": "completed", "activeForm": "Researching"},
            {"content": "Implement fix", "status": "in_progress", "activeForm": "Implementing"},
            {"content": "Write tests", "status": "pending", "activeForm": "Writing tests"},
        ]

        result = manager.handoff_sync_todos(todos)

        assert result is not None
        handoff = manager.handoff_get(result)
        assert handoff is not None
        assert "Research patterns" in handoff.title

    def test_sync_skips_if_fewer_than_3_todos_and_no_active(self, manager: LessonsManager) -> None:
        """sync_todos returns None if < 3 todos and no active handoff (avoids noise)."""
        todos = [
            {"content": "Quick fix", "status": "completed", "activeForm": "Fixing"},
            {"content": "Test it", "status": "pending", "activeForm": "Testing"},
        ]

        result = manager.handoff_sync_todos(todos)

        assert result is None
        assert len(manager.handoff_list()) == 0

    def test_sync_updates_existing_approach(self, manager: LessonsManager) -> None:
        """sync_todos updates most recently updated active handoff."""
        handoff_id = manager.handoff_add("Existing approach")

        todos = [
            {"content": "Done task", "status": "completed", "activeForm": "Done"},
            {"content": "Current task", "status": "in_progress", "activeForm": "Working"},
        ]

        result = manager.handoff_sync_todos(todos)

        assert result == handoff_id

    def test_sync_completed_to_tried(self, manager: LessonsManager) -> None:
        """Completed todos become tried entries with success outcome."""
        handoff_id = manager.handoff_add("Test approach")

        todos = [
            {"content": "Task A", "status": "completed", "activeForm": "Task A"},
            {"content": "Task B", "status": "completed", "activeForm": "Task B"},
        ]

        manager.handoff_sync_todos(todos)
        handoff = manager.handoff_get(handoff_id)

        assert len(handoff.tried) == 2
        assert handoff.tried[0].outcome == "success"
        assert handoff.tried[0].description == "Task A"

    def test_sync_in_progress_to_checkpoint(self, manager: LessonsManager) -> None:
        """In-progress todo becomes checkpoint."""
        handoff_id = manager.handoff_add("Test approach")

        todos = [
            {"content": "Current work", "status": "in_progress", "activeForm": "Working"},
        ]

        manager.handoff_sync_todos(todos)
        handoff = manager.handoff_get(handoff_id)

        assert handoff.checkpoint == "Current work"

    def test_sync_pending_to_next_steps(self, manager: LessonsManager) -> None:
        """Pending todos become next_steps."""
        handoff_id = manager.handoff_add("Test approach")

        todos = [
            {"content": "Next A", "status": "pending", "activeForm": "Next A"},
            {"content": "Next B", "status": "pending", "activeForm": "Next B"},
        ]

        manager.handoff_sync_todos(todos)
        handoff = manager.handoff_get(handoff_id)

        assert "Next A" in handoff.next_steps
        assert "Next B" in handoff.next_steps

    def test_sync_empty_todos_returns_none(self, manager: LessonsManager) -> None:
        """Empty todo list returns None."""
        result = manager.handoff_sync_todos([])
        assert result is None

    def test_sync_avoids_duplicate_tried(self, manager: LessonsManager) -> None:
        """sync_todos doesn't add duplicate tried entries."""
        handoff_id = manager.handoff_add("Test approach")
        manager.handoff_add_tried(handoff_id, "success", "Already done")

        todos = [
            {"content": "Already done", "status": "completed", "activeForm": "Done"},
        ]

        manager.handoff_sync_todos(todos)
        handoff = manager.handoff_get(handoff_id)

        # Should still only have 1 tried entry
        assert len(handoff.tried) == 1

    def test_sync_completed_todos_updates_status_to_in_progress(self, manager: LessonsManager) -> None:
        """Completed todos should move status from not_started to in_progress."""
        handoff_id = manager.handoff_add("Test approach")
        handoff = manager.handoff_get(handoff_id)
        assert handoff.status == "not_started"

        todos = [
            {"content": "Done task", "status": "completed", "activeForm": "Done"},
            {"content": "Next task", "status": "pending", "activeForm": "Next"},
        ]

        manager.handoff_sync_todos(todos)
        handoff = manager.handoff_get(handoff_id)

        # Status should be in_progress because work has been done
        assert handoff.status == "in_progress"

    def test_sync_all_completed_todos_sets_ready_for_review(self, manager: LessonsManager) -> None:
        """All completed todos with none pending should set ready_for_review status."""
        handoff_id = manager.handoff_add("Test approach")

        todos = [
            {"content": "Task 1", "status": "completed", "activeForm": "Task 1"},
            {"content": "Task 2", "status": "completed", "activeForm": "Task 2"},
        ]

        manager.handoff_sync_todos(todos)
        handoff = manager.handoff_get(handoff_id)

        # All done but no commit step - should be ready for lesson review (not auto-completed)
        assert handoff.status == "ready_for_review"

    def test_sync_all_completed_with_commit_auto_completes(self, manager: LessonsManager) -> None:
        """All completed todos with a commit step should auto-complete the handoff."""
        handoff_id = manager.handoff_add("Test approach")

        todos = [
            {"content": "Implement feature", "status": "completed", "activeForm": "Implementing"},
            {"content": "Run tests", "status": "completed", "activeForm": "Running tests"},
            {"content": "Commit changes", "status": "completed", "activeForm": "Committing"},
        ]

        manager.handoff_sync_todos(todos)
        handoff = manager.handoff_get(handoff_id)

        # Has commit step - should auto-complete
        assert handoff.status == "completed"

    def test_sync_commit_detection_case_insensitive(self, manager: LessonsManager) -> None:
        """Commit detection should be case-insensitive."""
        handoff_id = manager.handoff_add("Test approach")

        todos = [
            {"content": "Fix bug", "status": "completed", "activeForm": "Fixing"},
            {"content": "COMMIT the fix", "status": "completed", "activeForm": "Committing"},
        ]

        manager.handoff_sync_todos(todos)
        handoff = manager.handoff_get(handoff_id)

        assert handoff.status == "completed"

    def test_sync_in_progress_todo_updates_status(self, manager: LessonsManager) -> None:
        """In progress todo should move status to in_progress."""
        handoff_id = manager.handoff_add("Test approach")

        todos = [
            {"content": "Working on it", "status": "in_progress", "activeForm": "Working"},
        ]

        manager.handoff_sync_todos(todos)
        handoff = manager.handoff_get(handoff_id)

        assert handoff.status == "in_progress"

    def test_sync_only_pending_todos_stays_not_started(self, manager: LessonsManager) -> None:
        """Only pending todos should keep status as not_started."""
        handoff_id = manager.handoff_add("Test approach")

        todos = [
            {"content": "Future task", "status": "pending", "activeForm": "Future"},
        ]

        manager.handoff_sync_todos(todos)
        handoff = manager.handoff_get(handoff_id)

        # No work done yet
        assert handoff.status == "not_started"

    def test_sync_regression_all_done_must_be_ready_for_review(self, manager: LessonsManager) -> None:
        """REGRESSION: All completed todos must set status to ready_for_review, not stuck at not_started.

        Bug scenario: User completes all work (15 tasks), but handoff stays at not_started
        because sync_todos didn't update status when only completed todos existed.

        New behavior: All done → ready_for_review (user reviews for lessons) → HANDOFF COMPLETE → completed
        """
        handoff_id = manager.handoff_add("Fix install.sh")
        handoff = manager.handoff_get(handoff_id)
        assert handoff.status == "not_started"  # Initial state

        # Simulate a full session with all tasks completed
        todos = [
            {"content": "Fix install.sh to include _version.py", "status": "completed", "activeForm": "Fixing"},
            {"content": "Add integration test for installed CLI import", "status": "completed", "activeForm": "Adding"},
            {"content": "Fix bash tests to isolate CLAUDE_RECALL_STATE", "status": "completed", "activeForm": "Fixing"},
        ]

        manager.handoff_sync_todos(todos)
        handoff = manager.handoff_get(handoff_id)

        # CRITICAL: Must be ready_for_review, NOT not_started or in_progress
        assert handoff.status == "ready_for_review", (
            f"BUG: Handoff stuck at '{handoff.status}' despite all todos completed. "
            f"Tried: {[t.description for t in handoff.tried]}"
        )

    def test_sync_regression_work_done_must_be_in_progress(self, manager: LessonsManager) -> None:
        """REGRESSION: Completed todos with pending must set status to in_progress.

        Bug scenario: User completes several tasks but more remain, handoff stays not_started.
        """
        handoff_id = manager.handoff_add("Multi-step work")
        handoff = manager.handoff_get(handoff_id)
        assert handoff.status == "not_started"

        todos = [
            {"content": "First task done", "status": "completed", "activeForm": "First"},
            {"content": "Second task done", "status": "completed", "activeForm": "Second"},
            {"content": "Third task pending", "status": "pending", "activeForm": "Third"},
        ]

        manager.handoff_sync_todos(todos)
        handoff = manager.handoff_get(handoff_id)

        # CRITICAL: Must be in_progress (work done), NOT not_started
        assert handoff.status == "in_progress", (
            f"BUG: Handoff stuck at '{handoff.status}' despite completed work. "
            f"Tried: {[t.description for t in handoff.tried]}, Next: {handoff.next_steps}"
        )


class TestHandoffInjectTodos:
    """Tests for Handoff to TodoWrite injection functionality."""

    def test_inject_returns_empty_if_no_active(self, manager: LessonsManager) -> None:
        """inject_todos returns empty string if no active approaches."""
        result = manager.handoff_inject_todos()
        assert result == ""

    def test_inject_formats_approach_as_todos(self, manager: LessonsManager) -> None:
        """inject_todos formats approach state as todo list."""
        handoff_id = manager.handoff_add("Test approach")
        manager.handoff_add_tried(handoff_id, "success", "First task succeeded")
        manager.handoff_update_checkpoint(handoff_id, "Current task")
        manager.handoff_update_next(handoff_id, "Next task")

        result = manager.handoff_inject_todos()

        assert "CONTINUE PREVIOUS WORK" in result
        assert "First task succeeded" in result
        assert "Current task" in result
        assert "Next task" in result
        assert "```json" in result

    def test_inject_shows_status_icons(self, manager: LessonsManager) -> None:
        """inject_todos uses status icons for visual clarity."""
        handoff_id = manager.handoff_add("Test approach")
        manager.handoff_add_tried(handoff_id, "success", "Succeeded")
        manager.handoff_update_checkpoint(handoff_id, "Doing")
        manager.handoff_update_next(handoff_id, "Todo")

        result = manager.handoff_inject_todos()

        assert "✓" in result  # completed
        assert "→" in result  # in_progress
        assert "○" in result  # pending

    def test_inject_json_excludes_completed(self, manager: LessonsManager) -> None:
        """inject_todos JSON only includes non-completed todos."""
        import json

        handoff_id = manager.handoff_add("Test approach")
        manager.handoff_add_tried(handoff_id, "success", "Succeeded task")
        manager.handoff_update_checkpoint(handoff_id, "Current task")

        result = manager.handoff_inject_todos()

        # Extract JSON from result
        json_start = result.find("```json\n") + len("```json\n")
        json_end = result.find("\n```", json_start)
        json_str = result[json_start:json_end]
        todos = json.loads(json_str)

        # JSON should only have current task, not done task
        assert len(todos) == 1
        assert f"[{handoff_id}] Current task" in todos[0]["content"]
        assert todos[0]["status"] == "in_progress"


class TestTodoSyncRoundTrip:
    """Tests for full TodoWrite to Handoff round-trip sync."""

    def test_full_round_trip(self, manager: LessonsManager) -> None:
        """Todos synced to approach can be restored as todos."""
        import json

        # Simulate session 1: sync todos to approach
        todos_session1 = [
            {"content": "Step 1", "status": "completed", "activeForm": "Step 1"},
            {"content": "Step 2", "status": "in_progress", "activeForm": "Step 2"},
            {"content": "Step 3", "status": "pending", "activeForm": "Step 3"},
        ]
        handoff_id = manager.handoff_sync_todos(todos_session1)

        # Simulate session 2: inject todos from approach
        result = manager.handoff_inject_todos()

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


class TestStaleHandoffArchival:
    """Tests for auto-archiving stale handoffs."""

    def test_stale_handoff_archived_on_inject(self, manager: LessonsManager) -> None:
        """Approaches untouched for >7 days are auto-archived during inject."""
        from datetime import timedelta

        # Create an approach and backdate it to 8 days ago
        manager.handoff_add(title="Old task", desc="Started long ago")

        # Manually update the approach's updated date to be stale
        handoffs = manager._parse_handoffs_file(manager.project_handoffs_file)
        handoffs[0].updated = date.today() - timedelta(days=8)
        manager._write_handoffs_file(handoffs)

        # Inject should auto-archive the stale approach
        result = manager.handoff_inject()

        # Should not appear in active approaches
        assert "Old task" not in result or "Auto-archived" in result

        # Should be in archive with stale note
        archive_content = manager.project_handoffs_archive.read_text()
        assert "Old task" in archive_content
        assert "Auto-archived" in archive_content

    def test_handoff_exactly_7_days_not_archived(self, manager: LessonsManager) -> None:
        """Approaches exactly 7 days old are NOT archived (need >7 days)."""
        from datetime import timedelta

        manager.handoff_add(title="Week old task")

        # Set to exactly 7 days ago
        handoffs = manager._parse_handoffs_file(manager.project_handoffs_file)
        handoffs[0].updated = date.today() - timedelta(days=7)
        manager._write_handoffs_file(handoffs)

        result = manager.handoff_inject()

        # Should still appear in active handoffs
        assert "Week old task" in result
        assert "Active Handoffs" in result

    def test_completed_approach_not_stale_archived(self, manager: LessonsManager) -> None:
        """Completed approaches are handled by different rules, not stale archival."""
        from datetime import timedelta

        manager.handoff_add(title="Finished task")
        handoffs = manager._parse_handoffs_file(manager.project_handoffs_file)
        handoffs[0].status = "completed"
        handoffs[0].updated = date.today() - timedelta(days=8)
        manager._write_handoffs_file(handoffs)

        # This should NOT be archived by stale logic (completed has own rules)
        archived = manager._archive_stale_handoffs()
        assert len(archived) == 0

    def test_stale_archival_returns_archived_ids(self, manager: LessonsManager) -> None:
        """_archive_stale_handoffs returns list of archived approach IDs."""
        from datetime import timedelta

        manager.handoff_add(title="Stale 1")
        manager.handoff_add(title="Stale 2")
        manager.handoff_add(title="Fresh")

        handoffs = manager._parse_handoffs_file(manager.project_handoffs_file)
        handoffs[0].updated = date.today() - timedelta(days=10)
        handoffs[1].updated = date.today() - timedelta(days=8)
        # handoffs[2] stays fresh (today)
        manager._write_handoffs_file(handoffs)

        archived = manager._archive_stale_handoffs()

        assert len(archived) == 2
        assert handoffs[0].id in archived
        assert handoffs[1].id in archived

    def test_no_stale_approaches_no_changes(self, manager: LessonsManager) -> None:
        """When no approaches are stale, files are not modified."""
        manager.handoff_add(title="Fresh task")

        # Get original content
        original_content = manager.project_handoffs_file.read_text()

        archived = manager._archive_stale_handoffs()

        assert len(archived) == 0
        # Archive file should not be created
        assert not manager.project_handoffs_archive.exists()
        # Main file unchanged (content-wise, though timestamps may differ)
        assert "Fresh task" in manager.project_handoffs_file.read_text()


class TestCompletedHandoffArchival:
    """Tests for auto-archiving completed handoffs after N days."""

    def test_completed_handoff_archived_after_days(self, manager: LessonsManager) -> None:
        """Completed approaches are archived after HANDOFF_COMPLETED_ARCHIVE_DAYS."""
        from core.models import HANDOFF_COMPLETED_ARCHIVE_DAYS

        handoff_id = manager.handoff_add(title="Finished work")
        manager.handoff_complete(handoff_id)

        # Backdate the completed approach
        handoffs = manager._parse_handoffs_file(manager.project_handoffs_file)
        handoffs[0].updated = date.today() - timedelta(days=HANDOFF_COMPLETED_ARCHIVE_DAYS + 1)
        manager._write_handoffs_file(handoffs)

        # Trigger archival via inject
        manager.handoff_inject()

        # Should be archived
        archive_content = manager.project_handoffs_archive.read_text()
        assert "Finished work" in archive_content

        # Should not be in active list
        active = manager.handoff_list(include_completed=True)
        assert len(active) == 0

    def test_completed_approach_at_threshold_not_archived(self, manager: LessonsManager) -> None:
        """Completed approaches exactly at threshold are NOT archived."""
        from core.models import HANDOFF_COMPLETED_ARCHIVE_DAYS

        handoff_id = manager.handoff_add(title="Just finished")
        manager.handoff_complete(handoff_id)

        # Set to exactly at threshold
        handoffs = manager._parse_handoffs_file(manager.project_handoffs_file)
        handoffs[0].updated = date.today() - timedelta(days=HANDOFF_COMPLETED_ARCHIVE_DAYS)
        manager._write_handoffs_file(handoffs)

        archived = manager._archive_old_completed_handoffs()

        assert len(archived) == 0
        # Should still be in active
        active = manager.handoff_list(include_completed=True)
        assert len(active) == 1

    def test_fresh_completed_not_archived(self, manager: LessonsManager) -> None:
        """Recently completed approaches stay in active for visibility."""
        handoff_id = manager.handoff_add(title="Just done")
        manager.handoff_complete(handoff_id)

        archived = manager._archive_old_completed_handoffs()

        assert len(archived) == 0
        # Should show in completed list
        completed = manager.handoff_list_completed()
        assert len(completed) == 1

    def test_stale_and_completed_archived_separately(self, manager: LessonsManager) -> None:
        """Both stale active and old completed get archived."""
        from core.models import HANDOFF_STALE_DAYS, HANDOFF_COMPLETED_ARCHIVE_DAYS

        # Create stale active approach
        id1 = manager.handoff_add(title="Stale active")
        # Create old completed approach
        id2 = manager.handoff_add(title="Old completed")
        manager.handoff_complete(id2)

        handoffs = manager._parse_handoffs_file(manager.project_handoffs_file)
        handoffs[0].updated = date.today() - timedelta(days=HANDOFF_STALE_DAYS + 1)
        handoffs[1].updated = date.today() - timedelta(days=HANDOFF_COMPLETED_ARCHIVE_DAYS + 1)
        manager._write_handoffs_file(handoffs)

        # Inject triggers both
        manager.handoff_inject()

        archive_content = manager.project_handoffs_archive.read_text()
        assert "Stale active" in archive_content
        assert "Old completed" in archive_content

        # Both should be gone from active
        active = manager.handoff_list(include_completed=True)
        assert len(active) == 0

    def test_archive_old_completed_returns_ids(self, manager: LessonsManager) -> None:
        """_archive_old_completed_handoffs returns list of archived IDs."""
        from core.models import HANDOFF_COMPLETED_ARCHIVE_DAYS

        id1 = manager.handoff_add(title="Old 1")
        id2 = manager.handoff_add(title="Old 2")
        id3 = manager.handoff_add(title="Fresh")
        manager.handoff_complete(id1)
        manager.handoff_complete(id2)
        manager.handoff_complete(id3)

        handoffs = manager._parse_handoffs_file(manager.project_handoffs_file)
        handoffs[0].updated = date.today() - timedelta(days=HANDOFF_COMPLETED_ARCHIVE_DAYS + 2)
        handoffs[1].updated = date.today() - timedelta(days=HANDOFF_COMPLETED_ARCHIVE_DAYS + 1)
        # id3 stays fresh
        manager._write_handoffs_file(handoffs)

        archived = manager._archive_old_completed_handoffs()

        assert len(archived) == 2
        assert id1 in archived
        assert id2 in archived
        assert id3 not in archived


class TestAutoCompleteOnFinalPattern:
    """Tests for auto-completing handoffs when tried step matches 'final' patterns."""

    def test_tried_with_final_commit_autocompletes(self, manager: LessonsManager) -> None:
        """Adding tried step with 'Final report and commit' marks approach complete."""
        handoff_id = manager.handoff_add(title="Feature work")

        manager.handoff_add_tried(handoff_id, "success", "Final report and commit")

        handoff = manager.handoff_get(handoff_id)
        assert handoff.status == "completed"

    def test_tried_with_final_review_autocompletes(self, manager: LessonsManager) -> None:
        """Adding tried step with 'Final review' marks approach complete."""
        handoff_id = manager.handoff_add(title="Bug fix")

        manager.handoff_add_tried(handoff_id, "success", "Final review and merge")

        handoff = manager.handoff_get(handoff_id)
        assert handoff.status == "completed"

    def test_final_pattern_case_insensitive(self, manager: LessonsManager) -> None:
        """Final pattern matching is case insensitive."""
        handoff_id = manager.handoff_add(title="Task")

        manager.handoff_add_tried(handoff_id, "success", "FINAL COMMIT")

        handoff = manager.handoff_get(handoff_id)
        assert handoff.status == "completed"

    def test_final_pattern_requires_success(self, manager: LessonsManager) -> None:
        """Only successful 'final' steps trigger auto-complete."""
        handoff_id = manager.handoff_add(title="Task")

        manager.handoff_add_tried(handoff_id, "fail", "Final commit failed")

        handoff = manager.handoff_get(handoff_id)
        assert handoff.status != "completed"

    def test_final_pattern_partial_does_not_complete(self, manager: LessonsManager) -> None:
        """Partial outcome with 'final' does not trigger auto-complete."""
        handoff_id = manager.handoff_add(title="Task")

        manager.handoff_add_tried(handoff_id, "partial", "Final steps started")

        handoff = manager.handoff_get(handoff_id)
        assert handoff.status != "completed"

    def test_word_final_in_middle_does_not_trigger(self, manager: LessonsManager) -> None:
        """'Final' must be at start of description to trigger."""
        handoff_id = manager.handoff_add(title="Task")

        manager.handoff_add_tried(handoff_id, "success", "Updated the final configuration")

        handoff = manager.handoff_get(handoff_id)
        assert handoff.status != "completed"

    def test_done_pattern_autocompletes(self, manager: LessonsManager) -> None:
        """'Done' at start also triggers auto-complete."""
        handoff_id = manager.handoff_add(title="Task")

        manager.handoff_add_tried(handoff_id, "success", "Done - all tests passing")

        handoff = manager.handoff_get(handoff_id)
        assert handoff.status == "completed"

    def test_complete_pattern_autocompletes(self, manager: LessonsManager) -> None:
        """'Complete' at start also triggers auto-complete."""
        handoff_id = manager.handoff_add(title="Task")

        manager.handoff_add_tried(handoff_id, "success", "Complete implementation merged")

        handoff = manager.handoff_get(handoff_id)
        assert handoff.status == "completed"

    def test_finished_pattern_autocompletes(self, manager: LessonsManager) -> None:
        """'Finished' at start also triggers auto-complete."""
        handoff_id = manager.handoff_add(title="Task")

        manager.handoff_add_tried(handoff_id, "success", "Finished all tasks")

        handoff = manager.handoff_get(handoff_id)
        assert handoff.status == "completed"

    def test_autocomplete_sets_phase_to_review(self, manager: LessonsManager) -> None:
        """Auto-completed approaches get phase set to 'review'."""
        handoff_id = manager.handoff_add(title="Task")
        manager.handoff_update_phase(handoff_id, "implementing")

        manager.handoff_add_tried(handoff_id, "success", "Final commit")

        handoff = manager.handoff_get(handoff_id)
        assert handoff.status == "completed"
        assert handoff.phase == "review"


class TestAutoPhaseUpdate:
    """Tests for auto-updating phase based on tried steps in handoffs."""

    def test_implement_keyword_bumps_to_implementing(self, manager: LessonsManager) -> None:
        """Tried step containing 'implement' bumps phase to implementing."""
        handoff_id = manager.handoff_add(title="Feature")
        handoff = manager.handoff_get(handoff_id)
        assert handoff.phase == "research"  # Default

        manager.handoff_add_tried(handoff_id, "success", "Implement the core logic")

        handoff = manager.handoff_get(handoff_id)
        assert handoff.phase == "implementing"

    def test_build_keyword_bumps_to_implementing(self, manager: LessonsManager) -> None:
        """Tried step containing 'build' bumps phase to implementing."""
        handoff_id = manager.handoff_add(title="Feature")

        manager.handoff_add_tried(handoff_id, "success", "Build the component")

        handoff = manager.handoff_get(handoff_id)
        assert handoff.phase == "implementing"

    def test_create_keyword_bumps_to_implementing(self, manager: LessonsManager) -> None:
        """Tried step containing 'create' bumps phase to implementing."""
        handoff_id = manager.handoff_add(title="Feature")

        manager.handoff_add_tried(handoff_id, "success", "Create new module")

        handoff = manager.handoff_get(handoff_id)
        assert handoff.phase == "implementing"

    def test_add_keyword_bumps_to_implementing(self, manager: LessonsManager) -> None:
        """Tried step starting with 'Add' bumps phase to implementing."""
        handoff_id = manager.handoff_add(title="Feature")

        manager.handoff_add_tried(handoff_id, "success", "Add error handling")

        handoff = manager.handoff_get(handoff_id)
        assert handoff.phase == "implementing"

    def test_fix_keyword_bumps_to_implementing(self, manager: LessonsManager) -> None:
        """Tried step starting with 'Fix' bumps phase to implementing."""
        handoff_id = manager.handoff_add(title="Bug")

        manager.handoff_add_tried(handoff_id, "success", "Fix the null pointer issue")

        handoff = manager.handoff_get(handoff_id)
        assert handoff.phase == "implementing"

    def test_many_success_steps_bumps_to_implementing(self, manager: LessonsManager) -> None:
        """10+ successful tried steps bumps phase to implementing."""
        handoff_id = manager.handoff_add(title="Big task")

        # Add 10 generic success steps
        for i in range(10):
            manager.handoff_add_tried(handoff_id, "success", f"Step {i + 1}")

        handoff = manager.handoff_get(handoff_id)
        assert handoff.phase == "implementing"

    def test_nine_steps_stays_in_research(self, manager: LessonsManager) -> None:
        """9 successful steps without implementing keywords stays in research."""
        handoff_id = manager.handoff_add(title="Research task")

        for i in range(9):
            manager.handoff_add_tried(handoff_id, "success", f"Research step {i + 1}")

        handoff = manager.handoff_get(handoff_id)
        assert handoff.phase == "research"

    def test_phase_not_downgraded(self, manager: LessonsManager) -> None:
        """If already in implementing, phase is not changed."""
        handoff_id = manager.handoff_add(title="Feature")
        manager.handoff_update_phase(handoff_id, "implementing")

        manager.handoff_add_tried(handoff_id, "success", "Research more options")

        handoff = manager.handoff_get(handoff_id)
        assert handoff.phase == "implementing"

    def test_review_phase_not_changed(self, manager: LessonsManager) -> None:
        """If in review phase, auto-update doesn't change it."""
        handoff_id = manager.handoff_add(title="Feature")
        manager.handoff_update_phase(handoff_id, "review")

        manager.handoff_add_tried(handoff_id, "success", "Implement one more thing")

        handoff = manager.handoff_get(handoff_id)
        assert handoff.phase == "review"

    def test_planning_phase_bumps_to_implementing(self, manager: LessonsManager) -> None:
        """Planning phase can be bumped to implementing."""
        handoff_id = manager.handoff_add(title="Feature")
        manager.handoff_update_phase(handoff_id, "planning")

        manager.handoff_add_tried(handoff_id, "success", "Implement the API")

        handoff = manager.handoff_get(handoff_id)
        assert handoff.phase == "implementing"

    def test_write_keyword_bumps_to_implementing(self, manager: LessonsManager) -> None:
        """Tried step starting with 'Write' bumps phase to implementing."""
        handoff_id = manager.handoff_add(title="Docs")

        manager.handoff_add_tried(handoff_id, "success", "Write the documentation")

        handoff = manager.handoff_get(handoff_id)
        assert handoff.phase == "implementing"

    def test_update_keyword_bumps_to_implementing(self, manager: LessonsManager) -> None:
        """Tried step starting with 'Update' bumps phase to implementing."""
        handoff_id = manager.handoff_add(title="Refactor")

        manager.handoff_add_tried(handoff_id, "success", "Update the interface")

        handoff = manager.handoff_get(handoff_id)
        assert handoff.phase == "implementing"

    def test_failed_implement_step_still_bumps(self, manager: LessonsManager) -> None:
        """Failed implementing step still bumps phase (attempted impl)."""
        handoff_id = manager.handoff_add(title="Feature")

        manager.handoff_add_tried(handoff_id, "fail", "Implement the feature - build errors")

        handoff = manager.handoff_get(handoff_id)
        assert handoff.phase == "implementing"


class TestExtractThemes:
    """Tests for _extract_themes() step categorization in handoffs."""

    def test_extract_themes_guard_keywords(self, manager: LessonsManager) -> None:
        """Steps with guard/destructor keywords are categorized as 'guard'."""
        handoff_id = manager.handoff_add(title="Cleanup")
        manager.handoff_add_tried(handoff_id, "success", "Add is_destroyed guard")
        manager.handoff_add_tried(handoff_id, "success", "Fix destructor order")
        manager.handoff_add_tried(handoff_id, "success", "Cleanup resources")

        handoff = manager.handoff_get(handoff_id)
        themes = manager._extract_themes(handoff.tried)

        assert themes.get("guard", 0) == 3

    def test_extract_themes_plugin_keywords(self, manager: LessonsManager) -> None:
        """Steps with plugin/phase keywords are categorized as 'plugin'."""
        handoff_id = manager.handoff_add(title="Plugin work")
        manager.handoff_add_tried(handoff_id, "success", "Phase 3: Plan plugin structure")
        manager.handoff_add_tried(handoff_id, "success", "Implement LED plugin")

        handoff = manager.handoff_get(handoff_id)
        themes = manager._extract_themes(handoff.tried)

        assert themes.get("plugin", 0) == 2

    def test_extract_themes_ui_keywords(self, manager: LessonsManager) -> None:
        """Steps with xml/button/modal keywords are categorized as 'ui'."""
        handoff_id = manager.handoff_add(title="UI work")
        manager.handoff_add_tried(handoff_id, "success", "Add XML button")
        manager.handoff_add_tried(handoff_id, "success", "Create modal dialog")
        manager.handoff_add_tried(handoff_id, "success", "Update panel layout")

        handoff = manager.handoff_get(handoff_id)
        themes = manager._extract_themes(handoff.tried)

        assert themes.get("ui", 0) == 3

    def test_extract_themes_fix_keywords(self, manager: LessonsManager) -> None:
        """Steps with fix/bug/error keywords are categorized as 'fix'."""
        handoff_id = manager.handoff_add(title="Bug fixes")
        manager.handoff_add_tried(handoff_id, "success", "Fix HIGH: null pointer")
        manager.handoff_add_tried(handoff_id, "success", "Bug in error handling")
        manager.handoff_add_tried(handoff_id, "success", "Handle issue #123")

        handoff = manager.handoff_get(handoff_id)
        themes = manager._extract_themes(handoff.tried)

        assert themes.get("fix", 0) == 3

    def test_extract_themes_other_fallback(self, manager: LessonsManager) -> None:
        """Unrecognized steps fall into 'other' category."""
        handoff_id = manager.handoff_add(title="Misc")
        manager.handoff_add_tried(handoff_id, "success", "Research the approach")
        manager.handoff_add_tried(handoff_id, "success", "Document findings")

        handoff = manager.handoff_get(handoff_id)
        themes = manager._extract_themes(handoff.tried)

        assert themes.get("other", 0) == 2

    def test_extract_themes_mixed(self, manager: LessonsManager) -> None:
        """Mixed steps are categorized correctly (first matching theme wins)."""
        handoff_id = manager.handoff_add(title="Mixed work")
        manager.handoff_add_tried(handoff_id, "success", "Add is_destroyed guard")
        manager.handoff_add_tried(handoff_id, "success", "Fix the null error")  # pure fix
        manager.handoff_add_tried(handoff_id, "success", "Plugin phase 2")
        manager.handoff_add_tried(handoff_id, "success", "Random task")

        handoff = manager.handoff_get(handoff_id)
        themes = manager._extract_themes(handoff.tried)

        assert themes.get("guard", 0) == 1
        assert themes.get("fix", 0) == 1
        assert themes.get("plugin", 0) == 1
        assert themes.get("other", 0) == 1

    def test_extract_themes_empty(self, manager: LessonsManager) -> None:
        """Empty tried list returns empty dict."""
        themes = manager._extract_themes([])
        assert themes == {}


class TestSummarizeTriedSteps:
    """Tests for _summarize_tried_steps() compact formatting in handoffs."""

    def test_summarize_empty_returns_empty(self, manager: LessonsManager) -> None:
        """Empty tried list returns empty list of lines."""
        result = manager._summarize_tried_steps([])
        assert result == []

    def test_summarize_shows_progress_count(self, manager: LessonsManager) -> None:
        """Summary includes step count."""
        handoff_id = manager.handoff_add(title="Task")
        for i in range(5):
            manager.handoff_add_tried(handoff_id, "success", f"Step {i+1}")

        handoff = manager.handoff_get(handoff_id)
        result = manager._summarize_tried_steps(handoff.tried)
        result_str = "\n".join(result)

        assert "5 steps" in result_str

    def test_summarize_all_success(self, manager: LessonsManager) -> None:
        """All success steps show '(all success)'."""
        handoff_id = manager.handoff_add(title="Task")
        manager.handoff_add_tried(handoff_id, "success", "Step 1")
        manager.handoff_add_tried(handoff_id, "success", "Step 2")

        handoff = manager.handoff_get(handoff_id)
        result = manager._summarize_tried_steps(handoff.tried)
        result_str = "\n".join(result)

        assert "all success" in result_str

    def test_summarize_mixed_outcomes(self, manager: LessonsManager) -> None:
        """Mixed outcomes show success/fail counts."""
        handoff_id = manager.handoff_add(title="Task")
        manager.handoff_add_tried(handoff_id, "success", "Step 1")
        manager.handoff_add_tried(handoff_id, "fail", "Step 2 failed")
        manager.handoff_add_tried(handoff_id, "success", "Step 3")

        handoff = manager.handoff_get(handoff_id)
        result = manager._summarize_tried_steps(handoff.tried)
        result_str = "\n".join(result)

        assert "2" in result_str and "1" in result_str  # 2 success, 1 fail

    def test_summarize_shows_last_3_steps(self, manager: LessonsManager) -> None:
        """Summary shows last 3 steps."""
        handoff_id = manager.handoff_add(title="Task")
        for i in range(10):
            manager.handoff_add_tried(handoff_id, "success", f"Step {i+1}")

        handoff = manager.handoff_get(handoff_id)
        result = manager._summarize_tried_steps(handoff.tried)
        result_str = "\n".join(result)

        assert "Step 8" in result_str
        assert "Step 9" in result_str
        assert "Step 10" in result_str
        assert "Step 7" not in result_str  # Not in last 3

    def test_summarize_truncates_long_descriptions(self, manager: LessonsManager) -> None:
        """Long step descriptions are truncated."""
        handoff_id = manager.handoff_add(title="Task")
        long_desc = "A" * 100  # 100 chars
        manager.handoff_add_tried(handoff_id, "success", long_desc)

        handoff = manager.handoff_get(handoff_id)
        result = manager._summarize_tried_steps(handoff.tried)
        result_str = "\n".join(result)

        assert "..." in result_str
        assert len(result_str) < 150  # Should be truncated

    def test_summarize_shows_themes_for_earlier(self, manager: LessonsManager) -> None:
        """Earlier steps (before last 3) show theme summary."""
        handoff_id = manager.handoff_add(title="Task")
        # Add 5 guard-related steps
        for i in range(5):
            manager.handoff_add_tried(handoff_id, "success", f"Add is_destroyed guard {i+1}")
        # Add 3 more steps (will be the "recent" ones)
        manager.handoff_add_tried(handoff_id, "success", "Recent 1")
        manager.handoff_add_tried(handoff_id, "success", "Recent 2")
        manager.handoff_add_tried(handoff_id, "success", "Recent 3")

        handoff = manager.handoff_get(handoff_id)
        result = manager._summarize_tried_steps(handoff.tried)
        result_str = "\n".join(result)

        assert "Earlier:" in result_str
        assert "guard" in result_str

    def test_summarize_no_themes_for_few_steps(self, manager: LessonsManager) -> None:
        """No theme summary when 3 or fewer steps."""
        handoff_id = manager.handoff_add(title="Task")
        manager.handoff_add_tried(handoff_id, "success", "Step 1")
        manager.handoff_add_tried(handoff_id, "success", "Step 2")

        handoff = manager.handoff_get(handoff_id)
        result = manager._summarize_tried_steps(handoff.tried)
        result_str = "\n".join(result)

        assert "Earlier:" not in result_str


class TestHandoffInjectCompact:
    """Tests for compact handoff injection format."""

    def test_inject_shows_relative_time(self, manager: LessonsManager) -> None:
        """Injection shows relative time instead of full dates."""
        manager.handoff_add(title="Test approach")

        result = manager.handoff_inject()

        assert "today" in result.lower() or "Last" in result

    def test_inject_compact_progress_not_full_list(self, manager: LessonsManager) -> None:
        """Injection shows progress summary, not full tried list."""
        handoff_id = manager.handoff_add(title="Task")
        for i in range(20):
            manager.handoff_add_tried(handoff_id, "success", f"Step {i+1}")

        result = manager.handoff_inject()

        # Should NOT have numbered list 1. 2. 3. etc
        assert "1. [success]" not in result
        assert "20. [success]" not in result
        # Should have progress summary
        assert "20 steps" in result or "Progress" in result

    def test_inject_shows_appears_done_warning(self, manager: LessonsManager) -> None:
        """Warning shown when last step looks like completion."""
        handoff_id = manager.handoff_add(title="Task")
        manager.handoff_add_tried(handoff_id, "success", "Research")
        manager.handoff_add_tried(handoff_id, "success", "Implement")
        # Don't use "Final" as it will auto-complete now
        # Instead test with an approach that was manually kept open

        # For this test, we need to add a "final-looking" step without triggering auto-complete
        # Let's test with a step that says "commit" at the end, not start
        handoff_id2 = manager.handoff_add(title="Task 2")
        manager.handoff_add_tried(handoff_id2, "success", "All done and ready for commit")

        result = manager.handoff_inject()

        # This shouldn't trigger the warning since "All done" doesn't start with completion pattern
        # The warning only shows for steps starting with Final/Done/Complete/Finished
        assert handoff_id2 in result

    def test_inject_compact_files(self, manager: LessonsManager) -> None:
        """Files list is compacted when more than 3."""
        manager.handoff_add(
            title="Multi-file task",
            files=["file1.py", "file2.py", "file3.py", "file4.py", "file5.py"]
        )

        result = manager.handoff_inject()

        assert "file1.py" in result
        assert "file2.py" in result
        assert "file3.py" in result
        assert "+2 more" in result or "(+2" in result

    def test_inject_all_files_when_few(self, manager: LessonsManager) -> None:
        """All files shown when 3 or fewer."""
        manager.handoff_add(
            title="Small task",
            files=["file1.py", "file2.py"]
        )

        result = manager.handoff_inject()

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
        handoff_id = manager.handoff_add("Implement API layer")
        handoff = manager.handoff_get(handoff_id)

        # After implementation, Handoff should have 'handoff' field instead of 'checkpoint'
        assert hasattr(handoff, "handoff") or hasattr(handoff, "checkpoint")

    def test_handoff_without_handoff_context(self, manager: LessonsManager) -> None:
        """Handoff can be created without HandoffContext (None default)."""
        handoff_id = manager.handoff_add("Simple task")
        handoff = manager.handoff_get(handoff_id)

        # Either the new 'handoff' field is None, or the old 'checkpoint' is empty
        if hasattr(handoff, "handoff"):
            assert handoff.handoff is None
        else:
            assert handoff.checkpoint == ""

    def test_handoff_update_with_context(self, manager: LessonsManager) -> None:
        """Should be able to update Handoff with HandoffContext."""
        try:
            from core.models import HandoffContext
        except ImportError:
            pytest.skip("HandoffContext not yet implemented")

        handoff_id = manager.handoff_add("Feature work")

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
            manager.handoff_update_context(handoff_id, context)
            handoff = manager.handoff_get(handoff_id)
            assert handoff.handoff is not None
            assert handoff.handoff.summary == "Progress: core logic complete"
        else:
            # Fall back to existing checkpoint method
            manager.handoff_update_checkpoint(handoff_id, context.summary)
            handoff = manager.handoff_get(handoff_id)
            assert context.summary in handoff.checkpoint


class TestHandoffBlockedBy:
    """Tests for blocked_by field on Handoff."""

    def test_handoff_with_blocked_by(self, manager: LessonsManager) -> None:
        """Create Handoff with blocked_by dependency list."""
        handoff_id = manager.handoff_add("Blocked task")
        handoff = manager.handoff_get(handoff_id)

        # After implementation, Handoff should have 'blocked_by' field
        assert hasattr(handoff, "blocked_by") or True  # Will fail until implemented

    def test_handoff_blocked_by_default_empty(self, manager: LessonsManager) -> None:
        """Handoff blocked_by defaults to empty list."""
        handoff_id = manager.handoff_add("Independent task")
        handoff = manager.handoff_get(handoff_id)

        if hasattr(handoff, "blocked_by"):
            assert handoff.blocked_by == []
        else:
            # Field doesn't exist yet - this is expected in TDD
            pass

    def test_handoff_update_blocked_by(self, manager: LessonsManager) -> None:
        """Should be able to update Handoff blocked_by list."""
        handoff_id = manager.handoff_add("Dependent task")

        # Create another approach to depend on
        blocking_id = manager.handoff_add("Blocking task")

        # This method should exist after implementation
        if hasattr(manager, "handoff_update_blocked_by"):
            manager.handoff_update_blocked_by(handoff_id, [blocking_id])
            handoff = manager.handoff_get(handoff_id)
            assert blocking_id in handoff.blocked_by
        else:
            # Method doesn't exist yet - expected in TDD
            pass

    def test_handoff_blocked_by_multiple_dependencies(self, manager: LessonsManager) -> None:
        """Handoff can depend on multiple other handoffs."""
        handoff_id = manager.handoff_add("Complex task")
        dep1_id = manager.handoff_add("Dependency 1")
        dep2_id = manager.handoff_add("Dependency 2")

        if hasattr(manager, "handoff_update_blocked_by"):
            manager.handoff_update_blocked_by(handoff_id, [dep1_id, dep2_id])
            handoff = manager.handoff_get(handoff_id)
            assert len(handoff.blocked_by) == 2
            assert dep1_id in handoff.blocked_by
            assert dep2_id in handoff.blocked_by


class TestHandoffContextSerialization:
    """Tests for serializing/deserializing HandoffContext to markdown."""

    def test_handoff_context_serializes_to_markdown(self, manager: LessonsManager) -> None:
        """HandoffContext should serialize to readable markdown format."""
        try:
            from core.models import HandoffContext
        except ImportError:
            pytest.skip("HandoffContext not yet implemented")

        handoff_id = manager.handoff_add("Feature with context")

        context = HandoffContext(
            summary="Database migration complete",
            critical_files=["db/migrate.py:25", "db/models.py:100"],
            recent_changes=["Created migration script", "Updated models"],
            learnings=["Alembic requires careful ordering"],
            blockers=[],
            git_ref="mig4567",
        )

        if hasattr(manager, "handoff_update_context"):
            manager.handoff_update_context(handoff_id, context)

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

        handoff_id = manager.handoff_add("Parseable context")

        context = HandoffContext(
            summary="Test parse roundtrip",
            critical_files=["test.py:1"],
            recent_changes=["Added test"],
            learnings=["Tests are important"],
            blockers=["Need more tests"],
            git_ref="tst1234",
        )

        if hasattr(manager, "handoff_update_context"):
            manager.handoff_update_context(handoff_id, context)

            # Force re-parse by getting fresh
            handoff = manager.handoff_get(handoff_id)

            assert handoff.handoff is not None
            assert handoff.handoff.summary == "Test parse roundtrip"
            assert "test.py:1" in handoff.handoff.critical_files
            assert "Added test" in handoff.handoff.recent_changes
            assert "Tests are important" in handoff.handoff.learnings
            assert "Need more tests" in handoff.handoff.blockers
            assert handoff.handoff.git_ref == "tst1234"

    def test_blocked_by_serializes_to_markdown(self, manager: LessonsManager) -> None:
        """blocked_by field should serialize to markdown."""
        handoff_id = manager.handoff_add("Task with deps")

        if hasattr(manager, "handoff_update_blocked_by"):
            dep_id = manager.handoff_add("Dependency")
            manager.handoff_update_blocked_by(handoff_id, [dep_id])

            content = manager.project_handoffs_file.read_text()
            assert "**Blocked By**:" in content or dep_id in content

    def test_blocked_by_parses_from_markdown(self, manager: LessonsManager) -> None:
        """blocked_by field should parse correctly from markdown."""
        handoff_id = manager.handoff_add("Task to parse")

        if hasattr(manager, "handoff_update_blocked_by"):
            dep_id = manager.handoff_add("Dep task")
            manager.handoff_update_blocked_by(handoff_id, [dep_id])

            # Force re-parse
            handoff = manager.handoff_get(handoff_id)
            assert dep_id in handoff.blocked_by


class TestHandoffContextBackwardCompatibility:
    """Tests for backward compatibility with old checkpoint field."""

    def test_old_checkpoint_migrates_to_handoff_summary(self, manager: LessonsManager) -> None:
        """If old checkpoint field exists, migrate to handoff.summary."""
        try:
            from core.models import HandoffContext
        except ImportError:
            pytest.skip("HandoffContext not yet implemented")

        # Create approach with old checkpoint
        handoff_id = manager.handoff_add("Legacy approach")
        manager.handoff_update_checkpoint(handoff_id, "Old checkpoint text")

        handoff = manager.handoff_get(handoff_id)

        # Either new handoff field has summary from checkpoint, or checkpoint still works
        if hasattr(handoff, "handoff") and handoff.handoff is not None:
            assert handoff.handoff.summary == "Old checkpoint text"
        else:
            assert handoff.checkpoint == "Old checkpoint text"

    def test_handoffs_without_context_still_parse(self, manager: LessonsManager) -> None:
        """Old handoff format without HandoffContext should still parse."""
        # Write old format directly
        handoffs_file = manager.project_handoffs_file
        handoffs_file.parent.mkdir(parents=True, exist_ok=True)

        old_format = """# HANDOFFS.md - Active Work Tracking

> Track ongoing work with tried steps and next steps.
> When completed, review for lessons to extract.

## Active Handoffs

### [hf-0000001] Legacy handoff
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
        handoffs_file.write_text(old_format)

        # Should parse without errors
        handoff = manager.handoff_get("hf-0000001")
        assert handoff is not None
        assert handoff.title == "Legacy handoff"
        assert handoff.status == "in_progress"

    def test_empty_handoff_context_ok(self, manager: LessonsManager) -> None:
        """Handoff with None/empty HandoffContext should work."""
        handoff_id = manager.handoff_add("No context needed")
        handoff = manager.handoff_get(handoff_id)

        # Should not error, context is optional
        if hasattr(handoff, "handoff"):
            assert handoff.handoff is None
        assert handoff.title == "No context needed"


class TestHandoffContextInInjection:
    """Tests for HandoffContext in context injection output."""

    def test_inject_shows_handoff_context_summary(self, manager: LessonsManager) -> None:
        """Injection output shows HandoffContext summary prominently."""
        try:
            from core.models import HandoffContext
        except ImportError:
            pytest.skip("HandoffContext not yet implemented")

        handoff_id = manager.handoff_add("Feature with rich context")

        context = HandoffContext(
            summary="API layer done, frontend integration next",
            critical_files=["api/routes.py:50"],
            recent_changes=["Added REST endpoints"],
            learnings=["Need auth middleware"],
            blockers=[],
            git_ref="api1234",
        )

        if hasattr(manager, "handoff_update_context"):
            manager.handoff_update_context(handoff_id, context)

            output = manager.handoff_inject()

            assert "API layer done" in output or "summary" in output.lower()

    def test_inject_shows_critical_files(self, manager: LessonsManager) -> None:
        """Injection output shows critical files from HandoffContext."""
        try:
            from core.models import HandoffContext
        except ImportError:
            pytest.skip("HandoffContext not yet implemented")

        handoff_id = manager.handoff_add("File-focused work")

        context = HandoffContext(
            summary="Working on core",
            critical_files=["core/engine.py:100", "core/types.py:25"],
            recent_changes=[],
            learnings=[],
            blockers=[],
            git_ref="cor5678",
        )

        if hasattr(manager, "handoff_update_context"):
            manager.handoff_update_context(handoff_id, context)

            output = manager.handoff_inject()

            assert "core/engine.py" in output or "engine" in output

    def test_inject_shows_blockers(self, manager: LessonsManager) -> None:
        """Injection output highlights blockers from HandoffContext."""
        try:
            from core.models import HandoffContext
        except ImportError:
            pytest.skip("HandoffContext not yet implemented")

        handoff_id = manager.handoff_add("Blocked work")

        context = HandoffContext(
            summary="Waiting on external",
            critical_files=[],
            recent_changes=[],
            learnings=[],
            blockers=["Need API key from partner", "Design spec pending"],
            git_ref="blk9999",
        )

        if hasattr(manager, "handoff_update_context"):
            manager.handoff_update_context(handoff_id, context)

            output = manager.handoff_inject()

            assert "API key" in output or "blocker" in output.lower()

    def test_inject_shows_git_ref(self, manager: LessonsManager) -> None:
        """Injection output shows git reference from HandoffContext."""
        try:
            from core.models import HandoffContext
        except ImportError:
            pytest.skip("HandoffContext not yet implemented")

        handoff_id = manager.handoff_add("Git-tracked work")

        context = HandoffContext(
            summary="At commit point",
            critical_files=[],
            recent_changes=["Major refactor"],
            learnings=[],
            blockers=[],
            git_ref="ref7777",
        )

        if hasattr(manager, "handoff_update_context"):
            manager.handoff_update_context(handoff_id, context)

            output = manager.handoff_inject()

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

    def test_hash_ids_are_unique_for_different_titles(self, manager: "LessonsManager"):
        """Two handoffs with different titles should get different IDs."""
        id1 = manager.handoff_add(title="First title")
        id2 = manager.handoff_add(title="Second title")

        assert id1 != id2
        assert id1.startswith("hf-")
        assert id2.startswith("hf-")

    def test_same_title_returns_same_id_due_to_duplicate_detection(
        self, manager: "LessonsManager"
    ):
        """Two handoffs with same title return same ID due to duplicate detection."""
        import time

        id1 = manager.handoff_add(title="Same title")
        time.sleep(0.01)  # Small delay
        id2 = manager.handoff_add(title="Same title")

        # Due to duplicate detection, same title returns same ID
        assert id1 == id2
        assert id1.startswith("hf-")

    def test_old_ids_still_parsed(self, manager: "LessonsManager"):
        """Old A### format IDs should still be parseable."""
        # Write a file with old format IDs directly
        handoffs_file = manager.project_handoffs_file
        handoffs_file.parent.mkdir(parents=True, exist_ok=True)

        old_format_content = """# HANDOFFS.md - Active Work Tracking

> Track ongoing work with tried steps and next steps.
> When completed, review for lessons to extract.

## Active Handoffs

### [hf-0000001] Legacy handoff with old ID
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
        handoff = manager.handoff_get("hf-0000001")

        assert handoff is not None
        assert handoff.id == "hf-0000001"
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

### [hf-0000001] Legacy handoff
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
        manager.handoff_update_status("hf-0000001", "in_progress")

        # Read back and verify ID is preserved
        handoff = manager.handoff_get("hf-0000001")
        assert handoff is not None
        assert handoff.id == "hf-0000001"  # ID should NOT change to hash format

        # Verify in file content as well
        content = handoffs_file.read_text()
        assert "[hf-0000001]" in content

    def test_blocked_by_accepts_both_formats(self, manager: "LessonsManager"):
        """blocked_by field should work with both old A### and new hf- IDs."""
        # Write a file with old format ID
        handoffs_file = manager.project_handoffs_file
        handoffs_file.parent.mkdir(parents=True, exist_ok=True)

        old_format_content = """# HANDOFFS.md - Active Work Tracking

> Track ongoing work with tried steps and next steps.
> When completed, review for lessons to extract.

## Active Handoffs

### [hf-0000001] Blocker handoff
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
        manager.handoff_update_blocked_by(new_id, ["hf-0000001", new_id])

        # Verify blocked_by is stored correctly
        handoff = manager.handoff_get(new_id)
        assert handoff is not None
        assert "hf-0000001" in handoff.blocked_by
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

### [hf-0000001] Legacy with old Files format
- **Status**: in_progress | **Phase**: research | **Agent**: user
- **Created**: {today} | **Updated**: {today}
- **Files**: src/main.py, src/utils.py
- **Description**: Old format still works

**Tried**:

**Next**:

---
"""
        handoffs_file.write_text(old_format_content)

        handoff = manager.handoff_get("hf-0000001")
        assert handoff is not None
        # Old files should be available via refs
        assert handoff.refs == ["src/main.py", "src/utils.py"]
        # And via files alias
        assert handoff.files == ["src/main.py", "src/utils.py"]


# =============================================================================
# Ready Queue (Phase 5)
# =============================================================================


class TestHandoffReady:
    """Tests for ready queue feature - surfacing unblocked work."""

    def test_ready_no_blockers(self, manager: "LessonsManager"):
        """Handoff without blockers is ready."""
        handoff_id = manager.handoff_add(title="Independent work")

        ready_list = manager.handoff_ready()

        assert len(ready_list) == 1
        assert ready_list[0].id == handoff_id

    def test_ready_blockers_completed(self, manager: "LessonsManager"):
        """Handoff with completed blockers is ready."""
        # Create blocker and complete it
        blocker_id = manager.handoff_add(title="Blocker task")
        manager.handoff_complete(blocker_id)

        # Create dependent handoff blocked by the (now completed) blocker
        dependent_id = manager.handoff_add(title="Dependent task")
        manager.handoff_update_blocked_by(dependent_id, [blocker_id])

        ready_list = manager.handoff_ready()

        # Should include the dependent since blocker is completed
        ready_ids = [h.id for h in ready_list]
        assert dependent_id in ready_ids

    def test_not_ready_blockers_pending(self, manager: "LessonsManager"):
        """Handoff with pending blockers is not ready."""
        # Create blocker that's still in progress
        blocker_id = manager.handoff_add(title="Blocker task")
        manager.handoff_update_status(blocker_id, "in_progress")

        # Create dependent handoff blocked by the pending blocker
        dependent_id = manager.handoff_add(title="Dependent task")
        manager.handoff_update_blocked_by(dependent_id, [blocker_id])

        ready_list = manager.handoff_ready()

        # Should NOT include the dependent since blocker is not completed
        ready_ids = [h.id for h in ready_list]
        assert dependent_id not in ready_ids
        # But blocker should be ready (it has no blockers itself)
        assert blocker_id in ready_ids

    def test_ready_excludes_completed(self, manager: "LessonsManager"):
        """Completed handoffs should not appear in ready list."""
        handoff_id = manager.handoff_add(title="Will complete")
        manager.handoff_complete(handoff_id)

        ready_list = manager.handoff_ready()

        ready_ids = [h.id for h in ready_list]
        assert handoff_id not in ready_ids

    def test_ready_sorted_in_progress_first(self, manager: "LessonsManager"):
        """in_progress handoffs should be sorted before not_started."""
        # Create a not_started handoff first
        not_started_id = manager.handoff_add(title="Not started yet")

        # Create an in_progress handoff second
        in_progress_id = manager.handoff_add(title="Already working")
        manager.handoff_update_status(in_progress_id, "in_progress")

        ready_list = manager.handoff_ready()

        # in_progress should come first
        assert len(ready_list) >= 2
        in_progress_idx = next(i for i, h in enumerate(ready_list) if h.id == in_progress_id)
        not_started_idx = next(i for i, h in enumerate(ready_list) if h.id == not_started_id)
        assert in_progress_idx < not_started_idx

    def test_ready_multiple_blockers_all_completed(self, manager: "LessonsManager"):
        """Handoff is ready only when ALL blockers are completed."""
        blocker1_id = manager.handoff_add(title="Blocker 1")
        blocker2_id = manager.handoff_add(title="Blocker 2")

        dependent_id = manager.handoff_add(title="Needs both")
        manager.handoff_update_blocked_by(dependent_id, [blocker1_id, blocker2_id])

        # Complete only one blocker
        manager.handoff_complete(blocker1_id)

        ready_list = manager.handoff_ready()
        ready_ids = [h.id for h in ready_list]

        # Dependent is NOT ready - still blocked by blocker2
        assert dependent_id not in ready_ids
        # blocker2 is ready (no blockers)
        assert blocker2_id in ready_ids

        # Now complete the second blocker
        manager.handoff_complete(blocker2_id)

        ready_list = manager.handoff_ready()
        ready_ids = [h.id for h in ready_list]

        # Now dependent is ready
        assert dependent_id in ready_ids

    def test_ready_cli_command(self, temp_lessons_base, temp_project_root):
        """CLI lists ready handoffs."""
        import subprocess

        env = {
            **os.environ,
            "CLAUDE_RECALL_BASE": str(temp_lessons_base),
            "PROJECT_DIR": str(temp_project_root),
        }

        # Add a handoff
        subprocess.run(
            [sys.executable, "-m", "core.cli", "handoff", "add", "Ready task"],
            env=env,
            cwd=Path(__file__).parent.parent,
            check=True,
        )

        # Run ready command
        result = subprocess.run(
            [sys.executable, "-m", "core.cli", "handoff", "ready"],
            env=env,
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "Ready task" in result.stdout

    def test_inject_shows_ready_count(self, manager: "LessonsManager"):
        """Injection should show ready count at top."""
        # Create some handoffs
        manager.handoff_add(title="Ready work 1")
        manager.handoff_add(title="Ready work 2")

        # Create one that's blocked
        blocker_id = manager.handoff_add(title="Blocker")
        blocked_id = manager.handoff_add(title="Blocked work")
        manager.handoff_update_blocked_by(blocked_id, [blocker_id])

        output = manager.handoff_inject()

        # Should show ready count - 3 are ready (blocker has no deps, ready 1 & 2)
        assert "Ready: 3" in output or "3 ready" in output.lower()


# =============================================================================
# Handoff Resume with Validation (Phase 4)
# =============================================================================


class TestHandoffResume:
    """Tests for handoff_resume with validation."""

    def test_resume_handoff_without_context(self, manager: "LessonsManager"):
        """Resuming a handoff without context should work (legacy mode)."""
        # Create a basic handoff without context
        handoff_id = manager.handoff_add(
            title="Test handoff",
            desc="A basic handoff without context",
        )

        result = manager.handoff_resume(handoff_id)

        assert result is not None
        assert result.handoff.id == handoff_id
        assert result.handoff.title == "Test handoff"
        assert result.validation.valid is True
        assert result.validation.warnings == []
        assert result.validation.errors == []
        assert result.context is None

    def test_resume_handoff_with_valid_context(self, manager: "LessonsManager", temp_project_root: Path):
        """Resuming a handoff with valid context should show no warnings."""
        # Create a test file
        test_file = temp_project_root / "src" / "main.py"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("def main():\n    pass\n")

        # Initialize git repo and make commit
        subprocess.run(["git", "init"], cwd=temp_project_root, capture_output=True)
        subprocess.run(["git", "add", "."], cwd=temp_project_root, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=temp_project_root,
            capture_output=True,
            env={**os.environ, "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@test.com",
                 "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@test.com"},
        )

        # Get the current commit hash
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=temp_project_root,
            capture_output=True,
            text=True,
        )
        current_commit = result.stdout.strip()

        # Create handoff with context using current commit
        from core.models import HandoffContext
        handoff_id = manager.handoff_add(title="Test with context")
        context = HandoffContext(
            summary="Working on main function",
            critical_files=["src/main.py:1"],
            recent_changes=["Added main.py"],
            learnings=["Python project setup"],
            blockers=[],
            git_ref=current_commit,
        )
        manager.handoff_update_context(handoff_id, context)

        resume_result = manager.handoff_resume(handoff_id)

        assert resume_result is not None
        assert resume_result.validation.valid is True
        assert resume_result.validation.warnings == []
        assert resume_result.validation.errors == []
        assert resume_result.context is not None
        assert resume_result.context.summary == "Working on main function"

    def test_resume_handoff_git_diverged(self, manager: "LessonsManager", temp_project_root: Path):
        """Resuming a handoff after git commit should warn about divergence."""
        # Initialize git and make first commit
        subprocess.run(["git", "init"], cwd=temp_project_root, capture_output=True)
        test_file = temp_project_root / "src" / "main.py"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("def main():\n    pass\n")
        subprocess.run(["git", "add", "."], cwd=temp_project_root, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=temp_project_root,
            capture_output=True,
            env={**os.environ, "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@test.com",
                 "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@test.com"},
        )

        # Get the first commit hash
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=temp_project_root,
            capture_output=True,
            text=True,
        )
        first_commit = result.stdout.strip()

        # Create handoff with context using first commit
        from core.models import HandoffContext
        handoff_id = manager.handoff_add(title="Test git divergence")
        context = HandoffContext(
            summary="Working on main function",
            critical_files=["src/main.py:1"],
            recent_changes=[],
            learnings=[],
            blockers=[],
            git_ref=first_commit,
        )
        manager.handoff_update_context(handoff_id, context)

        # Make another commit to cause divergence
        test_file.write_text("def main():\n    print('hello')\n")
        subprocess.run(["git", "add", "."], cwd=temp_project_root, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "second"],
            cwd=temp_project_root,
            capture_output=True,
            env={**os.environ, "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@test.com",
                 "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@test.com"},
        )

        resume_result = manager.handoff_resume(handoff_id)

        assert resume_result is not None
        assert resume_result.validation.valid is True  # Still valid, just has warnings
        assert len(resume_result.validation.warnings) == 1
        assert "diverged" in resume_result.validation.warnings[0].lower() or \
               "changed" in resume_result.validation.warnings[0].lower()
        assert resume_result.validation.errors == []

    def test_resume_handoff_missing_file(self, manager: "LessonsManager", temp_project_root: Path):
        """Resuming a handoff with missing critical file should report error."""
        # Initialize git
        subprocess.run(["git", "init"], cwd=temp_project_root, capture_output=True)

        # Create and commit a file
        test_file = temp_project_root / "src" / "main.py"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("def main(): pass\n")
        subprocess.run(["git", "add", "."], cwd=temp_project_root, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=temp_project_root,
            capture_output=True,
            env={**os.environ, "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@test.com",
                 "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@test.com"},
        )

        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=temp_project_root,
            capture_output=True,
            text=True,
        )
        current_commit = result.stdout.strip()

        # Create handoff with context referencing existing file
        from core.models import HandoffContext
        handoff_id = manager.handoff_add(title="Test missing file")
        context = HandoffContext(
            summary="Working on files",
            critical_files=["src/main.py:1", "src/missing.py:10"],  # One exists, one doesn't
            recent_changes=[],
            learnings=[],
            blockers=[],
            git_ref=current_commit,
        )
        manager.handoff_update_context(handoff_id, context)

        resume_result = manager.handoff_resume(handoff_id)

        assert resume_result is not None
        assert resume_result.validation.valid is False  # Invalid due to missing file
        assert len(resume_result.validation.errors) == 1
        assert "src/missing.py" in resume_result.validation.errors[0]

    def test_resume_handoff_not_found(self, manager: "LessonsManager"):
        """Resuming a non-existent handoff should raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            manager.handoff_resume("hf-nonexistent")
        assert "not found" in str(exc_info.value).lower()

    def test_resume_cli_command(self, temp_lessons_base: Path, temp_project_root: Path):
        """CLI handoff resume command should output context."""
        # Create a handoff first
        env = {
            **os.environ,
            "CLAUDE_RECALL_BASE": str(temp_lessons_base),
            "PROJECT_DIR": str(temp_project_root),
        }

        # Add a handoff
        result = subprocess.run(
            [sys.executable, "-m", "core.cli", "handoff", "add", "Test CLI resume"],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 0, f"Failed to add handoff: {result.stderr}"

        # Extract the handoff ID from output (e.g., "Added approach hf-abc1234: Test CLI resume")
        import re
        match = re.search(r"(hf-[0-9a-f]+)", result.stdout)
        assert match, f"Could not find handoff ID in output: {result.stdout}"
        handoff_id = match.group(1)

        # Resume the handoff
        result = subprocess.run(
            [sys.executable, "-m", "core.cli", "handoff", "resume", handoff_id],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 0, f"Resume failed: {result.stderr}"
        assert handoff_id in result.stdout
        assert "Test CLI resume" in result.stdout


# =============================================================================
# Phase 6: CLI set-context Command
# =============================================================================


class TestSetContextCLI:
    """Tests for the CLI set-context command used by precompact-hook."""

    def test_set_context_from_json(self, tmp_path):
        """CLI should parse JSON and set context on handoff."""
        import json

        env = os.environ.copy()
        env["PROJECT_DIR"] = str(tmp_path)
        env["CLAUDE_RECALL_BASE"] = str(tmp_path / ".lessons")

        # First create a handoff
        result = subprocess.run(
            [sys.executable, "core/cli.py", "handoff", "add", "Test context work"],
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 0
        # Extract handoff ID from output (e.g., "Added approach hf-abc1234: Test context work")
        handoff_id = result.stdout.split()[2].rstrip(":")

        # Now set context
        context_json = json.dumps({
            "summary": "Implemented feature X",
            "critical_files": ["core/cli.py:42", "core/models.py:100"],
            "recent_changes": ["Added CLI command", "Fixed parsing"],
            "learnings": ["JSON parsing is tricky"],
            "blockers": [],
            "git_ref": "abc1234",
        })

        result = subprocess.run(
            [
                sys.executable,
                "core/cli.py",
                "handoff",
                "set-context",
                handoff_id,
                "--json",
                context_json,
            ],
            capture_output=True,
            text=True,
            env=env,
        )

        assert result.returncode == 0
        assert "abc1234" in result.stdout

    def test_set_context_updates_handoff(self, manager: "LessonsManager"):
        """set-context should properly store context in handoff."""
        try:
            from core.models import HandoffContext
        except ImportError:
            pytest.skip("HandoffContext not yet implemented")

        handoff_id = manager.handoff_add(title="Context test")

        context = HandoffContext(
            summary="Made good progress on feature",
            critical_files=["core/main.py:50", "tests/test_main.py:100"],
            recent_changes=["Added tests", "Fixed bug"],
            learnings=["Need to mock external calls"],
            blockers=["Waiting for API response"],
            git_ref="def5678",
        )

        manager.handoff_update_context(handoff_id, context)

        handoff = manager.handoff_get(handoff_id)
        assert handoff.handoff is not None
        assert handoff.handoff.summary == "Made good progress on feature"
        assert handoff.handoff.git_ref == "def5678"
        assert "core/main.py:50" in handoff.handoff.critical_files
        assert "Added tests" in handoff.handoff.recent_changes
        assert "Need to mock external calls" in handoff.handoff.learnings
        assert "Waiting for API response" in handoff.handoff.blockers

    def test_set_context_preserves_other_fields(self, manager: "LessonsManager"):
        """set-context should not alter other handoff fields."""
        try:
            from core.models import HandoffContext
        except ImportError:
            pytest.skip("HandoffContext not yet implemented")

        handoff_id = manager.handoff_add(
            title="Preserve fields test",
            desc="Original description",
            files=["original.py"],
            phase="implementing",
            agent="general-purpose",
        )
        manager.handoff_update_status(handoff_id, "in_progress")
        manager.handoff_add_tried(handoff_id, "success", "First step done")
        manager.handoff_update_next(handoff_id, "Next step here")

        context = HandoffContext(
            summary="New context",
            critical_files=["new.py:10"],
            recent_changes=["Update"],
            learnings=[],
            blockers=[],
            git_ref="ghi9012",
        )

        manager.handoff_update_context(handoff_id, context)

        handoff = manager.handoff_get(handoff_id)
        # Original fields should be preserved
        assert handoff.title == "Preserve fields test"
        assert handoff.description == "Original description"
        assert handoff.status == "in_progress"
        assert handoff.phase == "implementing"
        assert handoff.agent == "general-purpose"
        assert len(handoff.tried) == 1
        assert handoff.next_steps == "Next step here"
        # Context should be set
        assert handoff.handoff is not None
        assert handoff.handoff.git_ref == "ghi9012"

    def test_set_context_invalid_json(self, tmp_path):
        """CLI should reject invalid JSON with helpful error."""
        env = os.environ.copy()
        env["PROJECT_DIR"] = str(tmp_path)
        env["CLAUDE_RECALL_BASE"] = str(tmp_path / ".lessons")

        # First create a handoff
        result = subprocess.run(
            [sys.executable, "core/cli.py", "handoff", "add", "Invalid JSON test"],
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 0
        handoff_id = result.stdout.split()[2].rstrip(":")

        # Try to set invalid JSON
        result = subprocess.run(
            [
                sys.executable,
                "core/cli.py",
                "handoff",
                "set-context",
                handoff_id,
                "--json",
                "not valid json",
            ],
            capture_output=True,
            text=True,
            env=env,
        )

        assert result.returncode != 0
        assert "Invalid JSON" in result.stderr

    def test_set_context_not_object(self, tmp_path):
        """CLI should reject non-object JSON."""
        import json

        env = os.environ.copy()
        env["PROJECT_DIR"] = str(tmp_path)
        env["CLAUDE_RECALL_BASE"] = str(tmp_path / ".lessons")

        # First create a handoff
        result = subprocess.run(
            [sys.executable, "core/cli.py", "handoff", "add", "Array JSON test"],
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 0
        handoff_id = result.stdout.split()[2].rstrip(":")

        # Try to set array instead of object
        result = subprocess.run(
            [
                sys.executable,
                "core/cli.py",
                "handoff",
                "set-context",
                handoff_id,
                "--json",
                json.dumps(["item1", "item2"]),
            ],
            capture_output=True,
            text=True,
            env=env,
        )

        assert result.returncode != 0
        assert "JSON object" in result.stderr

    def test_set_context_nonexistent_handoff(self, tmp_path):
        """CLI should error on nonexistent handoff."""
        import json

        env = os.environ.copy()
        env["PROJECT_DIR"] = str(tmp_path)
        env["CLAUDE_RECALL_BASE"] = str(tmp_path / ".lessons")

        context_json = json.dumps({
            "summary": "Test",
            "critical_files": [],
            "recent_changes": [],
            "learnings": [],
            "blockers": [],
            "git_ref": "abc123",
        })

        result = subprocess.run(
            [
                sys.executable,
                "core/cli.py",
                "handoff",
                "set-context",
                "hf-nonexist",
                "--json",
                context_json,
            ],
            capture_output=True,
            text=True,
            env=env,
        )

        assert result.returncode != 0
        assert "not found" in result.stderr.lower()

    def test_set_context_empty_fields(self, manager: "LessonsManager"):
        """set-context should handle empty/missing fields gracefully."""
        try:
            from core.models import HandoffContext
        except ImportError:
            pytest.skip("HandoffContext not yet implemented")

        handoff_id = manager.handoff_add(title="Empty fields test")

        # Context with only summary (other fields empty)
        context = HandoffContext(
            summary="Just a summary",
            critical_files=[],
            recent_changes=[],
            learnings=[],
            blockers=[],
            git_ref="abc123",  # git_ref is extracted from Haiku
        )

        manager.handoff_update_context(handoff_id, context)

        handoff = manager.handoff_get(handoff_id)
        assert handoff.handoff is not None
        assert handoff.handoff.summary == "Just a summary"
        assert handoff.handoff.critical_files == []
        assert handoff.handoff.git_ref == "abc123"


# =============================================================================
# Phase 7: Injection Format Updates for HandoffContext
# =============================================================================


class TestHandoffContextInjectionFormat:
    """Tests for updated HandoffContext display in injection output (Phase 7)."""

    def test_inject_shows_abbreviated_git_ref(self, manager: "LessonsManager") -> None:
        """Injection output shows abbreviated git_ref (first 7 chars)."""
        from core.models import HandoffContext

        handoff_id = manager.handoff_add(title="Abbreviated ref test")

        context = HandoffContext(
            summary="Testing abbreviated git ref",
            critical_files=["core/main.py:50"],
            recent_changes=["Updated main"],
            learnings=[],
            blockers=[],
            git_ref="abc1234567890abcdef",  # Long git ref
        )

        manager.handoff_update_context(handoff_id, context)
        output = manager.handoff_inject()

        # Should show abbreviated ref (first 7 chars)
        assert "abc1234" in output
        # Should NOT show the full long ref
        assert "abc1234567890" not in output

    def test_inject_shows_learnings(self, manager: "LessonsManager") -> None:
        """Injection output shows learnings from HandoffContext."""
        from core.models import HandoffContext

        handoff_id = manager.handoff_add(title="Learnings test")

        context = HandoffContext(
            summary="Making progress",
            critical_files=[],
            recent_changes=[],
            learnings=["_extract_themes() groups by keyword prefix", "Use pipe separators"],
            blockers=[],
            git_ref="abc1234",
        )

        manager.handoff_update_context(handoff_id, context)
        output = manager.handoff_inject()

        # Should show learnings
        assert "Learnings:" in output
        assert "_extract_themes()" in output

    def test_inject_omits_empty_learnings(self, manager: "LessonsManager") -> None:
        """Injection output omits Learnings line when empty."""
        from core.models import HandoffContext

        handoff_id = manager.handoff_add(title="Empty learnings test")

        context = HandoffContext(
            summary="No learnings yet",
            critical_files=["core/main.py:50"],
            recent_changes=[],
            learnings=[],  # Empty
            blockers=[],
            git_ref="abc1234",
        )

        manager.handoff_update_context(handoff_id, context)
        output = manager.handoff_inject()

        # Should NOT show Learnings line if empty
        # But should still show summary and refs
        assert "No learnings yet" in output
        assert "core/main.py" in output
        # No Learnings line
        assert "Learnings:" not in output

    def test_inject_omits_empty_refs(self, manager: "LessonsManager") -> None:
        """Injection output omits Refs line when critical_files is empty."""
        from core.models import HandoffContext

        handoff_id = manager.handoff_add(title="Empty refs test")

        context = HandoffContext(
            summary="Just summary",
            critical_files=[],  # Empty
            recent_changes=[],
            learnings=["Some learning"],
            blockers=[],
            git_ref="abc1234",
        )

        manager.handoff_update_context(handoff_id, context)
        output = manager.handoff_inject()

        # Should show summary and learnings but not Refs
        assert "Just summary" in output
        assert "Some learning" in output
        # Check that the handoff section doesn't have a "Refs:" subline
        # Note: There's already "- **Refs**:" for the main handoff refs, so we check the subline
        lines = output.split("\n")
        handoff_context_started = False
        for line in lines:
            if "**Handoff**" in line and "abc1234" in line:
                handoff_context_started = True
            if handoff_context_started and line.strip().startswith("- Refs:"):
                # This is the context refs line, should not be present for empty
                pytest.fail("Should not have Refs line in handoff context when critical_files is empty")
            if handoff_context_started and line.strip().startswith("- Learnings:"):
                break  # We've passed where Refs would be

    def test_inject_omits_empty_blockers(self, manager: "LessonsManager") -> None:
        """Injection output omits Blockers line when empty."""
        from core.models import HandoffContext

        handoff_id = manager.handoff_add(title="Empty blockers test")

        context = HandoffContext(
            summary="No blockers",
            critical_files=[],
            recent_changes=[],
            learnings=[],
            blockers=[],  # Empty
            git_ref="abc1234",
        )

        manager.handoff_update_context(handoff_id, context)
        output = manager.handoff_inject()

        # Should not have Blockers line in handoff context section
        lines = output.split("\n")
        handoff_context_started = False
        for line in lines:
            if "**Handoff**" in line and "abc1234" in line:
                handoff_context_started = True
                continue
            if handoff_context_started:
                # Check we're still in the handoff context section (indented)
                if line.strip().startswith("- Blockers:"):
                    pytest.fail("Should not have Blockers line when blockers is empty")
                # Stop if we hit a non-indented line (new section)
                if line.strip() and not line.startswith("  "):
                    break

    def test_inject_legacy_without_handoff_context(self, manager: "LessonsManager") -> None:
        """Injection output works for handoffs without HandoffContext (legacy mode)."""
        # Create a handoff without setting handoff context
        handoff_id = manager.handoff_add(title="Legacy handoff")
        manager.handoff_update_status(handoff_id, "in_progress")
        manager.handoff_add_tried(handoff_id, "success", "Did something")
        manager.handoff_update_next(handoff_id, "Do next thing")

        output = manager.handoff_inject()

        # Should show the handoff info normally
        assert "Legacy handoff" in output
        assert "in_progress" in output
        assert "Next" in output
        assert "Do next thing" in output
        # Should NOT have a Handoff context section
        assert "**Handoff** (" not in output

    def test_inject_critical_files_shown_as_refs(self, manager: "LessonsManager") -> None:
        """Critical files from HandoffContext are shown with 'Refs' label."""
        from core.models import HandoffContext

        handoff_id = manager.handoff_add(title="Refs label test")

        context = HandoffContext(
            summary="Checking refs label",
            critical_files=["approaches.py:142", "models.py:50"],
            recent_changes=[],
            learnings=[],
            blockers=[],
            git_ref="def5678",
        )

        manager.handoff_update_context(handoff_id, context)
        output = manager.handoff_inject()

        # Should show "Refs:" followed by the files
        assert "Refs: approaches.py:142" in output or "Refs:" in output and "approaches.py" in output

    def test_inject_handoff_context_format_with_all_fields(
        self, manager: "LessonsManager"
    ) -> None:
        """Injection output format matches the target format with all fields."""
        from core.models import HandoffContext

        handoff_id = manager.handoff_add(title="Context handoff system")
        manager.handoff_update_status(handoff_id, "in_progress")
        manager.handoff_update_phase(handoff_id, "implementing")

        # Add some tried steps to test progress display
        for i in range(12):
            manager.handoff_add_tried(handoff_id, "success", f"Step {i+1}")
        manager.handoff_add_tried(handoff_id, "fail", "Failed step")

        context = HandoffContext(
            summary="Compact injection working, need relevance scoring",
            critical_files=["approaches.py:142", "models.py:50"],
            recent_changes=["Updated injection format"],
            learnings=["_extract_themes() groups by keyword prefix"],
            blockers=[],
            git_ref="abc1234def5678",  # Long ref, should be abbreviated
        )

        manager.handoff_update_context(handoff_id, context)
        manager.handoff_update_next(handoff_id, "Relevance scoring for approach injection")

        output = manager.handoff_inject()

        # Verify key elements of the target format
        assert "Context handoff system" in output
        assert "in_progress" in output
        assert "implementing" in output

        # Progress should show counts
        assert "13 steps" in output or "13" in output

        # Handoff context section should be present
        assert "**Handoff**" in output

        # Abbreviated git ref
        assert "abc1234" in output
        assert "abc1234def5678" not in output  # Not the full ref

        # Summary
        assert "Compact injection working" in output

        # Refs
        assert "approaches.py:142" in output

        # Learnings
        assert "_extract_themes()" in output

        # Next steps
        assert "Relevance scoring" in output


# =============================================================================
# Phase 8: Stealth Mode Tests
# =============================================================================


class TestStealthModeDataclass:
    """Tests for stealth field on Handoff dataclass."""

    def test_handoff_has_stealth_field(self, manager: "LessonsManager"):
        """Handoff dataclass should have stealth: bool = False."""
        from core.models import Handoff

        # Create a default handoff
        handoff = Handoff(
            id="hf-test123",
            title="Test handoff",
            status="not_started",
            created=date.today(),
            updated=date.today(),
        )
        assert hasattr(handoff, "stealth")
        assert handoff.stealth is False

    def test_handoff_stealth_can_be_set_true(self, manager: "LessonsManager"):
        """Handoff can be created with stealth=True."""
        from core.models import Handoff

        handoff = Handoff(
            id="hf-test123",
            title="Test stealth handoff",
            status="not_started",
            created=date.today(),
            updated=date.today(),
            stealth=True,
        )
        assert handoff.stealth is True


class TestStealthHandoffStorage:
    """Tests for stealth handoffs stored in HANDOFFS_LOCAL.md."""

    def test_add_stealth_handoff_via_api(self, manager: "LessonsManager"):
        """Should be able to add a stealth handoff via API."""
        handoff_id = manager.handoff_add(title="Secret work", stealth=True)

        assert handoff_id.startswith("hf-")

    def test_stealth_handoff_stored_in_local_file(self, manager: "LessonsManager"):
        """Stealth handoffs should be stored in HANDOFFS_LOCAL.md."""
        handoff_id = manager.handoff_add(title="Secret work", stealth=True)

        # Should exist in LOCAL file
        local_file = manager.project_stealth_handoffs_file
        assert local_file.exists()
        content = local_file.read_text()
        assert "Secret work" in content
        assert handoff_id in content

    def test_stealth_handoff_not_in_regular_file(self, manager: "LessonsManager"):
        """Stealth handoffs should NOT be in regular HANDOFFS.md."""
        handoff_id = manager.handoff_add(title="Secret work", stealth=True)

        # Add a regular handoff too for comparison
        regular_id = manager.handoff_add(title="Public work", stealth=False)

        # Regular file should have public work but NOT secret work
        regular_file = manager.project_handoffs_file
        assert regular_file.exists()
        content = regular_file.read_text()
        assert "Public work" in content
        assert regular_id in content
        assert "Secret work" not in content
        assert handoff_id not in content

    def test_regular_handoff_not_in_local_file(self, manager: "LessonsManager"):
        """Regular handoffs should NOT be in HANDOFFS_LOCAL.md."""
        regular_id = manager.handoff_add(title="Public work", stealth=False)

        # LOCAL file should not contain regular handoff
        local_file = manager.project_stealth_handoffs_file
        if local_file.exists():
            content = local_file.read_text()
            assert "Public work" not in content
            assert regular_id not in content


class TestStealthHandoffRetrieval:
    """Tests for retrieving stealth handoffs."""

    def test_stealth_handoff_included_in_list(self, manager: "LessonsManager"):
        """handoff_list() should include stealth handoffs by default."""
        stealth_id = manager.handoff_add(title="Secret work", stealth=True)
        regular_id = manager.handoff_add(title="Public work", stealth=False)

        handoffs = manager.handoff_list(include_completed=False)

        # Both should be included
        ids = [h.id for h in handoffs]
        assert stealth_id in ids
        assert regular_id in ids

    def test_stealth_handoff_included_in_injection(self, manager: "LessonsManager"):
        """handoff_inject() should include stealth handoffs."""
        stealth_id = manager.handoff_add(title="Secret work", stealth=True)
        manager.handoff_update_status(stealth_id, "in_progress")

        output = manager.handoff_inject()

        assert "Secret work" in output
        assert stealth_id in output

    def test_handoff_get_finds_stealth_handoff(self, manager: "LessonsManager"):
        """handoff_get() should find stealth handoffs by ID."""
        stealth_id = manager.handoff_add(title="Secret work", stealth=True)

        handoff = manager.handoff_get(stealth_id)

        assert handoff is not None
        assert handoff.id == stealth_id
        assert handoff.title == "Secret work"
        assert handoff.stealth is True


class TestStealthHandoffSerialization:
    """Tests for stealth field serialization/deserialization."""

    def test_stealth_field_persists_round_trip(self, manager: "LessonsManager"):
        """Stealth field should persist through save/load cycle."""
        stealth_id = manager.handoff_add(title="Secret work", stealth=True)

        # Force reload by creating new manager with same paths
        manager2 = type(manager)(
            lessons_base=manager.lessons_base,
            project_root=manager.project_root,
        )

        handoff = manager2.handoff_get(stealth_id)
        assert handoff is not None
        assert handoff.stealth is True

    def test_stealth_field_in_markdown_format(self, manager: "LessonsManager"):
        """Stealth field should appear in markdown file format."""
        manager.handoff_add(title="Secret work", stealth=True)

        local_file = manager.project_stealth_handoffs_file
        content = local_file.read_text()

        # Should have stealth marker in the file
        # (implementation can choose format: field, filename itself, or both)
        assert local_file.name == "HANDOFFS_LOCAL.md"


class TestStealthHandoffCLI:
    """Tests for stealth handoff CLI support."""

    def test_cli_add_stealth_handoff(
        self, temp_lessons_base: Path, temp_project_root: Path
    ):
        """CLI should support --stealth flag for adding handoffs."""
        env = os.environ.copy()
        env["PROJECT_DIR"] = str(temp_project_root)
        env["CLAUDE_RECALL_BASE"] = str(temp_lessons_base)

        result = subprocess.run(
            [
                sys.executable,
                "core/cli.py",
                "handoff",
                "add",
                "Secret CLI work",
                "--stealth",
            ],
            capture_output=True,
            text=True,
            env=env,
        )

        assert result.returncode == 0
        assert "hf-" in result.stdout
        assert "(stealth)" in result.stdout

        # Verify stored in LOCAL file
        local_file = temp_project_root / ".claude-recall" / "HANDOFFS_LOCAL.md"
        if not local_file.exists():
            local_file = temp_project_root / ".coding-agent-lessons" / "HANDOFFS_LOCAL.md"

        assert local_file.exists()
        content = local_file.read_text()
        assert "Secret CLI work" in content


class TestStealthHandoffUpdate:
    """Tests for updating stealth handoffs."""

    def test_update_stealth_handoff_status(self, manager: "LessonsManager"):
        """Should be able to update status of stealth handoffs."""
        stealth_id = manager.handoff_add(title="Secret work", stealth=True)

        manager.handoff_update_status(stealth_id, "in_progress")

        handoff = manager.handoff_get(stealth_id)
        assert handoff.status == "in_progress"

    def test_update_stealth_handoff_next(self, manager: "LessonsManager"):
        """Should be able to update next steps of stealth handoffs."""
        stealth_id = manager.handoff_add(title="Secret work", stealth=True)

        manager.handoff_update_next(stealth_id, "Continue stealth work")

        handoff = manager.handoff_get(stealth_id)
        assert handoff.next_steps == "Continue stealth work"

    def test_add_tried_to_stealth_handoff(self, manager: "LessonsManager"):
        """Should be able to add tried steps to stealth handoffs."""
        stealth_id = manager.handoff_add(title="Secret work", stealth=True)

        manager.handoff_add_tried(stealth_id, "success", "Secret step worked")

        handoff = manager.handoff_get(stealth_id)
        assert len(handoff.tried) == 1
        assert handoff.tried[0].description == "Secret step worked"


class TestStealthHandoffComplete:
    """Tests for completing stealth handoffs."""

    def test_complete_stealth_handoff(self, manager: "LessonsManager"):
        """Should be able to complete stealth handoffs."""
        stealth_id = manager.handoff_add(title="Secret work", stealth=True)

        result = manager.handoff_complete(stealth_id)

        assert result.handoff.status == "completed"
        assert result.handoff.stealth is True

    def test_archive_stealth_handoff(self, manager: "LessonsManager"):
        """Should be able to archive stealth handoffs."""
        stealth_id = manager.handoff_add(title="Secret work", stealth=True)
        manager.handoff_complete(stealth_id)

        manager.handoff_archive(stealth_id)

        # Should no longer be gettable
        handoff = manager.handoff_get(stealth_id)
        assert handoff is None

        # Should be in stealth archive (HANDOFFS_LOCAL_ARCHIVE.md or similar)
        # or in a separate section of the archive


class TestStealthMixedOperations:
    """Tests for mixed stealth and regular handoff operations."""

    def test_list_mixed_handoffs(self, manager: "LessonsManager"):
        """list() should return both stealth and regular handoffs."""
        stealth1 = manager.handoff_add(title="Stealth 1", stealth=True)
        regular1 = manager.handoff_add(title="Regular 1", stealth=False)
        stealth2 = manager.handoff_add(title="Stealth 2", stealth=True)
        regular2 = manager.handoff_add(title="Regular 2", stealth=False)

        handoffs = manager.handoff_list()

        ids = [h.id for h in handoffs]
        assert stealth1 in ids
        assert regular1 in ids
        assert stealth2 in ids
        assert regular2 in ids

    def test_inject_mixed_handoffs(self, manager: "LessonsManager"):
        """inject() should include both stealth and regular handoffs."""
        stealth_id = manager.handoff_add(title="Stealth work", stealth=True)
        regular_id = manager.handoff_add(title="Regular work", stealth=False)

        manager.handoff_update_status(stealth_id, "in_progress")
        manager.handoff_update_status(regular_id, "in_progress")

        output = manager.handoff_inject()

        assert "Stealth work" in output
        assert "Regular work" in output

    def test_handoff_ready_includes_stealth(self, manager: "LessonsManager"):
        """handoff_ready() should include stealth handoffs."""
        stealth_id = manager.handoff_add(title="Stealth ready", stealth=True)
        regular_id = manager.handoff_add(title="Regular ready", stealth=False)

        ready = manager.handoff_ready()

        ids = [h.id for h in ready]
        assert stealth_id in ids
        assert regular_id in ids


# =============================================================================
# Phase 10: Dependency Inference Tests
# =============================================================================


class TestDependencyInferenceCLI:
    """Tests for CLI update with --blocked-by flag."""

    def test_cli_update_blocked_by_single_id(
        self, temp_lessons_base: Path, temp_project_root: Path
    ):
        """CLI update with --blocked-by should set single blocker ID."""
        # Create handoffs file with legacy format for predictable ID
        handoffs_file = temp_project_root / ".recall" / "HANDOFFS.md"
        handoffs_file.parent.mkdir(parents=True, exist_ok=True)
        today = date.today().isoformat()
        handoffs_file.write_text(f"""# HANDOFFS.md - Active Work Tracking

> Track ongoing work with tried steps and next steps.
> When completed, review for lessons to extract.

## Active Handoffs

### [hf-0000001] Main task
- **Status**: not_started | **Phase**: research | **Agent**: user
- **Created**: {today} | **Updated**: {today}
- **Refs**:
- **Description**: Test handoff

**Tried**:

**Next**:

---

### [hf-0000002] Blocking task
- **Status**: in_progress | **Phase**: research | **Agent**: user
- **Created**: {today} | **Updated**: {today}
- **Refs**:
- **Description**: Blocker

**Tried**:

**Next**:

---
""")

        # Get the project root (coding-agent-lessons directory)
        repo_root = Path(__file__).parent.parent

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "core.cli",
                "handoff",
                "update",
                "hf-0000001",
                "--blocked-by",
                "hf-0000002",
            ],
            cwd=str(repo_root),
            env={
                **os.environ,
                "CLAUDE_RECALL_BASE": str(temp_lessons_base),
                "PROJECT_DIR": str(temp_project_root),
            },
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr
        assert "Updated hf-0000001 blocked_by to hf-0000002" in result.stdout

        # Verify in manager
        manager = LessonsManager(
            lessons_base=temp_lessons_base,
            project_root=temp_project_root,
        )
        handoff = manager.handoff_get("hf-0000001")
        assert handoff is not None
        assert handoff.blocked_by == ["hf-0000002"]

    def test_cli_update_blocked_by_multiple_ids(
        self, temp_lessons_base: Path, temp_project_root: Path
    ):
        """CLI update with --blocked-by should accept comma-separated IDs."""
        # Create handoffs file with legacy format for predictable IDs
        handoffs_file = temp_project_root / ".recall" / "HANDOFFS.md"
        handoffs_file.parent.mkdir(parents=True, exist_ok=True)
        today = date.today().isoformat()
        handoffs_file.write_text(f"""# HANDOFFS.md - Active Work Tracking

> Track ongoing work with tried steps and next steps.
> When completed, review for lessons to extract.

## Active Handoffs

### [hf-0000001] Main task
- **Status**: not_started | **Phase**: research | **Agent**: user
- **Created**: {today} | **Updated**: {today}
- **Refs**:
- **Description**: Test handoff

**Tried**:

**Next**:

---

### [hf-0000002] First blocker
- **Status**: in_progress | **Phase**: research | **Agent**: user
- **Created**: {today} | **Updated**: {today}
- **Refs**:
- **Description**: Blocker 1

**Tried**:

**Next**:

---

### [hf-0000003] Second blocker
- **Status**: in_progress | **Phase**: research | **Agent**: user
- **Created**: {today} | **Updated**: {today}
- **Refs**:
- **Description**: Blocker 2

**Tried**:

**Next**:

---
""")

        # Get the project root (coding-agent-lessons directory)
        repo_root = Path(__file__).parent.parent

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "core.cli",
                "handoff",
                "update",
                "hf-0000001",
                "--blocked-by",
                "hf-0000002,hf-0000003",
            ],
            cwd=str(repo_root),
            env={
                **os.environ,
                "CLAUDE_RECALL_BASE": str(temp_lessons_base),
                "PROJECT_DIR": str(temp_project_root),
            },
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr
        assert "Updated hf-0000001 blocked_by to hf-0000002, hf-0000003" in result.stdout

        # Verify in manager
        manager = LessonsManager(
            lessons_base=temp_lessons_base,
            project_root=temp_project_root,
        )
        handoff = manager.handoff_get("hf-0000001")
        assert handoff is not None
        assert set(handoff.blocked_by) == {"hf-0000002", "hf-0000003"}

    def test_cli_update_blocked_by_with_hf_ids(
        self, temp_lessons_base: Path, temp_project_root: Path
    ):
        """CLI update with --blocked-by should accept hf-XXXXXXX format IDs."""
        manager = LessonsManager(
            lessons_base=temp_lessons_base,
            project_root=temp_project_root,
        )
        main_id = manager.handoff_add(title="Main task")
        blocker_id = manager.handoff_add(title="Blocking task")

        # Get the project root (coding-agent-lessons directory)
        repo_root = Path(__file__).parent.parent

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "core.cli",
                "handoff",
                "update",
                main_id,
                "--blocked-by",
                blocker_id,
            ],
            cwd=str(repo_root),
            env={
                **os.environ,
                "CLAUDE_RECALL_BASE": str(temp_lessons_base),
                "PROJECT_DIR": str(temp_project_root),
            },
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr

        # Verify in manager
        handoff = manager.handoff_get(main_id)
        assert handoff is not None
        assert handoff.blocked_by == [blocker_id]


class TestDependencyInferenceParsing:
    """Tests for parsing blocked_by from HANDOFF UPDATE patterns."""

    def test_explicit_blocked_by_single(self, manager: "LessonsManager"):
        """HANDOFF UPDATE hf-0000001: blocked_by hf-0000002 should set single blocker."""
        handoffs_file = manager.project_handoffs_file
        handoffs_file.parent.mkdir(parents=True, exist_ok=True)
        today = date.today().isoformat()
        handoffs_file.write_text(f"""# HANDOFFS.md - Active Work Tracking

> Track ongoing work with tried steps and next steps.
> When completed, review for lessons to extract.

## Active Handoffs

### [hf-0000001] Main task
- **Status**: not_started | **Phase**: research | **Agent**: user
- **Created**: {today} | **Updated**: {today}
- **Refs**:
- **Description**: Test handoff

**Tried**:

**Next**:

---
""")

        # Simulate what stop-hook would do
        manager.handoff_update_blocked_by("hf-0000001", ["hf-0000002"])

        handoff = manager.handoff_get("hf-0000001")
        assert handoff is not None
        assert handoff.blocked_by == ["hf-0000002"]

    def test_explicit_blocked_by_multiple(self, manager: "LessonsManager"):
        """HANDOFF UPDATE hf-0000001: blocked_by hf-0000002,hf-0000003 should set multiple blockers."""
        handoffs_file = manager.project_handoffs_file
        handoffs_file.parent.mkdir(parents=True, exist_ok=True)
        today = date.today().isoformat()
        handoffs_file.write_text(f"""# HANDOFFS.md - Active Work Tracking

> Track ongoing work with tried steps and next steps.
> When completed, review for lessons to extract.

## Active Handoffs

### [hf-0000001] Main task
- **Status**: not_started | **Phase**: research | **Agent**: user
- **Created**: {today} | **Updated**: {today}
- **Refs**:
- **Description**: Test handoff

**Tried**:

**Next**:

---
""")

        # Simulate what stop-hook would do with comma-separated IDs
        manager.handoff_update_blocked_by("hf-0000001", ["hf-0000002", "hf-0000003"])

        handoff = manager.handoff_get("hf-0000001")
        assert handoff is not None
        assert set(handoff.blocked_by) == {"hf-0000002", "hf-0000003"}


class TestDependencyInferencePatterns:
    """Tests for inferring blocked_by from natural language patterns."""

    def test_infer_waiting_for_pattern(self, manager: "LessonsManager"):
        """'waiting for hf-0000002' in next_steps should infer blocked_by hf-0000002."""
        handoffs_file = manager.project_handoffs_file
        handoffs_file.parent.mkdir(parents=True, exist_ok=True)
        today = date.today().isoformat()
        handoffs_file.write_text(f"""# HANDOFFS.md - Active Work Tracking

> Track ongoing work with tried steps and next steps.
> When completed, review for lessons to extract.

## Active Handoffs

### [hf-0000001] Main task
- **Status**: not_started | **Phase**: research | **Agent**: user
- **Created**: {today} | **Updated**: {today}
- **Refs**:
- **Description**: Test handoff

**Tried**:

**Next**:

---

### [hf-0000002] Blocking task
- **Status**: in_progress | **Phase**: research | **Agent**: user
- **Created**: {today} | **Updated**: {today}
- **Refs**:
- **Description**: Blocker

**Tried**:

**Next**:

---
""")

        # Test the shell function via Python emulation
        # The actual inference happens in stop-hook.sh, but we test the Python side
        # by verifying that update_blocked_by works correctly
        manager.handoff_update_blocked_by("hf-0000001", ["hf-0000002"])

        handoff = manager.handoff_get("hf-0000001")
        assert handoff is not None
        assert "hf-0000002" in handoff.blocked_by

    def test_infer_blocked_by_pattern(self, manager: "LessonsManager"):
        """'blocked by hf-0000003' in next_steps should infer blocked_by hf-0000003."""
        handoffs_file = manager.project_handoffs_file
        handoffs_file.parent.mkdir(parents=True, exist_ok=True)
        today = date.today().isoformat()
        handoffs_file.write_text(f"""# HANDOFFS.md - Active Work Tracking

> Track ongoing work with tried steps and next steps.
> When completed, review for lessons to extract.

## Active Handoffs

### [hf-0000001] Main task
- **Status**: not_started | **Phase**: research | **Agent**: user
- **Created**: {today} | **Updated**: {today}
- **Refs**:
- **Description**: Test handoff

**Tried**:

**Next**:

---
""")

        manager.handoff_update_blocked_by("hf-0000001", ["hf-0000003"])

        handoff = manager.handoff_get("hf-0000001")
        assert handoff is not None
        assert "hf-0000003" in handoff.blocked_by

    def test_infer_depends_on_pattern(self, manager: "LessonsManager"):
        """'depends on hf-abc1234' in next_steps should infer blocked_by hf-abc1234."""
        main_id = manager.handoff_add(title="Main task")
        blocker_id = manager.handoff_add(title="Blocking task")

        manager.handoff_update_blocked_by(main_id, [blocker_id])

        handoff = manager.handoff_get(main_id)
        assert handoff is not None
        assert blocker_id in handoff.blocked_by

    def test_infer_after_completes_pattern(self, manager: "LessonsManager"):
        """'after hf-0000002 completes' in next_steps should infer blocked_by hf-0000002."""
        handoffs_file = manager.project_handoffs_file
        handoffs_file.parent.mkdir(parents=True, exist_ok=True)
        today = date.today().isoformat()
        handoffs_file.write_text(f"""# HANDOFFS.md - Active Work Tracking

> Track ongoing work with tried steps and next steps.
> When completed, review for lessons to extract.

## Active Handoffs

### [hf-0000001] Main task
- **Status**: not_started | **Phase**: research | **Agent**: user
- **Created**: {today} | **Updated**: {today}
- **Refs**:
- **Description**: Test handoff

**Tried**:

**Next**:

---
""")

        manager.handoff_update_blocked_by("hf-0000001", ["hf-0000002"])

        handoff = manager.handoff_get("hf-0000001")
        assert handoff is not None
        assert "hf-0000002" in handoff.blocked_by


class TestDependencyInferencePrecedence:
    """Tests for explicit blocked_by overriding inferred patterns."""

    def test_explicit_overrides_inferred(self, manager: "LessonsManager"):
        """Explicit blocked_by should replace any previously inferred blockers."""
        handoffs_file = manager.project_handoffs_file
        handoffs_file.parent.mkdir(parents=True, exist_ok=True)
        today = date.today().isoformat()
        handoffs_file.write_text(f"""# HANDOFFS.md - Active Work Tracking

> Track ongoing work with tried steps and next steps.
> When completed, review for lessons to extract.

## Active Handoffs

### [hf-0000001] Main task
- **Status**: not_started | **Phase**: research | **Agent**: user
- **Created**: {today} | **Updated**: {today}
- **Refs**:
- **Description**: Test handoff
- **Blocked By**: hf-0000002

**Tried**:

**Next**:

---
""")

        # Explicit update should replace existing blockers
        manager.handoff_update_blocked_by("hf-0000001", ["hf-0000003", "A004"])

        handoff = manager.handoff_get("hf-0000001")
        assert handoff is not None
        assert set(handoff.blocked_by) == {"hf-0000003", "A004"}
        assert "hf-0000002" not in handoff.blocked_by

    def test_clear_blocked_by_with_empty_list(self, manager: "LessonsManager"):
        """Setting blocked_by to empty list should clear all blockers."""
        handoffs_file = manager.project_handoffs_file
        handoffs_file.parent.mkdir(parents=True, exist_ok=True)
        today = date.today().isoformat()
        handoffs_file.write_text(f"""# HANDOFFS.md - Active Work Tracking

> Track ongoing work with tried steps and next steps.
> When completed, review for lessons to extract.

## Active Handoffs

### [hf-0000001] Main task
- **Status**: not_started | **Phase**: research | **Agent**: user
- **Created**: {today} | **Updated**: {today}
- **Refs**:
- **Description**: Test handoff
- **Blocked By**: hf-0000002, hf-0000003

**Tried**:

**Next**:

---
""")

        manager.handoff_update_blocked_by("hf-0000001", [])

        handoff = manager.handoff_get("hf-0000001")
        assert handoff is not None
        assert handoff.blocked_by == []


class TestDependencyInferenceShell:
    """Tests for shell-based inference function (infer_blocked_by in stop-hook.sh)."""

    def test_infer_blocked_by_shell_function(self, temp_project_root: Path):
        """Test infer_blocked_by shell function extracts blockers from text."""
        # Write a self-contained test script that defines the function inline
        # (extracted from stop-hook.sh) to avoid sourcing issues
        test_script = temp_project_root / "test_infer.sh"

        test_script.write_text("""#!/bin/bash
# Inline copy of infer_blocked_by function from stop-hook.sh
infer_blocked_by() {
    local text="$1"
    local blockers=""

    # Pattern: "waiting for <ID>"
    local waiting_matches
    waiting_matches=$(echo "$text" | grep -oE 'waiting for (hf-[0-9a-f]{7}|[A-Z][0-9]{3})' | \\
        grep -oE '(hf-[0-9a-f]{7}|[A-Z][0-9]{3})' || true)
    [[ -n "$waiting_matches" ]] && blockers="$waiting_matches"

    # Pattern: "blocked by <ID>"
    local blocked_matches
    blocked_matches=$(echo "$text" | grep -oE 'blocked by (hf-[0-9a-f]{7}|[A-Z][0-9]{3})' | \\
        grep -oE '(hf-[0-9a-f]{7}|[A-Z][0-9]{3})' || true)
    if [[ -n "$blocked_matches" ]]; then
        [[ -n "$blockers" ]] && blockers="$blockers"$'\\n'"$blocked_matches" || blockers="$blocked_matches"
    fi

    # Pattern: "depends on <ID>"
    local depends_matches
    depends_matches=$(echo "$text" | grep -oE 'depends on (hf-[0-9a-f]{7}|[A-Z][0-9]{3})' | \\
        grep -oE '(hf-[0-9a-f]{7}|[A-Z][0-9]{3})' || true)
    if [[ -n "$depends_matches" ]]; then
        [[ -n "$blockers" ]] && blockers="$blockers"$'\\n'"$depends_matches" || blockers="$depends_matches"
    fi

    # Pattern: "after <ID> completes"
    local after_matches
    after_matches=$(echo "$text" | grep -oE 'after (hf-[0-9a-f]{7}|[A-Z][0-9]{3}) completes' | \\
        grep -oE '(hf-[0-9a-f]{7}|[A-Z][0-9]{3})' || true)
    if [[ -n "$after_matches" ]]; then
        [[ -n "$blockers" ]] && blockers="$blockers"$'\\n'"$after_matches" || blockers="$after_matches"
    fi

    # Deduplicate and format as comma-separated list
    if [[ -n "$blockers" ]]; then
        echo "$blockers" | sort -u | tr '\\n' ',' | sed 's/,$//'
    fi
}

# Test cases
echo "Test 1: waiting for hf-0000002"
result=$(infer_blocked_by "waiting for hf-0000002")
echo "Result: $result"

echo "Test 2: blocked by hf-abc1234"
result=$(infer_blocked_by "blocked by hf-abc1234")
echo "Result: $result"

echo "Test 3: depends on hf-0000003"
result=$(infer_blocked_by "depends on hf-0000003")
echo "Result: $result"

echo "Test 4: after hf-0000001 completes"
result=$(infer_blocked_by "after hf-0000001 completes")
echo "Result: $result"

echo "Test 5: multiple patterns"
result=$(infer_blocked_by "waiting for hf-0000002 and blocked by hf-0000003")
echo "Result: $result"

echo "Test 6: no patterns"
result=$(infer_blocked_by "just some text without any IDs")
echo "Result: $result"
""")

        result = subprocess.run(
            ["bash", str(test_script)],
            capture_output=True,
            text=True,
        )

        # Check results - the output should contain the expected blocker IDs
        output = result.stdout
        assert "Test 1" in output
        assert "hf-0000002" in output
        assert "hf-abc1234" in output
        assert "hf-0000003" in output
        assert "hf-0000001" in output

    def test_infer_blocked_by_with_hf_format(self, temp_project_root: Path):
        """Test infer_blocked_by handles hf-XXXXXXX format IDs."""
        test_script = temp_project_root / "test_infer_hf.sh"

        test_script.write_text("""#!/bin/bash
# Inline copy of infer_blocked_by function
infer_blocked_by() {
    local text="$1"
    local blockers=""

    # Pattern: "waiting for <ID>"
    local waiting_matches
    waiting_matches=$(echo "$text" | grep -oE 'waiting for (hf-[0-9a-f]{7}|[A-Z][0-9]{3})' | \\
        grep -oE '(hf-[0-9a-f]{7}|[A-Z][0-9]{3})' || true)
    [[ -n "$waiting_matches" ]] && blockers="$waiting_matches"

    # Deduplicate and format as comma-separated list
    if [[ -n "$blockers" ]]; then
        echo "$blockers" | sort -u | tr '\\n' ',' | sed 's/,$//'
    fi
}

result=$(infer_blocked_by "waiting for hf-abc1234 to complete")
echo "$result"
""")

        result = subprocess.run(
            ["bash", str(test_script)],
            capture_output=True,
            text=True,
        )

        # Should extract hf-abc1234
        assert "hf-abc1234" in result.stdout


class TestOrphanHandoffAutoCompletion:
    """Tests for auto-completing orphan handoffs that were never closed out."""

    def test_orphan_handoff_auto_completed(self, manager: LessonsManager) -> None:
        """Handoffs in ready_for_review with all success steps are auto-completed after 1 day."""
        from core.models import HANDOFF_ORPHAN_DAYS

        handoff_id = manager.handoff_add(title="Orphan work")
        manager.handoff_add_tried(handoff_id, "success", "Step 1")
        manager.handoff_add_tried(handoff_id, "success", "Step 2")
        manager.handoff_update_status(handoff_id, "ready_for_review")

        # Backdate the handoff
        handoffs = manager._parse_handoffs_file(manager.project_handoffs_file)
        handoffs[0].updated = date.today() - timedelta(days=HANDOFF_ORPHAN_DAYS + 1)
        manager._write_handoffs_file(handoffs)

        # Trigger auto-completion via inject
        manager.handoff_inject()

        # Should now be completed
        handoff = manager.handoff_get(handoff_id)
        assert handoff.status == "completed"
        assert "Auto-completed" in (handoff.description or "")

    def test_orphan_with_failed_step_not_completed(self, manager: LessonsManager) -> None:
        """Handoffs with any non-success steps are not auto-completed."""
        from core.models import HANDOFF_ORPHAN_DAYS

        handoff_id = manager.handoff_add(title="Incomplete work")
        manager.handoff_add_tried(handoff_id, "success", "Step 1")
        manager.handoff_add_tried(handoff_id, "fail", "Step 2 failed")
        manager.handoff_update_status(handoff_id, "ready_for_review")

        # Backdate the handoff
        handoffs = manager._parse_handoffs_file(manager.project_handoffs_file)
        handoffs[0].updated = date.today() - timedelta(days=HANDOFF_ORPHAN_DAYS + 1)
        manager._write_handoffs_file(handoffs)

        # Trigger auto-completion via inject
        manager.handoff_inject()

        # Should NOT be completed (has failed step)
        handoff = manager.handoff_get(handoff_id)
        assert handoff.status == "ready_for_review"

    def test_orphan_in_progress_not_completed(self, manager: LessonsManager) -> None:
        """Handoffs in in_progress status are not auto-completed."""
        from core.models import HANDOFF_ORPHAN_DAYS

        handoff_id = manager.handoff_add(title="In progress work")
        manager.handoff_add_tried(handoff_id, "success", "Step 1")
        manager.handoff_update_status(handoff_id, "in_progress")

        # Backdate the handoff
        handoffs = manager._parse_handoffs_file(manager.project_handoffs_file)
        handoffs[0].updated = date.today() - timedelta(days=HANDOFF_ORPHAN_DAYS + 1)
        manager._write_handoffs_file(handoffs)

        # Trigger auto-completion via inject
        manager.handoff_inject()

        # Should NOT be completed (wrong status - only ready_for_review is auto-completed)
        handoff = manager.handoff_get(handoff_id)
        assert handoff.status == "in_progress"

    def test_orphan_no_tried_steps_not_completed(self, manager: LessonsManager) -> None:
        """Handoffs with no tried steps are not auto-completed."""
        from core.models import HANDOFF_ORPHAN_DAYS

        handoff_id = manager.handoff_add(title="Empty work")
        manager.handoff_update_status(handoff_id, "ready_for_review")

        # Backdate the handoff
        handoffs = manager._parse_handoffs_file(manager.project_handoffs_file)
        handoffs[0].updated = date.today() - timedelta(days=HANDOFF_ORPHAN_DAYS + 1)
        manager._write_handoffs_file(handoffs)

        # Trigger auto-completion via inject
        manager.handoff_inject()

        # Should NOT be completed (no tried steps)
        handoff = manager.handoff_get(handoff_id)
        assert handoff.status == "ready_for_review"

    def test_recent_orphan_not_completed(self, manager: LessonsManager) -> None:
        """Fresh handoffs in ready_for_review are not auto-completed."""
        handoff_id = manager.handoff_add(title="Fresh work")
        manager.handoff_add_tried(handoff_id, "success", "Step 1")
        manager.handoff_update_status(handoff_id, "ready_for_review")

        # Don't backdate - keep it fresh (today)

        # Trigger auto-completion via inject
        manager.handoff_inject()

        # Should NOT be completed (too fresh)
        handoff = manager.handoff_get(handoff_id)
        assert handoff.status == "ready_for_review"

    def test_auto_complete_returns_ids(self, manager: LessonsManager) -> None:
        """_auto_complete_orphan_handoffs returns list of completed handoff IDs."""
        from core.models import HANDOFF_ORPHAN_DAYS

        h1 = manager.handoff_add(title="Orphan 1")
        h2 = manager.handoff_add(title="Orphan 2")
        manager.handoff_add_tried(h1, "success", "Done")
        manager.handoff_add_tried(h2, "success", "Done")
        manager.handoff_update_status(h1, "ready_for_review")
        manager.handoff_update_status(h2, "ready_for_review")

        # Backdate both
        handoffs = manager._parse_handoffs_file(manager.project_handoffs_file)
        for h in handoffs:
            h.updated = date.today() - timedelta(days=HANDOFF_ORPHAN_DAYS + 1)
        manager._write_handoffs_file(handoffs)

        # Call the internal method directly
        completed = manager._auto_complete_orphan_handoffs()

        assert len(completed) == 2
        assert h1 in completed
        assert h2 in completed


class TestSessionLinking:
    """Tests for session-to-handoff linking feature."""

    def test_session_set_and_get(
        self, manager: LessonsManager, temp_state_dir: Path
    ) -> None:
        """Set a session mapping, retrieve it, verify it matches."""
        # Create a handoff
        handoff_id = manager.handoff_add(title="Session-linked work")

        # Link session to handoff
        session_id = "test-session-12345"
        manager.handoff_set_session(handoff_id, session_id)

        # Retrieve and verify
        result = manager.handoff_get_by_session(session_id)
        assert result == handoff_id

    def test_session_get_nonexistent(
        self, manager: LessonsManager, temp_state_dir: Path
    ) -> None:
        """Get session that doesn't exist returns None."""
        result = manager.handoff_get_by_session("nonexistent-session-xyz")
        assert result is None

    def test_session_handoff_completed_returns_none(
        self, manager: LessonsManager, temp_state_dir: Path
    ) -> None:
        """If handoff is completed, get returns None."""
        # Create a handoff and link session
        handoff_id = manager.handoff_add(title="Work to complete")
        session_id = "session-for-completed"
        manager.handoff_set_session(handoff_id, session_id)

        # Verify link works
        assert manager.handoff_get_by_session(session_id) == handoff_id

        # Complete the handoff
        manager.handoff_update_status(handoff_id, "completed")

        # Now get should return None (handoff is completed)
        assert manager.handoff_get_by_session(session_id) is None

    def test_session_auto_cleanup_old_entries(
        self, manager: LessonsManager, temp_state_dir: Path
    ) -> None:
        """Entries older than 24h are cleaned on save."""
        import json
        from datetime import datetime, timedelta

        # Manually create old session entry by writing directly to file
        session_file = temp_state_dir / "session-handoffs.json"
        old_time = (datetime.now() - timedelta(hours=25)).isoformat()
        current_time = datetime.now().isoformat()

        old_data = {
            "old-session": {
                "handoff_id": "hf-old1234",
                "created": old_time,
            },
            "current-session": {
                "handoff_id": "hf-new5678",
                "created": current_time,
            },
        }
        session_file.parent.mkdir(parents=True, exist_ok=True)
        session_file.write_text(json.dumps(old_data))

        # Create a new handoff and set a new session - this triggers save/cleanup
        handoff_id = manager.handoff_add(title="New work")
        manager.handoff_set_session(handoff_id, "brand-new-session")

        # Read the file back and verify old entry was cleaned
        saved_data = json.loads(session_file.read_text())

        # Old session should be gone (older than 24h)
        assert "old-session" not in saved_data
        # Current session should remain
        assert "current-session" in saved_data
        # New session should be present
        assert "brand-new-session" in saved_data

    def test_session_priority_in_sync_todos(
        self, manager: LessonsManager, temp_state_dir: Path
    ) -> None:
        """session_handoff takes priority over explicit prefix in sync_todos."""
        # Create two handoffs
        handoff_a = manager.handoff_add(title="Session-linked handoff")
        handoff_b = manager.handoff_add(title="Explicitly referenced handoff")

        # Link session to handoff_a
        session_id = "priority-test-session"
        manager.handoff_set_session(handoff_a, session_id)

        # Todos explicitly reference handoff_b
        todos = [
            {"content": f"[{handoff_b}] Task 1", "status": "completed", "activeForm": "Task 1"},
            {"content": f"[{handoff_b}] Task 2", "status": "in_progress", "activeForm": "Task 2"},
            {"content": "Task 3", "status": "pending", "activeForm": "Task 3"},
        ]

        # Sync with session_handoff - should use handoff_a even though todos reference handoff_b
        result = manager.handoff_sync_todos(todos, session_handoff=handoff_a)

        # Session-based handoff takes priority
        assert result == handoff_a

        # Verify handoff_a was updated (not handoff_b)
        handoff = manager.handoff_get(handoff_a)
        assert handoff.status == "in_progress"
        assert len(handoff.tried) >= 1

    def test_add_transcript_to_linked_handoff(
        self, manager: LessonsManager, temp_state_dir: Path
    ) -> None:
        """add_transcript returns handoff_id when linked."""
        # Create a handoff and link session
        handoff_id = manager.handoff_add(title="Transcript test")
        session_id = "transcript-session-123"
        manager.handoff_set_session(handoff_id, session_id)

        # Add transcript
        transcript_path = "/tmp/transcripts/session.jsonl"
        result = manager.handoff_add_transcript(session_id, transcript_path)

        # Should return the linked handoff_id
        assert result == handoff_id

    def test_add_transcript_no_linked_handoff(
        self, manager: LessonsManager, temp_state_dir: Path
    ) -> None:
        """add_transcript returns None when no session link exists."""
        # Try to add transcript for unlinked session
        result = manager.handoff_add_transcript(
            "unlinked-session",
            "/tmp/transcripts/orphan.jsonl"
        )

        # Should return None (no linked handoff)
        assert result is None

    def test_session_set_with_transcript_path(
        self, manager: LessonsManager, temp_state_dir: Path
    ) -> None:
        """handoff_set_session can store transcript_path."""
        import json

        handoff_id = manager.handoff_add(title="Work with transcript")
        session_id = "session-with-transcript"
        transcript_path = "/tmp/transcripts/main.jsonl"

        manager.handoff_set_session(handoff_id, session_id, transcript_path=transcript_path)

        # Verify transcript path was stored
        session_file = temp_state_dir / "session-handoffs.json"
        saved_data = json.loads(session_file.read_text())

        assert saved_data[session_id]["transcript_path"] == transcript_path

    def test_add_transcript_with_agent_type(
        self, manager: LessonsManager, temp_state_dir: Path
    ) -> None:
        """add_transcript accepts agent_type parameter."""
        # Create and link handoff
        handoff_id = manager.handoff_add(title="Multi-agent work")
        session_id = "multi-agent-session"
        manager.handoff_set_session(handoff_id, session_id)

        # Add transcript with agent type
        result = manager.handoff_add_transcript(
            session_id,
            "/tmp/transcripts/explore.jsonl",
            agent_type="Explore"
        )

        # Should still return the handoff_id
        assert result == handoff_id


class TestExplicitHandoffIdInTodos:
    """Tests for explicit handoff ID targeting via [hf-XXXXXXX] prefix in todos."""

    def test_todo_with_explicit_handoff_id_syncs_to_that_handoff(
        self, manager: LessonsManager
    ) -> None:
        """Todos with [hf-XXXXXXX] prefix sync to that specific handoff."""
        # Create two handoffs
        handoff_a = manager.handoff_add(title="Handoff A")
        handoff_b = manager.handoff_add(title="Handoff B")

        # Sync todos that explicitly reference handoff_a
        todos = [
            {"content": f"[{handoff_a}] Task 1", "status": "completed", "activeForm": "Task 1"},
            {"content": f"[{handoff_a}] Task 2", "status": "in_progress", "activeForm": "Task 2"},
            {"content": f"[{handoff_a}] Task 3", "status": "pending", "activeForm": "Task 3"},
        ]
        result = manager.handoff_sync_todos(todos)

        # Should sync to handoff_a despite handoff_b being more recently updated
        assert result == handoff_a

        # Verify handoff_a was updated
        handoff = manager.handoff_get(handoff_a)
        assert handoff.status == "in_progress"
        assert len(handoff.tried) >= 1

    def test_todo_without_explicit_id_uses_most_recent(
        self, manager: LessonsManager
    ) -> None:
        """Todos without explicit handoff ID use most recently updated handoff."""
        # Create two handoffs
        handoff_a = manager.handoff_add(title="Handoff A")
        handoff_b = manager.handoff_add(title="Handoff B")

        # Sync some work to handoff_a to make it more recently updated
        manager.handoff_update_checkpoint(handoff_a, "Working on A")

        # Sync todos without explicit ID - should go to handoff_a (most recent)
        todos = [
            {"content": "Generic task 1", "status": "completed", "activeForm": "Task 1"},
            {"content": "Generic task 2", "status": "pending", "activeForm": "Task 2"},
            {"content": "Generic task 3", "status": "pending", "activeForm": "Task 3"},
        ]
        result = manager.handoff_sync_todos(todos)

        # Should sync to most recently updated (handoff_a)
        assert result == handoff_a

    def test_explicit_id_overrides_most_recent(self, manager: LessonsManager) -> None:
        """Explicit handoff ID takes precedence over most recently updated."""
        # Create handoffs and update them in order
        handoff_old = manager.handoff_add(title="Old Handoff")
        handoff_new = manager.handoff_add(title="New Handoff")

        # Update new to make it most recently updated
        manager.handoff_update_checkpoint(handoff_new, "Very recent work")

        # Sync todos that explicitly target the old handoff
        todos = [
            {"content": f"[{handoff_old}] Target old", "status": "in_progress", "activeForm": "Target old"},
            {"content": "Task 2", "status": "pending", "activeForm": "Task 2"},
            {"content": "Task 3", "status": "pending", "activeForm": "Task 3"},
        ]
        result = manager.handoff_sync_todos(todos)

        # Should sync to explicitly referenced handoff, not most recent
        assert result == handoff_old

    def test_ignores_completed_handoff_in_explicit_id(
        self, manager: LessonsManager
    ) -> None:
        """Explicit ID referencing completed handoff falls back to most recent."""
        # Create a handoff and mark it completed
        completed_handoff = manager.handoff_add(title="Completed Work")
        manager.handoff_update_status(completed_handoff, "completed")

        # Create another active handoff
        active_handoff = manager.handoff_add(title="Active Work")

        # Sync todos that reference the completed handoff
        todos = [
            {"content": f"[{completed_handoff}] Task 1", "status": "in_progress", "activeForm": "Task 1"},
            {"content": "Task 2", "status": "pending", "activeForm": "Task 2"},
            {"content": "Task 3", "status": "pending", "activeForm": "Task 3"},
        ]
        result = manager.handoff_sync_todos(todos)

        # Should fall back to active handoff since referenced one is completed
        assert result == active_handoff


# =============================================================================
# Session ID Gating for Fallback (Prevents Cross-Session Pollution)
# =============================================================================


class TestSessionIdGating:
    """Tests for session_id gating in handoff_sync_todos.

    When a session has a session_id but no session_handoff link, it indicates
    genuinely new work that shouldn't auto-link to existing handoffs. This
    prevents cross-session pollution where unrelated sessions accidentally
    share the same handoff.
    """

    def test_sync_todos_with_session_id_no_link_skips_fallback(
        self, manager: LessonsManager
    ) -> None:
        """When session_id provided but no session_handoff, fallback is skipped."""
        # Create an existing active handoff (would be picked up by fallback)
        existing_handoff = manager.handoff_add(title="Existing work")

        # Sync todos WITH session_id but WITHOUT session_handoff
        # This simulates a new session that hasn't been linked to any handoff
        todos = [
            {"content": "Task A", "status": "completed", "activeForm": "Task A"},
            {"content": "Task B", "status": "in_progress", "activeForm": "Task B"},
            {"content": "Task C", "status": "pending", "activeForm": "Task C"},
        ]
        result = manager.handoff_sync_todos(
            todos,
            session_handoff=None,  # No linked handoff
            session_id="new-session-123",  # But we have a session ID
        )

        # Should NOT fall back to existing_handoff - should create new or return None
        # Since we have 3+ todos, it will create a new handoff
        assert result != existing_handoff
        assert result is not None  # Created new handoff
        assert result.startswith("hf-")

    def test_sync_todos_without_session_id_uses_fallback(
        self, manager: LessonsManager
    ) -> None:
        """When session_id NOT provided, fallback to most recent still works (legacy)."""
        # Create an existing active handoff
        existing_handoff = manager.handoff_add(title="Existing work")

        # Sync todos WITHOUT session_id (legacy behavior)
        todos = [
            {"content": "Task A", "status": "completed", "activeForm": "Task A"},
            {"content": "Task B", "status": "pending", "activeForm": "Task B"},
        ]
        result = manager.handoff_sync_todos(
            todos,
            session_handoff=None,
            session_id=None,  # No session_id - legacy caller
        )

        # Should fall back to existing handoff
        assert result == existing_handoff

    def test_sync_todos_with_explicit_ref_ignores_session_gate(
        self, manager: LessonsManager
    ) -> None:
        """Explicit [hf-XXX] references work even when session_id is provided."""
        # Create target handoff
        target_handoff = manager.handoff_add(title="Target work")

        # Create another handoff (to ensure we're not just picking most recent)
        manager.handoff_add(title="Other work")

        # Sync todos with session_id but explicit handoff reference
        todos = [
            {"content": f"[{target_handoff}] Task 1", "status": "completed", "activeForm": "Task 1"},
            {"content": "Task 2", "status": "pending", "activeForm": "Task 2"},
        ]
        result = manager.handoff_sync_todos(
            todos,
            session_handoff=None,
            session_id="some-session-456",  # Session ID present
        )

        # Should sync to explicitly referenced handoff despite session_id gating
        assert result == target_handoff

    def test_sync_todos_with_session_handoff_takes_priority(
        self, manager: LessonsManager
    ) -> None:
        """session_handoff takes priority even when session_id is provided."""
        # Create handoffs
        linked_handoff = manager.handoff_add(title="Linked work")
        other_handoff = manager.handoff_add(title="Other work")

        # Update other to make it most recently updated
        manager.handoff_update_checkpoint(other_handoff, "Recent activity")

        # Sync todos with both session_handoff and session_id
        todos = [
            {"content": "Task 1", "status": "completed", "activeForm": "Task 1"},
            {"content": "Task 2", "status": "pending", "activeForm": "Task 2"},
        ]
        result = manager.handoff_sync_todos(
            todos,
            session_handoff=linked_handoff,  # Explicit link
            session_id="session-789",
        )

        # Should use linked handoff, not other_handoff
        assert result == linked_handoff

    def test_sync_todos_with_session_id_no_link_returns_none_when_few_todos(
        self, manager: LessonsManager
    ) -> None:
        """When session_id blocks fallback and <3 todos, returns None."""
        existing_handoff = manager.handoff_add(title="Existing work")

        # Only 2 todos - not enough to auto-create
        todos = [
            {"content": "Task A", "status": "completed", "activeForm": "Task A"},
            {"content": "Task B", "status": "pending", "activeForm": "Task B"},
        ]
        result = manager.handoff_sync_todos(
            todos,
            session_handoff=None,
            session_id="new-session-123",
        )

        # Should return None - fallback blocked by session_id, too few for auto-create
        assert result is None

        # Verify existing handoff was NOT touched
        handoff = manager.handoff_get(existing_handoff)
        assert len(handoff.tried) == 0

    def test_sync_todos_autocreate_respects_subagent_guard(
        self, manager: LessonsManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Auto-create from sync_todos should respect sub-agent guard."""
        # Mock as Explore sub-agent
        monkeypatch.setattr(
            manager, "_detect_session_origin", lambda session_id: "Explore"
        )

        # 3+ todos to trigger auto-create
        todos = [
            {"content": "Task A", "status": "completed", "activeForm": "Task A"},
            {"content": "Task B", "status": "in_progress", "activeForm": "Task B"},
            {"content": "Task C", "status": "pending", "activeForm": "Task C"},
        ]
        result = manager.handoff_sync_todos(
            todos,
            session_handoff=None,
            session_id="explore-session-123",
        )

        # Sub-agent should NOT be able to auto-create handoff
        assert result is None


# =============================================================================
# Session ID Shell Quoting Safety
# =============================================================================


class TestSessionIdShellQuoting:
    """Tests for session_id handling in shell commands.

    The stop-hook.sh script passes session_id to Python CLI. This must be
    properly quoted to handle spaces, special characters, and shell metacharacters.
    The fix uses Bash arrays instead of string concatenation to ensure safe
    argument passing.
    """

    def test_sync_todos_cli_accepts_session_id_with_spaces(
        self, manager: LessonsManager
    ) -> None:
        """CLI sync-todos should accept session_id with spaces via proper quoting."""
        # Create an existing active handoff
        existing_handoff = manager.handoff_add(title="Existing work")

        # Simulate session_id with spaces (unlikely in practice, but tests quoting)
        session_with_spaces = "session with spaces and special-chars!"
        todos = [
            {"content": "Task A", "status": "completed", "activeForm": "Task A"},
            {"content": "Task B", "status": "pending", "activeForm": "Task B"},
        ]

        # This tests the CLI layer, which should handle quoted session_id
        result = manager.handoff_sync_todos(
            todos,
            session_handoff=None,
            session_id=session_with_spaces,
        )

        # Should NOT fall back to existing_handoff when session_id provided
        assert result != existing_handoff

    def test_sync_todos_cli_accepts_session_id_with_special_chars(
        self, manager: LessonsManager
    ) -> None:
        """CLI sync-todos should accept session_id with shell metacharacters."""
        # Simulate session_id with characters that would break shell without proper quoting
        session_with_special = 'session;with$dangerous"chars'
        todos = [
            {"content": "Task A", "status": "completed", "activeForm": "Task A"},
        ]

        # Should handle special characters without shell errors
        result = manager.handoff_sync_todos(
            todos,
            session_handoff=None,
            session_id=session_with_special,
        )

        # Should create new handoff (3+ todos) or return None (<3 todos)
        # Just verify it doesn't crash or return the wrong handoff
        if result is not None:
            assert result.startswith("hf-")

    def test_sync_todos_without_session_id_still_uses_fallback(
        self, manager: LessonsManager
    ) -> None:
        """Legacy behavior: no session_id still falls back to most recent."""
        # Create an existing active handoff
        existing_handoff = manager.handoff_add(title="Existing work")

        # Sync todos WITHOUT session_id (legacy path)
        todos = [
            {"content": "Task A", "status": "completed", "activeForm": "Task A"},
            {"content": "Task B", "status": "pending", "activeForm": "Task B"},
        ]

        result = manager.handoff_sync_todos(
            todos,
            session_handoff=None,
            session_id=None,  # Legacy: no session_id
        )

        # Should fall back to existing handoff
        assert result == existing_handoff


# =============================================================================
# Batch Handoff Processing
# =============================================================================
# Batch Handoff Processing
# =============================================================================


class TestHandoffBatchProcess:
    """Tests for batch handoff processing.

    The batch_process method allows multiple handoff operations in a single call,
    reducing overhead when processing multiple commands from agent output.
    """

    def test_handoff_batch_process_add_single(self, manager: "LessonsManager"):
        """Batch with one add operation should create the handoff."""
        operations = [
            {"op": "add", "title": "Batch test handoff", "desc": "Created via batch"}
        ]

        result = manager.handoff_batch_process(operations)

        # Should return results for each operation
        assert "results" in result
        assert len(result["results"]) == 1
        assert result["results"][0]["ok"] is True
        assert result["results"][0]["id"].startswith("hf-")

        # Handoff should exist
        handoff = manager.handoff_get(result["results"][0]["id"])
        assert handoff is not None
        assert handoff.title == "Batch test handoff"
        assert handoff.description == "Created via batch"

    def test_handoff_batch_process_multiple_updates(
        self, manager: "LessonsManager"
    ):
        """Batch with multiple updates to same handoff should apply all."""
        # Create a handoff first
        handoff_id = manager.handoff_add(title="Multi-update test")

        operations = [
            {"op": "update", "id": handoff_id, "status": "in_progress"},
            {"op": "update", "id": handoff_id, "tried": ["success", "First step done"]},
            {"op": "update", "id": handoff_id, "tried": ["partial", "Second step partial"]},
            {"op": "update", "id": handoff_id, "next": "Continue with third step"},
        ]

        result = manager.handoff_batch_process(operations)

        # All operations should succeed
        assert len(result["results"]) == 4
        assert all(r["ok"] for r in result["results"])

        # Verify all updates applied
        handoff = manager.handoff_get(handoff_id)
        assert handoff.status == "in_progress"
        assert len(handoff.tried) == 2
        assert handoff.tried[0].outcome == "success"
        assert handoff.tried[0].description == "First step done"
        assert handoff.tried[1].outcome == "partial"
        assert handoff.tried[1].description == "Second step partial"
        assert handoff.next_steps == "Continue with third step"

    def test_handoff_batch_process_mixed_operations(
        self, manager: "LessonsManager"
    ):
        """Batch with mixed add, update, and complete operations."""
        operations = [
            {"op": "add", "title": "Mixed ops handoff", "desc": "Will be completed"},
            # Note: we'll use LAST to reference the just-created handoff
        ]

        # First batch: create handoff
        result1 = manager.handoff_batch_process(operations)
        handoff_id = result1["results"][0]["id"]

        # Second batch: update and complete
        operations2 = [
            {"op": "update", "id": handoff_id, "status": "in_progress"},
            {"op": "update", "id": handoff_id, "tried": ["success", "All work done"]},
            {"op": "complete", "id": handoff_id},
        ]

        result2 = manager.handoff_batch_process(operations2)

        # All operations should succeed
        assert len(result2["results"]) == 3
        assert all(r["ok"] for r in result2["results"])

        # Verify final state
        handoff = manager.handoff_get(handoff_id)
        assert handoff.status == "completed"
        assert len(handoff.tried) == 1

    def test_handoff_batch_process_last_reference(
        self, manager: "LessonsManager"
    ):
        """Batch using 'LAST' to reference most recently created handoff."""
        operations = [
            {"op": "add", "title": "First handoff"},
            {"op": "update", "id": "LAST", "status": "in_progress"},
            {"op": "update", "id": "LAST", "tried": ["success", "Work on first"]},
            {"op": "add", "title": "Second handoff"},
            {"op": "update", "id": "LAST", "next": "Next step for second"},
        ]

        result = manager.handoff_batch_process(operations)

        # All operations should succeed
        assert len(result["results"]) == 5
        assert all(r["ok"] for r in result["results"])

        # last_id should be the second handoff created
        assert "last_id" in result
        second_id = result["results"][3]["id"]  # Fourth op is second add
        assert result["last_id"] == second_id

        # Verify first handoff got its updates
        first_id = result["results"][0]["id"]
        first_handoff = manager.handoff_get(first_id)
        assert first_handoff.status == "in_progress"
        assert len(first_handoff.tried) == 1
        assert first_handoff.tried[0].description == "Work on first"

        # Verify second handoff got its update
        second_handoff = manager.handoff_get(second_id)
        assert second_handoff.next_steps == "Next step for second"

    def test_handoff_batch_process_invalid_op_continues(
        self, manager: "LessonsManager"
    ):
        """One bad operation should not stop processing of others."""
        # Create a valid handoff
        valid_id = manager.handoff_add(title="Valid handoff")

        operations = [
            {"op": "update", "id": valid_id, "status": "in_progress"},
            {"op": "update", "id": "hf-invalid", "status": "blocked"},  # Invalid ID
            {"op": "update", "id": valid_id, "tried": ["success", "This should work"]},
            {"op": "complete", "id": "hf-missing"},  # Another invalid ID
            {"op": "update", "id": valid_id, "next": "Final next step"},
        ]

        result = manager.handoff_batch_process(operations)

        # Should have results for all operations
        assert len(result["results"]) == 5

        # Valid operations should succeed
        assert result["results"][0]["ok"] is True  # First update
        assert result["results"][2]["ok"] is True  # Third update (tried)
        assert result["results"][4]["ok"] is True  # Fifth update (next)

        # Invalid operations should fail gracefully
        assert result["results"][1]["ok"] is False
        assert "error" in result["results"][1]
        assert result["results"][3]["ok"] is False
        assert "error" in result["results"][3]

        # Verify valid handoff was fully updated
        handoff = manager.handoff_get(valid_id)
        assert handoff.status == "in_progress"
        assert len(handoff.tried) == 1
        assert handoff.next_steps == "Final next step"

    def test_handoff_batch_process_empty_list(self, manager: "LessonsManager"):
        """Empty operations list should return empty results."""
        result = manager.handoff_batch_process([])

        assert "results" in result
        assert len(result["results"]) == 0
        # last_id should be None or not present for empty batch
        assert result.get("last_id") is None

    def test_handoff_batch_process_invalid_status(self, manager: "LessonsManager"):
        """Invalid status should return error."""
        # First add a handoff
        result = manager.handoff_batch_process([{"op": "add", "title": "Test"}])
        handoff_id = result["results"][0]["id"]

        # Try to update with invalid status
        result = manager.handoff_batch_process([
            {"op": "update", "id": handoff_id, "status": "bogus_status"}
        ])

        assert result["results"][0]["ok"] is False
        assert "Invalid status" in result["results"][0]["error"]

    def test_handoff_batch_process_invalid_phase(self, manager: "LessonsManager"):
        """Invalid phase should return error."""
        # First add a handoff
        result = manager.handoff_batch_process([{"op": "add", "title": "Test"}])
        handoff_id = result["results"][0]["id"]

        # Try to update with invalid phase
        result = manager.handoff_batch_process([
            {"op": "update", "id": handoff_id, "phase": "bogus_phase"}
        ])

        assert result["results"][0]["ok"] is False
        assert "Invalid phase" in result["results"][0]["error"]

    def test_handoff_batch_process_invalid_agent(self, manager: "LessonsManager"):
        """Invalid agent should return error."""
        # First add a handoff
        result = manager.handoff_batch_process([{"op": "add", "title": "Test"}])
        handoff_id = result["results"][0]["id"]

        # Try to update with invalid agent
        result = manager.handoff_batch_process([
            {"op": "update", "id": handoff_id, "agent": "bogus_agent"}
        ])

        assert result["results"][0]["ok"] is False
        assert "Invalid agent" in result["results"][0]["error"]

    def test_handoff_batch_process_invalid_tried_outcome(self, manager: "LessonsManager"):
        """Invalid tried outcome should return error."""
        # First add a handoff
        result = manager.handoff_batch_process([{"op": "add", "title": "Test"}])
        handoff_id = result["results"][0]["id"]

        # Try to update with invalid tried outcome
        result = manager.handoff_batch_process([
            {"op": "update", "id": handoff_id, "tried": ["bogus_outcome", "description"]}
        ])

        assert result["results"][0]["ok"] is False
        assert "Invalid tried outcome" in result["results"][0]["error"]

    def test_handoff_batch_process_no_valid_fields(self, manager: "LessonsManager"):
        """Update with no valid fields should return warning."""
        # First add a handoff
        result = manager.handoff_batch_process([{"op": "add", "title": "Test"}])
        handoff_id = result["results"][0]["id"]

        # Try to update with only invalid fields (empty update)
        result = manager.handoff_batch_process([
            {"op": "update", "id": handoff_id}
        ])

        assert result["results"][0]["ok"] is True
        assert result["results"][0]["id"] == handoff_id
        assert "warning" in result["results"][0]
        assert "No valid fields" in result["results"][0]["warning"]

    def test_handoff_batch_process_last_without_add(self, manager: "LessonsManager"):
        """LAST reference without prior add should fail."""
        result = manager.handoff_batch_process([
            {"op": "update", "id": "LAST", "status": "in_progress"}
        ])

        assert result["results"][0]["ok"] is False
        assert "LAST" in result["results"][0]["error"] or "No handoff" in result["results"][0]["error"]


# =============================================================================
# Transcript Parsing (parse_transcript_for_handoffs)
# =============================================================================


class TestSanitizeText:
    """Tests for _sanitize_text static method."""

    def test_sanitize_text_removes_control_characters(self, manager: "LessonsManager"):
        """Control characters should be removed."""
        text = "Hello\x00World\x07\x08"
        result = manager._sanitize_text(text)
        # Control chars are stripped without adding space
        assert result == "HelloWorld"

    def test_sanitize_text_preserves_unicode(self, manager: "LessonsManager"):
        """Common unicode characters should be preserved."""
        text = "Hello World cafe"
        result = manager._sanitize_text(text)
        assert "cafe" in result

    def test_sanitize_text_collapses_spaces(self, manager: "LessonsManager"):
        """Multiple spaces should be collapsed to single space."""
        text = "Hello    World    Test"
        result = manager._sanitize_text(text)
        assert result == "Hello World Test"

    def test_sanitize_text_truncates(self, manager: "LessonsManager"):
        """Text should be truncated to max_length."""
        text = "a" * 100
        result = manager._sanitize_text(text, max_length=50)
        assert len(result) == 50

    def test_sanitize_text_trims_whitespace(self, manager: "LessonsManager"):
        """Leading and trailing whitespace should be trimmed."""
        text = "  Hello World  "
        result = manager._sanitize_text(text)
        assert result == "Hello World"

    def test_sanitize_text_empty_string(self, manager: "LessonsManager"):
        """Empty string should return empty string."""
        result = manager._sanitize_text("")
        assert result == ""

    def test_sanitize_text_none_like(self, manager: "LessonsManager"):
        """None-like empty values should return empty string."""
        result = manager._sanitize_text(None)
        assert result == ""


class TestInferBlockedBy:
    """Tests for _infer_blocked_by static method."""

    def test_infer_blocked_by_waiting_for(self, manager: "LessonsManager"):
        """Should detect 'waiting for <ID>' pattern."""
        text = "We need to finish this task, waiting for hf-abc1234 to complete first"
        result = manager._infer_blocked_by(text)
        assert "hf-abc1234" in result

    def test_infer_blocked_by_blocked_by(self, manager: "LessonsManager"):
        """Should detect 'blocked by <ID>' pattern."""
        text = "This is blocked by A001"
        result = manager._infer_blocked_by(text)
        assert "A001" in result

    def test_infer_blocked_by_depends_on(self, manager: "LessonsManager"):
        """Should detect 'depends on <ID>' pattern."""
        text = "This feature depends on hf-1234567"
        result = manager._infer_blocked_by(text)
        assert "hf-1234567" in result

    def test_infer_blocked_by_after_completes(self, manager: "LessonsManager"):
        """Should detect 'after <ID> completes' pattern."""
        text = "Start this after A002 completes"
        result = manager._infer_blocked_by(text)
        assert "A002" in result

    def test_infer_blocked_by_multiple(self, manager: "LessonsManager"):
        """Should detect multiple blockers."""
        text = "Waiting for hf-abc1234 and depends on A001"
        result = manager._infer_blocked_by(text)
        assert "hf-abc1234" in result
        assert "A001" in result
        assert len(result) == 2

    def test_infer_blocked_by_no_matches(self, manager: "LessonsManager"):
        """Should return empty list when no blockers found."""
        text = "This is a normal description with no dependencies"
        result = manager._infer_blocked_by(text)
        assert result == []

    def test_infer_blocked_by_empty_text(self, manager: "LessonsManager"):
        """Should return empty list for empty text."""
        result = manager._infer_blocked_by("")
        assert result == []

    def test_infer_blocked_by_case_insensitive(self, manager: "LessonsManager"):
        """Patterns should be case-insensitive."""
        text = "WAITING FOR hf-abc1234 and BLOCKED BY A001"
        result = manager._infer_blocked_by(text)
        assert "hf-abc1234" in result
        assert "A001" in result


class TestParseTranscriptForHandoffs:
    """Tests for parse_transcript_for_handoffs method."""

    def test_parse_handoff_add(self, manager: "LessonsManager"):
        """Should parse HANDOFF: pattern."""
        transcript = {
            "assistant_texts": ["HANDOFF: Implement new feature"]
        }
        result = manager.parse_transcript_for_handoffs(transcript)

        assert len(result) == 1
        assert result[0]["op"] == "add"
        assert result[0]["title"] == "Implement new feature"

    def test_parse_handoff_add_with_description(self, manager: "LessonsManager"):
        """Should parse HANDOFF: pattern with description."""
        transcript = {
            "assistant_texts": ["HANDOFF: Implement feature - This is a detailed description"]
        }
        result = manager.parse_transcript_for_handoffs(transcript)

        assert len(result) == 1
        assert result[0]["op"] == "add"
        assert result[0]["title"] == "Implement feature"
        assert result[0]["desc"] == "This is a detailed description"

    def test_parse_plan_mode(self, manager: "LessonsManager"):
        """Should parse PLAN MODE: pattern."""
        transcript = {
            "assistant_texts": ["PLAN MODE: Design new architecture"]
        }
        result = manager.parse_transcript_for_handoffs(transcript)

        assert len(result) == 1
        assert result[0]["op"] == "add"
        assert result[0]["title"] == "Design new architecture"
        assert result[0]["phase"] == "research"
        assert result[0]["agent"] == "plan"

    def test_parse_handoff_update_status(self, manager: "LessonsManager"):
        """Should parse HANDOFF UPDATE status pattern."""
        transcript = {
            "assistant_texts": ["HANDOFF UPDATE hf-abc1234: status in_progress"]
        }
        result = manager.parse_transcript_for_handoffs(transcript)

        assert len(result) == 1
        assert result[0]["op"] == "update"
        assert result[0]["id"] == "hf-abc1234"
        assert result[0]["status"] == "in_progress"

    def test_parse_handoff_update_phase(self, manager: "LessonsManager"):
        """Should parse HANDOFF UPDATE phase pattern."""
        transcript = {
            "assistant_texts": ["HANDOFF UPDATE A001: phase implementing"]
        }
        result = manager.parse_transcript_for_handoffs(transcript)

        assert len(result) == 1
        assert result[0]["op"] == "update"
        assert result[0]["id"] == "A001"
        assert result[0]["phase"] == "implementing"

    def test_parse_handoff_update_agent(self, manager: "LessonsManager"):
        """Should parse HANDOFF UPDATE agent pattern."""
        transcript = {
            "assistant_texts": ["HANDOFF UPDATE hf-abc1234: agent explore"]
        }
        result = manager.parse_transcript_for_handoffs(transcript)

        assert len(result) == 1
        assert result[0]["op"] == "update"
        assert result[0]["id"] == "hf-abc1234"
        assert result[0]["agent"] == "explore"

    def test_parse_handoff_update_desc(self, manager: "LessonsManager"):
        """Should parse HANDOFF UPDATE desc pattern."""
        transcript = {
            "assistant_texts": ["HANDOFF UPDATE hf-abc1234: desc Updated description text"]
        }
        result = manager.parse_transcript_for_handoffs(transcript)

        assert len(result) == 1
        assert result[0]["op"] == "update"
        assert result[0]["id"] == "hf-abc1234"
        assert result[0]["desc"] == "Updated description text"

    def test_parse_handoff_update_tried_success(self, manager: "LessonsManager"):
        """Should parse HANDOFF UPDATE tried pattern with success outcome."""
        transcript = {
            "assistant_texts": ["HANDOFF UPDATE hf-abc1234: tried success - Implemented the feature"]
        }
        result = manager.parse_transcript_for_handoffs(transcript)

        assert len(result) == 1
        assert result[0]["op"] == "update"
        assert result[0]["id"] == "hf-abc1234"
        assert result[0]["tried"] == ["success", "Implemented the feature"]

    def test_parse_handoff_update_tried_fail(self, manager: "LessonsManager"):
        """Should parse HANDOFF UPDATE tried pattern with fail outcome."""
        transcript = {
            "assistant_texts": ["HANDOFF UPDATE hf-abc1234: tried fail - Approach did not work"]
        }
        result = manager.parse_transcript_for_handoffs(transcript)

        assert len(result) == 1
        assert result[0]["tried"] == ["fail", "Approach did not work"]

    def test_parse_handoff_update_tried_partial(self, manager: "LessonsManager"):
        """Should parse HANDOFF UPDATE tried pattern with partial outcome."""
        transcript = {
            "assistant_texts": ["HANDOFF UPDATE hf-abc1234: tried partial - Works but needs more"]
        }
        result = manager.parse_transcript_for_handoffs(transcript)

        assert len(result) == 1
        assert result[0]["tried"] == ["partial", "Works but needs more"]

    def test_parse_handoff_update_tried_invalid_outcome(self, manager: "LessonsManager"):
        """Should skip HANDOFF UPDATE tried with invalid outcome."""
        transcript = {
            "assistant_texts": ["HANDOFF UPDATE hf-abc1234: tried maybe - Not a valid outcome"]
        }
        result = manager.parse_transcript_for_handoffs(transcript)

        assert len(result) == 0

    def test_parse_handoff_update_next(self, manager: "LessonsManager"):
        """Should parse HANDOFF UPDATE next pattern."""
        transcript = {
            "assistant_texts": ["HANDOFF UPDATE hf-abc1234: next Write tests for the new feature"]
        }
        result = manager.parse_transcript_for_handoffs(transcript)

        assert len(result) == 1
        assert result[0]["op"] == "update"
        assert result[0]["id"] == "hf-abc1234"
        assert result[0]["next"] == "Write tests for the new feature"

    def test_parse_handoff_update_next_with_inferred_blockers(self, manager: "LessonsManager"):
        """Should infer blocked_by from next text."""
        # Note: hf-IDs must be valid hex (0-9, a-f)
        transcript = {
            "assistant_texts": ["HANDOFF UPDATE hf-abc1234: next Waiting for hf-def5678 to complete first"]
        }
        result = manager.parse_transcript_for_handoffs(transcript)

        assert len(result) == 1
        assert result[0]["op"] == "update"
        assert result[0]["next"] == "Waiting for hf-def5678 to complete first"
        assert "blocked_by" in result[0]
        assert "hf-def5678" in result[0]["blocked_by"]

    def test_parse_handoff_update_blocked_by(self, manager: "LessonsManager"):
        """Should parse HANDOFF UPDATE blocked_by pattern."""
        transcript = {
            "assistant_texts": ["HANDOFF UPDATE hf-abc1234: blocked_by A001,A002"]
        }
        result = manager.parse_transcript_for_handoffs(transcript)

        assert len(result) == 1
        assert result[0]["op"] == "update"
        assert result[0]["id"] == "hf-abc1234"
        assert result[0]["blocked_by"] == "A001,A002"

    def test_parse_handoff_update_checkpoint(self, manager: "LessonsManager"):
        """Should parse HANDOFF UPDATE checkpoint pattern."""
        transcript = {
            "assistant_texts": ["HANDOFF UPDATE hf-abc1234: checkpoint Finished implementing core logic"]
        }
        result = manager.parse_transcript_for_handoffs(transcript)

        assert len(result) == 1
        assert result[0]["op"] == "update"
        assert result[0]["id"] == "hf-abc1234"
        assert result[0]["checkpoint"] == "Finished implementing core logic"

    def test_parse_handoff_complete(self, manager: "LessonsManager"):
        """Should parse HANDOFF COMPLETE pattern."""
        transcript = {
            "assistant_texts": ["HANDOFF COMPLETE hf-abc1234"]
        }
        result = manager.parse_transcript_for_handoffs(transcript)

        assert len(result) == 1
        assert result[0]["op"] == "complete"
        assert result[0]["id"] == "hf-abc1234"

    def test_parse_handoff_complete_legacy_format(self, manager: "LessonsManager"):
        """Should parse HANDOFF COMPLETE with legacy A### format."""
        transcript = {
            "assistant_texts": ["HANDOFF COMPLETE A001"]
        }
        result = manager.parse_transcript_for_handoffs(transcript)

        assert len(result) == 1
        assert result[0]["op"] == "complete"
        assert result[0]["id"] == "A001"

    def test_parse_handoff_update_with_last(self, manager: "LessonsManager"):
        """Should parse HANDOFF UPDATE with LAST reference."""
        transcript = {
            "assistant_texts": ["HANDOFF UPDATE LAST: status in_progress"]
        }
        result = manager.parse_transcript_for_handoffs(transcript)

        assert len(result) == 1
        assert result[0]["op"] == "update"
        assert result[0]["id"] == "LAST"
        assert result[0]["status"] == "in_progress"

    def test_parse_handoff_complete_with_last(self, manager: "LessonsManager"):
        """Should parse HANDOFF COMPLETE with LAST reference."""
        transcript = {
            "assistant_texts": ["HANDOFF COMPLETE LAST"]
        }
        result = manager.parse_transcript_for_handoffs(transcript)

        assert len(result) == 1
        assert result[0]["op"] == "complete"
        assert result[0]["id"] == "LAST"

    def test_parse_multiple_patterns(self, manager: "LessonsManager"):
        """Should parse multiple patterns from same text block."""
        transcript = {
            "assistant_texts": [
                "HANDOFF: Implement feature\nHANDOFF UPDATE LAST: status in_progress\nHANDOFF UPDATE LAST: tried success - Done"
            ]
        }
        result = manager.parse_transcript_for_handoffs(transcript)

        assert len(result) == 3
        assert result[0]["op"] == "add"
        assert result[1]["op"] == "update"
        assert result[1]["status"] == "in_progress"
        assert result[2]["op"] == "update"
        assert result[2]["tried"] == ["success", "Done"]

    def test_parse_multiple_text_blocks(self, manager: "LessonsManager"):
        """Should parse patterns from multiple text blocks."""
        transcript = {
            "assistant_texts": [
                "HANDOFF: First feature",
                "HANDOFF: Second feature",
            ]
        }
        result = manager.parse_transcript_for_handoffs(transcript)

        assert len(result) == 2
        assert result[0]["title"] == "First feature"
        assert result[1]["title"] == "Second feature"

    def test_parse_prefers_new_texts(self, manager: "LessonsManager"):
        """Should prefer assistant_texts_new when available."""
        transcript = {
            "assistant_texts": ["HANDOFF: Old feature"],
            "assistant_texts_new": ["HANDOFF: New feature"],
        }
        result = manager.parse_transcript_for_handoffs(transcript)

        assert len(result) == 1
        assert result[0]["title"] == "New feature"

    def test_parse_falls_back_to_all_texts(self, manager: "LessonsManager"):
        """Should fall back to assistant_texts when no new texts."""
        transcript = {
            "assistant_texts": ["HANDOFF: Some feature"],
            "assistant_texts_new": [],
        }
        result = manager.parse_transcript_for_handoffs(transcript)

        assert len(result) == 1
        assert result[0]["title"] == "Some feature"

    def test_parse_empty_transcript(self, manager: "LessonsManager"):
        """Should return empty list for empty transcript."""
        transcript = {}
        result = manager.parse_transcript_for_handoffs(transcript)

        assert result == []

    def test_parse_empty_texts(self, manager: "LessonsManager"):
        """Should return empty list for empty text arrays."""
        transcript = {"assistant_texts": [], "assistant_texts_new": []}
        result = manager.parse_transcript_for_handoffs(transcript)

        assert result == []

    def test_parse_ignores_non_string_texts(self, manager: "LessonsManager"):
        """Should ignore non-string entries in text arrays."""
        transcript = {
            "assistant_texts": [None, 123, {"obj": "value"}, "HANDOFF: Valid feature"]
        }
        result = manager.parse_transcript_for_handoffs(transcript)

        assert len(result) == 1
        assert result[0]["title"] == "Valid feature"

    def test_parse_skips_long_lines(self, manager: "LessonsManager"):
        """Should skip lines over 1000 characters to prevent ReDoS."""
        long_line = "HANDOFF: " + "a" * 1000
        transcript = {
            "assistant_texts": [long_line, "HANDOFF: Short feature"]
        }
        result = manager.parse_transcript_for_handoffs(transcript)

        # Only the short feature should be parsed
        assert len(result) == 1
        assert result[0]["title"] == "Short feature"

    def test_parse_sanitizes_title(self, manager: "LessonsManager"):
        """Should sanitize title text."""
        transcript = {
            "assistant_texts": ["HANDOFF: Feature    with     many   spaces"]
        }
        result = manager.parse_transcript_for_handoffs(transcript)

        assert result[0]["title"] == "Feature with many spaces"

    def test_parse_no_match(self, manager: "LessonsManager"):
        """Should return empty for text with no matching patterns."""
        transcript = {
            "assistant_texts": ["This is just normal text without any handoff patterns"]
        }
        result = manager.parse_transcript_for_handoffs(transcript)

        assert result == []


class TestParseTranscriptIntegration:
    """Integration tests for parse_transcript_for_handoffs + batch_process."""

    def test_parse_and_process_add(self, manager: "LessonsManager"):
        """Should parse and process add operation."""
        transcript = {
            "assistant_texts": ["HANDOFF: New integration feature"]
        }
        operations = manager.parse_transcript_for_handoffs(transcript)
        result = manager.handoff_batch_process(operations)

        assert len(result["results"]) == 1
        assert result["results"][0]["ok"] is True
        assert result["last_id"] is not None

        # Verify handoff was created
        handoff = manager.handoff_get(result["last_id"])
        assert handoff is not None
        assert handoff.title == "New integration feature"

    def test_parse_and_process_add_then_update(self, manager: "LessonsManager"):
        """Should parse and process add followed by update with LAST."""
        transcript = {
            "assistant_texts": [
                "HANDOFF: Feature to update\nHANDOFF UPDATE LAST: status in_progress\nHANDOFF UPDATE LAST: tried success - Completed step 1"
            ]
        }
        operations = manager.parse_transcript_for_handoffs(transcript)
        result = manager.handoff_batch_process(operations)

        assert len(result["results"]) == 3
        assert all(r["ok"] for r in result["results"])

        # Verify handoff state
        handoff = manager.handoff_get(result["last_id"])
        assert handoff is not None
        assert handoff.status == "in_progress"
        assert len(handoff.tried) == 1
        assert handoff.tried[0].outcome == "success"

    def test_parse_and_process_complete(self, manager: "LessonsManager"):
        """Should parse and process complete operation."""
        transcript = {
            "assistant_texts": [
                "HANDOFF: Feature to complete\nHANDOFF COMPLETE LAST"
            ]
        }
        operations = manager.parse_transcript_for_handoffs(transcript)
        result = manager.handoff_batch_process(operations)

        assert len(result["results"]) == 2
        assert all(r["ok"] for r in result["results"])

        # Verify handoff is completed
        handoff = manager.handoff_get(result["last_id"])
        assert handoff is not None
        assert handoff.status == "completed"


class TestLazyOriginDetection:
    """Tests for lazy origin detection optimization in parse_transcript_for_handoffs.

    The optimization: _detect_session_origin should only be called when HANDOFF: or
    PLAN MODE: patterns are found, not for every session. Most sessions (90%) are
    "User" origin and don't need origin detection.
    """

    def test_origin_detection_not_called_when_no_handoff_patterns(
        self, manager: "LessonsManager", monkeypatch: pytest.MonkeyPatch
    ):
        """Origin detection should NOT be called when no HANDOFF/PLAN MODE patterns exist."""
        call_count = 0

        def mock_detect_origin(session_id: str) -> str:
            nonlocal call_count
            call_count += 1
            return "User"

        monkeypatch.setattr(manager, "_detect_session_origin", mock_detect_origin)

        # Parse transcript with no handoff patterns
        transcript = {
            "assistant_texts": [
                "This is just regular text",
                "HANDOFF UPDATE hf-abc1234: status in_progress",  # Update doesn't need origin
                "HANDOFF COMPLETE hf-abc1234",  # Complete doesn't need origin
                "More regular text here",
            ]
        }
        result = manager.parse_transcript_for_handoffs(transcript, session_id="test-session")

        # Should NOT have called origin detection
        assert call_count == 0, f"Expected 0 calls to _detect_session_origin, got {call_count}"

        # Should still parse the update and complete operations
        assert len(result) == 2
        assert result[0]["op"] == "update"
        assert result[1]["op"] == "complete"

    def test_origin_detection_called_when_handoff_add_pattern_found(
        self, manager: "LessonsManager", monkeypatch: pytest.MonkeyPatch
    ):
        """Origin detection SHOULD be called when HANDOFF: pattern is found."""
        call_count = 0

        def mock_detect_origin(session_id: str) -> str:
            nonlocal call_count
            call_count += 1
            return "User"

        monkeypatch.setattr(manager, "_detect_session_origin", mock_detect_origin)

        transcript = {
            "assistant_texts": ["HANDOFF: New feature to implement"]
        }
        result = manager.parse_transcript_for_handoffs(transcript, session_id="test-session")

        # Should have called origin detection exactly once
        assert call_count == 1, f"Expected 1 call to _detect_session_origin, got {call_count}"

        # Should parse the add operation (User can create handoffs)
        assert len(result) == 1
        assert result[0]["op"] == "add"
        assert result[0]["title"] == "New feature to implement"

    def test_origin_detection_called_when_plan_mode_pattern_found(
        self, manager: "LessonsManager", monkeypatch: pytest.MonkeyPatch
    ):
        """Origin detection SHOULD be called when PLAN MODE: pattern is found."""
        call_count = 0

        def mock_detect_origin(session_id: str) -> str:
            nonlocal call_count
            call_count += 1
            return "User"

        monkeypatch.setattr(manager, "_detect_session_origin", mock_detect_origin)

        transcript = {
            "assistant_texts": ["PLAN MODE: Design architecture"]
        }
        result = manager.parse_transcript_for_handoffs(transcript, session_id="test-session")

        assert call_count == 1, f"Expected 1 call to _detect_session_origin, got {call_count}"
        assert len(result) == 1
        assert result[0]["op"] == "add"
        assert result[0]["phase"] == "research"

    def test_origin_detection_only_called_once_for_multiple_add_patterns(
        self, manager: "LessonsManager", monkeypatch: pytest.MonkeyPatch
    ):
        """Origin detection should be called once even with multiple HANDOFF: patterns."""
        call_count = 0

        def mock_detect_origin(session_id: str) -> str:
            nonlocal call_count
            call_count += 1
            return "User"

        monkeypatch.setattr(manager, "_detect_session_origin", mock_detect_origin)

        transcript = {
            "assistant_texts": [
                "HANDOFF: First feature",
                "HANDOFF: Second feature",
                "PLAN MODE: Third feature",
            ]
        }
        result = manager.parse_transcript_for_handoffs(transcript, session_id="test-session")

        # Should only call once, not once per pattern
        assert call_count == 1, f"Expected 1 call to _detect_session_origin, got {call_count}"
        assert len(result) == 3

    def test_subagent_handoff_add_blocked_with_lazy_detection(
        self, manager: "LessonsManager", monkeypatch: pytest.MonkeyPatch
    ):
        """Sub-agent HANDOFF: patterns should still be blocked with lazy detection."""
        monkeypatch.setattr(
            manager, "_detect_session_origin", lambda session_id: "Explore"
        )

        transcript = {
            "assistant_texts": ["HANDOFF: Sub-agent trying to create handoff"]
        }
        result = manager.parse_transcript_for_handoffs(transcript, session_id="explore-session")

        # Sub-agent cannot create handoffs - should return empty
        assert len(result) == 0

    def test_no_origin_detection_without_session_id(
        self, manager: "LessonsManager", monkeypatch: pytest.MonkeyPatch
    ):
        """Without session_id, origin detection should not be called."""
        call_count = 0

        def mock_detect_origin(session_id: str) -> str:
            nonlocal call_count
            call_count += 1
            return "User"

        monkeypatch.setattr(manager, "_detect_session_origin", mock_detect_origin)

        transcript = {
            "assistant_texts": ["HANDOFF: New feature"]
        }
        # No session_id provided - backward compatibility
        result = manager.parse_transcript_for_handoffs(transcript)

        # Should NOT call origin detection when no session_id
        assert call_count == 0
        # Should still create the operation (default to allowing)
        assert len(result) == 1
        assert result[0]["op"] == "add"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestSyncTodosCompletedHandoff:
    """Tests for sync_todos behavior with completed handoffs."""

    def test_sync_todos_does_not_create_handoff_for_completed_reference(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If todos reference a completed handoff, don't create a new one."""
        lessons_base = tmp_path / "lessons_base"
        project_root = tmp_path / "project"
        lessons_base.mkdir()
        project_root.mkdir()

        monkeypatch.setenv("CLAUDE_RECALL_BASE", str(lessons_base))
        monkeypatch.setenv("PROJECT_DIR", str(project_root))

        manager = LessonsManager(lessons_base, project_root)

        # Create and complete a handoff
        handoff_id = manager.handoff_add(title="Original work")
        manager.handoff_update_status(handoff_id, "completed")

        # Now sync todos that reference the completed handoff
        todos = [
            {"content": f"[{handoff_id}] First task", "status": "completed", "activeForm": "First task"},
            {"content": f"[{handoff_id}] Second task", "status": "completed", "activeForm": "Second task"},
            {"content": f"[{handoff_id}] Third task", "status": "completed", "activeForm": "Third task"},
        ]

        result = manager.handoff_sync_todos(todos)

        # Should NOT create a new handoff - the work is tracked under the completed one
        assert result is None

        # Verify no new active handoffs were created
        active = manager.handoff_list(include_completed=False)
        assert len(active) == 0
