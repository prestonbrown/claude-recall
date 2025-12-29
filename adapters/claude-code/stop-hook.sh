#!/bin/bash
# SPDX-License-Identifier: MIT
# Claude Code Stop hook - tracks lesson citations from AI responses
#
# Uses timestamp-based checkpointing to process citations incrementally:
# - First run: process all entries, save latest timestamp
# - Subsequent runs: only process entries newer than checkpoint

set -uo pipefail

LESSONS_BASE="${LESSONS_BASE:-$HOME/.config/coding-agent-lessons}"
BASH_MANAGER="$LESSONS_BASE/lessons-manager.sh"
# Python manager - try multiple locations
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_MANAGER="$SCRIPT_DIR/../../core/lessons_manager.py"
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
        local result=""
        if [[ -f "$PYTHON_MANAGER" ]]; then
            result=$(PROJECT_DIR="$project_root" LESSONS_BASE="$LESSONS_BASE" \
                python3 "$PYTHON_MANAGER" add-ai "$category" "$title" "$content" 2>&1 || true)
        fi

        # Fall back to bash manager if Python fails
        if [[ -z "$result" && -x "$BASH_MANAGER" ]]; then
            # Bash manager doesn't have add-ai, would need to be added
            # For now just skip bash fallback for AI lessons
            :
        fi

        if [[ -n "$result" && "$result" != Error:* ]]; then
            ((added_count++)) || true
        fi
    done <<< "$ai_lessons"

    (( added_count > 0 )) && echo "[lessons] $added_count AI lesson(s) added" >&2
}

# Detect and process APPROACH patterns in assistant messages
# Patterns:
#   APPROACH: <title>                                -> approach add "<title>"
#   APPROACH UPDATE A###: status <status>            -> approach update A### --status <status>
#   APPROACH UPDATE A###: tried <outcome> - <desc>   -> approach update A### --tried <outcome> "<desc>"
#   APPROACH UPDATE A###: next <text>                -> approach update A### --next "<text>"
#   APPROACH COMPLETE A###                           -> approach complete A###
process_approaches() {
    local transcript_path="$1"
    local project_root="$2"
    local last_timestamp="$3"
    local processed_count=0

    # Extract approach patterns from assistant messages
    local approach_lines=""
    if [[ -z "$last_timestamp" ]]; then
        approach_lines=$(jq -r 'select(.type == "assistant") |
            .message.content[]? | select(.type == "text") | .text' "$transcript_path" 2>/dev/null | \
            grep -E '^APPROACH( UPDATE| COMPLETE)?:?' || true)
    else
        approach_lines=$(jq -r --arg ts "$last_timestamp" '
            select(.type == "assistant" and .timestamp > $ts) |
            .message.content[]? | select(.type == "text") | .text' "$transcript_path" 2>/dev/null | \
            grep -E '^APPROACH( UPDATE| COMPLETE)?:?' || true)
    fi

    [[ -z "$approach_lines" ]] && return 0

    while IFS= read -r line; do
        [[ -z "$line" ]] && continue
        local result=""

        # Pattern 1: APPROACH: <title> -> add new approach
        if [[ "$line" =~ ^APPROACH:\ (.+)$ ]]; then
            local title="${BASH_REMATCH[1]}"
            title=$(sanitize_input "$title" 200)
            [[ -z "$title" ]] && continue

            if [[ -f "$PYTHON_MANAGER" ]]; then
                result=$(PROJECT_DIR="$project_root" LESSONS_BASE="$LESSONS_BASE" \
                    python3 "$PYTHON_MANAGER" approach add "$title" 2>&1 || true)
            fi

        # Pattern 2: APPROACH UPDATE A###: status <status>
        elif [[ "$line" =~ ^APPROACH\ UPDATE\ ([A-Z][0-9]{3}):\ status\ (.+)$ ]]; then
            local approach_id="${BASH_REMATCH[1]}"
            local status="${BASH_REMATCH[2]}"
            # Status is validated by Python, just basic sanitize
            status=$(sanitize_input "$status" 20)

            if [[ -f "$PYTHON_MANAGER" ]]; then
                result=$(PROJECT_DIR="$project_root" LESSONS_BASE="$LESSONS_BASE" \
                    python3 "$PYTHON_MANAGER" approach update "$approach_id" --status "$status" 2>&1 || true)
            fi

        # Pattern 3: APPROACH UPDATE A###: tried <outcome> - <description>
        elif [[ "$line" =~ ^APPROACH\ UPDATE\ ([A-Z][0-9]{3}):\ tried\ ([a-z]+)\ -\ (.+)$ ]]; then
            local approach_id="${BASH_REMATCH[1]}"
            local outcome="${BASH_REMATCH[2]}"
            local description="${BASH_REMATCH[3]}"
            description=$(sanitize_input "$description" 500)

            if [[ -f "$PYTHON_MANAGER" ]]; then
                result=$(PROJECT_DIR="$project_root" LESSONS_BASE="$LESSONS_BASE" \
                    python3 "$PYTHON_MANAGER" approach update "$approach_id" --tried "$outcome" "$description" 2>&1 || true)
            fi

        # Pattern 4: APPROACH UPDATE A###: next <text>
        elif [[ "$line" =~ ^APPROACH\ UPDATE\ ([A-Z][0-9]{3}):\ next\ (.+)$ ]]; then
            local approach_id="${BASH_REMATCH[1]}"
            local next_text="${BASH_REMATCH[2]}"
            next_text=$(sanitize_input "$next_text" 500)

            if [[ -f "$PYTHON_MANAGER" ]]; then
                result=$(PROJECT_DIR="$project_root" LESSONS_BASE="$LESSONS_BASE" \
                    python3 "$PYTHON_MANAGER" approach update "$approach_id" --next "$next_text" 2>&1 || true)
            fi

        # Pattern 5: APPROACH COMPLETE A###
        elif [[ "$line" =~ ^APPROACH\ COMPLETE\ ([A-Z][0-9]{3})$ ]]; then
            local approach_id="${BASH_REMATCH[1]}"

            if [[ -f "$PYTHON_MANAGER" ]]; then
                result=$(PROJECT_DIR="$project_root" LESSONS_BASE="$LESSONS_BASE" \
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

    # Process APPROACH: patterns (placeholder for Phase 2)
    process_approaches "$transcript_path" "$project_root" "$last_timestamp"

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
            result=$(PROJECT_DIR="$project_root" LESSONS_BASE="$LESSONS_BASE" python3 "$PYTHON_MANAGER" cite "$lesson_id" 2>&1 || true)
        fi

        # Fall back to bash manager if Python fails
        if [[ -z "$result" && -x "$BASH_MANAGER" ]]; then
            result=$(PROJECT_DIR="$project_root" "$BASH_MANAGER" cite "$lesson_id" 2>&1 || true)
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
