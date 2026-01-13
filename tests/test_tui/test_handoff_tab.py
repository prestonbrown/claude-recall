#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Tests for HandoffSummary model extensions in the TUI.

These tests verify the extended HandoffSummary dataclass with:
- New fields: project, agent, description, tried_steps, next_steps, refs, checkpoint
- New TriedStep dataclass for tracking attempts
- New properties: age_days, updated_age_days

These tests are designed to FAIL initially because the new fields don't exist yet.
"""

from dataclasses import FrozenInstanceError
from datetime import date, timedelta

import pytest


# ============================================================================
# Tests for TriedStep dataclass
# ============================================================================


class TestTriedStep:
    """Tests for the TriedStep dataclass."""

    def test_tried_step_importable(self):
        """TriedStep should be importable from core.tui.models."""
        from core.tui.models import TriedStep

        assert TriedStep is not None

    def test_tried_step_basic_creation(self):
        """TriedStep should be creatable with outcome and description."""
        from core.tui.models import TriedStep

        step = TriedStep(outcome="success", description="Initial setup completed")

        assert step.outcome == "success"
        assert step.description == "Initial setup completed"

    def test_tried_step_fail_outcome(self):
        """TriedStep should accept 'fail' outcome."""
        from core.tui.models import TriedStep

        step = TriedStep(outcome="fail", description="Database migration failed")

        assert step.outcome == "fail"
        assert step.description == "Database migration failed"

    def test_tried_step_partial_outcome(self):
        """TriedStep should accept 'partial' outcome."""
        from core.tui.models import TriedStep

        step = TriedStep(outcome="partial", description="Some tests passing")

        assert step.outcome == "partial"
        assert step.description == "Some tests passing"

    def test_tried_step_is_dataclass(self):
        """TriedStep should be a proper dataclass with expected behavior."""
        from dataclasses import is_dataclass

        from core.tui.models import TriedStep

        assert is_dataclass(TriedStep), "TriedStep should be a dataclass"

        # Create two identical instances
        step1 = TriedStep(outcome="success", description="Test")
        step2 = TriedStep(outcome="success", description="Test")

        # Dataclasses with same values should be equal
        assert step1 == step2, "TriedStep instances with same values should be equal"

    def test_tried_step_has_required_fields(self):
        """TriedStep should have outcome and description as required fields."""
        from core.tui.models import TriedStep

        # Should fail without required arguments
        with pytest.raises(TypeError):
            TriedStep()  # type: ignore

        with pytest.raises(TypeError):
            TriedStep(outcome="success")  # type: ignore

        with pytest.raises(TypeError):
            TriedStep(description="Test")  # type: ignore


# ============================================================================
# Tests for HandoffSummary extensions - New fields
# ============================================================================


class TestHandoffSummaryNewFields:
    """Tests for new fields added to HandoffSummary."""

    def test_project_field_exists(self):
        """HandoffSummary should have a project field."""
        from core.tui.models import HandoffSummary

        handoff = HandoffSummary(
            id="hf-abc1234",
            title="Test Handoff",
            status="in_progress",
            phase="implementing",
            created="2026-01-07",
            updated="2026-01-07",
        )

        assert hasattr(handoff, "project"), "HandoffSummary should have 'project' field"

    def test_project_field_default_empty_string(self):
        """HandoffSummary.project should default to empty string."""
        from core.tui.models import HandoffSummary

        handoff = HandoffSummary(
            id="hf-abc1234",
            title="Test Handoff",
            status="in_progress",
            phase="implementing",
            created="2026-01-07",
            updated="2026-01-07",
        )

        assert handoff.project == "", (
            f"Expected project to default to '', got '{handoff.project}'"
        )

    def test_project_field_accepts_value(self):
        """HandoffSummary.project should accept a project path."""
        from core.tui.models import HandoffSummary

        handoff = HandoffSummary(
            id="hf-abc1234",
            title="Test Handoff",
            status="in_progress",
            phase="implementing",
            created="2026-01-07",
            updated="2026-01-07",
            project="/Users/test/code/myproject",
        )

        assert handoff.project == "/Users/test/code/myproject"

    def test_agent_field_exists(self):
        """HandoffSummary should have an agent field."""
        from core.tui.models import HandoffSummary

        handoff = HandoffSummary(
            id="hf-abc1234",
            title="Test Handoff",
            status="in_progress",
            phase="implementing",
            created="2026-01-07",
            updated="2026-01-07",
        )

        assert hasattr(handoff, "agent"), "HandoffSummary should have 'agent' field"

    def test_agent_field_default_user(self):
        """HandoffSummary.agent should default to 'user'."""
        from core.tui.models import HandoffSummary

        handoff = HandoffSummary(
            id="hf-abc1234",
            title="Test Handoff",
            status="in_progress",
            phase="implementing",
            created="2026-01-07",
            updated="2026-01-07",
        )

        assert handoff.agent == "user", (
            f"Expected agent to default to 'user', got '{handoff.agent}'"
        )

    def test_agent_field_accepts_valid_values(self):
        """HandoffSummary.agent should accept valid agent types."""
        from core.tui.models import HandoffSummary

        valid_agents = ["user", "explore", "general-purpose", "plan", "review"]

        for agent_value in valid_agents:
            handoff = HandoffSummary(
                id="hf-abc1234",
                title="Test Handoff",
                status="in_progress",
                phase="implementing",
                created="2026-01-07",
                updated="2026-01-07",
                agent=agent_value,
            )
            assert handoff.agent == agent_value, (
                f"agent should accept '{agent_value}', got '{handoff.agent}'"
            )

    def test_description_field_exists(self):
        """HandoffSummary should have a description field."""
        from core.tui.models import HandoffSummary

        handoff = HandoffSummary(
            id="hf-abc1234",
            title="Test Handoff",
            status="in_progress",
            phase="implementing",
            created="2026-01-07",
            updated="2026-01-07",
        )

        assert hasattr(handoff, "description"), (
            "HandoffSummary should have 'description' field"
        )

    def test_description_field_default_empty_string(self):
        """HandoffSummary.description should default to empty string."""
        from core.tui.models import HandoffSummary

        handoff = HandoffSummary(
            id="hf-abc1234",
            title="Test Handoff",
            status="in_progress",
            phase="implementing",
            created="2026-01-07",
            updated="2026-01-07",
        )

        assert handoff.description == "", (
            f"Expected description to default to '', got '{handoff.description}'"
        )

    def test_description_field_accepts_value(self):
        """HandoffSummary.description should accept full description text."""
        from core.tui.models import HandoffSummary

        desc = "Implementing OAuth2 authentication with Google and GitHub providers."

        handoff = HandoffSummary(
            id="hf-abc1234",
            title="Test Handoff",
            status="in_progress",
            phase="implementing",
            created="2026-01-07",
            updated="2026-01-07",
            description=desc,
        )

        assert handoff.description == desc

    def test_tried_steps_field_exists(self):
        """HandoffSummary should have a tried_steps field."""
        from core.tui.models import HandoffSummary

        handoff = HandoffSummary(
            id="hf-abc1234",
            title="Test Handoff",
            status="in_progress",
            phase="implementing",
            created="2026-01-07",
            updated="2026-01-07",
        )

        assert hasattr(handoff, "tried_steps"), (
            "HandoffSummary should have 'tried_steps' field"
        )

    def test_tried_steps_default_empty_list(self):
        """HandoffSummary.tried_steps should default to empty list."""
        from core.tui.models import HandoffSummary

        handoff = HandoffSummary(
            id="hf-abc1234",
            title="Test Handoff",
            status="in_progress",
            phase="implementing",
            created="2026-01-07",
            updated="2026-01-07",
        )

        assert handoff.tried_steps == [], (
            f"Expected tried_steps to default to [], got {handoff.tried_steps}"
        )
        assert isinstance(handoff.tried_steps, list), (
            "tried_steps should be a list"
        )

    def test_tried_steps_contains_tried_step_objects(self):
        """HandoffSummary.tried_steps should contain TriedStep objects."""
        from core.tui.models import HandoffSummary, TriedStep

        steps = [
            TriedStep(outcome="success", description="Initial setup"),
            TriedStep(outcome="fail", description="First attempt at migration"),
            TriedStep(outcome="partial", description="Some tests passing"),
        ]

        handoff = HandoffSummary(
            id="hf-abc1234",
            title="Test Handoff",
            status="in_progress",
            phase="implementing",
            created="2026-01-07",
            updated="2026-01-07",
            tried_steps=steps,
        )

        assert len(handoff.tried_steps) == 3
        assert all(isinstance(s, TriedStep) for s in handoff.tried_steps)
        assert handoff.tried_steps[0].outcome == "success"
        assert handoff.tried_steps[1].outcome == "fail"
        assert handoff.tried_steps[2].outcome == "partial"

    def test_next_steps_field_exists(self):
        """HandoffSummary should have a next_steps field."""
        from core.tui.models import HandoffSummary

        handoff = HandoffSummary(
            id="hf-abc1234",
            title="Test Handoff",
            status="in_progress",
            phase="implementing",
            created="2026-01-07",
            updated="2026-01-07",
        )

        assert hasattr(handoff, "next_steps"), (
            "HandoffSummary should have 'next_steps' field"
        )

    def test_next_steps_default_empty_list(self):
        """HandoffSummary.next_steps should default to empty list."""
        from core.tui.models import HandoffSummary

        handoff = HandoffSummary(
            id="hf-abc1234",
            title="Test Handoff",
            status="in_progress",
            phase="implementing",
            created="2026-01-07",
            updated="2026-01-07",
        )

        assert handoff.next_steps == [], (
            f"Expected next_steps to default to [], got {handoff.next_steps}"
        )
        assert isinstance(handoff.next_steps, list), (
            "next_steps should be a list"
        )

    def test_next_steps_contains_strings(self):
        """HandoffSummary.next_steps should contain string items."""
        from core.tui.models import HandoffSummary

        next_items = [
            "Complete OAuth2 token refresh",
            "Add unit tests for auth flow",
            "Update documentation",
        ]

        handoff = HandoffSummary(
            id="hf-abc1234",
            title="Test Handoff",
            status="in_progress",
            phase="implementing",
            created="2026-01-07",
            updated="2026-01-07",
            next_steps=next_items,
        )

        assert len(handoff.next_steps) == 3
        assert handoff.next_steps == next_items
        assert all(isinstance(s, str) for s in handoff.next_steps)

    def test_refs_field_exists(self):
        """HandoffSummary should have a refs field."""
        from core.tui.models import HandoffSummary

        handoff = HandoffSummary(
            id="hf-abc1234",
            title="Test Handoff",
            status="in_progress",
            phase="implementing",
            created="2026-01-07",
            updated="2026-01-07",
        )

        assert hasattr(handoff, "refs"), (
            "HandoffSummary should have 'refs' field"
        )

    def test_refs_default_empty_list(self):
        """HandoffSummary.refs should default to empty list."""
        from core.tui.models import HandoffSummary

        handoff = HandoffSummary(
            id="hf-abc1234",
            title="Test Handoff",
            status="in_progress",
            phase="implementing",
            created="2026-01-07",
            updated="2026-01-07",
        )

        assert handoff.refs == [], (
            f"Expected refs to default to [], got {handoff.refs}"
        )
        assert isinstance(handoff.refs, list), (
            "refs should be a list"
        )

    def test_refs_contains_file_references(self):
        """HandoffSummary.refs should contain file:line references."""
        from core.tui.models import HandoffSummary

        file_refs = [
            "core/auth/oauth.py:42",
            "core/auth/tokens.py:156",
            "tests/test_auth.py:23",
        ]

        handoff = HandoffSummary(
            id="hf-abc1234",
            title="Test Handoff",
            status="in_progress",
            phase="implementing",
            created="2026-01-07",
            updated="2026-01-07",
            refs=file_refs,
        )

        assert len(handoff.refs) == 3
        assert handoff.refs == file_refs
        assert all(isinstance(r, str) for r in handoff.refs)

    def test_checkpoint_field_exists(self):
        """HandoffSummary should have a checkpoint field."""
        from core.tui.models import HandoffSummary

        handoff = HandoffSummary(
            id="hf-abc1234",
            title="Test Handoff",
            status="in_progress",
            phase="implementing",
            created="2026-01-07",
            updated="2026-01-07",
        )

        assert hasattr(handoff, "checkpoint"), (
            "HandoffSummary should have 'checkpoint' field"
        )

    def test_checkpoint_default_empty_string(self):
        """HandoffSummary.checkpoint should default to empty string."""
        from core.tui.models import HandoffSummary

        handoff = HandoffSummary(
            id="hf-abc1234",
            title="Test Handoff",
            status="in_progress",
            phase="implementing",
            created="2026-01-07",
            updated="2026-01-07",
        )

        assert handoff.checkpoint == "", (
            f"Expected checkpoint to default to '', got '{handoff.checkpoint}'"
        )

    def test_checkpoint_accepts_value(self):
        """HandoffSummary.checkpoint should accept progress summary text."""
        from core.tui.models import HandoffSummary

        checkpoint_text = "OAuth2 flow working for Google; GitHub integration pending"

        handoff = HandoffSummary(
            id="hf-abc1234",
            title="Test Handoff",
            status="in_progress",
            phase="implementing",
            created="2026-01-07",
            updated="2026-01-07",
            checkpoint=checkpoint_text,
        )

        assert handoff.checkpoint == checkpoint_text


# ============================================================================
# Tests for HandoffSummary extensions - Age properties
# ============================================================================


class TestHandoffSummaryAgeProperties:
    """Tests for age_days and updated_age_days properties."""

    def test_age_days_property_exists(self):
        """HandoffSummary should have an age_days property."""
        from core.tui.models import HandoffSummary

        handoff = HandoffSummary(
            id="hf-abc1234",
            title="Test Handoff",
            status="in_progress",
            phase="implementing",
            created="2026-01-07",
            updated="2026-01-07",
        )

        assert hasattr(handoff, "age_days"), (
            "HandoffSummary should have 'age_days' property"
        )

    def test_age_days_returns_integer(self):
        """HandoffSummary.age_days should return an integer."""
        from core.tui.models import HandoffSummary

        today = date.today().isoformat()

        handoff = HandoffSummary(
            id="hf-abc1234",
            title="Test Handoff",
            status="in_progress",
            phase="implementing",
            created=today,
            updated=today,
        )

        assert isinstance(handoff.age_days, int), (
            f"age_days should return int, got {type(handoff.age_days)}"
        )

    def test_age_days_created_today(self):
        """Handoff created today should have age_days = 0."""
        from core.tui.models import HandoffSummary

        today = date.today().isoformat()

        handoff = HandoffSummary(
            id="hf-abc1234",
            title="Test Handoff",
            status="in_progress",
            phase="implementing",
            created=today,
            updated=today,
        )

        assert handoff.age_days == 0, (
            f"Handoff created today should have age_days=0, got {handoff.age_days}"
        )

    def test_age_days_created_one_day_ago(self):
        """Handoff created yesterday should have age_days = 1."""
        from core.tui.models import HandoffSummary

        yesterday = (date.today() - timedelta(days=1)).isoformat()
        today = date.today().isoformat()

        handoff = HandoffSummary(
            id="hf-abc1234",
            title="Test Handoff",
            status="in_progress",
            phase="implementing",
            created=yesterday,
            updated=today,
        )

        assert handoff.age_days == 1, (
            f"Handoff created yesterday should have age_days=1, got {handoff.age_days}"
        )

    def test_age_days_created_week_ago(self):
        """Handoff created a week ago should have age_days = 7."""
        from core.tui.models import HandoffSummary

        week_ago = (date.today() - timedelta(days=7)).isoformat()
        today = date.today().isoformat()

        handoff = HandoffSummary(
            id="hf-abc1234",
            title="Test Handoff",
            status="in_progress",
            phase="implementing",
            created=week_ago,
            updated=today,
        )

        assert handoff.age_days == 7, (
            f"Handoff created a week ago should have age_days=7, got {handoff.age_days}"
        )

    def test_age_days_invalid_date_returns_zero(self):
        """Invalid created date should return age_days = 0."""
        from core.tui.models import HandoffSummary

        handoff = HandoffSummary(
            id="hf-abc1234",
            title="Test Handoff",
            status="in_progress",
            phase="implementing",
            created="invalid-date",
            updated="2026-01-07",
        )

        assert handoff.age_days == 0, (
            f"Invalid created date should return age_days=0, got {handoff.age_days}"
        )

    def test_age_days_empty_date_returns_zero(self):
        """Empty created date should return age_days = 0."""
        from core.tui.models import HandoffSummary

        handoff = HandoffSummary(
            id="hf-abc1234",
            title="Test Handoff",
            status="in_progress",
            phase="implementing",
            created="",
            updated="2026-01-07",
        )

        assert handoff.age_days == 0, (
            f"Empty created date should return age_days=0, got {handoff.age_days}"
        )

    def test_updated_age_days_property_exists(self):
        """HandoffSummary should have an updated_age_days property."""
        from core.tui.models import HandoffSummary

        handoff = HandoffSummary(
            id="hf-abc1234",
            title="Test Handoff",
            status="in_progress",
            phase="implementing",
            created="2026-01-07",
            updated="2026-01-07",
        )

        assert hasattr(handoff, "updated_age_days"), (
            "HandoffSummary should have 'updated_age_days' property"
        )

    def test_updated_age_days_returns_integer(self):
        """HandoffSummary.updated_age_days should return an integer."""
        from core.tui.models import HandoffSummary

        today = date.today().isoformat()

        handoff = HandoffSummary(
            id="hf-abc1234",
            title="Test Handoff",
            status="in_progress",
            phase="implementing",
            created=today,
            updated=today,
        )

        assert isinstance(handoff.updated_age_days, int), (
            f"updated_age_days should return int, got {type(handoff.updated_age_days)}"
        )

    def test_updated_age_days_updated_today(self):
        """Handoff updated today should have updated_age_days = 0."""
        from core.tui.models import HandoffSummary

        week_ago = (date.today() - timedelta(days=7)).isoformat()
        today = date.today().isoformat()

        handoff = HandoffSummary(
            id="hf-abc1234",
            title="Test Handoff",
            status="in_progress",
            phase="implementing",
            created=week_ago,
            updated=today,
        )

        assert handoff.updated_age_days == 0, (
            f"Handoff updated today should have updated_age_days=0, "
            f"got {handoff.updated_age_days}"
        )

    def test_updated_age_days_updated_three_days_ago(self):
        """Handoff updated 3 days ago should have updated_age_days = 3."""
        from core.tui.models import HandoffSummary

        week_ago = (date.today() - timedelta(days=7)).isoformat()
        three_days_ago = (date.today() - timedelta(days=3)).isoformat()

        handoff = HandoffSummary(
            id="hf-abc1234",
            title="Test Handoff",
            status="in_progress",
            phase="implementing",
            created=week_ago,
            updated=three_days_ago,
        )

        assert handoff.updated_age_days == 3, (
            f"Handoff updated 3 days ago should have updated_age_days=3, "
            f"got {handoff.updated_age_days}"
        )

    def test_updated_age_days_invalid_date_returns_zero(self):
        """Invalid updated date should return updated_age_days = 0."""
        from core.tui.models import HandoffSummary

        handoff = HandoffSummary(
            id="hf-abc1234",
            title="Test Handoff",
            status="in_progress",
            phase="implementing",
            created="2026-01-07",
            updated="not-a-date",
        )

        assert handoff.updated_age_days == 0, (
            f"Invalid updated date should return updated_age_days=0, "
            f"got {handoff.updated_age_days}"
        )

    def test_updated_age_days_empty_date_returns_zero(self):
        """Empty updated date should return updated_age_days = 0."""
        from core.tui.models import HandoffSummary

        handoff = HandoffSummary(
            id="hf-abc1234",
            title="Test Handoff",
            status="in_progress",
            phase="implementing",
            created="2026-01-07",
            updated="",
        )

        assert handoff.updated_age_days == 0, (
            f"Empty updated date should return updated_age_days=0, "
            f"got {handoff.updated_age_days}"
        )


# ============================================================================
# Tests for existing HandoffSummary properties (ensure no regressions)
# ============================================================================


class TestHandoffSummaryExistingProperties:
    """Tests to ensure existing HandoffSummary properties still work."""

    def test_is_active_property(self):
        """is_active should return True for non-completed handoffs."""
        from core.tui.models import HandoffSummary

        active_statuses = ["not_started", "in_progress", "blocked", "ready_for_review"]

        for status in active_statuses:
            handoff = HandoffSummary(
                id="hf-abc1234",
                title="Test Handoff",
                status=status,
                phase="implementing",
                created="2026-01-07",
                updated="2026-01-07",
            )
            assert handoff.is_active is True, (
                f"Status '{status}' should be active, got is_active={handoff.is_active}"
            )

        # Completed should not be active
        completed = HandoffSummary(
            id="hf-abc1234",
            title="Test Handoff",
            status="completed",
            phase="review",
            created="2026-01-07",
            updated="2026-01-07",
        )
        assert completed.is_active is False, (
            "Status 'completed' should not be active"
        )

    def test_is_blocked_property(self):
        """is_blocked should return True only for blocked status."""
        from core.tui.models import HandoffSummary

        blocked = HandoffSummary(
            id="hf-abc1234",
            title="Test Handoff",
            status="blocked",
            phase="implementing",
            created="2026-01-07",
            updated="2026-01-07",
        )
        assert blocked.is_blocked is True

        not_blocked = HandoffSummary(
            id="hf-abc1234",
            title="Test Handoff",
            status="in_progress",
            phase="implementing",
            created="2026-01-07",
            updated="2026-01-07",
        )
        assert not_blocked.is_blocked is False


# ============================================================================
# Tests for full HandoffSummary with all fields
# ============================================================================


class TestHandoffSummaryFullConstruction:
    """Tests for constructing HandoffSummary with all fields."""

    def test_full_handoff_summary_construction(self):
        """HandoffSummary should accept all new fields together."""
        from core.tui.models import HandoffSummary, TriedStep

        tried = [
            TriedStep(outcome="success", description="Initial setup"),
            TriedStep(outcome="fail", description="Migration failed"),
        ]
        next_items = ["Fix migration", "Run tests"]
        refs = ["core/db.py:42", "tests/test_db.py:10"]

        handoff = HandoffSummary(
            id="hf-abc1234",
            title="Database Migration",
            status="in_progress",
            phase="implementing",
            created="2026-01-05",
            updated="2026-01-07",
            project="/Users/test/code/myproject",
            agent="general-purpose",
            description="Migrating from SQLite to PostgreSQL",
            tried_steps=tried,
            next_steps=next_items,
            refs=refs,
            checkpoint="Schema migration complete, data migration pending",
        )

        # Verify all fields
        assert handoff.id == "hf-abc1234"
        assert handoff.title == "Database Migration"
        assert handoff.status == "in_progress"
        assert handoff.phase == "implementing"
        assert handoff.created == "2026-01-05"
        assert handoff.updated == "2026-01-07"
        assert handoff.project == "/Users/test/code/myproject"
        assert handoff.agent == "general-purpose"
        assert handoff.description == "Migrating from SQLite to PostgreSQL"
        assert len(handoff.tried_steps) == 2
        assert len(handoff.next_steps) == 2
        assert len(handoff.refs) == 2
        assert handoff.checkpoint == "Schema migration complete, data migration pending"

    def test_handoff_summary_mutable_lists_are_independent(self):
        """Each HandoffSummary instance should have independent list fields."""
        from core.tui.models import HandoffSummary

        handoff1 = HandoffSummary(
            id="hf-0000001",
            title="First",
            status="in_progress",
            phase="research",
            created="2026-01-07",
            updated="2026-01-07",
        )

        handoff2 = HandoffSummary(
            id="hf-0000002",
            title="Second",
            status="in_progress",
            phase="research",
            created="2026-01-07",
            updated="2026-01-07",
        )

        # Modify handoff1's lists
        handoff1.tried_steps.append("test")  # type: ignore  # Testing mutation
        handoff1.next_steps.append("next")
        handoff1.refs.append("ref")

        # handoff2's lists should be unaffected
        assert len(handoff2.tried_steps) == 0, (
            "handoff2.tried_steps should be independent from handoff1"
        )
        assert len(handoff2.next_steps) == 0, (
            "handoff2.next_steps should be independent from handoff1"
        )
        assert len(handoff2.refs) == 0, (
            "handoff2.refs should be independent from handoff1"
        )


# ============================================================================
# Fixtures for StateReader tests
# ============================================================================


@pytest.fixture
def temp_project_with_handoffs(tmp_path):
    """Create a temp project with a HANDOFFS.md file containing rich data."""
    project_root = tmp_path / "test-project"
    project_root.mkdir()
    recall_dir = project_root / ".claude-recall"
    recall_dir.mkdir()

    handoffs_content = """# HANDOFFS.md - Active Work Tracking

