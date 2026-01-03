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

# Guard against recursive calls from Haiku subprocesses
[[ -n "${LESSONS_SCORING_ACTIVE:-}" ]] && exit 0

# Support new (CLAUDE_RECALL_*), transitional (RECALL_*), and legacy (LESSONS_*) env vars
CLAUDE_RECALL_BASE="${CLAUDE_RECALL_BASE:-${RECALL_BASE:-${LESSONS_BASE:-$HOME/.config/claude-recall}}}"
CLAUDE_RECALL_DEBUG="${CLAUDE_RECALL_DEBUG:-${RECALL_DEBUG:-${LESSONS_DEBUG:-}}}"
# Export legacy names for downstream compatibility
LESSONS_BASE="$CLAUDE_RECALL_BASE"
LESSONS_DEBUG="$CLAUDE_RECALL_DEBUG"
# Python manager - try installed location first, fall back to dev location
if [[ -f "$CLAUDE_RECALL_BASE/cli.py" ]]; then
    PYTHON_MANAGER="$CLAUDE_RECALL_BASE/cli.py"
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
    result=$(echo "$prompt" | LESSONS_SCORING_ACTIVE=1 timeout "$CLAUDE_TIMEOUT" claude -p --model haiku 2>/dev/null) || return 1

    # Validate we got something useful
    [[ -z "$result" ]] && return 1

    # Strip any markdown code block markers if present
    result=$(echo "$result" | sed 's/^```json//g' | sed 's/^```//g' | sed 's/```$//g')

    # Inject git_ref into the JSON
    result=$(echo "$result" | jq --arg ref "$git_ref" '. + {git_ref: $ref}' 2>/dev/null) || return 1

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

    # Extract recent messages
    local messages
    messages=$(extract_recent_messages "$transcript_path" "$MAX_MESSAGES")

    [[ -z "$messages" ]] && {
        echo "[session-end] No messages to summarize" >&2
        exit 0
    }

    # Get current git ref
    local git_ref
    git_ref=$(get_git_ref "$project_root")

    # Extract structured handoff context
    local context_json
    context_json=$(extract_handoff_context "$messages" "$git_ref")

    if [[ -n "$context_json" ]] && echo "$context_json" | jq -e . >/dev/null 2>&1; then
        # Use structured set-context command
        if [[ -f "$PYTHON_MANAGER" ]]; then
            local result
            result=$(PROJECT_DIR="$project_root" LESSONS_BASE="$LESSONS_BASE" LESSONS_DEBUG="${LESSONS_DEBUG:-}" \
                python3 "$PYTHON_MANAGER" handoff set-context "$handoff_id" --json "$context_json" 2>&1)

            if [[ $? -eq 0 ]]; then
                local summary_preview
                summary_preview=$(echo "$context_json" | jq -r '.summary // ""' | head -c 50)
                echo "[session-end] Set context for $handoff_id (git: ${git_ref:-none}): ${summary_preview}..." >&2
            else
                echo "[session-end] Failed to set context: $result" >&2
            fi
        fi
    else
        echo "[session-end] Failed to extract handoff context" >&2
    fi

    exit 0
}

main
