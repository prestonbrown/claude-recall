#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
CLI interface for the lessons manager.

This module provides the command-line interface for managing lessons and handoffs.
(Handoffs were formerly called "approaches".)

Usage:
    python3 core/cli.py <command> [args]
    python3 -m core.cli <command> [args]
"""

import argparse
import json as json_module
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


def _get_lessons_base() -> Path:
    """Get the system lessons base directory, checking RECALL_BASE first, then LESSONS_BASE."""
    base_path = os.environ.get("RECALL_BASE") or os.environ.get("LESSONS_BASE")
    if base_path:
        return Path(base_path)
    return Path.home() / ".config" / "coding-agent-lessons"


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

    # handoff command (with subcommands) - "approach" is kept as alias for backward compat
    handoff_parser = subparsers.add_parser("handoff", aliases=["approach"], help="Manage handoffs (work tracking). 'approach' is a deprecated alias.")
    handoff_subparsers = handoff_parser.add_subparsers(dest="handoff_command", help="Handoff commands")

    # handoff add (alias: start)
    handoff_add_parser = handoff_subparsers.add_parser("add", aliases=["start"], help="Add a new handoff")
    handoff_add_parser.add_argument("title", help="Handoff title")
    handoff_add_parser.add_argument("--desc", help="Description")
    handoff_add_parser.add_argument("--files", help="Comma-separated list of files")
    handoff_add_parser.add_argument("--phase", default="research", help="Initial phase (research, planning, implementing, review)")
    handoff_add_parser.add_argument("--agent", default="user", help="Agent working on this (explore, general-purpose, plan, review, user)")
    handoff_add_parser.add_argument("--stealth", action="store_true", help="Store in local file (not committed to git)")

    # handoff update
    handoff_update_parser = handoff_subparsers.add_parser("update", help="Update a handoff")
    handoff_update_parser.add_argument("id", help="Handoff ID (e.g., A001 or hf-abc1234)")
    handoff_update_parser.add_argument("--status", help="New status (not_started, in_progress, blocked, completed)")
    handoff_update_parser.add_argument("--tried", nargs=2, metavar=("OUTCOME", "DESC"), help="Add tried step (outcome: success|fail|partial)")
    handoff_update_parser.add_argument("--next", help="Update next steps")
    handoff_update_parser.add_argument("--files", help="Update files (comma-separated)")
    handoff_update_parser.add_argument("--desc", help="Update description")
    handoff_update_parser.add_argument("--phase", help="Update phase (research, planning, implementing, review)")
    handoff_update_parser.add_argument("--agent", help="Update agent (explore, general-purpose, plan, review, user)")
    handoff_update_parser.add_argument("--checkpoint", help="Update checkpoint (progress summary for session handoff)")
    handoff_update_parser.add_argument("--blocked-by", help="Set blocked_by dependencies (comma-separated handoff IDs)")

    # handoff complete
    handoff_complete_parser = handoff_subparsers.add_parser("complete", help="Mark handoff as completed")
    handoff_complete_parser.add_argument("id", help="Handoff ID")

    # handoff archive
    handoff_archive_parser = handoff_subparsers.add_parser("archive", help="Archive a handoff")
    handoff_archive_parser.add_argument("id", help="Handoff ID")

    # handoff delete (alias: remove)
    handoff_delete_parser = handoff_subparsers.add_parser("delete", aliases=["remove"], help="Delete a handoff")
    handoff_delete_parser.add_argument("id", help="Handoff ID")

    # handoff list
    handoff_list_parser = handoff_subparsers.add_parser("list", help="List handoffs")
    handoff_list_parser.add_argument("--status", help="Filter by status")
    handoff_list_parser.add_argument("--include-completed", action="store_true", help="Include completed handoffs")

    # handoff show
    handoff_show_parser = handoff_subparsers.add_parser("show", help="Show a handoff")
    handoff_show_parser.add_argument("id", help="Handoff ID")

    # handoff inject
    handoff_subparsers.add_parser("inject", help="Output handoffs for context injection")

    # handoff sync-todos (sync from TodoWrite tool calls)
    sync_todos_parser = handoff_subparsers.add_parser(
        "sync-todos",
        help="Sync TodoWrite todos to handoff (called by stop-hook)"
    )
    sync_todos_parser.add_argument("todos_json", help="JSON array of todos from TodoWrite")

    # handoff inject-todos (format handoffs as todo suggestions)
    handoff_subparsers.add_parser(
        "inject-todos",
        help="Format active handoff as TodoWrite continuation prompt"
    )

    # handoff ready (list ready handoffs)
    handoff_subparsers.add_parser(
        "ready",
        help="List handoffs that are ready to work on (not blocked)"
    )

    # handoff set-context (set structured handoff context from precompact hook)
    set_context_parser = handoff_subparsers.add_parser(
        "set-context",
        help="Set structured handoff context (called by precompact-hook)"
    )
    set_context_parser.add_argument("id", help="Handoff ID (e.g., A001 or hf-abc1234)")
    set_context_parser.add_argument(
        "--json",
        required=True,
        dest="context_json",
        help="JSON object with summary, critical_files, recent_changes, learnings, blockers, git_ref"
    )

    # handoff resume (resume handoff with validation)
    resume_parser = handoff_subparsers.add_parser(
        "resume",
        help="Resume a handoff with validation of codebase state"
    )
    resume_parser.add_argument("id", help="Handoff ID (e.g., A001 or hf-abc1234)")

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

    # Lessons base - use helper that checks RECALL_BASE first, then LESSONS_BASE
    lessons_base = _get_lessons_base()
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

        elif args.command in ("handoff", "approach"):
            if args.command == "approach":
                print("Note: 'approach' command is deprecated, use 'handoff' instead", file=sys.stderr)

            if not args.handoff_command:
                handoff_parser.print_help()
                sys.exit(1)

            if args.handoff_command in ("add", "start"):
                files = None
                if args.files:
                    files = [f.strip() for f in args.files.split(",") if f.strip()]
                stealth = getattr(args, 'stealth', False)
                handoff_id = manager.handoff_add(
                    title=args.title,
                    desc=args.desc,
                    files=files,
                    phase=args.phase,
                    agent=args.agent,
                    stealth=stealth,
                )
                mode = " (stealth)" if stealth else ""
                print(f"Added handoff {handoff_id}: {args.title}{mode}")

            elif args.handoff_command == "update":
                updated = False
                if args.status:
                    manager.handoff_update_status(args.id, args.status)
                    print(f"Updated {args.id} status to {args.status}")
                    updated = True
                if args.tried:
                    outcome, desc = args.tried
                    manager.handoff_add_tried(args.id, outcome, desc)
                    print(f"Added tried step to {args.id}")
                    updated = True
                if args.next:
                    manager.handoff_update_next(args.id, args.next)
                    print(f"Updated {args.id} next steps")
                    updated = True
                if args.files:
                    files_list = [f.strip() for f in args.files.split(",") if f.strip()]
                    manager.handoff_update_files(args.id, files_list)
                    print(f"Updated {args.id} files")
                    updated = True
                if args.desc:
                    manager.handoff_update_desc(args.id, args.desc)
                    print(f"Updated {args.id} description")
                    updated = True
                if args.phase:
                    manager.handoff_update_phase(args.id, args.phase)
                    print(f"Updated {args.id} phase to {args.phase}")
                    updated = True
                if args.agent:
                    manager.handoff_update_agent(args.id, args.agent)
                    print(f"Updated {args.id} agent to {args.agent}")
                    updated = True
                if args.checkpoint:
                    manager.handoff_update_checkpoint(args.id, args.checkpoint)
                    print(f"Updated {args.id} checkpoint")
                    updated = True
                blocked_by_arg = getattr(args, 'blocked_by', None)
                if blocked_by_arg:
                    blocked_by_list = [b.strip() for b in blocked_by_arg.split(",") if b.strip()]
                    manager.handoff_update_blocked_by(args.id, blocked_by_list)
                    print(f"Updated {args.id} blocked_by to {', '.join(blocked_by_list)}")
                    updated = True
                if not updated:
                    print("No update options provided", file=sys.stderr)
                    sys.exit(1)

            elif args.handoff_command == "complete":
                result = manager.handoff_complete(args.id)
                print(f"Completed {args.id}")
                print("\n" + result.extraction_prompt)

            elif args.handoff_command == "archive":
                manager.handoff_archive(args.id)
                print(f"Archived {args.id}")

            elif args.handoff_command == "delete":
                manager.handoff_delete(args.id)
                print(f"Deleted {args.id}")

            elif args.handoff_command == "list":
                handoffs = manager.handoff_list(
                    status_filter=args.status,
                    include_completed=args.include_completed,
                )
                if not handoffs:
                    print("(no handoffs found)")
                else:
                    for handoff in handoffs:
                        print(f"[{handoff.id}] {handoff.title}")
                        print(f"    Status: {handoff.status} | Created: {handoff.created} | Updated: {handoff.updated}")
                        if handoff.files:
                            print(f"    Files: {', '.join(handoff.files)}")
                        if handoff.description:
                            print(f"    Description: {handoff.description}")
                    print(f"\nTotal: {len(handoffs)} handoff(s)")

            elif args.handoff_command == "show":
                handoff = manager.handoff_get(args.id)
                if handoff is None:
                    print(f"Error: Handoff {args.id} not found", file=sys.stderr)
                    sys.exit(1)
                print(f"### [{handoff.id}] {handoff.title}")
                print(f"- **Status**: {handoff.status}")
                print(f"- **Created**: {handoff.created}")
                print(f"- **Updated**: {handoff.updated}")
                print(f"- **Files**: {', '.join(handoff.files) if handoff.files else '(none)'}")
                print(f"- **Description**: {handoff.description if handoff.description else '(none)'}")
                if handoff.checkpoint:
                    session_info = f" ({handoff.last_session})" if handoff.last_session else ""
                    print(f"- **Checkpoint{session_info}**: {handoff.checkpoint}")
                print()
                print("**Tried**:")
                if handoff.tried:
                    for i, tried in enumerate(handoff.tried, 1):
                        print(f"{i}. [{tried.outcome}] {tried.description}")
                else:
                    print("(none)")
                print()
                print(f"**Next**: {handoff.next_steps if handoff.next_steps else '(none)'}")

            elif args.handoff_command == "inject":
                output = manager.handoff_inject()
                if output:
                    print(output)
                else:
                    print("(no active handoffs)")

            elif args.handoff_command == "sync-todos":
                try:
                    todos = json_module.loads(args.todos_json)
                    if not isinstance(todos, list):
                        print("Error: todos_json must be a JSON array", file=sys.stderr)
                        sys.exit(1)
                    result = manager.handoff_sync_todos(todos)
                    if result:
                        print(f"Synced {len(todos)} todo(s) to handoff {result}")
                except json_module.JSONDecodeError as e:
                    print(f"Error: Invalid JSON: {e}", file=sys.stderr)
                    sys.exit(1)

            elif args.handoff_command == "inject-todos":
                output = manager.handoff_inject_todos()
                if output:
                    print(output)

            elif args.handoff_command == "ready":
                ready_handoffs = manager.handoff_ready()
                if not ready_handoffs:
                    print("(no ready handoffs)")
                else:
                    for handoff in ready_handoffs:
                        status_indicator = "[*]" if handoff.status == "in_progress" else "[ ]"
                        print(f"{status_indicator} [{handoff.id}] {handoff.title}")
                        print(f"    Status: {handoff.status} | Phase: {handoff.phase} | Updated: {handoff.updated}")
                        if handoff.blocked_by:
                            print(f"    Blocked by: {', '.join(handoff.blocked_by)} (all completed)")
                    print(f"\nReady: {len(ready_handoffs)} handoff(s)")

            elif args.handoff_command == "set-context":
                try:
                    from core.models import HandoffContext
                except ImportError:
                    from models import HandoffContext
                try:
                    context_data = json_module.loads(args.context_json)
                    if not isinstance(context_data, dict):
                        print("Error: context_json must be a JSON object", file=sys.stderr)
                        sys.exit(1)
                    # Build HandoffContext from JSON data
                    context = HandoffContext(
                        summary=context_data.get("summary", ""),
                        critical_files=context_data.get("critical_files", []),
                        recent_changes=context_data.get("recent_changes", []),
                        learnings=context_data.get("learnings", []),
                        blockers=context_data.get("blockers", []),
                        git_ref=context_data.get("git_ref", ""),
                    )
                    manager.handoff_update_context(args.id, context)
                    print(f"Set context for {args.id} (git ref: {context.git_ref})")
                except json_module.JSONDecodeError as e:
                    print(f"Error: Invalid JSON: {e}", file=sys.stderr)
                    sys.exit(1)

            elif args.handoff_command == "resume":
                result = manager.handoff_resume(args.id)
                print(result.format())

    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