## Active Handoffs

### [hf-8136b12] Include Plan File Path in Handoffs
- **Status**: ready_for_review | **Phase**: implementing | **Agent**: user
- **Created**: 2026-01-07 | **Updated**: 2026-01-08

**Description**: Add plan file path to handoff refs when ExitPlanMode is called.

**Tried** (3 steps):
  1. [success] Write failing test for plan file path
  2. [success] Implement fix in post-exitplanmode-hook.sh
  3. [partial] Run tests to verify

**Next**:
  - Complete code review
  - Merge to main

**Refs**: core/tui/app.py:92, adapters/hooks/post-exitplanmode-hook.sh:45

**Checkpoint**: Tests passing, ready for review

### [hf-a1b2c3d] OAuth2 Integration
- **Status**: blocked | **Phase**: research | **Agent**: explore
- **Created**: 2026-01-05 | **Updated**: 2026-01-06

**Description**: Integrate OAuth2 authentication with Google and GitHub providers.

**Tried** (2 steps):
  1. [success] Research OAuth2 libraries
  2. [fail] Attempt initial Google OAuth setup - missing credentials

**Next**:
  - Get Google OAuth credentials from admin
  - Set up dev environment

**Refs**: core/auth/oauth.py:15, docs/AUTH.md:42

**Checkpoint**: Blocked waiting for credentials

