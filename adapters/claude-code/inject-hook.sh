#!/bin/bash
# SPDX-License-Identifier: MIT
# Claude Code SessionStart hook - injects lessons context

set -euo pipefail

LESSONS_BASE="${LESSONS_BASE:-$HOME/.config/coding-agent-lessons}"
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

    # Also get active approaches (project-level only)
    local approaches=""
    local todo_continuation=""
    if [[ -f "$PYTHON_MANAGER" ]]; then
        approaches=$(PROJECT_DIR="$cwd" LESSONS_BASE="$LESSONS_BASE" LESSONS_DEBUG="${LESSONS_DEBUG:-}" python3 "$PYTHON_MANAGER" approach inject 2>/dev/null || true)

        # Generate todo continuation prompt if there are active approaches
        if [[ -n "$approaches" && "$approaches" != "(no active approaches)" ]]; then
            # Extract the most recent approach for todo format
            todo_continuation=$(PROJECT_DIR="$cwd" LESSONS_BASE="$LESSONS_BASE" python3 "$PYTHON_MANAGER" approach inject-todos 2>/dev/null || true)
        fi
    fi
    if [[ -n "$approaches" && "$approaches" != "(no active approaches)" ]]; then
        if [[ -n "$summary" ]]; then
            summary="$summary

$approaches"
        else
            summary="$approaches"
        fi
    fi

    # Generate user-visible feedback (stderr)
    local sys_count=0 proj_count=0
    if [[ "$summary" =~ LESSONS\ \(([0-9]+)S,\ ([0-9]+)L ]]; then
        sys_count="${BASH_REMATCH[1]}"
        proj_count="${BASH_REMATCH[2]}"
    fi

    local approach_count=0
    if [[ -n "$approaches" && "$approaches" != "(no active approaches)" ]]; then
        approach_count=$(echo "$approaches" | grep -c "^### \[A" || true)
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
    if [[ $approach_count -gt 0 ]]; then
        if [[ -n "$feedback" ]]; then
            feedback="$feedback, $approach_count active approaches"
        else
            feedback="$approach_count active approaches"
        fi
    fi

    # Output to stderr if anything to report
    if [[ -n "$feedback" ]]; then
        echo "Injected: $feedback" >&2
    fi

    if [[ -n "$summary" ]]; then
        # Add lesson duty reminder
        summary="$summary

LESSON DUTY: When user corrects you, something fails, or you discover a pattern:
  ASK: \"Should I record this as a lesson? [category]: title - content\"

WORK TRACKING: Use TodoWrite for multi-step work - it auto-syncs to persistent approaches.
  Your todos are automatically saved to APPROACHES.md and restored next session."

        # Add todo continuation if available
        if [[ -n "$todo_continuation" ]]; then
            summary="$summary

$todo_continuation"
        fi

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
