#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Statistics aggregator for the TUI debug viewer.

Computes system health metrics from buffered log events.
"""

import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional

try:
    from core.tui.log_reader import LogReader, format_event_line
    from core.tui.models import DebugEvent, EventType, SystemStats
except ImportError:
    from .log_reader import LogReader, format_event_line
    from .models import DebugEvent, EventType, SystemStats

if TYPE_CHECKING:
    from .state_reader import StateReader

# -----------------------------------------------------------------------------
# Configuration Constants
# -----------------------------------------------------------------------------

# Cache TTL for computed statistics (seconds)
STATS_CACHE_TTL_SECONDS: float = 1.0

# Health status thresholds (milliseconds)
HEALTH_OK_THRESHOLD_MS: float = 100.0  # Below this avg_hook_ms: OK
HEALTH_WARNING_THRESHOLD_MS: float = 200.0  # Above this avg_hook_ms: WARNING

# Health status labels
HEALTH_STATUS_OK = "OK"
HEALTH_STATUS_WARNING = "WARNING"
HEALTH_STATUS_DEGRADED = "DEGRADED"


class StatsAggregator:
    """
    Aggregates statistics from debug log events.

    Computes metrics like session counts, error counts, and hook timing
    percentiles from the LogReader event buffer.

    Attributes:
        log_reader: LogReader instance to get events from
        state_reader: StateReader instance for lessons/handoffs state
    """

    def __init__(
        self,
        log_reader: LogReader,
        state_reader: Optional["StateReader"] = None,
    ) -> None:
        """
        Initialize the stats aggregator.

        Args:
            log_reader: LogReader instance to read events from
            state_reader: StateReader for lessons/handoffs (optional)
        """
        self.log_reader = log_reader
        self.state_reader = state_reader
        self._cached_stats: Optional[SystemStats] = None
        self._cache_time: float = 0.0
        self._cache_ttl: float = STATS_CACHE_TTL_SECONDS

    def _extract_hook_timing(self, event: DebugEvent) -> Optional[float]:
        """
        Extract hook timing from a timing event.

        Args:
            event: A timing-related debug event

        Returns:
            Timing in milliseconds, or None if not a timing event
        """
        if event.event == EventType.HOOK_END:
            return event.get("total_ms")
        elif event.event == EventType.TIMING:
            return event.get("ms")
        elif event.event == EventType.HOOK_PHASE:
            return event.get("ms")
        return None

    def _percentile(self, values: List[float], p: float) -> float:
        """
        Calculate the p-th percentile of a list of values.

        Args:
            values: List of numeric values
            p: Percentile to calculate (0-100)

        Returns:
            The p-th percentile value
        """
        if not values:
            return 0.0

        sorted_values = sorted(values)
        n = len(sorted_values)
        k = (n - 1) * p / 100
        f = int(k)
        c = f + 1

        if c >= n:
            return sorted_values[-1]

        return sorted_values[f] + (k - f) * (sorted_values[c] - sorted_values[f])

    def compute(self) -> SystemStats:
        """
        Compute aggregated statistics from buffered events.

        Returns:
            SystemStats with computed metrics
        """
        # Check cache first
        now = time.time()
        if self._cached_stats and (now - self._cache_time) < self._cache_ttl:
            return self._cached_stats

        # Ensure buffer is loaded
        self.log_reader.load_buffer()
        events = list(self.log_reader.iter_events())

        # Rolling 24-hour window for "today's" stats
        cutoff_24h = datetime.now(timezone.utc) - timedelta(hours=24)

        # Use Counter for efficient counting
        events_by_type: Counter = Counter(e.event for e in events)
        events_by_project: Counter = Counter(e.project for e in events if e.project)

        # Initialize counters for today events
        sessions_today = 0
        citations_today = 0
        errors_today = 0
        all_hook_timings: List[float] = []
        hook_timings: Dict[str, List[float]] = defaultdict(list)

        # Process events
        for event in events:
            # Check if event is within rolling 24-hour window
            is_recent = event.timestamp_dt and event.timestamp_dt >= cutoff_24h

            if event.event == EventType.SESSION_START and is_recent:
                sessions_today += 1

            if event.event == EventType.CITATION and is_recent:
                citations_today += 1

            if event.is_error and is_recent:
                errors_today += 1

            # Collect timing data (also filtered to rolling 24h window)
            if event.is_timing and is_recent:
                timing = self._extract_hook_timing(event)
                if timing is not None:
                    all_hook_timings.append(timing)

                    # Group by hook name
                    hook_name = event.get("hook") or event.get("op") or "unknown"
                    hook_timings[hook_name].append(timing)

        # Calculate timing statistics
        avg_hook_ms = 0.0
        p95_hook_ms = 0.0
        max_hook_ms = 0.0

        if all_hook_timings:
            avg_hook_ms = sum(all_hook_timings) / len(all_hook_timings)
            p95_hook_ms = self._percentile(all_hook_timings, 95)
            max_hook_ms = max(all_hook_timings)

        # Get log file size
        log_size_bytes = self.log_reader.get_log_size_bytes()
        log_size_mb = log_size_bytes / (1024 * 1024)

        result = SystemStats(
            sessions_today=sessions_today,
            citations_today=citations_today,
            errors_today=errors_today,
            avg_hook_ms=round(avg_hook_ms, 2),
            p95_hook_ms=round(p95_hook_ms, 2),
            max_hook_ms=round(max_hook_ms, 2),
            log_size_mb=round(log_size_mb, 2),
            log_line_count=len(events),
            events_by_type=dict(events_by_type),
            events_by_project=dict(events_by_project),
            hook_timings=dict(hook_timings),
        )

        # Cache the result
        self._cached_stats = result
        self._cache_time = now
        return result

    def invalidate_cache(self) -> None:
        """Force cache invalidation."""
        self._cached_stats = None

    def compute_session_stats(self, session_id: str) -> Dict[str, Any]:
        """
        Compute statistics for a specific session.

        Args:
            session_id: Session ID to analyze

        Returns:
            Dict with session-specific metrics including:
            - session_id, event_count, errors, citations, duration_ms, project
            - first_event_time: datetime or None
            - last_event_time: datetime or None
            - tokens: int from session_start event's total_tokens
        """
        events = self.log_reader.filter_by_session(session_id)

        if not events:
            return {
                "session_id": session_id,
                "event_count": 0,
                "errors": 0,
                "citations": 0,
                "duration_ms": 0,
                "project": "",
                "first_event_time": None,
                "last_event_time": None,
                "tokens": 0,
            }

        citations = sum(1 for e in events if e.event == EventType.CITATION)
        errors = sum(1 for e in events if e.is_error)

        # Calculate timestamps from events
        timestamps = [e.timestamp_dt for e in events if e.timestamp_dt]
        first_event_time = min(timestamps) if timestamps else None
        last_event_time = max(timestamps) if timestamps else None

        # Calculate duration from first to last event
        if len(timestamps) >= 2:
            duration = (last_event_time - first_event_time).total_seconds() * 1000
        else:
            duration = 0

        # Extract tokens from session_start event
        tokens = 0
        has_session_start = False
        for e in events:
            if e.event == EventType.SESSION_START:
                has_session_start = True
                tokens = e.get("total_tokens", 0)
                break

        return {
            "session_id": session_id,
            "event_count": len(events),
            "errors": errors,
            "citations": citations,
            "duration_ms": round(duration, 2),
            "project": events[0].project if events else "",
            "first_event_time": first_event_time,
            "last_event_time": last_event_time,
            "tokens": tokens,
            "has_session_start": has_session_start,
        }

    def compute_project_stats(self, project: str) -> Dict[str, Any]:
        """
        Compute statistics for a specific project.

        Args:
            project: Project name to analyze

        Returns:
            Dict with project-specific metrics
        """
        events = self.log_reader.filter_by_project(project)

        if not events:
            return {
                "project": project,
                "event_count": 0,
                "errors": 0,
                "citations": 0,
                "sessions": 0,
            }

        citations = sum(1 for e in events if e.event == EventType.CITATION)
        errors = sum(1 for e in events if e.is_error)
        sessions = len(set(e.session_id for e in events if e.session_id))

        return {
            "project": project,
            "event_count": len(events),
            "errors": errors,
            "citations": citations,
            "sessions": sessions,
        }

    def get_recent_errors(self, limit: int = 10) -> List[DebugEvent]:
        """
        Get the most recent error events.

        Args:
            limit: Maximum number of errors to return

        Returns:
            List of error events, most recent first
        """
        self.log_reader.load_buffer()
        errors = [e for e in self.log_reader.iter_events() if e.is_error]
        return list(reversed(errors[-limit:]))

    def get_timing_summary(self, stats: Optional[SystemStats] = None) -> Dict[str, Dict[str, float]]:
        """
        Get timing summary by hook/operation.

        Args:
            stats: Pre-computed SystemStats to avoid redundant compute() call.
                   If None, will call compute() to get fresh stats.

        Returns:
            Dict mapping hook name to timing stats (avg, p95, max, count)
        """
        if stats is None:
            stats = self.compute()
        summary = {}

        for hook, timings in stats.hook_timings.items():
            if timings:
                summary[hook] = {
                    "avg_ms": round(sum(timings) / len(timings), 2),
                    "p95_ms": round(self._percentile(timings, 95), 2),
                    "max_ms": round(max(timings), 2),
                    "count": len(timings),
                }

        return summary

    def format_summary(
        self,
        project: Optional[str] = None,
        limit: int = 10,
    ) -> str:
        """
        Format a text summary of system stats.

        Args:
            project: Filter to specific project (optional)
            limit: Number of recent events to show

        Returns:
            Multi-line string with formatted statistics
        """
        stats = self.compute()

        lines = [
            "=== Claude Recall Status ===",
            f"Sessions today: {stats.sessions_today} | Citations: {stats.citations_today} | Errors: {stats.errors_today}",
            "",
        ]

        # Health status
        if stats.errors_today == 0 and stats.avg_hook_ms < HEALTH_OK_THRESHOLD_MS:
            health = HEALTH_STATUS_OK
        elif stats.errors_today > 0 or stats.avg_hook_ms > HEALTH_WARNING_THRESHOLD_MS:
            health = HEALTH_STATUS_WARNING
        else:
            health = HEALTH_STATUS_DEGRADED

        lines.append(f"HEALTH: {health} (avg hook: {stats.avg_hook_ms:.0f}ms, p95: {stats.p95_hook_ms:.0f}ms)")
        lines.append(f"Log: {stats.log_size_mb:.1f}MB ({stats.log_line_count} events buffered)")
        lines.append("")

        # Recent events
        events = self.log_reader.read_recent(limit)
        if project:
            events = [e for e in events if e.project == project]

        if events:
            lines.append(f"RECENT ({len(events)} events):")
            for event in events:
                lines.append("  " + format_event_line(event, color=True))
            lines.append("")

        # State info if available
        if self.state_reader:
            try:
                lesson_counts = self.state_reader.get_lesson_counts()
                lines.append(
                    f"LESSONS: {lesson_counts.get('system', 0)}S / {lesson_counts.get('project', 0)}L"
                )

                handoffs = self.state_reader.get_active_handoffs()
                if handoffs:
                    lines.append(f"HANDOFFS ({len(handoffs)} active):")
                    for h in handoffs[:5]:
                        lines.append(f"  [{h.id}] {h.title} ({h.status}, {h.phase})")
            except Exception:
                pass  # State reader errors should not break summary

        lines.append("")

        # Event breakdown
        if stats.events_by_type:
            type_str = ", ".join(f"{t}: {c}" for t, c in sorted(stats.events_by_type.items()))
            lines.append(f"Events: {type_str}")

        # Project breakdown
        if stats.events_by_project:
            proj_str = ", ".join(
                f"{p}: {c}"
                for p, c in sorted(stats.events_by_project.items(), key=lambda x: -x[1])[:5]
            )
            lines.append(f"Projects: {proj_str}")

        return "\n".join(lines)
