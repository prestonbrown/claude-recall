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
    [[ -f "$config" ]] || return 0  # Enabled by default if no config
    # Note: jq // operator treats false as falsy, so we check explicitly
    local enabled=$(jq -r '.claudeRecall.enabled' "$config" 2>/dev/null)
    [[ "$enabled" != "false" ]]  # Enabled unless explicitly false
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
project_name=$(basename "$project_root")

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

# Validate plan belongs to current project by checking file references
# Plans often reference project files - if those files don't exist here, skip
plan_content=$(cat "$plan_file" 2>/dev/null)
plan_has_file_refs=false
plan_matches_project=false

# Look for file path patterns in the plan (e.g., src/foo.ts, ./bar.py, core/baz.py)
# Extract potential file paths and check if any exist in current project
while IFS= read -r potential_path; do
    [[ -z "$potential_path" ]] && continue
    plan_has_file_refs=true
    # Check if file exists relative to project root
    if [[ -f "$project_root/$potential_path" ]]; then
        plan_matches_project=true
        break
    fi
done < <(echo "$plan_content" | grep -oE '(src|lib|core|app|tests?|pkg|cmd)/[a-zA-Z0-9_./-]+\.[a-zA-Z]+' | head -10)

# If plan has file references but none match this project, skip it
if $plan_has_file_refs && ! $plan_matches_project; then
    log_debug "post-exitplanmode: plan '$plan_file' has file refs but none exist in $project_name - skipping (likely wrong project)"
    exit 0
fi

# Log when we can't validate (no file refs detected)
if ! $plan_has_file_refs; then
    log_debug "post-exitplanmode: plan '$plan_file' has no detectable file refs - proceeding without validation"
fi

# Extract title from first # heading
# Supports "# Plan: Title" or just "# Title"
title=$(grep -m1 '^# ' "$plan_file" 2>/dev/null | sed 's/^# Plan: //; s/^# //')
if [[ -z "$title" ]]; then
    log_debug "post-exitplanmode: no title found in $plan_file"
    exit 0
fi

log_debug "post-exitplanmode: creating handoff from plan '$title'"

# Create handoff with phase=implementing and capture output
if [[ -f "$PYTHON_MANAGER" ]]; then
    output=$(PROJECT_DIR="$project_root" python3 "$PYTHON_MANAGER" handoff add "$title" --phase implementing --files "$plan_file" 2>&1) || {
        log_debug "post-exitplanmode: failed to create handoff"
        exit 0
    }

    # Parse handoff ID from output (format: "Added handoff hf-xxxxxxx: Title")
    handoff_id=$(echo "$output" | grep -oE 'hf-[0-9a-f]{7}' | head -1)

    if [[ -n "$handoff_id" ]]; then
        # Extract session_id and store session -> handoff mapping
        session_id=$(echo "$input" | jq -r '.session_id // empty')
        if [[ -n "$session_id" ]]; then
            PROJECT_DIR="$project_root" python3 "$PYTHON_MANAGER" \
                handoff set-session "$handoff_id" "$session_id" 2>/dev/null || true
        fi

        # Output explicit, actionable message for the agent
        cat <<EOF

════════════════════════════════════════════════════════════════
HANDOFF CREATED: $handoff_id
Title: $title

For continuation in a new session, include:
  "Continue handoff $handoff_id: $title"

The next session will auto-inject this handoff's context.
════════════════════════════════════════════════════════════════

EOF
    fi
fi

exit 0