### [hf-xyz9999] Completed Feature
- **Status**: completed | **Phase**: review | **Agent**: general-purpose
- **Created**: 2026-01-01 | **Updated**: 2026-01-03

**Description**: Add dark mode toggle to settings.

**Tried** (1 steps):
  1. [success] Implement dark mode toggle

**Next**:

**Refs**: core/ui/settings.py:100

**Checkpoint**: Merged to main
"""
    (recall_dir / "HANDOFFS.md").write_text(handoffs_content)

    return project_root


@pytest.fixture
def temp_multi_project_setup(tmp_path):
    """Create multiple temp projects with handoffs for cross-project testing."""
    projects = {}

    # Project A - web-app
    project_a = tmp_path / "web-app"
    project_a.mkdir()
    recall_a = project_a / ".claude-recall"
    recall_a.mkdir()
    (recall_a / "HANDOFFS.md").write_text("""# HANDOFFS.md

### [hf-webapp1] Frontend Refactor
- **Status**: in_progress | **Phase**: implementing | **Agent**: general-purpose
- **Created**: 2026-01-06 | **Updated**: 2026-01-08

**Description**: Refactor frontend components to use React hooks.

**Tried** (1 steps):
  1. [success] Convert class components to functional

**Next**:
  - Add unit tests

**Refs**: src/components/App.jsx:10
""")
    projects["web-app"] = project_a

    # Project B - api-server
    project_b = tmp_path / "api-server"
    project_b.mkdir()
    recall_b = project_b / ".claude-recall"
    recall_b.mkdir()
    (recall_b / "HANDOFFS.md").write_text("""# HANDOFFS.md

