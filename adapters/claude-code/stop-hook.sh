#!/bin/bash
# SPDX-License-Identifier: MIT
# Claude Code Stop hook - tracks lesson citations from AI responses
#
# Uses timestamp-based checkpointing to process citations incrementally:
# - First run: process all entries, save latest timestamp
# - Subsequent runs: only process entries newer than checkpoint

set -uo pipefail

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
STATE_DIR="$LESSONS_BASE/.citation-state"

is_enabled() {
    local config="$HOME/.claude/settings.json"
    [[ -f "$config" ]] && {
        local enabled=$(jq -r '.lessonsSystem.enabled // true' "$config" 2>/dev/null || echo "true")
        [[ "$enabled" == "true" ]]
    } || return 0
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
# Example: AI LESSON: correction: Always use absolute paths - Relative paths fail in shell hooks
process_ai_lessons() {
    local transcript_path="$1"
    local project_root="$2"
    local last_timestamp="$3"
    local added_count=0

    # Extract AI LESSON patterns from assistant messages
    local ai_lessons=""
    if [[ -z "$last_timestamp" ]]; then
        ai_lessons=$(jq -r 'select(.type == "assistant") |
            .message.content[]? | select(.type == "text") | .text' "$transcript_path" 2>/dev/null | \
            grep -oE 'AI LESSON:.*' || true)
    else
        ai_lessons=$(jq -r --arg ts "$last_timestamp" '
            select(.type == "assistant" and .timestamp > $ts) |
            .message.content[]? | select(.type == "text") | .text' "$transcript_path" 2>/dev/null | \
            grep -oE 'AI LESSON:.*' || true)
    fi

    [[ -z "$ai_lessons" ]] && return 0

    while IFS= read -r lesson_line; do
        [[ -z "$lesson_line" ]] && continue

        # Parse: AI LESSON: category: title - content
        # Remove "AI LESSON: " prefix
        local remainder="${lesson_line#AI LESSON: }"
        remainder="${remainder#AI LESSON:}"  # Also handle without space

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
        if [[ -f "$PYTHON_MANAGER" ]]; then
            result=$(PROJECT_DIR="$project_root" LESSONS_BASE="$LESSONS_BASE" LESSONS_DEBUG="${LESSONS_DEBUG:-}" \
                python3 "$PYTHON_MANAGER" add-ai -- "$category" "$title" "$content" 2>&1 || true)
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

# Detect and process APPROACH patterns in assistant messages
# ID can be explicit (A###) or LAST (most recently created in this processing run)
# Patterns:
#   APPROACH: <title>                                     -> approach add "<title>"
#   APPROACH: <title> - <description>                     -> approach add "<title>" --desc "<description>"
#   PLAN MODE: <title>                                    -> approach add "<title>" --phase research --agent plan
#   APPROACH UPDATE A###|LAST: status <status>            -> approach update ID --status <status>
#   APPROACH UPDATE A###|LAST: phase <phase>              -> approach update ID --phase <phase>
#   APPROACH UPDATE A###|LAST: agent <agent>              -> approach update ID --agent <agent>
#   APPROACH UPDATE A###|LAST: desc <text>                -> approach update ID --desc "<text>"
#   APPROACH UPDATE A###|LAST: tried <outcome> - <desc>   -> approach update ID --tried <outcome> "<desc>"
#   APPROACH UPDATE A###|LAST: next <text>                -> approach update ID --next "<text>"
#   APPROACH COMPLETE A###|LAST                           -> approach complete ID
process_approaches() {
    local transcript_path="$1"
    local project_root="$2"
    local last_timestamp="$3"
    local processed_count=0
    local last_approach_id=""  # Track last created approach for LAST reference

    # Extract approach patterns from assistant messages
    # Also match PLAN MODE: pattern for plan mode integration
    local approach_lines=""
    if [[ -z "$last_timestamp" ]]; then
        approach_lines=$(jq -r 'select(.type == "assistant") |
            .message.content[]? | select(.type == "text") | .text' "$transcript_path" 2>/dev/null | \
            grep -E '^(APPROACH( UPDATE| COMPLETE)?|PLAN MODE):?' || true)
    else
        approach_lines=$(jq -r --arg ts "$last_timestamp" '
            select(.type == "assistant" and .timestamp > $ts) |
            .message.content[]? | select(.type == "text") | .text' "$transcript_path" 2>/dev/null | \
            grep -E '^(APPROACH( UPDATE| COMPLETE)?|PLAN MODE):?' || true)
    fi

    [[ -z "$approach_lines" ]] && return 0

    while IFS= read -r line; do
        [[ -z "$line" ]] && continue
        # H2: Skip overly long lines to prevent ReDoS in regex matching
        [[ ${#line} -gt 1000 ]] && continue
        local result=""

        # Pattern 1: APPROACH: <title> [- <description>] -> add new approach
        # Use -- to terminate options and prevent injection via crafted titles
        if [[ "$line" =~ ^APPROACH:\ (.+)$ ]]; then
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
                # Extract created ID for LAST reference (e.g., "Added approach hf-a1b2c3d: ..." or "Added approach A001: ...")
                if [[ "$result" =~ Added\ approach\ (hf-[0-9a-f]{7}|[A-Z][0-9]{3}) ]]; then
                    last_approach_id="${BASH_REMATCH[1]}"
                fi
            fi

        # Pattern 1b: PLAN MODE: <title> -> add approach with plan mode defaults
        elif [[ "$line" =~ ^PLAN\ MODE:\ (.+)$ ]]; then
            local title="${BASH_REMATCH[1]}"
            title=$(sanitize_input "$title" 200)
            [[ -z "$title" ]] && continue

            if [[ -f "$PYTHON_MANAGER" ]]; then
                result=$(PROJECT_DIR="$project_root" LESSONS_BASE="$LESSONS_BASE" LESSONS_DEBUG="${LESSONS_DEBUG:-}" \
                    python3 "$PYTHON_MANAGER" approach add --phase research --agent plan -- "$title" 2>&1 || true)
                # Extract created ID for LAST reference
                if [[ "$result" =~ Added\ approach\ (hf-[0-9a-f]{7}|[A-Z][0-9]{3}) ]]; then
                    last_approach_id="${BASH_REMATCH[1]}"
                fi
            fi

        # Pattern 2: APPROACH UPDATE A###|hf-XXXXXXX|LAST: status <status>
        elif [[ "$line" =~ ^APPROACH\ UPDATE\ (hf-[0-9a-f]{7}|[A-Z][0-9]{3}|LAST):\ status\ (.+)$ ]]; then
            local approach_id="${BASH_REMATCH[1]}"
            [[ "$approach_id" == "LAST" ]] && approach_id="$last_approach_id"
            [[ -z "$approach_id" ]] && continue
            local status="${BASH_REMATCH[2]}"
            status=$(sanitize_input "$status" 20)

            if [[ -f "$PYTHON_MANAGER" ]]; then
                result=$(PROJECT_DIR="$project_root" LESSONS_BASE="$LESSONS_BASE" LESSONS_DEBUG="${LESSONS_DEBUG:-}" \
                    python3 "$PYTHON_MANAGER" approach update "$approach_id" --status "$status" 2>&1 || true)
            fi

        # Pattern 2b: APPROACH UPDATE A###|hf-XXXXXXX|LAST: phase <phase>
        elif [[ "$line" =~ ^APPROACH\ UPDATE\ (hf-[0-9a-f]{7}|[A-Z][0-9]{3}|LAST):\ phase\ (.+)$ ]]; then
            local approach_id="${BASH_REMATCH[1]}"
            [[ "$approach_id" == "LAST" ]] && approach_id="$last_approach_id"
            [[ -z "$approach_id" ]] && continue
            local phase="${BASH_REMATCH[2]}"
            phase=$(sanitize_input "$phase" 20)

            if [[ -f "$PYTHON_MANAGER" ]]; then
                result=$(PROJECT_DIR="$project_root" LESSONS_BASE="$LESSONS_BASE" LESSONS_DEBUG="${LESSONS_DEBUG:-}" \
                    python3 "$PYTHON_MANAGER" approach update "$approach_id" --phase "$phase" 2>&1 || true)
            fi

        # Pattern 2c: APPROACH UPDATE A###|hf-XXXXXXX|LAST: agent <agent>
        elif [[ "$line" =~ ^APPROACH\ UPDATE\ (hf-[0-9a-f]{7}|[A-Z][0-9]{3}|LAST):\ agent\ (.+)$ ]]; then
            local approach_id="${BASH_REMATCH[1]}"
            [[ "$approach_id" == "LAST" ]] && approach_id="$last_approach_id"
            [[ -z "$approach_id" ]] && continue
            local agent="${BASH_REMATCH[2]}"
            agent=$(sanitize_input "$agent" 30)

            if [[ -f "$PYTHON_MANAGER" ]]; then
                result=$(PROJECT_DIR="$project_root" LESSONS_BASE="$LESSONS_BASE" LESSONS_DEBUG="${LESSONS_DEBUG:-}" \
                    python3 "$PYTHON_MANAGER" approach update "$approach_id" --agent "$agent" 2>&1 || true)
            fi

        # Pattern 2d: APPROACH UPDATE A###|hf-XXXXXXX|LAST: desc <text>
        elif [[ "$line" =~ ^APPROACH\ UPDATE\ (hf-[0-9a-f]{7}|[A-Z][0-9]{3}|LAST):\ desc\ (.+)$ ]]; then
            local approach_id="${BASH_REMATCH[1]}"
            [[ "$approach_id" == "LAST" ]] && approach_id="$last_approach_id"
            [[ -z "$approach_id" ]] && continue
            local desc_text="${BASH_REMATCH[2]}"
            desc_text=$(sanitize_input "$desc_text" 500)

            if [[ -f "$PYTHON_MANAGER" ]]; then
                result=$(PROJECT_DIR="$project_root" LESSONS_BASE="$LESSONS_BASE" LESSONS_DEBUG="${LESSONS_DEBUG:-}" \
                    python3 "$PYTHON_MANAGER" approach update "$approach_id" --desc "$desc_text" 2>&1 || true)
            fi

        # Pattern 3: APPROACH UPDATE A###|hf-XXXXXXX|LAST: tried <outcome> - <description>
        elif [[ "$line" =~ ^APPROACH\ UPDATE\ (hf-[0-9a-f]{7}|[A-Z][0-9]{3}|LAST):\ tried\ ([a-z]+)\ -\ (.+)$ ]]; then
            local approach_id="${BASH_REMATCH[1]}"
            local outcome="${BASH_REMATCH[2]}"
            local description="${BASH_REMATCH[3]}"
            [[ "$approach_id" == "LAST" ]] && approach_id="$last_approach_id"
            [[ -z "$approach_id" ]] && continue
            # Validate outcome is one of the expected values
            [[ "$outcome" =~ ^(success|fail|partial)$ ]] || continue
            description=$(sanitize_input "$description" 500)

            if [[ -f "$PYTHON_MANAGER" ]]; then
                result=$(PROJECT_DIR="$project_root" LESSONS_BASE="$LESSONS_BASE" LESSONS_DEBUG="${LESSONS_DEBUG:-}" \
                    python3 "$PYTHON_MANAGER" approach update "$approach_id" --tried "$outcome" "$description" 2>&1 || true)
            fi

        # Pattern 4: APPROACH UPDATE A###|hf-XXXXXXX|LAST: next <text>
        elif [[ "$line" =~ ^APPROACH\ UPDATE\ (hf-[0-9a-f]{7}|[A-Z][0-9]{3}|LAST):\ next\ (.+)$ ]]; then
            local approach_id="${BASH_REMATCH[1]}"
            [[ "$approach_id" == "LAST" ]] && approach_id="$last_approach_id"
            [[ -z "$approach_id" ]] && continue
            local next_text="${BASH_REMATCH[2]}"
            next_text=$(sanitize_input "$next_text" 500)

            if [[ -f "$PYTHON_MANAGER" ]]; then
                result=$(PROJECT_DIR="$project_root" LESSONS_BASE="$LESSONS_BASE" LESSONS_DEBUG="${LESSONS_DEBUG:-}" \
                    python3 "$PYTHON_MANAGER" approach update "$approach_id" --next -- "$next_text" 2>&1 || true)

                # Infer blocked_by from next_steps text patterns
                local inferred_blockers
                inferred_blockers=$(infer_blocked_by "$next_text")
                if [[ -n "$inferred_blockers" ]]; then
                    PROJECT_DIR="$project_root" LESSONS_BASE="$LESSONS_BASE" LESSONS_DEBUG="${LESSONS_DEBUG:-}" \
                        python3 "$PYTHON_MANAGER" approach update "$approach_id" --blocked-by "$inferred_blockers" 2>&1 || true
                fi
            fi

        # Pattern 4b: APPROACH UPDATE A###|hf-XXXXXXX|LAST: blocked_by <id>,<id>,...
        elif [[ "$line" =~ ^APPROACH\ UPDATE\ (hf-[0-9a-f]{7}|[A-Z][0-9]{3}|LAST):\ blocked_by\ (.+)$ ]]; then
            local approach_id="${BASH_REMATCH[1]}"
            [[ "$approach_id" == "LAST" ]] && approach_id="$last_approach_id"
            [[ -z "$approach_id" ]] && continue
            local blocked_ids="${BASH_REMATCH[2]}"
            blocked_ids=$(sanitize_input "$blocked_ids" 200)

            if [[ -f "$PYTHON_MANAGER" ]]; then
                result=$(PROJECT_DIR="$project_root" LESSONS_BASE="$LESSONS_BASE" LESSONS_DEBUG="${LESSONS_DEBUG:-}" \
                    python3 "$PYTHON_MANAGER" approach update "$approach_id" --blocked-by "$blocked_ids" 2>&1 || true)
            fi

        # Pattern 5: APPROACH COMPLETE A###|hf-XXXXXXX|LAST
        elif [[ "$line" =~ ^APPROACH\ COMPLETE\ (hf-[0-9a-f]{7}|[A-Z][0-9]{3}|LAST)$ ]]; then
            local approach_id="${BASH_REMATCH[1]}"
            [[ "$approach_id" == "LAST" ]] && approach_id="$last_approach_id"
            [[ -z "$approach_id" ]] && continue

            if [[ -f "$PYTHON_MANAGER" ]]; then
                result=$(PROJECT_DIR="$project_root" LESSONS_BASE="$LESSONS_BASE" LESSONS_DEBUG="${LESSONS_DEBUG:-}" \
                    python3 "$PYTHON_MANAGER" approach complete "$approach_id" 2>&1 || true)
            fi
        fi

        # Count successful operations (non-empty result without Error:)
        if [[ -n "$result" && "$result" != Error:* ]]; then
            ((processed_count++)) || true
        fi
    done <<< "$approach_lines"

    (( processed_count > 0 )) && echo "[approaches] $processed_count approach command(s) processed" >&2
}

# Capture TodoWrite tool calls and sync to approaches
# This bridges ephemeral TodoWrite with persistent HANDOFFS.md
# - completed todos -> tried entries (success)
# - in_progress todo -> checkpoint
# - pending todos -> next_steps
capture_todowrite() {
    local transcript_path="$1"
    local project_root="$2"
    local last_timestamp="$3"

    # Extract the LAST TodoWrite tool_use block from assistant messages
    # We want the final state, not intermediate states
    # NOTE: Must use jq -c (compact) not -r (raw) because -r pretty-prints arrays
    # across multiple lines, and tail -1 would only get the closing "]"
    local todo_json=""
    if [[ -z "$last_timestamp" ]]; then
        todo_json=$(jq -c '
            select(.type == "assistant") |
            .message.content[]? |
            select(.type == "tool_use" and .name == "TodoWrite") |
            .input.todos' "$transcript_path" 2>/dev/null | tail -1 || true)
    else
        todo_json=$(jq -c --arg ts "$last_timestamp" '
            select(.type == "assistant" and .timestamp > $ts) |
            .message.content[]? |
            select(.type == "tool_use" and .name == "TodoWrite") |
            .input.todos' "$transcript_path" 2>/dev/null | tail -1 || true)
    fi

    # Skip if no TodoWrite calls or empty/null result
    [[ -z "$todo_json" || "$todo_json" == "null" ]] && return 0

    # Validate it's a JSON array
    if ! echo "$todo_json" | jq -e 'type == "array"' >/dev/null 2>&1; then
        return 0
    fi

    # Call Python manager to sync todos to approach
    if [[ -f "$PYTHON_MANAGER" ]]; then
        local result
        result=$(PROJECT_DIR="$project_root" LESSONS_BASE="$LESSONS_BASE" LESSONS_DEBUG="${LESSONS_DEBUG:-}" \
            python3 "$PYTHON_MANAGER" approach sync-todos "$todo_json" 2>&1 || true)

        if [[ -n "$result" && "$result" != Error:* ]]; then
            echo "[approaches] Synced TodoWrite to approach" >&2
        fi
    fi
}

main() {
    is_enabled || exit 0

    # Read input first (stdin must be consumed before other operations)
    local input=$(cat)

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

    # Process AI LESSON: patterns (adds new AI-generated lessons)
    process_ai_lessons "$transcript_path" "$project_root" "$last_timestamp"

    # Process APPROACH: patterns (approach tracking and plan mode)
    process_approaches "$transcript_path" "$project_root" "$last_timestamp"

    # Capture TodoWrite tool calls and sync to approaches
    capture_todowrite "$transcript_path" "$project_root" "$last_timestamp"

    # Process entries newer than checkpoint
    # Filter by timestamp, extract citations from assistant messages
    local citations=""
    if [[ -z "$last_timestamp" ]]; then
        # First run: process all assistant messages
        citations=$(jq -r 'select(.type == "assistant") |
            .message.content[]? | select(.type == "text") | .text' "$transcript_path" 2>/dev/null | \
            grep -oE '\[[LS][0-9]{3}\]' | sort -u || true)
    else
        # Incremental: only entries after checkpoint
        citations=$(jq -r --arg ts "$last_timestamp" '
            select(.type == "assistant" and .timestamp > $ts) |
            .message.content[]? | select(.type == "text") | .text' "$transcript_path" 2>/dev/null | \
            grep -oE '\[[LS][0-9]{3}\]' | sort -u || true)
    fi

    # Get latest timestamp for checkpoint update
    local latest_ts=$(jq -r '.timestamp // empty' "$transcript_path" 2>/dev/null | tail -1)

    # Update checkpoint even if no citations (to advance the checkpoint)
    if [[ -z "$citations" ]]; then
        [[ -n "$latest_ts" ]] && echo "$latest_ts" > "$state_file"
        exit 0
    fi

    # Filter out lesson listings (ID followed by star rating bracket)
    # Real citations: "[L010]:" or "[L010]," (no star bracket)
    # Listings: "[L010] [*****" (ID followed by star rating)
    # Cache all text to avoid running jq per-citation
    local all_text=$(jq -r '.message.content[]? | select(.type == "text") | .text' "$transcript_path" 2>/dev/null || true)
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
        exit 0
    }

    # Cite each lesson (Python first, bash fallback)
    local cited_count=0
    while IFS= read -r citation; do
        [[ -z "$citation" ]] && continue
        local lesson_id=$(echo "$citation" | tr -d '[]')
        local result=""

        # Try Python manager first
        if [[ -f "$PYTHON_MANAGER" ]]; then
            result=$(PROJECT_DIR="$project_root" LESSONS_BASE="$LESSONS_BASE" LESSONS_DEBUG="${LESSONS_DEBUG:-}" python3 "$PYTHON_MANAGER" cite "$lesson_id" 2>&1 || true)
        fi

        # Fall back to bash manager if Python fails
        if [[ -z "$result" && -x "$BASH_MANAGER" ]]; then
            result=$(PROJECT_DIR="$project_root" LESSONS_DEBUG="${LESSONS_DEBUG:-}" "$BASH_MANAGER" cite "$lesson_id" 2>&1 || true)
        fi

        if [[ "$result" == OK:* ]]; then
            ((cited_count++)) || true
        fi
    done <<< "$citations"

    # Update checkpoint
    [[ -n "$latest_ts" ]] && echo "$latest_ts" > "$state_file"

    (( cited_count > 0 )) && echo "[lessons] $cited_count lesson(s) cited" >&2
    exit 0
}

main
