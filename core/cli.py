#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
CLI interface for Claude Recall.

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
    from core._version import __version__
    from core.commands import COMMAND_REGISTRY, dispatch_command
    from core.manager import LessonsManager
    from core.paths import PathResolver
except ImportError:
    from _version import __version__
    from commands import COMMAND_REGISTRY, dispatch_command
    from manager import LessonsManager
    from paths import PathResolver


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Claude Recall - AI coding agent memory system"
    )
    parser.add_argument(
        "--version", action="version", version=f"claude-recall {__version__}"
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
    add_parser.add_argument(
        "--type",
        choices=["constraint", "informational", "preference"],
        default="",
        help="Lesson type for framing (auto-classified if not specified)",
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
    add_ai_parser.add_argument(
        "--type",
        choices=["constraint", "informational", "preference"],
        default="",
        help="Lesson type for framing (auto-classified if not specified)",
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

    # cite command (accepts multiple IDs for batch processing)
    cite_parser = subparsers.add_parser("cite", help="Cite one or more lessons")
    cite_parser.add_argument("lesson_ids", nargs="+", help="Lesson ID(s) (e.g., L001 L002 L003)")

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

    # prescore-cache command - background cache warmup
    prescore_parser = subparsers.add_parser(
        "prescore-cache", help="Pre-score lessons against transcript queries (background cache warmup)"
    )
    prescore_parser.add_argument(
        "--transcript", required=True, help="Path to transcript JSONL file"
    )
    prescore_parser.add_argument(
        "--max-queries", type=int, default=3, help="Maximum queries to pre-score"
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

    # handoff extract-lessons
    extract_lessons_parser = handoff_subparsers.add_parser(
        "extract-lessons",
        help="Extract lesson suggestions from a handoff"
    )
    extract_lessons_parser.add_argument("id", help="Handoff ID")
    extract_lessons_parser.add_argument(
        "--json", action="store_true", dest="output_json",
        help="Output as JSON instead of formatted text"
    )

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
    sync_todos_parser.add_argument("--session-handoff", help="Handoff ID from session lookup (highest priority)")

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

    # handoff set-session (link session to handoff)
    set_session_parser = handoff_subparsers.add_parser(
        "set-session",
        help="Store session -> handoff mapping"
    )
    set_session_parser.add_argument("handoff_id", help="Handoff ID (e.g., hf-abc1234)")
    set_session_parser.add_argument("session_id", help="Claude session ID")
    set_session_parser.add_argument("--transcript", help="Path to transcript file")

    # handoff get-session-handoff (lookup handoff for session)
    get_session_handoff_parser = handoff_subparsers.add_parser(
        "get-session-handoff",
        help="Lookup handoff for session"
    )
    get_session_handoff_parser.add_argument("session_id", help="Claude session ID")

    # handoff add-transcript (add transcript to linked handoff)
    add_transcript_parser = handoff_subparsers.add_parser(
        "add-transcript",
        help="Add transcript to linked handoff"
    )
    add_transcript_parser.add_argument("session_id", help="Claude session ID")
    add_transcript_parser.add_argument("transcript_path", help="Path to transcript file")
    add_transcript_parser.add_argument("--agent-type", help="Agent type (e.g., 'Explore')")

    # handoff batch-process (process multiple operations in one call)
    handoff_subparsers.add_parser(
        "batch-process",
        help="Process multiple handoff operations in one call (reads JSON from stdin)"
    )

    # handoff process-transcript (parse transcript and process handoffs in one call)
    process_transcript_parser = handoff_subparsers.add_parser(
        "process-transcript",
        help="Parse transcript JSON for handoff patterns and process them (reads JSON from stdin)"
    )
    process_transcript_parser.add_argument(
        "--session-id", help="Claude session ID for sub-agent detection"
    )
    process_transcript_parser.add_argument(
        "--since", help="Timestamp to filter for incremental processing"
    )

    # watch command - TUI debug viewer
    watch_parser = subparsers.add_parser("watch", help="Launch debug TUI viewer")
    watch_parser.add_argument("--project", "-p", help="Filter to specific project")
    watch_parser.add_argument("--summary", action="store_true", help="One-shot text summary (no TUI)")
    watch_parser.add_argument("--tail", action="store_true", help="Simple colorized tail mode (no TUI)")
    watch_parser.add_argument("--lines", "-n", type=int, default=50, help="Number of lines for tail/summary")

    # Session commands for sub-agent detection and linking
    session_parser = subparsers.add_parser("session", help="Session management commands")
    session_subparsers = session_parser.add_subparsers(dest="session_command")

    # session detect-origin <session_id>
    detect_origin_parser = session_subparsers.add_parser(
        "detect-origin", help="Detect session type from first prompt"
    )
    detect_origin_parser.add_argument("session_id", help="Claude session ID")

    # session find-parent <session_id>
    find_parent_parser = session_subparsers.add_parser(
        "find-parent", help="Find parent session by temporal overlap"
    )
    find_parent_parser.add_argument("session_id", help="Claude session ID")

    # session link <session_id> [--handoff <id>]
    link_parser = session_subparsers.add_parser(
        "link", help="Link session with origin/parent detection"
    )
    link_parser.add_argument("session_id", help="Claude session ID")
    link_parser.add_argument("--handoff", help="Handoff ID to link to")

    # extract-context command - extract handoff context from transcript
    extract_context_parser = subparsers.add_parser(
        "extract-context",
        help="Extract handoff context from transcript using Haiku"
    )
    extract_context_parser.add_argument(
        "transcript_path", help="Path to transcript JSONL file"
    )
    extract_context_parser.add_argument(
        "--git-ref", help="Git commit hash to include in context"
    )

    # Debug commands for logging from bash hooks
    debug_parser = subparsers.add_parser("debug", help="Debug logging commands")
    debug_subparsers = debug_parser.add_subparsers(dest="debug_command")

    # debug hook-start <hook> [--trigger <trigger>]
    hook_start_parser = debug_subparsers.add_parser("hook-start", help="Log hook start")
    hook_start_parser.add_argument("hook", help="Hook name (inject, stop, precompact)")
    hook_start_parser.add_argument("--trigger", help="What triggered the hook")

    # debug hook-phase <hook> <phase> <ms> [--key=value ...]
    hook_phase_parser = debug_subparsers.add_parser("hook-phase", help="Log hook phase timing")
    hook_phase_parser.add_argument("hook", help="Hook name")
    hook_phase_parser.add_argument("phase", help="Phase name")
    hook_phase_parser.add_argument("ms", type=float, help="Duration in milliseconds")
    hook_phase_parser.add_argument("--details", help="JSON details object")

    # debug hook-end <hook> <total_ms> [--phases <json>]
    hook_end_parser = debug_subparsers.add_parser("hook-end", help="Log hook end")
    hook_end_parser.add_argument("hook", help="Hook name")
    hook_end_parser.add_argument("total_ms", type=float, help="Total duration in ms")
    hook_end_parser.add_argument("--phases", help="JSON object of phase->ms timings")

    # debug log-error <event> <message>
    error_parser = debug_subparsers.add_parser("log-error", help="Log an error event")
    error_parser.add_argument("event", help="Error event name")
    error_parser.add_argument("message", help="Error message")

    # debug injection-budget - log token budget breakdown
    budget_parser = debug_subparsers.add_parser(
        "injection-budget", help="Log injection token budget breakdown"
    )
    budget_parser.add_argument("total", type=int, help="Total tokens")
    budget_parser.add_argument("lessons", type=int, help="Lessons tokens")
    budget_parser.add_argument("handoffs", type=int, help="Handoffs tokens")
    budget_parser.add_argument("duties", type=int, help="Duties tokens")

    # config command - read settings for shell scripts
    config_parser = subparsers.add_parser("config", help="Get configuration value")
    config_parser.add_argument("key", help="Config key (dot notation, e.g., claudeRecall.debugLevel)")
    config_parser.add_argument("--default", "-d", default="", help="Default value if key not found")
    config_parser.add_argument(
        "--type", "-t",
        choices=["string", "int", "bool"],
        default="string",
        help="Value type (string, int, bool)"
    )

    args = parser.parse_args()

    if not args.command:
        # Default to TUI (watch) when no subcommand given
        args.command = "watch"
        args.project = None
        args.summary = False
        args.tail = False
        args.lines = 50

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

    # Lessons base - use PathResolver that checks CLAUDE_RECALL_BASE first, then RECALL_BASE, then LESSONS_BASE
    lessons_base = PathResolver.lessons_base()
    manager = LessonsManager(lessons_base, project_root)

    try:
        # Use Command pattern for registered commands
        if args.command in COMMAND_REGISTRY:
            return dispatch_command(args, manager)

        # Commands with subcommands or special handling
        if args.command in ("handoff", "approach"):
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
                if handoff_id:
                    print(f"Added handoff {handoff_id}: {args.title}{mode}")
                else:
                    print(f"Handoff creation blocked (sub-agent session)")

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
                if result.suggested_lessons:
                    print("\n" + "=" * 60)
                    print("LESSON SUGGESTIONS (extract with 'handoff extract-lessons'):")
                    for i, suggestion in enumerate(result.suggested_lessons, 1):
                        conf_indicator = {"low": "-", "medium": "", "high": "+"}.get(suggestion.confidence, "?")
                        print(f"  {i}. [{suggestion.category}]{conf_indicator} {suggestion.title}")
                        print(f"     {suggestion.content}")
                    print("=" * 60)

            elif args.handoff_command == "extract-lessons":
                handoff = manager.handoff_get(args.id)
                if handoff is None:
                    print(f"Error: Handoff {args.id} not found", file=sys.stderr)
                    sys.exit(1)
                suggestions = manager.extract_lessons_from_handoff(handoff)
                if getattr(args, 'output_json', False):
                    # Output as JSON for programmatic use
                    import json as json_out
                    json_data = [
                        {
                            "category": s.category,
                            "title": s.title,
                            "content": s.content,
                            "source": s.source,
                            "confidence": s.confidence,
                        }
                        for s in suggestions
                    ]
                    print(json_out.dumps(json_data, indent=2))
                else:
                    if not suggestions:
                        print("(no lesson suggestions found)")
                    else:
                        print(f"Lesson suggestions for [{args.id}] {handoff.title}:")
                        print()
                        for i, suggestion in enumerate(suggestions, 1):
                            conf_indicator = {"low": "-", "medium": "", "high": "+"}.get(suggestion.confidence, "?")
                            print(f"{i}. [{suggestion.category}]{conf_indicator} {suggestion.title}")
                            print(f"   {suggestion.content}")
                            print(f"   (source: {suggestion.source})")
                            print()

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
                    session_handoff = getattr(args, 'session_handoff', None)
                    result = manager.handoff_sync_todos(todos, session_handoff=session_handoff)
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

            elif args.handoff_command == "set-session":
                transcript = getattr(args, 'transcript', None)
                manager.handoff_set_session(args.handoff_id, args.session_id, transcript_path=transcript)
                print(f"Linked session {args.session_id} to handoff {args.handoff_id}")

            elif args.handoff_command == "get-session-handoff":
                handoff_id = manager.handoff_get_by_session(args.session_id)
                if handoff_id:
                    print(handoff_id)
                # If not found, print nothing (exit code 0)

            elif args.handoff_command == "add-transcript":
                agent_type = getattr(args, 'agent_type', None)
                result = manager.handoff_add_transcript(args.session_id, args.transcript_path, agent_type=agent_type)
                if result:
                    print(f"Added transcript to handoff {result}")
                else:
                    print("No linked handoff found for session", file=sys.stderr)
                    sys.exit(1)

            elif args.handoff_command == "batch-process":
                # Read JSON from stdin (sys already imported at module level)
                operations = json_module.loads(sys.stdin.read())
                if not isinstance(operations, list):
                    print("Error: Expected JSON array of operations", file=sys.stderr)
                    sys.exit(1)
                result = manager.handoff_batch_process(operations)
                print(json_module.dumps(result))

            elif args.handoff_command == "process-transcript":
                # Read transcript JSON from stdin, parse for handoffs, and process
                import time as time_module
                debug_timing = os.environ.get("CLAUDE_RECALL_DEBUG", "0") >= "1"

                t0 = time_module.perf_counter()
                transcript_data = json_module.loads(sys.stdin.read())
                t1 = time_module.perf_counter()

                if not isinstance(transcript_data, dict):
                    print("Error: Expected JSON object with assistant_texts array", file=sys.stderr)
                    sys.exit(1)

                session_id = getattr(args, 'session_id', "") or ""
                # Parse transcript for handoff operations
                operations = manager.parse_transcript_for_handoffs(
                    transcript_data,
                    session_id=session_id,
                )
                t2 = time_module.perf_counter()

                if operations:
                    # Process all operations in batch
                    result = manager.handoff_batch_process(operations)
                    t3 = time_module.perf_counter()
                    if debug_timing:
                        print(f"[timing] json_parse={int((t1-t0)*1000)}ms parse_transcript={int((t2-t1)*1000)}ms batch_process={int((t3-t2)*1000)}ms", file=sys.stderr)
                    print(json_module.dumps(result))
                else:
                    # No operations found
                    if debug_timing:
                        print(f"[timing] json_parse={int((t1-t0)*1000)}ms parse_transcript={int((t2-t1)*1000)}ms (no ops)", file=sys.stderr)
                    print(json_module.dumps({"results": [], "last_id": None}))

        elif args.command == "watch":
            try:
                from core.tui.log_reader import LogReader, get_default_log_path, format_event_line
                from core.tui.state_reader import StateReader
                from core.tui.stats import StatsAggregator
            except ImportError:
                from tui.log_reader import LogReader, get_default_log_path, format_event_line
                from tui.state_reader import StateReader
                from tui.stats import StatsAggregator

            log_path = get_default_log_path()
            reader = LogReader(log_path)
            reader.load_buffer()

            if args.summary:
                # One-shot text summary for agents
                state_reader = StateReader()
                aggregator = StatsAggregator(reader, state_reader)
                print(aggregator.format_summary(project=args.project, limit=args.lines))

            elif args.tail:
                # Simple colorized tail mode
                events = reader.read_recent(args.lines)
                if args.project:
                    events = [e for e in events if e.project == args.project]
                for event in events:
                    print(format_event_line(event))

            else:
                # Full TUI mode
                try:
                    from core.tui.app import RecallMonitorApp
                except ImportError:
                    try:
                        from tui.app import RecallMonitorApp
                    except ImportError as e:
                        print(f"Error: TUI requires textual package: {e}", file=sys.stderr)
                        print("Install with: pip install textual", file=sys.stderr)
                        sys.exit(1)
                app = RecallMonitorApp(project_filter=args.project)
                app.run()

        elif args.command == "session":
            if not args.session_command:
                session_parser.print_help()
                sys.exit(1)

            # Import transcript reader for session operations
            try:
                from core.tui.transcript_reader import (
                    TranscriptReader, detect_origin as _detect_origin
                )
            except ImportError:
                from tui.transcript_reader import (
                    TranscriptReader, detect_origin as _detect_origin
                )

            if args.session_command == "detect-origin":
                # Find the session transcript and detect origin from first prompt
                reader = TranscriptReader()
                sessions = reader.list_all_sessions(limit=500)
                session = None
                for s in sessions:
                    if s.session_id == args.session_id:
                        session = s
                        break
                if session is None:
                    print("Unknown", file=sys.stdout)
                else:
                    print(session.origin)

            elif args.session_command == "find-parent":
                # Find parent session by temporal overlap
                reader = TranscriptReader()
                sessions = reader.list_all_sessions(limit=500)
                # Find our session
                target = None
                for s in sessions:
                    if s.session_id == args.session_id:
                        target = s
                        break
                if target is None or target.origin == "User":
                    # Not found or already a User session (no parent)
                    print("")
                else:
                    # Find User sessions that were active when this started
                    user_sessions = [s for s in sessions if s.origin == "User"]
                    parent_candidates = []
                    for parent in user_sessions:
                        if parent.start_time < target.start_time < parent.last_activity:
                            parent_candidates.append(parent)
                    if parent_candidates:
                        # Prefer most recently started parent
                        best = max(parent_candidates, key=lambda p: p.start_time)
                        print(best.session_id)
                    else:
                        print("")

            elif args.session_command == "link":
                # Link session with origin/parent detection and store in session-handoffs.json
                reader = TranscriptReader()
                sessions = reader.list_all_sessions(limit=500)
                session = None
                for s in sessions:
                    if s.session_id == args.session_id:
                        session = s
                        break

                if session is None:
                    print(f"Error: Session {args.session_id} not found", file=sys.stderr)
                    sys.exit(1)

                origin = session.origin
                parent_id = None

                # Find parent if this is a sub-agent
                if origin != "User":
                    user_sessions = [s for s in sessions if s.origin == "User"]
                    for parent in user_sessions:
                        if parent.start_time < session.start_time < parent.last_activity:
                            parent_id = parent.session_id
                            break

                # Store in session-handoffs.json with extended schema
                handoff_id = args.handoff
                manager.handoff_set_session_extended(
                    session_id=args.session_id,
                    handoff_id=handoff_id,
                    origin=origin,
                    parent_session_id=parent_id,
                    is_sub_agent=(origin != "User"),
                )
                result = {"origin": origin, "parent": parent_id, "handoff": handoff_id}
                print(json_module.dumps(result))

        elif args.command == "extract-context":
            # Extract handoff context from transcript using Python context extractor
            try:
                from core.context_extractor import extract_context, _get_git_ref
            except ImportError:
                from context_extractor import extract_context, _get_git_ref

            transcript_path = Path(args.transcript_path).expanduser()
            if not transcript_path.exists():
                print(f"Error: Transcript not found: {transcript_path}", file=sys.stderr)
                sys.exit(1)

            # Set LESSONS_SCORING_ACTIVE to prevent recursive Haiku calls
            os.environ["LESSONS_SCORING_ACTIVE"] = "1"

            context = extract_context(transcript_path)

            if context is None:
                # Return empty JSON object to indicate extraction failed
                print("{}")
                sys.exit(0)

            # Override git_ref if provided via CLI
            git_ref = getattr(args, "git_ref", None)
            if git_ref:
                context.git_ref = git_ref
            elif not context.git_ref:
                # Try to get git ref from project dir
                context.git_ref = _get_git_ref()

            # Output as JSON
            result = {
                "summary": context.summary,
                "critical_files": context.critical_files,
                "recent_changes": context.recent_changes,
                "learnings": context.learnings,
                "blockers": context.blockers,
                "git_ref": context.git_ref,
            }
            print(json_module.dumps(result))

        elif args.command == "debug":
            try:
                from core.debug_logger import get_logger
            except ImportError:
                from debug_logger import get_logger
            logger = get_logger()

            if args.debug_command == "hook-start":
                logger.hook_start(args.hook, args.trigger)
            elif args.debug_command == "hook-phase":
                details = None
                if args.details:
                    try:
                        details = json_module.loads(args.details)
                    except json_module.JSONDecodeError:
                        pass
                logger.hook_phase(args.hook, args.phase, args.ms, details)
            elif args.debug_command == "hook-end":
                phases = None
                if args.phases:
                    try:
                        phases = json_module.loads(args.phases)
                    except json_module.JSONDecodeError:
                        pass
                # hook_end expects start_time, but from bash we just log directly
                # So we use a simple event write instead
                if logger.level >= 1:
                    event = {
                        "event": "hook_end",
                        "level": "debug",
                        "hook": args.hook,
                        "total_ms": round(args.total_ms, 2),
                    }
                    if phases:
                        event["phases"] = {k: round(v, 2) for k, v in phases.items()}
                    logger._write(event)
            elif args.debug_command == "log-error":
                # Log an error event for debugging hook failures
                logger.inject_error(args.event, args.message)
            elif args.debug_command == "injection-budget":
                # Log injection token budget breakdown
                logger.injection_budget(
                    total_tokens=args.total,
                    lessons_tokens=args.lessons,
                    handoffs_tokens=args.handoffs,
                    duties_tokens=args.duties,
                )
            else:
                print("Unknown debug command", file=sys.stderr)
                sys.exit(1)

        elif args.command == "config":
            try:
                from core.config import get_setting, get_bool_setting, get_int_setting
            except ImportError:
                from config import get_setting, get_bool_setting, get_int_setting

            if args.type == "bool":
                default_bool = args.default.lower() in ("true", "1", "yes") if args.default else False
                value = get_bool_setting(args.key, default_bool)
                # Output shell-friendly booleans
                print("true" if value else "false")
            elif args.type == "int":
                default_int = int(args.default) if args.default else 0
                value = get_int_setting(args.key, default_int)
                print(value)
            else:
                value = get_setting(args.key, args.default if args.default else None)
                # Print value or empty string for None
                print(value if value is not None else "")

    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
