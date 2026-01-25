#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
LessonsManager class - Main entry point for Claude Recall.

This module provides the LessonsManager class that combines lesson and handoff
functionality through composition of mixins.
"""

import json
import os
from pathlib import Path

# Handle both module import and direct script execution
try:
    from core.debug_logger import get_logger
except ImportError:
    from debug_logger import get_logger

# Default values for configurable settings
DEFAULT_PROMOTION_THRESHOLD = 50
DEFAULT_MAX_LESSONS = 30
CLAUDE_RECALL_CONFIG_PATH = Path(os.environ.get("CLAUDE_RECALL_CONFIG", "")) if os.environ.get("CLAUDE_RECALL_CONFIG") else Path.home() / ".config" / "claude-recall" / "config.json"


def _read_claude_recall_settings() -> dict:
    """Read Claude Recall settings from ~/.config/claude-recall/config.json.

    Returns dict with settings or empty dict if not available.
    """
    try:
        if not CLAUDE_RECALL_CONFIG_PATH.exists():
            return {}
        with open(CLAUDE_RECALL_CONFIG_PATH) as f:
            settings = json.load(f)
        return settings if isinstance(settings, dict) else {}
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        return {}


# Handle both module import and direct script execution
try:
    from core.lessons import LessonsMixin
    from core.handoffs import HandoffsMixin
    from core.paths import PathResolver
except ImportError:
    from lessons import LessonsMixin
    from handoffs import HandoffsMixin
    from paths import PathResolver


class LessonsManager(LessonsMixin, HandoffsMixin):
    """
    Manager for AI coding agent lessons.

    Provides methods to add, cite, edit, delete, promote, and list lessons
    stored in markdown format.

    This class composes functionality from:
    - LessonsMixin: All lesson-related operations
    - HandoffsMixin: All handoff-related operations (formerly ApproachesMixin)
    """

    def __init__(self, lessons_base: Path, project_root: Path):
        """
        Initialize the lessons manager.

        Args:
            lessons_base: Base directory for code (~/.config/claude-recall)
            project_root: Root directory of the project (containing .git)
        """
        self.lessons_base = Path(lessons_base)
        self.project_root = Path(project_root)

        # State directory for mutable data (XDG compliant)
        self.state_dir = PathResolver.state_dir()
        self.state_dir.mkdir(parents=True, exist_ok=True)

        # Auto-migrate system lessons from old location
        self._migrate_system_lessons()

        self.system_lessons_file = self.state_dir / "LESSONS.md"
        self._decay_state_file = self.state_dir / ".decay-last-run"
        self._session_state_dir = self.state_dir / ".citation-state"

        # Warn if lessons exist in config dir but not being used
        config_lessons = self.lessons_base / "LESSONS.md"
        if config_lessons.exists() and self.system_lessons_file.exists():
            # Both exist - the one in state_dir takes precedence, config is ignored
            import sys
            print(
                f"Warning: System lessons found in both {config_lessons} and {self.system_lessons_file}. "
                f"Using {self.system_lessons_file} (state dir). "
                f"To merge, manually combine files then delete {config_lessons}",
                file=sys.stderr
            )

        # Get project data directory (prefers .claude-recall/ over legacy paths)
        project_data_dir = PathResolver.project_data_dir(self.project_root)
        self.project_lessons_file = project_data_dir / "LESSONS.md"

        # Ensure project directory exists with auto-gitignore
        project_data_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_gitignore(project_data_dir)

        # Read configurable settings from ~/.config/claude-recall/config.json
        recall_settings = _read_claude_recall_settings()
        self.promotion_threshold = recall_settings.get(
            "promotionThreshold", DEFAULT_PROMOTION_THRESHOLD
        )
        self.max_lessons = recall_settings.get("maxLessons", DEFAULT_MAX_LESSONS)

        # Auto-migration cache (triggers migration runs once per session)
        self._migration_done = False

    def _migrate_system_lessons(self) -> None:
        """Migrate system lessons from old ~/.config location to ~/.local/state."""
        old_location = self.lessons_base / "LESSONS.md"
        new_location = self.state_dir / "LESSONS.md"

        # Only migrate if old exists and new doesn't
        if old_location.exists() and not new_location.exists():
            import shutil
            shutil.move(str(old_location), str(new_location))

            # Also migrate state files if they exist
            for state_file in [".decay-last-run"]:
                old_state = self.lessons_base / state_file
                if old_state.exists():
                    shutil.move(str(old_state), str(self.state_dir / state_file))

            # Migrate citation-state directory
            old_citation_dir = self.lessons_base / ".citation-state"
            if old_citation_dir.exists():
                shutil.move(str(old_citation_dir), str(self.state_dir / ".citation-state"))

    def _ensure_gitignore(self, project_data_dir: Path) -> None:
        """Create .gitignore in project data dir if it doesn't exist."""
        gitignore = project_data_dir / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text("# Auto-generated - claude-recall data\n*\n")
