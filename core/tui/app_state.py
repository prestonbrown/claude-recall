# SPDX-License-Identifier: MIT
"""State management dataclasses for the TUI app.

This module provides structured state containers that replace scattered
instance variables in RecallMonitorApp. The dataclasses group related
state together semantically:

- SortState: Column and direction for table sorting
- SessionState: State for the sessions tab (sort, selection, view mode)
- HandoffState: State for the handoffs tab (sort, filter, selection, details)
- AppState: Top-level container for all app state
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set


@dataclass
class SortState:
    """Sorting state for tables.

    Tracks which column is sorted and in what direction.
    """

    column: Optional[str] = None
    reverse: bool = False


@dataclass
class SessionState:
    """State for the sessions tab.

    Groups all session-related state: current selection, sorting,
    view mode, and cached data.
    """

    current_id: Optional[str] = None
    user_selected_id: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)
    sort: SortState = field(default_factory=SortState)
    show_system: bool = False
    timeline_view: bool = False


@dataclass
class HandoffState:
    """State for the handoffs tab.

    Groups all handoff-related state: selection, sorting, filtering,
    completion toggle, and detail navigation state.
    """

    current_id: Optional[str] = None
    user_selected_id: Optional[str] = None
    enter_confirmed_id: Optional[str] = None
    displayed_id: Optional[str] = None  # Currently shown in details pane (for scroll preservation)
    data: Dict[str, Any] = field(default_factory=dict)
    sort: SortState = field(default_factory=SortState)
    filter_text: str = ""
    show_completed: bool = False
    total_count: int = 0
    detail_sessions: List[dict] = field(default_factory=list)
    detail_blockers: List[str] = field(default_factory=list)
    # Cache for lightweight context per handoff (handoff_id -> LightweightContext)
    lightweight_context: Dict[str, Any] = field(default_factory=dict)
    # Track which handoffs are currently being extracted
    extracting_context: Set[str] = field(default_factory=set)


@dataclass
class AppState:
    """Top-level app state container.

    Aggregates all sub-states and global app-level state like
    pause status, event counts, and tab loading status.
    """

    session: SessionState = field(default_factory=SessionState)
    handoff: HandoffState = field(default_factory=HandoffState)
    project_filter: Optional[str] = None
    paused: bool = False
    last_event_count: int = 0
    live_activity_user_scrolled: bool = False
    tabs_loaded: Dict[str, bool] = field(default_factory=dict)
    chart_period_hours: int = 24  # 24h, 168 (7d), or 720 (30d)
