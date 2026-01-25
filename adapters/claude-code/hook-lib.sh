#!/bin/bash
# SPDX-License-Identifier: MIT
# Claude Recall shared hook library - common functions for all hooks
#
# Usage: source this file at the top of hook scripts
#   source "$(dirname "${BASH_SOURCE[0]}")/hook-lib.sh"
#   setup_env
#
# Functions provided:
#   setup_env()         - Environment variable resolution + legacy exports
#   find_python_manager() - Locate core/cli.py with fallback chain
#   load_debug_level()  - Read from env > config.json > default
#   get_ms()            - Get current time in milliseconds
#   log_phase()         - Log timing for a phase
#   log_hook_end()      - Log total hook timing
#   find_project_root() - Git root detection
#   get_git_ref()       - Current git ref (short hash)
#   is_enabled()        - Check config.json for enabled flag

# Guard against double-sourcing
[[ -n "${HOOK_LIB_LOADED:-}" ]] && return 0
HOOK_LIB_LOADED=1

# Guard against recursive calls from Haiku subprocesses
# Export so child processes can inherit this check
# Returns 0 if NOT recursive (should continue), exits with 0 if recursive (should stop)
hook_lib_check_recursion() {
    if [[ -n "${LESSONS_SCORING_ACTIVE:-}" ]]; then
        exit 0
    fi
    return 0
}

# ============================================================
# ENVIRONMENT SETUP
# ============================================================

# Setup all environment variables with fallback chains
# Call this early in your hook's execution
setup_env() {
    # Support new (CLAUDE_RECALL_*), transitional (RECALL_*), and legacy (LESSONS_*) env vars
    CLAUDE_RECALL_BASE="${CLAUDE_RECALL_BASE:-${RECALL_BASE:-${LESSONS_BASE:-$HOME/.config/claude-recall}}}"
    CLAUDE_RECALL_STATE="${CLAUDE_RECALL_STATE:-${XDG_STATE_HOME:-$HOME/.local/state}/claude-recall}"

    # Load debug level (env var > config.json > default)
    load_debug_level

    # Export for downstream Python manager and child processes
    export CLAUDE_RECALL_BASE
    export CLAUDE_RECALL_STATE
    export CLAUDE_RECALL_DEBUG

    # Export legacy names for downstream compatibility
    LESSONS_BASE="$CLAUDE_RECALL_BASE"
    LESSONS_DEBUG="$CLAUDE_RECALL_DEBUG"
    export LESSONS_BASE
    export LESSONS_DEBUG

    # Locate Python manager
    find_python_manager

    # Legacy bash manager path (rarely used now)
    BASH_MANAGER="$CLAUDE_RECALL_BASE/lessons-manager.sh"
    export BASH_MANAGER
}

# Load debug level from env var, config.json, or default to "1"
load_debug_level() {
    local _env_debug="${CLAUDE_RECALL_DEBUG:-${RECALL_DEBUG:-${LESSONS_DEBUG:-}}}"
    local config_path="${CLAUDE_RECALL_CONFIG:-$HOME/.config/claude-recall/config.json}"

    if [[ -n "$_env_debug" ]]; then
        CLAUDE_RECALL_DEBUG="$_env_debug"
    elif [[ -f "$config_path" ]]; then
        local _settings_debug
        _settings_debug=$(jq -r '.debugLevel // empty' "$config_path" 2>/dev/null || true)
        CLAUDE_RECALL_DEBUG="${_settings_debug:-1}"
    else
        CLAUDE_RECALL_DEBUG="1"
    fi
}

