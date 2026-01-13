#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Tests for TUI analytics module.

Test-first development: these tests define the expected behavior
of the HandoffAnalytics class before implementation.
"""

import pytest
from datetime import date


class TestLessonCounts:
    """Tests for compute_lesson_counts function."""

    def test_compute_lesson_counts_empty_list(self):
        """Empty list returns zero counts."""
        from core.tui.analytics import HandoffAnalytics

        result = HandoffAnalytics.compute_lesson_counts([])

        assert result == {"system": 0, "project": 0, "total": 0}

    def test_compute_lesson_counts_system_only(self):
        """List with only system lessons counts correctly."""
        from core.tui.analytics import HandoffAnalytics
        from core.tui.models import LessonSummary

        lessons = [
            LessonSummary(id="S001", level="system", title="System 1", uses=5, velocity=1.0),
            LessonSummary(id="S002", level="system", title="System 2", uses=3, velocity=0.5),
        ]

        result = HandoffAnalytics.compute_lesson_counts(lessons)

        assert result["system"] == 2
        assert result["project"] == 0
        assert result["total"] == 2

    def test_compute_lesson_counts_project_only(self):
        """List with only project lessons counts correctly."""
        from core.tui.analytics import HandoffAnalytics
        from core.tui.models import LessonSummary

        lessons = [
            LessonSummary(id="L001", level="project", title="Project 1", uses=10, velocity=2.0),
        ]

        result = HandoffAnalytics.compute_lesson_counts(lessons)

        assert result["system"] == 0
        assert result["project"] == 1
        assert result["total"] == 1

    def test_compute_lesson_counts_mixed(self):
        """Mixed system and project lessons count correctly."""
        from core.tui.analytics import HandoffAnalytics
        from core.tui.models import LessonSummary

        lessons = [
            LessonSummary(id="S001", level="system", title="System 1", uses=5, velocity=1.0),
            LessonSummary(id="L001", level="project", title="Project 1", uses=10, velocity=2.0),
            LessonSummary(id="L002", level="project", title="Project 2", uses=8, velocity=1.5),
            LessonSummary(id="S002", level="system", title="System 2", uses=3, velocity=0.5),
        ]

        result = HandoffAnalytics.compute_lesson_counts(lessons)

        assert result["system"] == 2
        assert result["project"] == 2
        assert result["total"] == 4


class TestHandoffCounts:
    """Tests for compute_handoff_counts function."""

    def test_compute_handoff_counts_empty_list(self):
        """Empty list returns empty dict."""
        from core.tui.analytics import HandoffAnalytics

        result = HandoffAnalytics.compute_handoff_counts([])

        assert result == {}

    def test_compute_handoff_counts_single_status(self):
        """Single status counted correctly."""
        from core.tui.analytics import HandoffAnalytics
        from core.tui.models import HandoffSummary

        handoffs = [
            HandoffSummary(
                id="hf-abc123", title="Task 1", status="in_progress",
                phase="implementing", created="2025-01-01", updated="2025-01-10"
            ),
        ]

        result = HandoffAnalytics.compute_handoff_counts(handoffs)

        assert result == {"in_progress": 1}

    def test_compute_handoff_counts_multiple_statuses(self):
        """Multiple statuses counted correctly."""
        from core.tui.analytics import HandoffAnalytics
        from core.tui.models import HandoffSummary

        handoffs = [
            HandoffSummary(
                id="hf-abc123", title="Task 1", status="in_progress",
                phase="implementing", created="2025-01-01", updated="2025-01-10"
            ),
            HandoffSummary(
                id="hf-def456", title="Task 2", status="blocked",
                phase="research", created="2025-01-02", updated="2025-01-09"
            ),
            HandoffSummary(
                id="hf-ghi789", title="Task 3", status="in_progress",
                phase="planning", created="2025-01-03", updated="2025-01-08"
            ),
            HandoffSummary(
                id="hf-jkl012", title="Task 4", status="completed",
                phase="review", created="2025-01-04", updated="2025-01-07"
            ),
        ]

        result = HandoffAnalytics.compute_handoff_counts(handoffs)

        assert result["in_progress"] == 2
        assert result["blocked"] == 1
        assert result["completed"] == 1

    def test_compute_handoff_counts_unknown_status(self):
        """Unknown status falls back to 'unknown'."""
        from core.tui.analytics import HandoffAnalytics
        from core.tui.models import HandoffSummary

        handoffs = [
            HandoffSummary(
                id="hf-abc123", title="Task 1", status="",
                phase="implementing", created="2025-01-01", updated="2025-01-10"
            ),
        ]

        result = HandoffAnalytics.compute_handoff_counts(handoffs)

        assert result == {"unknown": 1}


class TestHandoffStats:
    """Tests for compute_handoff_stats function."""

    def test_compute_handoff_stats_empty_list(self):
        """Empty list returns zeroed stats."""
        from core.tui.analytics import HandoffAnalytics

        result = HandoffAnalytics.compute_handoff_stats([])

        assert result["total_count"] == 0
        assert result["active_count"] == 0
        assert result["blocked_count"] == 0
        assert result["stale_count"] == 0
        assert result["by_status"] == {}
        assert result["by_phase"] == {}
        assert result["age_stats"]["min_age_days"] == 0
        assert result["age_stats"]["max_age_days"] == 0
        assert result["age_stats"]["avg_age_days"] == 0.0

    def test_compute_handoff_stats_single_handoff(self):
        """Single handoff stats computed correctly."""
        from core.tui.analytics import HandoffAnalytics
        from core.tui.models import HandoffSummary

        handoffs = [
            HandoffSummary(
                id="hf-abc123", title="Task 1", status="in_progress",
                phase="implementing", created="2025-01-01", updated="2025-01-10"
            ),
        ]

        result = HandoffAnalytics.compute_handoff_stats(handoffs)

        assert result["total_count"] == 1
        assert result["active_count"] == 1
        assert result["blocked_count"] == 0
        assert result["by_status"] == {"in_progress": 1}
        assert result["by_phase"] == {"implementing": 1}

    def test_compute_handoff_stats_blocked_handoffs(self):
        """Blocked handoffs counted correctly."""
        from core.tui.analytics import HandoffAnalytics
        from core.tui.models import HandoffSummary

        handoffs = [
            HandoffSummary(
                id="hf-abc123", title="Task 1", status="blocked",
                phase="implementing", created="2025-01-01", updated="2025-01-10"
            ),
            HandoffSummary(
                id="hf-def456", title="Task 2", status="blocked",
                phase="research", created="2025-01-02", updated="2025-01-09"
            ),
            HandoffSummary(
                id="hf-ghi789", title="Task 3", status="in_progress",
                phase="planning", created="2025-01-03", updated="2025-01-08"
            ),
        ]

        result = HandoffAnalytics.compute_handoff_stats(handoffs)

        assert result["blocked_count"] == 2

    def test_compute_handoff_stats_completed_not_active(self):
        """Completed handoffs not counted as active."""
        from core.tui.analytics import HandoffAnalytics
        from core.tui.models import HandoffSummary

        handoffs = [
            HandoffSummary(
                id="hf-abc123", title="Task 1", status="completed",
                phase="review", created="2025-01-01", updated="2025-01-10"
            ),
            HandoffSummary(
                id="hf-def456", title="Task 2", status="in_progress",
                phase="implementing", created="2025-01-02", updated="2025-01-09"
            ),
        ]

        result = HandoffAnalytics.compute_handoff_stats(handoffs)

        assert result["total_count"] == 2
        assert result["active_count"] == 1

    def test_compute_handoff_stats_phase_counts(self):
        """Phase counts computed correctly."""
        from core.tui.analytics import HandoffAnalytics
        from core.tui.models import HandoffSummary

        handoffs = [
            HandoffSummary(
                id="hf-abc123", title="Task 1", status="in_progress",
                phase="implementing", created="2025-01-01", updated="2025-01-10"
            ),
            HandoffSummary(
                id="hf-def456", title="Task 2", status="in_progress",
                phase="research", created="2025-01-02", updated="2025-01-09"
            ),
            HandoffSummary(
                id="hf-ghi789", title="Task 3", status="in_progress",
                phase="implementing", created="2025-01-03", updated="2025-01-08"
            ),
        ]

        result = HandoffAnalytics.compute_handoff_stats(handoffs)

        assert result["by_phase"]["implementing"] == 2
        assert result["by_phase"]["research"] == 1

    def test_compute_handoff_stats_stale_count(self):
        """Stale handoffs (7+ days since update) counted correctly."""
        from core.tui.analytics import HandoffAnalytics
        from core.tui.models import HandoffSummary

        today = date.today().isoformat()
        old_date = "2020-01-01"  # Definitely stale

        handoffs = [
            HandoffSummary(
                id="hf-abc123", title="Fresh", status="in_progress",
                phase="implementing", created=today, updated=today
            ),
            HandoffSummary(
                id="hf-def456", title="Stale", status="in_progress",
                phase="implementing", created=old_date, updated=old_date
            ),
        ]

        result = HandoffAnalytics.compute_handoff_stats(handoffs)

        assert result["stale_count"] == 1


class TestFlowMetrics:
    """Tests for compute_flow_metrics function (handoff lifecycle health)."""

    def test_compute_flow_metrics_empty_list(self):
        """Empty list returns zeroed flow metrics."""
        from core.tui.analytics import HandoffAnalytics, HandoffFlowMetrics

        result = HandoffAnalytics.compute_flow_metrics([])

        assert isinstance(result, HandoffFlowMetrics)
        assert result.total == 0
        assert result.by_status == {}
        assert result.by_phase == {}
        assert result.avg_cycle_days == 0.0
        assert result.blocked_over_threshold == []
        assert result.completion_rate == 0.0

    def test_compute_flow_metrics_status_distribution(self):
        """Status distribution (funnel) computed correctly."""
        from core.tui.analytics import HandoffAnalytics
        from core.tui.models import HandoffSummary

        handoffs = [
            HandoffSummary(
                id="hf-001", title="Task 1", status="not_started",
                phase="research", created="2025-01-01", updated="2025-01-01"
            ),
            HandoffSummary(
                id="hf-002", title="Task 2", status="in_progress",
                phase="implementing", created="2025-01-02", updated="2025-01-05"
            ),
            HandoffSummary(
                id="hf-003", title="Task 3", status="in_progress",
                phase="planning", created="2025-01-03", updated="2025-01-06"
            ),
            HandoffSummary(
                id="hf-004", title="Task 4", status="completed",
                phase="review", created="2025-01-04", updated="2025-01-10"
            ),
        ]

        result = HandoffAnalytics.compute_flow_metrics(handoffs)

        assert result.by_status["not_started"] == 1
        assert result.by_status["in_progress"] == 2
        assert result.by_status["completed"] == 1

    def test_compute_flow_metrics_phase_distribution(self):
        """Phase distribution excludes completed handoffs."""
        from core.tui.analytics import HandoffAnalytics
        from core.tui.models import HandoffSummary

        handoffs = [
            HandoffSummary(
                id="hf-001", title="Task 1", status="in_progress",
                phase="research", created="2025-01-01", updated="2025-01-01"
            ),
            HandoffSummary(
                id="hf-002", title="Task 2", status="in_progress",
                phase="implementing", created="2025-01-02", updated="2025-01-05"
            ),
            HandoffSummary(
                id="hf-003", title="Task 3", status="blocked",
                phase="implementing", created="2025-01-03", updated="2025-01-06"
            ),
            HandoffSummary(
                id="hf-004", title="Task 4", status="completed",
                phase="review", created="2025-01-04", updated="2025-01-10"
            ),
        ]

        result = HandoffAnalytics.compute_flow_metrics(handoffs)

        # Completed should not be counted in phase distribution
        assert result.by_phase["research"] == 1
        assert result.by_phase["implementing"] == 2
        assert "review" not in result.by_phase  # Completed handoff's phase not counted

    def test_compute_flow_metrics_avg_cycle_time(self):
        """Average cycle time computed for completed handoffs only."""
        from core.tui.analytics import HandoffAnalytics
        from core.tui.models import HandoffSummary

        handoffs = [
            # 5 days to complete (Jan 1 -> Jan 6)
            HandoffSummary(
                id="hf-001", title="Task 1", status="completed",
                phase="review", created="2025-01-01", updated="2025-01-06"
            ),
            # 10 days to complete (Jan 2 -> Jan 12)
            HandoffSummary(
                id="hf-002", title="Task 2", status="completed",
                phase="review", created="2025-01-02", updated="2025-01-12"
            ),
            # Not completed, should be excluded
            HandoffSummary(
                id="hf-003", title="Task 3", status="in_progress",
                phase="implementing", created="2025-01-03", updated="2025-01-06"
            ),
        ]

        result = HandoffAnalytics.compute_flow_metrics(handoffs)

        # Average of 5 and 10 = 7.5 days
        assert result.avg_cycle_days == 7.5

    def test_compute_flow_metrics_blocked_alerts(self):
        """Blocked alerts flag handoffs blocked > threshold days."""
        from core.tui.analytics import HandoffAnalytics
        from core.tui.models import HandoffSummary

        old_date = "2020-01-01"  # Very old, definitely > 3 days
        today = date.today().isoformat()

        handoffs = [
            # Blocked for a long time
            HandoffSummary(
                id="hf-001", title="Long blocked", status="blocked",
                phase="implementing", created=old_date, updated=old_date
            ),
            # Recently blocked (should not trigger alert)
            HandoffSummary(
                id="hf-002", title="Recent blocked", status="blocked",
                phase="research", created=today, updated=today
            ),
            # Not blocked (should not appear)
            HandoffSummary(
                id="hf-003", title="Active", status="in_progress",
                phase="planning", created=old_date, updated=old_date
            ),
        ]

        result = HandoffAnalytics.compute_flow_metrics(handoffs)

        # Only hf-001 should be in blocked_over_threshold
        assert len(result.blocked_over_threshold) == 1
        assert result.blocked_over_threshold[0][0] == "hf-001"
        assert result.blocked_over_threshold[0][2] > 3  # Days blocked > 3

    def test_compute_flow_metrics_completion_rate(self):
        """Completion rate computed as completed / total."""
        from core.tui.analytics import HandoffAnalytics
        from core.tui.models import HandoffSummary

        handoffs = [
            HandoffSummary(
                id="hf-001", title="Task 1", status="completed",
                phase="review", created="2025-01-01", updated="2025-01-06"
            ),
            HandoffSummary(
                id="hf-002", title="Task 2", status="completed",
                phase="review", created="2025-01-02", updated="2025-01-12"
            ),
            HandoffSummary(
                id="hf-003", title="Task 3", status="in_progress",
                phase="implementing", created="2025-01-03", updated="2025-01-06"
            ),
            HandoffSummary(
                id="hf-004", title="Task 4", status="not_started",
                phase="research", created="2025-01-04", updated="2025-01-04"
            ),
        ]

        result = HandoffAnalytics.compute_flow_metrics(handoffs)

        # 2 completed out of 4 total = 0.5
        assert result.completion_rate == 0.5

    def test_compute_flow_metrics_counts(self):
        """Active and blocked counts included."""
        from core.tui.analytics import HandoffAnalytics
        from core.tui.models import HandoffSummary

        handoffs = [
            HandoffSummary(
                id="hf-001", title="Task 1", status="in_progress",
                phase="implementing", created="2025-01-01", updated="2025-01-06"
            ),
            HandoffSummary(
                id="hf-002", title="Task 2", status="blocked",
                phase="research", created="2025-01-02", updated="2025-01-05"
            ),
            HandoffSummary(
                id="hf-003", title="Task 3", status="completed",
                phase="review", created="2025-01-03", updated="2025-01-10"
            ),
        ]

        result = HandoffAnalytics.compute_flow_metrics(handoffs)

        assert result.total == 3
        assert result.active_count == 2  # in_progress + blocked
        assert result.blocked_count == 1

    def test_compute_flow_metrics_malformed_dates(self):
        """Malformed dates handled gracefully."""
        from core.tui.analytics import HandoffAnalytics
        from core.tui.models import HandoffSummary

        handoffs = [
            HandoffSummary(
                id="hf-001", title="Bad dates", status="completed",
                phase="review", created="invalid", updated="also-invalid",
            ),
        ]
        result = HandoffAnalytics.compute_flow_metrics(handoffs)
        assert result.avg_cycle_days == 0.0
        assert result.completion_rate == 1.0  # Still counts as completed

    def test_compute_flow_metrics_datetime_strings(self):
        """Datetime strings with time component handled correctly."""
        from core.tui.analytics import HandoffAnalytics
        from core.tui.models import HandoffSummary

        handoffs = [
            HandoffSummary(
                id="hf-001", title="Task 1", status="completed",
                phase="review", created="2025-01-01T10:30:00", updated="2025-01-05T14:00:00",
            ),
        ]
        result = HandoffAnalytics.compute_flow_metrics(handoffs)
        assert result.avg_cycle_days == 4.0
