#!/bin/bash
# SPDX-License-Identifier: MIT
# Claude Code SessionStart hook - injects lessons context

set -euo pipefail

LESSONS_BASE="${LESSONS_BASE:-$HOME/.config/coding-agent-lessons}"
BASH_MANAGER="$LESSONS_BASE/lessons-manager.sh"
# Python manager - try multiple locations
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_MANAGER="$SCRIPT_DIR/../../core/lessons_manager.py"
DECAY_INTERVAL=$((7 * 86400))  # 7 days in seconds

# Check if enabled
is_enabled() {
    local config="$HOME/.claude/settings.json"
    [[ -f "$config" ]] && {
        local enabled=$(jq -r '.lessonsSystem.enabled // true' "$config" 2>/dev/null || echo "true")
        [[ "$enabled" == "true" ]]
    } || return 0
}

# Run decay if it's been more than DECAY_INTERVAL since last run
run_decay_if_due() {
    local decay_state="$LESSONS_BASE/.decay-last-run"
    local now=$(date +%s)
    local last_run=0

    # Read and validate decay state (must be numeric)
    if [[ -f "$decay_state" ]]; then
        last_run=$(head -1 "$decay_state" 2>/dev/null | tr -dc '0-9')
        [[ -z "$last_run" ]] && last_run=0
    fi

    if [[ $((now - last_run)) -gt $DECAY_INTERVAL ]]; then
        # Run decay in background so it doesn't slow down session start
        # Try Python first, fall back to bash
        if [[ -f "$PYTHON_MANAGER" ]]; then
            PROJECT_DIR="$cwd" LESSONS_BASE="$LESSONS_BASE" python3 "$PYTHON_MANAGER" decay 30 >/dev/null 2>&1 &
        elif [[ -x "$BASH_MANAGER" ]]; then
            "$BASH_MANAGER" decay 30 >/dev/null 2>&1 &
        fi
    fi
}

# Generate lessons context using Python manager (with bash fallback)
generate_context() {
    local cwd="$1"
    local summary=""

    # Try Python manager first
    if [[ -f "$PYTHON_MANAGER" ]]; then
        summary=$(PROJECT_DIR="$cwd" LESSONS_BASE="$LESSONS_BASE" python3 "$PYTHON_MANAGER" inject 5 2>/dev/null || true)
    fi

    # Fall back to bash manager if Python fails or returns empty
    if [[ -z "$summary" && -x "$BASH_MANAGER" ]]; then
        summary=$(PROJECT_DIR="$cwd" "$BASH_MANAGER" inject 5 2>/dev/null || true)
    fi

    echo "$summary"
}

main() {
    is_enabled || exit 0

    local input=$(cat)
    local cwd=$(echo "$input" | jq -r '.cwd // "."' 2>/dev/null || echo ".")

    # Generate lessons context
    local summary=$(generate_context "$cwd")

    # Also get active approaches (project-level only)
    local approaches=""
    if [[ -f "$PYTHON_MANAGER" ]]; then
        approaches=$(PROJECT_DIR="$cwd" LESSONS_BASE="$LESSONS_BASE" python3 "$PYTHON_MANAGER" approach inject 2>/dev/null || true)
    fi
    if [[ -n "$approaches" && "$approaches" != "(no active approaches)" ]]; then
        if [[ -n "$summary" ]]; then
            summary="$summary

$approaches"
        else
            summary="$approaches"
        fi
    fi

    if [[ -n "$summary" ]]; then
        # Add lesson and approach duty reminder
        summary="$summary

LESSON DUTY: When user corrects you, something fails, or you discover a pattern:
  ASK: \"Should I record this as a lesson? [category]: title - content\"

APPROACH TRACKING: For multi-step tasks, track progress with:
  APPROACH: <title>                              - Start tracking new approach
  PLAN MODE: <title>                             - Start approach for plan mode (phase=research, agent=plan)
  APPROACH UPDATE A###: status <status>          - Update status (in_progress|blocked)
  APPROACH UPDATE A###: phase <phase>            - Update phase (research|planning|implementing|review)
  APPROACH UPDATE A###: tried <outcome> - <desc> - Record what you tried (success|fail|partial)
  APPROACH UPDATE A###: next <text>              - Set next steps
  APPROACH COMPLETE A###                         - Mark complete and review for lessons"

        local escaped=$(printf '%s' "$summary" | jq -Rs .)
        cat << EOF
{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":$escaped}}
EOF
    fi

    # Trigger decay check in background (runs weekly)
    run_decay_if_due

    exit 0
}

main