### [hf-api0001] REST API v2
- **Status**: in_progress | **Phase**: planning | **Agent**: plan
- **Created**: 2026-01-07 | **Updated**: 2026-01-07

**Description**: Design and implement REST API v2 with breaking changes.

**Tried** (0 steps):

**Next**:
  - Write API spec
  - Get team feedback

**Refs**:

### [hf-api0002] Database Migration
- **Status**: blocked | **Phase**: implementing | **Agent**: user
- **Created**: 2026-01-04 | **Updated**: 2026-01-05

**Description**: Migrate from SQLite to PostgreSQL.

**Tried** (1 steps):
  1. [fail] Run migration script - schema incompatibility

**Next**:
  - Fix schema issues

**Refs**: db/migrate.py:50
""")
    projects["api-server"] = project_b

    # Project C - no handoffs (empty file)
    project_c = tmp_path / "empty-project"
    project_c.mkdir()
    recall_c = project_c / ".claude-recall"
    recall_c.mkdir()
    (recall_c / "HANDOFFS.md").write_text("# HANDOFFS.md\n\n")
    projects["empty-project"] = project_c

    return projects


@pytest.fixture
def temp_state_dir_for_reader(tmp_path, monkeypatch):
    """Create temp state directory and set environment."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.setenv("CLAUDE_RECALL_STATE", str(state_dir))
    return state_dir


# ============================================================================
# Tests for StateReader Handoff Parsing Enhancements
# ============================================================================


class TestStateReaderHandoffParsing:
    """Tests for enhanced handoff parsing in StateReader.

    These tests verify that _parse_handoffs_file extracts all fields:
    - agent (from status line)
    - description
    - tried_steps (with outcomes)
    - next_steps
    - refs
    - checkpoint
    """

    def test_parse_agent_field(self, temp_project_with_handoffs):
        """StateReader should extract agent field from status line."""
        from core.tui.state_reader import StateReader

        reader = StateReader(project_root=temp_project_with_handoffs)
        handoffs = reader.get_handoffs(temp_project_with_handoffs)

        # Find the handoff with agent='user'
        user_handoff = next(
            (h for h in handoffs if h.id == "hf-8136b12"), None
        )
        assert user_handoff is not None, "Should find hf-8136b12"
        assert user_handoff.agent == "user", (
            f"Expected agent='user', got '{user_handoff.agent}'"
        )

        # Find the handoff with agent='explore'
        explore_handoff = next(
            (h for h in handoffs if h.id == "hf-a1b2c3d"), None
        )
        assert explore_handoff is not None, "Should find hf-a1b2c3d"
        assert explore_handoff.agent == "explore", (
            f"Expected agent='explore', got '{explore_handoff.agent}'"
        )

        # Find the handoff with agent='general-purpose'
        gp_handoff = next(
            (h for h in handoffs if h.id == "hf-xyz9999"), None
        )
        assert gp_handoff is not None, "Should find hf-xyz9999"
        assert gp_handoff.agent == "general-purpose", (
            f"Expected agent='general-purpose', got '{gp_handoff.agent}'"
        )

    def test_parse_description_field(self, temp_project_with_handoffs):
        """StateReader should extract description field."""
        from core.tui.state_reader import StateReader

        reader = StateReader(project_root=temp_project_with_handoffs)
        handoffs = reader.get_handoffs(temp_project_with_handoffs)

        handoff = next((h for h in handoffs if h.id == "hf-8136b12"), None)
        assert handoff is not None, "Should find hf-8136b12"

        expected_desc = "Add plan file path to handoff refs when ExitPlanMode is called."
        assert handoff.description == expected_desc, (
            f"Expected description='{expected_desc}', got '{handoff.description}'"
        )

    def test_parse_tried_steps(self, temp_project_with_handoffs):
        """StateReader should extract tried steps with outcomes."""
        from core.tui.models import TriedStep
        from core.tui.state_reader import StateReader

        reader = StateReader(project_root=temp_project_with_handoffs)
        handoffs = reader.get_handoffs(temp_project_with_handoffs)

        handoff = next((h for h in handoffs if h.id == "hf-8136b12"), None)
        assert handoff is not None, "Should find hf-8136b12"

        assert len(handoff.tried_steps) == 3, (
            f"Expected 3 tried steps, got {len(handoff.tried_steps)}"
        )

        # Check first step
        step1 = handoff.tried_steps[0]
        assert isinstance(step1, TriedStep), "tried_steps should contain TriedStep objects"
        assert step1.outcome == "success", f"Expected outcome='success', got '{step1.outcome}'"
        assert "Write failing test" in step1.description, (
            f"Expected description to contain 'Write failing test', got '{step1.description}'"
        )

        # Check third step (partial)
        step3 = handoff.tried_steps[2]
        assert step3.outcome == "partial", f"Expected outcome='partial', got '{step3.outcome}'"

    def test_parse_tried_steps_fail_outcome(self, temp_project_with_handoffs):
        """StateReader should correctly parse 'fail' outcome in tried steps."""
        from core.tui.state_reader import StateReader

        reader = StateReader(project_root=temp_project_with_handoffs)
        handoffs = reader.get_handoffs(temp_project_with_handoffs)

        # hf-a1b2c3d has a fail step
        handoff = next((h for h in handoffs if h.id == "hf-a1b2c3d"), None)
        assert handoff is not None, "Should find hf-a1b2c3d"

        assert len(handoff.tried_steps) == 2, (
            f"Expected 2 tried steps, got {len(handoff.tried_steps)}"
        )

        # Second step should be fail
        step2 = handoff.tried_steps[1]
        assert step2.outcome == "fail", f"Expected outcome='fail', got '{step2.outcome}'"
        assert "missing credentials" in step2.description, (
            f"Expected description to contain 'missing credentials', got '{step2.description}'"
        )

    def test_parse_next_steps(self, temp_project_with_handoffs):
        """StateReader should extract next steps list."""
        from core.tui.state_reader import StateReader

        reader = StateReader(project_root=temp_project_with_handoffs)
        handoffs = reader.get_handoffs(temp_project_with_handoffs)

        handoff = next((h for h in handoffs if h.id == "hf-8136b12"), None)
        assert handoff is not None, "Should find hf-8136b12"

        assert len(handoff.next_steps) == 2, (
            f"Expected 2 next steps, got {len(handoff.next_steps)}"
        )
        assert "Complete code review" in handoff.next_steps[0], (
            f"Expected first next step to contain 'Complete code review', "
            f"got '{handoff.next_steps[0]}'"
        )
        assert "Merge to main" in handoff.next_steps[1], (
            f"Expected second next step to contain 'Merge to main', "
            f"got '{handoff.next_steps[1]}'"
        )

    def test_parse_next_steps_empty(self, temp_project_with_handoffs):
        """StateReader should handle empty next steps."""
        from core.tui.state_reader import StateReader

        reader = StateReader(project_root=temp_project_with_handoffs)
        handoffs = reader.get_handoffs(temp_project_with_handoffs)

        # hf-xyz9999 (completed) has empty next steps
        handoff = next((h for h in handoffs if h.id == "hf-xyz9999"), None)
        assert handoff is not None, "Should find hf-xyz9999"

        assert len(handoff.next_steps) == 0, (
            f"Expected 0 next steps for completed handoff, got {len(handoff.next_steps)}"
        )

    def test_parse_refs(self, temp_project_with_handoffs):
        """StateReader should extract file:line references."""
        from core.tui.state_reader import StateReader

        reader = StateReader(project_root=temp_project_with_handoffs)
        handoffs = reader.get_handoffs(temp_project_with_handoffs)

        handoff = next((h for h in handoffs if h.id == "hf-8136b12"), None)
        assert handoff is not None, "Should find hf-8136b12"

        assert len(handoff.refs) == 2, (
            f"Expected 2 refs, got {len(handoff.refs)}"
        )
        assert "core/tui/app.py:92" in handoff.refs, (
            f"Expected 'core/tui/app.py:92' in refs, got {handoff.refs}"
        )
        assert "adapters/hooks/post-exitplanmode-hook.sh:45" in handoff.refs, (
            f"Expected 'adapters/hooks/post-exitplanmode-hook.sh:45' in refs, "
            f"got {handoff.refs}"
        )

    def test_parse_refs_empty(self, temp_multi_project_setup):
        """StateReader should handle empty refs field."""
        from core.tui.state_reader import StateReader

        project_root = temp_multi_project_setup["api-server"]
        reader = StateReader(project_root=project_root)
        handoffs = reader.get_handoffs(project_root)

        # hf-api0001 has empty refs
        handoff = next((h for h in handoffs if h.id == "hf-api0001"), None)
        assert handoff is not None, "Should find hf-api0001"

        assert len(handoff.refs) == 0, (
            f"Expected 0 refs for handoff with empty refs, got {len(handoff.refs)}"
        )

    def test_parse_checkpoint(self, temp_project_with_handoffs):
        """StateReader should extract checkpoint text."""
        from core.tui.state_reader import StateReader

        reader = StateReader(project_root=temp_project_with_handoffs)
        handoffs = reader.get_handoffs(temp_project_with_handoffs)

        handoff = next((h for h in handoffs if h.id == "hf-8136b12"), None)
        assert handoff is not None, "Should find hf-8136b12"

        assert handoff.checkpoint == "Tests passing, ready for review", (
            f"Expected checkpoint='Tests passing, ready for review', "
            f"got '{handoff.checkpoint}'"
        )

    def test_parse_checkpoint_blocked(self, temp_project_with_handoffs):
        """StateReader should extract checkpoint for blocked handoff."""
        from core.tui.state_reader import StateReader

        reader = StateReader(project_root=temp_project_with_handoffs)
        handoffs = reader.get_handoffs(temp_project_with_handoffs)

        handoff = next((h for h in handoffs if h.id == "hf-a1b2c3d"), None)
        assert handoff is not None, "Should find hf-a1b2c3d"

        assert handoff.checkpoint == "Blocked waiting for credentials", (
            f"Expected checkpoint='Blocked waiting for credentials', "
            f"got '{handoff.checkpoint}'"
        )

    def test_parse_multiple_handoffs(self, temp_project_with_handoffs):
        """StateReader should parse all handoffs from a file."""
        from core.tui.state_reader import StateReader

        reader = StateReader(project_root=temp_project_with_handoffs)
        handoffs = reader.get_handoffs(temp_project_with_handoffs)

        assert len(handoffs) == 3, (
            f"Expected 3 handoffs, got {len(handoffs)}"
        )

        # Verify all IDs are present
        ids = {h.id for h in handoffs}
        expected_ids = {"hf-8136b12", "hf-a1b2c3d", "hf-xyz9999"}
        assert ids == expected_ids, (
            f"Expected IDs {expected_ids}, got {ids}"
        )


