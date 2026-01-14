"""
Tests for the alerts module.

Tests cover:
- AlertsManager initialization and configuration
- Alert detection for various conditions (latency, errors, stale handoffs, effectiveness)
- Alert generation and formatting
- Daily digest generation
- Webhook sending (mocked)
- CLI integration
"""

import json
import os
import pytest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

# Import the module under test
from core.alerts import (
    AlertsManager,
    Alert,
    AlertType,
    AlertSeverity,
    get_alert_settings,
)


class TestAlertTypes:
    """Test alert type definitions."""

    def test_alert_type_values(self):
        """Alert types should have expected string values."""
        assert AlertType.LATENCY_SPIKE == "latency_spike"
        assert AlertType.HIGH_ERROR_RATE == "high_error_rate"
        assert AlertType.STALE_HANDOFFS == "stale_handoffs"
        assert AlertType.LOW_EFFECTIVENESS == "low_effectiveness"

    def test_alert_severity_values(self):
        """Alert severities should have expected string values."""
        assert AlertSeverity.INFO == "info"
        assert AlertSeverity.WARNING == "warning"
        assert AlertSeverity.CRITICAL == "critical"


class TestAlert:
    """Test Alert dataclass."""

    def test_alert_creation(self):
        """Should create an alert with all required fields."""
        alert = Alert(
            alert_type=AlertType.LATENCY_SPIKE,
            severity=AlertSeverity.WARNING,
            message="Hook latency spike detected",
            details={"avg_ms": 250, "baseline_ms": 100},
        )

        assert alert.alert_type == AlertType.LATENCY_SPIKE
        assert alert.severity == AlertSeverity.WARNING
        assert alert.message == "Hook latency spike detected"
        assert alert.details["avg_ms"] == 250

    def test_alert_timestamp_auto_generated(self):
        """Alert timestamp should be auto-generated if not provided."""
        alert = Alert(
            alert_type=AlertType.HIGH_ERROR_RATE,
            severity=AlertSeverity.CRITICAL,
            message="High error rate",
        )

        assert alert.timestamp is not None
        # Should be within the last minute
        assert (datetime.now(timezone.utc) - alert.timestamp).seconds < 60

    def test_alert_to_dict(self):
        """Alert should convert to dict for JSON serialization."""
        alert = Alert(
            alert_type=AlertType.STALE_HANDOFFS,
            severity=AlertSeverity.INFO,
            message="3 handoffs are stale",
            details={"count": 3, "ids": ["hf-abc", "hf-def", "hf-ghi"]},
        )

        d = alert.to_dict()

        assert d["type"] == "stale_handoffs"
        assert d["severity"] == "info"
        assert d["message"] == "3 handoffs are stale"
        assert d["details"]["count"] == 3
        assert "timestamp" in d


class TestAlertSettings:
    """Test alert configuration reading."""

    def test_get_alert_settings_defaults(self, tmp_path, monkeypatch):
        """Should return default settings when no config exists."""
        settings_path = tmp_path / "settings.json"
        monkeypatch.setenv("CLAUDE_CODE_SETTINGS", str(settings_path))

        settings = get_alert_settings()

        assert settings["enabled"] is False
        assert settings["stale_handoff_days"] == 7
        assert settings["latency_spike_multiplier"] == 2.0
        assert settings["error_rate_threshold"] == 0.10
        assert settings["effectiveness_threshold"] == 0.30
        assert settings["webhook_url"] is None

    def test_get_alert_settings_from_config(self, tmp_path, monkeypatch):
        """Should read settings from config file."""
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({
            "claudeRecall": {
                "alerts": {
                    "enabled": True,
                    "staleHandoffDays": 14,
                    "latencySpikeMultiplier": 3.0,
                    "errorRateThreshold": 0.05,
                    "effectivenessThreshold": 0.5,
                    "webhookUrl": "https://hooks.example.com/alert",
                }
            }
        }))
        monkeypatch.setenv("CLAUDE_CODE_SETTINGS", str(settings_path))

        settings = get_alert_settings()

        assert settings["enabled"] is True
        assert settings["stale_handoff_days"] == 14
        assert settings["latency_spike_multiplier"] == 3.0
        assert settings["error_rate_threshold"] == 0.05
        assert settings["effectiveness_threshold"] == 0.5
        assert settings["webhook_url"] == "https://hooks.example.com/alert"


