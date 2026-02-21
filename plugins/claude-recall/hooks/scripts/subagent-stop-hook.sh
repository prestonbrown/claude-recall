#!/bin/bash
# SPDX-License-Identifier: MIT
# Claude Recall SubagentStop hook - injects relevant lessons after subagent work
#
# Uses local BM25 scoring to find lessons relevant to the subagent's output.
# Skips short outputs (<50 chars) to avoid noise from trivial subagent runs.

set -euo pipefail

# Source shared library
HOOK_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HOOK_LIB_DIR/hook-lib.sh"

# Check for recursion guard early
hook_lib_check_recursion

# Setup environment variables
setup_env

# Tunable parameters
MIN_SUBAGENT_OUTPUT=50     # Skip scoring for very short subagent output
SUBAGENT_TOP_N=3           # Fewer results than prompt injection
SUBAGENT_MIN_SCORE=3       # Higher threshold than prompt injection
SUBAGENT_QUERY_MAX=2000    # Truncate long output for scoring
SCORE_TIMEOUT=2            # Local BM25 timeout in seconds

main() {
    is_enabled || exit 0

    # Parse input - SubagentStop provides cwd and the subagent's output
    local input=$(cat)
    local cwd=$(echo "$input" | jq -r '.cwd // "."' 2>/dev/null || echo ".")

    # Set session ID for dedup tracking
    local session_id=$(echo "$input" | jq -r '.session_id // ""' 2>/dev/null || echo "")
    _HOOK_SESSION_ID="$session_id"
    local subagent_output=$(echo "$input" | jq -r '.stdout // .output // ""' 2>/dev/null || echo "")

    # Skip if output is empty or very short
    [[ -z "$subagent_output" ]] && exit 0
    [[ ${#subagent_output} -lt $MIN_SUBAGENT_OUTPUT ]] && exit 0

    local project_root=$(find_project_root "$cwd")

    # Skip if Go binary doesn't exist
    [[ -z "$GO_RECALL" || ! -x "$GO_RECALL" ]] && exit 0

    # Truncate long output for scoring
    local query="${subagent_output:0:$SUBAGENT_QUERY_MAX}"

    local result stderr_file
    stderr_file=$(mktemp)
    result=$(PROJECT_DIR="$project_root" LESSONS_BASE="$LESSONS_BASE" LESSONS_DEBUG="${LESSONS_DEBUG:-}" \
        timeout "$SCORE_TIMEOUT" \
        "$GO_RECALL" score-local "$query" \
            --top "$SUBAGENT_TOP_N" \
            --min-score "$SUBAGENT_MIN_SCORE" 2>"$stderr_file") || {
        rm -f "$stderr_file"
        exit 0
    }
    rm -f "$stderr_file"

    [[ -z "$result" ]] && exit 0
    [[ "$result" == *"No lessons found"* ]] && exit 0

    # Extract IDs from results
    local new_ids=$(echo "$result" | grep -oE '\[[LS][0-9]{3}\]' | tr -d '[]' | sort -u)

    # Filter out already injected (remove header + content line pairs)
    local injected=$(get_injected_ids)
    if [[ -n "$injected" ]]; then
        local filtered=""
        local skip_next=false
        while IFS= read -r line; do
            if $skip_next; then
                skip_next=false
                continue
            fi
            local dominated=false
            while IFS= read -r id; do
                if [[ -n "$id" && "$line" == *"[$id]"* ]]; then
                    dominated=true
                    break
                fi
            done <<< "$injected"
            if $dominated; then
                skip_next=true
                continue
            fi
            if [[ -n "$filtered" ]]; then
                filtered="$filtered"$'\n'"$line"
            else
                filtered="$line"
            fi
        done <<< "$result"
        result="$filtered"
    fi

    # Re-extract IDs after filtering
    new_ids=$(echo "$result" | grep -oE '\[[LS][0-9]{3}\]' | tr -d '[]' | sort -u)

    [[ -z "$result" ]] && exit 0

    local context="RELEVANT LESSONS after subagent work:
$result

Cite [ID] when applying."

    local escaped=$(printf '%s' "$context" | jq -Rs .)
    cat << EOF
{"hookSpecificOutput":{"hookEventName":"SubagentStop","additionalContext":$escaped}}
EOF

    # Record injected IDs for dedup
    [[ -n "$new_ids" ]] && record_injected $new_ids
}

main
