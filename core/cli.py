#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
CLI interface for the lessons manager.

This module provides the command-line interface for managing lessons and approaches.

Usage:
    python3 core/cli.py <command> [args]
    python3 -m core.cli <command> [args]
"""

import argparse
import os
import sys
from pathlib import Path

# Handle both module import and direct script execution
try:
    from core.manager import LessonsManager
    from core.models import ROBOT_EMOJI, LessonRating
except ImportError:
    from manager import LessonsManager
    from models import ROBOT_EMOJI, LessonRating


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Lessons Manager - Tool-agnostic AI coding agent lessons"
    )
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # add command
    add_parser = subparsers.add_parser("add", help="Add a project lesson")
    add_parser.add_argument("category", help="Lesson category")
    add_parser.add_argument("title", help="Lesson title")
    add_parser.add_argument("content", help="Lesson content")
    add_parser.add_argument("--force", action="store_true", help="Skip duplicate check")
    add_parser.add_argument("--system", action="store_true", help="Add as system lesson")
    add_parser.add_argument(
        "--no-promote", action="store_true", help="Never promote to system level"
    )

    # add-ai command
    add_ai_parser = subparsers.add_parser("add-ai", help="Add an AI-generated lesson")
    add_ai_parser.add_argument("category", help="Lesson category")
    add_ai_parser.add_argument("title", help="Lesson title")
    add_ai_parser.add_argument("content", help="Lesson content")
    add_ai_parser.add_argument("--system", action="store_true", help="Add as system lesson")
    add_ai_parser.add_argument(
        "--no-promote", action="store_true", help="Never promote to system level"
    )

    # add-system command (alias for add --system, for backward compatibility)
    add_system_parser = subparsers.add_parser(
        "add-system", help="Add a system lesson (alias for add --system)"
    )
    add_system_parser.add_argument("category", help="Lesson category")
    add_system_parser.add_argument("title", help="Lesson title")
    add_system_parser.add_argument("content", help="Lesson content")
    add_system_parser.add_argument(
        "--force", action="store_true", help="Skip duplicate check"
    )

    # cite command
    cite_parser = subparsers.add_parser("cite", help="Cite a lesson")
    cite_parser.add_argument("lesson_id", help="Lesson ID (e.g., L001)")

    # inject command
    inject_parser = subparsers.add_parser("inject", help="Output top lessons for injection")
    inject_parser.add_argument("top_n", type=int, nargs="?", default=5, help="Number of top lessons")

    # list command
    list_parser = subparsers.add_parser("list", help="List lessons")
    list_parser.add_argument("--project", action="store_true", help="Project lessons only")
    list_parser.add_argument("--system", action="store_true", help="System lessons only")
    list_parser.add_argument("--search", "-s", help="Search term")
    list_parser.add_argument("--category", "-c", help="Filter by category")
    list_parser.add_argument("--stale", action="store_true", help="Show stale lessons only")

    # decay command
    decay_parser = subparsers.add_parser("decay", help="Decay lesson metrics")
    decay_parser.add_argument("days", type=int, nargs="?", default=30, help="Stale threshold days")

    # edit command
    edit_parser = subparsers.add_parser("edit", help="Edit a lesson")
    edit_parser.add_argument("lesson_id", help="Lesson ID")
    edit_parser.add_argument("content", help="New content")

    # delete command (alias: remove)
    delete_parser = subparsers.add_parser("delete", aliases=["remove"], help="Delete a lesson")
    delete_parser.add_argument("lesson_id", help="Lesson ID")

    # promote command
    promote_parser = subparsers.add_parser("promote", help="Promote project lesson to system")
    promote_parser.add_argument("lesson_id", help="Lesson ID")

    # score-relevance command
    score_relevance_parser = subparsers.add_parser(
        "score-relevance", help="Score lessons by relevance to text using Haiku"
    )
    score_relevance_parser.add_argument("text", help="Text to score lessons against")
    score_relevance_parser.add_argument(
        "--top", type=int, default=10, help="Number of top results to show"
    )
    score_relevance_parser.add_argument(
        "--min-score", type=int, default=0, help="Minimum relevance score (0-10)"
    )
    score_relevance_parser.add_argument(
        "--timeout", type=int, default=30, help="Timeout in seconds for Haiku call"
    )

    # approach command (with subcommands)
    approach_parser = subparsers.add_parser("approach", help="Manage approaches")
    approach_subparsers = approach_parser.add_subparsers(dest="approach_command", help="Approach commands")

    # approach add (alias: start)
    approach_add_parser = approach_subparsers.add_parser("add", aliases=["start"], help="Add a new approach")
    approach_add_parser.add_argument("title", help="Approach title")
    approach_add_parser.add_argument("--desc", help="Description")
    approach_add_parser.add_argument("--files", help="Comma-separated list of files")
    approach_add_parser.add_argument("--phase", default="research", help="Initial phase (research, planning, implementing, review)")
    approach_add_parser.add_argument("--agent", default="user", help="Agent working on this (explore, general-purpose, plan, review, user)")

    # approach update
    approach_update_parser = approach_subparsers.add_parser("update", help="Update an approach")
    approach_update_parser.add_argument("id", help="Approach ID (e.g., A001)")
    approach_update_parser.add_argument("--status", help="New status (not_started, in_progress, blocked, completed)")
    approach_update_parser.add_argument("--tried", nargs=2, metavar=("OUTCOME", "DESC"), help="Add tried approach (outcome: success|fail|partial)")
    approach_update_parser.add_argument("--next", help="Update next steps")
    approach_update_parser.add_argument("--files", help="Update files (comma-separated)")
    approach_update_parser.add_argument("--desc", help="Update description")
    approach_update_parser.add_argument("--phase", help="Update phase (research, planning, implementing, review)")
    approach_update_parser.add_argument("--agent", help="Update agent (explore, general-purpose, plan, review, user)")
    approach_update_parser.add_argument("--checkpoint", help="Update checkpoint (progress summary for session handoff)")

    # approach complete
    approach_complete_parser = approach_subparsers.add_parser("complete", help="Mark approach as completed")
    approach_complete_parser.add_argument("id", help="Approach ID")

    # approach archive
    approach_archive_parser = approach_subparsers.add_parser("archive", help="Archive an approach")
    approach_archive_parser.add_argument("id", help="Approach ID")

    # approach delete (alias: remove)
    approach_delete_parser = approach_subparsers.add_parser("delete", aliases=["remove"], help="Delete an approach")
    approach_delete_parser.add_argument("id", help="Approach ID")

    # approach list
    approach_list_parser = approach_subparsers.add_parser("list", help="List approaches")
    approach_list_parser.add_argument("--status", help="Filter by status")
    approach_list_parser.add_argument("--include-completed", action="store_true", help="Include completed approaches")

    # approach show
    approach_show_parser = approach_subparsers.add_parser("show", help="Show an approach")
    approach_show_parser.add_argument("id", help="Approach ID")

    # approach inject
    approach_subparsers.add_parser("inject", help="Output approaches for context injection")

    # approach sync-todos (sync from TodoWrite tool calls)
    sync_todos_parser = approach_subparsers.add_parser(
        "sync-todos",
        help="Sync TodoWrite todos to approach (called by stop-hook)"
    )
    sync_todos_parser.add_argument("todos_json", help="JSON array of todos from TodoWrite")

    # approach inject-todos (format approaches as todo suggestions)
    approach_subparsers.add_parser(
        "inject-todos",
        help="Format active approach as TodoWrite continuation prompt"
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Find project root - check env var first, then search for .git
    project_root_env = os.environ.get("PROJECT_DIR")
    if project_root_env:
        project_root = Path(project_root_env)
    else:
        project_root = Path.cwd()
        while project_root != project_root.parent:
            if (project_root / ".git").exists():
                break
            project_root = project_root.parent
        else:
            project_root = Path.cwd()

    # Lessons base - check env var first, then use default
    lessons_base_env = os.environ.get("LESSONS_BASE")
    if lessons_base_env:
        lessons_base = Path(lessons_base_env)
    else:
        lessons_base = Path.home() / ".config" / "coding-agent-lessons"
    manager = LessonsManager(lessons_base, project_root)

    try:
        if args.command == "add":
            level = "system" if args.system else "project"
            promotable = not getattr(args, "no_promote", False)
            lesson_id = manager.add_lesson(
                level=level,
                category=args.category,
                title=args.title,
                content=args.content,
                force=args.force,
                promotable=promotable,
            )
            promo_note = " (no-promote)" if not promotable else ""
            print(f"Added {level} lesson {lesson_id}: {args.title}{promo_note}")

        elif args.command == "add-ai":
            level = "system" if args.system else "project"
            promotable = not getattr(args, "no_promote", False)
            lesson_id = manager.add_ai_lesson(
                level=level,
                category=args.category,
                title=args.title,
                content=args.content,
                promotable=promotable,
            )
            promo_note = " (no-promote)" if not promotable else ""
            print(f"Added AI {level} lesson {lesson_id}: {args.title}{promo_note}")

        elif args.command == "add-system":
            # Alias for add --system (backward compatibility with bash script)
            lesson_id = manager.add_lesson(
                level="system",
                category=args.category,
                title=args.title,
                content=args.content,
                force=args.force,
            )
            print(f"Added system lesson {lesson_id}: {args.title}")

        elif args.command == "cite":
            result = manager.cite_lesson(args.lesson_id)
            if result.promotion_ready:
                print(f"PROMOTION_READY:{result.lesson_id}:{result.uses}")
            else:
                print(f"OK:{result.uses}")

        elif args.command == "inject":
            result = manager.inject_context(args.top_n)
            print(result.format())

        elif args.command == "list":
            scope = "all"
            if args.project:
                scope = "project"
            elif args.system:
                scope = "system"

            lessons = manager.list_lessons(
                scope=scope,
                search=args.search,
                category=args.category,
                stale_only=args.stale,
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

        elif args.command == "decay":
            result = manager.decay_lessons(args.days)
            print(result.message)

        elif args.command == "edit":
            manager.edit_lesson(args.lesson_id, args.content)
            print(f"Updated {args.lesson_id} content")

        elif args.command == "delete":
            manager.delete_lesson(args.lesson_id)
            print(f"Deleted {args.lesson_id}")

        elif args.command == "promote":
            new_id = manager.promote_lesson(args.lesson_id)
            print(f"Promoted {args.lesson_id} -> {new_id}")

        elif args.command == "score-relevance":
            result = manager.score_relevance(args.text, timeout_seconds=args.timeout)
            print(result.format(top_n=args.top, min_score=args.min_score))

        elif args.command == "approach":
            if not args.approach_command:
                approach_parser.print_help()
                sys.exit(1)

            if args.approach_command in ("add", "start"):
                files = None
                if args.files:
                    files = [f.strip() for f in args.files.split(",") if f.strip()]
                approach_id = manager.approach_add(
                    title=args.title,
                    desc=args.desc,
                    files=files,
                    phase=args.phase,
                    agent=args.agent,
                )
                print(f"Added approach {approach_id}: {args.title}")

            elif args.approach_command == "update":
                updated = False
                if args.status:
                    manager.approach_update_status(args.id, args.status)
                    print(f"Updated {args.id} status to {args.status}")
                    updated = True
                if args.tried:
                    outcome, desc = args.tried
                    manager.approach_add_tried(args.id, outcome, desc)
                    print(f"Added tried approach to {args.id}")
                    updated = True
                if args.next:
                    manager.approach_update_next(args.id, args.next)
                    print(f"Updated {args.id} next steps")
                    updated = True
                if args.files:
                    files_list = [f.strip() for f in args.files.split(",") if f.strip()]
                    manager.approach_update_files(args.id, files_list)
                    print(f"Updated {args.id} files")
                    updated = True
                if args.desc:
                    manager.approach_update_desc(args.id, args.desc)
                    print(f"Updated {args.id} description")
                    updated = True
                if args.phase:
                    manager.approach_update_phase(args.id, args.phase)
                    print(f"Updated {args.id} phase to {args.phase}")
                    updated = True
                if args.agent:
                    manager.approach_update_agent(args.id, args.agent)
                    print(f"Updated {args.id} agent to {args.agent}")
                    updated = True
                if args.checkpoint:
                    manager.approach_update_checkpoint(args.id, args.checkpoint)
                    print(f"Updated {args.id} checkpoint")
                    updated = True
                if not updated:
                    print("No update options provided", file=sys.stderr)
                    sys.exit(1)

            elif args.approach_command == "complete":
                result = manager.approach_complete(args.id)
                print(f"Completed {args.id}")
                print("\n" + result.extraction_prompt)

            elif args.approach_command == "archive":
                manager.approach_archive(args.id)
                print(f"Archived {args.id}")

            elif args.approach_command == "delete":
                manager.approach_delete(args.id)
                print(f"Deleted {args.id}")

            elif args.approach_command == "list":
                approaches = manager.approach_list(
                    status_filter=args.status,
                    include_completed=args.include_completed,
                )
                if not approaches:
                    print("(no approaches found)")
                else:
                    for approach in approaches:
                        print(f"[{approach.id}] {approach.title}")
                        print(f"    Status: {approach.status} | Created: {approach.created} | Updated: {approach.updated}")
                        if approach.files:
                            print(f"    Files: {', '.join(approach.files)}")
                        if approach.description:
                            print(f"    Description: {approach.description}")
                    print(f"\nTotal: {len(approaches)} approach(es)")

            elif args.approach_command == "show":
                approach = manager.approach_get(args.id)
                if approach is None:
                    print(f"Error: Approach {args.id} not found", file=sys.stderr)
                    sys.exit(1)
                print(f"### [{approach.id}] {approach.title}")
                print(f"- **Status**: {approach.status}")
                print(f"- **Created**: {approach.created}")
                print(f"- **Updated**: {approach.updated}")
                print(f"- **Files**: {', '.join(approach.files) if approach.files else '(none)'}")
                print(f"- **Description**: {approach.description if approach.description else '(none)'}")
                if approach.checkpoint:
                    session_info = f" ({approach.last_session})" if approach.last_session else ""
                    print(f"- **Checkpoint{session_info}**: {approach.checkpoint}")
                print()
                print("**Tried**:")
                if approach.tried:
                    for i, tried in enumerate(approach.tried, 1):
                        print(f"{i}. [{tried.outcome}] {tried.description}")
                else:
                    print("(none)")
                print()
                print(f"**Next**: {approach.next_steps if approach.next_steps else '(none)'}")

            elif args.approach_command == "inject":
                output = manager.approach_inject()
                if output:
                    print(output)
                else:
                    print("(no active approaches)")

            elif args.approach_command == "sync-todos":
                import json as json_module
                try:
                    todos = json_module.loads(args.todos_json)
                    if not isinstance(todos, list):
                        print("Error: todos_json must be a JSON array", file=sys.stderr)
                        sys.exit(1)
                    result = manager.approach_sync_todos(todos)
                    if result:
                        print(f"Synced {len(todos)} todo(s) to approach {result}")
                except json_module.JSONDecodeError as e:
                    print(f"Error: Invalid JSON: {e}", file=sys.stderr)
                    sys.exit(1)

            elif args.approach_command == "inject-todos":
                output = manager.approach_inject_todos()
                if output:
                    print(output)

    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