class TestAlertsManager:
    """Test AlertsManager class."""

    @pytest.fixture
    def manager(self, temp_state_dir):
        """Create AlertsManager with isolated state."""
        return AlertsManager(state_dir=temp_state_dir)

    @pytest.fixture
    def manager_with_log(self, temp_state_dir):
        """Create AlertsManager with sample log data."""
        # Create a debug.log with sample events
        log_file = temp_state_dir / "debug.log"
        now = datetime.now(timezone.utc)
        events = []

        # Add some hook_end events for timing baseline (recent)
        for i in range(10):
            ts_dt = now - timedelta(hours=i)
            ts = ts_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            events.append(json.dumps({
                "event": "hook_end",
                "timestamp": ts,
                "hook": "inject",
                "total_ms": 80 + i * 5,  # 80-125ms
                "level": "info",
            }))

        # Add one session_start
        events.append(json.dumps({
            "event": "session_start",
            "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "level": "info",
        }))

        log_file.write_text("\n".join(events) + "\n")

        return AlertsManager(state_dir=temp_state_dir)

    def test_init_creates_reader(self, manager):
        """Manager should initialize with a log reader."""
        assert manager.log_reader is not None
        assert manager.state_reader is not None

    def test_check_latency_no_spike(self, manager_with_log):
        """Should not alert when latency is normal."""
        alerts = manager_with_log.check_latency_spike()

        # With baseline ~100ms and 2x multiplier, normal data shouldn't alert
        latency_alerts = [a for a in alerts if a.alert_type == AlertType.LATENCY_SPIKE]
        assert len(latency_alerts) == 0

    def test_check_latency_spike_detected(self, temp_state_dir):
        """Should alert when latency exceeds threshold."""
        # Create log with spike
        log_file = temp_state_dir / "debug.log"
        now = datetime.now(timezone.utc)
        events = []

        # Add baseline timing (older, in 7-day baseline window but not recent 6h window)
        for i in range(5):
            ts_dt = now - timedelta(hours=24 + i)
            ts = ts_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            events.append(json.dumps({
                "event": "hook_end",
                "timestamp": ts,
                "hook": "inject",
                "total_ms": 100,
                "level": "info",
            }))

        # Add spike timing (recent, in 6h window) - 3x baseline
        for i in range(5):
            ts_dt = now - timedelta(hours=i)
            ts = ts_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            events.append(json.dumps({
                "event": "hook_end",
                "timestamp": ts,
                "hook": "inject",
                "total_ms": 350,  # 3.5x baseline
                "level": "info",
            }))

        log_file.write_text("\n".join(events) + "\n")

        manager = AlertsManager(state_dir=temp_state_dir)
        alerts = manager.check_latency_spike()

        latency_alerts = [a for a in alerts if a.alert_type == AlertType.LATENCY_SPIKE]
        assert len(latency_alerts) == 1
        assert latency_alerts[0].severity == AlertSeverity.WARNING

    def test_check_error_rate_no_alerts(self, manager_with_log):
        """Should not alert when error rate is low."""
        alerts = manager_with_log.check_error_rate()

        error_alerts = [a for a in alerts if a.alert_type == AlertType.HIGH_ERROR_RATE]
        assert len(error_alerts) == 0

    def test_check_error_rate_high(self, temp_state_dir):
        """Should alert when error rate exceeds threshold."""
        log_file = temp_state_dir / "debug.log"
        now = datetime.now(timezone.utc)
        events = []

        # Add 8 normal events
        for i in range(8):
            ts_dt = now - timedelta(hours=i)
            ts = ts_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            events.append(json.dumps({
                "event": "session_start",
                "timestamp": ts,
                "level": "info",
            }))

        # Add 3 error events (25% error rate, above 10% threshold)
        for i in range(3):
            ts_dt = now - timedelta(hours=i)
            ts = ts_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            events.append(json.dumps({
                "event": "error",
                "timestamp": ts,
                "level": "error",
                "message": f"Test error {i}",
            }))

        log_file.write_text("\n".join(events) + "\n")

        manager = AlertsManager(state_dir=temp_state_dir)
        alerts = manager.check_error_rate()

        error_alerts = [a for a in alerts if a.alert_type == AlertType.HIGH_ERROR_RATE]
        assert len(error_alerts) == 1
        assert error_alerts[0].severity == AlertSeverity.CRITICAL

    def test_check_stale_handoffs_none(self, temp_state_dir, tmp_path):
        """Should not alert when no stale handoffs exist."""
        # Create project dir with recent handoff
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        data_dir = project_dir / ".claude-recall"
        data_dir.mkdir()

        today = date.today().isoformat()
        handoffs_file = data_dir / "HANDOFFS.md"
        handoffs_file.write_text(f"""# Handoffs

### [hf-abc1234] Active work
- **Status**: in_progress | **Phase**: implementing
- **Created**: {today} | **Updated**: {today}
**Description**: Some active work
""")

        manager = AlertsManager(
            state_dir=temp_state_dir,
            project_root=project_dir,
        )
        alerts = manager.check_stale_handoffs()

        stale_alerts = [a for a in alerts if a.alert_type == AlertType.STALE_HANDOFFS]
        assert len(stale_alerts) == 0

    def test_check_stale_handoffs_detected(self, temp_state_dir, tmp_path):
        """Should alert when handoffs are stale (>7 days without update)."""
        # Create project dir with stale handoff
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        data_dir = project_dir / ".claude-recall"
        data_dir.mkdir()

        old_date = (date.today() - timedelta(days=10)).isoformat()
        handoffs_file = data_dir / "HANDOFFS.md"
        handoffs_file.write_text(f"""# Handoffs

### [hf-old1234] Stale work
- **Status**: in_progress | **Phase**: implementing
- **Created**: {old_date} | **Updated**: {old_date}
**Description**: Work that hasn't been touched

### [hf-old5678] Another stale one
- **Status**: blocked | **Phase**: research
- **Created**: {old_date} | **Updated**: {old_date}
**Description**: Blocked and forgotten
""")

        manager = AlertsManager(
            state_dir=temp_state_dir,
            project_root=project_dir,
        )
        alerts = manager.check_stale_handoffs()

        stale_alerts = [a for a in alerts if a.alert_type == AlertType.STALE_HANDOFFS]
        assert len(stale_alerts) == 1
        assert stale_alerts[0].details["count"] == 2
        assert "hf-old1234" in stale_alerts[0].details["ids"]
        assert "hf-old5678" in stale_alerts[0].details["ids"]

    def test_check_low_effectiveness_none(self, temp_state_dir):
        """Should not alert when no low-effectiveness lessons exist."""
        # Create effectiveness.json with good scores
        eff_file = temp_state_dir / "effectiveness.json"
        eff_file.write_text(json.dumps({
            "L001": {
                "total_citations_tracked": 10,
                "effective_citations": 8,
                "effectiveness_rate": 0.8,
            },
            "L002": {
                "total_citations_tracked": 5,
                "effective_citations": 4,
                "effectiveness_rate": 0.8,
            },
        }))

        manager = AlertsManager(state_dir=temp_state_dir)
        alerts = manager.check_low_effectiveness()

        eff_alerts = [a for a in alerts if a.alert_type == AlertType.LOW_EFFECTIVENESS]
        assert len(eff_alerts) == 0

    def test_check_low_effectiveness_detected(self, temp_state_dir):
        """Should alert when lessons have low effectiveness."""
        # Create effectiveness.json with poor scores
        eff_file = temp_state_dir / "effectiveness.json"
        eff_file.write_text(json.dumps({
            "L001": {
                "total_citations_tracked": 10,
                "effective_citations": 2,
                "effectiveness_rate": 0.2,  # 20% - below 30% threshold
            },
            "L002": {
                "total_citations_tracked": 5,
                "effective_citations": 1,
                "effectiveness_rate": 0.2,  # 20%
            },
            "L003": {
                "total_citations_tracked": 2,  # Not enough citations
                "effective_citations": 0,
                "effectiveness_rate": 0.0,
            },
        }))

        manager = AlertsManager(state_dir=temp_state_dir)
        alerts = manager.check_low_effectiveness()

        eff_alerts = [a for a in alerts if a.alert_type == AlertType.LOW_EFFECTIVENESS]
        assert len(eff_alerts) == 1
        assert eff_alerts[0].details["count"] == 2
        assert "L001" in eff_alerts[0].details["lessons"]
        assert "L002" in eff_alerts[0].details["lessons"]
        # L003 should be excluded due to insufficient citations
        assert "L003" not in eff_alerts[0].details["lessons"]

    def test_get_all_alerts(self, manager_with_log):
        """get_alerts should return all current alerts."""
        alerts = manager_with_log.get_alerts()

        # Should be a list of Alert objects
        assert isinstance(alerts, list)
        for alert in alerts:
            assert isinstance(alert, Alert)

    def test_generate_digest_empty(self, manager_with_log):
        """Should generate digest even with no alerts."""
        digest = manager_with_log.generate_digest()

        assert isinstance(digest, str)
        assert "Claude Recall Daily Digest" in digest

    def test_generate_digest_with_alerts(self, temp_state_dir, tmp_path):
        """Should generate comprehensive digest with alerts."""
        # Set up state that will trigger alerts
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        data_dir = project_dir / ".claude-recall"
        data_dir.mkdir()

        old_date = (date.today() - timedelta(days=10)).isoformat()
        handoffs_file = data_dir / "HANDOFFS.md"
        handoffs_file.write_text(f"""# Handoffs

### [hf-stale1] Stale handoff
- **Status**: in_progress | **Phase**: implementing
- **Created**: {old_date} | **Updated**: {old_date}
""")

        # Add some log events
        log_file = temp_state_dir / "debug.log"
        now = datetime.now(timezone.utc)
        events = [
            json.dumps({
                "event": "session_start",
                "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "level": "info",
            }),
        ]
        log_file.write_text("\n".join(events) + "\n")

        manager = AlertsManager(
            state_dir=temp_state_dir,
            project_root=project_dir,
        )
        digest = manager.generate_digest()

        assert "Claude Recall Daily Digest" in digest
        assert "stale" in digest.lower() or "handoff" in digest.lower()

    def test_send_bell_disabled_by_default(self, manager_with_log, capsys):
        """Bell should not ring when alerting is disabled."""
        manager_with_log.send_bell_if_needed()
        captured = capsys.readouterr()
        # Bell character should not be in output
        assert "\a" not in captured.out
        assert "\a" not in captured.err

    def test_send_bell_when_enabled(self, temp_state_dir, tmp_path, monkeypatch, capsys):
        """Bell should ring when alerting is enabled and alerts exist."""
        # Enable alerting
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({
            "claudeRecall": {
                "alerts": {
                    "enabled": True,
                }
            }
        }))
        monkeypatch.setenv("CLAUDE_CODE_SETTINGS", str(settings_path))

        # Create stale handoff to trigger alert
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        data_dir = project_dir / ".claude-recall"
        data_dir.mkdir()

        old_date = (date.today() - timedelta(days=10)).isoformat()
        handoffs_file = data_dir / "HANDOFFS.md"
        handoffs_file.write_text(f"""# Handoffs

### [hf-stale] Stale handoff
- **Status**: in_progress | **Phase**: implementing
- **Created**: {old_date} | **Updated**: {old_date}
""")

        manager = AlertsManager(
            state_dir=temp_state_dir,
            project_root=project_dir,
        )
        manager.send_bell_if_needed()
        captured = capsys.readouterr()

        # Bell character should be in stderr
        assert "\a" in captured.err

    @patch("core.alerts.urllib.request.urlopen")
    def test_send_webhook(self, mock_urlopen, temp_state_dir, tmp_path, monkeypatch):
        """Should send webhook when configured and alerts exist."""
        # Configure webhook
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({
            "claudeRecall": {
                "alerts": {
                    "enabled": True,
                    "webhookUrl": "https://hooks.example.com/alert",
                }
            }
        }))
        monkeypatch.setenv("CLAUDE_CODE_SETTINGS", str(settings_path))

        # Create log with error to trigger alert
        log_file = temp_state_dir / "debug.log"
        now = datetime.now(timezone.utc)
        events = []
        for i in range(5):
            ts_dt = now - timedelta(hours=i)
            ts = ts_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            events.append(json.dumps({
                "event": "error" if i < 2 else "session_start",
                "timestamp": ts,
                "level": "error" if i < 2 else "info",
            }))
        log_file.write_text("\n".join(events) + "\n")

        # Mock the urlopen response
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"ok": true}'
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        manager = AlertsManager(state_dir=temp_state_dir)
        result = manager.send_webhook()

        assert result is True
        mock_urlopen.assert_called_once()
        # Verify the request was made with correct URL
        call_args = mock_urlopen.call_args
        request = call_args[0][0]
        assert request.full_url == "https://hooks.example.com/alert"

    def test_send_webhook_no_url(self, manager_with_log):
        """Should return False when no webhook URL configured."""
        result = manager_with_log.send_webhook()
        assert result is False


