#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Analytics computations for TUI state data.

Pure functions that operate on parsed data structures.
No file I/O or parsing logic here.
"""

from typing import Any, Dict, List

try:
    from core.tui.models import HandoffSummary, LessonSummary
except ImportError:
    from .models import HandoffSummary, LessonSummary


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
