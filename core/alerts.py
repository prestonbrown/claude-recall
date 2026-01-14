#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Real-time alerting system for Claude Recall.

Provides proactive notifications when issues are detected:
- Hook latency spikes (>2x normal)
- High error rates (>10% in last 24h)
- Stale handoffs (>7 days without update)
- Lesson effectiveness drops (<30% effectiveness)

Alert mechanisms:
- Terminal bell on health degradation (optional, configurable)
- Daily digest summary
- Webhook integration (optional)
"""

import json
import sys
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Import from existing modules
try:
    from core.config import get_setting
    from core.tui.log_reader import LogReader, get_default_log_path
    from core.tui.state_reader import StateReader
    from core.tui.stats import StatsAggregator
except ImportError:
    from config import get_setting
    from tui.log_reader import LogReader, get_default_log_path
    from tui.state_reader import StateReader
    from tui.stats import StatsAggregator


# -----------------------------------------------------------------------------
# Alert Type and Severity Constants
# -----------------------------------------------------------------------------


class AlertType:
    """Constants for alert types."""

    LATENCY_SPIKE = "latency_spike"
    HIGH_ERROR_RATE = "high_error_rate"
    STALE_HANDOFFS = "stale_handoffs"
    LOW_EFFECTIVENESS = "low_effectiveness"


class AlertSeverity:
    """Constants for alert severity levels."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------


def get_alert_settings() -> Dict[str, Any]:
    """
    Get alert configuration from settings.

    Reads from ~/.claude/settings.json under claudeRecall.alerts namespace.

    Returns:
        Dict with alert settings:
        - enabled: bool (default False)
        - stale_handoff_days: int (default 7)
        - latency_spike_multiplier: float (default 2.0)
        - error_rate_threshold: float (default 0.10)
        - effectiveness_threshold: float (default 0.30)
        - webhook_url: Optional[str] (default None)
    """
    # Read from nested config path
    alerts_config = get_setting("claudeRecall.alerts", {})

    if not isinstance(alerts_config, dict):
        alerts_config = {}

    return {
        "enabled": alerts_config.get("enabled", False),
        "stale_handoff_days": alerts_config.get("staleHandoffDays", 7),
        "latency_spike_multiplier": alerts_config.get("latencySpikeMultiplier", 2.0),
        "error_rate_threshold": alerts_config.get("errorRateThreshold", 0.10),
        "effectiveness_threshold": alerts_config.get("effectivenessThreshold", 0.30),
        "webhook_url": alerts_config.get("webhookUrl", None),
    }


# -----------------------------------------------------------------------------
# Alert Data Class
# -----------------------------------------------------------------------------


