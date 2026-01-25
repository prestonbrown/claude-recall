#!/bin/bash
# SPDX-License-Identifier: MIT
# Claude Recall PreCompact hook - captures session progress before compaction
#
# When auto-compaction or /compact is triggered, this hook:
# 1. Reads recent conversation from transcript
# 2. Uses Haiku to extract structured HandoffContext as JSON
# 3. Updates the most recent active handoff's context via set-context CLI
#
# This enables rich session handoff across compactions.

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
# Timeout for Haiku calls that aren't handled by Python CLI
HAIKU_TIMEOUT=15

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

# Detect if transcript indicates major work requiring a handoff
# Returns: comma-separated indicators if major, empty if minor
detect_major_work() {
    local transcript_path="$1"
    local indicators=""

    # Count TodoWrite tool uses
    local todo_count
    todo_count=$(jq -s '[.[].message.content[]? | select(.type == "tool_use" and .name == "TodoWrite")] | length' "$transcript_path" 2>/dev/null || echo "0")
    [[ $todo_count -ge 3 ]] && indicators="todos:$todo_count"

    # Count unique file edits (Edit tool_use)
    local file_count
    file_count=$(jq -rs '[.[].message.content[]? | select(.type == "tool_use" and .name == "Edit") | .input.file_path] | unique | length' "$transcript_path" 2>/dev/null || echo "0")
    if [[ $file_count -ge 4 ]]; then
        [[ -n "$indicators" ]] && indicators="$indicators,"
        indicators="${indicators}files:$file_count"
    fi

    # Check for implementing keywords in assistant messages
    local has_impl_keywords
    has_impl_keywords=$(jq -rs '[.[]] | map(select(.type == "assistant") | .message.content) | flatten | map(select(type == "object" and .type == "text") | .text) | join(" ")' "$transcript_path" 2>/dev/null | grep -iE '(implement|refactor|integrat|migrat|major change|multi-step|architecture)' | head -1)
    if [[ -n "$has_impl_keywords" ]]; then
        [[ -n "$indicators" ]] && indicators="$indicators,"
        indicators="${indicators}keywords"
    fi

    echo "$indicators"
}

# Extract simple user messages from transcript (for title generation)
# This is a simpler extraction just for getting user prompts, not full context
extract_user_messages() {
    local transcript_path="$1"
    local max_messages="${2:-10}"

    # Get last N user messages only - just need the prompts for title generation
    jq -r 'select(.type == "user") | "User: " + (.message.content // "")' "$transcript_path" 2>/dev/null | tail -n "$max_messages"
}

# Auto-create a handoff from transcript analysis
auto_create_handoff() {
    local project_root="$1"
    local transcript_path="$2"

    # Get user messages for title generation
    local messages
    messages=$(extract_user_messages "$transcript_path" 10)

    # Use Haiku to generate a title from the messages
    local title
    title=$(echo "$messages" | head -c 2000 | LESSONS_SCORING_ACTIVE=1 timeout "$HAIKU_TIMEOUT" claude -p --model haiku "Summarize this work in 5-10 words as a task title (no punctuation, no quotes):" 2>/dev/null | head -1 | tr -d '"')
    [[ -z "$title" || ${#title} -lt 5 ]] && title="Auto-detected work session"

    # Create the handoff with implementing phase (we're mid-work)
    local result
    result=$(PROJECT_DIR="$project_root" LESSONS_BASE="$LESSONS_BASE" \
        "$PYTHON_BIN" "$PYTHON_MANAGER" handoff add --phase implementing -- "$title" 2>&1)

    # Extract the ID
    echo "$result" | grep -oE 'hf-[0-9a-f]{7}' | head -1
}

# Save a minimal session snapshot for non-major work
save_session_snapshot() {
    local project_root="$1"
    local transcript_path="$2"

    local snapshot_dir="$project_root/.claude-recall"
    local snapshot_file="$snapshot_dir/.session-snapshot"
    mkdir -p "$snapshot_dir"

    # Get user messages for summary generation
    local messages
    messages=$(extract_user_messages "$transcript_path" 10)

    # Use Haiku to generate a brief summary
    local summary
    summary=$(echo "$messages" | head -c 2000 | LESSONS_SCORING_ACTIVE=1 timeout "$HAIKU_TIMEOUT" claude -p --model haiku "One sentence summary of what was done in this session:" 2>/dev/null | head -1)
    [[ -z "$summary" ]] && summary="Session work (summary unavailable)"

    # Save with timestamp
    cat > "$snapshot_file" << EOF
timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)
summary: $summary
EOF
    echo "[precompact] Saved session snapshot to $snapshot_file" >&2
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

    # Export PROJECT_DIR for Python CLI
    export PROJECT_DIR="$project_root"

    # Find most recent active handoff
    local handoff_id
    handoff_id=$(get_most_recent_handoff "$project_root")

    # No active handoff - detect if we should create one or save snapshot
    if [[ -z "$handoff_id" ]]; then
        local work_indicators
        work_indicators=$(detect_major_work "$transcript_path")

        if [[ -n "$work_indicators" ]]; then
            # Major work detected - auto-create handoff
            echo "[precompact] Major work detected ($work_indicators) - auto-creating handoff" >&2
            handoff_id=$(auto_create_handoff "$project_root" "$transcript_path")
            if [[ -z "$handoff_id" ]]; then
                echo "[precompact] Failed to auto-create handoff, saving snapshot instead" >&2
                save_session_snapshot "$project_root" "$transcript_path"
                exit 0
            fi
            echo "[precompact] Auto-created handoff $handoff_id" >&2
        else
            # Minor work - save session snapshot
            save_session_snapshot "$project_root" "$transcript_path"
            exit 0
        fi
    fi

    # Get current git ref
    local git_ref
    git_ref=$(get_git_ref "$project_root")

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
                echo "[precompact] Set context for $handoff_id (git: ${git_ref:-none}): ${summary_preview}..." >&2
            else
                echo "[precompact] Failed to set context: $result" >&2
            fi
        fi
    else
        echo "[precompact] Failed to extract handoff context" >&2
    fi

    exit 0
}

main
