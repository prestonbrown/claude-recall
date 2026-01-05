#!/bin/bash
# SPDX-License-Identifier: MIT
# Claude Recall SessionStart hook - injects lessons context

set -euo pipefail

# Timing support - capture start time immediately
HOOK_START_MS=$(python3 -c 'import time; print(int(time.time() * 1000))' 2>/dev/null || echo 0)
PHASE_TIMES_JSON="{}"  # Build JSON incrementally (bash 3.x compatible)

# Guard against recursive calls from Haiku subprocesses
[[ -n "${LESSONS_SCORING_ACTIVE:-}" ]] && exit 0

# Support new (CLAUDE_RECALL_*), transitional (RECALL_*), and legacy (LESSONS_*) env vars
CLAUDE_RECALL_BASE="${CLAUDE_RECALL_BASE:-${RECALL_BASE:-${LESSONS_BASE:-$HOME/.config/claude-recall}}}"
CLAUDE_RECALL_STATE="${CLAUDE_RECALL_STATE:-${XDG_STATE_HOME:-$HOME/.local/state}/claude-recall}"
# Debug level: env var > settings.json > default (1)
_env_debug="${CLAUDE_RECALL_DEBUG:-${RECALL_DEBUG:-${LESSONS_DEBUG:-}}}"
if [[ -n "$_env_debug" ]]; then
    CLAUDE_RECALL_DEBUG="$_env_debug"
elif [[ -f "$HOME/.claude/settings.json" ]]; then
    _settings_debug=$(jq -r '.lessonsSystem.debugLevel // empty' "$HOME/.claude/settings.json" 2>/dev/null || true)
    CLAUDE_RECALL_DEBUG="${_settings_debug:-1}"
else
    CLAUDE_RECALL_DEBUG="1"
fi
# Export legacy names for downstream compatibility
LESSONS_BASE="$CLAUDE_RECALL_BASE"
LESSONS_DEBUG="$CLAUDE_RECALL_DEBUG"
export CLAUDE_RECALL_STATE
BASH_MANAGER="$CLAUDE_RECALL_BASE/lessons-manager.sh"
# Python manager - try installed location first, fall back to dev location
if [[ -f "$CLAUDE_RECALL_BASE/cli.py" ]]; then
    PYTHON_MANAGER="$CLAUDE_RECALL_BASE/cli.py"
else
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    PYTHON_MANAGER="$SCRIPT_DIR/../../core/cli.py"
fi
DECAY_INTERVAL=$((7 * 86400))  # 7 days in seconds

# Timing helpers (bash 3.x compatible - no associative arrays)
get_ms() {
    python3 -c 'import time; print(int(time.time() * 1000))' 2>/dev/null || echo 0
}

log_phase() {
    local phase="$1"
    local start_ms="$2"
    local end_ms=$(get_ms)
    local duration=$((end_ms - start_ms))
    # Append to JSON (handles first entry vs subsequent)
    if [[ "$PHASE_TIMES_JSON" == "{}" ]]; then
        PHASE_TIMES_JSON="{\"$phase\":$duration"
    else
        PHASE_TIMES_JSON="$PHASE_TIMES_JSON,\"$phase\":$duration"
    fi
    if [[ "${CLAUDE_RECALL_DEBUG:-0}" -ge 2 ]] && [[ -f "$PYTHON_MANAGER" ]]; then
        PROJECT_DIR="${cwd:-$(pwd)}" python3 "$PYTHON_MANAGER" debug hook-phase inject "$phase" "$duration" 2>/dev/null &
    fi
}

log_hook_end() {
    local end_ms=$(get_ms)
    local total_ms=$((end_ms - HOOK_START_MS))
    if [[ "${CLAUDE_RECALL_DEBUG:-0}" -ge 2 ]] && [[ -f "$PYTHON_MANAGER" ]]; then
        # Close the JSON object
        local phases_json="${PHASE_TIMES_JSON}}"
        PROJECT_DIR="${cwd:-$(pwd)}" python3 "$PYTHON_MANAGER" debug hook-end inject "$total_ms" --phases "$phases_json" 2>/dev/null &
    fi
}

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
    local decay_state="$CLAUDE_RECALL_STATE/.decay-last-run"
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
            PROJECT_DIR="$cwd" CLAUDE_RECALL_BASE="$CLAUDE_RECALL_BASE" CLAUDE_RECALL_STATE="$CLAUDE_RECALL_STATE" CLAUDE_RECALL_DEBUG="${CLAUDE_RECALL_DEBUG:-}" python3 "$PYTHON_MANAGER" decay 30 >/dev/null 2>&1 &
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
        summary=$(PROJECT_DIR="$cwd" CLAUDE_RECALL_BASE="$CLAUDE_RECALL_BASE" CLAUDE_RECALL_STATE="$CLAUDE_RECALL_STATE" CLAUDE_RECALL_DEBUG="${CLAUDE_RECALL_DEBUG:-}" python3 "$PYTHON_MANAGER" inject 3 2>/dev/null || true)
    fi

    # Fall back to bash manager if Python fails or returns empty
    if [[ -z "$summary" && -x "$BASH_MANAGER" ]]; then
        summary=$(PROJECT_DIR="$cwd" CLAUDE_RECALL_DEBUG="${CLAUDE_RECALL_DEBUG:-}" "$BASH_MANAGER" inject 3 2>/dev/null || true)
    fi

    echo "$summary"
}

