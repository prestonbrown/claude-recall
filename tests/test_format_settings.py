#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Tests for format-settings.py JSON formatter."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

FORMATTER_PATH = Path(__file__).parent.parent / "adapters" / "claude-code" / "format-settings.py"


class TestFormatSettings:
    """Tests for the config.json formatter."""

    def test_valid_json_without_hooks(self, tmp_path: Path) -> None:
        """Formatter should produce valid JSON when there are no hooks."""
        settings = {"foo": "bar", "baz": 123}
        input_file = tmp_path / "config.json"
        input_file.write_text(json.dumps(settings))

        result = subprocess.run(
            [sys.executable, str(FORMATTER_PATH), str(input_file)],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, f"Formatter failed: {result.stderr}"
        # Should be valid JSON
        parsed = json.loads(result.stdout)
        assert parsed == settings

    def test_valid_json_with_hooks(self, tmp_path: Path) -> None:
        """Formatter should produce valid JSON when hooks are present."""
        settings = {
            "enabled": True,
            "hooks": {
                "Stop": [{"hooks": [{"type": "command", "command": "echo test", "timeout": 1000}]}]
            },
        }
        input_file = tmp_path / "config.json"
        input_file.write_text(json.dumps(settings))

        result = subprocess.run(
            [sys.executable, str(FORMATTER_PATH), str(input_file)],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, f"Formatter failed: {result.stderr}"
        parsed = json.loads(result.stdout)
        assert parsed == settings

    def test_hook_objects_on_single_line(self, tmp_path: Path) -> None:
        """Hook objects should be formatted on single lines."""
        settings = {
            "hooks": {
                "Stop": [{"hooks": [{"type": "command", "command": "echo test", "timeout": 1000}]}]
            },
        }
        input_file = tmp_path / "config.json"
        input_file.write_text(json.dumps(settings))

        result = subprocess.run(
            [sys.executable, str(FORMATTER_PATH), str(input_file)],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        # Check that hook object is on one line
        assert '{ "type": "command", "command": "echo test", "timeout": 1000 }' in result.stdout

    def test_preserves_all_fields(self, tmp_path: Path) -> None:
        """Formatter should preserve all input fields."""
        settings = {
            "customSetting": True,
            "nested": {"a": 1, "b": 2},
            "array": [1, 2, 3],
            "hooks": {
                "SessionStart": [{"hooks": []}],
                "Stop": [{"hooks": []}],
            },
        }
        input_file = tmp_path / "config.json"
        input_file.write_text(json.dumps(settings))

        result = subprocess.run(
            [sys.executable, str(FORMATTER_PATH), str(input_file)],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        parsed = json.loads(result.stdout)
        assert parsed == settings

    def test_post_tool_use_formatting(self, tmp_path: Path) -> None:
        """PostToolUse entries should be formatted with matcher on own line."""
        settings = {
            "hooks": {
                "PostToolUse": [
                    {
                        "matcher": "ExitPlanMode",
                        "hooks": [{"type": "command", "command": "echo exit", "timeout": 1000}],
                    }
                ]
            },
        }
        input_file = tmp_path / "config.json"
        input_file.write_text(json.dumps(settings))

        result = subprocess.run(
            [sys.executable, str(FORMATTER_PATH), str(input_file)],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        parsed = json.loads(result.stdout)
        assert parsed == settings
        # Check matcher is present
        assert '"matcher": "ExitPlanMode"' in result.stdout
