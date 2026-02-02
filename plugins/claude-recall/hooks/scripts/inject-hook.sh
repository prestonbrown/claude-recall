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

# Generate combined context (lessons + handoffs + todos)
# Uses Go binary, falls back to individual calls if unavailable
# Returns: sets LESSONS_SUMMARY_RAW, HANDOFFS_SUMMARY, TODOS_PROMPT variables
# Note: topLessonsToShow is configurable (default: 5), smart-inject-hook.sh adds query-relevant ones
generate_combined_context() {
    local cwd="$1"
    local top_n
    top_n=$(get_top_lessons_count)

    # Reset output variables
    LESSONS_SUMMARY_RAW=""
    HANDOFFS_SUMMARY=""
    TODOS_PROMPT=""

    # Try Go fast path first (recall-hook inject-combined)
    if [[ -n "$GO_RECALL_HOOK" && -x "$GO_RECALL_HOOK" ]]; then
        local combined_output
        combined_output=$(PROJECT_DIR="$cwd" "$GO_RECALL_HOOK" inject-combined "$top_n" 2>/dev/null)

        if [[ $? -eq 0 && -n "$combined_output" ]]; then
            # Parse JSON output using jq
            LESSONS_SUMMARY_RAW=$(echo "$combined_output" | jq -r '.lessons // empty')
            HANDOFFS_SUMMARY=$(echo "$combined_output" | jq -r '.handoffs // empty')
            TODOS_PROMPT=$(echo "$combined_output" | jq -r '.todos // empty')
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
            # Parse JSON output using jq
            LESSONS_SUMMARY_RAW=$(echo "$combined_output" | jq -r '.lessons // empty')
            HANDOFFS_SUMMARY=$(echo "$combined_output" | jq -r '.handoffs // empty')
            TODOS_PROMPT=$(echo "$combined_output" | jq -r '.todos // empty')
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

    # Get handoffs - Go only
    if [[ -n "$GO_RECALL" && -x "$GO_RECALL" ]]; then
        HANDOFFS_SUMMARY=$(PROJECT_DIR="$cwd" "$GO_RECALL" handoff inject 2>/dev/null || true)
        if [[ "$HANDOFFS_SUMMARY" == "(no active handoffs)" ]]; then
            HANDOFFS_SUMMARY=""
        fi
    fi

    # Get todos if handoffs exist - Go only
    if [[ -n "$HANDOFFS_SUMMARY" ]]; then
        if [[ -n "$GO_RECALL" && -x "$GO_RECALL" ]]; then
            TODOS_PROMPT=$(PROJECT_DIR="$cwd" "$GO_RECALL" handoff inject-todos 2>/dev/null || true)
        fi
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

    # Generate combined context (lessons + handoffs + todos) in single call
    local phase_start
    phase_start=$(get_elapsed_ms)
    generate_combined_context "$cwd"
    log_phase "load_combined" "$phase_start" "inject"

    # Variables set by generate_combined_context:
    # - LESSONS_SUMMARY_RAW: formatted lessons
    # - HANDOFFS_SUMMARY: active handoffs
    # - TODOS_PROMPT: todo continuation prompt
    local handoffs="$HANDOFFS_SUMMARY"
    local todo_continuation="$TODOS_PROMPT"

    # NOTE: Session linking removed - now happens only when Claude explicitly
    # works on a handoff (via TodoWrite sync after user confirms continuation)

    # Build combined summary
    local summary="$LESSONS_SUMMARY_RAW"
    if [[ -n "$handoffs" ]]; then
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
    if [[ -n "$handoffs" ]]; then
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
    - ASK: \"Any lessons from this work?\" (context is fresh now!)
    - Commit your changes (git commit auto-completes the handoff)
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
        if [[ $total_tokens -gt 0 && -n "$GO_RECALL" && -x "$GO_RECALL" ]]; then
            PROJECT_DIR="$cwd" "$GO_RECALL" debug injection-budget \
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
