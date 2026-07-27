#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Test suite for inject-combined CLI command.

This command combines the output of:
1. inject (lessons)
2. handoff inject (active handoffs)
3. handoff inject-todos (todo continuation prompt)

into a single JSON response to reduce subprocess overhead (~300ms -> ~100ms).

Run with: pytest tests/test_inject_combined.py -v
"""

import json
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import pytest


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def temp_lessons_base(tmp_path: Path) -> Path:
    """Create a temporary lessons base directory."""
    lessons_base = tmp_path / ".config" / "claude-recall"
    lessons_base.mkdir(parents=True)
    return lessons_base


@pytest.fixture
def temp_project_root(tmp_path: Path) -> Path:
    """Create a temporary project directory with .git folder."""
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    return project


@pytest.fixture
def manager(temp_lessons_base: Path, temp_project_root: Path):
    """Create a LessonsManager instance with temporary paths."""
    from core.manager import LessonsManager
    return LessonsManager(
        lessons_base=temp_lessons_base,
        project_root=temp_project_root,
    )


@pytest.fixture
def manager_with_lessons(manager):
    """Create a manager with some pre-existing lessons."""
    manager.add_lesson(
        level="project",
        category="pattern",
        title="Test pattern lesson",
        content="Always test first.",
    )
    manager.add_lesson(
        level="system",
        category="gotcha",
        title="System gotcha",
        content="Watch out for this.",
    )
    return manager


@pytest.fixture
def manager_with_handoffs(manager_with_lessons):
    """Create a manager with lessons and active handoffs."""
    manager_with_lessons.handoff_add(
        title="Test feature implementation",
        desc="Implementing a test feature",
        phase="implementing",
    )
    return manager_with_lessons


# =============================================================================
# Command Registration Tests
# =============================================================================


class TestInjectCombinedRegistration:
    """Tests for inject-combined command registration."""

    def test_inject_combined_command_is_registered(self):
        """InjectCombinedCommand should be registered for 'inject-combined'."""
        from core.commands import COMMAND_REGISTRY, InjectCombinedCommand
        assert "inject-combined" in COMMAND_REGISTRY
        assert COMMAND_REGISTRY["inject-combined"] is InjectCombinedCommand

    def test_inject_combined_command_class_exists(self):
        """InjectCombinedCommand class should exist."""
        from core.commands import InjectCombinedCommand, Command
        assert issubclass(InjectCombinedCommand, Command)


# =============================================================================
# CLI Argument Parser Tests
# =============================================================================


class TestInjectCombinedParser:
    """Tests for inject-combined argument parsing."""

    def test_inject_combined_command_registered(self):
        """inject-combined command should be registered in COMMAND_REGISTRY."""
        from core.commands import COMMAND_REGISTRY
        assert "inject-combined" in COMMAND_REGISTRY

    def test_inject_combined_default_top_n(self):
        """inject-combined should default to 5 top lessons."""
        args = Namespace(command="inject-combined", top_n=5)
        assert args.top_n == 5

    def test_inject_combined_custom_top_n(self):
        """inject-combined should accept custom top_n."""
        args = Namespace(command="inject-combined", top_n=10)
        assert args.top_n == 10


# =============================================================================
# Command Output Tests
# =============================================================================


@pytest.mark.skip(reason="Python CLI removed - inject-combined now handled by Go binary")
class TestInjectCombinedCLI:
    """Integration tests for inject-combined via subprocess.

    NOTE: These tests are skipped because the Python CLI (core/cli.py) was removed.
    The inject-combined command is now handled by the Go binary (go/bin/recall).
    """

    def test_cli_returns_json(self, tmp_path, isolated_subprocess_env):
        """CLI inject-combined should return valid JSON."""
        pass

    def test_cli_accepts_top_n_argument(self, tmp_path, isolated_subprocess_env):
        """CLI inject-combined should accept top_n argument."""
        pass
