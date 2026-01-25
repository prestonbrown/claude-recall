#!/bin/bash
# SPDX-License-Identifier: MIT
# test-install.sh - Automated tests for install.sh

set -euo pipefail

# Test configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALLER="$SCRIPT_DIR/../install.sh"
TEST_DIR=$(mktemp -d)
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Override HOME for testing
export HOME="$TEST_DIR/home"
export CLAUDE_RECALL_BASE="$HOME/.config/claude-recall"

setup() {
    rm -rf "$TEST_DIR"
    mkdir -p "$HOME"
    mkdir -p "$HOME/.claude"  # Simulate Claude Code installed
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

assert_file_not_exists() {
    local file="$1"
    local msg="${2:-File should not exist: $file}"
    if [[ ! -f "$file" ]]; then
        return 0
    else
        echo -e "${RED}ASSERTION FAILED${NC}: $msg"
        return 1
    fi
}

assert_dir_exists() {
    local dir="$1"
    local msg="${2:-Directory should exist: $dir}"
    if [[ -d "$dir" ]]; then
        return 0
    else
        echo -e "${RED}ASSERTION FAILED${NC}: $msg"
        return 1
    fi
}

assert_executable() {
    local file="$1"
    local msg="${2:-File should be executable: $file}"
    if [[ -x "$file" ]]; then
        return 0
    else
        echo -e "${RED}ASSERTION FAILED${NC}: $msg"
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

test_help_option() {
    local output
    output=$("$INSTALLER" --help)
    assert_contains "$output" "Usage:" "Help should show usage"
    assert_contains "$output" "--claude" "Help should mention --claude"
    assert_contains "$output" "--opencode" "Help should mention --opencode"
    assert_contains "$output" "--migrate" "Help should mention --migrate"
}

# =============================================================================
# CONFIG PRESERVATION TESTS (Pure unit tests of merge logic)
# =============================================================================

# These tests verify the jq merge logic directly without running the full installer.
# The merge order should be: defaults < existing config

test_config_merge_preserves_existing() {
    # Test: existing config values should override defaults

    local defaults='{"enabled": true, "maxLessons": 30, "debugLevel": 1}'
    local existing='{"debugLevel": 2}'

    local result
    result=$(jq -s '.[0] * .[1]' \
        <(echo "$defaults") \
        <(echo "$existing"))

    local debug_level
    debug_level=$(echo "$result" | jq -r '.debugLevel')
    assert_eq "2" "$debug_level" "Custom debugLevel should be preserved"

    local max_lessons
    max_lessons=$(echo "$result" | jq -r '.maxLessons')
    assert_eq "30" "$max_lessons" "Default maxLessons should be used"
}

test_config_merge_with_new_defaults() {
    # Test: new fields in defaults should be added to existing config

    local defaults='{"enabled": true, "maxLessons": 30, "newField": "default", "debugLevel": 1}'
    local existing='{"debugLevel": 2}'

    local result
    result=$(jq -s '.[0] * .[1]' \
        <(echo "$defaults") \
        <(echo "$existing"))

    local debug_level new_field
    debug_level=$(echo "$result" | jq -r '.debugLevel')
    new_field=$(echo "$result" | jq -r '.newField')

    assert_eq "2" "$debug_level" "Custom debugLevel should be preserved"
    assert_eq "default" "$new_field" "New default field should be added"
}

test_config_merge_fresh_install() {
    # Test: fresh install with no existing config should use defaults

    local defaults='{"enabled": true, "maxLessons": 30, "debugLevel": 1}'
    local existing='{}'

    local result
    result=$(jq -s '.[0] * .[1]' \
        <(echo "$defaults") \
        <(echo "$existing"))

    local debug_level
    debug_level=$(echo "$result" | jq -r '.debugLevel')
    assert_eq "1" "$debug_level" "Fresh install should use defaults"
}

test_config_merge_priority_order() {
    # Test: priority is defaults < existing

    local defaults='{"enabled": true, "maxLessons": 30, "debugLevel": 1}'
    local existing='{"debugLevel": 2, "maxLessons": 25}'

    local result
    result=$(jq -s '.[0] * .[1]' \
        <(echo "$defaults") \
        <(echo "$existing"))

    local debug_level max_lessons
    debug_level=$(echo "$result" | jq -r '.debugLevel')
    max_lessons=$(echo "$result" | jq -r '.maxLessons')

    # Priority: defaults (1) < existing (2)
    assert_eq "2" "$debug_level" "Existing config value should override default"
    assert_eq "25" "$max_lessons" "Existing config value should override default"
}

test_config_merge_multiline_json() {
    # Test: multiline JSON with closing braces should merge correctly
    # This tests the fix for the ${var:-{}} bash expansion bug where
    # JSON ending in } would get an extra } appended

    # Simulate real config.json format (multiline)
    local defaults
    defaults=$(cat <<'JSONEOF'
{
  "enabled": true,
  "maxLessons": 30,
  "debugLevel": 1
}
JSONEOF
)

    local existing
    existing=$(cat <<'JSONEOF'
{
  "enabled": true,
  "maxLessons": 30,
  "debugLevel": 2
}
JSONEOF
)

    local migration='{}'

    # This tests the jq merge with multiline JSON
    local result
    result=$(jq -s '.[0] * .[1] * .[2]' \
        <(echo "$defaults") \
        <(echo "$existing") \
        <(echo "$migration"))

    # Should not fail with parse error
    local debug_level
    debug_level=$(echo "$result" | jq -r '.debugLevel')
    assert_eq "2" "$debug_level" "Multiline JSON with closing braces should merge correctly"
}

test_config_merge_variable_with_closing_brace() {
    # Test: variable containing JSON that ends with } should work
    # This specifically tests the install.sh fix that avoids ${var:-{}}

    local defaults='{"enabled": true, "maxLessons": 30, "debugLevel": 1}'

    # Simulate SAVED_CONFIG_JSON variable containing JSON ending with }
    local SAVED_CONFIG_JSON='{"debugLevel": 2}'

    # Use the fixed pattern (conditional instead of ${var:-{}})
    local saved_config
    if [[ -n "$SAVED_CONFIG_JSON" ]]; then
        saved_config="$SAVED_CONFIG_JSON"
    else
        saved_config="{}"
    fi

    local result
    result=$(jq -s '.[0] * .[1]' \
        <(echo "$defaults") \
        <(echo "$saved_config"))

    local debug_level
    debug_level=$(echo "$result" | jq -r '.debugLevel')
    assert_eq "2" "$debug_level" "Variable containing JSON with } should merge correctly"
}

# =============================================================================
# RUN TESTS
# =============================================================================

main() {
    echo ""
    echo -e "${YELLOW}=== Install Script Test Suite ===${NC}"
    echo ""

    # Basic commands
    run_test "help option" test_help_option

    # Config preservation (plugin-based installation)
    run_test "config merge preserves existing" test_config_merge_preserves_existing
    run_test "config merge with new defaults" test_config_merge_with_new_defaults
    run_test "config merge fresh install" test_config_merge_fresh_install
    run_test "config merge priority order" test_config_merge_priority_order
    run_test "config merge multiline JSON" test_config_merge_multiline_json
    run_test "config merge variable with closing brace" test_config_merge_variable_with_closing_brace
    
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
