#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Analytics computations for TUI state data.

Pure functions that operate on parsed data structures.
No file I/O or parsing logic here.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List

try:
    from core.tui.models import HandoffSummary, LessonSummary
except ImportError:
    from .models import HandoffSummary, LessonSummary


# Threshold for flagging handoffs blocked too long
BLOCKED_ALERT_THRESHOLD_DAYS = 3


@dataclass
class HandoffFlowMetrics:
    """Metrics for handoff lifecycle health.

    Provides visibility into handoff flow through the pipeline:
    - Status distribution (completion funnel)
    - Phase distribution (where work is piling up)
    - Cycle time (how long handoffs take to complete)
    - Blocked alerts (handoffs stuck too long)

    Attributes:
        total: Total number of handoffs
        by_status: Count by status (not_started, in_progress, blocked, ready_for_review, completed)
        by_phase: Count by phase (research, planning, implementing, review)
        avg_cycle_days: Average days from created to completed (for completed handoffs only)
        blocked_over_threshold: List of (id, title, days_blocked) for handoffs blocked > threshold
        completion_rate: Fraction of handoffs that are completed (0.0 to 1.0)
        active_count: Number of non-completed handoffs
        blocked_count: Number of blocked handoffs
    """

    total: int = 0
    by_status: Dict[str, int] = field(default_factory=dict)
    by_phase: Dict[str, int] = field(default_factory=dict)
    avg_cycle_days: float = 0.0
    blocked_over_threshold: List[tuple] = field(default_factory=list)
    completion_rate: float = 0.0
    active_count: int = 0
    blocked_count: int = 0