# Find Python manager with fallback chain:
# 1. Installed location: $CLAUDE_RECALL_BASE/core/cli.py
# 2. Legacy flat structure: $CLAUDE_RECALL_BASE/cli.py
# 3. Dev location: relative to this script's directory
#
# Also sets PYTHON_BIN to venv python if available (for anthropic support)
find_python_manager() {
    local base_dir=""
    if [[ -f "$CLAUDE_RECALL_BASE/core/cli.py" ]]; then
        PYTHON_MANAGER="$CLAUDE_RECALL_BASE/core/cli.py"
        base_dir="$CLAUDE_RECALL_BASE"
    elif [[ -f "$CLAUDE_RECALL_BASE/cli.py" ]]; then
        PYTHON_MANAGER="$CLAUDE_RECALL_BASE/cli.py"  # Legacy flat structure
        base_dir="$CLAUDE_RECALL_BASE"
    else
        # Dev location - relative to hook-lib.sh (adapters/claude-code/)
        local script_dir
        script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
        PYTHON_MANAGER="$script_dir/../../core/cli.py"
        base_dir="$script_dir/../.."
    fi

    # Use venv python if available (has anthropic for trigger generation)
    if [[ -x "$base_dir/.venv/bin/python" ]]; then
        PYTHON_BIN="$base_dir/.venv/bin/python"
    else
        PYTHON_BIN="python3"
    fi

    export PYTHON_MANAGER PYTHON_BIN
}

# ============================================================
# SETTINGS HELPERS
# ============================================================

# Check if Claude Recall is enabled in config.json
# Returns 0 (true) if enabled, 1 (false) if disabled
is_enabled() {
    local config="${CLAUDE_RECALL_CONFIG:-$HOME/.config/claude-recall/config.json}"
    [[ -f "$config" ]] || return 0  # Enabled by default if no config

    # Note: jq // operator treats false as falsy, so we check explicitly
    local enabled
    enabled=$(jq -r '.enabled' "$config" 2>/dev/null)
    [[ "$enabled" != "false" ]]  # Enabled unless explicitly false
}

# Read a numeric setting with default
# Usage: get_setting "topLessonsToShow" 3
get_setting() {
    local key="$1"
    local default="$2"
    local config="${CLAUDE_RECALL_CONFIG:-$HOME/.config/claude-recall/config.json}"

    if [[ -f "$config" ]]; then
        jq -r ".$key // $default" "$config" 2>/dev/null || echo "$default"
    else
        echo "$default"
    fi
}

# ============================================================
# TIMING INFRASTRUCTURE
# ============================================================
# Uses platform-specific methods for millisecond precision timing.
# Linux: date +%s%3N (native)
# macOS: perl Time::HiRes (always available, fast)

# Detect timing method once at source time
if date +%s%3N >/dev/null 2>&1 && [[ "$(date +%s%3N)" =~ ^[0-9]+$ ]]; then
    _get_ms_now() { date +%s%3N; }
else
    _get_ms_now() { perl -MTime::HiRes -e 'printf("%.0f\n",Time::HiRes::time()*1000)'; }
fi

HOOK_START_MS=""

# Get current time in milliseconds
get_ms() {
    _get_ms_now
}

# Initialize timing state
init_timing() {
    HOOK_START_MS=$(_get_ms_now)
    PHASE_TIMES_JSON="{}"
    export HOOK_START_MS
}

# Get elapsed milliseconds since init_timing
get_elapsed_ms() {
    local now=$(_get_ms_now)
    echo "$((now - HOOK_START_MS))"
}

# Log timing for a named phase
# Usage:
#   local phase_start=$(get_elapsed_ms)
#   ... do work ...
#   log_phase "phase_name" "$phase_start"
log_phase() {
    local phase="$1"
    local start_elapsed="$2"
    local hook_name="${3:-hook}"

    # Skip if debug disabled (level 0)
    [[ "${CLAUDE_RECALL_DEBUG:-0}" -lt 1 ]] && return 0

    local end_elapsed=$(get_elapsed_ms)
    local duration=$((end_elapsed - start_elapsed))

    # Add to phase times JSON
    if [[ "$PHASE_TIMES_JSON" == "{}" ]]; then
        PHASE_TIMES_JSON="{\"$phase\":$duration}"
    else
        PHASE_TIMES_JSON="${PHASE_TIMES_JSON%\}},\"$phase\":$duration}"
    fi

    # Background the debug logging
    if [[ -n "$PYTHON_MANAGER" && -f "$PYTHON_MANAGER" ]]; then
        PROJECT_DIR="${PROJECT_DIR:-$(pwd)}" "$PYTHON_BIN" "$PYTHON_MANAGER" debug hook-phase "$hook_name" "$phase" "$duration" 2>/dev/null &
    fi
}

