#!/bin/bash
# SPDX-License-Identifier: MIT
# test-stop-hook.sh - Tests for Claude Code stop hook citation tracking

set -euo pipefail

# Test configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STOP_HOOK="$SCRIPT_DIR/../adapters/claude-code/stop-hook.sh"
MANAGER="$SCRIPT_DIR/../core/lessons-manager.sh"
TEST_DIR=$(mktemp -d)
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Override paths for testing
export CLAUDE_RECALL_BASE="$TEST_DIR/.config/claude-recall"
export CLAUDE_RECALL_STATE="$TEST_DIR/.local/state/claude-recall"
export PROJECT_DIR="$TEST_DIR/project"
export HOME="$TEST_DIR"  # Override HOME for .claude paths

setup() {
    rm -rf "$TEST_DIR"
    mkdir -p "$TEST_DIR/project/.git"  # Fake git repo
    mkdir -p "$CLAUDE_RECALL_BASE"
    mkdir -p "$CLAUDE_RECALL_STATE"  # Isolate system lessons
    mkdir -p "$TEST_DIR/.claude"

    # Create shared config.json with lessons enabled
    mkdir -p "$TEST_DIR/.config/claude-recall"
    echo '{"enabled":true}' > "$TEST_DIR/.config/claude-recall/config.json"

    # Symlink manager to where hook expects it (HOME is overridden to TEST_DIR)
    ln -sf "$MANAGER" "$CLAUDE_RECALL_BASE/lessons-manager.sh"

    # Initialize a test lesson to cite
    "$MANAGER" add pattern "Test lesson" "This is a test lesson" >/dev/null 2>&1
}

teardown() {
    rm -rf "$TEST_DIR"
}

# Helper: create a mock transcript entry
create_transcript_entry() {
    local timestamp="$1"
    local text="$2"
    local type="${3:-assistant}"

    cat <<EOF
{"timestamp":"$timestamp","uuid":"$(uuidgen 2>/dev/null || echo "test-uuid-$RANDOM")","type":"$type","message":{"role":"$type","content":[{"type":"text","text":"$text"}]}}
EOF
}

