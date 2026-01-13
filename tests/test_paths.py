"""Tests for centralized path resolution."""
import os
import pytest
from pathlib import Path


class TestPathResolver:
    """Tests for PathResolver centralized path resolution."""

    def test_lessons_base_returns_path(self, monkeypatch):
        """Should return a Path object."""
        # Clear all env vars to get default behavior
        monkeypatch.delenv("CLAUDE_RECALL_BASE", raising=False)
        monkeypatch.delenv("RECALL_BASE", raising=False)
        monkeypatch.delenv("LESSONS_BASE", raising=False)

        from core.paths import PathResolver

        result = PathResolver.lessons_base()
        assert isinstance(result, Path)
        assert result == Path.home() / ".config" / "claude-recall"

    def test_lessons_base_respects_env_var(self, monkeypatch, tmp_path):
        """CLAUDE_RECALL_BASE env var overrides default."""
        custom_base = tmp_path / "custom-base"
        monkeypatch.setenv("CLAUDE_RECALL_BASE", str(custom_base))

        from core.paths import PathResolver

        result = PathResolver.lessons_base()
        assert result == custom_base

    def test_lessons_base_respects_legacy_recall_base(self, monkeypatch, tmp_path):
        """RECALL_BASE env var works as legacy fallback."""
        monkeypatch.delenv("CLAUDE_RECALL_BASE", raising=False)
        custom_base = tmp_path / "recall-base"
        monkeypatch.setenv("RECALL_BASE", str(custom_base))
        monkeypatch.delenv("LESSONS_BASE", raising=False)

        from core.paths import PathResolver

        result = PathResolver.lessons_base()
        assert result == custom_base

    def test_lessons_base_respects_legacy_lessons_base(self, monkeypatch, tmp_path):
        """LESSONS_BASE env var works as legacy fallback."""
        monkeypatch.delenv("CLAUDE_RECALL_BASE", raising=False)
        monkeypatch.delenv("RECALL_BASE", raising=False)
        custom_base = tmp_path / "lessons-base"
        monkeypatch.setenv("LESSONS_BASE", str(custom_base))

        from core.paths import PathResolver

        result = PathResolver.lessons_base()
        assert result == custom_base

    def test_state_dir_returns_xdg_path(self, monkeypatch):
        """Should use XDG_STATE_HOME or fallback to ~/.local/state."""
        monkeypatch.delenv("CLAUDE_RECALL_STATE", raising=False)
        monkeypatch.delenv("XDG_STATE_HOME", raising=False)

        from core.paths import PathResolver

        result = PathResolver.state_dir()
        assert isinstance(result, Path)
        assert result == Path.home() / ".local" / "state" / "claude-recall"

    def test_state_dir_respects_env_var(self, monkeypatch, tmp_path):
        """CLAUDE_RECALL_STATE env var overrides default."""
        custom_state = tmp_path / "custom-state"
        monkeypatch.setenv("CLAUDE_RECALL_STATE", str(custom_state))

        from core.paths import PathResolver

        result = PathResolver.state_dir()
        assert result == custom_state

    def test_state_dir_respects_xdg_state_home(self, monkeypatch, tmp_path):
        """XDG_STATE_HOME is used when CLAUDE_RECALL_STATE is not set."""
        monkeypatch.delenv("CLAUDE_RECALL_STATE", raising=False)
        xdg_state = tmp_path / "xdg-state"
        monkeypatch.setenv("XDG_STATE_HOME", str(xdg_state))

        from core.paths import PathResolver

        result = PathResolver.state_dir()
        assert result == xdg_state / "claude-recall"

    def test_project_data_dir_returns_claude_recall_subdir(self, tmp_path):
        """Given project root, returns .claude-recall subdir."""
        from core.paths import PathResolver

        result = PathResolver.project_data_dir(tmp_path)
        assert result == tmp_path / ".claude-recall"

    def test_project_data_dir_prefers_existing_claude_recall(self, tmp_path):
        """Prefers .claude-recall if it exists."""
        from core.paths import PathResolver

        # Create .claude-recall directory
        claude_recall_dir = tmp_path / ".claude-recall"
        claude_recall_dir.mkdir()

        result = PathResolver.project_data_dir(tmp_path)
        assert result == claude_recall_dir

    def test_project_data_dir_falls_back_to_recall(self, tmp_path):
        """Falls back to .recall if it exists and .claude-recall doesn't."""
        from core.paths import PathResolver

        # Create .recall directory (legacy)
        recall_dir = tmp_path / ".recall"
        recall_dir.mkdir()

        result = PathResolver.project_data_dir(tmp_path)
        assert result == recall_dir

    def test_project_data_dir_falls_back_to_legacy(self, tmp_path):
        """Falls back to .coding-agent-lessons if it exists."""
        from core.paths import PathResolver

        # Create legacy directory
        legacy_dir = tmp_path / ".coding-agent-lessons"
        legacy_dir.mkdir()

        result = PathResolver.project_data_dir(tmp_path)
        assert result == legacy_dir

    def test_project_data_dir_prefers_claude_recall_over_legacy(self, tmp_path):
        """Prefers .claude-recall over legacy directories if both exist."""
        from core.paths import PathResolver

        # Create both directories
        claude_recall_dir = tmp_path / ".claude-recall"
        claude_recall_dir.mkdir()
        recall_dir = tmp_path / ".recall"
        recall_dir.mkdir()
        legacy_dir = tmp_path / ".coding-agent-lessons"
        legacy_dir.mkdir()

        result = PathResolver.project_data_dir(tmp_path)
        assert result == claude_recall_dir
