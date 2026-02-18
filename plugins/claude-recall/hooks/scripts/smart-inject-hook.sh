#!/bin/bash
# SPDX-License-Identifier: MIT
# Claude Recall UserPromptSubmit hook - injects lessons relevant to the user's query
#
# Uses local BM25 scoring to find relevant lessons for each prompt.
# Runs on every substantive prompt (>= MIN_PROMPT_LENGTH chars).
# Optional Haiku upgrade path available via useHaikuScoring setting.

set -euo pipefail

# Source shared library
HOOK_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HOOK_LIB_DIR/hook-lib.sh"

# Check for recursion guard early
hook_lib_check_recursion

# Setup environment variables
setup_env

# Read relevanceTopN from settings (default: 5)
get_relevance_top_n() {
    get_setting "relevanceTopN" 5
}

# Tunable parameters for relevance scoring
RELEVANCE_TOP_N=$(get_relevance_top_n)  # Number of lessons to inject after scoring
SCORE_RELEVANCE_TIMEOUT=2  # Local BM25 timeout in seconds
MIN_PROMPT_LENGTH=20       # Skip scoring for very short prompts
MIN_RELEVANCE_SCORE=3      # Only include lessons scored >= this threshold

TOP_LESSONS=$RELEVANCE_TOP_N

# Score lessons against the prompt using local BM25 scoring
score_and_format_lessons() {
    local prompt="$1"
    local cwd="$2"

    local result stderr_file
    stderr_file=$(mktemp)
    result=$(PROJECT_DIR="$cwd" LESSONS_BASE="$LESSONS_BASE" LESSONS_DEBUG="${LESSONS_DEBUG:-}" \
        timeout "$SCORE_RELEVANCE_TIMEOUT" \
        "$GO_RECALL" score-local "$prompt" \
            --top "$TOP_LESSONS" \
            --min-score "$MIN_RELEVANCE_SCORE" 2>"$stderr_file") || {
        local stderr_content
        stderr_content=$(cat "$stderr_file" 2>/dev/null)
        rm -f "$stderr_file"
        if [[ -n "$stderr_content" ]]; then
            log_injection_skip "$cwd" "score_local_error" "$stderr_content"
        fi
        return 1
    }
    rm -f "$stderr_file"

    [[ -z "$result" ]] && return 1
    [[ "$result" == *"No lessons found"* ]] && return 1

    echo "$result"
}

# Score lessons using Haiku API (optional upgrade path)
score_and_format_lessons_haiku() {
    local prompt="$1"
    local cwd="$2"

    local result stderr_file
    stderr_file=$(mktemp)
    result=$(PROJECT_DIR="$cwd" LESSONS_BASE="$LESSONS_BASE" LESSONS_DEBUG="${LESSONS_DEBUG:-}" \
        ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}" \
        LESSONS_SCORING_ACTIVE=1 \
        timeout 10 \
        "$GO_RECALL" score-relevance "$prompt" \
            --top "$TOP_LESSONS" \
            --min-score "$MIN_RELEVANCE_SCORE" \
            --timeout 10 2>"$stderr_file") || {
        local stderr_content
        stderr_content=$(cat "$stderr_file" 2>/dev/null)
        rm -f "$stderr_file"
        if [[ -n "$stderr_content" ]]; then
            log_injection_skip "$cwd" "score_relevance_error" "$stderr_content"
        fi
        return 1
    }
    rm -f "$stderr_file"

    [[ -z "$result" ]] && return 1
    [[ "$result" == *"No lessons found"* ]] && return 1
    [[ "$result" == *"error"* ]] && return 1

    echo "$result"
}

# Log when prompt-submit injection is skipped
log_injection_skip() {
    local project_root="$1" reason="$2" detail="$3"
    [[ -z "$GO_RECALL" || ! -x "$GO_RECALL" ]] && return 0
    [[ "${CLAUDE_RECALL_DEBUG:-0}" -lt 1 ]] && return 0
    PROJECT_DIR="$project_root" "$GO_RECALL" debug log "lessons_injection_skipped: hook=prompt_submit reason=$reason detail=$detail" 2>/dev/null &
}

main() {
    is_enabled || exit 0

    # Parse input
    local input=$(cat)
    local prompt=$(echo "$input" | jq -r '.prompt // ""' 2>/dev/null || echo "")
    local cwd=$(echo "$input" | jq -r '.cwd // "."' 2>/dev/null || echo ".")

    local project_root=$(find_project_root "$cwd")

    # Skip if no prompt
    [[ -z "$prompt" ]] && exit 0

    # Skip short prompts (greetings, confirmations, etc.)
    if [[ ${#prompt} -lt $MIN_PROMPT_LENGTH ]]; then
        log_injection_skip "$project_root" "short_prompt" "length=${#prompt}, min=$MIN_PROMPT_LENGTH"
        exit 0
    fi

    # Skip if Go binary doesn't exist
    [[ -z "$GO_RECALL" || ! -x "$GO_RECALL" ]] && exit 0

    # Optional Haiku scoring upgrade (requires API key + explicit opt-in)
    local use_haiku="false"
    if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
        use_haiku=$(get_setting "useHaikuScoring" "false")
    fi

    # Score lessons against the prompt
    local scored_lessons
    if [[ "$use_haiku" == "true" ]]; then
        if ! scored_lessons=$(score_and_format_lessons_haiku "$prompt" "$cwd"); then
            log_injection_skip "$project_root" "score_failed" "timeout or error from score-relevance (haiku)"
            exit 0
        fi
    else
        if ! scored_lessons=$(score_and_format_lessons "$prompt" "$cwd"); then
            log_injection_skip "$project_root" "score_failed" "timeout or error from score-local"
            exit 0
        fi
    fi

    # If we got relevant lessons, inject them
    if [[ -n "$scored_lessons" ]]; then
        local context="RELEVANT LESSONS for your query:
$scored_lessons

Cite [ID] when applying. LESSON: [category:] title - content to add (output only, no shell commands)."

        local escaped=$(printf '%s' "$context" | jq -Rs .)
        cat << EOF
{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":$escaped}}
EOF
    fi

    exit 0
}

main
