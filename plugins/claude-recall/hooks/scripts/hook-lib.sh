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
#   load_debug_level()  - Read from env > settings.json > default
#   get_ms()            - Get current time in milliseconds
#   log_phase()         - Log timing for a phase
#   log_hook_end()      - Log total hook timing
#   find_project_root() - Git root detection
#   get_git_ref()       - Current git ref (short hash)
#   is_enabled()        - Check settings.json for claudeRecall.enabled

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
    # Detect plugin install vs legacy install
    # CLAUDE_PLUGIN_ROOT is set by Claude Code when running hooks from a plugin
    if [[ -n "${CLAUDE_PLUGIN_ROOT:-}" ]]; then
        # Plugin install: use plugin directory for code, XDG state for data
        CLAUDE_RECALL_BASE="${CLAUDE_PLUGIN_ROOT}"
    else
        # Legacy install: ~/.config/claude-recall
        CLAUDE_RECALL_BASE="${CLAUDE_RECALL_BASE:-${RECALL_BASE:-${LESSONS_BASE:-$HOME/.config/claude-recall}}}"
    fi
    CLAUDE_RECALL_STATE="${CLAUDE_RECALL_STATE:-${XDG_STATE_HOME:-$HOME/.local/state}/claude-recall}"

    # Load debug level (env var > config.json > settings.json > default)
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

# Load debug level from env var, config.json, settings.json, or default to "1"
load_debug_level() {
    local _env_debug="${CLAUDE_RECALL_DEBUG:-${RECALL_DEBUG:-${LESSONS_DEBUG:-}}}"

    if [[ -n "$_env_debug" ]]; then
        CLAUDE_RECALL_DEBUG="$_env_debug"
        return
    fi

    # Try plugin config.json first (CLAUDE_PLUGIN_ROOT may not be set yet)
    local _config_file="${CLAUDE_PLUGIN_ROOT:-}/config.json"
    if [[ -n "${CLAUDE_PLUGIN_ROOT:-}" && -f "$_config_file" ]]; then
        local _config_debug
        _config_debug=$(jq -r '.debugLevel // empty' "$_config_file" 2>/dev/null || true)
        if [[ -n "$_config_debug" ]]; then
            CLAUDE_RECALL_DEBUG="$_config_debug"
            return
        fi
    fi

    # Try legacy config location
    local _legacy_config="$HOME/.config/claude-recall/config.json"
    if [[ -f "$_legacy_config" ]]; then
        local _legacy_debug
        _legacy_debug=$(jq -r '.debugLevel // empty' "$_legacy_config" 2>/dev/null || true)
        if [[ -n "$_legacy_debug" ]]; then
            CLAUDE_RECALL_DEBUG="$_legacy_debug"
            return
        fi
    fi

    # Fall back to settings.json (for migration)
    if [[ -f "$HOME/.claude/settings.json" ]]; then
        local _settings_debug
        _settings_debug=$(jq -r '.claudeRecall.debugLevel // empty' "$HOME/.claude/settings.json" 2>/dev/null || true)
        CLAUDE_RECALL_DEBUG="${_settings_debug:-1}"
    else
        CLAUDE_RECALL_DEBUG="1"
    fi
}

# Find Python manager with fallback chain:
# 1. Plugin location: $CLAUDE_PLUGIN_ROOT/core/cli.py
# 2. Installed location: $CLAUDE_RECALL_BASE/core/cli.py
# 3. Legacy flat structure: $CLAUDE_RECALL_BASE/cli.py
# 4. Dev location: relative to this script's directory
find_python_manager() {
    if [[ -n "${CLAUDE_PLUGIN_ROOT:-}" && -f "${CLAUDE_PLUGIN_ROOT}/core/cli.py" ]]; then
        PYTHON_MANAGER="${CLAUDE_PLUGIN_ROOT}/core/cli.py"
    elif [[ -f "$CLAUDE_RECALL_BASE/core/cli.py" ]]; then
        PYTHON_MANAGER="$CLAUDE_RECALL_BASE/core/cli.py"
    elif [[ -f "$CLAUDE_RECALL_BASE/cli.py" ]]; then
        PYTHON_MANAGER="$CLAUDE_RECALL_BASE/cli.py"  # Legacy flat structure
    else
        # Dev location - relative to hook-lib.sh (plugin/hooks/scripts/)
        local script_dir
        script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
        PYTHON_MANAGER="$script_dir/../../core/cli.py"
    fi
    export PYTHON_MANAGER
}