class HandoffAnalytics:
    """Pure computation on handoff/lesson data."""

    @staticmethod
    def compute_lesson_counts(lessons: List[LessonSummary]) -> Dict[str, int]:
        """Compute counts by level.

        Args:
            lessons: List of LessonSummary objects

        Returns:
            Dict with 'system', 'project', and 'total' counts
        """
        system_count = sum(1 for lesson in lessons if lesson.level == "system")
        project_count = sum(1 for lesson in lessons if lesson.level == "project")
        return {
            "system": system_count,
            "project": project_count,
            "total": len(lessons),
        }

    @staticmethod
    def compute_handoff_counts(handoffs: List[HandoffSummary]) -> Dict[str, int]:
        """Compute counts by status.

        Args:
            handoffs: List of HandoffSummary objects

        Returns:
            Dict mapping status to count (empty dict if no handoffs)
        """
        counts: Dict[str, int] = {}
        for handoff in handoffs:
            status = handoff.status if handoff.status else "unknown"
            counts[status] = counts.get(status, 0) + 1
        return counts

    @staticmethod
    def compute_handoff_stats(handoffs: List[HandoffSummary]) -> Dict[str, Any]:
        """Compute comprehensive handoff statistics.

        Args:
            handoffs: List of HandoffSummary objects

        Returns:
            Dict with computed statistics:
            - total_count: Total number of handoffs
            - active_count: Number of non-completed handoffs
            - blocked_count: Number of blocked handoffs
            - stale_count: Number of handoffs not updated in >7 days
            - by_status: Dict mapping status to count
            - by_phase: Dict mapping phase to count
            - age_stats: Dict with min_age_days, max_age_days, avg_age_days
        """
        if not handoffs:
            return {
                "total_count": 0,
                "active_count": 0,
                "blocked_count": 0,
                "stale_count": 0,
                "by_status": {},
                "by_phase": {},
                "age_stats": {
                    "min_age_days": 0,
                    "max_age_days": 0,
                    "avg_age_days": 0.0,
                },
            }

        # Count by status
        by_status: Dict[str, int] = {}
        for handoff in handoffs:
            by_status[handoff.status] = by_status.get(handoff.status, 0) + 1

        # Count by phase
        by_phase: Dict[str, int] = {}
        for handoff in handoffs:
            by_phase[handoff.phase] = by_phase.get(handoff.phase, 0) + 1

        # Age statistics
        ages = [handoff.age_days for handoff in handoffs]
        min_age = min(ages) if ages else 0
        max_age = max(ages) if ages else 0
        avg_age = sum(ages) / len(ages) if ages else 0.0

        # Stale count (7+ days since update)
        stale_count = sum(1 for handoff in handoffs if handoff.updated_age_days >= 7)

        return {
            "total_count": len(handoffs),
            "active_count": sum(1 for handoff in handoffs if handoff.is_active),
            "blocked_count": sum(1 for handoff in handoffs if handoff.is_blocked),
            "stale_count": stale_count,
            "by_status": by_status,
            "by_phase": by_phase,
            "age_stats": {
                "min_age_days": min_age,
                "max_age_days": max_age,
                "avg_age_days": avg_age,
            },
        }

    @staticmethod
    def compute_flow_metrics(
        handoffs: List[HandoffSummary],
        blocked_threshold_days: int = BLOCKED_ALERT_THRESHOLD_DAYS,
    ) -> HandoffFlowMetrics:
        """Compute handoff flow/lifecycle metrics.

        Provides visibility into handoff pipeline health:
        - Completion funnel (how many at each status)
        - Phase distribution (where work is piling up)
        - Cycle time (how long handoffs take to complete)
        - Blocked alerts (handoffs stuck too long)

        Args:
            handoffs: List of HandoffSummary objects
            blocked_threshold_days: Days blocked before flagging (default: 3)

        Returns:
            HandoffFlowMetrics with computed analytics
        """
        if not handoffs:
            return HandoffFlowMetrics()

        # Count by status
        by_status: Dict[str, int] = {}
        for handoff in handoffs:
            status = handoff.status if handoff.status else "unknown"
            by_status[status] = by_status.get(status, 0) + 1

        # Count by phase (only for non-completed handoffs)
        by_phase: Dict[str, int] = {}
        for handoff in handoffs:
            if handoff.status != "completed":
                phase = handoff.phase if handoff.phase else "unknown"
                by_phase[phase] = by_phase.get(phase, 0) + 1

        # Compute cycle time for completed handoffs
        completed_cycle_days = []
        for handoff in handoffs:
            if handoff.status == "completed":
                try:
                    created = date.fromisoformat(handoff.created[:10])  # Handle datetime strings
                    updated = date.fromisoformat(handoff.updated[:10])
                    cycle_days = (updated - created).days
                    # Only include non-negative cycle times
                    if cycle_days >= 0:
                        completed_cycle_days.append(cycle_days)
                except (ValueError, TypeError):
                    pass  # Skip malformed dates

        avg_cycle_days = (
            sum(completed_cycle_days) / len(completed_cycle_days)
            if completed_cycle_days
            else 0.0
        )

        # Find blocked handoffs over threshold
        blocked_over_threshold = []
        for handoff in handoffs:
            if handoff.status == "blocked":
                days_blocked = handoff.updated_age_days
                if days_blocked > blocked_threshold_days:
                    blocked_over_threshold.append(
                        (handoff.id, handoff.title, days_blocked)
                    )

        # Sort blocked by days (most blocked first)
        blocked_over_threshold.sort(key=lambda x: x[2], reverse=True)

        # Completion rate
        total = len(handoffs)
        completed_count = by_status.get("completed", 0)
        completion_rate = completed_count / total if total > 0 else 0.0

        # Active and blocked counts
        active_count = sum(1 for h in handoffs if h.status != "completed")
        blocked_count = by_status.get("blocked", 0)

        return HandoffFlowMetrics(
            total=total,
            by_status=by_status,
            by_phase=by_phase,
            avg_cycle_days=avg_cycle_days,
            blocked_over_threshold=blocked_over_threshold,
            completion_rate=completion_rate,
            active_count=active_count,
            blocked_count=blocked_count,
        )
