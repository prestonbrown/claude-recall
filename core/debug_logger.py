#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Debug logging for lessons manager.

Outputs JSON lines format to ~/.config/coding-agent-lessons/debug.log
when RECALL_DEBUG or LESSONS_DEBUG is set.

Levels:
  0 or unset: disabled
  1: info - high-level operations (session start, cite, decay)
  2: debug - includes intermediate steps (injection details)
  3: trace - includes file I/O timing, lock waits
"""

import json
import os
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Dict, List, Optional


# Configuration - support both new and old env var names
DEBUG_ENV_VAR = "RECALL_DEBUG"  # New name
DEBUG_ENV_VAR_LEGACY = "LESSONS_DEBUG"  # Old name for backward compat
LOG_FILE_NAME = "debug.log"
MAX_LOG_SIZE_MB = 50  # 50MB keeps ~500K events
MAX_LOG_FILES = 3  # 3 files = 150MB max disk usage

# Session ID - generated once per process
_SESSION_ID: Optional[str] = None


def _get_session_id() -> str:
    """Get or create a session ID for correlating events."""
    global _SESSION_ID
    if _SESSION_ID is None:
        _SESSION_ID = uuid.uuid4().hex[:12]
    return _SESSION_ID


def _get_debug_level() -> int:
    """Get the configured debug level from environment.

    Checks RECALL_DEBUG first, then falls back to LESSONS_DEBUG for backward compat.
    """
    # Check new env var first, fall back to old
    level = os.environ.get(DEBUG_ENV_VAR) or os.environ.get(DEBUG_ENV_VAR_LEGACY, "0")
    try:
        return int(level)
    except ValueError:
        # Treat any non-numeric truthy value as level 1
        return 1 if level.lower() in ("true", "yes", "on") else 0


def _get_log_path() -> Path:
    """Get the log file path.

    Checks RECALL_BASE first, then falls back to LESSONS_BASE for backward compat.
    """
    lessons_base = Path(
        os.environ.get("RECALL_BASE")
        or os.environ.get("LESSONS_BASE")
        or (Path.home() / ".config" / "coding-agent-lessons")
    )
    return lessons_base / LOG_FILE_NAME


def _rotate_if_needed(log_path: Path) -> None:
    """Rotate log file if it exceeds size limit."""
    if not log_path.exists():
        return

    size_mb = log_path.stat().st_size / (1024 * 1024)
    if size_mb < MAX_LOG_SIZE_MB:
        return

    # Rotate: debug.log.2 -> delete, debug.log.1 -> .2, debug.log -> .1
    for i in range(MAX_LOG_FILES - 1, 0, -1):
        old_path = log_path.parent / f"{LOG_FILE_NAME}.{i}"
        new_path = log_path.parent / f"{LOG_FILE_NAME}.{i + 1}"
        if old_path.exists():
            if i == MAX_LOG_FILES - 1:
                old_path.unlink()
            else:
                old_path.rename(new_path)

    # Rotate current to .1
    backup_path = log_path.parent / f"{LOG_FILE_NAME}.1"
    log_path.rename(backup_path)


class DebugLogger:
    """
    JSON lines debug logger for lessons manager.

    All methods are no-ops when LESSONS_DEBUG is 0 or unset.
    """

    def __init__(self) -> None:
        self._level = _get_debug_level()
        self._log_path = _get_log_path() if self._level > 0 else None

    @property
    def enabled(self) -> bool:
        return self._level > 0

    @property
    def level(self) -> int:
        return self._level

    def _write(self, event: Dict[str, Any]) -> None:
        """Write an event to the log file."""
        if not self.enabled or self._log_path is None:
            return

        # Add common fields
        event["timestamp"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        event["session_id"] = _get_session_id()
        event["pid"] = os.getpid()

        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            _rotate_if_needed(self._log_path)

            with open(self._log_path, "a") as f:
                f.write(json.dumps(event, default=str) + "\n")
        except (OSError, IOError, ValueError) as e:
            # Never let logging errors affect main operation.
            # At trace level, we attempt to log the failure to stderr for debugging.
            if self._level >= 3:
                import sys
                print(f"[debug_logger] write failed: {type(e).__name__}: {e}", file=sys.stderr)

    # =========================================================================
    # Level 1: Info events
    # =========================================================================

    def session_start(
        self,
        project_root: str,
        lessons_base: str,
        total_lessons: int,
        system_count: int,
        project_count: int,
        top_lessons: List[Dict[str, Any]],
        total_tokens: int,
    ) -> None:
        """Log session start with loaded lessons summary."""
        if self._level < 1:
            return
        self._write(
            {
                "event": "session_start",
                "level": "info",
                "project_root": project_root,
                "lessons_base": lessons_base,
                "total_lessons": total_lessons,
                "system_count": system_count,
                "project_count": project_count,
                "top_lessons": top_lessons[:10],  # Limit array size
                "total_tokens": total_tokens,
            }
        )

    def citation(
        self,
        lesson_id: str,
        uses_before: int,
        uses_after: int,
        velocity_before: float,
        velocity_after: float,
        promotion_ready: bool,
    ) -> None:
        """Log a lesson citation."""
        if self._level < 1:
            return
        self._write(
            {
                "event": "citation",
                "level": "info",
                "lesson_id": lesson_id,
                "uses_before": uses_before,
                "uses_after": uses_after,
                "velocity_before": velocity_before,
                "velocity_after": velocity_after,
                "promotion_ready": promotion_ready,
            }
        )

    def lesson_added(
        self,
        lesson_id: str,
        level: str,
        category: str,
        source: str,
        title_length: int,
        content_length: int,
    ) -> None:
        """Log new lesson creation."""
        if self._level < 1:
            return
        self._write(
            {
                "event": "lesson_added",
                "level": "info",
                "lesson_id": lesson_id,
                "lesson_level": level,
                "category": category,
                "source": source,
                "title_length": title_length,
                "content_length": content_length,
            }
        )

    def decay_result(
        self,
        decayed_uses: int,
        decayed_velocity: int,
        sessions_since_last: int,
        skipped: bool,
        lessons_affected: List[Dict[str, Any]],
    ) -> None:
        """Log decay operation results."""
        if self._level < 1:
            return
        self._write(
            {
                "event": "decay_result",
                "level": "info",
                "decayed_uses": decayed_uses,
                "decayed_velocity": decayed_velocity,
                "sessions_since_last": sessions_since_last,
                "skipped": skipped,
                "lessons_affected": lessons_affected[:20],  # Limit array size
            }
        )

    def handoff_created(
        self,
        handoff_id: str,
        title: str,
        phase: str,
        agent: str,
    ) -> None:
        """Log new handoff creation."""
        if self._level < 1:
            return
        self._write(
            {
                "event": "handoff_created",
                "level": "info",
                "handoff_id": handoff_id,
                "title": title,
                "phase": phase,
                "agent": agent,
            }
        )

    # =========================================================================
    # DEPRECATED ALIASES (remove after 2025-06-01)
    # These delegate to handoff_* methods and are kept for API compatibility.
    # =========================================================================

    # DEPRECATED (remove after 2025-06-01): Use handoff_created instead
    def approach_created(
        self,
        approach_id: str,
        title: str,
        phase: str,
        agent: str,
    ) -> None:
        """DEPRECATED: Use handoff_created instead."""
        return self.handoff_created(handoff_id=approach_id, title=title, phase=phase, agent=agent)

    def handoff_change(
        self,
        handoff_id: str,
        action: str,  # status_change, phase_change, agent_change, tried_added
        old_value: Optional[str] = None,
        new_value: Optional[str] = None,
    ) -> None:
        """Log handoff state changes."""
        if self._level < 1:
            return
        self._write(
            {
                "event": "handoff_change",
                "level": "info",
                "handoff_id": handoff_id,
                "action": action,
                "old_value": old_value,
                "new_value": new_value,
            }
        )

    # DEPRECATED (remove after 2025-06-01): Use handoff_change instead
    def approach_change(
        self,
        approach_id: str,
        action: str,
        old_value: Optional[str] = None,
        new_value: Optional[str] = None,
    ) -> None:
        """DEPRECATED: Use handoff_change instead."""
        return self.handoff_change(handoff_id=approach_id, action=action, old_value=old_value, new_value=new_value)

    def handoff_completed(
        self,
        handoff_id: str,
        tried_count: int,
        duration_days: Optional[int] = None,
    ) -> None:
        """Log handoff completion."""
        if self._level < 1:
            return
        self._write(
            {
                "event": "handoff_completed",
                "level": "info",
                "handoff_id": handoff_id,
                "tried_count": tried_count,
                "duration_days": duration_days,
            }
        )

    # DEPRECATED (remove after 2025-06-01): Use handoff_completed instead
    def approach_completed(
        self,
        approach_id: str,
        tried_count: int,
        duration_days: Optional[int] = None,
    ) -> None:
        """DEPRECATED: Use handoff_completed instead."""
        return self.handoff_completed(handoff_id=approach_id, tried_count=tried_count, duration_days=duration_days)

    def error(self, operation: str, error: str, context: Optional[Dict] = None) -> None:
        """Log errors - level 1 (always shown when debug enabled)."""
        if self._level < 1:
            return
        event = {"event": "error", "level": "error", "op": operation, "err": error}
        if context:
            event["ctx"] = context
        self._write(event)

    def mutation(self, op: str, target: str, details: Optional[Dict] = None) -> None:
        """Log mutations (edit/delete/promote/sync) - level 1."""
        if self._level < 1:
            return
        event = {"event": "mutation", "level": "info", "op": op, "target": target}
        if details:
            event.update(details)
        self._write(event)

    # =========================================================================
    # Level 2: Debug events
    # =========================================================================

    def relevance_score(
        self,
        query_len: int,
        lesson_count: int,
        duration_ms: int,
        top_scores: List[tuple],
        error: Optional[str] = None,
    ) -> None:
        """Log Haiku relevance scoring - level 2."""
        if self._level < 2:
            return
        event = {
            "event": "relevance",
            "level": "debug",
            "q_len": query_len,
            "lessons": lesson_count,
            "ms": duration_ms,
            "top": top_scores[:3],  # Just top 3 as tuples: [["L001", 8], ["S002", 7]]
        }
        if error:
            event["err"] = error
        self._write(event)

    def injection_generated(
        self,
        token_budget: int,
        lessons_included: int,
        lessons_excluded: int,
        included_ids: List[str],
    ) -> None:
        """Log injection generation details."""
        if self._level < 2:
            return
        self._write(
            {
                "event": "injection_generated",
                "level": "debug",
                "token_budget": token_budget,
                "lessons_included": lessons_included,
                "lessons_excluded": lessons_excluded,
                "included_ids": included_ids[:20],
            }
        )

    # =========================================================================
    # Level 3: Trace events
    # =========================================================================

    @contextmanager
    def trace_file_io(self, operation: str, file_path: str):
        """Context manager to trace file I/O timing."""
        if self._level < 3:
            yield
            return

        start = time.perf_counter()
        try:
            yield
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            self._write(
                {
                    "event": "file_io",
                    "level": "trace",
                    "operation": operation,  # read, write, parse
                    "file_path": str(file_path),
                    "duration_ms": round(duration_ms, 2),
                }
            )

    @contextmanager
    def trace_lock(self, file_path: str):
        """Context manager to trace lock acquisition timing."""
        if self._level < 3:
            yield
            return

        start = time.perf_counter()
        try:
            yield
        finally:
            wait_ms = (time.perf_counter() - start) * 1000
            self._write(
                {
                    "event": "lock_acquired",
                    "level": "trace",
                    "file_path": str(file_path),
                    "wait_ms": round(wait_ms, 2),
                }
            )


# Global singleton
_logger: Optional[DebugLogger] = None


def get_logger() -> DebugLogger:
    """Get the global debug logger instance."""
    global _logger
    if _logger is None:
        _logger = DebugLogger()
    return _logger


def reset_logger() -> None:
    """Reset the global logger (for testing)."""
    global _logger
    _logger = None


# Convenience decorator for tracing function calls
def trace_call(func):
    """Decorator to trace function entry/exit at level 3."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        logger = get_logger()
        if logger.level < 3:
            return func(*args, **kwargs)

        start = time.perf_counter()
        try:
            result = func(*args, **kwargs)
            return result
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            logger._write(
                {
                    "event": "function_call",
                    "level": "trace",
                    "function": func.__name__,
                    "duration_ms": round(duration_ms, 2),
                }
            )

    return wrapper
