#!/bin/bash
# SPDX-License-Identifier: MIT
# Claude Recall Stop hook - tracks lesson citations from AI responses
#
# Uses timestamp-based checkpointing to process citations incrementally:
# - First run: process all entries, save latest timestamp
# - Subsequent runs: only process entries newer than checkpoint

set -uo pipefail

# Source shared library
HOOK_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HOOK_LIB_DIR/hook-lib.sh"

# Check for recursion guard early
hook_lib_check_recursion

# Initialize timing immediately
init_timing

# Setup environment variables
setup_env

# Hook-specific state directory
STATE_DIR="$CLAUDE_RECALL_STATE/.citation-state"

# Global transcript cache (set by parse_transcript_once)
TRANSCRIPT_CACHE=""

# Byte-offset tracking for incremental transcript parsing
OFFSET_FILE="$CLAUDE_RECALL_STATE/transcript_offsets.json"

# Go binaries are now set by hook-lib.sh via find_go_binary()
# GO_RECALL and GO_RECALL_HOOK are exported
# Legacy variable for backward compatibility
GO_HOOK_BINARY="${GO_RECALL_HOOK:-}"

# Process citations using Go binary (fast path)
# Returns 0 if successful, 1 if Go binary not available
# Sets GO_CITATIONS_PROCESSED to count of citations processed
GO_CITATIONS_PROCESSED=0
process_citations_go() {
    local cwd="$1"
    local session_id="$2"
    local transcript_path="$3"

    # Check if Go binary exists and is executable
    if [[ -z "$GO_HOOK_BINARY" || ! -x "$GO_HOOK_BINARY" ]]; then
        return 1
    fi

    # Build JSON input for Go hook
    local go_input
    go_input=$(jq -n \
        --arg cwd "$cwd" \
        --arg session_id "$session_id" \
        --arg transcript_path "$transcript_path" \
        '{cwd: $cwd, session_id: $session_id, transcript_path: $transcript_path}')

    # Call Go binary
    local go_result
    go_result=$(echo "$go_input" | "$GO_HOOK_BINARY" stop 2>/dev/null)

    if [[ $? -ne 0 || -z "$go_result" ]]; then
        return 1
    fi

    # Parse result
    GO_CITATIONS_PROCESSED=$(echo "$go_result" | jq -r '.citations_processed // 0' 2>/dev/null || echo "0")
    local citations_found=$(echo "$go_result" | jq -r '.citations | length // 0' 2>/dev/null || echo "0")

    # Log result
    (( GO_CITATIONS_PROCESSED > 0 )) && echo "[lessons] $GO_CITATIONS_PROCESSED lesson(s) cited (Go)" >&2

    return 0
}

get_transcript_offset() {
    local session_id="$1"
    [[ -f "$OFFSET_FILE" ]] || echo '{}' > "$OFFSET_FILE"
    local result
    result=$(jq -r --arg id "$session_id" '.[$id] // "0"' "$OFFSET_FILE" 2>/dev/null)
    if [[ $? -ne 0 || -z "$result" ]]; then
        # Corrupted offset file, reset it
        echo '{}' > "$OFFSET_FILE"
        echo "0"
    else
        echo "$result"
    fi
}

set_transcript_offset() {
    local session_id="$1" offset="$2"
    local tmp=$(mktemp "${OFFSET_FILE}.XXXXXX")
    if ! jq --arg id "$session_id" --arg off "$offset" \
            '.[$id] = ($off | tonumber)' "$OFFSET_FILE" > "$tmp" 2>/dev/null; then
        rm -f "$tmp"
        return 1
    fi
    mv "$tmp" "$OFFSET_FILE"
}

