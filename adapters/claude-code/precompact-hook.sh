#!/bin/bash
# SPDX-License-Identifier: MIT
# Claude Code PreCompact hook - captures session progress before compaction
#
# When auto-compaction or /compact is triggered, this hook:
# 1. Reads recent conversation from transcript
# 2. Uses Haiku to extract a progress summary
# 3. Updates the most recent active approach's checkpoint
#
# This enables session handoff across compactions.

set -uo pipefail

LESSONS_BASE="${LESSONS_BASE:-$HOME/.config/coding-agent-lessons}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_MANAGER="$SCRIPT_DIR/../../core/lessons_manager.py"

# Maximum messages to include in summary prompt
MAX_MESSAGES=20
# Timeout for claude call (seconds)
CLAUDE_TIMEOUT=30

is_enabled() {
    local config="$HOME/.claude/settings.json"
    [[ -f "$config" ]] && {
        local enabled=$(jq -r '.lessonsSystem.enabled // true' "$config" 2>/dev/null || echo "true")
        [[ "$enabled" == "true" ]]
    } || return 0
}

find_project_root() {
    local dir="${1:-$(pwd)}"
    while [[ "$dir" != "/" ]]; do
        [[ -d "$dir/.git" ]] && { echo "$dir"; return 0; }
        dir=$(dirname "$dir")
    done
    echo "$1"
}

# Extract recent messages from transcript for summarization
extract_recent_messages() {
    local transcript_path="$1"
    local max_messages="$2"

    # Get last N user/assistant messages, format as conversation
    jq -r --argjson max "$max_messages" '
        select(.type == "user" or .type == "assistant") |
        if .type == "user" then
            "User: " + (.message.content // "")
        else
            "Assistant: " + (
                if .message.content | type == "array" then
                    [.message.content[] | select(.type == "text") | .text] | join(" ")
                else
                    .message.content // ""
                end
            )
        end
    ' "$transcript_path" 2>/dev/null | tail -n "$max_messages"
}

# Call Haiku to extract progress summary
extract_progress_summary() {
    local messages="$1"

    # Skip if messages are empty or too short
    [[ ${#messages} -lt 50 ]] && return 1

    local prompt="Analyze this conversation excerpt and provide a VERY BRIEF progress summary (1-2 sentences max).
Focus on: what was accomplished, current state, and immediate next step.
Format: Just the summary text, no labels or formatting.

Conversation:
$messages"

    # Call claude in programmatic mode with haiku
    local result
    result=$(echo "$prompt" | timeout "$CLAUDE_TIMEOUT" claude -p --model haiku 2>/dev/null) || return 1

    # Validate we got something useful
    [[ -z "$result" ]] && return 1
    [[ ${#result} -gt 500 ]] && result="${result:0:500}..."

    echo "$result"
}

# Get the most recent active approach
get_most_recent_approach() {
    local project_root="$1"

    if [[ -f "$PYTHON_MANAGER" ]]; then
        # Get first non-completed approach (most recent by file order)
        PROJECT_DIR="$project_root" LESSONS_BASE="$LESSONS_BASE" \
            python3 "$PYTHON_MANAGER" approach list 2>/dev/null | \
            head -1 | grep -oE '\[A[0-9]{3}\]' | tr -d '[]' || true
    fi
}

main() {
    is_enabled || exit 0

    # Read input from stdin
    local input=$(cat)

    local cwd=$(echo "$input" | jq -r '.cwd // "."' 2>/dev/null || echo ".")
    local project_root=$(find_project_root "$cwd")
    local transcript_path=$(echo "$input" | jq -r '.transcript_path // ""' 2>/dev/null || echo "")
    local trigger=$(echo "$input" | jq -r '.trigger // "auto"' 2>/dev/null || echo "auto")

    # Expand tilde
    transcript_path="${transcript_path/#\~/$HOME}"

    [[ -z "$transcript_path" || ! -f "$transcript_path" ]] && exit 0

    # Find most recent active approach
    local approach_id
    approach_id=$(get_most_recent_approach "$project_root")

    # No active approach - nothing to checkpoint
    [[ -z "$approach_id" ]] && {
        echo "[precompact] No active approach to checkpoint" >&2
        exit 0
    }

    # Extract recent messages
    local messages
    messages=$(extract_recent_messages "$transcript_path" "$MAX_MESSAGES")

    [[ -z "$messages" ]] && {
        echo "[precompact] No messages to summarize" >&2
        exit 0
    }

    # Call Haiku to extract progress summary
    local summary
    summary=$(extract_progress_summary "$messages") || {
        echo "[precompact] Failed to extract progress summary" >&2
        exit 0
    }

    # Update the approach checkpoint
    if [[ -f "$PYTHON_MANAGER" ]]; then
        local result
        result=$(PROJECT_DIR="$project_root" LESSONS_BASE="$LESSONS_BASE" LESSONS_DEBUG="${LESSONS_DEBUG:-}" \
            python3 "$PYTHON_MANAGER" approach update "$approach_id" --checkpoint "$summary" 2>&1)

        if [[ $? -eq 0 ]]; then
            echo "[precompact] Checkpointed $approach_id: ${summary:0:50}..." >&2
        else
            echo "[precompact] Failed to update checkpoint: $result" >&2
        fi
    fi

    exit 0
}

main