class TestCLIIntegration:
    """Test CLI commands for alerts."""

    @pytest.fixture
    def cli_env(self, temp_state_dir, tmp_path, monkeypatch):
        """Set up environment for CLI tests."""
        # Create project directory
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        monkeypatch.setenv("PROJECT_DIR", str(project_dir))
        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(temp_state_dir))

        return {
            "project_dir": project_dir,
            "state_dir": temp_state_dir,
        }

    def test_alerts_check_command(self, cli_env):
        """alerts check should show current alerts."""
        import subprocess

        result = subprocess.run(
            ["python3", "-m", "core.cli", "alerts", "check"],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "PROJECT_DIR": str(cli_env["project_dir"]),
                "CLAUDE_RECALL_STATE": str(cli_env["state_dir"]),
            },
        )

        # Should exit successfully even with no alerts
        assert result.returncode == 0

    def test_alerts_digest_command(self, cli_env):
        """alerts digest should show daily digest."""
        import subprocess

        result = subprocess.run(
            ["python3", "-m", "core.cli", "alerts", "digest"],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "PROJECT_DIR": str(cli_env["project_dir"]),
                "CLAUDE_RECALL_STATE": str(cli_env["state_dir"]),
            },
        )

        assert result.returncode == 0
        assert "Digest" in result.stdout or "digest" in result.stdout.lower()

    def test_alerts_config_command(self, cli_env):
        """alerts config should show current settings."""
        import subprocess

        result = subprocess.run(
            ["python3", "-m", "core.cli", "alerts", "config"],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "PROJECT_DIR": str(cli_env["project_dir"]),
                "CLAUDE_RECALL_STATE": str(cli_env["state_dir"]),
            },
        )

        assert result.returncode == 0
        # Should show config values
        assert "enabled" in result.stdout.lower() or "Alerts" in result.stdout