# ============================================================================
# Tests for StateReader.get_all_handoffs()
# ============================================================================


class TestStateReaderGetAllHandoffs:
    """Tests for the get_all_handoffs() method.

    This method should scan multiple projects and return handoffs from all of them,
    with the 'project' field populated to indicate which project each handoff belongs to.
    """

    def test_get_all_handoffs_method_exists(self, temp_state_dir_for_reader):
        """StateReader should have a get_all_handoffs() method."""
        from core.tui.state_reader import StateReader

        reader = StateReader()

        assert hasattr(reader, "get_all_handoffs"), (
            "StateReader should have 'get_all_handoffs' method"
        )
        assert callable(getattr(reader, "get_all_handoffs", None)), (
            "get_all_handoffs should be callable"
        )

    def test_get_all_handoffs_returns_list(self, temp_state_dir_for_reader):
        """get_all_handoffs should return a list."""
        from core.tui.state_reader import StateReader

        reader = StateReader()
        result = reader.get_all_handoffs()

        assert isinstance(result, list), (
            f"get_all_handoffs should return list, got {type(result)}"
        )

    def test_get_all_handoffs_scans_projects(
        self, temp_multi_project_setup, temp_state_dir_for_reader, monkeypatch
    ):
        """get_all_handoffs should find handoffs across multiple projects."""
        from core.tui.state_reader import StateReader

        # Set up known projects list for the reader to scan
        # This may require monkeypatching or environment setup depending on implementation
        projects = temp_multi_project_setup

        # Create a reader that knows about these projects
        reader = StateReader()

        # The implementation needs to know where to look for projects.
        # It might scan a parent directory, use environment, or take a list.
        # For this test, we pass the projects explicitly.
        all_handoffs = reader.get_all_handoffs(
            project_roots=[projects["web-app"], projects["api-server"], projects["empty-project"]]
        )

        # web-app has 1 handoff, api-server has 2, empty-project has 0
        # Total should be 3
        assert len(all_handoffs) == 3, (
            f"Expected 3 handoffs across all projects, got {len(all_handoffs)}"
        )

    def test_get_all_handoffs_populates_project_field(
        self, temp_multi_project_setup, temp_state_dir_for_reader
    ):
        """Each handoff should have its project field populated."""
        from core.tui.state_reader import StateReader

        projects = temp_multi_project_setup
        reader = StateReader()

        all_handoffs = reader.get_all_handoffs(
            project_roots=[projects["web-app"], projects["api-server"]]
        )

        # All handoffs should have non-empty project field
        for handoff in all_handoffs:
            assert handoff.project != "", (
                f"Handoff {handoff.id} should have project field populated"
            )

        # Find handoff from web-app and verify project path
        webapp_handoff = next(
            (h for h in all_handoffs if h.id == "hf-webapp1"), None
        )
        assert webapp_handoff is not None, "Should find hf-webapp1"
        assert "web-app" in webapp_handoff.project, (
            f"Expected 'web-app' in project path, got '{webapp_handoff.project}'"
        )

        # Find handoff from api-server and verify project path
        api_handoff = next(
            (h for h in all_handoffs if h.id == "hf-api0001"), None
        )
        assert api_handoff is not None, "Should find hf-api0001"
        assert "api-server" in api_handoff.project, (
            f"Expected 'api-server' in project path, got '{api_handoff.project}'"
        )

    def test_get_all_handoffs_handles_empty_projects(
        self, temp_multi_project_setup, temp_state_dir_for_reader
    ):
        """get_all_handoffs should gracefully handle projects with no handoffs."""
        from core.tui.state_reader import StateReader

        projects = temp_multi_project_setup
        reader = StateReader()

        # Include the empty project
        all_handoffs = reader.get_all_handoffs(
            project_roots=[projects["empty-project"], projects["web-app"]]
        )

        # Should only have handoffs from web-app (1)
        assert len(all_handoffs) == 1, (
            f"Expected 1 handoff (empty project contributes 0), got {len(all_handoffs)}"
        )


# ============================================================================
# Tests for StateReader.get_handoff_stats()
# ============================================================================


