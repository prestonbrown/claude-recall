"""Configuration reader for Claude Recall.

Provides a Python interface to read settings, which can be called from
shell scripts via CLI. Replaces multiple jq calls with a single Python
module for consistent configuration reading.
"""
import json
import os
from pathlib import Path
from typing import Any, Optional


def get_settings_path() -> Path:
    """Get path to Claude Code settings.json.

    Returns:
        Path to settings.json, respecting CLAUDE_CODE_SETTINGS env var.
    """
    custom = os.environ.get("CLAUDE_CODE_SETTINGS")
    if custom:
        return Path(custom)
    return Path.home() / ".claude" / "settings.json"


def get_setting(key: str, default: Any = None) -> Any:
    """Get a setting value by dot-notation key.

    Args:
        key: Dot-notation key like "claudeRecall.debugLevel"
        default: Default value if key not found

    Returns:
        Setting value or default
    """
    settings_path = get_settings_path()

    if not settings_path.exists():
        return default

    try:
        with open(settings_path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError):
        return default

    # Navigate dot-notation path
    parts = key.split(".")
    current = data
    for part in parts:
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]

    return current


def get_bool_setting(key: str, default: bool = False) -> bool:
    """Get a boolean setting.

    Args:
        key: Dot-notation key
        default: Default value if key not found

    Returns:
        Boolean value. Converts string "true", "1", "yes" to True.
    """
    value = get_setting(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    return bool(value)


def get_int_setting(key: str, default: int = 0) -> int:
    """Get an integer setting.

    Args:
        key: Dot-notation key
        default: Default value if key not found or invalid

    Returns:
        Integer value or default if conversion fails.
    """
    value = get_setting(key, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
