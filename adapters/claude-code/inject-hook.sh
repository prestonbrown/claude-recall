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
        # Try Python first, fall back to bash
        if [[ -f "$PYTHON_MANAGER" ]]; then
            PROJECT_DIR="$cwd" CLAUDE_RECALL_BASE="$CLAUDE_RECALL_BASE" CLAUDE_RECALL_STATE="$CLAUDE_RECALL_STATE" CLAUDE_RECALL_DEBUG="${CLAUDE_RECALL_DEBUG:-}" python3 "$PYTHON_MANAGER" decay 30 >/dev/null 2>&1 &
        elif [[ -x "$BASH_MANAGER" ]]; then
            "$BASH_MANAGER" decay 30 >/dev/null 2>&1 &
        fi
    fi
}

# Generate lessons context using Python manager (with bash fallback)
# Note: topLessonsToShow is configurable (default: 5), smart-inject-hook.sh adds query-relevant ones
generate_context() {
    local cwd="$1"
    local summary=""
    local top_n
    top_n=$(get_top_lessons_count)

    # Try Python manager first
    if [[ -f "$PYTHON_MANAGER" ]]; then
        local stderr_file
        stderr_file=$(mktemp 2>/dev/null || echo "/tmp/inject-hook-$$")

        summary=$(PROJECT_DIR="$cwd" CLAUDE_RECALL_BASE="$CLAUDE_RECALL_BASE" \
            CLAUDE_RECALL_STATE="$CLAUDE_RECALL_STATE" \
            CLAUDE_RECALL_DEBUG="${CLAUDE_RECALL_DEBUG:-}" \
            python3 "$PYTHON_MANAGER" inject "$top_n" 2>"$stderr_file")

        local exit_code=$?
        if [[ $exit_code -ne 0 ]]; then
            # Log error if debug enabled
            if [[ "${CLAUDE_RECALL_DEBUG:-0}" -ge 1 ]] && [[ -f "$PYTHON_MANAGER" ]]; then
                local error_msg
                error_msg=$(cat "$stderr_file" 2>/dev/null | head -c 500)
                PROJECT_DIR="$cwd" CLAUDE_RECALL_BASE="$CLAUDE_RECALL_BASE" \
                    CLAUDE_RECALL_STATE="$CLAUDE_RECALL_STATE" \
                    python3 "$PYTHON_MANAGER" debug log-error \
                    "inject_hook_failed" "exit=$exit_code: $error_msg" 2>/dev/null &
            fi
            summary=""  # Clear on failure
        fi
        rm -f "$stderr_file" 2>/dev/null
    fi

    # Fall back to bash manager if Python fails or returns empty
    if [[ -z "$summary" && -x "$BASH_MANAGER" ]]; then
        summary=$(PROJECT_DIR="$cwd" CLAUDE_RECALL_DEBUG="${CLAUDE_RECALL_DEBUG:-}" "$BASH_MANAGER" inject "$top_n" 2>/dev/null || true)
    fi

    echo "$summary"
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

    # Generate lessons context (with timing)
    local phase_start
    phase_start=$(get_elapsed_ms)
    local summary
    summary=$(generate_context "$cwd")
    # Store raw lessons content for token budget tracking
    local LESSONS_SUMMARY_RAW="$summary"
    log_phase "load_lessons" "$phase_start" "inject"

    # Also get active handoffs (project-level only)
    local handoffs=""
    local todo_continuation=""
    if [[ -f "$PYTHON_MANAGER" ]]; then
        phase_start=$(get_elapsed_ms)
        handoffs=$(PROJECT_DIR="$cwd" CLAUDE_RECALL_BASE="$CLAUDE_RECALL_BASE" CLAUDE_RECALL_STATE="$CLAUDE_RECALL_STATE" CLAUDE_RECALL_DEBUG="${CLAUDE_RECALL_DEBUG:-}" python3 "$PYTHON_MANAGER" handoff inject 2>/dev/null || true)
        log_phase "load_handoffs" "$phase_start" "inject"

        # Generate todo continuation prompt if there are active handoffs
        if [[ -n "$handoffs" && "$handoffs" != "(no active handoffs)" ]]; then
            # Extract the most recent handoff for todo format
            todo_continuation=$(PROJECT_DIR="$cwd" CLAUDE_RECALL_BASE="$CLAUDE_RECALL_BASE" CLAUDE_RECALL_STATE="$CLAUDE_RECALL_STATE" python3 "$PYTHON_MANAGER" handoff inject-todos 2>/dev/null || true)

            # Link session to continuation handoff so updates go to the right place
            if [[ -n "$todo_continuation" && -n "$claude_session_id" ]]; then
                priority_handoff_id=$(echo "$todo_continuation" | grep -oE 'hf-[0-9a-f]+' | head -1)
                if [[ -n "$priority_handoff_id" ]]; then
                    PROJECT_DIR="$cwd" CLAUDE_RECALL_BASE="$CLAUDE_RECALL_BASE" CLAUDE_RECALL_STATE="$CLAUDE_RECALL_STATE" \
                        python3 "$PYTHON_MANAGER" handoff set-session "$priority_handoff_id" "$claude_session_id" >/dev/null 2>&1 || true
                fi
            fi
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
            review_ids=$(echo "$handoffs" | grep -B2 "ready_for_review" | grep -oE '\[hf-[0-9a-f]+\]' | tr -d '[]' | tr '\n' ' ' | sed 's/ $//' || true)
        fi

        # Add lesson review duty if there are handoffs ready for review
        if [[ -n "$review_ids" ]]; then
            # Format each ID on its own line (stop-hook regex only matches ONE ID per line)
            local complete_cmds
            complete_cmds=$(echo "$review_ids" | tr ' ' '\n' | sed 's/^/      HANDOFF COMPLETE /')
            summary="$summary

LESSON REVIEW DUTY: Handoff(s) [$review_ids] completed all work.
  1. Review the tried steps above with the user
  2. ASK: \"Any lessons to extract from this work? Patterns, gotchas, or decisions worth recording?\"
  3. Record any lessons the user wants to keep
  4. Then output (one per line):
$complete_cmds"
        fi

        # Add lesson duty reminder
        summary="$summary

LESSON DUTY: When user corrects you, something fails, or you discover a pattern:
  ASK: \"Should I record this as a lesson? [category]: title - content\"
  CITE: When applying a lesson, say \"Applying [L###]: ...\"
  BEFORE git/implementing: Check if high-star lessons apply
  AFTER mistakes: Cite the violated lesson, propose new if novel

HANDOFF DUTY: For MAJOR work (3+ files, multi-step, integration), you MUST:
  1. Use TodoWrite to track progress - todos auto-sync to handoffs
  2. If working without TodoWrite, output: HANDOFF: title
  MAJOR = new feature, 4+ files, architectural, integration, refactoring
  MINOR = single-file fix, config, docs (no handoff needed)
  COMPLETION: When all todos done in this session:
    - If code changed, run /review
    - Commit your changes (auto-completes the handoff)
    - Or manually: HANDOFF COMPLETE <id>"

        # Add todo continuation if available
        if [[ -n "$todo_continuation" ]]; then
            summary="$summary

$todo_continuation"
        fi

        # Calculate and log token budget breakdown
        # Token estimate: ~4 bytes per token for English text
        local lessons_tokens=0 handoffs_tokens=0 duties_tokens=0 total_tokens=0
        if [[ -n "${summary%%$'\n'*}" ]]; then
            # Lessons come from generate_context which is before handoffs appended
            # We need to track the original summary length before handoffs
            # For simplicity, estimate from component sizes
            if [[ -n "$LESSONS_SUMMARY_RAW" ]]; then
                lessons_tokens=$(( ${#LESSONS_SUMMARY_RAW} / 4 ))
            fi
            if [[ -n "$handoffs" && "$handoffs" != "(no active handoffs)" ]]; then
                handoffs_tokens=$(( ${#handoffs} / 4 ))
            fi
            # Duties text is roughly 500-700 chars
            local lessons_len=${#LESSONS_SUMMARY_RAW}
            local handoffs_len=${#handoffs}
            duties_tokens=$(( (${#summary} - lessons_len - handoffs_len) / 4 ))
            if [[ $duties_tokens -lt 0 ]]; then
                duties_tokens=0
            fi
            total_tokens=$(( ${#summary} / 4 ))
        fi

        # Log token budget to debug log (background, non-blocking)
        if [[ -f "$PYTHON_MANAGER" && $total_tokens -gt 0 ]]; then
            PROJECT_DIR="$cwd" CLAUDE_RECALL_BASE="$CLAUDE_RECALL_BASE" \
                CLAUDE_RECALL_STATE="$CLAUDE_RECALL_STATE" \
                CLAUDE_RECALL_DEBUG="${CLAUDE_RECALL_DEBUG:-}" \
                python3 "$PYTHON_MANAGER" debug injection-budget \
                "$total_tokens" "$lessons_tokens" "$handoffs_tokens" "$duties_tokens" \
                >/dev/null 2>&1 &
        fi

        local escaped
        escaped=$(printf '%s' "$summary" | jq -Rs .)
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
    log_hook_end "inject"

    exit 0
}

main
