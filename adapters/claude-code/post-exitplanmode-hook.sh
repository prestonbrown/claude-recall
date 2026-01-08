#!/bin/bash
# SPDX-License-Identifier: MIT
# Claude Recall PostToolUse:ExitPlanMode hook - creates handoff from plan file
#
# When user approves a plan and exits plan mode, this hook:
# 1. Finds the most recent plan file in .claude/plans/
# 2. Extracts the title from the first # heading
# 3. Creates a handoff with phase=implementing

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
    [[ -f "$config" ]] && {
        local enabled=$(jq -r '.claudeRecall.enabled // true' "$config" 2>/dev/null || echo "true")
        [[ "$enabled" != "false" ]]
    }
}

find_project_root() {
    local dir="${1:-$(pwd)}"
    while [[ "$dir" != "/" ]]; do
        [[ -d "$dir/.git" ]] && { echo "$dir"; return 0; }
        dir=$(dirname "$dir")
    done
    echo "$1"
}

log_debug() {
    if [[ "${CLAUDE_RECALL_DEBUG:-0}" -ge 2 ]] && [[ -f "$PYTHON_MANAGER" ]]; then
        PROJECT_DIR="${project_root:-${cwd:-$(pwd)}}" python3 "$PYTHON_MANAGER" debug log "$1" 2>/dev/null || true
    fi
}

# Read JSON input from stdin
input=$(cat)
cwd=$(echo "$input" | jq -r '.cwd // empty')

# Validate cwd
if [[ -z "$cwd" ]]; then
    log_debug "post-exitplanmode: no cwd in input"
    exit 0
fi

# Find actual project root (walk up to .git)
project_root=$(find_project_root "$cwd")

# Check if enabled
if ! is_enabled; then
    exit 0
fi

# Find most recent plan file by modification time
# Plans are stored globally in ~/.claude/plans/, not per-project
plans_dir="$HOME/.claude/plans"
if [[ ! -d "$plans_dir" ]]; then
    log_debug "post-exitplanmode: no plans directory at $plans_dir"
    exit 0
fi

# Use ls -t to sort by modification time (most recent first)
plan_file=$(ls -t "$plans_dir"/*.md 2>/dev/null | head -1)
if [[ -z "$plan_file" ]]; then
    log_debug "post-exitplanmode: no plan files found in $plans_dir"
    exit 0
fi

# Extract title from first # heading
# Supports "# Plan: Title" or just "# Title"
title=$(grep -m1 '^# ' "$plan_file" 2>/dev/null | sed 's/^# Plan: //; s/^# //')
if [[ -z "$title" ]]; then
    log_debug "post-exitplanmode: no title found in $plan_file"
    exit 0
fi

log_debug "post-exitplanmode: creating handoff from plan '$title'"

# Create handoff with phase=implementing
if [[ -f "$PYTHON_MANAGER" ]]; then
    PROJECT_DIR="$project_root" python3 "$PYTHON_MANAGER" approach add "$title" --phase implementing 2>/dev/null || {
        log_debug "post-exitplanmode: failed to create handoff"
    }
fi

exit 0
