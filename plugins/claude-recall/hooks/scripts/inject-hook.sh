#!/bin/bash
# SPDX-License-Identifier: MIT
# Claude Recall SessionStart hook - injects lessons context

set -euo pipefail

# Source shared library
HOOK_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HOOK_LIB_DIR/hook-lib.sh"

# Check for recursion guard early
hook_lib_check_recursion

# Initialize timing immediately
init_timing

# Setup environment variables
setup_env

# Get decayIntervalDays from settings (default: 7)
DECAY_INTERVAL_DAYS=$(get_setting "decayIntervalDays" 7)
DECAY_INTERVAL=$((DECAY_INTERVAL_DAYS * 86400))  # Convert to seconds

# Get topLessonsToShow setting (default: 5)
get_top_lessons_count() {
    get_setting "topLessonsToShow" 5
}

# Run decay if it's been more than DECAY_INTERVAL since last run
run_decay_if_due() {
    local decay_state="$CLAUDE_RECALL_STATE/.decay-last-run"
    local now
    now=$(date +%s)
    local last_run=0

    # Read and validate decay state (must be numeric)
    if [[ -f "$decay_state" ]]; then
        last_run=$(head -1 "$decay_state" 2>/dev/null | tr -dc '0-9')
        [[ -z "$last_run" ]] && last_run=0
    fi

    if [[ $((now - last_run)) -gt $DECAY_INTERVAL ]]; then
        # Run decay in background so it doesn't slow down session start
        # Prefer Go, fall back to bash
        if [[ -n "$GO_RECALL" && -x "$GO_RECALL" ]]; then
            PROJECT_DIR="$cwd" "$GO_RECALL" decay >/dev/null 2>&1 &
        elif [[ -x "$BASH_MANAGER" ]]; then
            "$BASH_MANAGER" decay 30 >/dev/null 2>&1 &
        fi
    fi
}

# Generate combined context (lessons only)
# Uses Go binary, falls back to individual calls if unavailable
# Returns: sets LESSONS_SUMMARY_RAW variable
# Note: topLessonsToShow is configurable (default: 5), smart-inject-hook.sh adds query-relevant ones
generate_combined_context() {
    local cwd="$1"
    local top_n
    top_n=$(get_top_lessons_count)

    # Reset output variables
    LESSONS_SUMMARY_RAW=""

    # Try Go fast path first (recall-hook inject-combined)
    if [[ -n "$GO_RECALL_HOOK" && -x "$GO_RECALL_HOOK" ]]; then
        local combined_output
        combined_output=$(PROJECT_DIR="$cwd" "$GO_RECALL_HOOK" inject-combined "$top_n" 2>/dev/null)

        if [[ $? -eq 0 && -n "$combined_output" ]]; then
            LESSONS_SUMMARY_RAW=$(echo "$combined_output" | jq -r '.lessons // empty')
            return 0
        fi
    fi

    # Try Go CLI inject-combined
    if [[ -n "$GO_RECALL" && -x "$GO_RECALL" ]]; then
        local stderr_file
        stderr_file=$(mktemp 2>/dev/null || echo "/tmp/inject-hook-$$")

        local combined_output
        combined_output=$(PROJECT_DIR="$cwd" "$GO_RECALL" inject-combined "$top_n" 2>"$stderr_file")

        local exit_code=$?
        if [[ $exit_code -eq 0 && -n "$combined_output" ]]; then
            LESSONS_SUMMARY_RAW=$(echo "$combined_output" | jq -r '.lessons // empty')
            rm -f "$stderr_file" 2>/dev/null
            return 0
        fi

        # Log error if debug enabled
        if [[ "${CLAUDE_RECALL_DEBUG:-0}" -ge 1 ]]; then
            local error_msg
            error_msg=$(cat "$stderr_file" 2>/dev/null | head -c 500)
            PROJECT_DIR="$cwd" "$GO_RECALL" debug log-error \
                "inject_combined_failed" "exit=$exit_code: $error_msg" 2>/dev/null &
        fi
        rm -f "$stderr_file" 2>/dev/null
    fi

    # Fallback: individual calls if combined fails
    generate_context_fallback "$cwd" "$top_n"
}

