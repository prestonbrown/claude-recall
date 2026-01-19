"""Centralized path resolution for Claude Recall.

All path resolution should go through this module to ensure consistency.
"""
import os
from pathlib import Path


class PathResolver:
    """Resolves paths for Claude Recall components."""

    @staticmethod
    def lessons_base() -> Path:
        """Get the base directory for code/system lessons.

        Resolution order:
        1. CLAUDE_RECALL_BASE env var
        2. RECALL_BASE env var (legacy)
        3. LESSONS_BASE env var (legacy)
        4. ~/.config/claude-recall
        """
        base = (
            os.environ.get("CLAUDE_RECALL_BASE")
            or os.environ.get("RECALL_BASE")
            or os.environ.get("LESSONS_BASE")
        )
        if base:
            return Path(base)
        return Path.home() / ".config" / "claude-recall"

    @staticmethod
    def state_dir() -> Path:
        """Get the state directory for mutable data (lessons, decay, logs).

        Resolution order:
        1. CLAUDE_RECALL_STATE env var
        2. XDG_STATE_HOME/claude-recall
        3. ~/.local/state/claude-recall
        """
        state = os.environ.get("CLAUDE_RECALL_STATE")
        if state:
            return Path(state)
        xdg_state = os.environ.get("XDG_STATE_HOME")
        if xdg_state:
            return Path(xdg_state) / "claude-recall"
        return Path.home() / ".local" / "state" / "claude-recall"

    @staticmethod
    def project_data_dir(project_root: Path) -> Path:
        """Get the project-specific data directory.

        Checks for directories in order of precedence:
        .claude-recall/ -> .recall/ -> .coding-agent-lessons/ -> default (.claude-recall/)

        Args:
            project_root: The project root directory

        Returns:
            Path to the project data directory
        """
        claude_recall_dir = project_root / ".claude-recall"
        recall_dir = project_root / ".recall"
        legacy_dir = project_root / ".coding-agent-lessons"

        # Prefer new directory if it exists, otherwise check legacy paths
        if claude_recall_dir.exists():
            return claude_recall_dir
        elif recall_dir.exists():
            return recall_dir
        elif legacy_dir.exists():
            return legacy_dir
        else:
            # Default to new directory for new projects
            return claude_recall_dir