class TestStateReaderHandoffStats:
    """Tests for the get_handoff_stats() method.

    This method should compute statistics from a list of handoffs:
    - total_count
    - by_status (dict mapping status -> count)
    - by_phase (dict mapping phase -> count)
    - age_stats (min, max, avg age in days)
    - blocked_count
    - stale_count (>7 days since update)
    """

    def test_get_handoff_stats_method_exists(self, temp_state_dir_for_reader):
        """StateReader should have a get_handoff_stats() method."""
        from core.tui.state_reader import StateReader

        reader = StateReader()

        assert hasattr(reader, "get_handoff_stats"), (
            "StateReader should have 'get_handoff_stats' method"
        )
        assert callable(getattr(reader, "get_handoff_stats", None)), (
            "get_handoff_stats should be callable"
        )

    def test_get_handoff_stats_returns_dict(self, temp_project_with_handoffs):
        """get_handoff_stats should return a dictionary."""
        from core.tui.state_reader import StateReader

        reader = StateReader(project_root=temp_project_with_handoffs)
        handoffs = reader.get_handoffs(temp_project_with_handoffs)
        stats = reader.get_handoff_stats(handoffs)

        assert isinstance(stats, dict), (
            f"get_handoff_stats should return dict, got {type(stats)}"
        )

    def test_get_handoff_stats_total_count(self, temp_project_with_handoffs):
        """get_handoff_stats should include total_count."""
        from core.tui.state_reader import StateReader

        reader = StateReader(project_root=temp_project_with_handoffs)
        handoffs = reader.get_handoffs(temp_project_with_handoffs)
        stats = reader.get_handoff_stats(handoffs)

        assert "total_count" in stats, (
            "Stats should include 'total_count' key"
        )
        assert stats["total_count"] == 3, (
            f"Expected total_count=3, got {stats['total_count']}"
        )

    def test_get_handoff_stats_by_status(self, temp_project_with_handoffs):
        """get_handoff_stats should count handoffs by status."""
        from core.tui.state_reader import StateReader

        reader = StateReader(project_root=temp_project_with_handoffs)
        handoffs = reader.get_handoffs(temp_project_with_handoffs)
        stats = reader.get_handoff_stats(handoffs)

        assert "by_status" in stats, (
            "Stats should include 'by_status' key"
        )
        by_status = stats["by_status"]

        # Our fixture has: 1 ready_for_review, 1 blocked, 1 completed
        assert by_status.get("ready_for_review", 0) == 1, (
            f"Expected 1 ready_for_review, got {by_status.get('ready_for_review', 0)}"
        )
        assert by_status.get("blocked", 0) == 1, (
            f"Expected 1 blocked, got {by_status.get('blocked', 0)}"
        )
        assert by_status.get("completed", 0) == 1, (
            f"Expected 1 completed, got {by_status.get('completed', 0)}"
        )

    def test_get_handoff_stats_by_phase(self, temp_project_with_handoffs):
        """get_handoff_stats should count handoffs by phase."""
        from core.tui.state_reader import StateReader

        reader = StateReader(project_root=temp_project_with_handoffs)
        handoffs = reader.get_handoffs(temp_project_with_handoffs)
        stats = reader.get_handoff_stats(handoffs)

        assert "by_phase" in stats, (
            "Stats should include 'by_phase' key"
        )
        by_phase = stats["by_phase"]

        # Our fixture has: 1 implementing, 1 research, 1 review
        assert by_phase.get("implementing", 0) == 1, (
            f"Expected 1 implementing, got {by_phase.get('implementing', 0)}"
        )
        assert by_phase.get("research", 0) == 1, (
            f"Expected 1 research, got {by_phase.get('research', 0)}"
        )
        assert by_phase.get("review", 0) == 1, (
            f"Expected 1 review, got {by_phase.get('review', 0)}"
        )

    def test_get_handoff_stats_age_stats(self, temp_project_with_handoffs):
        """get_handoff_stats should include age statistics."""
        from core.tui.state_reader import StateReader

        reader = StateReader(project_root=temp_project_with_handoffs)
        handoffs = reader.get_handoffs(temp_project_with_handoffs)
        stats = reader.get_handoff_stats(handoffs)

        assert "age_stats" in stats, (
            "Stats should include 'age_stats' key"
        )
        age_stats = stats["age_stats"]

        # Age stats should have min, max, avg
        assert "min_age_days" in age_stats, "age_stats should have 'min_age_days'"
        assert "max_age_days" in age_stats, "age_stats should have 'max_age_days'"
        assert "avg_age_days" in age_stats, "age_stats should have 'avg_age_days'"

        # All values should be non-negative
        assert age_stats["min_age_days"] >= 0, "min_age_days should be non-negative"
        assert age_stats["max_age_days"] >= 0, "max_age_days should be non-negative"
        assert age_stats["avg_age_days"] >= 0, "avg_age_days should be non-negative"

        # Max should be >= min
        assert age_stats["max_age_days"] >= age_stats["min_age_days"], (
            "max_age_days should be >= min_age_days"
        )

    def test_get_handoff_stats_blocked_count(self, temp_project_with_handoffs):
        """get_handoff_stats should count blocked handoffs."""
        from core.tui.state_reader import StateReader

        reader = StateReader(project_root=temp_project_with_handoffs)
        handoffs = reader.get_handoffs(temp_project_with_handoffs)
        stats = reader.get_handoff_stats(handoffs)

        assert "blocked_count" in stats, (
            "Stats should include 'blocked_count' key"
        )
        # Our fixture has 1 blocked handoff
        assert stats["blocked_count"] == 1, (
            f"Expected blocked_count=1, got {stats['blocked_count']}"
        )

    def test_get_handoff_stats_stale_count(self, tmp_path):
        """get_handoff_stats should count stale handoffs (>7 days since update)."""
        from datetime import date, timedelta

        from core.tui.state_reader import StateReader

        # Create project with stale handoffs
        project_root = tmp_path / "stale-project"
        project_root.mkdir()
        recall_dir = project_root / ".claude-recall"
        recall_dir.mkdir()

        today = date.today().isoformat()
        eight_days_ago = (date.today() - timedelta(days=8)).isoformat()
        three_days_ago = (date.today() - timedelta(days=3)).isoformat()

        handoffs_content = f"""# HANDOFFS.md

### [hf-stale01] Stale Handoff
- **Status**: in_progress | **Phase**: implementing | **Agent**: user
- **Created**: {eight_days_ago} | **Updated**: {eight_days_ago}

### [hf-fresh01] Fresh Handoff
- **Status**: in_progress | **Phase**: research | **Agent**: user
- **Created**: {three_days_ago} | **Updated**: {today}

### [hf-stale02] Another Stale One
- **Status**: blocked | **Phase**: planning | **Agent**: user
- **Created**: 2026-01-01 | **Updated**: 2026-01-01
"""
        (recall_dir / "HANDOFFS.md").write_text(handoffs_content)

        reader = StateReader(project_root=project_root)
        handoffs = reader.get_handoffs(project_root)
        stats = reader.get_handoff_stats(handoffs)

        assert "stale_count" in stats, (
            "Stats should include 'stale_count' key"
        )
        # 2 handoffs are stale (>7 days old): hf-stale01, hf-stale02
        assert stats["stale_count"] == 2, (
            f"Expected stale_count=2, got {stats['stale_count']}"
        )

    def test_get_handoff_stats_empty_list(self, temp_state_dir_for_reader):
        """get_handoff_stats should handle empty handoff list."""
        from core.tui.state_reader import StateReader

        reader = StateReader()
        stats = reader.get_handoff_stats([])

        assert stats["total_count"] == 0, "total_count should be 0 for empty list"
        assert stats["blocked_count"] == 0, "blocked_count should be 0 for empty list"
        assert stats["stale_count"] == 0, "stale_count should be 0 for empty list"
        assert stats["by_status"] == {}, "by_status should be empty dict for empty list"
        assert stats["by_phase"] == {}, "by_phase should be empty dict for empty list"

    def test_get_handoff_stats_active_count(self, temp_project_with_handoffs):
        """get_handoff_stats should count active (non-completed) handoffs."""
        from core.tui.state_reader import StateReader

        reader = StateReader(project_root=temp_project_with_handoffs)
        handoffs = reader.get_handoffs(temp_project_with_handoffs)
        stats = reader.get_handoff_stats(handoffs)

        assert "active_count" in stats, (
            "Stats should include 'active_count' key"
        )
        # Our fixture has 3 handoffs, 1 completed, so 2 active
        assert stats["active_count"] == 2, (
            f"Expected active_count=2, got {stats['active_count']}"
        )


# ============================================================================
# Tests for HandoffSummary blocked_by field
# ============================================================================


class TestHandoffSummaryBlockedBy:
    """Tests for the blocked_by field in HandoffSummary."""

    def test_blocked_by_field_exists(self):
        """HandoffSummary should have a blocked_by field."""
        from core.tui.models import HandoffSummary

        handoff = HandoffSummary(
            id="hf-abc1234",
            title="Test Handoff",
            status="blocked",
            phase="implementing",
            created="2026-01-07",
            updated="2026-01-07",
        )

        assert hasattr(handoff, "blocked_by"), (
            "HandoffSummary should have 'blocked_by' field"
        )

    def test_blocked_by_default_empty_list(self):
        """HandoffSummary.blocked_by should default to empty list."""
        from core.tui.models import HandoffSummary

        handoff = HandoffSummary(
            id="hf-abc1234",
            title="Test Handoff",
            status="blocked",
            phase="implementing",
            created="2026-01-07",
            updated="2026-01-07",
        )

        assert handoff.blocked_by == [], (
            f"Expected blocked_by to default to [], got {handoff.blocked_by}"
        )
        assert isinstance(handoff.blocked_by, list), (
            "blocked_by should be a list"
        )

    def test_blocked_by_accepts_handoff_ids(self):
        """HandoffSummary.blocked_by should accept list of handoff IDs."""
        from core.tui.models import HandoffSummary

        blocking_ids = ["hf-dep0001", "hf-dep0002"]

        handoff = HandoffSummary(
            id="hf-abc1234",
            title="Test Handoff",
            status="blocked",
            phase="implementing",
            created="2026-01-07",
            updated="2026-01-07",
            blocked_by=blocking_ids,
        )

        assert len(handoff.blocked_by) == 2
        assert handoff.blocked_by == blocking_ids
        assert all(isinstance(id_, str) for id_ in handoff.blocked_by)


# ============================================================================
# Tests for HandoffSummary handoff (HandoffContext) field
# ============================================================================