# Parse transcript once and cache all needed data
# This replaces 12+ separate jq invocations with a single parse
# Uses byte-offset tracking to only parse new content since last run
parse_transcript_once() {
    local transcript_path="$1"
    local last_timestamp="$2"
    local session_id="$3"

    # Get byte offset for this session (0 = first run, parse everything)
    local offset=0
    [[ -n "$session_id" ]] && offset=$(get_transcript_offset "$session_id")

    # Get current file size (macOS: stat -f%z, Linux: stat -c%s)
    local current_size
    current_size=$(stat -f%z "$transcript_path" 2>/dev/null || stat -c%s "$transcript_path" 2>/dev/null || echo "0")

    # Handle edge cases
    if [[ "$offset" -ge "$current_size" ]]; then
        # No new content - return empty cache
        TRANSCRIPT_CACHE='{"assistant_texts":[],"assistant_texts_new":[],"last_todowrite":null,"last_todowrite_new":null,"edit_count":0,"todowrite_count":0,"latest_timestamp":"","citations":[],"citations_new":[]}'
        return 0
    fi

    # Parse content: either full file (offset=0) or tail from offset
    # When using tail, skip partial first line with tail -n +2
    local jq_input
    if [[ "$offset" -eq 0 ]]; then
        # First run or reset: parse entire file
        jq_input=$(cat "$transcript_path")
    else
        # Incremental: parse only new content, skip partial first line
        jq_input=$(tail -c +$((offset + 1)) "$transcript_path" | tail -n +2)
    fi

    # Single jq call extracts everything we need
    # Output is a JSON object we can query cheaply with simple jq calls
    TRANSCRIPT_CACHE=$(echo "$jq_input" | jq -s --arg ts "$last_timestamp" '{
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
        latest_timestamp: ([.[] | .timestamp // empty] | last // ""),

        # Bash commands (for git commit detection in Python)
        bash_commands: [.[] | select(.type == "assistant") |
            .message.content[]? |
            select(.type == "tool_use" and .name == "Bash") |
            .input.command // ""],

        # Extract filtered citations (all assistant texts)
        # Finds [L###] or [S###] NOT followed by " [*" (star rating = listing, not citation)
        # Uses scan with capture group to check context after each citation
        citations: ([.[] | select(.type == "assistant") |
            .message.content[]? | select(.type == "text") | .text] | join("\n") |
            [scan("(\\[[LS][0-9]{3}\\])(.{0,3})")] |
            map(select(.[1] | test("^ \\[\\*") | not)) |
            map(.[0]) | unique | sort),

        # Extract filtered citations (new messages only, for incremental processing)
        citations_new: (if $ts == "" then [] else
            ([.[] | select(.type == "assistant" and .timestamp > $ts) |
                .message.content[]? | select(.type == "text") | .text] | join("\n") |
                [scan("(\\[[LS][0-9]{3}\\])(.{0,3})")] |
                map(select(.[1] | test("^ \\[\\*") | not)) |
                map(.[0]) | unique | sort)
        end)
    }' 2>/dev/null || echo "{}")

    # Update byte offset for next run (save current file size)
    [[ -n "$session_id" ]] && set_transcript_offset "$session_id" "$current_size"
}

# Clean up orphaned checkpoint files (transcripts deleted but checkpoints remain)
# Runs opportunistically: max 10 files per invocation, only files >7 days old
cleanup_orphaned_checkpoints() {
    local max_age_days=7
    local max_cleanup=10
    local cleaned=0

    [[ -d "$STATE_DIR" ]] || return 0

    # Only run cleanup 10% of the time to avoid performance impact
    # Each find command takes ~30-50ms with many sessions
    (( RANDOM % 10 != 0 )) && return 0

    # Build a list of existing sessions ONCE (much faster than per-file find)
    # PERF: Use sed to extract basename instead of xargs -n1 which spawns one process per file
    local existing_sessions
    existing_sessions=$(find ~/.claude/projects -name "*.jsonl" -type f 2>/dev/null | sed 's|.*/||; s/\.jsonl$//' | sort -u)

    for state_file in "$STATE_DIR"/*; do
        [[ -f "$state_file" ]] || continue
        [[ $cleaned -ge $max_cleanup ]] && break

        local session_id=$(basename "$state_file")
        local found=false

        # Check if session exists in our pre-built list (O(1) with grep -q)
        if echo "$existing_sessions" | grep -qx "$session_id"; then
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

# Detect and extract AI LESSON: patterns from assistant messages
# Returns JSON array of lessons for batch processing
# Format: AI LESSON: category: title - content
# Format with explicit type: AI LESSON [constraint]: category: title - content
# Types: constraint, informational, preference (auto-classified if not specified)
# Example: AI LESSON: correction: Always use absolute paths - Relative paths fail in shell hooks
# Example: AI LESSON [constraint]: gotcha: Never commit WIP - Uncommitted changes are sacred
extract_ai_lessons_json() {
    local last_timestamp="$1"

    # Extract AI LESSON patterns from cached assistant texts
    # Use cached data - select appropriate field based on timestamp
    local texts_field="assistant_texts"
    [[ -n "$last_timestamp" ]] && texts_field="assistant_texts_new"
    local ai_lessons=""
    # Pattern matches: "AI LESSON: ..." or "AI LESSON [type]: ..."
    ai_lessons=$(echo "$TRANSCRIPT_CACHE" | jq -r --arg f "$texts_field" '.[$f][]' 2>/dev/null | \
        grep -oE 'AI LESSON( \[[a-z]+\])?:.*' || true)

    [[ -z "$ai_lessons" ]] && { echo "[]"; return 0; }

    # Build JSON array of lessons
    local json_lessons="["
    local first=true

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

        # Add to JSON array (use jq for proper escaping)
        local lesson_json
        lesson_json=$(jq -n \
            --arg cat "$category" \
            --arg title "$title" \
            --arg content "$content" \
            --arg type "$explicit_type" \
            '{category: $cat, title: $title, content: $content, type: $type}')

        if [[ "$first" == "true" ]]; then
            json_lessons="$json_lessons$lesson_json"
            first=false
        else
            json_lessons="$json_lessons,$lesson_json"
        fi
    done <<< "$ai_lessons"

    json_lessons="$json_lessons]"
    echo "$json_lessons"
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
#   HANDOFF UPDATE <id>|LAST: checkpoint <text>          -> handoff update ID --checkpoint "<text>"
#   HANDOFF UPDATE <id>|LAST: blocked_by <id>,<id>       -> handoff update ID --blocked-by "<ids>"
#   HANDOFF COMPLETE <id>|LAST                           -> handoff complete ID
#
# This function uses a single Go call to parse all patterns and process them.
# All parsing, sanitization, and sub-agent detection happens in Go.
process_handoffs() {
    local transcript_path="$1"
    local project_root="$2"
    local last_timestamp="$3"
    local session_id="$4"
    local processed_count=0

    # Debug timing using get_elapsed_ms (no subprocess overhead)
    local t0 t1 t2 t3
    [[ "${CLAUDE_RECALL_DEBUG:-0}" -ge 2 ]] && t0=$(get_elapsed_ms)

    # Skip if no Go binary available
    [[ -z "$GO_RECALL" || ! -x "$GO_RECALL" ]] && return 0

    # Skip if no transcript cache
    [[ -z "$TRANSCRIPT_CACHE" ]] && return 0

    # Build session-id argument if provided
    local session_arg=""
    [[ -n "$session_id" ]] && session_arg="--session-id $session_id"

    [[ "${CLAUDE_RECALL_DEBUG:-0}" -ge 2 ]] && t1=$(get_elapsed_ms)

    # Single Go call parses patterns, handles sub-agent blocking, and processes all operations
    local result
    result=$(echo "$TRANSCRIPT_CACHE" | PROJECT_DIR="$project_root" LESSONS_BASE="$LESSONS_BASE" LESSONS_DEBUG="${LESSONS_DEBUG:-}" \
        "$GO_RECALL" handoff process-transcript $session_arg 2>&1 || true)

    [[ "${CLAUDE_RECALL_DEBUG:-0}" -ge 2 ]] && t2=$(get_elapsed_ms)

    # Count successful operations
    processed_count=$(echo "$result" | jq '[.results[]? | select(.ok == true)] | length' 2>/dev/null || echo 0)

    [[ "${CLAUDE_RECALL_DEBUG:-0}" -ge 2 ]] && {
        t3=$(get_elapsed_ms)
        echo "[timing:process_handoffs] setup=$((t1-t0))ms go=$((t2-t1))ms jq=$((t3-t2))ms" >&2
    }

    (( processed_count > 0 )) && echo "[handoffs] $processed_count handoff command(s) processed" >&2

    # Output lesson suggestions for any completed handoffs
    local suggestions
    suggestions=$(echo "$result" | jq -r '
        .results[]? |
        select(.ok == true and .suggested_lessons != null and (.suggested_lessons | length) > 0) |
        "LESSON SUGGESTION from handoff \(.id):",
        (.suggested_lessons[] | "  [\(.category)] \(.title) - \(.content)")
    ' 2>/dev/null || true)

    [[ -n "$suggestions" ]] && {
        echo "" >&2
        echo "============================================================" >&2
        echo "$suggestions" >&2
        echo "============================================================" >&2
        echo "To add a lesson: LESSON: category: title - content" >&2
    }
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

    # Call Go binary to sync todos to handoff
    if [[ -n "$GO_RECALL" && -x "$GO_RECALL" ]]; then
        local result
        result=$(PROJECT_DIR="$project_root" LESSONS_BASE="$LESSONS_BASE" LESSONS_DEBUG="${LESSONS_DEBUG:-}" \
            "$GO_RECALL" handoff sync-todos "$todo_json" 2>&1 || true)

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
    if [[ -n "$GO_RECALL" && -x "$GO_RECALL" ]]; then
        handoff_exists=$(PROJECT_DIR="$project_root" LESSONS_BASE="$LESSONS_BASE" \
            "$GO_RECALL" handoff list 2>/dev/null | grep -E '\[hf-' | head -1 || true)
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

    # FAST PATH: Single Go binary call replaces all bash/jq processing
    # Go handles: stdin parsing, transcript reading, citation extraction,
    # AI lesson extraction, checkpoint management
    if [[ -n "$GO_RECALL_HOOK" && -x "$GO_RECALL_HOOK" ]]; then
        "$GO_RECALL_HOOK" stop-all
        exit $?
    fi

    # Fallback if Go binary not available (shouldn't happen in normal installs)
    local input=$(cat)
    echo "[lessons] warning: Go binary not found, stop hook skipped" >&2
    exit 0
}

main
