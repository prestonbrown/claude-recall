#!/bin/bash
# SPDX-License-Identifier: MIT
# Claude Recall UserPromptSubmit hook - captures LESSON: commands

set -euo pipefail

# Guard against recursive calls from Haiku subprocesses
[[ -n "${LESSONS_SCORING_ACTIVE:-}" ]] && exit 0

# Support new (CLAUDE_RECALL_*), transitional (RECALL_*), and legacy (LESSONS_*) env vars
CLAUDE_RECALL_BASE="${CLAUDE_RECALL_BASE:-${RECALL_BASE:-${LESSONS_BASE:-$HOME/.config/claude-recall}}}"
CLAUDE_RECALL_DEBUG="${CLAUDE_RECALL_DEBUG:-${RECALL_DEBUG:-${LESSONS_DEBUG:-}}}"
# Export legacy names for downstream compatibility
LESSONS_BASE="$CLAUDE_RECALL_BASE"
LESSONS_DEBUG="$CLAUDE_RECALL_DEBUG"
BASH_MANAGER="$CLAUDE_RECALL_BASE/lessons-manager.sh"
# Python manager - try installed location first, fall back to dev location
if [[ -f "$CLAUDE_RECALL_BASE/cli.py" ]]; then
    PYTHON_MANAGER="$CLAUDE_RECALL_BASE/cli.py"
else
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    PYTHON_MANAGER="$SCRIPT_DIR/../../core/cli.py"
fi

is_enabled() {
    local config="$HOME/.claude/settings.json"
    [[ -f "$config" ]] && {
        local enabled=$(jq -r '.lessonsSystem.enabled // true' "$config" 2>/dev/null || echo "true")
        [[ "$enabled" == "true" ]]
    } || return 0
}

parse_lesson() {
    local prompt="$1" level="project" lesson_text="" promotable="yes"

    # Check for (no-promote) modifier
    if echo "$prompt" | grep -qi "(no-promote)"; then
        promotable="no"
        # Remove the modifier and collapse extra spaces
        prompt=$(echo "$prompt" | sed -E 's/[[:space:]]*\(no-promote\)[[:space:]]*/ /i' | sed -E 's/[[:space:]]+:/:/')
    fi

    if echo "$prompt" | grep -qi "^SYSTEM LESSON:"; then
        level="system"
        lesson_text=$(echo "$prompt" | sed -E 's/^SYSTEM LESSON:[[:space:]]*//i')
    elif echo "$prompt" | grep -qi "^LESSON:"; then
        lesson_text=$(echo "$prompt" | sed -E 's/^LESSON:[[:space:]]*//i')
    else
        return 1
    fi

    local category="correction"
    if [[ "$lesson_text" =~ ^([a-z]+):[[:space:]]*(.*)$ ]]; then
        category="${BASH_REMATCH[1]}"
        lesson_text="${BASH_REMATCH[2]}"
    fi

    local title="" content=""
    if [[ "$lesson_text" =~ ^([^-]+)[[:space:]]*-[[:space:]]*(.+)$ ]]; then
        title="${BASH_REMATCH[1]}"
        content="${BASH_REMATCH[2]}"
    else
        title="$lesson_text"
        content="$lesson_text"
    fi

    title=$(echo "$title" | sed -E 's/^[[:space:]]+|[[:space:]]+$//g')
    content=$(echo "$content" | sed -E 's/^[[:space:]]+|[[:space:]]+$//g')

    [[ -n "$title" && -n "$content" ]] && {
        echo "$level"
        echo "$category"
        echo "$title"
        echo "$content"
        echo "$promotable"
        return 0
    }
    return 1
}

main() {
    is_enabled || exit 0

    local input=$(cat)
    local prompt=$(echo "$input" | jq -r '.prompt // ""' 2>/dev/null || echo "")
    local cwd=$(echo "$input" | jq -r '.cwd // "."' 2>/dev/null || echo ".")

    [[ -z "$prompt" ]] && exit 0

    if parsed=$(parse_lesson "$prompt"); then
        local level=$(echo "$parsed" | sed -n '1p')
        local category=$(echo "$parsed" | sed -n '2p')
        local title=$(echo "$parsed" | sed -n '3p')
        local content=$(echo "$parsed" | sed -n '4p')
        local promotable=$(echo "$parsed" | sed -n '5p')

        local result=""
        local promo_note=""

        # Use Python manager (with fallback to bash)
        if [[ -f "$PYTHON_MANAGER" ]]; then
            local cmd="add"
            local args=()
            [[ "$level" == "system" ]] && args+=("--system")
            [[ "$promotable" == "no" ]] && { args+=("--no-promote"); promo_note=" (no-promote)"; }

            result=$(PROJECT_DIR="$cwd" LESSONS_BASE="$LESSONS_BASE" LESSONS_DEBUG="${LESSONS_DEBUG:-}" \
                python3 "$PYTHON_MANAGER" add ${args[@]+"${args[@]}"} -- "$category" "$title" "$content" 2>&1)
        elif [[ -x "$BASH_MANAGER" ]]; then
            local cmd="add"
            [[ "$level" == "system" ]] && cmd="add-system"
            result=$(PROJECT_DIR="$cwd" LESSONS_DEBUG="${LESSONS_DEBUG:-}" "$BASH_MANAGER" "$cmd" "$category" "$title" "$content" 2>&1)
        fi

        local lesson_id=$(echo "$result" | grep -oE '[LS][0-9]+' | head -1 || echo "")

        cat << EOF
{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":"LESSON RECORDED: [$lesson_id] [$title] added as $level lesson (category: $category)$promo_note. Cite using [$lesson_id] when applying."}}
EOF
    fi
    exit 0
}

main