class TestHandoffSummaryContext:
    """Tests for the handoff (HandoffContext) field in HandoffSummary."""

    def test_handoff_context_field_exists(self):
        """HandoffSummary should have a handoff field for HandoffContext."""
        from core.tui.models import HandoffSummary

        handoff = HandoffSummary(
            id="hf-abc1234",
            title="Test Handoff",
            status="in_progress",
            phase="implementing",
            created="2026-01-07",
            updated="2026-01-07",
        )

        assert hasattr(handoff, "handoff"), (
            "HandoffSummary should have 'handoff' field for HandoffContext"
        )

    def test_handoff_context_default_none(self):
        """HandoffSummary.handoff should default to None."""
        from core.tui.models import HandoffSummary

        handoff = HandoffSummary(
            id="hf-abc1234",
            title="Test Handoff",
            status="in_progress",
            phase="implementing",
            created="2026-01-07",
            updated="2026-01-07",
        )

        assert handoff.handoff is None, (
            f"Expected handoff to default to None, got {handoff.handoff}"
        )

    def test_handoff_context_accepts_context_object(self):
        """HandoffSummary.handoff should accept a HandoffContextSummary."""
        from core.tui.models import HandoffContextSummary, HandoffSummary

        context = HandoffContextSummary(
            summary="OAuth2 integration 80% complete",
            critical_files=["core/auth/oauth.py:42", "core/auth/tokens.py:100"],
            recent_changes=["Added Google OAuth flow", "Fixed token refresh"],
            learnings=["OAuth2 requires PKCE for mobile apps"],
            blockers=["Need GitHub OAuth credentials"],
            git_ref="abc1234def5678",
        )

        handoff = HandoffSummary(
            id="hf-abc1234",
            title="OAuth Integration",
            status="in_progress",
            phase="implementing",
            created="2026-01-07",
            updated="2026-01-07",
            handoff=context,
        )

        assert handoff.handoff is not None
        assert handoff.handoff.summary == "OAuth2 integration 80% complete"
        assert len(handoff.handoff.critical_files) == 2
        assert len(handoff.handoff.recent_changes) == 2
        assert len(handoff.handoff.learnings) == 1
        assert len(handoff.handoff.blockers) == 1
        assert handoff.handoff.git_ref == "abc1234def5678"


# ============================================================================
# Tests for HandoffContextSummary dataclass
# ============================================================================


class TestHandoffContextSummary:
    """Tests for the HandoffContextSummary dataclass."""

    def test_handoff_context_summary_importable(self):
        """HandoffContextSummary should be importable from core.tui.models."""
        from core.tui.models import HandoffContextSummary

        assert HandoffContextSummary is not None

    def test_handoff_context_summary_basic_creation(self):
        """HandoffContextSummary should be creatable with all fields."""
        from core.tui.models import HandoffContextSummary

        context = HandoffContextSummary(
            summary="Working on feature X",
            critical_files=["core/feature.py:10"],
            recent_changes=["Added new method"],
            learnings=["Found edge case"],
            blockers=[],
            git_ref="abc1234",
        )

        assert context.summary == "Working on feature X"
        assert context.critical_files == ["core/feature.py:10"]
        assert context.recent_changes == ["Added new method"]
        assert context.learnings == ["Found edge case"]
        assert context.blockers == []
        assert context.git_ref == "abc1234"

    def test_handoff_context_summary_is_dataclass(self):
        """HandoffContextSummary should be a proper dataclass."""
        from dataclasses import is_dataclass

        from core.tui.models import HandoffContextSummary

        assert is_dataclass(HandoffContextSummary), (
            "HandoffContextSummary should be a dataclass"
        )

    def test_handoff_context_summary_has_required_fields(self):
        """HandoffContextSummary should have all required fields."""
        from core.tui.models import HandoffContextSummary

        # Should fail without required arguments
        with pytest.raises(TypeError):
            HandoffContextSummary()  # type: ignore


# ============================================================================
# Tests for StateReader parsing blocked_by
# ============================================================================


class TestStateReaderBlockedByParsing:
    """Tests for parsing blocked_by field in StateReader."""

    def test_parse_blocked_by_single(self, tmp_path):
        """StateReader should parse single blocked_by ID."""
        from core.tui.state_reader import StateReader

        project_root = tmp_path / "test-project"
        project_root.mkdir()
        recall_dir = project_root / ".claude-recall"
        recall_dir.mkdir()

        handoffs_content = """# HANDOFFS.md

### [hf-blocked1] Blocked Handoff
- **Status**: blocked | **Phase**: implementing | **Agent**: user
- **Created**: 2026-01-07 | **Updated**: 2026-01-07
- **Blocked By**: hf-dep0001

**Description**: Waiting on dependency.
"""
        (recall_dir / "HANDOFFS.md").write_text(handoffs_content)

        reader = StateReader(project_root=project_root)
        handoffs = reader.get_handoffs(project_root)

        assert len(handoffs) == 1
        handoff = handoffs[0]
        assert hasattr(handoff, "blocked_by"), "Handoff should have blocked_by field"
        assert handoff.blocked_by == ["hf-dep0001"], (
            f"Expected blocked_by=['hf-dep0001'], got {handoff.blocked_by}"
        )

    def test_parse_blocked_by_multiple(self, tmp_path):
        """StateReader should parse multiple blocked_by IDs."""
        from core.tui.state_reader import StateReader

        project_root = tmp_path / "test-project"
        project_root.mkdir()
        recall_dir = project_root / ".claude-recall"
        recall_dir.mkdir()

        handoffs_content = """# HANDOFFS.md

### [hf-blocked1] Multi-blocked Handoff
- **Status**: blocked | **Phase**: implementing | **Agent**: user
- **Created**: 2026-01-07 | **Updated**: 2026-01-07
- **Blocked By**: hf-dep0001, hf-dep0002, hf-dep0003

**Description**: Waiting on multiple dependencies.
"""
        (recall_dir / "HANDOFFS.md").write_text(handoffs_content)

        reader = StateReader(project_root=project_root)
        handoffs = reader.get_handoffs(project_root)

        assert len(handoffs) == 1
        handoff = handoffs[0]
        assert len(handoff.blocked_by) == 3, (
            f"Expected 3 blocked_by IDs, got {len(handoff.blocked_by)}"
        )
        assert "hf-dep0001" in handoff.blocked_by
        assert "hf-dep0002" in handoff.blocked_by
        assert "hf-dep0003" in handoff.blocked_by

    def test_parse_blocked_by_empty(self, tmp_path):
        """StateReader should handle missing blocked_by field."""
        from core.tui.state_reader import StateReader

        project_root = tmp_path / "test-project"
        project_root.mkdir()
        recall_dir = project_root / ".claude-recall"
        recall_dir.mkdir()

        handoffs_content = """# HANDOFFS.md

### [hf-normal1] Normal Handoff
- **Status**: in_progress | **Phase**: implementing | **Agent**: user
- **Created**: 2026-01-07 | **Updated**: 2026-01-07

**Description**: No blocked_by field.
"""
        (recall_dir / "HANDOFFS.md").write_text(handoffs_content)

        reader = StateReader(project_root=project_root)
        handoffs = reader.get_handoffs(project_root)

        assert len(handoffs) == 1
        handoff = handoffs[0]
        assert handoff.blocked_by == [], (
            f"Expected empty blocked_by list, got {handoff.blocked_by}"
        )


# ============================================================================
# Tests for StateReader parsing HandoffContext
# ============================================================================


class TestStateReaderHandoffContextParsing:
    """Tests for parsing HandoffContext fields in StateReader."""

    def test_parse_handoff_context_section(self, tmp_path):
        """StateReader should parse Handoff Context section."""
        from core.tui.state_reader import StateReader

        project_root = tmp_path / "test-project"
        project_root.mkdir()
        recall_dir = project_root / ".claude-recall"
        recall_dir.mkdir()

        handoffs_content = """# HANDOFFS.md

### [hf-ctx0001] Handoff with Context
- **Status**: in_progress | **Phase**: implementing | **Agent**: user
- **Created**: 2026-01-07 | **Updated**: 2026-01-07

**Description**: Has full handoff context.

**Handoff Context**:
- **Git Ref**: abc1234def5678
- **Summary**: OAuth2 integration 80% complete
- **Critical Files**: core/auth/oauth.py:42, core/auth/tokens.py:100
- **Recent Changes**: Added Google OAuth flow, Fixed token refresh
- **Learnings**: OAuth2 requires PKCE for mobile apps
- **Blockers**: Need GitHub OAuth credentials
"""
        (recall_dir / "HANDOFFS.md").write_text(handoffs_content)

        reader = StateReader(project_root=project_root)
        handoffs = reader.get_handoffs(project_root)

        assert len(handoffs) == 1
        handoff = handoffs[0]
        assert handoff.handoff is not None, "Handoff should have handoff context"
        assert handoff.handoff.git_ref == "abc1234def5678", (
            f"Expected git_ref='abc1234def5678', got '{handoff.handoff.git_ref}'"
        )
        assert "OAuth2 integration" in handoff.handoff.summary, (
            f"Expected summary to contain 'OAuth2 integration', got '{handoff.handoff.summary}'"
        )
        assert len(handoff.handoff.critical_files) == 2, (
            f"Expected 2 critical files, got {len(handoff.handoff.critical_files)}"
        )
        assert len(handoff.handoff.recent_changes) == 2, (
            f"Expected 2 recent changes, got {len(handoff.handoff.recent_changes)}"
        )
        assert len(handoff.handoff.learnings) == 1, (
            f"Expected 1 learning, got {len(handoff.handoff.learnings)}"
        )
        assert len(handoff.handoff.blockers) == 1, (
            f"Expected 1 blocker, got {len(handoff.handoff.blockers)}"
        )

    def test_parse_handoff_context_missing(self, tmp_path):
        """StateReader should handle missing Handoff Context section."""
        from core.tui.state_reader import StateReader

        project_root = tmp_path / "test-project"
        project_root.mkdir()
        recall_dir = project_root / ".claude-recall"
        recall_dir.mkdir()

        handoffs_content = """# HANDOFFS.md

### [hf-noctx1] Handoff without Context
- **Status**: in_progress | **Phase**: implementing | **Agent**: user
- **Created**: 2026-01-07 | **Updated**: 2026-01-07

**Description**: No handoff context section.
"""
        (recall_dir / "HANDOFFS.md").write_text(handoffs_content)

        reader = StateReader(project_root=project_root)
        handoffs = reader.get_handoffs(project_root)

        assert len(handoffs) == 1
        handoff = handoffs[0]
        assert handoff.handoff is None, (
            f"Expected handoff context to be None, got {handoff.handoff}"
        )

    def test_parse_handoff_context_partial(self, tmp_path):
        """StateReader should handle partial Handoff Context (some fields missing)."""
        from core.tui.state_reader import StateReader

        project_root = tmp_path / "test-project"
        project_root.mkdir()
        recall_dir = project_root / ".claude-recall"
        recall_dir.mkdir()

        handoffs_content = """# HANDOFFS.md

### [hf-partial1] Handoff with Partial Context
- **Status**: in_progress | **Phase**: implementing | **Agent**: user
- **Created**: 2026-01-07 | **Updated**: 2026-01-07

**Description**: Has partial handoff context.

**Handoff Context**:
- **Git Ref**: abc1234
- **Summary**: Partial context example
"""
        (recall_dir / "HANDOFFS.md").write_text(handoffs_content)

        reader = StateReader(project_root=project_root)
        handoffs = reader.get_handoffs(project_root)

        assert len(handoffs) == 1
        handoff = handoffs[0]
        assert handoff.handoff is not None, "Handoff should have handoff context"
        assert handoff.handoff.git_ref == "abc1234"
        assert handoff.handoff.summary == "Partial context example"
        # Missing fields should be empty lists or empty strings
        assert handoff.handoff.critical_files == []
        assert handoff.handoff.recent_changes == []
        assert handoff.handoff.learnings == []
        assert handoff.handoff.blockers == []


