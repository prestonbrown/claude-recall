#!/bin/bash
# SPDX-License-Identifier: MIT
# Claude Code PreCompact hook - captures session progress before compaction
#
# When auto-compaction or /compact is triggered, this hook:
# 1. Reads recent conversation from transcript
# 2. Uses Haiku to extract structured HandoffContext as JSON
# 3. Updates the most recent active handoff's context via set-context CLI
#
# This enables rich session handoff across compactions.

set -uo pipefail

# Support both new (RECALL_*) and old (LESSONS_*) env vars for backward compatibility
LESSONS_BASE="${RECALL_BASE:-${LESSONS_BASE:-$HOME/.config/coding-agent-lessons}}"
LESSONS_DEBUG="${RECALL_DEBUG:-${LESSONS_DEBUG:-}}"
# Python manager - try installed location first, fall back to dev location
if [[ -f "$LESSONS_BASE/cli.py" ]]; then
    PYTHON_MANAGER="$LESSONS_BASE/cli.py"
else
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    PYTHON_MANAGER="$SCRIPT_DIR/../../core/cli.py"
fi

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

# Get current git commit hash (short form)
get_git_ref() {
    local project_root="$1"
    git -C "$project_root" rev-parse --short HEAD 2>/dev/null || echo ""
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

# Call Haiku to extract structured handoff context as JSON
extract_handoff_context() {
    local messages="$1"
    local git_ref="$2"

    # Skip if messages are empty or too short
    [[ ${#messages} -lt 50 ]] && return 1

    local prompt='Analyze this conversation and extract a structured handoff context for session continuity.

Return ONLY valid JSON with these fields:
{
  "summary": "1-2 sentence progress summary - what was accomplished and current state",
  "critical_files": ["file.py:42", "other.py:100"],  // 2-3 most important file:line refs mentioned
  "recent_changes": ["Added X", "Fixed Y"],          // list of changes made this session
  "learnings": ["Pattern found", "Gotcha discovered"], // discoveries/patterns found
  "blockers": ["Waiting for Z"]                       // issues blocking progress (empty if none)
}

Important:
- Return ONLY the JSON object, no markdown code blocks, no explanation
- Keep arrays short (2-5 items max)
- Use file:line format for critical_files when line numbers are mentioned
- Leave arrays empty [] if nothing applies

Conversation:
'"$messages"

    # Call claude in programmatic mode with haiku
    local result
    result=$(echo "$prompt" | timeout "$CLAUDE_TIMEOUT" claude -p --model haiku 2>/dev/null) || return 1

    # Validate we got something useful
    [[ -z "$result" ]] && return 1

    # Strip any markdown code block markers if present
    result=$(echo "$result" | sed 's/^```json//g' | sed 's/^```//g' | sed 's/```$//g')

    # Inject git_ref into the JSON
    result=$(echo "$result" | jq --arg ref "$git_ref" '. + {git_ref: $ref}' 2>/dev/null) || return 1

    echo "$result"
}

# Legacy: Call Haiku to extract simple progress summary (fallback)
# TODO: Remove this function after 2025-06-01 when all users have migrated to structured handoff context
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

# Get the most recent active handoff
get_most_recent_handoff() {
    local project_root="$1"

    if [[ -f "$PYTHON_MANAGER" ]]; then
        # Get first non-completed handoff (most recent by file order)
        # Matches both legacy A### format and new hf-XXXXXXX format
        PROJECT_DIR="$project_root" LESSONS_BASE="$LESSONS_BASE" \
            python3 "$PYTHON_MANAGER" handoff list 2>/dev/null | \
            head -1 | grep -oE '\[(A[0-9]{3}|hf-[0-9a-f]+)\]' | tr -d '[]' || true
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

    # Find most recent active handoff
    local handoff_id
    handoff_id=$(get_most_recent_handoff "$project_root")

    # No active handoff - nothing to checkpoint
    [[ -z "$handoff_id" ]] && {
        echo "[precompact] No active handoff to checkpoint" >&2
        exit 0
    }

    # Extract recent messages
    local messages
    messages=$(extract_recent_messages "$transcript_path" "$MAX_MESSAGES")

    [[ -z "$messages" ]] && {
        echo "[precompact] No messages to summarize" >&2
        exit 0
    }

    # Get current git ref
    local git_ref
    git_ref=$(get_git_ref "$project_root")

    # Try to extract structured handoff context first
    local context_json
    context_json=$(extract_handoff_context "$messages" "$git_ref")

    if [[ -n "$context_json" ]] && echo "$context_json" | jq -e . >/dev/null 2>&1; then
        # Use new structured set-context command
        if [[ -f "$PYTHON_MANAGER" ]]; then
            local result
            result=$(PROJECT_DIR="$project_root" LESSONS_BASE="$LESSONS_BASE" LESSONS_DEBUG="${LESSONS_DEBUG:-}" \
                python3 "$PYTHON_MANAGER" handoff set-context "$handoff_id" --json "$context_json" 2>&1)

            if [[ $? -eq 0 ]]; then
                local summary_preview
                summary_preview=$(echo "$context_json" | jq -r '.summary // ""' | head -c 50)
                echo "[precompact] Set context for $handoff_id (git: ${git_ref:-none}): ${summary_preview}..." >&2
            else
                echo "[precompact] Failed to set context: $result" >&2
                # Fall through to legacy checkpoint
            fi
        fi
    else
        # Fallback to legacy checkpoint if structured extraction fails
        echo "[precompact] Falling back to legacy checkpoint" >&2
        local summary
        summary=$(extract_progress_summary "$messages") || {
            echo "[precompact] Failed to extract progress summary" >&2
            exit 0
        }

        if [[ -f "$PYTHON_MANAGER" ]]; then
            local result
            result=$(PROJECT_DIR="$project_root" LESSONS_BASE="$LESSONS_BASE" LESSONS_DEBUG="${LESSONS_DEBUG:-}" \
                python3 "$PYTHON_MANAGER" handoff update "$handoff_id" --checkpoint "$summary" 2>&1)

            if [[ $? -eq 0 ]]; then
                echo "[precompact] Checkpointed $handoff_id: ${summary:0:50}..." >&2
            else
                echo "[precompact] Failed to update checkpoint: $result" >&2
            fi
        fi
    fi

    exit 0
}

main
