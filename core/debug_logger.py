#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Debug logging for Claude Recall.

Outputs JSON lines format to ~/.local/state/claude-recall/debug.log
when CLAUDE_RECALL_DEBUG, RECALL_DEBUG, or LESSONS_DEBUG is set.

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


# Configuration - support multiple env var names for backward compatibility
DEBUG_ENV_VAR = "CLAUDE_RECALL_DEBUG"  # Primary name
DEBUG_ENV_VAR_FALLBACK = "RECALL_DEBUG"  # Fallback
DEBUG_ENV_VAR_LEGACY = "LESSONS_DEBUG"  # Legacy name for backward compat
LOG_FILE_NAME = "debug.log"
MAX_LOG_SIZE_MB = 50  # 50MB keeps ~500K events
MAX_LOG_FILES = 3  # 3 files = 150MB max disk usage
CLAUDE_SETTINGS_PATH = Path.home() / ".claude" / "settings.json"

# Session ID - generated once per process
_SESSION_ID: Optional[str] = None


def _get_session_id() -> str:
    """Get or create a session ID for correlating events."""
    global _SESSION_ID
    if _SESSION_ID is None:
        _SESSION_ID = uuid.uuid4().hex[:12]
    return _SESSION_ID


def _read_settings_debug_level() -> Optional[int]:
    """Read debugLevel from ~/.claude/settings.json if it exists.

    Returns None if file doesn't exist or debugLevel isn't set.
    """
    try:
        if not CLAUDE_SETTINGS_PATH.exists():
            return None
        with open(CLAUDE_SETTINGS_PATH) as f:
            settings = json.load(f)
        level = settings.get("lessonsSystem", {}).get("debugLevel")
        if level is not None:
            return int(level)
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        pass
    return None


def _get_debug_level() -> int:
    """Get the configured debug level.

    Checks in order of precedence:
    1. CLAUDE_RECALL_DEBUG env var (temporary override)
    2. lessonsSystem.debugLevel in ~/.claude/settings.json
    3. Default: 1
    """
    # Check env vars first (highest precedence)
    env_level = (
        os.environ.get(DEBUG_ENV_VAR) or
        os.environ.get(DEBUG_ENV_VAR_FALLBACK) or
        os.environ.get(DEBUG_ENV_VAR_LEGACY)
    )
    if env_level:
        try:
            return int(env_level)
        except ValueError:
            # Treat any non-numeric truthy value as level 1
            return 1 if env_level.lower() in ("true", "yes", "on") else 0

    # Check settings.json
    settings_level = _read_settings_debug_level()
    if settings_level is not None:
        return settings_level

    # Default
    return 1


def _get_log_path() -> Path:
    """Get the log file path.

    Uses XDG_STATE_HOME (~/.local/state) for logs per XDG spec.
    CLAUDE_RECALL_STATE overrides with full path to state dir.
    """
    explicit_state = os.environ.get("CLAUDE_RECALL_STATE")
    if explicit_state:
        # Explicit override: use as-is (already includes claude-recall)
        state_dir = Path(explicit_state)
    else:
        # Default: XDG_STATE_HOME/claude-recall
        xdg_state = os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state")
        state_dir = Path(xdg_state) / "claude-recall"
    return state_dir / LOG_FILE_NAME


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
    JSON lines debug logger for Claude Recall.

    All methods are no-ops when CLAUDE_RECALL_DEBUG is 0 or unset.
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

        # Add project context from env (set by hooks)
        project_dir = os.environ.get("PROJECT_DIR", "")
        if project_dir:
            # Use last path component as short identifier
            event["project"] = Path(project_dir).name

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
    # Level 2: Debug events (includes timing)
    # =========================================================================

    @contextmanager
    def timer(self, operation: str, context: Optional[Dict[str, Any]] = None):
        """Context manager to time any operation at level 2.

        Usage:
            with logger.timer("inject_lessons", {"count": 5}):
                do_work()

        Logs: {"event": "timing", "op": "inject_lessons", "ms": 42.5, "count": 5}
        """
        if self._level < 2:
            yield
            return

        start = time.perf_counter()
        try:
            yield
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            event = {
                "event": "timing",
                "level": "debug",
                "op": operation,
                "ms": round(duration_ms, 2),
            }
            if context:
                event.update(context)
            self._write(event)

    def hook_start(self, hook_name: str, trigger: Optional[str] = None) -> float:
        """Log hook start and return start time for later duration calc.

        Args:
            hook_name: inject, stop, precompact, etc.
            trigger: What triggered the hook (auto, manual, compact, etc.)

        Returns:
            Start time (time.perf_counter()) for passing to hook_end
        """
        start = time.perf_counter()
        if self._level < 2:
            return start

        event = {
            "event": "hook_start",
            "level": "debug",
            "hook": hook_name,
        }
        if trigger:
            event["trigger"] = trigger
        self._write(event)
        return start

    def hook_end(self, hook_name: str, start_time: float, phases: Optional[Dict[str, float]] = None) -> None:
        """Log hook completion with total and phase timings.

        Args:
            hook_name: inject, stop, precompact, etc.
            start_time: Value returned from hook_start
            phases: Dict of phase_name -> duration_ms for breakdown
        """
        if self._level < 2:
            return

        total_ms = (time.perf_counter() - start_time) * 1000
        event = {
            "event": "hook_end",
            "level": "debug",
            "hook": hook_name,
            "total_ms": round(total_ms, 2),
        }
        if phases:
            event["phases"] = {k: round(v, 2) for k, v in phases.items()}
        self._write(event)

    def hook_phase(self, hook_name: str, phase: str, duration_ms: float, details: Optional[Dict] = None) -> None:
        """Log individual hook phase timing.

        Args:
            hook_name: inject, stop, precompact
            phase: Phase name like "load_lessons", "parse_output", "haiku_call"
            duration_ms: How long this phase took
            details: Optional additional context
        """
        if self._level < 2:
            return

        event = {
            "event": "hook_phase",
            "level": "debug",
            "hook": hook_name,
            "phase": phase,
            "ms": round(duration_ms, 2),
        }
        if details:
            event.update(details)
        self._write(event)

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
