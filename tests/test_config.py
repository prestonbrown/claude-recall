"""Tests for configuration reader module."""
import json
import os
import subprocess
import sys
import pytest
from pathlib import Path


class TestGetSettingsPath:
    """Tests for get_settings_path function."""

    def test_returns_default_path_when_no_env_var(self, monkeypatch):
        """Default path should be ~/.claude/settings.json."""
        monkeypatch.delenv("CLAUDE_CODE_SETTINGS", raising=False)

        from core.config import get_settings_path

        result = get_settings_path()
        assert isinstance(result, Path)
        assert result == Path.home() / ".claude" / "settings.json"

    def test_respects_env_var_override(self, tmp_path, monkeypatch):
        """CLAUDE_CODE_SETTINGS env var overrides default path."""
        custom_path = tmp_path / "custom" / "settings.json"
        monkeypatch.setenv("CLAUDE_CODE_SETTINGS", str(custom_path))

        from core.config import get_settings_path

        result = get_settings_path()
        assert result == custom_path


class TestGetSetting:
    """Tests for get_setting function."""

    def test_returns_default_when_file_missing(self, tmp_path, monkeypatch):
        """When settings.json doesn't exist, return default."""
        nonexistent = tmp_path / "nonexistent" / "settings.json"
        monkeypatch.setenv("CLAUDE_CODE_SETTINGS", str(nonexistent))

        from core.config import get_setting

        result = get_setting("someKey", default="fallback")
        assert result == "fallback"

    def test_returns_default_when_key_missing(self, tmp_path, monkeypatch):
        """When key doesn't exist in settings, return default."""
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({"otherKey": "value"}))
        monkeypatch.setenv("CLAUDE_CODE_SETTINGS", str(settings_path))

        from core.config import get_setting

        result = get_setting("missingKey", default="default_value")
        assert result == "default_value"

    def test_reads_simple_key(self, tmp_path, monkeypatch):
        """Reads a simple top-level key."""
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({"simpleKey": "the_value"}))
        monkeypatch.setenv("CLAUDE_CODE_SETTINGS", str(settings_path))

        from core.config import get_setting

        result = get_setting("simpleKey")
        assert result == "the_value"

    def test_reads_nested_key_with_dot_notation(self, tmp_path, monkeypatch):
        """Supports dot-notation for nested keys like 'claudeRecall.debugLevel'."""
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({
            "claudeRecall": {
                "debugLevel": 2,
                "nested": {
                    "deep": "value"
                }
            }
        }))
        monkeypatch.setenv("CLAUDE_CODE_SETTINGS", str(settings_path))

        from core.config import get_setting

        result = get_setting("claudeRecall.debugLevel")
        assert result == 2

        result_deep = get_setting("claudeRecall.nested.deep")
        assert result_deep == "value"

    def test_returns_default_for_partial_nested_path(self, tmp_path, monkeypatch):
        """Returns default when nested path doesn't fully exist."""
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({"claudeRecall": {"other": "value"}}))
        monkeypatch.setenv("CLAUDE_CODE_SETTINGS", str(settings_path))

        from core.config import get_setting

        result = get_setting("claudeRecall.debugLevel", default=0)
        assert result == 0

    def test_handles_invalid_json_gracefully(self, tmp_path, monkeypatch):
        """Invalid JSON returns default without raising."""
        settings_path = tmp_path / "settings.json"
        settings_path.write_text("not valid json {{{")
        monkeypatch.setenv("CLAUDE_CODE_SETTINGS", str(settings_path))

        from core.config import get_setting

        result = get_setting("anyKey", default="safe_default")
        assert result == "safe_default"

    def test_returns_none_as_default(self, tmp_path, monkeypatch):
        """Default of None is supported."""
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({}))
        monkeypatch.setenv("CLAUDE_CODE_SETTINGS", str(settings_path))

        from core.config import get_setting

        result = get_setting("missing")
        assert result is None


