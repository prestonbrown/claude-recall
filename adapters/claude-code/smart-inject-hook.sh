#!/bin/bash
# SPDX-License-Identifier: MIT
# Claude Recall UserPromptSubmit hook - injects lessons relevant to the user's query
#
# Uses Haiku to score lesson relevance against the user's prompt.
# Only runs on first prompt of session to avoid latency on every message.

set -euo pipefail

# Guard against recursive calls: skip if we're inside a score-relevance subagent
# This prevents infinite loops when Haiku subagents trigger this hook
[[ -n "${LESSONS_SCORING_ACTIVE:-}" ]] && exit 0

# Support new (CLAUDE_RECALL_*), transitional (RECALL_*), and legacy (LESSONS_*) env vars
CLAUDE_RECALL_BASE="${CLAUDE_RECALL_BASE:-${RECALL_BASE:-${LESSONS_BASE:-$HOME/.config/claude-recall}}}"
CLAUDE_RECALL_STATE="${CLAUDE_RECALL_STATE:-${XDG_STATE_HOME:-$HOME/.local/state}/claude-recall}"
CLAUDE_RECALL_DEBUG="${CLAUDE_RECALL_DEBUG:-${RECALL_DEBUG:-${LESSONS_DEBUG:-}}}"
# Export for downstream Python manager
export CLAUDE_RECALL_STATE
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

# Read relevanceTopN from settings (default: 5)
get_relevance_top_n() {
    local config="$HOME/.claude/settings.json"
    if [[ -f "$config" ]]; then
        jq -r '.claudeRecall.relevanceTopN // 5' "$config" 2>/dev/null || echo "5"
    else
        echo "5"
    fi
}

# Tunable parameters for relevance scoring
RELEVANCE_TOP_N=$(get_relevance_top_n)  # Number of lessons to inject after scoring
SCORE_RELEVANCE_TIMEOUT=10 # Haiku timeout in seconds (10s handles ~100 lessons)
MIN_PROMPT_LENGTH=20       # Skip scoring for very short prompts
MIN_RELEVANCE_SCORE=3      # Only include lessons scored >= this threshold

# Backward compatibility aliases
TOP_LESSONS=$RELEVANCE_TOP_N
RELEVANCE_TIMEOUT=$SCORE_RELEVANCE_TIMEOUT

is_enabled() {
    local config="$HOME/.claude/settings.json"
    [[ -f "$config" ]] && {
        local enabled=$(jq -r '.claudeRecall.enabled // true' "$config" 2>/dev/null || echo "true")
        [[ "$enabled" == "true" ]]
    } || return 0
}

# Check if this is the first prompt in the session
# Returns 0 (true) if first prompt, 1 (false) otherwise
is_first_prompt() {
    local transcript_path="$1"

    # No transcript = first prompt
    [[ -z "$transcript_path" || ! -f "$transcript_path" ]] && return 0

    # Empty transcript = first prompt
    local size=$(wc -c < "$transcript_path" 2>/dev/null || echo "0")
    [[ "$size" -eq 0 ]] && return 0

    # Check if transcript has any assistant messages yet
    # If no assistant messages, this is still the "first" meaningful prompt
    if ! grep -q '"role":"assistant"' "$transcript_path" 2>/dev/null; then
        return 0
    fi

    return 1
}

# Score lessons against the prompt and return formatted output
score_and_format_lessons() {
    local prompt="$1"
    local cwd="$2"

    # Call the Python score-relevance command
    # Export LESSONS_SCORING_ACTIVE so Python can inherit it and pass to Haiku subprocess
    local result
    result=$(PROJECT_DIR="$cwd" LESSONS_BASE="$LESSONS_BASE" LESSONS_DEBUG="${LESSONS_DEBUG:-}" \
        LESSONS_SCORING_ACTIVE=1 \
        timeout "$RELEVANCE_TIMEOUT" \
        python3 "$PYTHON_MANAGER" score-relevance "$prompt" \
            --top "$TOP_LESSONS" \
            --min-score "$MIN_RELEVANCE_SCORE" \
            --timeout "$RELEVANCE_TIMEOUT" 2>/dev/null) || return 1

    # Check we got meaningful output
    [[ -z "$result" ]] && return 1
    [[ "$result" == *"No lessons found"* ]] && return 1
    [[ "$result" == *"error"* ]] && return 1

    echo "$result"
}

main() {
    is_enabled || exit 0

    # Parse input
    local input=$(cat)
    local prompt=$(echo "$input" | jq -r '.prompt // ""' 2>/dev/null || echo "")
    local cwd=$(echo "$input" | jq -r '.cwd // "."' 2>/dev/null || echo ".")
    local transcript_path=$(echo "$input" | jq -r '.transcript_path // ""' 2>/dev/null || echo "")

    # Skip if no prompt
    [[ -z "$prompt" ]] && exit 0

    # Skip short prompts (greetings, confirmations, etc.)
    [[ ${#prompt} -lt $MIN_PROMPT_LENGTH ]] && exit 0

    # Only run smart injection on first prompt to avoid latency
    is_first_prompt "$transcript_path" || exit 0

    # Skip if Python manager doesn't exist
    [[ ! -f "$PYTHON_MANAGER" ]] && exit 0

    # Score lessons against the prompt
    local scored_lessons
    scored_lessons=$(score_and_format_lessons "$prompt" "$cwd") || exit 0

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
