#!/bin/bash
# SPDX-License-Identifier: MIT
# Claude Recall PostToolUse:TodoWrite hook - syncs todos to active handoff
#
# When Claude writes a todo list, this hook:
# 1. Extracts the todos from tool_input
# 2. Calls sync-todos to update the active handoff
# 3. Creates a new handoff if none exists AND there are 3+ todos

set -uo pipefail

# Guard against recursive calls
[[ -n "${LESSONS_SCORING_ACTIVE:-}" ]] && exit 0

# Support new (CLAUDE_RECALL_*), transitional (RECALL_*), and legacy (LESSONS_*) env vars
CLAUDE_RECALL_BASE="${CLAUDE_RECALL_BASE:-${RECALL_BASE:-${LESSONS_BASE:-$HOME/.config/claude-recall}}}"
CLAUDE_RECALL_STATE="${CLAUDE_RECALL_STATE:-${XDG_STATE_HOME:-$HOME/.local/state}/claude-recall}"
# Debug level: env var > settings.json > default (1)
_env_debug="${CLAUDE_RECALL_DEBUG:-${RECALL_DEBUG:-${LESSONS_DEBUG:-}}}"
if [[ -n "$_env_debug" ]]; then
    CLAUDE_RECALL_DEBUG="$_env_debug"
elif [[ -f "$HOME/.claude/settings.json" ]]; then
    _settings_debug=$(jq -r '.claudeRecall.debugLevel // empty' "$HOME/.claude/settings.json" 2>/dev/null || true)
    CLAUDE_RECALL_DEBUG="${_settings_debug:-1}"
else
    CLAUDE_RECALL_DEBUG="1"
fi
export CLAUDE_RECALL_STATE

# Python manager - try installed location first, fall back to dev location
if [[ -f "$CLAUDE_RECALL_BASE/cli.py" ]]; then
    PYTHON_MANAGER="$CLAUDE_RECALL_BASE/cli.py"
else
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    PYTHON_MANAGER="$SCRIPT_DIR/../../core/cli.py"
fi

is_enabled() {
    local config="$HOME/.claude/settings.json"
    [[ -f "$config" ]] || return 0  # Enabled by default if no config
    # Note: jq // operator treats false as falsy, so we check explicitly
    local enabled=$(jq -r '.claudeRecall.enabled' "$config" 2>/dev/null)
    [[ "$enabled" != "false" ]]  # Enabled unless explicitly false
}

log_debug() {
    if [[ "${CLAUDE_RECALL_DEBUG:-0}" -ge 2 ]] && [[ -f "$PYTHON_MANAGER" ]]; then
        PROJECT_DIR="${cwd:-$(pwd)}" python3 "$PYTHON_MANAGER" debug log "$1" 2>/dev/null || true
    fi
}

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
    session_handoff=$(PROJECT_DIR="$cwd" python3 "$PYTHON_MANAGER" \
        handoff get-session-handoff "$session_id" 2>/dev/null || echo "")
fi

# Sync todos to active handoff (CLI handles 3+ threshold for auto-create)
# Pass session_handoff to sync-todos if found
if [[ -f "$PYTHON_MANAGER" ]]; then
    if [[ -n "$session_handoff" ]]; then
        PROJECT_DIR="$cwd" python3 "$PYTHON_MANAGER" handoff sync-todos "$todos" \
            --session-handoff "$session_handoff" 2>/dev/null || {
            log_debug "post-todowrite: failed to sync todos"
        }
    else
        PROJECT_DIR="$cwd" python3 "$PYTHON_MANAGER" handoff sync-todos "$todos" 2>/dev/null || {
            log_debug "post-todowrite: failed to sync todos"
        }
    fi
fi

exit 0