@dataclass
class Alert:
    """
    Represents a single alert.

    Attributes:
        alert_type: Type of alert (from AlertType constants)
        severity: Severity level (from AlertSeverity constants)
        message: Human-readable alert message
        details: Additional context (varies by alert type)
        timestamp: When the alert was generated
    """

    alert_type: str
    severity: str
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: Optional[datetime] = None

    def __post_init__(self):
        """Set timestamp if not provided."""
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)

    def to_dict(self) -> Dict[str, Any]:
        """Convert alert to dictionary for JSON serialization."""
        return {
            "type": self.alert_type,
            "severity": self.severity,
            "message": self.message,
            "details": self.details,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


# -----------------------------------------------------------------------------
# AlertsManager
# -----------------------------------------------------------------------------


class AlertsManager:
    """
    Manages alert detection, generation, and notification.

    Analyzes health metrics from existing TUI infrastructure and generates
    alerts when thresholds are exceeded.

    Attributes:
        state_dir: Path to state directory
        project_root: Path to project root (for handoffs)
        log_reader: LogReader for accessing debug events
        state_reader: StateReader for accessing lessons/handoffs state
        settings: Alert configuration
    """

    def __init__(
        self,
        state_dir: Optional[Path] = None,
        project_root: Optional[Path] = None,
    ) -> None:
        """
        Initialize the alerts manager.

        Args:
            state_dir: Path to state directory. If None, uses default.
            project_root: Path to project root. If None, attempts to detect.
        """
        self.state_dir = state_dir or get_default_log_path().parent
        self.project_root = project_root
        self.settings = get_alert_settings()

        # Initialize readers
        log_path = self.state_dir / "debug.log"
        self.log_reader = LogReader(log_path)
        self.state_reader = StateReader(
            state_dir=self.state_dir,
            project_root=self.project_root,
        )

    def check_latency_spike(self) -> List[Alert]:
        """
        Check for hook latency spikes.

        Compares recent hook timing (last 6 hours) against baseline (7-day average).
        Alerts if recent timing exceeds baseline by configured multiplier (default 2x).

        Returns:
            List of latency spike alerts (0 or 1)
        """
        alerts = []
        multiplier = self.settings["latency_spike_multiplier"]

        # Load events
        self.log_reader.load_buffer()
        events = list(self.log_reader.iter_events())

        if not events:
            return alerts

        # Filter to hook_end events
        now = datetime.now(timezone.utc)
        recent_cutoff = now - timedelta(hours=6)
        baseline_cutoff = now - timedelta(days=7)

        recent_timings = []
        baseline_timings = []

        for event in events:
            if event.event != "hook_end":
                continue

            timing = event.get("total_ms")
            if timing is None:
                continue

            ts = event.timestamp_dt
            if ts is None:
                continue

            if ts >= recent_cutoff:
                recent_timings.append(timing)
            elif ts >= baseline_cutoff:
                baseline_timings.append(timing)

        # Need both recent and baseline data to compare
        if not recent_timings or not baseline_timings:
            return alerts

        recent_avg = sum(recent_timings) / len(recent_timings)
        baseline_avg = sum(baseline_timings) / len(baseline_timings)

        # Check if recent average exceeds baseline by multiplier
        if baseline_avg > 0 and recent_avg > baseline_avg * multiplier:
            alerts.append(Alert(
                alert_type=AlertType.LATENCY_SPIKE,
                severity=AlertSeverity.WARNING,
                message=f"Hook latency spike: {recent_avg:.0f}ms avg (baseline: {baseline_avg:.0f}ms)",
                details={
                    "recent_avg_ms": round(recent_avg, 2),
                    "baseline_avg_ms": round(baseline_avg, 2),
                    "multiplier": round(recent_avg / baseline_avg, 2),
                    "recent_count": len(recent_timings),
                    "baseline_count": len(baseline_timings),
                },
            ))

        return alerts

    def check_error_rate(self) -> List[Alert]:
        """
        Check for high error rate.

        Calculates error rate over last 24 hours. Alerts if rate exceeds
        configured threshold (default 10%).

        Returns:
            List of error rate alerts (0 or 1)
        """
        alerts = []
        threshold = self.settings["error_rate_threshold"]

        # Load events
        self.log_reader.load_buffer()
        events = list(self.log_reader.iter_events())

        if not events:
            return alerts

        # Filter to last 24 hours
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=24)

        total_events = 0
        error_count = 0

        for event in events:
            ts = event.timestamp_dt
            if ts is None or ts < cutoff:
                continue

            total_events += 1
            if event.is_error:
                error_count += 1

        # Need minimum events to calculate meaningful rate
        if total_events < 5:
            return alerts

        error_rate = error_count / total_events

        if error_rate > threshold:
            alerts.append(Alert(
                alert_type=AlertType.HIGH_ERROR_RATE,
                severity=AlertSeverity.CRITICAL,
                message=f"High error rate: {error_rate:.1%} in last 24h ({error_count}/{total_events} events)",
                details={
                    "error_rate": round(error_rate, 4),
                    "error_count": error_count,
                    "total_events": total_events,
                    "threshold": threshold,
                },
            ))

        return alerts

    def check_stale_handoffs(self) -> List[Alert]:
        """
        Check for stale handoffs.

        Identifies handoffs that haven't been updated in longer than configured
        days (default 7). Only checks active (non-completed) handoffs.

        Returns:
            List of stale handoff alerts (0 or 1)
        """
        alerts = []
        stale_days = self.settings["stale_handoff_days"]

        # Get active handoffs
        handoffs = self.state_reader.get_active_handoffs(self.project_root)

        if not handoffs:
            return alerts

        # Find stale handoffs
        stale_ids = []
        for handoff in handoffs:
            if handoff.updated_age_days >= stale_days:
                stale_ids.append(handoff.id)

        if stale_ids:
            alerts.append(Alert(
                alert_type=AlertType.STALE_HANDOFFS,
                severity=AlertSeverity.WARNING if len(stale_ids) <= 3 else AlertSeverity.CRITICAL,
                message=f"{len(stale_ids)} handoff(s) stale (>{stale_days} days without update)",
                details={
                    "count": len(stale_ids),
                    "ids": stale_ids,
                    "threshold_days": stale_days,
                },
            ))

        return alerts

    def check_low_effectiveness(self) -> List[Alert]:
        """
        Check for lessons with low effectiveness.

        Identifies lessons where effectiveness rate is below threshold
        (default 30%) and have enough citations to be meaningful (default 3+).

        Returns:
            List of low effectiveness alerts (0 or 1)
        """
        alerts = []
        threshold = self.settings["effectiveness_threshold"]

        # Get low-effectiveness lessons
        # Uses default min_citations=3 to filter out lessons with insufficient data
        low_eff = self.state_reader.get_lesson_effectiveness(
            threshold=threshold,
            min_citations=3,
        )

        if not low_eff:
            return alerts

        lesson_ids = [item[0] for item in low_eff]
        lesson_data = {
            item[0]: {"rate": item[1], "citations": item[2]}
            for item in low_eff
        }

        alerts.append(Alert(
            alert_type=AlertType.LOW_EFFECTIVENESS,
            severity=AlertSeverity.INFO if len(low_eff) <= 2 else AlertSeverity.WARNING,
            message=f"{len(low_eff)} lesson(s) with low effectiveness (<{threshold:.0%})",
            details={
                "count": len(low_eff),
                "lessons": lesson_ids,
                "lesson_data": lesson_data,
                "threshold": threshold,
            },
        ))

        return alerts

    def get_alerts(self) -> List[Alert]:
        """
        Get all current alerts.

        Runs all alert checks and returns combined list.

        Returns:
            List of all active alerts
        """
        alerts = []

        alerts.extend(self.check_latency_spike())
        alerts.extend(self.check_error_rate())
        alerts.extend(self.check_stale_handoffs())
        alerts.extend(self.check_low_effectiveness())

        return alerts

    def generate_digest(self) -> str:
        """
        Generate a daily digest summary.

        Provides an overview of system health including:
        - Current alerts
        - Statistics summary
        - Recommendations

        Returns:
            Formatted digest string
        """
        lines = ["=" * 50]
        lines.append("Claude Recall Daily Digest")
        lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        lines.append("=" * 50)
        lines.append("")

        # Get alerts
        alerts = self.get_alerts()

        if alerts:
            lines.append("ALERTS:")
            for alert in alerts:
                severity_marker = {
                    AlertSeverity.INFO: "[i]",
                    AlertSeverity.WARNING: "[!]",
                    AlertSeverity.CRITICAL: "[X]",
                }.get(alert.severity, "[ ]")
                lines.append(f"  {severity_marker} {alert.message}")
            lines.append("")
        else:
            lines.append("ALERTS: None - all systems healthy")
            lines.append("")

        # Add stats summary
        try:
            aggregator = StatsAggregator(self.log_reader, self.state_reader)
            stats = aggregator.compute()

            lines.append("STATISTICS (24h):")
            lines.append(f"  Sessions: {stats.sessions_today}")
            lines.append(f"  Citations: {stats.citations_today}")
            lines.append(f"  Errors: {stats.errors_today}")
            lines.append(f"  Avg Hook Time: {stats.avg_hook_ms:.0f}ms (p95: {stats.p95_hook_ms:.0f}ms)")
            lines.append("")
        except Exception:
            pass  # Stats errors shouldn't break digest

        # Add lesson/handoff counts
        try:
            lesson_counts = self.state_reader.get_lesson_counts(self.project_root)
            lines.append("LESSONS:")
            lines.append(f"  System: {lesson_counts.get('system', 0)}")
            lines.append(f"  Project: {lesson_counts.get('project', 0)}")
            lines.append("")

            handoff_counts = self.state_reader.get_handoff_counts(self.project_root)
            if handoff_counts["total"] > 0:
                lines.append("HANDOFFS:")
                lines.append(f"  Active: {handoff_counts['total'] - handoff_counts.get('completed', 0)}")
                lines.append(f"  Blocked: {handoff_counts.get('blocked', 0)}")
                lines.append(f"  In Progress: {handoff_counts.get('in_progress', 0)}")
                lines.append("")
        except Exception:
            pass  # State errors shouldn't break digest

        lines.append("=" * 50)

        return "\n".join(lines)

    def send_bell_if_needed(self) -> None:
        """
        Send terminal bell if alerting is enabled and alerts exist.

        Bell is sent to stderr to be visible in terminal but not
        captured by hook output.
        """
        if not self.settings["enabled"]:
            return

        alerts = self.get_alerts()

        if alerts:
            # Print bell character to stderr
            print("\a", file=sys.stderr, end="")

    def send_webhook(self) -> bool:
        """
        Send alerts to configured webhook URL.

        Sends a JSON payload with all current alerts to the configured
        webhook URL if one is set.

        Returns:
            True if webhook was sent successfully, False otherwise
        """
        webhook_url = self.settings.get("webhook_url")

        if not webhook_url:
            return False

        # Validate URL scheme to prevent SSRF
        if not webhook_url.startswith(("https://", "http://")):
            return False

        if not self.settings["enabled"]:
            return False

        alerts = self.get_alerts()

        if not alerts:
            return True  # Nothing to send is not an error

        # Build payload
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "alerts": [alert.to_dict() for alert in alerts],
            "project": str(self.project_root) if self.project_root else None,
        }

        try:
            data = json.dumps(payload).encode("utf-8")
            request = urllib.request.Request(
                webhook_url,
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "claude-recall/1.0",
                },
            )

            with urllib.request.urlopen(request, timeout=10) as response:
                response.read()

            return True

        except Exception:
            return False

    def format_alerts_summary(self) -> str:
        """
        Format a brief summary of current alerts for display.

        Returns:
            Single-line summary suitable for stderr output
        """
        alerts = self.get_alerts()

        if not alerts:
            return ""

        critical = sum(1 for a in alerts if a.severity == AlertSeverity.CRITICAL)
        warning = sum(1 for a in alerts if a.severity == AlertSeverity.WARNING)
        info = sum(1 for a in alerts if a.severity == AlertSeverity.INFO)

        parts = []
        if critical:
            parts.append(f"{critical} critical")
        if warning:
            parts.append(f"{warning} warning")
        if info:
            parts.append(f"{info} info")

        return f"[Alerts: {', '.join(parts)}]"
