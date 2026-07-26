#!/bin/bash
# SPDX-License-Identifier: MIT
# run-all-tests.sh - Run the bash test suites.
#
# The primary suite is ./run-tests.sh at the repo root (pytest + TypeScript).
# This runner covers the shell-level suites, which exercise the CLI wrapper,
# the installer, and the hook scripts end to end.
#
# Suites are grouped by whether they currently pass. LEGACY_SUITES were written
# against the Python CLI that the Go rewrite replaced; they still assert
# Python-era output formats and fail on assertion mismatches, not on missing
# functionality. They run only with --legacy so this runner stays a usable
# signal instead of permanently red.
#
# Usage:
#   run-all-tests.sh            # current suites
#   run-all-tests.sh --legacy   # also run the pre-Go-rewrite suites

set -uo pipefail   # deliberately not -e: a failing suite must not abort the run

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

CURRENT_SUITES=(
    test-install.sh
)

# Suites written against interfaces that later changed. Each fails on stale
# expectations, not missing functionality, so they are quarantined rather than
# deleted - the coverage is worth porting, and pytest already covers the same
# code paths against current behavior.
#
#   test-lessons-manager.sh  asserts Python-CLI output formats (pre-Go-rewrite)
#   test-velocity.sh         same, via core/lessons-manager.sh
#   test-stop-hook.sh        expects ~/.config/claude-recall/.citation-state
#                            (pre-XDG; state now lives in ~/.local/state)
#   test-hook-guards.sh      expects APPROACHES.md (renamed to HANDOFFS.md)
LEGACY_SUITES=(
    test-lessons-manager.sh
    test-velocity.sh
    test-stop-hook.sh
    test-hook-guards.sh
)

run_legacy=0
[[ "${1:-}" == "--legacy" ]] && run_legacy=1

# These suites override HOME, so hooks cannot find the installed binary under
# $HOME/.local/bin. Point them at a local build when one exists; otherwise the
# hooks degrade to their skip path and the suites assert against that instead of
# real behavior. Build with: cd go && go build -o bin/recall ./cmd/...
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
[[ -x "$REPO_ROOT/go/bin/recall" ]] && export CLAUDE_RECALL_BIN="$REPO_ROOT/go/bin/recall"
[[ -x "$REPO_ROOT/go/bin/recall-hook" ]] && export CLAUDE_RECALL_HOOK_BIN="$REPO_ROOT/go/bin/recall-hook"

suites=("${CURRENT_SUITES[@]}")
if [[ $run_legacy -eq 1 ]]; then
    suites+=("${LEGACY_SUITES[@]}")
fi

echo ""
echo "========================================"
echo "  Claude Recall - Shell Test Runner"
echo "========================================"

failed=0
declare -a failed_names=()

for suite in "${suites[@]}"; do
    path="$SCRIPT_DIR/$suite"
    if [[ ! -f "$path" ]]; then
        echo -e "${RED}Missing suite: $suite${NC}"
        failed=1
        failed_names+=("$suite (missing)")
        continue
    fi
    echo ""
    echo -e "${YELLOW}Running $suite...${NC}"
    if ! bash "$path"; then
        failed=1
        failed_names+=("$suite")
    fi
done

echo ""
echo "========================================"
if [[ $failed -eq 0 ]]; then
    echo -e "${GREEN}All shell suites passed!${NC}"
else
    echo -e "${RED}Failed suites:${NC}"
    for name in "${failed_names[@]}"; do
        echo -e "  ${RED}- $name${NC}"
    done
fi

if [[ $run_legacy -eq 0 ]]; then
    echo ""
    echo "Skipped ${#LEGACY_SUITES[@]} legacy suite(s); re-run with --legacy to include them."
fi

exit $failed