# ============================================================
# SETTINGS HELPERS
# ============================================================

# Get the config file path (plugin config > legacy config)
get_config_file() {
    if [[ -n "${CLAUDE_PLUGIN_ROOT:-}" && -f "${CLAUDE_PLUGIN_ROOT}/config.json" ]]; then
        echo "${CLAUDE_PLUGIN_ROOT}/config.json"
    elif [[ -f "$HOME/.config/claude-recall/config.json" ]]; then
        echo "$HOME/.config/claude-recall/config.json"
    else
        echo ""
    fi
}

# Check if Claude Recall is enabled in settings
# Returns 0 (true) if enabled, 1 (false) if disabled
is_enabled() {
    # Try plugin/legacy config.json first
    local config_file
    config_file=$(get_config_file)
    if [[ -n "$config_file" ]]; then
        local enabled
        enabled=$(jq -r '.enabled' "$config_file" 2>/dev/null)
        [[ "$enabled" != "false" ]]  # Enabled unless explicitly false
        return
    fi

    # Fall back to settings.json for migration
    local settings="$HOME/.claude/settings.json"
    if [[ -f "$settings" ]]; then
        local enabled
        enabled=$(jq -r '.claudeRecall.enabled' "$settings" 2>/dev/null)
        [[ "$enabled" != "false" ]]  # Enabled unless explicitly false
    else
        return 0  # Enabled by default
    fi
}

# Read a setting with default
# Priority: plugin config.json > legacy config.json > settings.json > default
# Usage: get_setting "topLessonsToShow" 3
get_setting() {
    local key="$1"
    local default="$2"

    # Try plugin/legacy config.json first
    local config_file
    config_file=$(get_config_file)
    if [[ -n "$config_file" ]]; then
        local value
        value=$(jq -r ".$key // empty" "$config_file" 2>/dev/null)
        if [[ -n "$value" ]]; then
            echo "$value"
            return
        fi
    fi

    # Fall back to settings.json for migration
    local settings="$HOME/.claude/settings.json"
    if [[ -f "$settings" ]]; then
        local value
        value=$(jq -r ".claudeRecall.$key // empty" "$settings" 2>/dev/null)
        if [[ -n "$value" ]]; then
            echo "$value"
            return
        fi
    fi

    echo "$default"
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

    # Skip if debug level < 2 (no timing overhead in production)
    [[ "${CLAUDE_RECALL_DEBUG:-0}" -lt 2 ]] && return 0

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
        PROJECT_DIR="${PROJECT_DIR:-$(pwd)}" python3 "$PYTHON_MANAGER" debug hook-phase "$hook_name" "$phase" "$duration" 2>/dev/null &
    fi
}

# Log total hook duration and all phase timings
# Usage: log_hook_end "hook_name"
log_hook_end() {
    local hook_name="${1:-hook}"

    # Skip if debug level < 2 (no timing overhead in production)
    [[ "${CLAUDE_RECALL_DEBUG:-0}" -lt 2 ]] && return 0

    local total_ms=$(get_elapsed_ms)

    if [[ -n "$PYTHON_MANAGER" && -f "$PYTHON_MANAGER" ]]; then
        PROJECT_DIR="${PROJECT_DIR:-$(pwd)}" python3 "$PYTHON_MANAGER" debug hook-end "$hook_name" "$total_ms" "$PHASE_TIMES_JSON" 2>/dev/null &
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
        PROJECT_DIR="${PROJECT_DIR:-$(pwd)}" python3 "$PYTHON_MANAGER" debug log "$message" 2>/dev/null || true
    fi
}
