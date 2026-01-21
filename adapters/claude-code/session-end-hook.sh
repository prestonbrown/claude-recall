#!/bin/bash
# SPDX-License-Identifier: MIT
# Claude Recall SessionEnd hook - captures handoff context on normal session exit
#
# When a session ends normally (not via error), this hook:
# 1. Reads recent conversation from transcript
# 2. Uses Haiku to extract structured HandoffContext as JSON
# 3. Updates the most recent active handoff's context via set-context CLI
#
# This enables rich session handoff across sessions (not just compactions).
#
# Stop event provides:
#   - $CLAUDE_STOP_REASON: "user", "end_turn", "max_turns", etc.
#   - stdin: JSON with cwd, transcript_path, etc.

set -uo pipefail

# Source shared library
HOOK_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HOOK_LIB_DIR/hook-lib.sh"

# Check for recursion guard early
hook_lib_check_recursion

# Setup environment variables
setup_env

# Timeout for context extraction (seconds) - passed to Python CLI
CONTEXT_TIMEOUT=45

# Extract handoff context using Python CLI (unified extraction with tool_use/thinking support)
extract_handoff_context_python() {
    local transcript_path="$1"
    local git_ref="$2"

    if [[ ! -f "$PYTHON_MANAGER" ]]; then
        return 1
    fi

    # Call Python CLI for context extraction - it handles:
    # - Reading transcript with tool_use/thinking blocks
    # - Calling Haiku for summarization
    # - Validating the result (rejects garbage summaries)
    local result
    result=$(PROJECT_DIR="$PROJECT_DIR" LESSONS_BASE="$LESSONS_BASE" LESSONS_SCORING_ACTIVE=1 \
        timeout "$CONTEXT_TIMEOUT" "$PYTHON_BIN" "$PYTHON_MANAGER" extract-context "$transcript_path" --git-ref "$git_ref" 2>/dev/null) || return 1

    # Check if we got valid JSON (not empty object)
    if [[ -z "$result" ]] || [[ "$result" == "{}" ]]; then
        return 1
    fi

    # Validate JSON structure
    echo "$result" | jq -e '.summary' >/dev/null 2>&1 || return 1

    echo "$result"
}

# Get the most recent active handoff
get_most_recent_handoff() {
    local project_root="$1"

    if [[ -f "$PYTHON_MANAGER" ]]; then
        # Get first non-completed handoff (most recent by file order)
        # Matches both legacy A### format and new hf-XXXXXXX format
        PROJECT_DIR="$project_root" LESSONS_BASE="$LESSONS_BASE" \
            "$PYTHON_BIN" "$PYTHON_MANAGER" handoff list 2>/dev/null | \
            head -1 | grep -oE '\[(A[0-9]{3}|hf-[0-9a-f]+)\]' | tr -d '[]' || true
    fi
}

# Check if stop reason indicates a clean exit
is_clean_exit() {
    local stop_reason="$1"

    # Clean exit reasons - session ended normally
    case "$stop_reason" in
        # Normal exit conditions
        user|end_turn|max_turns|stop_sequence|"")
            return 0
            ;;
        # Error conditions - don't capture
        error|tool_error|timeout)
            return 1
            ;;
        # Unknown reasons - assume clean (be permissive)
        *)
            return 0
            ;;
    esac
}

# Background worker function - runs the slow Haiku API call asynchronously
# This is spawned via nohup so it doesn't block the user
do_extract_and_set_context() {
    local transcript_path="$1"
    local git_ref="$2"
    local handoff_id="$3"
    local project_root="$4"

    # Extract structured handoff context using Python CLI
    # This handles tool_use/thinking blocks properly (not just text blocks)
    local context_json
    context_json=$(extract_handoff_context_python "$transcript_path" "$git_ref")

    if [[ -n "$context_json" ]] && echo "$context_json" | jq -e . >/dev/null 2>&1; then
        # Use structured set-context command
        if [[ -f "$PYTHON_MANAGER" ]]; then
            local result
            result=$(PROJECT_DIR="$project_root" LESSONS_BASE="$LESSONS_BASE" LESSONS_DEBUG="${LESSONS_DEBUG:-}" \
                "$PYTHON_BIN" "$PYTHON_MANAGER" handoff set-context "$handoff_id" --json "$context_json" 2>&1)

            if [[ $? -eq 0 ]]; then
                local summary_preview
                summary_preview=$(echo "$context_json" | jq -r '.summary // ""' | head -c 50)
                echo "[session-end] Set context for $handoff_id (git: ${git_ref:-none}): ${summary_preview}..."
            else
                echo "[session-end] Failed to set context: $result"
            fi
        fi
    else
        echo "[session-end] Failed to extract handoff context"
    fi
}

main() {
    is_enabled || exit 0

    # Read input from stdin
    local input=$(cat)

    # Get stop reason from environment (set by Claude Code)
    local stop_reason="${CLAUDE_STOP_REASON:-}"

    # Also try to get it from input JSON (fallback)
    if [[ -z "$stop_reason" ]]; then
        stop_reason=$(echo "$input" | jq -r '.stop_reason // ""' 2>/dev/null || echo "")
    fi

    # Only capture handoff on clean exits
    if [[ -n "$stop_reason" ]] && ! is_clean_exit "$stop_reason"; then
        echo "[session-end] Skipping handoff capture for stop reason: $stop_reason" >&2
        exit 0
    fi

    local cwd=$(echo "$input" | jq -r '.cwd // "."' 2>/dev/null || echo ".")
    local project_root=$(find_project_root "$cwd")
    local transcript_path=$(echo "$input" | jq -r '.transcript_path // ""' 2>/dev/null || echo "")

    # Expand tilde
    transcript_path="${transcript_path/#\~/$HOME}"

    [[ -z "$transcript_path" || ! -f "$transcript_path" ]] && exit 0

    # Find most recent active handoff
    local handoff_id
    handoff_id=$(get_most_recent_handoff "$project_root")

    # No active handoff - nothing to checkpoint
    [[ -z "$handoff_id" ]] && {
        echo "[session-end] No active handoff to checkpoint" >&2
        exit 0
    }

    # Export PROJECT_DIR for Python CLI
    export PROJECT_DIR="$project_root"

    # Get current git ref
    local git_ref
    git_ref=$(get_git_ref "$project_root")

    # Run the slow Haiku API call in background so we don't block the user
    # This saves ~1.5-3 seconds of perceived latency
    # Output goes to background.log for debugging
    nohup bash -c "$(declare -f extract_handoff_context_python do_extract_and_set_context); \
        PYTHON_MANAGER='$PYTHON_MANAGER' \
        PROJECT_DIR='$project_root' \
        LESSONS_BASE='$LESSONS_BASE' \
        LESSONS_DEBUG='${LESSONS_DEBUG:-}' \
        LESSONS_SCORING_ACTIVE=1 \
        CONTEXT_TIMEOUT='$CONTEXT_TIMEOUT' \
        do_extract_and_set_context '$transcript_path' '$git_ref' '$handoff_id' '$project_root'" \
        >> "$CLAUDE_RECALL_STATE/background.log" 2>&1 &

    # Disown the background process so it's not tied to this shell
    disown 2>/dev/null || true

    exit 0
}

main
