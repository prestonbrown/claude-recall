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
#   HANDOFF UPDATE <id>|LAST: checkpoint <text>          -> handoff update ID --checkpoint "<text>"
#   HANDOFF UPDATE <id>|LAST: blocked_by <id>,<id>       -> handoff update ID --blocked-by "<ids>"
#   HANDOFF COMPLETE <id>|LAST                           -> handoff complete ID
#
# This function uses a single Python call to parse all patterns and process them.
# All parsing, sanitization, and sub-agent detection happens in Python.
process_handoffs() {
    local transcript_path="$1"
    local project_root="$2"
    local last_timestamp="$3"
    local session_id="$4"
    local processed_count=0

    # Debug timing using get_elapsed_ms (no subprocess overhead)
    local t0 t1 t2 t3
    [[ "${CLAUDE_RECALL_DEBUG:-0}" -ge 2 ]] && t0=$(get_elapsed_ms)

    # Skip if no Python manager available
    [[ ! -f "$PYTHON_MANAGER" ]] && return 0

    # Skip if no transcript cache
    [[ -z "$TRANSCRIPT_CACHE" ]] && return 0

    # Build session-id argument if provided
    local session_arg=""
    [[ -n "$session_id" ]] && session_arg="--session-id $session_id"

    [[ "${CLAUDE_RECALL_DEBUG:-0}" -ge 2 ]] && t1=$(get_elapsed_ms)

    # Single Python call parses patterns, handles sub-agent blocking, and processes all operations
    local result
    result=$(echo "$TRANSCRIPT_CACHE" | PROJECT_DIR="$project_root" LESSONS_BASE="$LESSONS_BASE" LESSONS_DEBUG="${LESSONS_DEBUG:-}" \
        python3 "$PYTHON_MANAGER" handoff process-transcript $session_arg 2>&1 || true)

    [[ "${CLAUDE_RECALL_DEBUG:-0}" -ge 2 ]] && t2=$(get_elapsed_ms)

    # Count successful operations
    processed_count=$(echo "$result" | jq '[.results[]? | select(.ok == true)] | length' 2>/dev/null || echo 0)

    [[ "${CLAUDE_RECALL_DEBUG:-0}" -ge 2 ]] && {
        t3=$(get_elapsed_ms)
        echo "[timing:process_handoffs] setup=$((t1-t0))ms python=$((t2-t1))ms jq=$((t3-t2))ms" >&2
    }

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

    # Time the startup phase (stdin parsing, cleanup, etc.)
    local phase_start=$(get_elapsed_ms)

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
    log_phase "startup" "$phase_start" "stop"

    # Parse transcript ONCE and cache all data (replaces 12+ jq calls)
    # Uses byte-offset tracking to only parse new content since last run
    phase_start=$(get_elapsed_ms)
    parse_transcript_once "$transcript_path" "$last_timestamp" "$session_id"
    log_phase "parse_transcript" "$phase_start" "stop"

    # Process AI LESSON: patterns (adds new AI-generated lessons)
    phase_start=$(get_elapsed_ms)
    process_ai_lessons "$transcript_path" "$project_root" "$last_timestamp"
    log_phase "process_lessons" "$phase_start" "stop"

    # Extract citations from cache for batch processing
    phase_start=$(get_elapsed_ms)

    # Get filtered citations from cache (already excludes listings with star ratings)
    local citations_field="citations"
    [[ -n "$last_timestamp" ]] && citations_field="citations_new"
    local citations=""
    citations=$(echo "$TRANSCRIPT_CACHE" | jq -r --arg f "$citations_field" '.[$f][]' 2>/dev/null || true)

    # Get latest timestamp from cache
    local latest_ts=$(echo "$TRANSCRIPT_CACHE" | jq -r '.latest_timestamp // ""' 2>/dev/null)

    log_phase "extract_citations" "$phase_start" "stop"

    # Convert citations to comma-separated IDs for batch command: [L001]\n[L002] -> L001,L002
    local citation_ids=""
    if [[ -n "$citations" ]]; then
        citation_ids=$(echo "$citations" | tr -d '[]' | tr '\n' ',' | sed 's/,$//')
    fi

    # BATCH PROCESSING: Single Python call for handoffs, todos, citations, and transcript
    # This saves ~200-300ms by eliminating 3 Python startups (70-150ms each)
    phase_start=$(get_elapsed_ms)

    if [[ -f "$PYTHON_MANAGER" ]]; then
        local batch_args=""
        batch_args="--transcript $transcript_path"
        [[ -n "$citation_ids" ]] && batch_args="$batch_args --citations $citation_ids"
        [[ -n "$claude_session_id" ]] && batch_args="$batch_args --session-id $claude_session_id"

        local batch_result
        batch_result=$(PROJECT_DIR="$project_root" LESSONS_BASE="$LESSONS_BASE" LESSONS_DEBUG="${LESSONS_DEBUG:-}" \
            python3 "$PYTHON_MANAGER" stop-hook-batch $batch_args 2>&1 || echo '{}')

        # Parse batch results for logging
        local handoffs_processed=$(echo "$batch_result" | jq -r '.handoffs_processed // 0' 2>/dev/null || echo "0")
        local todos_synced=$(echo "$batch_result" | jq -r '.todos_synced // false' 2>/dev/null || echo "false")
        local cited_count=$(echo "$batch_result" | jq -r '.citations_count // 0' 2>/dev/null || echo "0")
        local transcript_added=$(echo "$batch_result" | jq -r '.transcript_added // false' 2>/dev/null || echo "false")

        # Log results
        (( handoffs_processed > 0 )) && echo "[handoffs] $handoffs_processed handoff command(s) processed" >&2
        [[ "$todos_synced" == "true" ]] && echo "[handoffs] Synced TodoWrite to handoff" >&2
        (( cited_count > 0 )) && echo "[lessons] $cited_count lesson(s) cited" >&2
    else
        # Fallback to individual calls if Python manager not available
        # Process handoffs
        process_handoffs "$transcript_path" "$project_root" "$last_timestamp" "$claude_session_id"

        # Capture TodoWrite
        capture_todowrite "$transcript_path" "$project_root" "$last_timestamp"

        # Cite lessons individually (bash fallback)
        if [[ -n "$citation_ids" && -x "$BASH_MANAGER" ]]; then
            local lesson_ids=$(echo "$citation_ids" | tr ',' ' ')
            local cited_count=0
            for lesson_id in $lesson_ids; do
                local result=$(PROJECT_DIR="$project_root" LESSONS_DEBUG="${LESSONS_DEBUG:-}" "$BASH_MANAGER" cite "$lesson_id" 2>&1 || true)
                [[ "$result" == OK:* ]] && ((cited_count++)) || true
            done
            (( cited_count > 0 )) && echo "[lessons] $cited_count lesson(s) cited" >&2
        fi
    fi

    log_phase "batch_process" "$phase_start" "stop"

    # Warn if major work detected without handoff
    detect_and_warn_missing_handoff "$transcript_path" "$project_root"

    # Update checkpoint
    [[ -n "$latest_ts" ]] && echo "$latest_ts" > "$state_file"

    # Log timing summary
    log_hook_end "stop"

    # Background pre-scoring cache warmup (runs 20% of sessions to avoid spamming Haiku)
    # This pre-scores user queries from the transcript to warm the relevance cache
    if (( RANDOM % 5 == 0 )) && [[ -n "$transcript_path" && -f "$transcript_path" ]]; then
        # Run in background with nohup so it doesn't block session end
        # Redirect to background.log for debugging
        nohup python3 "$PYTHON_MANAGER" prescore-cache \
            --transcript "$transcript_path" \
            >> "$CLAUDE_RECALL_STATE/background.log" 2>&1 &
    fi

    exit 0
}

main
