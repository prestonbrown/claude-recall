#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Data models for the TUI debug viewer.

Defines dataclasses for events, statistics, and state summaries.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional


class EventType:
    """Constants for event types in debug logs."""

    SESSION_START = "session_start"
    CITATION = "citation"
    ERROR = "error"
    TIMING = "timing"
    HOOK_START = "hook_start"
    HOOK_END = "hook_end"
    HOOK_PHASE = "hook_phase"
    DECAY_RESULT = "decay_result"
    HANDOFF_CREATED = "handoff_created"
    HANDOFF_CHANGE = "handoff_change"
    HANDOFF_COMPLETED = "handoff_completed"
    LESSON_ADDED = "lesson_added"


@dataclass
class DebugEvent:
    """
    A single debug event from the log file.

    Parsed from JSON lines in debug.log. The raw dict preserves
    all fields for detailed inspection.

    Attributes:
        event: Event type (e.g., 'session_start', 'citation', 'error')
        level: Log level ('info', 'debug', 'trace', 'error')
        timestamp: ISO timestamp string
        session_id: Session identifier for correlation
        pid: Process ID
        project: Project name (from PROJECT_DIR env var)
        raw: Full parsed JSON dict with all event-specific fields
    """

    event: str
    level: str
    timestamp: str
    session_id: str
    pid: int
    project: str
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def timestamp_dt(self) -> Optional[datetime]:
        """Parse timestamp string to datetime object."""
        if not self.timestamp:
            return None
        try:
            # Handle ISO format with Z suffix
            ts = self.timestamp.replace("Z", "+00:00")
            return datetime.fromisoformat(ts)
        except ValueError:
            return None

    @property
    def is_error(self) -> bool:
        """Check if this is an error event."""
        return self.level == "error" or self.event == "error"

    @property
    def is_timing(self) -> bool:
        """Check if this is a timing/performance event."""
        return self.event in (
            EventType.TIMING,
            EventType.HOOK_START,
            EventType.HOOK_END,
            EventType.HOOK_PHASE,
        )

    def get(self, key: str, default: Any = None) -> Any:
        """Get a field from the raw event data."""
        return self.raw.get(key, default)


@dataclass
class SystemStats:
    """
    Aggregated system statistics for the health dashboard.

    Computed from buffered events in the log reader.

    Attributes:
        sessions_today: Number of session_start events today
        citations_today: Number of citation events today
        errors_today: Number of error events today
        avg_hook_ms: Average hook execution time in milliseconds
        p95_hook_ms: 95th percentile hook execution time
        max_hook_ms: Maximum hook execution time
        log_size_mb: Current log file size in megabytes
        log_line_count: Number of lines in the log buffer
        events_by_type: Count of events by type
        events_by_project: Count of events by project
        hook_timings: Dict mapping hook name to list of timing values
    """

    sessions_today: int = 0
    citations_today: int = 0
    errors_today: int = 0
    avg_hook_ms: float = 0.0
    p95_hook_ms: float = 0.0
    max_hook_ms: float = 0.0
    log_size_mb: float = 0.0
    log_line_count: int = 0
    events_by_type: Dict[str, int] = field(default_factory=dict)
    events_by_project: Dict[str, int] = field(default_factory=dict)
    hook_timings: Dict[str, List[float]] = field(default_factory=dict)


@dataclass
class LessonSummary:
    """
    Compact summary of a lesson for state overview.

    Derived from parsing LESSONS.md files.

    Attributes:
        id: Lesson ID (e.g., 'L001', 'S002')
        title: Lesson title
        uses: Total use count
        velocity: Recent activity velocity
        level: 'project' or 'system'
    """

    id: str
    title: str
    uses: int
    velocity: float
    level: str

    @property
    def is_system(self) -> bool:
        """Check if this is a system-level lesson."""
        return self.level == "system" or self.id.startswith("S")


@dataclass
class TriedStep:
    """Represents a tried step in a handoff with its outcome."""

    outcome: str  # success, fail, partial
    description: str


@dataclass
class HandoffContextSummary:
    """
    Rich context for session handoffs in TUI.

    Mirrors the HandoffContext from core.models for display purposes.

    Attributes:
        summary: 1-2 sentence progress summary
        critical_files: 2-3 most important file:line refs
        recent_changes: What was modified this session
        learnings: Discoveries/patterns found
        blockers: What's blocking progress
        git_ref: Commit hash at handoff time
    """

    summary: str
    critical_files: List[str]
    recent_changes: List[str]
    learnings: List[str]
    blockers: List[str]
    git_ref: str


@dataclass
class HandoffSummary:
    """
    Compact summary of a handoff for state overview.

    Derived from parsing HANDOFFS.md files.

    Attributes:
        id: Handoff ID (e.g., 'hf-a1b2c3d')
        title: Handoff title
        status: Current status (not_started, in_progress, blocked, ready_for_review, completed)
        phase: Current phase (research, planning, implementing, review)
        created: Creation date as ISO string (YYYY-MM-DD)
        updated: Last updated date as ISO string (YYYY-MM-DD)
        project: Project path
        agent: Agent type (user, explore, general-purpose, plan, review)
        description: Full description of the handoff
        tried_steps: List of attempted steps with outcomes
        next_steps: List of next steps to take
        refs: List of file:line references
        checkpoint: Current progress summary
        blocked_by: List of handoff IDs this depends on
        handoff: Rich context for session handoffs (HandoffContextSummary)
    """

    id: str
    title: str
    status: str
    phase: str
    created: str
    updated: str
    project: str = ""
    agent: str = "user"
    description: str = ""
    tried_steps: List[TriedStep] = field(default_factory=list)
    next_steps: List[str] = field(default_factory=list)
    refs: List[str] = field(default_factory=list)
    checkpoint: str = ""
    blocked_by: List[str] = field(default_factory=list)
    handoff: Optional[HandoffContextSummary] = None

    @property
    def is_active(self) -> bool:
        """Check if handoff is active (not completed)."""
        return self.status != "completed"

    @property
    def is_blocked(self) -> bool:
        """Check if handoff is blocked."""
        return self.status == "blocked"

    @property
    def age_days(self) -> int:
        """Calculate age in days since created date."""
        try:
            created_date = date.fromisoformat(self.created)
            return (date.today() - created_date).days
        except (ValueError, TypeError):
            return 0

    @property
    def updated_age_days(self) -> int:
        """Calculate days since last update."""
        try:
            updated_date = date.fromisoformat(self.updated)
            return (date.today() - updated_date).days
        except (ValueError, TypeError):
            return 0


@dataclass
class DecayInfo:
    """
    Decay state information.

    Attributes:
        last_decay_date: Date of last decay run as ISO string
        sessions_since_decay: Number of sessions since last decay
        decay_state_exists: Whether decay state file exists
    """

    last_decay_date: Optional[str] = None
    sessions_since_decay: int = 0
    decay_state_exists: bool = False
