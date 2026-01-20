#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Test suite for CLI Command pattern implementation.

This is a TDD test file - tests are written BEFORE the implementation.
Run with: pytest tests/test_cli_commands.py -v

The Command pattern provides:
- Abstract Command base class with execute() method
- Command registry for dispatch
- Incremental migration path from if-elif chain
"""

import pytest
from abc import ABC
from argparse import Namespace
from pathlib import Path


# =============================================================================
# Command Pattern Structure Tests
# =============================================================================


class TestCommandPatternStructure:
    """Tests for the Command pattern base structure."""

    def test_command_module_exists(self):
        """The commands module should exist."""
        from core import commands
        assert commands is not None

    def test_command_is_abstract_base_class(self):
        """Command should be an abstract base class."""
        from core.commands import Command
        assert issubclass(Command, ABC)

    def test_command_has_execute_method(self):
        """Command should have an abstract execute method."""
        from core.commands import Command
        # ABC with abstractmethod means it can't be instantiated directly
        with pytest.raises(TypeError, match="abstract"):
            Command()

    def test_command_execute_signature(self):
        """Execute method should accept args and manager parameters."""
        from core.commands import Command
        import inspect
        sig = inspect.signature(Command.execute)
        params = list(sig.parameters.keys())
        assert "args" in params
        assert "manager" in params

    def test_command_registry_exists(self):
        """COMMAND_REGISTRY should be a dict."""
        from core.commands import COMMAND_REGISTRY
        assert isinstance(COMMAND_REGISTRY, dict)

    def test_dispatch_command_function_exists(self):
        """dispatch_command function should exist."""
        from core.commands import dispatch_command
        assert callable(dispatch_command)


# =============================================================================
# Command Registration Tests
# =============================================================================


class TestCommandRegistration:
    """Tests for command registration in the registry."""

    def test_add_command_is_registered(self):
        """AddCommand should be registered for 'add'."""
        from core.commands import COMMAND_REGISTRY, AddCommand
        assert "add" in COMMAND_REGISTRY
        assert COMMAND_REGISTRY["add"] is AddCommand

    def test_add_ai_command_is_registered(self):
        """AddAICommand should be registered for 'add-ai'."""
        from core.commands import COMMAND_REGISTRY, AddAICommand
        assert "add-ai" in COMMAND_REGISTRY
        assert COMMAND_REGISTRY["add-ai"] is AddAICommand

    def test_add_system_command_is_registered(self):
        """AddSystemCommand should be registered for 'add-system'."""
        from core.commands import COMMAND_REGISTRY, AddSystemCommand
        assert "add-system" in COMMAND_REGISTRY
        assert COMMAND_REGISTRY["add-system"] is AddSystemCommand

    def test_cite_command_is_registered(self):
        """CiteCommand should be registered for 'cite'."""
        from core.commands import COMMAND_REGISTRY, CiteCommand
        assert "cite" in COMMAND_REGISTRY
        assert COMMAND_REGISTRY["cite"] is CiteCommand

    def test_inject_command_is_registered(self):
        """InjectCommand should be registered for 'inject'."""
        from core.commands import COMMAND_REGISTRY, InjectCommand
        assert "inject" in COMMAND_REGISTRY
        assert COMMAND_REGISTRY["inject"] is InjectCommand

    def test_list_command_is_registered(self):
        """ListCommand should be registered for 'list'."""
        from core.commands import COMMAND_REGISTRY, ListCommand
        assert "list" in COMMAND_REGISTRY
        assert COMMAND_REGISTRY["list"] is ListCommand

    def test_search_command_is_registered(self):
        """SearchCommand should be registered for 'search'."""
        from core.commands import COMMAND_REGISTRY, SearchCommand
        assert "search" in COMMAND_REGISTRY
        assert COMMAND_REGISTRY["search"] is SearchCommand

    def test_show_command_is_registered(self):
        """ShowCommand should be registered for 'show'."""
        from core.commands import COMMAND_REGISTRY, ShowCommand
        assert "show" in COMMAND_REGISTRY
        assert COMMAND_REGISTRY["show"] is ShowCommand

    def test_decay_command_is_registered(self):
        """DecayCommand should be registered for 'decay'."""
        from core.commands import COMMAND_REGISTRY, DecayCommand
        assert "decay" in COMMAND_REGISTRY
        assert COMMAND_REGISTRY["decay"] is DecayCommand

    def test_edit_command_is_registered(self):
        """EditCommand should be registered for 'edit'."""
        from core.commands import COMMAND_REGISTRY, EditCommand
        assert "edit" in COMMAND_REGISTRY
        assert COMMAND_REGISTRY["edit"] is EditCommand

    def test_delete_command_is_registered(self):
        """DeleteCommand should be registered for 'delete'."""
        from core.commands import COMMAND_REGISTRY, DeleteCommand
        assert "delete" in COMMAND_REGISTRY
        assert COMMAND_REGISTRY["delete"] is DeleteCommand

    def test_promote_command_is_registered(self):
        """PromoteCommand should be registered for 'promote'."""
        from core.commands import COMMAND_REGISTRY, PromoteCommand
        assert "promote" in COMMAND_REGISTRY
        assert COMMAND_REGISTRY["promote"] is PromoteCommand

    def test_score_relevance_command_is_registered(self):
        """ScoreRelevanceCommand should be registered for 'score-relevance'."""
        from core.commands import COMMAND_REGISTRY, ScoreRelevanceCommand
        assert "score-relevance" in COMMAND_REGISTRY
        assert COMMAND_REGISTRY["score-relevance"] is ScoreRelevanceCommand


# =============================================================================
# Command Execution Tests
# =============================================================================


class TestCommandExecution:
    """Tests for command execution behavior."""

    @pytest.fixture
    def temp_lessons_base(self, tmp_path: Path) -> Path:
        """Create a temporary lessons base directory."""
        lessons_base = tmp_path / ".config" / "claude-recall"
        lessons_base.mkdir(parents=True)
        return lessons_base

    @pytest.fixture
    def temp_project_root(self, tmp_path: Path) -> Path:
        """Create a temporary project directory with .git folder."""
        project = tmp_path / "project"
        project.mkdir()
        (project / ".git").mkdir()
        (project / ".claude-recall").mkdir()
        return project

    @pytest.fixture
    def manager(self, temp_lessons_base: Path, temp_project_root: Path):
        """Create a LessonsManager instance with temporary paths."""
        from core.manager import LessonsManager
        return LessonsManager(
            lessons_base=temp_lessons_base,
            project_root=temp_project_root,
        )

    def test_add_command_executes_successfully(
        self, manager, temp_lessons_base, temp_project_root, capsys
    ):
        """AddCommand.execute should add a lesson and return 0."""
        from core.commands import AddCommand

        args = Namespace(
            command="add",
            category="pattern",
            title="Test Pattern",
            content="Test content here",
            system=False,
            force=False,
            no_promote=False,
            type="",
        )

        cmd = AddCommand()
        result = cmd.execute(args, manager)

        assert result == 0
        captured = capsys.readouterr()
        assert "L001" in captured.out
        assert "Test Pattern" in captured.out

    def test_add_command_with_system_flag(
        self, manager, temp_lessons_base, temp_project_root, capsys
    ):
        """AddCommand with --system flag should add system lesson."""
        from core.commands import AddCommand

        args = Namespace(
            command="add",
            category="preference",
            title="System Pref",
            content="Always do this",
            system=True,
            force=False,
            no_promote=False,
            type="",
        )

        cmd = AddCommand()
        result = cmd.execute(args, manager)

        assert result == 0
        captured = capsys.readouterr()
        assert "S001" in captured.out
        assert "system" in captured.out.lower()

    def test_cite_command_executes_successfully(
        self, manager, temp_lessons_base, temp_project_root, capsys
    ):
        """CiteCommand.execute should cite a lesson and return 0."""
        from core.commands import CiteCommand

        # First add a lesson
        manager.add_lesson(
            level="project",
            category="pattern",
            title="Test",
            content="Content",
        )

        args = Namespace(
            command="cite",
            lesson_ids=["L001"],
        )

        cmd = CiteCommand()
        result = cmd.execute(args, manager)

        assert result == 0
        captured = capsys.readouterr()
        assert "OK" in captured.out

    def test_cite_command_handles_multiple_ids(
        self, manager, temp_lessons_base, temp_project_root, capsys
    ):
        """CiteCommand should handle multiple lesson IDs."""
        from core.commands import CiteCommand

        # Add two lessons
        manager.add_lesson(level="project", category="pattern", title="Test1", content="C1")
        manager.add_lesson(level="project", category="pattern", title="Test2", content="C2")

        args = Namespace(
            command="cite",
            lesson_ids=["L001", "L002"],
        )

        cmd = CiteCommand()
        result = cmd.execute(args, manager)

        assert result == 0
        captured = capsys.readouterr()
        # Should have output for both citations
        assert captured.out.count("OK") == 2

    def test_inject_command_executes_successfully(
        self, manager, temp_lessons_base, temp_project_root, capsys
    ):
        """InjectCommand.execute should output lessons context."""
        from core.commands import InjectCommand

        # Add a lesson to inject
        manager.add_lesson(
            level="project",
            category="pattern",
            title="Inject Me",
            content="Important content",
        )

        args = Namespace(
            command="inject",
            top_n=5,
        )

        cmd = InjectCommand()
        result = cmd.execute(args, manager)

        assert result == 0
        captured = capsys.readouterr()
        assert "Inject Me" in captured.out or "L001" in captured.out

    def test_list_command_executes_successfully(
        self, manager, temp_lessons_base, temp_project_root, capsys
    ):
        """ListCommand.execute should list lessons."""
        from core.commands import ListCommand

        # Add some lessons
        manager.add_lesson(level="project", category="pattern", title="Listed", content="C")

        args = Namespace(
            command="list",
            project=False,
            system=False,
            search=None,
            category=None,
            stale=False,
        )

        cmd = ListCommand()
        result = cmd.execute(args, manager)

        assert result == 0
        captured = capsys.readouterr()
        assert "Listed" in captured.out or "L001" in captured.out

    def test_search_command_executes_successfully(
        self, manager, temp_lessons_base, temp_project_root, capsys
    ):
        """SearchCommand.execute should search lessons by keyword."""
        from core.commands import SearchCommand

        # Add some lessons with searchable content
        manager.add_lesson(
            level="project", category="pattern", title="Git workflow", content="Use git add -p"
        )
        manager.add_lesson(
            level="project", category="pattern", title="Testing tips", content="Write tests first"
        )

        args = Namespace(
            command="search",
            term="git",
        )

        cmd = SearchCommand()
        result = cmd.execute(args, manager)

        assert result == 0
        captured = capsys.readouterr()
        assert "Git workflow" in captured.out
        assert "Testing tips" not in captured.out
        assert "Found: 1 lesson(s)" in captured.out

    def test_search_command_no_results(
        self, manager, temp_lessons_base, temp_project_root, capsys
    ):
        """SearchCommand.execute should handle no matches gracefully."""
        from core.commands import SearchCommand

        manager.add_lesson(
            level="project", category="pattern", title="Testing tips", content="Write tests first"
        )

        args = Namespace(
            command="search",
            term="nonexistent",
        )

        cmd = SearchCommand()
        result = cmd.execute(args, manager)

        assert result == 0
        captured = capsys.readouterr()
        assert "No lessons found matching 'nonexistent'" in captured.out

    def test_show_command_executes_successfully(
        self, manager, temp_lessons_base, temp_project_root, capsys
    ):
        """ShowCommand.execute should show lesson details."""
        from core.commands import ShowCommand

        manager.add_lesson(
            level="project",
            category="correction",
            title="Important lesson",
            content="This is the detailed content of the lesson",
        )

        args = Namespace(
            command="show",
            lesson_id="L001",
        )

        cmd = ShowCommand()
        result = cmd.execute(args, manager)

        assert result == 0
        captured = capsys.readouterr()
        assert "Important lesson" in captured.out
        assert "correction" in captured.out
        assert "This is the detailed content" in captured.out
        assert "Level: Project" in captured.out

    def test_show_command_nonexistent_lesson(
        self, manager, temp_lessons_base, temp_project_root, capsys
    ):
        """ShowCommand.execute should handle nonexistent lessons."""
        from core.commands import ShowCommand

        args = Namespace(
            command="show",
            lesson_id="L999",
        )

        cmd = ShowCommand()
        result = cmd.execute(args, manager)

        assert result == 1
        captured = capsys.readouterr()
        assert "Lesson not found: L999" in captured.out

    def test_delete_command_executes_successfully(
        self, manager, temp_lessons_base, temp_project_root, capsys
    ):
        """DeleteCommand.execute should delete a lesson."""
        from core.commands import DeleteCommand

        # Add then delete
        manager.add_lesson(level="project", category="pattern", title="Gone", content="C")

        args = Namespace(
            command="delete",
            lesson_id="L001",
        )

        cmd = DeleteCommand()
        result = cmd.execute(args, manager)

        assert result == 0
        captured = capsys.readouterr()
        assert "Deleted" in captured.out
        assert "L001" in captured.out


# =============================================================================
# Dispatch Tests
# =============================================================================


class TestDispatchCommand:
    """Tests for the dispatch_command function."""

    @pytest.fixture
    def temp_lessons_base(self, tmp_path: Path) -> Path:
        """Create a temporary lessons base directory."""
        lessons_base = tmp_path / ".config" / "claude-recall"
        lessons_base.mkdir(parents=True)
        return lessons_base

    @pytest.fixture
    def temp_project_root(self, tmp_path: Path) -> Path:
        """Create a temporary project directory with .git folder."""
        project = tmp_path / "project"
        project.mkdir()
        (project / ".git").mkdir()
        (project / ".claude-recall").mkdir()
        return project

    @pytest.fixture
    def manager(self, temp_lessons_base: Path, temp_project_root: Path):
        """Create a LessonsManager instance with temporary paths."""
        from core.manager import LessonsManager
        return LessonsManager(
            lessons_base=temp_lessons_base,
            project_root=temp_project_root,
        )

    def test_dispatch_routes_to_correct_command(self, manager, capsys):
        """dispatch_command should route to the correct command class."""
        from core.commands import dispatch_command

        args = Namespace(
            command="inject",
            top_n=3,
        )

        result = dispatch_command(args, manager)
        assert result == 0

    def test_dispatch_unknown_command_returns_error(self, manager, capsys):
        """dispatch_command should return 1 for unknown commands."""
        from core.commands import dispatch_command

        args = Namespace(command="unknown-command-xyz")

        result = dispatch_command(args, manager)
        assert result == 1
        captured = capsys.readouterr()
        assert "Unknown command" in captured.out

    def test_dispatch_add_command(self, manager, capsys):
        """dispatch_command should correctly dispatch 'add'."""
        from core.commands import dispatch_command

        args = Namespace(
            command="add",
            category="pattern",
            title="Dispatched",
            content="Content",
            system=False,
            force=False,
            no_promote=False,
            type="",
        )

        result = dispatch_command(args, manager)
        assert result == 0
        captured = capsys.readouterr()
        assert "L001" in captured.out


# =============================================================================
# Command Return Value Tests
# =============================================================================


class TestCommandReturnValues:
    """Tests for command return values and error handling."""

    @pytest.fixture
    def temp_lessons_base(self, tmp_path: Path) -> Path:
        """Create a temporary lessons base directory."""
        lessons_base = tmp_path / ".config" / "claude-recall"
        lessons_base.mkdir(parents=True)
        return lessons_base

    @pytest.fixture
    def temp_project_root(self, tmp_path: Path) -> Path:
        """Create a temporary project directory with .git folder."""
        project = tmp_path / "project"
        project.mkdir()
        (project / ".git").mkdir()
        (project / ".claude-recall").mkdir()
        return project

    @pytest.fixture
    def manager(self, temp_lessons_base: Path, temp_project_root: Path):
        """Create a LessonsManager instance with temporary paths."""
        from core.manager import LessonsManager
        return LessonsManager(
            lessons_base=temp_lessons_base,
            project_root=temp_project_root,
        )

    def test_all_commands_return_int(self, manager, capsys):
        """All command execute methods should return an integer."""
        from core.commands import COMMAND_REGISTRY

        # Test a few representative commands with valid args
        test_cases = [
            ("inject", Namespace(command="inject", top_n=3)),
            ("list", Namespace(
                command="list", project=False, system=False,
                search=None, category=None, stale=False
            )),
        ]

        for cmd_name, args in test_cases:
            cmd_class = COMMAND_REGISTRY[cmd_name]
            cmd = cmd_class()
            result = cmd.execute(args, manager)
            assert isinstance(result, int), f"{cmd_name} should return int"

    def test_successful_commands_return_zero(self, manager, capsys):
        """Successful command execution should return 0."""
        from core.commands import InjectCommand

        args = Namespace(command="inject", top_n=5)
        cmd = InjectCommand()
        result = cmd.execute(args, manager)
        assert result == 0


# =============================================================================
# Integration Tests
# =============================================================================


class TestCommandPatternIntegration:
    """Integration tests for command pattern with cli.py."""

    @pytest.fixture
    def temp_lessons_base(self, tmp_path: Path) -> Path:
        """Create a temporary lessons base directory."""
        lessons_base = tmp_path / ".config" / "claude-recall"
        lessons_base.mkdir(parents=True)
        return lessons_base

    @pytest.fixture
    def temp_project_root(self, tmp_path: Path) -> Path:
        """Create a temporary project directory with .git folder."""
        project = tmp_path / "project"
        project.mkdir()
        (project / ".git").mkdir()
        (project / ".claude-recall").mkdir()
        return project

    def test_command_registry_covers_basic_commands(self):
        """Registry should contain all basic lesson commands."""
        from core.commands import COMMAND_REGISTRY

        basic_commands = [
            "add", "add-ai", "add-system",
            "cite", "inject", "list",
            "decay", "edit", "delete", "promote",
            "score-relevance",
        ]

        for cmd in basic_commands:
            assert cmd in COMMAND_REGISTRY, f"'{cmd}' should be in COMMAND_REGISTRY"

    def test_all_registered_commands_are_command_subclasses(self):
        """All registered commands should be subclasses of Command."""
        from core.commands import COMMAND_REGISTRY, Command

        for name, cmd_class in COMMAND_REGISTRY.items():
            assert issubclass(cmd_class, Command), \
                f"'{name}' should be a Command subclass"

    def test_all_registered_commands_can_be_instantiated(self):
        """All registered command classes should be instantiable."""
        from core.commands import COMMAND_REGISTRY

        for name, cmd_class in COMMAND_REGISTRY.items():
            try:
                cmd = cmd_class()
                assert cmd is not None
            except TypeError as e:
                pytest.fail(f"'{name}' command failed to instantiate: {e}")


# =============================================================================
# Migrate Triggers Command Tests
# =============================================================================


class TestMigrateTriggersCommand:
    """Tests for the migrate-triggers command.

    This command auto-generates triggers for existing lessons using Claude Haiku.
    It finds lessons with empty triggers, batches them into a prompt for Haiku,
    parses the response, and updates the lessons file.
    """

    @pytest.fixture
    def temp_lessons_base(self, tmp_path: Path) -> Path:
        """Create a temporary lessons base directory."""
        lessons_base = tmp_path / ".config" / "claude-recall"
        lessons_base.mkdir(parents=True)
        return lessons_base

    @pytest.fixture
    def temp_project_root(self, tmp_path: Path) -> Path:
        """Create a temporary project directory with .git folder."""
        project = tmp_path / "project"
        project.mkdir()
        (project / ".git").mkdir()
        (project / ".claude-recall").mkdir()
        return project

    @pytest.fixture
    def manager(self, temp_lessons_base: Path, temp_project_root: Path):
        """Create a LessonsManager instance with temporary paths."""
        from core.manager import LessonsManager
        return LessonsManager(
            lessons_base=temp_lessons_base,
            project_root=temp_project_root,
        )

    def test_migrate_triggers_command_exists(self):
        """MigrateTriggersCommand should exist and be registered."""
        from core.commands import COMMAND_REGISTRY, MigrateTriggersCommand

        assert "migrate-triggers" in COMMAND_REGISTRY
        assert COMMAND_REGISTRY["migrate-triggers"] is MigrateTriggersCommand

    def test_migrate_triggers_finds_lessons_without_triggers(self, manager, capsys):
        """Command should identify lessons with empty triggers list."""
        from core.commands import MigrateTriggersCommand

        # Add lessons - some with triggers, some without
        manager.add_lesson(
            level="project",
            category="pattern",
            title="Mutex cleanup",
            content="Always release mutex in destructor",
        )
        manager.add_lesson(
            level="project",
            category="gotcha",
            title="XML binding order",
            content="Create subjects before XML widgets",
        )

        cmd = MigrateTriggersCommand()

        # Command should have a method to find lessons needing triggers
        lessons_without_triggers = cmd.find_lessons_without_triggers(manager)

        assert len(lessons_without_triggers) == 2
        assert all(len(lesson.triggers) == 0 for lesson in lessons_without_triggers)

    def test_migrate_triggers_generates_prompt_for_haiku(self, manager):
        """Command should format lessons into a batch prompt for Haiku."""
        from core.commands import MigrateTriggersCommand

        # Add a lesson
        manager.add_lesson(
            level="project",
            category="pattern",
            title="RAII widgets",
            content="Use lvgl_make_unique for widget memory management",
        )

        cmd = MigrateTriggersCommand()
        lessons = cmd.find_lessons_without_triggers(manager)

        prompt = cmd.generate_haiku_prompt(lessons)

        # Prompt should include lesson ID, title, content, category
        assert "L001" in prompt
        assert "RAII widgets" in prompt
        assert "lvgl_make_unique" in prompt
        assert "pattern" in prompt

        # Prompt should specify output format
        assert "L001:" in prompt or "format" in prompt.lower()

    def test_migrate_triggers_parses_haiku_response(self, manager):
        """Command should parse Haiku response and extract triggers."""
        from core.commands import MigrateTriggersCommand

        # Add lessons to match the IDs in the mock response
        manager.add_lesson(
            level="project",
            category="pattern",
            title="Mutex cleanup",
            content="Always release mutex in destructor",
        )
        manager.add_lesson(
            level="project",
            category="gotcha",
            title="XML binding order",
            content="Create subjects before XML widgets",
        )
        manager.add_lesson(
            level="project",
            category="preference",
            title="Dropdown styling",
            content="Use bind_options for dropdown population",
        )

        cmd = MigrateTriggersCommand()

        # Mock Haiku response format
        haiku_response = """L001: destructor, mutex, shutdown
