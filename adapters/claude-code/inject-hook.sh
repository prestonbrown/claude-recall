#!/bin/bash
# SPDX-License-Identifier: MIT
# Claude Code SessionStart hook - injects lessons context

set -euo pipefail

# Support both new (RECALL_*) and old (LESSONS_*) env vars for backward compatibility
LESSONS_BASE="${RECALL_BASE:-${LESSONS_BASE:-$HOME/.config/coding-agent-lessons}}"
LESSONS_DEBUG="${RECALL_DEBUG:-${LESSONS_DEBUG:-}}"
BASH_MANAGER="$LESSONS_BASE/lessons-manager.sh"
# Python manager - try installed location first, fall back to dev location
if [[ -f "$LESSONS_BASE/cli.py" ]]; then
    PYTHON_MANAGER="$LESSONS_BASE/cli.py"
else
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    PYTHON_MANAGER="$SCRIPT_DIR/../../core/cli.py"
fi
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
            PROJECT_DIR="$cwd" LESSONS_BASE="$LESSONS_BASE" LESSONS_DEBUG="${LESSONS_DEBUG:-}" python3 "$PYTHON_MANAGER" decay 30 >/dev/null 2>&1 &
        elif [[ -x "$BASH_MANAGER" ]]; then
            "$BASH_MANAGER" decay 30 >/dev/null 2>&1 &
        fi
    fi
}

# Generate lessons context using Python manager (with bash fallback)
# Note: Reduced to 3 lessons since smart-inject-hook.sh adds query-relevant ones
generate_context() {
    local cwd="$1"
    local summary=""

    # Try Python manager first
    if [[ -f "$PYTHON_MANAGER" ]]; then
        summary=$(PROJECT_DIR="$cwd" LESSONS_BASE="$LESSONS_BASE" LESSONS_DEBUG="${LESSONS_DEBUG:-}" python3 "$PYTHON_MANAGER" inject 3 2>/dev/null || true)
    fi

    # Fall back to bash manager if Python fails or returns empty
    if [[ -z "$summary" && -x "$BASH_MANAGER" ]]; then
        summary=$(PROJECT_DIR="$cwd" LESSONS_DEBUG="${LESSONS_DEBUG:-}" "$BASH_MANAGER" inject 3 2>/dev/null || true)
    fi

    echo "$summary"
}

main() {
    is_enabled || exit 0

    local input=$(cat)
    local cwd=$(echo "$input" | jq -r '.cwd // "."' 2>/dev/null || echo ".")

    # Generate lessons context
    local summary=$(generate_context "$cwd")

    # Also get active handoffs (project-level only)
    local handoffs=""
    local todo_continuation=""
    if [[ -f "$PYTHON_MANAGER" ]]; then
        handoffs=$(PROJECT_DIR="$cwd" LESSONS_BASE="$LESSONS_BASE" LESSONS_DEBUG="${LESSONS_DEBUG:-}" python3 "$PYTHON_MANAGER" handoff inject 2>/dev/null || true)

        # Generate todo continuation prompt if there are active handoffs
        if [[ -n "$handoffs" && "$handoffs" != "(no active handoffs)" ]]; then
            # Extract the most recent handoff for todo format
            todo_continuation=$(PROJECT_DIR="$cwd" LESSONS_BASE="$LESSONS_BASE" python3 "$PYTHON_MANAGER" handoff inject-todos 2>/dev/null || true)
        fi
    fi
    if [[ -n "$handoffs" && "$handoffs" != "(no active handoffs)" ]]; then
        if [[ -n "$summary" ]]; then
            summary="$summary

$handoffs"
        else
            summary="$handoffs"
        fi
    fi

    # Generate user-visible feedback (stderr)
    local sys_count=0 proj_count=0
    if [[ "$summary" =~ LESSONS\ \(([0-9]+)S,\ ([0-9]+)L ]]; then
        sys_count="${BASH_REMATCH[1]}"
        proj_count="${BASH_REMATCH[2]}"
    fi

    local handoff_count=0
    if [[ -n "$handoffs" && "$handoffs" != "(no active handoffs)" ]]; then
        handoff_count=$(echo "$handoffs" | grep -cE "^### \[(hf-[0-9a-f]+|A[0-9]{3})\]" || true)
    fi

    # Build feedback message (only non-zero parts)
    local feedback=""
    if [[ $sys_count -gt 0 || $proj_count -gt 0 ]]; then
        local lessons_str=""
        if [[ $sys_count -gt 0 ]]; then
            lessons_str="${sys_count} system"
        fi
        if [[ $proj_count -gt 0 ]]; then
            if [[ -n "$lessons_str" ]]; then
                lessons_str="$lessons_str + ${proj_count} project"
            else
                lessons_str="${proj_count} project"
            fi
        fi
        feedback="$lessons_str lessons"
    fi
    if [[ $handoff_count -gt 0 ]]; then
        if [[ -n "$feedback" ]]; then
            feedback="$feedback, $handoff_count active handoffs"
        else
            feedback="$handoff_count active handoffs"
        fi
    fi

    if [[ -n "$summary" ]]; then
        # Add lesson duty reminder
        summary="$summary

LESSON DUTY: When user corrects you, something fails, or you discover a pattern:
  ASK: \"Should I record this as a lesson? [category]: title - content\"

WORK TRACKING: Use TodoWrite for multi-step work - it auto-syncs to persistent handoffs.
  Your todos are automatically saved to HANDOFFS.md and restored next session."

        # Add todo continuation if available
        if [[ -n "$todo_continuation" ]]; then
            summary="$summary

$todo_continuation"
        fi

        local escaped=$(printf '%s' "$summary" | jq -Rs .)
        # NOTE: $feedback contains user-visible summary like "4 system + 4 project lessons, 3 active handoffs"
        # Currently disabled - Claude Code doesn't surface systemMessage or stderr to users.
        # When/if Claude Code adds hook feedback display, uncomment:
        # cat << EOF
        # {"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":$escaped,"systemMessage":"Injected: $feedback"}}
        # EOF
        cat << EOF
{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":$escaped}}
EOF
    fi

    # Trigger decay check in background (runs weekly)
    run_decay_if_due

    exit 0
}

main
