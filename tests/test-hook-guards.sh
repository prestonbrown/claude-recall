#!/bin/bash
# SPDX-License-Identifier: MIT
# Test that all hooks refuse to run recursively.
#
# Hooks may spawn `claude -p` subprocesses, whose own hooks would spawn more.
# LESSONS_SCORING_ACTIVE is the cutoff: every hook must exit as soon as it sees
# that variable set. Most hooks delegate the check to hook_lib_check_recursion
# in hook-lib.sh rather than inlining it, so the guard is accepted in either
# form - and hook-lib.sh's implementation is itself exercised below, otherwise
# the indirection would let a no-op function pass.
#
# Hooks are discovered rather than listed. A hardcoded list silently stops
# covering anything that moves, which is how this suite ended up asserting
# against paths that no longer existed.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Hooks live with the plugin. adapters/claude-code is the older layout, kept as
# symlinks into this directory - checking it too would only re-check the same
# files, so it gets a layout assertion instead (section 4).
HOOK_DIRS=(
    "$REPO_ROOT/plugins/claude-recall/hooks/scripts"
)
ADAPTER_DIR="$REPO_ROOT/adapters/claude-code"

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

# Label a hook by the directory it came from - the same basename exists in both
# layouts, and a failure needs to say which copy is broken.
hook_label() {
    local hook_path="$1"
    echo "$(basename "$(dirname "$hook_path")")/$(basename "$hook_path")"
}

# Collect every hook script under HOOK_DIRS. hook-lib.sh is not a hook and is
# excluded by the *-hook.sh pattern.
discover_hooks() {
    local dir
    for dir in "${HOOK_DIRS[@]}"; do
        [[ -d "$dir" ]] || continue
        find "$dir" -maxdepth 1 -name '*-hook.sh' -type f | sort
    done
}

# hook-lib.sh's guard must actually exit, in both directions
test_hook_lib_guard() {
    local lib="$1"
    local label="$(hook_label "$lib")"

    [[ -f "$lib" ]] && grep -q 'hook_lib_check_recursion' "$lib" || {
        log_skip "$label - no hook_lib_check_recursion"
        return 0
    }

    local guarded unguarded
    guarded=$(LESSONS_SCORING_ACTIVE=1 bash -c 'source "$1"; hook_lib_check_recursion; echo REACHED' _ "$lib" 2>/dev/null || true)
    unguarded=$(bash -c 'source "$1"; hook_lib_check_recursion; echo REACHED' _ "$lib" 2>/dev/null || true)

    if [[ "$guarded" == *REACHED* ]]; then
        log_fail "$label hook_lib_check_recursion does not exit when LESSONS_SCORING_ACTIVE is set"
    elif [[ "$unguarded" != *REACHED* ]]; then
        log_fail "$label hook_lib_check_recursion exits even when LESSONS_SCORING_ACTIVE is unset"
    else
        log_pass "$label hook_lib_check_recursion exits only under the guard"
    fi
}

# Test that hook has guard at the top - inline, or delegated to hook-lib.sh
test_has_guard_line() {
    local hook_path="$1"
    local hook_name="$(hook_label "$hook_path")"

    [[ ! -f "$hook_path" ]] && { log_skip "$hook_name - file not found"; return 0; }

    if head -20 "$hook_path" | grep -qE 'LESSONS_SCORING_ACTIVE.*exit 0|hook_lib_check_recursion'; then
        log_pass "$hook_name has guard at top"
    else
        log_fail "$hook_name missing guard at top of file"
    fi
}

# Test that hook exits immediately when guard is set
test_guard_behavior() {
    local hook_path="$1"
    local hook_name="$(hook_label "$hook_path")"

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

# The adapter directory must stay a symlink farm. A real file there is a second
# copy of a hook that discovery never sees, so it would go unguarded silently.
test_adapter_is_symlink() {
    local path="$1"
    local name="$(hook_label "$path")"
    local target

    if [[ ! -L "$path" ]]; then
        log_fail "$name is a real file, not a symlink into the plugin hooks dir - it escapes guard checks"
        return 0
    fi

    target="$(cd "$(dirname "$path")" && cd "$(dirname "$(readlink "$path")")" && pwd)"
    if [[ "$target" == "${HOOK_DIRS[0]}" ]]; then
        log_pass "$name links into the plugin hooks dir"
    else
        log_fail "$name links to $target, outside the plugin hooks dir"
    fi
}

# Test that claude -p calls have LESSONS_SCORING_ACTIVE in env
test_claude_call_has_guard() {
    local hook_path="$1"
    local hook_name="$(hook_label "$hook_path")"

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

# Built with a read loop, not mapfile: macOS ships bash 3.2
HOOKS=()
while IFS= read -r hook; do
    [[ -n "$hook" ]] && HOOKS+=("$hook")
done < <(discover_hooks)

# An empty run reports "all green" while covering nothing - the failure mode
# this suite is meant to catch.
if [[ ${#HOOKS[@]} -eq 0 ]]; then
    echo -e "${RED}✗${NC} no hook scripts found under: ${HOOK_DIRS[*]}"
    exit 1
fi
echo "Discovered ${#HOOKS[@]} hook scripts"
echo ""

echo "--- 0. hook-lib.sh Guard Implementation ---"
for dir in "${HOOK_DIRS[@]}"; do
    [[ -f "$dir/hook-lib.sh" ]] && test_hook_lib_guard "$dir/hook-lib.sh"
done
echo ""

echo "--- 1. Guard Line Present ---"
for hook in "${HOOKS[@]}"; do
    test_has_guard_line "$hook"
done
echo ""

echo "--- 2. Guard Behavior (hooks exit immediately) ---"
for hook in "${HOOKS[@]}"; do
    test_guard_behavior "$hook"
done
echo ""

echo "--- 3. Claude -p Calls Have Guard ---"
for hook in "${HOOKS[@]}"; do
    test_claude_call_has_guard "$hook"
done
echo ""

echo "--- 4. Adapter Layout (no unchecked second copies) ---"
if [[ -d "$ADAPTER_DIR" ]]; then
    while IFS= read -r entry; do
        [[ -n "$entry" ]] && test_adapter_is_symlink "$entry"
    done < <(find "$ADAPTER_DIR" -maxdepth 1 \( -name '*-hook.sh' -o -name 'hook-lib.sh' \) | sort)
else
    log_skip "adapters/claude-code - directory not present"
fi
echo ""

echo "=== Summary ==="
echo -e "Passed: ${GREEN}$passed${NC}"
echo -e "Failed: ${RED}$failed${NC}"
echo -e "Skipped: ${YELLOW}$skipped${NC}"

[[ $failed -eq 0 ]]