main() {
    is_enabled || exit 0

    local input=$(cat)
    local cwd=$(echo "$input" | jq -r '.cwd // "."' 2>/dev/null || echo ".")

    # Generate lessons context (with timing)
    local phase_start=$(get_ms)
    local summary=$(generate_context "$cwd")
    log_phase "load_lessons" "$phase_start"

    # Also get active handoffs (project-level only)
    local handoffs=""
    local todo_continuation=""
    if [[ -f "$PYTHON_MANAGER" ]]; then
        phase_start=$(get_ms)
        handoffs=$(PROJECT_DIR="$cwd" CLAUDE_RECALL_BASE="$CLAUDE_RECALL_BASE" CLAUDE_RECALL_STATE="$CLAUDE_RECALL_STATE" CLAUDE_RECALL_DEBUG="${CLAUDE_RECALL_DEBUG:-}" python3 "$PYTHON_MANAGER" handoff inject 2>/dev/null || true)
        log_phase "load_handoffs" "$phase_start"

        # Generate todo continuation prompt if there are active handoffs
        if [[ -n "$handoffs" && "$handoffs" != "(no active handoffs)" ]]; then
            # Extract the most recent handoff for todo format
            todo_continuation=$(PROJECT_DIR="$cwd" CLAUDE_RECALL_BASE="$CLAUDE_RECALL_BASE" CLAUDE_RECALL_STATE="$CLAUDE_RECALL_STATE" python3 "$PYTHON_MANAGER" handoff inject-todos 2>/dev/null || true)
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

    # Check for session snapshot from previous session (saved by precompact hook when no handoff existed)
    local snapshot_file="$cwd/.claude-recall/.session-snapshot"
    if [[ -f "$snapshot_file" ]]; then
        local snapshot_content
        snapshot_content=$(cat "$snapshot_file")
        summary="$summary

## Previous Session (no handoff was active)
$snapshot_content
Consider creating a handoff if continuing this work."
        # Clean up snapshot after injecting
        rm -f "$snapshot_file"
        echo "[inject] Loaded session snapshot from previous session" >&2
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
        # Check for ready_for_review handoffs that need lesson extraction
        local review_ids=""
        if [[ -n "$handoffs" ]] && echo "$handoffs" | grep -q "ready_for_review"; then
            # Extract handoff IDs that have ready_for_review status
            review_ids=$(echo "$handoffs" | grep -B2 "ready_for_review" | grep -oE '\[hf-[0-9a-f]+\]' | tr -d '[]' | tr '\n' ' ' | sed 's/ $//')
        fi

        # Add lesson review duty if there are handoffs ready for review
        if [[ -n "$review_ids" ]]; then
            summary="$summary

LESSON REVIEW DUTY: Handoff(s) [$review_ids] completed all work.
  1. Review the tried steps above with the user
  2. ASK: \"Any lessons to extract from this work? Patterns, gotchas, or decisions worth recording?\"
  3. Record any lessons the user wants to keep
  4. Then output: HANDOFF COMPLETE $review_ids"
        fi

        # Add lesson duty reminder
        summary="$summary

LESSON DUTY: When user corrects you, something fails, or you discover a pattern:
  ASK: \"Should I record this as a lesson? [category]: title - content\"

HANDOFF DUTY: For MAJOR work (3+ files, multi-step, integration), you MUST:
  1. Use TodoWrite to track progress - todos auto-sync to handoffs
  2. If working without TodoWrite, output: HANDOFF: title
  MAJOR = new feature, 4+ files, architectural, integration, refactoring
  MINOR = single-file fix, config, docs (no handoff needed)"

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

    # Log timing summary
    log_hook_end

    exit 0
}

main
