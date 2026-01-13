#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Command pattern implementation for CLI.

This module implements the Command pattern for the CLI, replacing the
long if-elif chain in cli.py with a more maintainable class-based approach.

Each command is a class that implements the Command interface:
- execute(args, manager) -> int

Commands are registered in COMMAND_REGISTRY and dispatched via dispatch_command().
"""

import sys
from abc import ABC, abstractmethod
from argparse import Namespace
from typing import Any, Dict, Type

# Handle both module import and direct script execution
try:
    from core.models import ROBOT_EMOJI, LessonRating
except ImportError:
    from models import ROBOT_EMOJI, LessonRating


class Command(ABC):
    """Abstract base class for all CLI commands.

    Each command encapsulates the logic for one CLI action.
    Commands receive parsed args and a LessonsManager instance.
    """

    @abstractmethod
    def execute(self, args: Namespace, manager: Any) -> int:
        """Execute the command.

        Args:
            args: Parsed command-line arguments
            manager: LessonsManager instance

        Returns:
            Exit code (0 for success, non-zero for errors)
        """
        pass


# =============================================================================
# Lesson Commands
# =============================================================================


class AddCommand(Command):
    """Add a new lesson."""

    def execute(self, args: Namespace, manager: Any) -> int:
        level = "system" if getattr(args, "system", False) else "project"
        promotable = not getattr(args, "no_promote", False)
        lesson_type = getattr(args, "type", "")
        lesson_id = manager.add_lesson(
            level=level,
            category=args.category,
            title=args.title,
            content=args.content,
            force=getattr(args, "force", False),
            promotable=promotable,
            lesson_type=lesson_type,
        )
        promo_note = " (no-promote)" if not promotable else ""
        print(f"Added {level} lesson {lesson_id}: {args.title}{promo_note}")
        return 0


class AddAICommand(Command):
    """Add an AI-generated lesson."""

    def execute(self, args: Namespace, manager: Any) -> int:
        level = "system" if getattr(args, "system", False) else "project"
        promotable = not getattr(args, "no_promote", False)
        lesson_type = getattr(args, "type", "")
        lesson_id = manager.add_ai_lesson(
            level=level,
            category=args.category,
            title=args.title,
            content=args.content,
            promotable=promotable,
            lesson_type=lesson_type,
        )
        promo_note = " (no-promote)" if not promotable else ""
        print(f"Added AI {level} lesson {lesson_id}: {args.title}{promo_note}")
        return 0


class AddSystemCommand(Command):
    """Add a system lesson (alias for add --system)."""

    def execute(self, args: Namespace, manager: Any) -> int:
        lesson_id = manager.add_lesson(
            level="system",
            category=args.category,
            title=args.title,
            content=args.content,
            force=getattr(args, "force", False),
        )
        print(f"Added system lesson {lesson_id}: {args.title}")
        return 0


class CiteCommand(Command):
    """Cite one or more existing lessons."""

    def execute(self, args: Namespace, manager: Any) -> int:
        for lesson_id in args.lesson_ids:
            try:
                result = manager.cite_lesson(lesson_id)
                if result.promotion_ready:
                    print(f"PROMOTION_READY:{result.lesson_id}:{result.uses}")
                else:
                    print(f"OK:{result.uses}")
            except ValueError as e:
                print(f"Error:{lesson_id}:{e}", file=sys.stderr)
        return 0


class InjectCommand(Command):
    """Output top lessons for context injection."""

    def execute(self, args: Namespace, manager: Any) -> int:
        result = manager.inject_context(args.top_n)
        print(result.format())
        return 0


class ListCommand(Command):
    """List lessons with optional filtering."""

    def execute(self, args: Namespace, manager: Any) -> int:
        scope = "all"
        if getattr(args, "project", False):
            scope = "project"
        elif getattr(args, "system", False):
            scope = "system"

        lessons = manager.list_lessons(
            scope=scope,
            search=getattr(args, "search", None),
            category=getattr(args, "category", None),
            stale_only=getattr(args, "stale", False),
        )

        if not lessons:
            print("(no lessons found)")
        else:
            for lesson in lessons:
                rating = LessonRating.calculate(lesson.uses, lesson.velocity)
                prefix = f"{ROBOT_EMOJI} " if lesson.source == "ai" else ""
                stale = " [STALE]" if lesson.is_stale() else ""
                print(f"[{lesson.id}] {rating} {prefix}{lesson.title}{stale}")
                print(f"    -> {lesson.content}")
            print(f"\nTotal: {len(lessons)} lesson(s)")
        return 0


class DecayCommand(Command):
    """Apply velocity decay to lessons."""

    def execute(self, args: Namespace, manager: Any) -> int:
        result = manager.decay_lessons(args.days)
        print(result.message)
        return 0


class EditCommand(Command):
    """Edit an existing lesson's content."""

    def execute(self, args: Namespace, manager: Any) -> int:
        manager.edit_lesson(args.lesson_id, args.content)
        print(f"Updated {args.lesson_id} content")
        return 0


class DeleteCommand(Command):
    """Delete a lesson."""

    def execute(self, args: Namespace, manager: Any) -> int:
        manager.delete_lesson(args.lesson_id)
        print(f"Deleted {args.lesson_id}")
        return 0


class PromoteCommand(Command):
    """Promote a project lesson to system level."""

    def execute(self, args: Namespace, manager: Any) -> int:
        new_id = manager.promote_lesson(args.lesson_id)
        print(f"Promoted {args.lesson_id} -> {new_id}")
        return 0


class ScoreRelevanceCommand(Command):
    """Score lessons by relevance to a query."""

    def execute(self, args: Namespace, manager: Any) -> int:
        timeout = getattr(args, "timeout", 5)
        result = manager.score_relevance(args.text, timeout_seconds=timeout)
        top_n = getattr(args, "top", 5)
        min_score = getattr(args, "min_score", 0.0)
        print(result.format(top_n=top_n, min_score=min_score))
        return 0


# =============================================================================
# Command Registry
# =============================================================================


COMMAND_REGISTRY: Dict[str, Type[Command]] = {
    "add": AddCommand,
    "add-ai": AddAICommand,
    "add-system": AddSystemCommand,
    "cite": CiteCommand,
    "inject": InjectCommand,
    "list": ListCommand,
    "decay": DecayCommand,
    "edit": EditCommand,
    "delete": DeleteCommand,
    "promote": PromoteCommand,
    "score-relevance": ScoreRelevanceCommand,
}


# =============================================================================
# Dispatch Function
# =============================================================================


def dispatch_command(args: Namespace, manager: Any) -> int:
    """Dispatch to appropriate command handler.

    Args:
        args: Parsed arguments with 'command' attribute
        manager: LessonsManager instance

    Returns:
        Exit code (0 for success, 1 for unknown command)
    """
    command_name = args.command
    if command_name not in COMMAND_REGISTRY:
        print(f"Unknown command: {command_name}")
        return 1

    command_class = COMMAND_REGISTRY[command_name]
    command = command_class()
    return command.execute(args, manager)