class TestGetBoolSetting:
    """Tests for get_bool_setting function."""

    def test_returns_true_for_bool_true(self, tmp_path, monkeypatch):
        """Boolean true value returns True."""
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({"enabled": True}))
        monkeypatch.setenv("CLAUDE_CODE_SETTINGS", str(settings_path))

        from core.config import get_bool_setting

        result = get_bool_setting("enabled")
        assert result is True

    def test_returns_false_for_bool_false(self, tmp_path, monkeypatch):
        """Boolean false value returns False."""
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({"disabled": False}))
        monkeypatch.setenv("CLAUDE_CODE_SETTINGS", str(settings_path))

        from core.config import get_bool_setting

        result = get_bool_setting("disabled")
        assert result is False

    def test_converts_string_true(self, tmp_path, monkeypatch):
        """String 'true' converts to True."""
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({"flag": "true"}))
        monkeypatch.setenv("CLAUDE_CODE_SETTINGS", str(settings_path))

        from core.config import get_bool_setting

        result = get_bool_setting("flag")
        assert result is True

    def test_converts_string_yes(self, tmp_path, monkeypatch):
        """String 'yes' converts to True."""
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({"flag": "yes"}))
        monkeypatch.setenv("CLAUDE_CODE_SETTINGS", str(settings_path))

        from core.config import get_bool_setting

        result = get_bool_setting("flag")
        assert result is True

    def test_converts_string_1(self, tmp_path, monkeypatch):
        """String '1' converts to True."""
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({"flag": "1"}))
        monkeypatch.setenv("CLAUDE_CODE_SETTINGS", str(settings_path))

        from core.config import get_bool_setting

        result = get_bool_setting("flag")
        assert result is True

    def test_returns_default_when_missing(self, tmp_path, monkeypatch):
        """Returns default when setting is missing."""
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({}))
        monkeypatch.setenv("CLAUDE_CODE_SETTINGS", str(settings_path))

        from core.config import get_bool_setting

        result = get_bool_setting("missing", default=True)
        assert result is True

        result_false = get_bool_setting("missing", default=False)
        assert result_false is False

    def test_nested_bool_setting(self, tmp_path, monkeypatch):
        """Supports dot-notation for nested boolean settings."""
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({
            "claudeRecall": {
                "features": {
                    "autoDecay": True
                }
            }
        }))
        monkeypatch.setenv("CLAUDE_CODE_SETTINGS", str(settings_path))

        from core.config import get_bool_setting

        result = get_bool_setting("claudeRecall.features.autoDecay")
        assert result is True


class TestGetIntSetting:
    """Tests for get_int_setting function."""

    def test_returns_int_value(self, tmp_path, monkeypatch):
        """Integer value is returned as-is."""
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({"level": 3}))
        monkeypatch.setenv("CLAUDE_CODE_SETTINGS", str(settings_path))

        from core.config import get_int_setting

        result = get_int_setting("level")
        assert result == 3
        assert isinstance(result, int)

    def test_converts_string_to_int(self, tmp_path, monkeypatch):
        """String number is converted to int."""
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({"level": "5"}))
        monkeypatch.setenv("CLAUDE_CODE_SETTINGS", str(settings_path))

        from core.config import get_int_setting

        result = get_int_setting("level")
        assert result == 5
        assert isinstance(result, int)

    def test_returns_default_for_invalid_int(self, tmp_path, monkeypatch):
        """Non-numeric string returns default."""
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({"level": "not_a_number"}))
        monkeypatch.setenv("CLAUDE_CODE_SETTINGS", str(settings_path))

        from core.config import get_int_setting

        result = get_int_setting("level", default=0)
        assert result == 0

    def test_returns_default_when_missing(self, tmp_path, monkeypatch):
        """Returns default when setting is missing."""
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({}))
        monkeypatch.setenv("CLAUDE_CODE_SETTINGS", str(settings_path))

        from core.config import get_int_setting

        result = get_int_setting("missing", default=42)
        assert result == 42

    def test_nested_int_setting(self, tmp_path, monkeypatch):
        """Supports dot-notation for nested integer settings."""
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({
            "claudeRecall": {
                "debugLevel": 2
            }
        }))
        monkeypatch.setenv("CLAUDE_CODE_SETTINGS", str(settings_path))

        from core.config import get_int_setting

        result = get_int_setting("claudeRecall.debugLevel")
        assert result == 2


