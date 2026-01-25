#!/bin/bash
# SPDX-License-Identifier: MIT
# test-exitplanmode-hook.sh - Tests for post-exitplanmode hook handoff creation

set -euo pipefail

# Test configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOK="$SCRIPT_DIR/../adapters/claude-code/post-exitplanmode-hook.sh"
TEST_DIR=$(mktemp -d)
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

# Override paths for testing
export CLAUDE_RECALL_BASE="$TEST_DIR/.config/claude-recall"
export CLAUDE_RECALL_STATE="$TEST_DIR/.local/state/claude-recall"
export PROJECT_DIR="$TEST_DIR/project"
export HOME="$TEST_DIR"

setup() {
    rm -rf "$TEST_DIR"
    mkdir -p "$TEST_DIR/project/.git"  # Fake git repo
    mkdir -p "$TEST_DIR/project/.claude-recall"  # Project handoffs dir
    mkdir -p "$CLAUDE_RECALL_BASE"
    mkdir -p "$CLAUDE_RECALL_STATE"
    mkdir -p "$TEST_DIR/.claude"
    mkdir -p "$TEST_DIR/.claude/plans"

    # Create shared config.json with recall enabled
    mkdir -p "$TEST_DIR/.config/claude-recall"
    echo '{"enabled":true}' > "$TEST_DIR/.config/claude-recall/config.json"

    # Symlink CLI to where hook expects it
    ln -sf "$SCRIPT_DIR/../core/cli.py" "$CLAUDE_RECALL_BASE/cli.py"

    # Initialize empty handoffs file
    cat > "$TEST_DIR/project/.claude-recall/HANDOFFS.md" << 'EOF'
# HANDOFFS.md - Active Work Tracking

## Active Handoffs

EOF
}

teardown() {
    rm -rf "$TEST_DIR"
}

# Helper: run hook with mock input
run_hook() {
    local cwd="${1:-$PROJECT_DIR}"
    echo "{\"cwd\":\"$cwd\"}" | "$HOOK" 2>&1
}

# Helper: create a plan file
create_plan() {
    local title="$1"
    local filename="${2:-test-plan.md}"
    cat > "$TEST_DIR/.claude/plans/$filename" << EOF
# Plan: $title

## Overview
This is a test plan.

## Steps
1. Step one
2. Step two
EOF
    # Touch to ensure it's the most recent
    sleep 0.1
    touch "$TEST_DIR/.claude/plans/$filename"
}

# Assertions
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
        echo "  Should NOT contain: '$needle'"
        echo "  Actual: '$haystack'"
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

test_no_plans_exits_cleanly() {
    # No plan files in directory
    rmdir "$TEST_DIR/.claude/plans" 2>/dev/null || rm -rf "$TEST_DIR/.claude/plans"

    local output=$(run_hook)
    # Should exit cleanly with no output
    [[ -z "$output" ]]
}

test_creates_handoff_from_plan() {
    create_plan "Test Feature Implementation"

    local output=$(run_hook)

    # Handoff file should contain the title
    assert_file_contains "$TEST_DIR/project/.claude-recall/HANDOFFS.md" \
        "Test Feature Implementation" \
        "Handoff should be created with plan title"
}

test_output_contains_handoff_id() {
    create_plan "My Test Plan"

    local output=$(run_hook)

    # Output should contain the handoff ID pattern
    assert_contains "$output" "hf-" "Output should contain handoff ID"
}

test_output_contains_visible_banner() {
    create_plan "My Test Plan"

    local output=$(run_hook)

    # Output should have visible banner
    assert_contains "$output" "HANDOFF CREATED" "Output should have HANDOFF CREATED banner"
    assert_contains "$output" "═══" "Output should have visual separator"
}

test_output_contains_continuation_prompt() {
    create_plan "My Test Plan"

    local output=$(run_hook)

    # Output should include ready-to-use continuation prompt
    assert_contains "$output" "Continue handoff" "Output should have continuation prompt"
    assert_contains "$output" "For continuation in a new session" "Output should explain usage"
}

test_output_contains_title() {
    create_plan "Specific Plan Title"

    local output=$(run_hook)

    # Output should show the title
    assert_contains "$output" "Title: Specific Plan Title" "Output should show title"
}

test_uses_most_recent_plan() {
    # Create older plan
    create_plan "Old Plan" "old-plan.md"
    sleep 0.2
    # Create newer plan
    create_plan "New Plan" "new-plan.md"

    local output=$(run_hook)

    # Should use the newer plan
    assert_contains "$output" "New Plan" "Should use most recent plan"
    assert_not_contains "$output" "Old Plan" "Should not use old plan"
}

test_extracts_title_without_plan_prefix() {
    # Create plan with "# Plan: Title" format
    cat > "$TEST_DIR/.claude/plans/prefixed.md" << 'EOF'
# Plan: My Prefixed Title

Content here
EOF

    local output=$(run_hook)

    # Should strip "Plan: " prefix
    assert_contains "$output" "Title: My Prefixed Title" "Should strip Plan: prefix"
    assert_not_contains "$output" "Title: Plan:" "Should not double the Plan: prefix"
}

test_extracts_title_without_prefix() {
    # Create plan with just "# Title" format
    cat > "$TEST_DIR/.claude/plans/simple.md" << 'EOF'
# Simple Title

Content here
EOF

    local output=$(run_hook)

    assert_contains "$output" "Title: Simple Title" "Should handle simple title format"
}

test_handoff_has_implementing_phase() {
    create_plan "Phase Test Plan"

    run_hook > /dev/null

    # Handoff should have implementing phase
    assert_file_contains "$TEST_DIR/project/.claude-recall/HANDOFFS.md" \
        "implementing" \
        "Handoff should have implementing phase"
}

test_disabled_does_nothing() {
    # Disable claude recall
    echo '{"enabled":false}' > "$TEST_DIR/.config/claude-recall/config.json"

    create_plan "Should Not Create"

    local output=$(run_hook)

    # Should be empty output
    [[ -z "$output" ]]

    # Handoffs file should not have the title
    ! grep -q "Should Not Create" "$TEST_DIR/project/.claude-recall/HANDOFFS.md"
}

test_handoff_includes_plan_file_path() {
    create_plan "Plan File Test"

    run_hook > /dev/null

    # Handoff should include the plan file path in refs
    assert_file_contains "$TEST_DIR/project/.claude-recall/HANDOFFS.md" \
        ".claude/plans/" \
        "Handoff should include plan file path in refs"
}

# =============================================================================
# Run Tests
# =============================================================================

echo ""
echo "========================================"
echo "  Post-ExitPlanMode Hook Tests"
echo "========================================"
echo ""

run_test test_no_plans_exits_cleanly
run_test test_creates_handoff_from_plan
run_test test_output_contains_handoff_id
run_test test_output_contains_visible_banner
run_test test_output_contains_continuation_prompt
run_test test_output_contains_title
run_test test_uses_most_recent_plan
run_test test_extracts_title_without_plan_prefix
run_test test_extracts_title_without_prefix
run_test test_handoff_has_implementing_phase
run_test test_disabled_does_nothing
run_test test_handoff_includes_plan_file_path

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
