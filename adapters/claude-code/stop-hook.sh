#!/bin/bash
# SPDX-License-Identifier: MIT
# Claude Recall Stop hook - tracks lesson citations from AI responses
#
# Uses timestamp-based checkpointing to process citations incrementally:
# - First run: process all entries, save latest timestamp
# - Subsequent runs: only process entries newer than checkpoint

set -uo pipefail

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
    _settings_debug=$(jq -r '.claudeRecall.debugLevel // empty' "$HOME/.claude/settings.json" 2>/dev/null || true)
    CLAUDE_RECALL_DEBUG="${_settings_debug:-1}"
else
    CLAUDE_RECALL_DEBUG="1"
fi
# Export for downstream Python manager
export CLAUDE_RECALL_STATE
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
STATE_DIR="$CLAUDE_RECALL_STATE/.citation-state"

# Global transcript cache (set by parse_transcript_once)
TRANSCRIPT_CACHE=""

# Parse transcript once and cache all needed data
# This replaces 12+ separate jq invocations with a single parse
parse_transcript_once() {
    local transcript_path="$1"
    local last_timestamp="$2"

    # Single jq call extracts everything we need
    # Output is a JSON object we can query cheaply with simple jq calls
    TRANSCRIPT_CACHE=$(jq -s --arg ts "$last_timestamp" '{
        # All assistant text content (joined for grep)
        assistant_texts: [.[] | select(.type == "assistant") |
            .message.content[]? | select(.type == "text") | .text],

        # Text from messages after timestamp (for incremental processing)
        assistant_texts_new: (if $ts == "" then [] else
            [.[] | select(.type == "assistant" and .timestamp > $ts) |
                .message.content[]? | select(.type == "text") | .text]
        end),

        # Last TodoWrite input (for sync) - from all messages
        last_todowrite: ([.[] | select(.type == "assistant") |
            .message.content[]? |
            select(.type == "tool_use" and .name == "TodoWrite") |
            .input.todos] | last // null),

        # Last TodoWrite input from NEW messages only
        last_todowrite_new: (if $ts == "" then null else
            ([.[] | select(.type == "assistant" and .timestamp > $ts) |
                .message.content[]? |
                select(.type == "tool_use" and .name == "TodoWrite") |
                .input.todos] | last // null)
        end),

        # Count unique files edited (for major work detection)
        edit_count: ([.[] | .message.content[]? |
            select(.type == "tool_use" and .name == "Edit") |
            .input.file_path] | unique | length),

        # Count TodoWrite calls (for major work detection)
        todowrite_count: ([.[] | .message.content[]? |
            select(.type == "tool_use" and .name == "TodoWrite")] | length),

        # Latest timestamp for checkpoint
        latest_timestamp: ([.[] | .timestamp // empty] | last // "")
    }' "$transcript_path" 2>/dev/null || echo "{}")
}

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
    if [[ "${CLAUDE_RECALL_DEBUG:-0}" -ge 1 ]] && [[ -f "$PYTHON_MANAGER" ]]; then
        PROJECT_DIR="${project_root:-$(pwd)}" python3 "$PYTHON_MANAGER" debug hook-phase stop "$phase" "$duration" 2>/dev/null &
    fi
}

log_hook_end() {
    local end_ms=$(get_ms)
    local total_ms=$((end_ms - HOOK_START_MS))
    if [[ "${CLAUDE_RECALL_DEBUG:-0}" -ge 1 ]] && [[ -f "$PYTHON_MANAGER" ]]; then
        # Close the JSON object
        local phases_json="${PHASE_TIMES_JSON}}"
        PROJECT_DIR="${project_root:-$(pwd)}" python3 "$PYTHON_MANAGER" debug hook-end stop "$total_ms" --phases "$phases_json" 2>/dev/null &
    fi
}

is_enabled() {
    local config="$HOME/.claude/settings.json"
    [[ -f "$config" ]] || return 0  # Enabled by default if no config
    # Note: jq // operator treats false as falsy, so we check explicitly
    local enabled=$(jq -r '.claudeRecall.enabled' "$config" 2>/dev/null)
    [[ "$enabled" != "false" ]]  # Enabled unless explicitly false
}

# Sanitize input for safe shell usage
# Removes control characters, limits length, escapes problematic patterns
sanitize_input() {
    local input="$1"
    local max_length="${2:-500}"

    # Remove control characters (keep printable ASCII and common unicode)
    input=$(printf '%s' "$input" | tr -cd '[:print:][:space:]' | tr -s ' ')

    # Truncate to max length
    input="${input:0:$max_length}"

    # Trim whitespace
    input=$(echo "$input" | xargs)

    printf '%s' "$input"
}

find_project_root() {
    local dir="${1:-$(pwd)}"
    while [[ "$dir" != "/" ]]; do
        [[ -d "$dir/.git" ]] && { echo "$dir"; return 0; }
        dir=$(dirname "$dir")
    done
    echo "$1"
}

# Infer blocked_by dependencies from natural language patterns in text.
# Patterns detected:
#   - "waiting for X" -> blocked_by X
#   - "blocked by Y" -> blocked_by Y
#   - "depends on Z" -> blocked_by Z
#   - "after A completes" -> blocked_by A
# Where X/Y/Z/A are handoff IDs (A### or hf-XXXXXXX format)
# Returns comma-separated list of blocker IDs, or empty if none found.
infer_blocked_by() {
    local text="$1"
    local blockers=""

    # Pattern: "waiting for <ID>"
    local waiting_matches
    waiting_matches=$(echo "$text" | grep -oE 'waiting for (hf-[0-9a-f]{7}|[A-Z][0-9]{3})' | \
        grep -oE '(hf-[0-9a-f]{7}|[A-Z][0-9]{3})' || true)
    [[ -n "$waiting_matches" ]] && blockers="$waiting_matches"

    # Pattern: "blocked by <ID>"
    local blocked_matches
    blocked_matches=$(echo "$text" | grep -oE 'blocked by (hf-[0-9a-f]{7}|[A-Z][0-9]{3})' | \
        grep -oE '(hf-[0-9a-f]{7}|[A-Z][0-9]{3})' || true)
    if [[ -n "$blocked_matches" ]]; then
        [[ -n "$blockers" ]] && blockers="$blockers"$'\n'"$blocked_matches" || blockers="$blocked_matches"
    fi

    # Pattern: "depends on <ID>"
    local depends_matches
    depends_matches=$(echo "$text" | grep -oE 'depends on (hf-[0-9a-f]{7}|[A-Z][0-9]{3})' | \
        grep -oE '(hf-[0-9a-f]{7}|[A-Z][0-9]{3})' || true)
    if [[ -n "$depends_matches" ]]; then
        [[ -n "$blockers" ]] && blockers="$blockers"$'\n'"$depends_matches" || blockers="$depends_matches"
    fi

    # Pattern: "after <ID> completes"
    local after_matches
    after_matches=$(echo "$text" | grep -oE 'after (hf-[0-9a-f]{7}|[A-Z][0-9]{3}) completes' | \
        grep -oE '(hf-[0-9a-f]{7}|[A-Z][0-9]{3})' || true)
    if [[ -n "$after_matches" ]]; then
        [[ -n "$blockers" ]] && blockers="$blockers"$'\n'"$after_matches" || blockers="$after_matches"
    fi

    # Deduplicate and format as comma-separated list
    if [[ -n "$blockers" ]]; then
        echo "$blockers" | sort -u | tr '\n' ',' | sed 's/,$//'
    fi
}

# Clean up orphaned checkpoint files (transcripts deleted but checkpoints remain)
# Runs opportunistically: max 10 files per invocation, only files >7 days old
cleanup_orphaned_checkpoints() {
    local max_age_days=7
    local max_cleanup=10
    local cleaned=0

    [[ -d "$STATE_DIR" ]] || return 0

    for state_file in "$STATE_DIR"/*; do
        [[ -f "$state_file" ]] || continue
        [[ $cleaned -ge $max_cleanup ]] && break

        local session_id=$(basename "$state_file")
        local found=false

        # Check if transcript exists in Claude's project directories
        if find ~/.claude/projects -name "${session_id}.jsonl" -type f 2>/dev/null | grep -q .; then
            found=true
        fi

        # If transcript not found and checkpoint is old enough, delete it
        if [[ "$found" == "false" ]]; then
            # Get file age in days (macOS: stat -f %m, Linux: stat -c %Y)
            local now=$(date +%s)
            local mtime=$(stat -f %m "$state_file" 2>/dev/null || stat -c %Y "$state_file" 2>/dev/null || echo "")

            # Safety: if stat failed or returned non-numeric, treat as new (don't delete)
            if [[ ! "$mtime" =~ ^[0-9]+$ ]]; then
                mtime=$now
            fi

            local file_age_days=$(( (now - mtime) / 86400 ))

            if [[ $file_age_days -gt $max_age_days ]]; then
                rm -f "$state_file"
                ((cleaned++)) || true
            fi
        fi
    done

    (( cleaned > 0 )) && echo "[lessons] Cleaned $cleaned orphaned checkpoint(s)" >&2
}

# Detect and process AI LESSON: patterns in assistant messages
# Format: AI LESSON: category: title - content
# Format with explicit type: AI LESSON [constraint]: category: title - content
# Types: constraint, informational, preference (auto-classified if not specified)
# Example: AI LESSON: correction: Always use absolute paths - Relative paths fail in shell hooks
# Example: AI LESSON [constraint]: gotcha: Never commit WIP - Uncommitted changes are sacred
process_ai_lessons() {
    local transcript_path="$1"
    local project_root="$2"
    local last_timestamp="$3"
    local added_count=0

    # Extract AI LESSON patterns from cached assistant texts
    # Use cached data - select appropriate field based on timestamp
    local texts_field="assistant_texts"
    [[ -n "$last_timestamp" ]] && texts_field="assistant_texts_new"
    local ai_lessons=""
    ai_lessons=$(echo "$TRANSCRIPT_CACHE" | jq -r --arg f "$texts_field" '.[$f][]' 2>/dev/null | \
        grep -oE 'AI LESSON:.*' || true)

    [[ -z "$ai_lessons" ]] && return 0

    while IFS= read -r lesson_line; do
        [[ -z "$lesson_line" ]] && continue

        # Parse: AI LESSON: category: title - content
        # Or:    AI LESSON [type]: category: title - content
        local explicit_type=""
        local remainder=""

        # Check for optional [type] bracket
        # Pattern: AI LESSON [type]: remainder
        local ai_lesson_typed_pattern='^AI LESSON \[([a-z]+)\]: ?(.*)$'
        if [[ "$lesson_line" =~ $ai_lesson_typed_pattern ]]; then
            explicit_type="${BASH_REMATCH[1]}"
            remainder="${BASH_REMATCH[2]}"
            # Validate type
            case "$explicit_type" in
                constraint|informational|preference) ;;
                *) explicit_type="" ;;  # Invalid type, ignore it
            esac
        else
            # Remove "AI LESSON: " prefix
            remainder="${lesson_line#AI LESSON: }"
            remainder="${remainder#AI LESSON:}"  # Also handle without space
        fi

        # Extract category (everything before first colon)
        local category="${remainder%%:*}"
        category=$(echo "$category" | tr '[:upper:]' '[:lower:]' | xargs)  # normalize

        # Extract title and content (everything after first colon)
        local title_content="${remainder#*:}"
        title_content=$(echo "$title_content" | xargs)  # trim whitespace

        # Split on " - " to get title and content
        local title="${title_content%% - *}"
        local content="${title_content#* - }"

        # If no " - " separator, use whole thing as title
        if [[ "$title" == "$title_content" ]]; then
            content=""
        fi

        # Validate we have at least a title
        [[ -z "$title" ]] && continue

        # Sanitize inputs to prevent injection
        title=$(sanitize_input "$title" 200)
        content=$(sanitize_input "$content" 1000)

        # Skip if title is empty after sanitization
        [[ -z "$title" ]] && continue

        # Default category if not recognized
        case "$category" in
            pattern|correction|decision|gotcha|preference) ;;
            *) category="pattern" ;;
        esac

        # Add the lesson using Python manager (with bash fallback)
        # Use -- to terminate options and prevent injection via crafted titles
        local result=""
        local type_args=""
        [[ -n "$explicit_type" ]] && type_args="--type $explicit_type"
        if [[ -f "$PYTHON_MANAGER" ]]; then
            result=$(PROJECT_DIR="$project_root" LESSONS_BASE="$LESSONS_BASE" LESSONS_DEBUG="${LESSONS_DEBUG:-}" \
                python3 "$PYTHON_MANAGER" add-ai $type_args -- "$category" "$title" "$content" 2>&1 || true)
        fi

        # Fall back to bash manager if Python fails
        if [[ -z "$result" && -x "$BASH_MANAGER" ]]; then
            # Bash manager doesn't support add-ai - log warning
            echo "[lessons] Warning: AI lesson skipped (Python unavailable, bash fallback not supported)" >&2
        fi

        if [[ -n "$result" && "$result" != Error:* ]]; then
            ((added_count++)) || true
        fi
    done <<< "$ai_lessons"

    (( added_count > 0 )) && echo "[lessons] $added_count AI lesson(s) added" >&2
}

# ============================================================
# HANDOFF PATTERN PROCESSING
# ============================================================
# Patterns processed (from transcript output):
#   HANDOFF: <title>              - Start tracking new handoff
#   HANDOFF UPDATE <id>: ...      - Update existing handoff
#   HANDOFF COMPLETE <id>         - Mark handoff complete
#
# ID can be hf-XXXXXXX (new format) or legacy A### format
# Full pattern variants:
#   HANDOFF: <title>                                     -> handoff add "<title>"
#   HANDOFF: <title> - <description>                     -> handoff add "<title>" --desc "<description>"
#   PLAN MODE: <title>                                   -> handoff add "<title>" --phase research --agent plan
#   HANDOFF UPDATE <id>|LAST: status <status>            -> handoff update ID --status <status>
#   HANDOFF UPDATE <id>|LAST: phase <phase>              -> handoff update ID --phase <phase>
#   HANDOFF UPDATE <id>|LAST: agent <agent>              -> handoff update ID --agent <agent>
#   HANDOFF UPDATE <id>|LAST: desc <text>                -> handoff update ID --desc "<text>"
#   HANDOFF UPDATE <id>|LAST: tried <outcome> - <desc>   -> handoff update ID --tried <outcome> "<desc>"
#   HANDOFF UPDATE <id>|LAST: next <text>                -> handoff update ID --next "<text>"
#   HANDOFF COMPLETE <id>|LAST                           -> handoff complete ID
process_handoffs() {
    local transcript_path="$1"
    local project_root="$2"
    local last_timestamp="$3"
    local session_id="$4"
    local processed_count=0
    local last_handoff_id=""  # Track last created handoff for LAST reference

    # Detect session origin to prevent sub-agents from creating handoffs
    # Sub-agents (Explore, Plan, General, System) can only UPDATE existing handoffs
    local session_origin="User"
    if [[ -n "$session_id" && -f "$PYTHON_MANAGER" ]]; then
        session_origin=$(PROJECT_DIR="$project_root" python3 "$PYTHON_MANAGER" session detect-origin "$session_id" 2>/dev/null || echo "User")
    fi
    local is_sub_agent=false
    if [[ "$session_origin" == "Explore" || "$session_origin" == "Plan" || "$session_origin" == "General" || "$session_origin" == "System" ]]; then
        is_sub_agent=true
    fi

    # Extract handoff patterns from cached assistant texts
    # Use cached data - select appropriate field based on timestamp
    local texts_field="assistant_texts"
    [[ -n "$last_timestamp" ]] && texts_field="assistant_texts_new"
    local pattern_lines=""
    pattern_lines=$(echo "$TRANSCRIPT_CACHE" | jq -r --arg f "$texts_field" '.[$f][]' 2>/dev/null | \
        grep -E '^(HANDOFF( UPDATE| COMPLETE)?|PLAN MODE):?' || true)

    [[ -z "$pattern_lines" ]] && return 0

    while IFS= read -r line; do
        [[ -z "$line" ]] && continue
        # H2: Skip overly long lines to prevent ReDoS in regex matching
        [[ ${#line} -gt 1000 ]] && continue
        local result=""

        # Pattern 1: HANDOFF: <title> [- <description>] -> add new handoff
        # Use -- to terminate options and prevent injection via crafted titles
        # NOTE: Sub-agents (Explore, Plan, General, System) are blocked from creating handoffs
        if [[ "$line" =~ ^HANDOFF:\ (.+)$ ]]; then
            # Block sub-agents from creating handoffs - they should only UPDATE
            if [[ "$is_sub_agent" == true ]]; then
                echo "[stop-hook] Blocked HANDOFF: from $session_origin sub-agent (use parent session)" >&2
                continue
            fi

            local full_match="${BASH_REMATCH[1]}"
            local title=""
            local desc=""

            # Check for " - " separator (description follows)
            if [[ "$full_match" =~ ^(.+)\ -\ (.+)$ ]]; then
                title="${BASH_REMATCH[1]}"
                desc="${BASH_REMATCH[2]}"
            else
                title="$full_match"
            fi

            title=$(sanitize_input "$title" 200)
            [[ -z "$title" ]] && continue
            desc=$(sanitize_input "$desc" 500)

            if [[ -f "$PYTHON_MANAGER" ]]; then
                if [[ -n "$desc" ]]; then
                    result=$(PROJECT_DIR="$project_root" LESSONS_BASE="$LESSONS_BASE" LESSONS_DEBUG="${LESSONS_DEBUG:-}" \
                        python3 "$PYTHON_MANAGER" approach add --desc "$desc" -- "$title" 2>&1 || true)
                else
                    result=$(PROJECT_DIR="$project_root" LESSONS_BASE="$LESSONS_BASE" LESSONS_DEBUG="${LESSONS_DEBUG:-}" \
                        python3 "$PYTHON_MANAGER" approach add -- "$title" 2>&1 || true)
                fi
                # Extract created ID for LAST reference (e.g., "Added handoff hf-a1b2c3d: ..." or "Added handoff A001: ...")
                if [[ "$result" =~ Added\ (approach|handoff)\ (hf-[0-9a-f]{7}|[A-Z][0-9]{3}) ]]; then
                    last_handoff_id="${BASH_REMATCH[2]}"
                fi
            fi

        # Pattern 1b: PLAN MODE: <title> -> add handoff with plan mode defaults
        # NOTE: Sub-agents are blocked from creating handoffs via PLAN MODE
        elif [[ "$line" =~ ^PLAN\ MODE:\ (.+)$ ]]; then
            # Block sub-agents from creating handoffs - they should only UPDATE
            if [[ "$is_sub_agent" == true ]]; then
                echo "[stop-hook] Blocked PLAN MODE: from $session_origin sub-agent (use parent session)" >&2
                continue
            fi

            local title="${BASH_REMATCH[1]}"
            title=$(sanitize_input "$title" 200)
            [[ -z "$title" ]] && continue

            if [[ -f "$PYTHON_MANAGER" ]]; then
                result=$(PROJECT_DIR="$project_root" LESSONS_BASE="$LESSONS_BASE" LESSONS_DEBUG="${LESSONS_DEBUG:-}" \
                    python3 "$PYTHON_MANAGER" approach add --phase research --agent plan -- "$title" 2>&1 || true)
                # Extract created ID for LAST reference
                if [[ "$result" =~ Added\ (approach|handoff)\ (hf-[0-9a-f]{7}|[A-Z][0-9]{3}) ]]; then
                    last_handoff_id="${BASH_REMATCH[2]}"
                fi
            fi

        # Pattern 2: HANDOFF UPDATE <id>|LAST: status <status>
        elif [[ "$line" =~ ^HANDOFF\ UPDATE\ (hf-[0-9a-f]{7}|[A-Z][0-9]{3}|LAST):\ status\ (.+)$ ]]; then
            local handoff_id="${BASH_REMATCH[1]}"
            [[ "$handoff_id" == "LAST" ]] && handoff_id="$last_handoff_id"
            [[ -z "$handoff_id" ]] && continue
            local status="${BASH_REMATCH[2]}"
            status=$(sanitize_input "$status" 20)

            if [[ -f "$PYTHON_MANAGER" ]]; then
                result=$(PROJECT_DIR="$project_root" LESSONS_BASE="$LESSONS_BASE" LESSONS_DEBUG="${LESSONS_DEBUG:-}" \
                    python3 "$PYTHON_MANAGER" approach update "$handoff_id" --status "$status" 2>&1 || true)
            fi

        # Pattern 2b: HANDOFF UPDATE <id>|LAST: phase <phase>
        elif [[ "$line" =~ ^HANDOFF\ UPDATE\ (hf-[0-9a-f]{7}|[A-Z][0-9]{3}|LAST):\ phase\ (.+)$ ]]; then
            local handoff_id="${BASH_REMATCH[1]}"
            [[ "$handoff_id" == "LAST" ]] && handoff_id="$last_handoff_id"
            [[ -z "$handoff_id" ]] && continue
            local phase="${BASH_REMATCH[2]}"
            phase=$(sanitize_input "$phase" 20)

            if [[ -f "$PYTHON_MANAGER" ]]; then
                result=$(PROJECT_DIR="$project_root" LESSONS_BASE="$LESSONS_BASE" LESSONS_DEBUG="${LESSONS_DEBUG:-}" \
                    python3 "$PYTHON_MANAGER" approach update "$handoff_id" --phase "$phase" 2>&1 || true)
            fi

        # Pattern 2c: HANDOFF UPDATE <id>|LAST: agent <agent>
        elif [[ "$line" =~ ^HANDOFF\ UPDATE\ (hf-[0-9a-f]{7}|[A-Z][0-9]{3}|LAST):\ agent\ (.+)$ ]]; then
            local handoff_id="${BASH_REMATCH[1]}"
            [[ "$handoff_id" == "LAST" ]] && handoff_id="$last_handoff_id"
            [[ -z "$handoff_id" ]] && continue
            local agent="${BASH_REMATCH[2]}"
            agent=$(sanitize_input "$agent" 30)

            if [[ -f "$PYTHON_MANAGER" ]]; then
                result=$(PROJECT_DIR="$project_root" LESSONS_BASE="$LESSONS_BASE" LESSONS_DEBUG="${LESSONS_DEBUG:-}" \
                    python3 "$PYTHON_MANAGER" approach update "$handoff_id" --agent "$agent" 2>&1 || true)
            fi

        # Pattern 2d: HANDOFF UPDATE <id>|LAST: desc <text>
        elif [[ "$line" =~ ^HANDOFF\ UPDATE\ (hf-[0-9a-f]{7}|[A-Z][0-9]{3}|LAST):\ desc\ (.+)$ ]]; then
            local handoff_id="${BASH_REMATCH[1]}"
            [[ "$handoff_id" == "LAST" ]] && handoff_id="$last_handoff_id"
            [[ -z "$handoff_id" ]] && continue
            local desc_text="${BASH_REMATCH[2]}"
            desc_text=$(sanitize_input "$desc_text" 500)

            if [[ -f "$PYTHON_MANAGER" ]]; then
                result=$(PROJECT_DIR="$project_root" LESSONS_BASE="$LESSONS_BASE" LESSONS_DEBUG="${LESSONS_DEBUG:-}" \
                    python3 "$PYTHON_MANAGER" approach update "$handoff_id" --desc "$desc_text" 2>&1 || true)
            fi

        # Pattern 3: HANDOFF UPDATE <id>|LAST: tried <outcome> - <description>
        elif [[ "$line" =~ ^HANDOFF\ UPDATE\ (hf-[0-9a-f]{7}|[A-Z][0-9]{3}|LAST):\ tried\ ([a-z]+)\ -\ (.+)$ ]]; then
            local handoff_id="${BASH_REMATCH[1]}"
            local outcome="${BASH_REMATCH[2]}"
            local description="${BASH_REMATCH[3]}"
            [[ "$handoff_id" == "LAST" ]] && handoff_id="$last_handoff_id"
            [[ -z "$handoff_id" ]] && continue
            # Validate outcome is one of the expected values
            [[ "$outcome" =~ ^(success|fail|partial)$ ]] || continue
            description=$(sanitize_input "$description" 500)

            if [[ -f "$PYTHON_MANAGER" ]]; then
                result=$(PROJECT_DIR="$project_root" LESSONS_BASE="$LESSONS_BASE" LESSONS_DEBUG="${LESSONS_DEBUG:-}" \
                    python3 "$PYTHON_MANAGER" approach update "$handoff_id" --tried "$outcome" "$description" 2>&1 || true)
            fi

        # Pattern 4: HANDOFF UPDATE <id>|LAST: next <text>
        elif [[ "$line" =~ ^HANDOFF\ UPDATE\ (hf-[0-9a-f]{7}|[A-Z][0-9]{3}|LAST):\ next\ (.+)$ ]]; then
            local handoff_id="${BASH_REMATCH[1]}"
            [[ "$handoff_id" == "LAST" ]] && handoff_id="$last_handoff_id"
            [[ -z "$handoff_id" ]] && continue
            local next_text="${BASH_REMATCH[2]}"
            next_text=$(sanitize_input "$next_text" 500)

            if [[ -f "$PYTHON_MANAGER" ]]; then
                result=$(PROJECT_DIR="$project_root" LESSONS_BASE="$LESSONS_BASE" LESSONS_DEBUG="${LESSONS_DEBUG:-}" \
                    python3 "$PYTHON_MANAGER" approach update "$handoff_id" --next -- "$next_text" 2>&1 || true)

                # Infer blocked_by from next_steps text patterns
                local inferred_blockers
                inferred_blockers=$(infer_blocked_by "$next_text")
                if [[ -n "$inferred_blockers" ]]; then
                    PROJECT_DIR="$project_root" LESSONS_BASE="$LESSONS_BASE" LESSONS_DEBUG="${LESSONS_DEBUG:-}" \
                        python3 "$PYTHON_MANAGER" approach update "$handoff_id" --blocked-by "$inferred_blockers" 2>&1 || true
                fi
            fi

        # Pattern 4b: HANDOFF UPDATE <id>|LAST: blocked_by <id>,<id>,...
        elif [[ "$line" =~ ^HANDOFF\ UPDATE\ (hf-[0-9a-f]{7}|[A-Z][0-9]{3}|LAST):\ blocked_by\ (.+)$ ]]; then
            local handoff_id="${BASH_REMATCH[1]}"
            [[ "$handoff_id" == "LAST" ]] && handoff_id="$last_handoff_id"
            [[ -z "$handoff_id" ]] && continue
            local blocked_ids="${BASH_REMATCH[2]}"
            blocked_ids=$(sanitize_input "$blocked_ids" 200)

            if [[ -f "$PYTHON_MANAGER" ]]; then
                result=$(PROJECT_DIR="$project_root" LESSONS_BASE="$LESSONS_BASE" LESSONS_DEBUG="${LESSONS_DEBUG:-}" \
                    python3 "$PYTHON_MANAGER" approach update "$handoff_id" --blocked-by "$blocked_ids" 2>&1 || true)
            fi

        # Pattern 5: HANDOFF COMPLETE <id>|LAST
        elif [[ "$line" =~ ^HANDOFF\ COMPLETE\ (hf-[0-9a-f]{7}|[A-Z][0-9]{3}|LAST)$ ]]; then
            local handoff_id="${BASH_REMATCH[1]}"
            [[ "$handoff_id" == "LAST" ]] && handoff_id="$last_handoff_id"
            [[ -z "$handoff_id" ]] && continue

            if [[ -f "$PYTHON_MANAGER" ]]; then
                result=$(PROJECT_DIR="$project_root" LESSONS_BASE="$LESSONS_BASE" LESSONS_DEBUG="${LESSONS_DEBUG:-}" \
                    python3 "$PYTHON_MANAGER" approach complete "$handoff_id" 2>&1 || true)
            fi
        fi

        # Count successful operations (non-empty result without Error:)
        if [[ -n "$result" && "$result" != Error:* ]]; then
            ((processed_count++)) || true
        fi
    done <<< "$pattern_lines"

    (( processed_count > 0 )) && echo "[handoffs] $processed_count handoff command(s) processed" >&2
}

# Capture TodoWrite tool calls and sync to handoffs
# This bridges ephemeral TodoWrite with persistent HANDOFFS.md
# - completed todos -> tried entries (success)
# - in_progress todo -> checkpoint
# - pending todos -> next_steps
capture_todowrite() {
    local transcript_path="$1"
    local project_root="$2"
    local last_timestamp="$3"

    # Get the LAST TodoWrite from cached data
    # Cache already has the final state, no need for tail -1
    local todos_field="last_todowrite"
    [[ -n "$last_timestamp" ]] && todos_field="last_todowrite_new"
    local todo_json=""
    todo_json=$(echo "$TRANSCRIPT_CACHE" | jq -c --arg f "$todos_field" '.[$f]' 2>/dev/null || true)

    # Skip if no TodoWrite calls or empty/null result
    [[ -z "$todo_json" || "$todo_json" == "null" ]] && return 0

    # Validate it's a JSON array
    if ! echo "$todo_json" | jq -e 'type == "array"' >/dev/null 2>&1; then
        return 0
    fi

    # Call Python manager to sync todos to handoff
    if [[ -f "$PYTHON_MANAGER" ]]; then
        local result
        result=$(PROJECT_DIR="$project_root" LESSONS_BASE="$LESSONS_BASE" LESSONS_DEBUG="${LESSONS_DEBUG:-}" \
            python3 "$PYTHON_MANAGER" approach sync-todos "$todo_json" 2>&1 || true)

        if [[ -n "$result" && "$result" != Error:* ]]; then
            echo "[handoffs] Synced TodoWrite to handoff" >&2
        fi
    fi
}

# Detect major work without handoff and warn
detect_and_warn_missing_handoff() {
    local transcript_path="$1"
    local project_root="$2"

    # Check if any handoff exists now (may have been created by capture_todowrite)
    local handoff_exists=""
    if [[ -f "$PYTHON_MANAGER" ]]; then
        handoff_exists=$(PROJECT_DIR="$project_root" LESSONS_BASE="$LESSONS_BASE" \
            python3 "$PYTHON_MANAGER" handoff list 2>/dev/null | grep -E '\[hf-' | head -1 || true)
    fi
    [[ -n "$handoff_exists" ]] && return 0

    # Use cached counts for major work detection
    local edit_count
    edit_count=$(echo "$TRANSCRIPT_CACHE" | jq -r '.edit_count // 0' 2>/dev/null || echo "0")

    local todo_count
    todo_count=$(echo "$TRANSCRIPT_CACHE" | jq -r '.todowrite_count // 0' 2>/dev/null || echo "0")

    # Warning threshold: 4+ file edits OR 3+ TodoWrite calls without handoff
    if [[ $edit_count -ge 4 || $todo_count -ge 3 ]]; then
        echo "[WARNING] Major work detected ($edit_count file edits, $todo_count TodoWrite calls) without handoff!" >&2
        echo "[WARNING] Consider using HANDOFF: title or TodoWrite for session continuity." >&2
    fi
}

main() {
    is_enabled || exit 0

    # Read input first (stdin must be consumed before other operations)
    local input=$(cat)

    # Extract session_id from Claude Code hook input for event correlation
    local claude_session_id=$(echo "$input" | jq -r '.session_id // ""' 2>/dev/null || echo "")
    if [[ -n "$claude_session_id" ]]; then
        export CLAUDE_RECALL_SESSION="$claude_session_id"
    fi

    # Opportunistic cleanup runs early (doesn't depend on current session)
    cleanup_orphaned_checkpoints

    local cwd=$(echo "$input" | jq -r '.cwd // "."' 2>/dev/null || echo ".")
    local project_root=$(find_project_root "$cwd")
    local transcript_path=$(echo "$input" | jq -r '.transcript_path // ""' 2>/dev/null || echo "")

    # Expand tilde
    transcript_path="${transcript_path/#\~/$HOME}"

    [[ -z "$transcript_path" || ! -f "$transcript_path" ]] && exit 0

    # Checkpoint state
    mkdir -p "$STATE_DIR"
    local session_id=$(basename "$transcript_path" .jsonl)
    local state_file="$STATE_DIR/$session_id"
    local last_timestamp=""
    [[ -f "$state_file" ]] && last_timestamp=$(cat "$state_file")

    # Parse transcript ONCE and cache all data (replaces 12+ jq calls)
    local phase_start=$(get_ms)
    parse_transcript_once "$transcript_path" "$last_timestamp"
    log_phase "parse_transcript" "$phase_start"

    # Process AI LESSON: patterns (adds new AI-generated lessons)
    phase_start=$(get_ms)
    process_ai_lessons "$transcript_path" "$project_root" "$last_timestamp"
    log_phase "process_lessons" "$phase_start"

    # Process HANDOFF/APPROACH: patterns (handoff tracking and plan mode)
    # Pass session_id so we can detect sub-agents and block handoff creation
    phase_start=$(get_ms)
    process_handoffs "$transcript_path" "$project_root" "$last_timestamp" "$claude_session_id"
    log_phase "process_handoffs" "$phase_start"

    # Capture TodoWrite tool calls and sync to handoffs
    phase_start=$(get_ms)
    capture_todowrite "$transcript_path" "$project_root" "$last_timestamp"
    log_phase "sync_todos" "$phase_start"

    # Warn if major work detected without handoff
    detect_and_warn_missing_handoff "$transcript_path" "$project_root"

    # Extract citations from cached assistant texts
    local texts_field="assistant_texts"
    [[ -n "$last_timestamp" ]] && texts_field="assistant_texts_new"
    local citations=""
    citations=$(echo "$TRANSCRIPT_CACHE" | jq -r --arg f "$texts_field" '.[$f][]' 2>/dev/null | \
        grep -oE '\[[LS][0-9]{3}\]' | sort -u || true)

    # Get latest timestamp from cache
    local latest_ts=$(echo "$TRANSCRIPT_CACHE" | jq -r '.latest_timestamp // ""' 2>/dev/null)

    # Update checkpoint even if no citations (to advance the checkpoint)
    if [[ -z "$citations" ]]; then
        [[ -n "$latest_ts" ]] && echo "$latest_ts" > "$state_file"
        exit 0
    fi

    # Filter out lesson listings (ID followed by star rating bracket)
    # Real citations: "[L010]:" or "[L010]," (no star bracket)
    # Listings: "[L010] [*****" (ID followed by star rating)
    # Use cached text (all assistant texts joined with newlines)
    local all_text=$(echo "$TRANSCRIPT_CACHE" | jq -r '.assistant_texts[]' 2>/dev/null || true)
    local filtered_citations=""
    while IFS= read -r cite; do
        [[ -z "$cite" ]] && continue
        # Check if this citation appears with a star bracket immediately after
        # Escape regex metacharacters in citation ID
        local escaped_cite=$(printf '%s' "$cite" | sed 's/[][\\.*^$()+?{|]/\\&/g')
        if ! echo "$all_text" | grep -qE "${escaped_cite} \\[\\*"; then
            filtered_citations+="$cite"$'\n'
        fi
    done <<< "$citations"
    citations=$(echo "$filtered_citations" | sort -u | grep -v '^$' || true)

    [[ -z "$citations" ]] && {
        [[ -n "$latest_ts" ]] && echo "$latest_ts" > "$state_file"
        log_hook_end
        exit 0
    }

    # Cite all lessons in a single batch call (much faster than per-lesson)
    phase_start=$(get_ms)
    local cited_count=0

    # Convert citations to space-separated IDs: [L001]\n[L002] -> L001 L002
    local lesson_ids=$(echo "$citations" | tr -d '[]' | tr '\n' ' ' | xargs)

    if [[ -n "$lesson_ids" && -f "$PYTHON_MANAGER" ]]; then
        # Single Python call with all IDs
        local result=$(PROJECT_DIR="$project_root" LESSONS_BASE="$LESSONS_BASE" LESSONS_DEBUG="${LESSONS_DEBUG:-}" \
            python3 "$PYTHON_MANAGER" cite $lesson_ids 2>&1 || true)
        # Count successful citations (each outputs OK: on its own line)
        cited_count=$(echo "$result" | grep -c "^OK:" || true)
    elif [[ -n "$lesson_ids" && -x "$BASH_MANAGER" ]]; then
        # Fall back to bash manager (still loops internally but less common)
        for lesson_id in $lesson_ids; do
            local result=$(PROJECT_DIR="$project_root" LESSONS_DEBUG="${LESSONS_DEBUG:-}" "$BASH_MANAGER" cite "$lesson_id" 2>&1 || true)
            [[ "$result" == OK:* ]] && ((cited_count++)) || true
        done
    fi
    log_phase "cite_lessons" "$phase_start"

    # Update checkpoint
    [[ -n "$latest_ts" ]] && echo "$latest_ts" > "$state_file"

    (( cited_count > 0 )) && echo "[lessons] $cited_count lesson(s) cited" >&2

    # Add transcript to linked handoff if session has one
    local session_id=$(echo "$input" | jq -r '.session_id // empty')
    if [[ -n "$session_id" && -n "$transcript_path" ]]; then
        PROJECT_DIR="$project_root" python3 "$PYTHON_MANAGER" \
            handoff add-transcript "$session_id" "$transcript_path" 2>/dev/null || true
    fi

    # Log timing summary
    log_hook_end
    exit 0
}

main