# Log total hook duration and all phase timings
# Usage: log_hook_end "hook_name"
log_hook_end() {
    local hook_name="${1:-hook}"

    # Skip if debug level < 1 (hook_end provides total timing even at level 1)
    [[ "${CLAUDE_RECALL_DEBUG:-0}" -lt 1 ]] && return 0

    local total_ms=$(get_elapsed_ms)

    if [[ -n "$PYTHON_MANAGER" && -f "$PYTHON_MANAGER" ]]; then
        # Pass phases as --phases if available (CLI expects named arg, not positional)
        if [[ -n "$PHASE_TIMES_JSON" && "$PHASE_TIMES_JSON" != "{}" ]]; then
            PROJECT_DIR="${PROJECT_DIR:-$(pwd)}" "$PYTHON_BIN" "$PYTHON_MANAGER" debug hook-end "$hook_name" "$total_ms" --phases "$PHASE_TIMES_JSON" 2>/dev/null &
        else
            PROJECT_DIR="${PROJECT_DIR:-$(pwd)}" "$PYTHON_BIN" "$PYTHON_MANAGER" debug hook-end "$hook_name" "$total_ms" 2>/dev/null &
        fi
    fi
}

# ============================================================
# PROJECT/GIT HELPERS
# ============================================================

# Find git root by walking up from a directory
# Falls back to the input directory if no git root found
# Usage: project_root=$(find_project_root "$cwd")
find_project_root() {
    local dir="${1:-$(pwd)}"
    while [[ "$dir" != "/" ]]; do
        [[ -d "$dir/.git" ]] && { echo "$dir"; return 0; }
        dir=$(dirname "$dir")
    done
    echo "$1"  # Fall back to input if no git root
}

# Get current git commit hash (short form)
# Returns empty string if not a git repo or git fails
# Usage: git_ref=$(get_git_ref "$project_root")
get_git_ref() {
    local project_root="$1"
    git -C "$project_root" rev-parse --short HEAD 2>/dev/null || echo ""
}

# ============================================================
# INPUT HELPERS
# ============================================================

# Sanitize input for safe shell usage
# Removes control characters, limits length, trims whitespace
# Usage: clean=$(sanitize_input "$raw" 500)
sanitize_input() {
    local input="$1"
    local max_length="${2:-500}"

    # Remove control characters (keep printable ASCII and spaces)
    input=$(printf '%s' "$input" | tr -cd '[:print:][:space:]' | tr -s ' ')

    # Truncate to max length
    input="${input:0:$max_length}"

    # Trim leading/trailing whitespace without xargs (pure bash)
    input="${input#"${input%%[![:space:]]*}"}"
    input="${input%"${input##*[![:space:]]}"}"

    printf '%s' "$input"
}

# ============================================================
# DEBUG HELPERS
# ============================================================

# Log a debug message (only if debug level >= 2)
# Usage: log_debug "post-todowrite: no cwd in input"
log_debug() {
    local message="$1"
    if [[ "${CLAUDE_RECALL_DEBUG:-0}" -ge 2 ]] && [[ -f "$PYTHON_MANAGER" ]]; then
        PROJECT_DIR="${PROJECT_DIR:-$(pwd)}" "$PYTHON_BIN" "$PYTHON_MANAGER" debug log "$message" 2>/dev/null || true
    fi
}