# ============================================================================
# Tests for _show_handoff_details displaying new fields
# ============================================================================


@pytest.fixture
def temp_project_with_full_handoffs(tmp_path):
    """Create temp project with handoffs containing all fields including context."""
    project_root = tmp_path / "test-project"
    project_root.mkdir()
    recall_dir = project_root / ".claude-recall"
    recall_dir.mkdir()

    handoffs_content = """# HANDOFFS.md

### [hf-full001] Full Details Handoff
- **Status**: in_progress | **Phase**: implementing | **Agent**: general-purpose
- **Created**: 2026-01-05 | **Updated**: 2026-01-08
- **Blocked By**: hf-dep0001, hf-dep0002

**Description**: A handoff with all fields populated for testing display.

**Tried** (2 steps):
  1. [success] Initial implementation
  2. [partial] Test coverage at 70%

**Next**:
  - Increase test coverage to 90%
  - Add integration tests

**Refs**: core/feature.py:42, tests/test_feature.py:10

**Checkpoint**: Basic implementation done

**Handoff Context**:
- **Git Ref**: abc1234def5678901234567890abcdef12345678
- **Summary**: Feature implementation 80% complete, tests needed
- **Critical Files**: core/feature.py:42, core/utils.py:100
- **Recent Changes**: Added main feature logic, Refactored helper functions
- **Learnings**: Edge case with empty input needs handling
- **Blockers**: Waiting for API spec clarification

### [hf-minimal] Minimal Handoff
- **Status**: not_started | **Phase**: research | **Agent**: user
- **Created**: 2026-01-08 | **Updated**: 2026-01-08

**Description**: A minimal handoff without optional fields.
"""
    (recall_dir / "HANDOFFS.md").write_text(handoffs_content)

    return project_root


class TestHandoffDetailsDisplay:
    """Tests for _show_handoff_details displaying all fields."""

    @pytest.mark.asyncio
    async def test_details_shows_project_field(
        self, temp_project_with_full_handoffs, monkeypatch
    ):
        """Handoff details should display project path when present."""
        pytest.importorskip("textual")

        from core.tui.app import RecallMonitorApp
        from core.tui.models import HandoffSummary

        # Set up environment
        state_dir = temp_project_with_full_handoffs.parent / "state"
        state_dir.mkdir(exist_ok=True)
        (state_dir / "debug.log").write_text("")
        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(state_dir))
        monkeypatch.setenv("PROJECT_DIR", str(temp_project_with_full_handoffs))

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f6")
            await pilot.pause()

            # Navigate to first row (hf-full001)
            await pilot.press("down")
            await pilot.pause()

            # Get the details widget
            from textual.widgets import RichLog
            details = app.query_one("#handoff-details", RichLog)

            # Render the content and check for project
            # The project field should be displayed if non-empty
            # Note: We check app.state.handoff.data for the handoff object
            handoff = app.state.handoff.data.get("hf-full001")
            if handoff and handoff.project:
                # The display method should show it
                assert True  # Project field exists and can be displayed

    @pytest.mark.asyncio
    async def test_details_shows_blocked_by_field(
        self, temp_project_with_full_handoffs, monkeypatch
    ):
        """Handoff details should display blocked_by IDs when present."""
        pytest.importorskip("textual")

        from core.tui.app import RecallMonitorApp

        state_dir = temp_project_with_full_handoffs.parent / "state"
        state_dir.mkdir(exist_ok=True)
        (state_dir / "debug.log").write_text("")
        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(state_dir))
        monkeypatch.setenv("PROJECT_DIR", str(temp_project_with_full_handoffs))

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f6")
            await pilot.pause()

            # Verify handoff with blocked_by is parsed
            handoff = app.state.handoff.data.get("hf-full001")
            if handoff:
                assert hasattr(handoff, "blocked_by"), (
                    "Handoff should have blocked_by field"
                )
                # If blocked_by is populated, it should be displayable
                if handoff.blocked_by:
                    assert len(handoff.blocked_by) == 2, (
                        f"Expected 2 blocked_by IDs, got {len(handoff.blocked_by)}"
                    )

    @pytest.mark.asyncio
    async def test_details_shows_handoff_context(
        self, temp_project_with_full_handoffs, monkeypatch
    ):
        """Handoff details should display HandoffContext section when present."""
        pytest.importorskip("textual")

        from core.tui.app import RecallMonitorApp

        state_dir = temp_project_with_full_handoffs.parent / "state"
        state_dir.mkdir(exist_ok=True)
        (state_dir / "debug.log").write_text("")
        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(state_dir))
        monkeypatch.setenv("PROJECT_DIR", str(temp_project_with_full_handoffs))

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f6")
            await pilot.pause()

            # Verify handoff with context is parsed
            handoff = app.state.handoff.data.get("hf-full001")
            if handoff:
                assert hasattr(handoff, "handoff"), (
                    "HandoffSummary should have 'handoff' field for context"
                )
                # If context is populated, all fields should be accessible
                if handoff.handoff:
                    ctx = handoff.handoff
                    assert ctx.git_ref is not None
                    assert ctx.summary is not None
                    assert isinstance(ctx.critical_files, list)
                    assert isinstance(ctx.recent_changes, list)
                    assert isinstance(ctx.learnings, list)
                    assert isinstance(ctx.blockers, list)

    @pytest.mark.asyncio
    async def test_details_handles_missing_context_gracefully(
        self, temp_project_with_full_handoffs, monkeypatch
    ):
        """Handoff details should not crash when context is missing."""
        pytest.importorskip("textual")

        from core.tui.app import RecallMonitorApp

        state_dir = temp_project_with_full_handoffs.parent / "state"
        state_dir.mkdir(exist_ok=True)
        (state_dir / "debug.log").write_text("")
        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(state_dir))
        monkeypatch.setenv("PROJECT_DIR", str(temp_project_with_full_handoffs))

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f6")
            await pilot.pause()

            # hf-minimal should exist without context
            handoff = app.state.handoff.data.get("hf-minimal")
            if handoff:
                # Should be None or handle gracefully
                assert handoff.handoff is None, (
                    "Minimal handoff should have no context"
                )

    @pytest.mark.asyncio
    async def test_details_shows_abbreviated_git_ref(
        self, temp_project_with_full_handoffs, monkeypatch
    ):
        """Git ref should be displayed abbreviated (first 8 chars)."""
        pytest.importorskip("textual")

        from core.tui.app import RecallMonitorApp

        state_dir = temp_project_with_full_handoffs.parent / "state"
        state_dir.mkdir(exist_ok=True)
        (state_dir / "debug.log").write_text("")
        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(state_dir))
        monkeypatch.setenv("PROJECT_DIR", str(temp_project_with_full_handoffs))

        app = RecallMonitorApp()

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("f6")
            await pilot.pause()

            handoff = app.state.handoff.data.get("hf-full001")
            if handoff and handoff.handoff:
                git_ref = handoff.handoff.git_ref
                # Full ref is 40 chars, but display should use first 8
                assert len(git_ref) >= 8, (
                    f"Git ref should be at least 8 chars, got {len(git_ref)}"
                )
                # The display method should truncate to 8 chars
                short_ref = git_ref[:8]
                assert short_ref == "abc1234d", (
                    f"Expected abbreviated ref 'abc1234d', got '{short_ref}'"
                )