class TestConfigCLI:
    """Tests for CLI config command."""

    def test_cli_config_reads_string(self, tmp_path, isolated_subprocess_env):
        """CLI config command reads string values."""
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({"myKey": "myValue"}))

        env = {**isolated_subprocess_env, "CLAUDE_CODE_SETTINGS": str(settings_path)}
        result = subprocess.run(
            [sys.executable, "core/cli.py", "config", "myKey"],
            capture_output=True,
            text=True,
            env=env,
            cwd="/Users/pbrown/Code/claude-recall",
        )

        assert result.returncode == 0
        assert result.stdout.strip() == "myValue"

    def test_cli_config_reads_nested_key(self, tmp_path, isolated_subprocess_env):
        """CLI config command reads nested dot-notation keys."""
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({
            "claudeRecall": {"debugLevel": 3}
        }))

        env = {**isolated_subprocess_env, "CLAUDE_CODE_SETTINGS": str(settings_path)}
        result = subprocess.run(
            [sys.executable, "core/cli.py", "config", "claudeRecall.debugLevel"],
            capture_output=True,
            text=True,
            env=env,
            cwd="/Users/pbrown/Code/claude-recall",
        )

        assert result.returncode == 0
        assert result.stdout.strip() == "3"

    def test_cli_config_uses_default(self, tmp_path, isolated_subprocess_env):
        """CLI config command returns default when key missing."""
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({}))

        env = {**isolated_subprocess_env, "CLAUDE_CODE_SETTINGS": str(settings_path)}
        result = subprocess.run(
            [sys.executable, "core/cli.py", "config", "missing", "-d", "fallback"],
            capture_output=True,
            text=True,
            env=env,
            cwd="/Users/pbrown/Code/claude-recall",
        )

        assert result.returncode == 0
        assert result.stdout.strip() == "fallback"

    def test_cli_config_bool_type(self, tmp_path, isolated_subprocess_env):
        """CLI config command handles bool type correctly."""
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({"enabled": True}))

        env = {**isolated_subprocess_env, "CLAUDE_CODE_SETTINGS": str(settings_path)}
        result = subprocess.run(
            [sys.executable, "core/cli.py", "config", "enabled", "-t", "bool"],
            capture_output=True,
            text=True,
            env=env,
            cwd="/Users/pbrown/Code/claude-recall",
        )

        assert result.returncode == 0
        assert result.stdout.strip() == "true"

    def test_cli_config_int_type(self, tmp_path, isolated_subprocess_env):
        """CLI config command handles int type correctly."""
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({"count": 42}))

        env = {**isolated_subprocess_env, "CLAUDE_CODE_SETTINGS": str(settings_path)}
        result = subprocess.run(
            [sys.executable, "core/cli.py", "config", "count", "-t", "int"],
            capture_output=True,
            text=True,
            env=env,
            cwd="/Users/pbrown/Code/claude-recall",
        )

        assert result.returncode == 0
        assert result.stdout.strip() == "42"

    def test_cli_config_missing_returns_empty(self, tmp_path, isolated_subprocess_env):
        """CLI config command returns empty string for missing key without default."""
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({}))

        env = {**isolated_subprocess_env, "CLAUDE_CODE_SETTINGS": str(settings_path)}
        result = subprocess.run(
            [sys.executable, "core/cli.py", "config", "nonexistent"],
            capture_output=True,
            text=True,
            env=env,
            cwd="/Users/pbrown/Code/claude-recall",
        )

        assert result.returncode == 0
        assert result.stdout.strip() == ""
