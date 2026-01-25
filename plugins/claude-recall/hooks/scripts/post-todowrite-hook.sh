#!/bin/bash
# SPDX-License-Identifier: MIT
# Claude Recall PostToolUse:TodoWrite hook - syncs todos to active handoff
#
# When Claude writes a todo list, this hook:
# 1. Extracts the todos from tool_input
# 2. Calls sync-todos to update the active handoff
# 3. Creates a new handoff if none exists AND there are 3+ todos

set -uo pipefail

# Source shared library
HOOK_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HOOK_LIB_DIR/hook-lib.sh"

# Check for recursion guard early
hook_lib_check_recursion

# Setup environment variables
setup_env

# Read JSON input from stdin
input=$(cat)
cwd=$(echo "$input" | jq -r '.cwd // empty')
todos=$(echo "$input" | jq -c '.tool_input.todos // []')

# Validate input
if [[ -z "$cwd" ]]; then
    log_debug "post-todowrite: no cwd in input"
    exit 0
fi

if [[ "$todos" == "[]" ]] || [[ -z "$todos" ]]; then
    log_debug "post-todowrite: no todos in input"
    exit 0
fi

# Check if enabled
if ! is_enabled; then
    exit 0
fi

log_debug "post-todowrite: syncing todos to handoff"

# Lookup handoff by session if available
session_id=$(echo "$input" | jq -r '.session_id // empty')
session_handoff=""

if [[ -n "$session_id" ]]; then
    session_handoff=$(PROJECT_DIR="$cwd" "$PYTHON_BIN" "$PYTHON_MANAGER" \
        handoff get-session-handoff "$session_id" 2>/dev/null || echo "")
fi

# Sync todos to active handoff (CLI handles 3+ threshold for auto-create)
# Pass session_handoff to sync-todos if found
if [[ -f "$PYTHON_MANAGER" ]]; then
    if [[ -n "$session_handoff" ]]; then
        PROJECT_DIR="$cwd" "$PYTHON_BIN" "$PYTHON_MANAGER" handoff sync-todos "$todos" \
            --session-handoff "$session_handoff" 2>/dev/null || {
            log_debug "post-todowrite: failed to sync todos"
        }
    else
        PROJECT_DIR="$cwd" "$PYTHON_BIN" "$PYTHON_MANAGER" handoff sync-todos "$todos" 2>/dev/null || {
            log_debug "post-todowrite: failed to sync todos"
        }
    fi
fi

exit 0