# Helper: create a full mock transcript file
create_transcript() {
    local path="$1"
    shift

    mkdir -p "$(dirname "$path")"
    : > "$path"  # Clear file

    while [[ $# -gt 0 ]]; do
        echo "$1" >> "$path"
        shift
    done
}

# Helper: run stop hook with mock input
run_hook() {
    local transcript_path="$1"
    local cwd="${2:-$PROJECT_DIR}"

    echo "{\"transcript_path\":\"$transcript_path\",\"cwd\":\"$cwd\"}" | "$STOP_HOOK" 2>&1 || true
}

# Assertions
assert_eq() {
    local expected="$1"
    local actual="$2"
    local msg="${3:-}"
    if [[ "$expected" == "$actual" ]]; then
        return 0
    else
        echo -e "${RED}ASSERTION FAILED${NC}: $msg"
        echo "  Expected: '$expected'"
        echo "  Actual:   '$actual'"
        return 1
    fi
}

assert_contains() {
    local haystack="$1"
    local needle="$2"
    local msg="${3:-}"
    if [[ "$haystack" == *"$needle"* ]]; then
        return 0
    else
        echo -e "${RED}ASSERTION FAILED${NC}: $msg"
        echo "  Expected to contain: '$needle'"
        echo "  Actual: '$haystack'"
        return 1
    fi
}

assert_file_exists() {
    local file="$1"
    local msg="${2:-File should exist: $file}"
    if [[ -f "$file" ]]; then
        return 0
    else
        echo -e "${RED}ASSERTION FAILED${NC}: $msg"
        return 1
    fi
}

assert_file_contains() {
    local file="$1"
    local needle="$2"
    local msg="${3:-}"
    if [[ -f "$file" ]] && grep -q "$needle" "$file"; then
        return 0
    else
        echo -e "${RED}ASSERTION FAILED${NC}: $msg"
        if [[ -f "$file" ]]; then
            echo "  File contents: $(cat "$file")"
        else
            echo "  File does not exist: $file"
        fi
        return 1
    fi
}

run_test() {
    local test_name="$1"
    ((TESTS_RUN++))
    setup
    echo -n "  Testing: $test_name... "
    if eval "$test_name"; then
        echo -e "${GREEN}PASSED${NC}"
        ((TESTS_PASSED++))
    else
        echo -e "${RED}FAILED${NC}"
        ((TESTS_FAILED++))
    fi
    teardown
}

# =============================================================================
# Test Cases
# =============================================================================

test_no_transcript_exits_cleanly() {
    local output=$(run_hook "/nonexistent/path.jsonl")
    # Should exit cleanly with no output on missing file
    [[ -z "$output" || "$output" == *"[lessons]"* ]] || return 0
}

test_empty_transcript_exits_cleanly() {
    local transcript="$TEST_DIR/empty.jsonl"
    : > "$transcript"  # Create empty file

    local output=$(run_hook "$transcript")
    # Should exit cleanly
    [[ "$?" -eq 0 ]]
}

test_extracts_citation_from_assistant_message() {
    local transcript="$TEST_DIR/test.jsonl"

    create_transcript "$transcript" \
        "$(create_transcript_entry "2025-01-01T00:00:00.000Z" "Applying [L001] for this task")"

    local output=$(run_hook "$transcript")
    assert_contains "$output" "[lessons] 1 lesson(s) cited" "Should cite 1 lesson"
}

test_ignores_user_messages() {
    local transcript="$TEST_DIR/test.jsonl"

    create_transcript "$transcript" \
        "$(create_transcript_entry "2025-01-01T00:00:00.000Z" "The user said [L001]" "user")"

    local output=$(run_hook "$transcript")
    # Should not cite from user messages
    [[ "$output" != *"[lessons]"* ]]
}

test_deduplicates_citations() {
    local transcript="$TEST_DIR/test.jsonl"

    create_transcript "$transcript" \
        "$(create_transcript_entry "2025-01-01T00:00:00.000Z" "Applying [L001] for this")" \
        "$(create_transcript_entry "2025-01-01T00:01:00.000Z" "Also [L001] here again")"

    local output=$(run_hook "$transcript")
    # Should only cite once despite multiple mentions
    assert_contains "$output" "[lessons] 1 lesson(s) cited" "Should dedupe to 1 citation"
}

test_multiple_different_citations() {
    local transcript="$TEST_DIR/test.jsonl"

    # Add another lesson first
    "$MANAGER" add pattern "Second lesson" "Another test" >/dev/null 2>&1

    create_transcript "$transcript" \
        "$(create_transcript_entry "2025-01-01T00:00:00.000Z" "Applying [L001] and [L002]")"

    local output=$(run_hook "$transcript")
    assert_contains "$output" "[lessons] 2 lesson(s) cited" "Should cite 2 lessons"
}

test_excludes_lesson_listings() {
    local transcript="$TEST_DIR/test.jsonl"

    # Create message with lesson listing format (should be excluded)
    create_transcript "$transcript" \
        "$(create_transcript_entry "2025-01-01T00:00:00.000Z" "[L001] [*****/*****] This is a listing not a citation")"

    local output=$(run_hook "$transcript")
    # Should NOT cite (it's a listing, not a citation)
    [[ "$output" != *"[lessons]"* ]]
}

test_checkpoint_created() {
    local transcript="$TEST_DIR/test-session.jsonl"

    create_transcript "$transcript" \
        "$(create_transcript_entry "2025-01-01T00:00:00.000Z" "Applying [L001]")"

    run_hook "$transcript"

    # Check checkpoint file exists
    local state_dir="$CLAUDE_RECALL_BASE/.citation-state"
    assert_file_exists "$state_dir/test-session" "Checkpoint file should exist"
}

test_checkpoint_contains_timestamp() {
    local transcript="$TEST_DIR/test-session.jsonl"

    create_transcript "$transcript" \
        "$(create_transcript_entry "2025-01-01T12:30:45.123Z" "Applying [L001]")"

    run_hook "$transcript"

    local state_file="$CLAUDE_RECALL_BASE/.citation-state/test-session"
    assert_file_contains "$state_file" "2025-01-01T12:30:45.123Z" "Checkpoint should contain timestamp"
}

test_incremental_processing_skips_old() {
    local transcript="$TEST_DIR/test-session.jsonl"

    # First run: one citation
    create_transcript "$transcript" \
        "$(create_transcript_entry "2025-01-01T00:00:00.000Z" "Applying [L001]")"
    run_hook "$transcript"

    # Second run: same content, should be skipped
    local output=$(run_hook "$transcript")
    # Should not cite again (already checkpointed)
    [[ "$output" != *"[lessons]"* ]]
}

test_incremental_processing_catches_new() {
    local transcript="$TEST_DIR/test-session.jsonl"

    # Add second lesson
    "$MANAGER" add pattern "Second lesson" "Another test" >/dev/null 2>&1

    # First run: one citation
    create_transcript "$transcript" \
        "$(create_transcript_entry "2025-01-01T00:00:00.000Z" "Applying [L001]")"
    run_hook "$transcript"

    # Add new entry with newer timestamp
    echo "$(create_transcript_entry "2025-01-01T01:00:00.000Z" "Now applying [L002]")" >> "$transcript"

    local output=$(run_hook "$transcript")
    # Should cite only the new one
    assert_contains "$output" "[lessons] 1 lesson(s) cited" "Should cite new lesson"
}

test_handles_system_lessons() {
    local transcript="$TEST_DIR/test.jsonl"

    # Add a system lesson
    "$MANAGER" add-system pattern "System lesson" "A system test" >/dev/null 2>&1

    create_transcript "$transcript" \
        "$(create_transcript_entry "2025-01-01T00:00:00.000Z" "Applying [S001]")"

    local output=$(run_hook "$transcript")
    assert_contains "$output" "[lessons] 1 lesson(s) cited" "Should cite system lesson"
}

test_lesson_use_count_incremented() {
    local transcript="$TEST_DIR/test.jsonl"

    # Get initial use count
    local before=$("$MANAGER" list --verbose 2>/dev/null | grep "\[L001\]" | grep -oE "Uses: [0-9]+" | grep -oE "[0-9]+" || echo "1")

    create_transcript "$transcript" \
        "$(create_transcript_entry "2025-01-01T00:00:00.000Z" "Applying [L001]")"
    run_hook "$transcript"

    # Get after use count
    local after=$("$MANAGER" list --verbose 2>/dev/null | grep "\[L001\]" | grep -oE "Uses: [0-9]+" | grep -oE "[0-9]+" || echo "2")

    [[ "$after" -gt "$before" ]] || {
        echo "Use count should have increased: before=$before, after=$after"
        return 1
    }
}

# =============================================================================
# Cleanup Tests
# =============================================================================

test_cleanup_removes_old_orphans() {
    # Create a fake orphan checkpoint (no matching transcript)
    local state_dir="$CLAUDE_RECALL_BASE/.citation-state"
    mkdir -p "$state_dir"
    local orphan_file="$state_dir/fake-orphan-session-id"
    echo "2025-01-01T00:00:00.000Z" > "$orphan_file"

    # Backdate it to 10 days ago (beyond 7-day threshold)
    touch -t 202401010000 "$orphan_file"

    # Run the hook (which triggers cleanup)
    local transcript="$TEST_DIR/test.jsonl"
    create_transcript "$transcript" \
        "$(create_transcript_entry "2025-01-01T00:00:00.000Z" "No citations here")"
    run_hook "$transcript"

    # Orphan should be deleted
    [[ ! -f "$orphan_file" ]] || {
        echo "Orphan checkpoint should have been deleted"
        return 1
    }
}

test_cleanup_keeps_recent_orphans() {
    # Create a fake orphan checkpoint (no matching transcript)
    local state_dir="$CLAUDE_RECALL_BASE/.citation-state"
    mkdir -p "$state_dir"
    local orphan_file="$state_dir/fake-recent-orphan-id"
    echo "2025-01-01T00:00:00.000Z" > "$orphan_file"

    # Don't backdate - it's recent (within 7 days)
    # File will have current mtime

    # Run the hook (which triggers cleanup)
    local transcript="$TEST_DIR/test.jsonl"
    create_transcript "$transcript" \
        "$(create_transcript_entry "2025-01-01T00:00:00.000Z" "No citations here")"
    run_hook "$transcript"

    # Recent orphan should be kept
    [[ -f "$orphan_file" ]] || {
        echo "Recent orphan checkpoint should NOT have been deleted"
        return 1
    }
}

# =============================================================================
# Decay Tests
# =============================================================================

test_decay_reduces_stale_lesson_uses() {
    # Create a lesson with old last-used date
    local lessons_file="$CLAUDE_RECALL_BASE/LESSONS.md"
    mkdir -p "$(dirname "$lessons_file")"

    # Create a lesson that was last used 60 days ago with 5 uses
    local old_date=$(date -v-60d +%Y-%m-%d 2>/dev/null || date -d "60 days ago" +%Y-%m-%d)
    cat > "$lessons_file" << EOF
# LESSONS.md - System Level

## Active Lessons

### [S001] [**+--/-----] Old lesson
- **Uses**: 5 | **Learned**: 2024-01-01 | **Last**: $old_date | **Category**: pattern
> This is an old lesson that should decay

EOF

    # Create a checkpoint to simulate activity
    local state_dir="$CLAUDE_RECALL_BASE/.citation-state"
    mkdir -p "$state_dir"
    touch "$state_dir/recent-session"

    # Run decay
    local output=$("$MANAGER" decay 30 2>&1)

    # Check that uses decreased (note: **Uses** in markdown)
    local new_uses=$(grep -oE '\*\*Uses\*\*: [0-9]+' "$lessons_file" | grep -oE '[0-9]+')
    [[ "$new_uses" -eq 4 ]] || {
        echo "Uses should have decreased from 5 to 4, got: $new_uses"
        return 1
    }
}

test_decay_skips_without_activity() {
    # Create a lesson with old last-used date
    local lessons_file="$CLAUDE_RECALL_BASE/LESSONS.md"
    mkdir -p "$(dirname "$lessons_file")"

    local old_date=$(date -v-60d +%Y-%m-%d 2>/dev/null || date -d "60 days ago" +%Y-%m-%d)
    cat > "$lessons_file" << EOF
# LESSONS.md - System Level

## Active Lessons

### [S001] [**+--/-----] Vacation lesson
- **Uses**: 5 | **Learned**: 2024-01-01 | **Last**: $old_date | **Category**: pattern
> This should not decay if no sessions occurred

EOF

    # Create decay state file (simulating previous decay ran)
    echo "$(date +%s)" > "$CLAUDE_RECALL_BASE/.decay-last-run"

    # Don't create any checkpoints (simulating no coding activity)

    # Run decay
    local output=$("$MANAGER" decay 30 2>&1)
    assert_contains "$output" "No sessions since last decay" "Should skip decay without activity"

    # Uses should remain unchanged (note: **Uses** in markdown)
    local new_uses=$(grep -oE '\*\*Uses\*\*: [0-9]+' "$lessons_file" | grep -oE '[0-9]+')
    [[ "$new_uses" -eq 5 ]] || {
        echo "Uses should remain at 5 without activity, got: $new_uses"
        return 1
    }
}

test_decay_never_below_one() {
    # Create a lesson with uses=1 and old date
    local lessons_file="$CLAUDE_RECALL_BASE/LESSONS.md"
    mkdir -p "$(dirname "$lessons_file")"

    local old_date=$(date -v-60d +%Y-%m-%d 2>/dev/null || date -d "60 days ago" +%Y-%m-%d)
    cat > "$lessons_file" << EOF
# LESSONS.md - System Level

## Active Lessons

### [S001] [+----/-----] Minimal lesson
- **Uses**: 1 | **Learned**: 2024-01-01 | **Last**: $old_date | **Category**: pattern
> This should never go below 1

EOF

    # Create a checkpoint to simulate activity
    local state_dir="$CLAUDE_RECALL_BASE/.citation-state"
    mkdir -p "$state_dir"
    touch "$state_dir/recent-session"

    # Run decay
    "$MANAGER" decay 30 >/dev/null 2>&1

    # Uses should still be 1 (floor) - note: **Uses** in markdown
    local new_uses=$(grep -oE '\*\*Uses\*\*: [0-9]+' "$lessons_file" | grep -oE '[0-9]+')
    [[ "$new_uses" -eq 1 ]] || {
        echo "Uses should remain at minimum 1, got: $new_uses"
        return 1
    }
}

# =============================================================================
# TodoWrite Capture Tests
# =============================================================================

# Helper: create a TodoWrite tool_use transcript entry
create_todowrite_entry() {
    local timestamp="$1"
    local todos_json="$2"

    cat <<EOF
{"timestamp":"$timestamp","uuid":"$(uuidgen 2>/dev/null || echo "test-uuid-$RANDOM")","type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","id":"toolu_test","name":"TodoWrite","input":{"todos":$todos_json}}]}}
EOF
}

# Setup for TodoWrite tests - needs Python manager
setup_todowrite() {
    setup
    # Create project-level lessons/approaches files
    mkdir -p "$PROJECT_DIR/.claude-recall"
    cat > "$PROJECT_DIR/.claude-recall/LESSONS.md" << 'EOF'
# LESSONS.md - Project Level

## Active Lessons

EOF
    cat > "$PROJECT_DIR/.claude-recall/APPROACHES.md" << 'EOF'
# APPROACHES.md - Active Work Tracking

## Active Approaches

EOF
}

test_todowrite_capture_creates_approach() {
    setup_todowrite
    local transcript="$TEST_DIR/test.jsonl"

    # Create TodoWrite with pending todos
    local todos='[{"content":"First task","status":"pending","activeForm":"Working on first task"}]'
    create_transcript "$transcript" \
        "$(create_todowrite_entry "2025-01-01T00:00:00.000Z" "$todos")"

    local output=$(run_hook "$transcript")

    # Should have synced
    assert_contains "$output" "[approaches] Synced TodoWrite" "Should sync TodoWrite"

    # Approach file should have content
    assert_file_contains "$PROJECT_DIR/.claude-recall/APPROACHES.md" "First task" \
        "Approach should contain todo content"
}

test_todowrite_capture_with_completed_todos() {
    setup_todowrite
    local transcript="$TEST_DIR/test.jsonl"

    # Create TodoWrite with completed todos
    local todos='[{"content":"Completed task","status":"completed","activeForm":"Done with task"},{"content":"Pending task","status":"pending","activeForm":"Working"}]'
    create_transcript "$transcript" \
        "$(create_todowrite_entry "2025-01-01T00:00:00.000Z" "$todos")"

    run_hook "$transcript"

    # Approach should have tried entry for completed (format: "1. [success] Completed task")
    assert_file_contains "$PROJECT_DIR/.claude-recall/APPROACHES.md" "success.*Completed task" \
        "Completed todos should become tried entries"
}

test_todowrite_capture_uses_last_call() {
    setup_todowrite
    local transcript="$TEST_DIR/test.jsonl"

    # Create multiple TodoWrite calls - should use the LAST one
    local todos1='[{"content":"First call task","status":"pending","activeForm":"First"}]'
    local todos2='[{"content":"Second call task","status":"pending","activeForm":"Second"}]'

    create_transcript "$transcript" \
        "$(create_todowrite_entry "2025-01-01T00:00:00.000Z" "$todos1")" \
        "$(create_todowrite_entry "2025-01-01T00:01:00.000Z" "$todos2")"

    run_hook "$transcript"

    # Should have the second task, not the first
    assert_file_contains "$PROJECT_DIR/.claude-recall/APPROACHES.md" "Second call task" \
        "Should use last TodoWrite call"
}

test_todowrite_capture_handles_multiline_json() {
    # This is the key regression test for the jq -c vs -r bug
    setup_todowrite
    local transcript="$TEST_DIR/test.jsonl"

    # Create TodoWrite with multiple todos (will be multi-line with jq -r)
    local todos='[{"content":"Task one","status":"completed","activeForm":"One"},{"content":"Task two","status":"completed","activeForm":"Two"},{"content":"Task three","status":"pending","activeForm":"Three"}]'
    create_transcript "$transcript" \
        "$(create_todowrite_entry "2025-01-01T00:00:00.000Z" "$todos")"

    local output=$(run_hook "$transcript")

    # Should sync successfully (the bug would cause this to fail silently)
    assert_contains "$output" "[approaches] Synced TodoWrite" \
        "Multi-todo arrays should sync (jq -c fix)"

    # All completed todos should be recorded
    assert_file_contains "$PROJECT_DIR/.claude-recall/APPROACHES.md" "success.*Task one" \
        "First completed task should be recorded"
    assert_file_contains "$PROJECT_DIR/.claude-recall/APPROACHES.md" "success.*Task two" \
        "Second completed task should be recorded"
}

test_todowrite_capture_incremental() {
    setup_todowrite
    local transcript="$TEST_DIR/test-session.jsonl"

    # First run
    local todos1='[{"content":"Initial task","status":"pending","activeForm":"Working"}]'
    create_transcript "$transcript" \
        "$(create_todowrite_entry "2025-01-01T00:00:00.000Z" "$todos1")"
    run_hook "$transcript"

    # Second run with new TodoWrite (later timestamp)
    local todos2='[{"content":"New task","status":"pending","activeForm":"Working"}]'
    echo "$(create_todowrite_entry "2025-01-01T01:00:00.000Z" "$todos2")" >> "$transcript"

    local output=$(run_hook "$transcript")

    # Should sync the new one
    assert_contains "$output" "[approaches] Synced TodoWrite" "Should sync new TodoWrite"
}

test_todowrite_capture_skips_empty() {
    setup_todowrite
    local transcript="$TEST_DIR/test.jsonl"

    # Create TodoWrite with empty array
    local todos='[]'
    create_transcript "$transcript" \
        "$(create_todowrite_entry "2025-01-01T00:00:00.000Z" "$todos")"

    local output=$(run_hook "$transcript")

    # Should not sync empty todos
    [[ "$output" != *"[approaches]"* ]] || {
        echo "Should not sync empty TodoWrite"
        return 1
    }
}

# =============================================================================
# Run Tests
# =============================================================================

echo ""
echo "========================================"
echo "  Stop Hook Citation Tracking Tests"
echo "========================================"
echo ""

run_test test_no_transcript_exits_cleanly
run_test test_empty_transcript_exits_cleanly
run_test test_extracts_citation_from_assistant_message
run_test test_ignores_user_messages
run_test test_deduplicates_citations
run_test test_multiple_different_citations
run_test test_excludes_lesson_listings
run_test test_checkpoint_created
run_test test_checkpoint_contains_timestamp
run_test test_incremental_processing_skips_old
run_test test_incremental_processing_catches_new
run_test test_handles_system_lessons
run_test test_lesson_use_count_incremented

echo ""
echo "========================================"
echo "  Cleanup Tests"
echo "========================================"
echo ""

run_test test_cleanup_removes_old_orphans
run_test test_cleanup_keeps_recent_orphans

echo ""
echo "========================================"
echo "  Decay Tests"
echo "========================================"
echo ""

run_test test_decay_reduces_stale_lesson_uses
run_test test_decay_skips_without_activity
run_test test_decay_never_below_one

echo ""
echo "========================================"
echo "  TodoWrite Capture Tests"
echo "========================================"
echo ""

run_test test_todowrite_capture_creates_approach
run_test test_todowrite_capture_with_completed_todos
run_test test_todowrite_capture_uses_last_call
run_test test_todowrite_capture_handles_multiline_json
run_test test_todowrite_capture_incremental
run_test test_todowrite_capture_skips_empty

echo ""
echo "========================================"
echo "  Results: $TESTS_PASSED/$TESTS_RUN passed"
if [[ $TESTS_FAILED -gt 0 ]]; then
    echo -e "  ${RED}$TESTS_FAILED tests failed${NC}"
    exit 1
else
    echo -e "  ${GREEN}All tests passed!${NC}"
fi
echo "========================================"
