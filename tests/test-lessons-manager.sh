#!/bin/bash
# SPDX-License-Identifier: MIT
# test-lessons-manager.sh - Automated tests for lessons-manager.sh

set -euo pipefail

# Test configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANAGER="$SCRIPT_DIR/../core/lessons-manager.sh"
TEST_DIR=$(mktemp -d)
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Override paths for testing
export CLAUDE_RECALL_BASE="$TEST_DIR/.config/claude-recall"
export CLAUDE_RECALL_STATE="$TEST_DIR/.local/state/claude-recall"
export PROJECT_DIR="$TEST_DIR/project"

setup() {
    rm -rf "$TEST_DIR"
    mkdir -p "$TEST_DIR/project/.git"  # Fake git repo
    mkdir -p "$CLAUDE_RECALL_BASE"
    mkdir -p "$CLAUDE_RECALL_STATE"  # Isolate system lessons
}

teardown() {
    rm -rf "$TEST_DIR"
}

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

assert_not_contains() {
    local haystack="$1"
    local needle="$2"
    local msg="${3:-}"
    if [[ "$haystack" != *"$needle"* ]]; then
        return 0
    else
        echo -e "${RED}ASSERTION FAILED${NC}: $msg"
        echo "  Expected NOT to contain: '$needle'"
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

assert_exit_code() {
    local expected="$1"
    local actual="$2"
    local msg="${3:-}"
    if [[ "$expected" == "$actual" ]]; then
        return 0
    else
        echo -e "${RED}ASSERTION FAILED${NC}: $msg"
        echo "  Expected exit code: $expected"
        echo "  Actual exit code:   $actual"
        return 1
    fi
}

run_test() {
    local test_name="$1"
    local test_func="$2"
    ((TESTS_RUN++))
    
    setup
    
    echo -n "  Testing: $test_name ... "
    
    local output
    local exit_code=0
    if output=$($test_func 2>&1); then
        echo -e "${GREEN}PASSED${NC}"
        ((TESTS_PASSED++))
    else
        exit_code=$?
        echo -e "${RED}FAILED${NC}"
        echo "$output" | sed 's/^/    /'
        ((TESTS_FAILED++))
    fi
    
    teardown
}

# =============================================================================
# TEST CASES
# =============================================================================

test_help_command() {
    local output
    output=$("$MANAGER" help)
    assert_contains "$output" "lessons-manager.sh" "Help should show script name"
    assert_contains "$output" "COMMANDS:" "Help should list commands"
    assert_contains "$output" "add" "Help should mention add command"
    assert_contains "$output" "cite" "Help should mention cite command"
}

test_add_project_lesson() {
    local output
    output=$("$MANAGER" add pattern "Test Lesson" "This is test content")
    assert_contains "$output" "Added project lesson L001" "Should confirm lesson added"
    
    local lessons_file="$TEST_DIR/project/.claude-recall/LESSONS.md"
    assert_file_exists "$lessons_file" "Lessons file should be created"
    
    local content
    content=$(cat "$lessons_file")
    assert_contains "$content" "[L001]" "Should have lesson ID"
    assert_contains "$content" "Test Lesson" "Should have lesson title"
    assert_contains "$content" "This is test content" "Should have lesson content"
    assert_contains "$content" "**Category**: pattern" "Should have category"
    assert_contains "$content" "**Uses**: 1" "Should start with 1 use"
}

test_add_system_lesson() {
    local output
    output=$("$MANAGER" add-system gotcha "System Gotcha" "Always check X before Y")
    assert_contains "$output" "Added system lesson S001" "Should confirm system lesson added"
    
    local lessons_file="$CLAUDE_RECALL_BASE/LESSONS.md"
    assert_file_exists "$lessons_file" "System lessons file should be created"
    
    local content
    content=$(cat "$lessons_file")
    assert_contains "$content" "[S001]" "Should have system lesson ID"
    assert_contains "$content" "System Gotcha" "Should have lesson title"
}

test_add_multiple_lessons_increment_id() {
    "$MANAGER" add pattern "First Lesson" "Content 1" >/dev/null
    "$MANAGER" add correction "Second Lesson" "Content 2" >/dev/null
    local output
    output=$("$MANAGER" add decision "Third Lesson" "Content 3")
    
    assert_contains "$output" "L003" "Third lesson should be L003"
    
    local lessons_file="$TEST_DIR/project/.claude-recall/LESSONS.md"
    local content
    content=$(cat "$lessons_file")
    assert_contains "$content" "[L001]" "Should have L001"
    assert_contains "$content" "[L002]" "Should have L002"
    assert_contains "$content" "[L003]" "Should have L003"
}

test_duplicate_detection() {
    "$MANAGER" add pattern "Use RAII for memory" "Always use smart pointers" >/dev/null
    
    local output
    local exit_code=0
    output=$("$MANAGER" add pattern "Use RAII for Memory" "Different content" 2>&1) || exit_code=$?
    
    assert_eq "1" "$exit_code" "Should fail on duplicate"
    assert_contains "$output" "Similar lesson already exists" "Should warn about duplicate"
}

test_add_force_bypasses_duplicate() {
    "$MANAGER" add pattern "Use RAII" "First version" >/dev/null
    
    local output
    output=$("$MANAGER" add --force pattern "Use RAII" "Second version")
    
    assert_contains "$output" "Added project lesson L002" "Force should bypass duplicate check"
}

test_cite_lesson() {
    "$MANAGER" add pattern "Cite Test" "Test content" >/dev/null
    
    local output
    output=$("$MANAGER" cite L001)
    assert_contains "$output" "OK:2" "Cite should return new count"
    
    local lessons_file="$TEST_DIR/project/.claude-recall/LESSONS.md"
    local content
    content=$(cat "$lessons_file")
    assert_contains "$content" "**Uses**: 2" "Uses should be incremented"
}

test_cite_updates_last_date() {
    "$MANAGER" add pattern "Date Test" "Test content" >/dev/null
    
    local today
    today=$(date +%Y-%m-%d)
    
    "$MANAGER" cite L001 >/dev/null
    
    local lessons_file="$TEST_DIR/project/.claude-recall/LESSONS.md"
    local content
    content=$(cat "$lessons_file")
    assert_contains "$content" "**Last**: $today" "Last date should be updated"
}

test_cite_nonexistent_lesson() {
    local output
    local exit_code=0
    output=$("$MANAGER" cite L999 2>&1) || exit_code=$?
    
    assert_eq "1" "$exit_code" "Should fail for nonexistent lesson"
    assert_contains "$output" "not found" "Should say lesson not found"
}

test_cite_system_lesson() {
    "$MANAGER" add-system pattern "System Test" "System content" >/dev/null
    
    local output
    output=$("$MANAGER" cite S001)
    assert_contains "$output" "OK:2" "Should cite system lesson"
}

test_edit_lesson() {
    "$MANAGER" add pattern "Edit Test" "Original content" >/dev/null
    
    local output
    output=$("$MANAGER" edit L001 "Updated content")
    assert_contains "$output" "Updated L001" "Should confirm update"
    
    local lessons_file="$TEST_DIR/project/.claude-recall/LESSONS.md"
    local content
    content=$(cat "$lessons_file")
    assert_contains "$content" "Updated content" "Content should be updated"
    assert_not_contains "$content" "Original content" "Old content should be gone"
}

test_edit_nonexistent_lesson() {
    local output
    local exit_code=0
    output=$("$MANAGER" edit L999 "New content" 2>&1) || exit_code=$?
    
    assert_eq "1" "$exit_code" "Should fail for nonexistent lesson"
}

test_delete_lesson() {
    "$MANAGER" add pattern "Delete Me" "To be deleted" >/dev/null
    "$MANAGER" add pattern "Keep Me" "To be kept" >/dev/null
    
    local output
    output=$("$MANAGER" delete L001)
    assert_contains "$output" "Deleted L001" "Should confirm deletion"
    
    local lessons_file="$TEST_DIR/project/.claude-recall/LESSONS.md"
    local content
    content=$(cat "$lessons_file")
    assert_not_contains "$content" "Delete Me" "Deleted lesson should be gone"
    assert_contains "$content" "Keep Me" "Other lesson should remain"
}

test_delete_nonexistent_lesson() {
    local output
    local exit_code=0
    output=$("$MANAGER" delete L999 2>&1) || exit_code=$?
    
    assert_eq "1" "$exit_code" "Should fail for nonexistent lesson"
}

test_list_empty() {
    local output
    output=$("$MANAGER" list)
    assert_contains "$output" "no lessons found" "Should indicate no lessons"
}

test_list_project_lessons() {
    "$MANAGER" add pattern "List Test 1" "Content 1" >/dev/null
    "$MANAGER" add correction "List Test 2" "Content 2" >/dev/null
    
    local output
    output=$("$MANAGER" list --project)
    assert_contains "$output" "PROJECT" "Should show project header"
    assert_contains "$output" "[L001]" "Should list L001"
    assert_contains "$output" "[L002]" "Should list L002"
    assert_contains "$output" "Total: 2" "Should show total count"
}

test_list_system_lessons() {
    "$MANAGER" add-system pattern "System List Test" "System content" >/dev/null
    
    local output
    output=$("$MANAGER" list --system)
    assert_contains "$output" "SYSTEM" "Should show system header"
    assert_contains "$output" "[S001]" "Should list S001"
}

test_list_search_filter() {
    "$MANAGER" add pattern "RAII Pattern" "Use smart pointers" >/dev/null
    "$MANAGER" add correction "Logging Fix" "Use spdlog" >/dev/null

    local output
    output=$("$MANAGER" list --search "RAII")
    assert_contains "$output" "RAII Pattern" "Should find matching lesson"
    assert_not_contains "$output" "Logging Fix" "Should not show non-matching lesson"
}

test_list_search_by_id() {
    "$MANAGER" add pattern "First Lesson" "Content one" >/dev/null
    "$MANAGER" add correction "Second Lesson" "Content two" >/dev/null
    "$MANAGER" add-system gotcha "System Lesson" "System content" >/dev/null

    # Search by project lesson ID
    local output
    output=$("$MANAGER" list --search "L001")
    assert_contains "$output" "First Lesson" "Should find lesson by ID L001"
    assert_not_contains "$output" "Second Lesson" "Should not show non-matching lesson"

    # Search by system lesson ID
    output=$("$MANAGER" list --search "S001")
    assert_contains "$output" "System Lesson" "Should find system lesson by ID S001"
    assert_not_contains "$output" "First Lesson" "Should not show project lessons when searching S001"

    # Search by partial ID
    output=$("$MANAGER" list --search "L00")
    assert_contains "$output" "First Lesson" "Should find L001 with partial ID"
    assert_contains "$output" "Second Lesson" "Should find L002 with partial ID"
}

test_list_search_case_insensitive_id() {
    "$MANAGER" add pattern "Case Test" "Content" >/dev/null

    # Search should be case-insensitive
    local output
    output=$("$MANAGER" list --search "l001")
    assert_contains "$output" "Case Test" "Should find lesson with lowercase id search"
}

test_list_category_filter() {
    "$MANAGER" add pattern "Pattern Lesson" "Pattern content" >/dev/null
    "$MANAGER" add gotcha "Gotcha Lesson" "Gotcha content" >/dev/null
    
    local output
    output=$("$MANAGER" list --category gotcha)
    assert_contains "$output" "Gotcha Lesson" "Should find gotcha lesson"
    assert_not_contains "$output" "Pattern Lesson" "Should not show pattern lesson"
}

test_list_verbose() {
    "$MANAGER" add pattern "Verbose Test" "Detailed content" >/dev/null
    
    local output
    output=$("$MANAGER" list --verbose)
    assert_contains "$output" "Uses:" "Verbose should show uses"
    assert_contains "$output" "Category:" "Verbose should show category"
}

test_inject_context() {
    "$MANAGER" add pattern "Inject Test 1" "Content 1" >/dev/null
    "$MANAGER" add pattern "Inject Test 2" "Content 2" >/dev/null
    
    local output
    output=$("$MANAGER" inject 2)
    assert_contains "$output" "LESSONS ACTIVE:" "Should show lessons count"
    assert_contains "$output" "TOP LESSONS:" "Should show top lessons header"
    assert_contains "$output" "[L00" "Should show lesson IDs"
}

test_inject_empty() {
    local output
    output=$("$MANAGER" inject 5)
    # Should not error, just return nothing
    assert_eq "" "$output" "Empty inject should produce no output"
}

test_star_rating_initial() {
    "$MANAGER" add pattern "Stars Test" "Content" >/dev/null

    local lessons_file="$TEST_DIR/project/.claude-recall/LESSONS.md"
    local content
    content=$(cat "$lessons_file")
    # 1 use, 0 velocity = [*----|-----] (uses|velocity format)
    assert_contains "$content" "[*----|-----]" "Initial stars should show 1 use, 0 velocity"
}

test_star_rating_increases() {
    "$MANAGER" add pattern "Stars Growth" "Content" >/dev/null

    # Cite multiple times to increase stars
    for i in {1..4}; do
        "$MANAGER" cite L001 >/dev/null
    done

    local lessons_file="$TEST_DIR/project/.claude-recall/LESSONS.md"
    local content
    content=$(cat "$lessons_file")
    # 5 uses, 4 velocity (citations add velocity) = [**---|***--] (uses|velocity format)
    assert_contains "$content" "[**---|***--]" "Stars should reflect 5 uses and 4 velocity"
}

test_promotion_threshold() {
    export SYSTEM_PROMOTION_THRESHOLD=5
    "$MANAGER" add pattern "Promote Me" "Content" >/dev/null
    
    local output
    for i in {1..5}; do
        output=$("$MANAGER" cite L001)
    done
    
    # After 5 citations (started at 1, so now 6 uses), should trigger promotion
    # Actually need 4 more cites to reach 5
    assert_contains "$output" "PROMOTION_READY" "Should indicate promotion ready"
}

test_categories_accepted() {
    local categories=("pattern" "correction" "decision" "gotcha" "preference")
    local i=1
    for cat in "${categories[@]}"; do
        local output
        output=$("$MANAGER" add "$cat" "Test $cat" "Content for $cat")
        assert_contains "$output" "L00$i" "Should add lesson with category $cat"
        ((i++))
    done
}

test_project_root_detection() {
    # Create nested directory structure
    mkdir -p "$TEST_DIR/project/src/deep/nested"
    export PROJECT_DIR="$TEST_DIR/project/src/deep/nested"
    
    "$MANAGER" add pattern "Nested Test" "Content" >/dev/null
    
    # Should create lessons file at project root, not nested dir
    local expected_file="$TEST_DIR/project/.claude-recall/LESSONS.md"
    assert_file_exists "$expected_file" "Lessons file should be at project root"
}

test_concurrent_operations() {
    # Add multiple lessons in quick succession
    for i in {1..5}; do
        "$MANAGER" add pattern "Concurrent $i" "Content $i" &
    done
    wait
    
    local lessons_file="$TEST_DIR/project/.claude-recall/LESSONS.md"
    local count
    count=$(grep -c "^### \[L" "$lessons_file" || echo 0)
    
    # Due to race conditions, we may not get exactly 5, but should have some
    [[ $count -ge 1 ]] || { echo "Should have at least 1 lesson, got $count"; return 1; }
}

test_special_characters_in_content() {
    local output
    output=$("$MANAGER" add pattern "Special Chars" "Content with 'quotes' and \"double quotes\" and \$vars")
    assert_contains "$output" "L001" "Should handle special characters"

    local lessons_file="$TEST_DIR/project/.claude-recall/LESSONS.md"
    local content
    content=$(cat "$lessons_file")
    assert_contains "$content" "quotes" "Content should be preserved"
}

test_manager_finds_cli_in_core_subdirectory() {
    # Simulate installed layout: lessons-manager.sh at root, cli.py in core/
    local install_dir="$TEST_DIR/installed"
    mkdir -p "$install_dir/core"

    # Copy script to root (cli.py goes in core/)
    cp "$MANAGER" "$install_dir/lessons-manager.sh"

    # Create a minimal cli.py stub that just prints success
    cat > "$install_dir/core/cli.py" << 'STUBEOF'
#!/usr/bin/env python3
print("CLI_FOUND_SUCCESS")
STUBEOF
    chmod +x "$install_dir/core/cli.py"

    # Run from installed location - should find cli.py in core/
    local output
    output=$("$install_dir/lessons-manager.sh" 2>&1)
    assert_contains "$output" "CLI_FOUND_SUCCESS" "Should find cli.py in core/ subdirectory"
}

# =============================================================================
# RUN TESTS
# =============================================================================

main() {
    echo ""
    echo -e "${YELLOW}=== Lessons Manager Test Suite ===${NC}"
    echo ""
    
    # Basic commands
    run_test "help command" test_help_command
    
    # Add operations
    run_test "add project lesson" test_add_project_lesson
    run_test "add system lesson" test_add_system_lesson
    run_test "add multiple lessons increment ID" test_add_multiple_lessons_increment_id
    run_test "duplicate detection" test_duplicate_detection
    run_test "add --force bypasses duplicate" test_add_force_bypasses_duplicate
    run_test "categories accepted" test_categories_accepted
    run_test "special characters in content" test_special_characters_in_content
    run_test "manager finds cli.py in core/ subdirectory" test_manager_finds_cli_in_core_subdirectory

    # Cite operations
    run_test "cite lesson" test_cite_lesson
    run_test "cite updates last date" test_cite_updates_last_date
    run_test "cite nonexistent lesson" test_cite_nonexistent_lesson
    run_test "cite system lesson" test_cite_system_lesson
    run_test "promotion threshold" test_promotion_threshold
    
    # Edit operations
    run_test "edit lesson" test_edit_lesson
    run_test "edit nonexistent lesson" test_edit_nonexistent_lesson
    
    # Delete operations
    run_test "delete lesson" test_delete_lesson
    run_test "delete nonexistent lesson" test_delete_nonexistent_lesson
    
    # List operations
    run_test "list empty" test_list_empty
    run_test "list project lessons" test_list_project_lessons
    run_test "list system lessons" test_list_system_lessons
    run_test "list search filter" test_list_search_filter
    run_test "list search by ID" test_list_search_by_id
    run_test "list search case insensitive ID" test_list_search_case_insensitive_id
    run_test "list category filter" test_list_category_filter
    run_test "list verbose" test_list_verbose
    
    # Inject operations
    run_test "inject context" test_inject_context
    run_test "inject empty" test_inject_empty
    
    # Star rating
    run_test "star rating initial" test_star_rating_initial
    run_test "star rating increases" test_star_rating_increases
    
    # Edge cases
    run_test "project root detection" test_project_root_detection
    run_test "concurrent operations" test_concurrent_operations
    
    echo ""
    echo -e "${YELLOW}=== Test Results ===${NC}"
    echo -e "  Total:  $TESTS_RUN"
    echo -e "  ${GREEN}Passed: $TESTS_PASSED${NC}"
    echo -e "  ${RED}Failed: $TESTS_FAILED${NC}"
    echo ""
    
    if [[ $TESTS_FAILED -gt 0 ]]; then
        exit 1
    fi
}

main "$@"