# Fallback: individual Go/bash calls (used if inject-combined fails)
generate_context_fallback() {
    local cwd="$1"
    local top_n="$2"

    # Get lessons - prefer Go recall-hook, fall back to Go CLI, then bash
    if [[ -n "$GO_RECALL_HOOK" && -x "$GO_RECALL_HOOK" ]]; then
        LESSONS_SUMMARY_RAW=$(PROJECT_DIR="$cwd" "$GO_RECALL_HOOK" inject "$top_n" 2>/dev/null || true)
    fi
    if [[ -z "$LESSONS_SUMMARY_RAW" && -n "$GO_RECALL" && -x "$GO_RECALL" ]]; then
        LESSONS_SUMMARY_RAW=$(PROJECT_DIR="$cwd" "$GO_RECALL" inject "$top_n" 2>/dev/null || true)
    fi
    if [[ -z "$LESSONS_SUMMARY_RAW" && -x "$BASH_MANAGER" ]]; then
        LESSONS_SUMMARY_RAW=$(PROJECT_DIR="$cwd" CLAUDE_RECALL_DEBUG="${CLAUDE_RECALL_DEBUG:-}" "$BASH_MANAGER" inject "$top_n" 2>/dev/null || true)
    fi
}

main() {
    is_enabled || exit 0

    local input
    input=$(cat)
    local cwd
    cwd=$(echo "$input" | jq -r '.cwd // "."' 2>/dev/null || echo ".")

    # Extract session_id from Claude Code hook input for event correlation
    local claude_session_id
    claude_session_id=$(echo "$input" | jq -r '.session_id // ""' 2>/dev/null || echo "")
    if [[ -n "$claude_session_id" ]]; then
        export CLAUDE_RECALL_SESSION="$claude_session_id"
    fi

    # Clear session dedup state for fresh session
    _HOOK_SESSION_ID="$claude_session_id"
    clear_dedup

    # Generate lessons context in single call
    local phase_start
    phase_start=$(get_elapsed_ms)
    generate_combined_context "$cwd"
    log_phase "load_combined" "$phase_start" "inject"

    # Build combined summary
    local summary="$LESSONS_SUMMARY_RAW"

    # Generate user-visible feedback (stderr)
    local sys_count=0 proj_count=0
    if [[ "$summary" =~ LESSONS\ \(([0-9]+)S,\ ([0-9]+)L ]]; then
        sys_count="${BASH_REMATCH[1]}"
        proj_count="${BASH_REMATCH[2]}"
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

    if [[ -n "$summary" ]]; then
        # Add lesson duty reminder
        summary="$summary

LESSON DUTY: When user corrects you, something fails, or you discover a pattern:
  ASK: \"Should I record this as a lesson? [category]: title - content\"
  CITE: When applying a lesson, say \"Applying [L###]: ...\"
  BEFORE git/implementing: Check if high-star lessons apply
  AFTER mistakes: Cite the violated lesson, propose new if novel"

        # Calculate and log token budget breakdown
        # Token estimate: ~4 bytes per token for English text
        local lessons_tokens=0 duties_tokens=0 total_tokens=0
        if [[ -n "${summary%%$'\n'*}" ]]; then
            if [[ -n "$LESSONS_SUMMARY_RAW" ]]; then
                lessons_tokens=$(( ${#LESSONS_SUMMARY_RAW} / 4 ))
            fi
            local lessons_len=${#LESSONS_SUMMARY_RAW}
            duties_tokens=$(( (${#summary} - lessons_len) / 4 ))
            if [[ $duties_tokens -lt 0 ]]; then
                duties_tokens=0
            fi
            total_tokens=$(( ${#summary} / 4 ))
        fi

        # Log token budget to debug log (background, non-blocking)
        if [[ $total_tokens -gt 0 && -n "$GO_RECALL" && -x "$GO_RECALL" ]]; then
            PROJECT_DIR="$cwd" "$GO_RECALL" debug injection-budget \
                "$total_tokens" "$lessons_tokens" "0" "$duties_tokens" \
                >/dev/null 2>&1 &
        fi

        # Record injected lesson IDs for session dedup
        local injected_ids=$(echo "$summary" | grep -oE '\[[LS][0-9]{3}\]' | tr -d '[]' | sort -u)
        [[ -n "$injected_ids" ]] && record_injected $injected_ids

        local escaped
        escaped=$(printf '%s' "$summary" | jq -Rs .)
        cat << EOF
{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":$escaped}}
EOF
    fi

    # Check for health alerts if alerting is enabled (non-blocking, runs in background)
    # This uses the alerts module to detect issues like stale handoffs or latency spikes
    if [[ -n "$GO_RECALL" && -x "$GO_RECALL" ]]; then
        (
            PROJECT_DIR="$cwd" "$GO_RECALL" alerts send --bell 2>/dev/null || true
        ) &
    fi

    # Trigger decay check in background (runs weekly)
    run_decay_if_due

    # Log timing summary
    log_hook_end "inject"

    exit 0
}

main