L002: XML, subjects, create order
L003: dropdown, bind_options"""

        parsed = cmd.parse_haiku_response(haiku_response)

        assert parsed["L001"] == ["destructor", "mutex", "shutdown"]
        assert parsed["L002"] == ["XML", "subjects", "create order"]
        assert parsed["L003"] == ["dropdown", "bind_options"]

    def test_migrate_triggers_writes_back_to_file(self, manager, capsys):
        """After parsing Haiku response, lessons file should be updated."""
        from core.commands import MigrateTriggersCommand
        from unittest.mock import patch, MagicMock

        # Add a lesson without auto-generating triggers
        manager.add_lesson(
            level="project",
            category="pattern",
            title="Mutex cleanup",
            content="Always release mutex in destructor",
            auto_triggers=False,  # Skip auto-generation during add
        )

        cmd = MigrateTriggersCommand()

        # Mock the Haiku API call - must patch on class, not instance for static method
        mock_response = "L001: destructor, mutex, shutdown"
        with patch.object(MigrateTriggersCommand, "call_haiku_api", return_value=mock_response):
            args = Namespace(command="migrate-triggers", dry_run=False)
            result = cmd.execute(args, manager)

        assert result == 0

        # Verify the lesson now has triggers
        lesson = manager.get_lesson("L001")
        assert lesson.triggers == ["destructor", "mutex", "shutdown"]

    def test_migrate_triggers_skips_lessons_with_triggers(self, manager):
        """Lessons that already have triggers should NOT be in migration batch."""
        from core.commands import MigrateTriggersCommand

        # Add a lesson, then manually set triggers on it
        lesson_id = manager.add_lesson(
            level="project",
            category="pattern",
            title="Already has triggers",
            content="This lesson has triggers set",
        )
        # Update the lesson to have triggers
        lesson = manager.get_lesson(lesson_id)
        lesson.triggers = ["existing", "triggers"]
        manager._save_lessons()

        # Add another lesson without triggers
        manager.add_lesson(
            level="project",
            category="gotcha",
            title="Needs triggers",
            content="This lesson needs triggers generated",
        )

        cmd = MigrateTriggersCommand()
        lessons_without_triggers = cmd.find_lessons_without_triggers(manager)

        # Should only find the lesson without triggers
        assert len(lessons_without_triggers) == 1
        assert lessons_without_triggers[0].title == "Needs triggers"

    def test_migrate_triggers_dry_run_mode(self, manager, capsys):
        """With --dry-run flag, command should show changes but NOT write."""
        from core.commands import MigrateTriggersCommand
        from unittest.mock import patch

        # Add a lesson
        manager.add_lesson(
            level="project",
            category="pattern",
            title="Dry run test",
            content="Test content for dry run",
        )

        cmd = MigrateTriggersCommand()

        # Mock the Haiku API call
        mock_response = "L001: dry, run, test"
        with patch.object(cmd, "call_haiku_api", return_value=mock_response):
            args = Namespace(command="migrate-triggers", dry_run=True)
            result = cmd.execute(args, manager)

        assert result == 0

        # Check output shows what would be generated
        captured = capsys.readouterr()
        assert "dry run" in captured.out.lower() or "would" in captured.out.lower()
        assert "L001" in captured.out

        # Verify the lesson was NOT updated
        lesson = manager.get_lesson("L001")
        assert lesson.triggers == []  # Still empty
