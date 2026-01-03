#!/bin/bash
# SPDX-License-Identifier: MIT
# Test that all hooks have LESSONS_SCORING_ACTIVE guards to prevent recursion
# This prevents infinite recursion when hooks spawn claude -p subprocesses

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
HOOKS_DIR="$REPO_ROOT/adapters/claude-code"
CORE_DIR="$REPO_ROOT/core"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

passed=0
failed=0
skipped=0

log_pass() { echo -e "${GREEN}✓${NC} $1"; ((passed++)) || true; }
log_fail() { echo -e "${RED}✗${NC} $1"; ((failed++)) || true; }
log_skip() { echo -e "${YELLOW}○${NC} $1 (skipped)"; ((skipped++)) || true; }

# Test that hook has guard at the top
test_has_guard_line() {
    local hook_path="$1"
    local hook_name="$(basename "$hook_path")"

    [[ ! -f "$hook_path" ]] && { log_skip "$hook_name - file not found"; return 0; }

    if head -20 "$hook_path" | grep -q 'LESSONS_SCORING_ACTIVE.*exit 0'; then
        log_pass "$hook_name has guard at top"
    else
        log_fail "$hook_name missing guard at top of file"
    fi
}

# Test that hook exits immediately when guard is set
test_guard_behavior() {
    local hook_path="$1"
    local hook_name="$(basename "$hook_path")"

    [[ ! -f "$hook_path" ]] && { log_skip "$hook_name - file not found"; return 0; }

    local input='{"cwd":"/tmp","prompt":"test","transcript_path":"/tmp/nonexistent.jsonl"}'
    local start_ms end_ms duration_ms

    start_ms=$(python3 -c 'import time; print(int(time.time() * 1000))')
    echo "$input" | LESSONS_SCORING_ACTIVE=1 timeout 2 bash "$hook_path" >/dev/null 2>&1 || true
    end_ms=$(python3 -c 'import time; print(int(time.time() * 1000))')
    duration_ms=$((end_ms - start_ms))

    if [[ $duration_ms -lt 200 ]]; then
        log_pass "$hook_name exits immediately with guard (${duration_ms}ms)"
    else
        log_fail "$hook_name took too long with guard set (${duration_ms}ms)"
    fi
}

# Test that claude -p calls have LESSONS_SCORING_ACTIVE in env
test_claude_call_has_guard() {
    local hook_path="$1"
    local hook_name="$(basename "$hook_path")"

    [[ ! -f "$hook_path" ]] && { log_skip "$hook_name - file not found"; return 0; }

    if ! grep -q "claude -p" "$hook_path"; then
        log_skip "$hook_name doesn't call claude -p"
        return 0
    fi

    if grep -E "LESSONS_SCORING_ACTIVE=1.*(claude -p|timeout.*claude)" "$hook_path" >/dev/null; then
        log_pass "$hook_name sets LESSONS_SCORING_ACTIVE before claude -p"
    else
        log_fail "$hook_name calls claude -p without setting LESSONS_SCORING_ACTIVE"
    fi
}

echo "=== Testing Hook Guards (Recursion Prevention) ==="
echo ""

echo "--- 1. Guard Line Present ---"
test_has_guard_line "$HOOKS_DIR/inject-hook.sh"
test_has_guard_line "$HOOKS_DIR/smart-inject-hook.sh"
test_has_guard_line "$HOOKS_DIR/capture-hook.sh"
test_has_guard_line "$HOOKS_DIR/stop-hook.sh"
test_has_guard_line "$HOOKS_DIR/session-end-hook.sh"
test_has_guard_line "$HOOKS_DIR/precompact-hook.sh"
test_has_guard_line "$CORE_DIR/lesson-reminder-hook.sh"
echo ""

echo "--- 2. Guard Behavior (hooks exit immediately) ---"
test_guard_behavior "$HOOKS_DIR/inject-hook.sh"
test_guard_behavior "$HOOKS_DIR/smart-inject-hook.sh"
test_guard_behavior "$HOOKS_DIR/capture-hook.sh"
test_guard_behavior "$HOOKS_DIR/stop-hook.sh"
test_guard_behavior "$HOOKS_DIR/session-end-hook.sh"
test_guard_behavior "$HOOKS_DIR/precompact-hook.sh"
test_guard_behavior "$CORE_DIR/lesson-reminder-hook.sh"
echo ""

echo "--- 3. Claude -p Calls Have Guard ---"
test_claude_call_has_guard "$HOOKS_DIR/session-end-hook.sh"
test_claude_call_has_guard "$HOOKS_DIR/precompact-hook.sh"
test_claude_call_has_guard "$HOOKS_DIR/smart-inject-hook.sh"
echo ""

echo "=== Summary ==="
echo -e "Passed: ${GREEN}$passed${NC}"
echo -e "Failed: ${RED}$failed${NC}"
echo -e "Skipped: ${YELLOW}$skipped${NC}"

[[ $failed -eq 0 ]]
