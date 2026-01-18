#!/bin/bash
# SPDX-License-Identifier: MIT
# install.sh - Install Claude Recall for Claude Code, OpenCode, or both
#
# Usage:
#   ./install.sh              # Auto-detect and install for available tools
#   ./install.sh --claude     # Install Claude Code adapter only
#   ./install.sh --opencode   # Install OpenCode adapter only
#   ./install.sh --migrate    # Migrate from old config locations
#   ./install.sh --uninstall  # Remove the system

set -euo pipefail

# Paths
CLAUDE_RECALL_BASE="${CLAUDE_RECALL_BASE:-$HOME/.config/claude-recall}"
CLAUDE_RECALL_STATE="${CLAUDE_RECALL_STATE:-${XDG_STATE_HOME:-$HOME/.local/state}/claude-recall}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Old paths for migration
OLD_SYSTEM_PATHS=(
    "$HOME/.config/coding-agent-lessons"
    "$HOME/.config/recall"
)
OLD_PROJECT_DIRS=(
    ".coding-agent-lessons"
    ".recall"
)

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

check_deps() {
    local missing=()
    command -v jq >/dev/null 2>&1 || missing+=("jq")
    command -v bash >/dev/null 2>&1 || missing+=("bash")
    
    if (( ${#missing[@]} > 0 )); then
        log_error "Missing dependencies: ${missing[*]}"
        echo "Install with: brew install ${missing[*]} (macOS) or apt install ${missing[*]} (Linux)"
        exit 1
    fi
}

detect_tools() {
    local tools=()
    [[ -d "$HOME/.claude" ]] && tools+=("claude")
    command -v opencode >/dev/null 2>&1 && tools+=("opencode")
    [[ -d "$HOME/.config/opencode" ]] && tools+=("opencode")
    printf '%s\n' "${tools[@]}" | sort -u
}

find_project_root() {
    local dir="${1:-$(pwd)}"
    while [[ "$dir" != "/" ]]; do
        [[ -d "$dir/.git" ]] && { echo "$dir"; return 0; }
        dir=$(dirname "$dir")
    done
    echo "$1"
}

# Migrate config from old locations to new Claude Recall locations
migrate_config() {
    log_info "Checking for config migration..."

    local migrated=0

    # Migrate system config from old paths
    for old_path in "${OLD_SYSTEM_PATHS[@]}"; do
        if [[ -d "$old_path" && ! -d "$CLAUDE_RECALL_BASE" ]]; then
            log_info "Migrating $old_path to $CLAUDE_RECALL_BASE..."
            mv "$old_path" "$CLAUDE_RECALL_BASE"
            log_success "Migrated config from $old_path"
            ((migrated++))
            break
        fi
    done

    # Also check for very old ~/.claude/LESSONS.md location
    local old_claude_lessons="$HOME/.claude/LESSONS.md"
    local new_system="$CLAUDE_RECALL_BASE/LESSONS.md"

    if [[ -f "$old_claude_lessons" ]]; then
        mkdir -p "$CLAUDE_RECALL_BASE"
        if [[ -f "$new_system" ]]; then
            log_info "Merging $old_claude_lessons into $new_system..."
            cat "$old_claude_lessons" >> "$new_system"
            log_success "Merged system lessons"
        else
            cp "$old_claude_lessons" "$new_system"
            log_success "Migrated system lessons to $new_system"
        fi

        mv "$old_claude_lessons" "${old_claude_lessons}.migrated.$(date +%Y%m%d)"
        log_info "Old file backed up to ${old_claude_lessons}.migrated.*"
        ((migrated++))
    fi

    # Migrate project dirs
    local project_root=$(find_project_root "$(pwd)")
    local new_project_dir="$project_root/.claude-recall"

    for old_name in "${OLD_PROJECT_DIRS[@]}"; do
        local old_dir="$project_root/$old_name"
        if [[ -d "$old_dir" && ! -d "$new_project_dir" ]]; then
            log_info "Migrating $old_dir to $new_project_dir..."
            mv "$old_dir" "$new_project_dir"
            log_success "Migrated project data from $old_name"
            ((migrated++))
            break
        fi
    done

    # Also check for very old .claude/LESSONS.md in project
    local old_claude_project="$project_root/.claude/LESSONS.md"
    local new_project="$new_project_dir/LESSONS.md"

    if [[ -f "$old_claude_project" ]]; then
        mkdir -p "$new_project_dir"
        if [[ -f "$new_project" ]]; then
            log_info "Merging $old_claude_project into $new_project..."
            cat "$old_claude_project" >> "$new_project"
            log_success "Merged project lessons"
        else
            cp "$old_claude_project" "$new_project"
            log_success "Migrated project lessons to $new_project"
        fi

        mv "$old_claude_project" "${old_claude_project}.migrated.$(date +%Y%m%d)"
        log_info "Old file backed up to ${old_claude_project}.migrated.*"
        ((migrated++))

        # Clean up empty .claude directory if it only had LESSONS.md
        if [[ -d "$project_root/.claude" ]]; then
            local remaining=$(ls -A "$project_root/.claude" 2>/dev/null | grep -v "\.migrated\." | wc -l)
            if (( remaining == 0 )); then
                log_info "Removing empty $project_root/.claude/ directory"
                rm -rf "$project_root/.claude"
            fi
        fi
    fi

    # Clean up old hook files from previous installations
    if [[ -f "$HOME/.claude/hooks/lessons-manager.sh" ]]; then
        log_info "Found old Claude Code hooks, cleaning up..."
        rm -f "$HOME/.claude/hooks/lessons-manager.sh"
        rm -f "$HOME/.claude/hooks/lessons-inject-hook.sh"
        rm -f "$HOME/.claude/hooks/lessons-capture-hook.sh"
        rm -f "$HOME/.claude/hooks/lessons-stop-hook.sh"
        log_success "Removed old hook files"
        ((migrated++))
    fi

    if (( migrated == 0 )); then
        log_info "No old config found to migrate"
    else
        log_success "Migration complete: $migrated item(s) migrated"
    fi

    return 0
}

install_core() {
    log_info "Installing Claude Recall core..."
    mkdir -p "$CLAUDE_RECALL_BASE" "$CLAUDE_RECALL_BASE/plugins"
    mkdir -p "$CLAUDE_RECALL_STATE"  # XDG state dir for logs

    # Clean up old flat file structure (migrating to package structure)
    rm -f "$CLAUDE_RECALL_BASE/cli.py" "$CLAUDE_RECALL_BASE/manager.py"
    rm -f "$CLAUDE_RECALL_BASE/models.py" "$CLAUDE_RECALL_BASE/parsing.py"
    rm -f "$CLAUDE_RECALL_BASE/file_lock.py" "$CLAUDE_RECALL_BASE/lessons.py"
    rm -f "$CLAUDE_RECALL_BASE/handoffs.py" "$CLAUDE_RECALL_BASE/debug_logger.py"
    rm -f "$CLAUDE_RECALL_BASE/__init__.py" "$CLAUDE_RECALL_BASE/_version.py"
    rm -f "$CLAUDE_RECALL_BASE/context_extractor.py" "$CLAUDE_RECALL_BASE/lessons_manager.py"
    rm -rf "$CLAUDE_RECALL_BASE/tui" 2>/dev/null || true
    rm -rf "$CLAUDE_RECALL_BASE/__pycache__" 2>/dev/null || true

    # Copy shell scripts to base (they use relative paths)
    cp "$SCRIPT_DIR/core/lessons-manager.sh" "$CLAUDE_RECALL_BASE/"
    cp "$SCRIPT_DIR/core/lesson-reminder-hook.sh" "$CLAUDE_RECALL_BASE/"

    # Install Python as a proper package structure (core/)
    # This allows standard imports like "from core.models import X"
    mkdir -p "$CLAUDE_RECALL_BASE/core"
    cp "$SCRIPT_DIR/core/_version.py" "$CLAUDE_RECALL_BASE/core/"
    cp "$SCRIPT_DIR/core/cli.py" "$CLAUDE_RECALL_BASE/core/"
    cp "$SCRIPT_DIR/core/manager.py" "$CLAUDE_RECALL_BASE/core/"
    cp "$SCRIPT_DIR/core/models.py" "$CLAUDE_RECALL_BASE/core/"
    cp "$SCRIPT_DIR/core/parsing.py" "$CLAUDE_RECALL_BASE/core/"
    cp "$SCRIPT_DIR/core/file_lock.py" "$CLAUDE_RECALL_BASE/core/"
    cp "$SCRIPT_DIR/core/lessons.py" "$CLAUDE_RECALL_BASE/core/"
    cp "$SCRIPT_DIR/core/handoffs.py" "$CLAUDE_RECALL_BASE/core/"
    cp "$SCRIPT_DIR/core/debug_logger.py" "$CLAUDE_RECALL_BASE/core/"
    cp "$SCRIPT_DIR/core/context_extractor.py" "$CLAUDE_RECALL_BASE/core/"
    cp "$SCRIPT_DIR/core/__init__.py" "$CLAUDE_RECALL_BASE/core/"
    cp "$SCRIPT_DIR/core/commands.py" "$CLAUDE_RECALL_BASE/core/"
    cp "$SCRIPT_DIR/core/config.py" "$CLAUDE_RECALL_BASE/core/"
    cp "$SCRIPT_DIR/core/paths.py" "$CLAUDE_RECALL_BASE/core/"

    # Copy TUI module as subpackage
    if [[ -d "$SCRIPT_DIR/core/tui" ]]; then
        mkdir -p "$CLAUDE_RECALL_BASE/core/tui/styles"
        cp "$SCRIPT_DIR/core/tui/"*.py "$CLAUDE_RECALL_BASE/core/tui/"
        [[ -f "$SCRIPT_DIR/core/tui/styles/app.tcss" ]] && cp "$SCRIPT_DIR/core/tui/styles/app.tcss" "$CLAUDE_RECALL_BASE/core/tui/styles/"
        log_success "Installed TUI module to $CLAUDE_RECALL_BASE/core/tui/"
    fi

    # Install claude-recall command
    if [[ -f "$SCRIPT_DIR/bin/claude-recall" ]]; then
        mkdir -p "$HOME/.local/bin"
        # Skip if source and dest are the same (dev environment)
        if [[ ! "$SCRIPT_DIR/bin/claude-recall" -ef "$HOME/.local/bin/claude-recall" ]]; then
            cp "$SCRIPT_DIR/bin/claude-recall" "$HOME/.local/bin/"
        fi
        chmod +x "$HOME/.local/bin/claude-recall"
        log_success "Installed claude-recall to ~/.local/bin/"

        # Clean up old recall-watch if present
        if [[ -f "$HOME/.local/bin/recall-watch" ]]; then
            rm -f "$HOME/.local/bin/recall-watch"
            log_info "Removed old recall-watch (renamed to claude-recall)"
        fi

        # Check if ~/.local/bin is in PATH
        if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
            log_warn "Add ~/.local/bin to your PATH to use 'claude-recall' command"
        fi
    fi

    chmod +x "$CLAUDE_RECALL_BASE/lessons-manager.sh" "$CLAUDE_RECALL_BASE/lesson-reminder-hook.sh"
    log_success "Installed shell scripts to $CLAUDE_RECALL_BASE/"
    log_success "Installed Python package to $CLAUDE_RECALL_BASE/core/"

    # Install OpenCode plugin to core location (adapters will symlink/copy)
    if [[ -f "$SCRIPT_DIR/plugins/opencode-lesson-reminder.ts" ]]; then
        cp "$SCRIPT_DIR/plugins/opencode-lesson-reminder.ts" "$CLAUDE_RECALL_BASE/plugins/"
        log_success "Installed OpenCode reminder plugin"
    fi

    # Note: System lessons file is now created in CLAUDE_RECALL_STATE on first use
    # by the Python manager, following XDG conventions
    if [[ ! -f "$CLAUDE_RECALL_STATE/LESSONS.md" ]]; then
        cat > "$CLAUDE_RECALL_STATE/LESSONS.md" << 'EOF'
# LESSONS.md - System Level

> **Claude Recall**: Cite lessons with [S###] when applying them.
> Stars accumulate with each use. System lessons apply to all projects.
>
> **Add lessons**: `SYSTEM LESSON: [category:] title - content`
> **Categories**: pattern, correction, decision, gotcha, preference

## Active Lessons

EOF
        log_success "Created system lessons file in state directory"
    fi
}

install_venv() {
    log_info "Setting up Python virtual environment for TUI..."

    local venv_dir="$CLAUDE_RECALL_BASE/.venv"

    # Create venv if it doesn't exist
    if [[ ! -d "$venv_dir" ]]; then
        if ! python3 -m venv "$venv_dir" 2>/dev/null; then
            log_warn "Could not create virtual environment (python3-venv may not be installed)"
            log_info "TUI will require manual: pip install textual textual-plotext"
            return 0
        fi
        log_success "Created virtual environment"
    fi

    # Install TUI dependencies
    log_info "Installing TUI dependencies (textual, rich)..."
    if "$venv_dir/bin/pip" install --quiet --upgrade pip 2>/dev/null && \
       "$venv_dir/bin/pip" install --quiet textual textual-plotext 2>/dev/null; then
        log_success "Installed TUI dependencies"
    else
        log_warn "Could not install TUI dependencies (network issue?)"
        log_info "TUI will require manual: pip install textual textual-plotext"
    fi
}

install_claude() {
    log_info "Installing Claude Code adapter..."

    local claude_dir="$HOME/.claude"
    local hooks_dir="$claude_dir/hooks"
    local commands_dir="$claude_dir/commands"

    mkdir -p "$hooks_dir" "$commands_dir"

    # Copy hooks
    cp "$SCRIPT_DIR/adapters/claude-code/inject-hook.sh" "$hooks_dir/"
    cp "$SCRIPT_DIR/adapters/claude-code/capture-hook.sh" "$hooks_dir/"
    cp "$SCRIPT_DIR/adapters/claude-code/smart-inject-hook.sh" "$hooks_dir/"
    cp "$SCRIPT_DIR/adapters/claude-code/stop-hook.sh" "$hooks_dir/"
    cp "$SCRIPT_DIR/adapters/claude-code/precompact-hook.sh" "$hooks_dir/"
    cp "$SCRIPT_DIR/adapters/claude-code/session-end-hook.sh" "$hooks_dir/"
    cp "$SCRIPT_DIR/adapters/claude-code/post-exitplanmode-hook.sh" "$hooks_dir/"
    cp "$SCRIPT_DIR/adapters/claude-code/post-todowrite-hook.sh" "$hooks_dir/"
    cp "$SCRIPT_DIR/adapters/claude-code/hook-lib.sh" "$hooks_dir/"
    chmod +x "$hooks_dir"/*.sh

    # Copy all commands from repo
    cp "$SCRIPT_DIR/adapters/claude-code/commands/"*.md "$commands_dir/"

    # Update settings.json with hooks using deep merge
    local settings_file="$claude_dir/settings.json"
    local hooks_config_file="$SCRIPT_DIR/adapters/claude-code/hooks-config.json"

    # Create settings file if it doesn't exist
    if [[ ! -f "$settings_file" ]]; then
        echo '{}' > "$settings_file"
    fi

    local backup="${settings_file}.backup.$(date +%Y%m%d_%H%M%S)"
    cp "$settings_file" "$backup"
    log_info "Backed up settings to $backup"

    # Read hooks config and substitute {{HOOKS_DIR}} placeholder
    local hooks_config
    hooks_config=$(sed "s|{{HOOKS_DIR}}|$hooks_dir|g" "$hooks_config_file")

    # Deep merge: preserve user hooks, update/add our hooks
    # Hooks are identified by patterns in their command field
    jq -s --argjson new_config "$hooks_config" '
      .[0] as $existing |

      # Helper: update or add a hook by command pattern
      def upsert_hook(pattern; new_hook):
        if any(.[]; .command | contains(pattern)) then
          map(if .command | contains(pattern) then new_hook else . end)
        else
          . + [new_hook]
        end;

      # Helper: update or add a PostToolUse matcher entry
      def upsert_matcher(matcher_name; new_entry):
        if any(.[]; .matcher == matcher_name) then
          map(if .matcher == matcher_name then new_entry else . end)
        else
          . + [new_entry]
        end;

      # Merge claudeRecall config (preserve user overrides)
      ($existing.claudeRecall // {}) as $user_recall |
      ($new_config.claudeRecall * $user_recall) as $merged_recall |

      # Start with existing settings
      $existing |

      # Set merged claudeRecall
      .claudeRecall = $merged_recall |

      # Ensure hooks object exists
      .hooks //= {} |

      # SessionStart: merge hooks
      .hooks.SessionStart //= [{"hooks": []}] |
      .hooks.SessionStart[0].hooks = (
        .hooks.SessionStart[0].hooks |
        reduce ($new_config.hooks.SessionStart[0].hooks[] | . as $h |
          ($h.command | split("/")[-1] | split(" ")[0]) as $pattern |
          {pattern: $pattern, hook: $h}
        ) as $item (.; upsert_hook($item.pattern; $item.hook))
      ) |

      # UserPromptSubmit: merge hooks
      .hooks.UserPromptSubmit //= [{"hooks": []}] |
      .hooks.UserPromptSubmit[0].hooks = (
        .hooks.UserPromptSubmit[0].hooks |
        reduce ($new_config.hooks.UserPromptSubmit[0].hooks[] | . as $h |
          ($h.command | split("/")[-1] | split(" ")[0]) as $pattern |
          {pattern: $pattern, hook: $h}
        ) as $item (.; upsert_hook($item.pattern; $item.hook))
      ) |

      # Stop: merge hooks
      .hooks.Stop //= [{"hooks": []}] |
      .hooks.Stop[0].hooks = (
        .hooks.Stop[0].hooks |
        reduce ($new_config.hooks.Stop[0].hooks[] | . as $h |
          ($h.command | split("/")[-1] | split(" ")[0]) as $pattern |
          {pattern: $pattern, hook: $h}
        ) as $item (.; upsert_hook($item.pattern; $item.hook))
      ) |

      # PreCompact: merge hooks
      .hooks.PreCompact //= [{"hooks": []}] |
      .hooks.PreCompact[0].hooks = (
        .hooks.PreCompact[0].hooks |
        reduce ($new_config.hooks.PreCompact[0].hooks[] | . as $h |
          ($h.command | split("/")[-1] | split(" ")[0]) as $pattern |
          {pattern: $pattern, hook: $h}
        ) as $item (.; upsert_hook($item.pattern; $item.hook))
      ) |

      # PostToolUse: merge by matcher name
      .hooks.PostToolUse //= [] |
      .hooks.PostToolUse = (
        .hooks.PostToolUse |
        reduce ($new_config.hooks.PostToolUse[]) as $entry (.;
          upsert_matcher($entry.matcher; $entry)
        )
      )
    ' "$settings_file" > "${settings_file}.tmp"

    # Post-process to match user's formatting style
    if [[ -s "${settings_file}.tmp" ]]; then
        python3 "$SCRIPT_DIR/adapters/claude-code/format-settings.py" "${settings_file}.tmp" > "${settings_file}.tmp2" 2>/dev/null
        if [[ -s "${settings_file}.tmp2" ]]; then
            mv "${settings_file}.tmp2" "${settings_file}.tmp"
        fi
        # Fallback: if Python formatting failed, keep jq output
    fi

    if [[ -s "${settings_file}.tmp" ]]; then
        mv "${settings_file}.tmp" "$settings_file"
        log_success "Deep merged hooks into settings.json"
    else
        rm -f "${settings_file}.tmp"
        log_error "Failed to update settings.json - restoring backup"
        cp "$backup" "$settings_file"
        return 1
    fi

    log_success "Installed Claude Code adapter"
}

install_opencode() {
    log_info "Installing OpenCode adapter..."

    local opencode_dir="$HOME/.config/opencode"
    local plugin_dir="$opencode_dir/plugin"
    local command_dir="$opencode_dir/command"

    mkdir -p "$plugin_dir" "$command_dir"

    # Install main lessons plugin
    if [[ -f "$SCRIPT_DIR/adapters/opencode/plugin.ts" ]]; then
        cp "$SCRIPT_DIR/adapters/opencode/plugin.ts" "$plugin_dir/lessons.ts"
    fi

    # Install periodic reminder plugin
    if [[ -f "$SCRIPT_DIR/plugins/opencode-lesson-reminder.ts" ]]; then
        cp "$SCRIPT_DIR/plugins/opencode-lesson-reminder.ts" "$plugin_dir/lesson-reminder.ts"
        log_success "Installed OpenCode reminder plugin"
    fi

    if [[ -f "$SCRIPT_DIR/adapters/opencode/command/lessons.md" ]]; then
        cp "$SCRIPT_DIR/adapters/opencode/command/lessons.md" "$command_dir/"
    fi

    local agents_md="$opencode_dir/AGENTS.md"
    local lessons_section='
## Claude Recall

A tiered learning cache that tracks corrections/patterns across sessions.

- **Project lessons** (`[L###]`): `.claude-recall/LESSONS.md`
- **System lessons** (`[S###]`): `~/.local/state/claude-recall/LESSONS.md`

**Add**: Type `LESSON: title - content` or `SYSTEM LESSON: title - content`
**Cite**: Reference `[L001]` when applying lessons (stars increase with use)
**View**: `/lessons` command
'

    if [[ -f "$agents_md" ]]; then
        # Check if old locations are referenced and need updating
        if grep -q "\.claude/LESSONS\.md\|\.coding-agent-lessons\|~/.config/coding-agent-lessons" "$agents_md"; then
            log_info "Updating old paths in AGENTS.md..."
            sed -i.bak \
                -e 's|\.claude/LESSONS\.md|.claude-recall/LESSONS.md|g' \
                -e 's|~/.claude/LESSONS\.md|~/.config/claude-recall/LESSONS.md|g' \
                -e 's|\.coding-agent-lessons|.claude-recall|g' \
                -e 's|~/.config/coding-agent-lessons|~/.config/claude-recall|g' \
                "$agents_md"
            rm -f "${agents_md}.bak"
            log_success "Updated AGENTS.md with new paths"
        elif ! grep -q "Claude Recall\|Lessons System" "$agents_md"; then
            echo "$lessons_section" >> "$agents_md"
        fi
    else
        echo "# Global OpenCode Instructions" > "$agents_md"
        echo "$lessons_section" >> "$agents_md"
    fi

    log_success "Installed OpenCode adapter"
}

uninstall() {
    log_warn "Uninstalling Claude Recall..."

    # Remove Claude Code adapter files
    rm -f "$HOME/.claude/hooks/inject-hook.sh"
    rm -f "$HOME/.claude/hooks/capture-hook.sh"
    rm -f "$HOME/.claude/hooks/smart-inject-hook.sh"
    rm -f "$HOME/.claude/hooks/stop-hook.sh"
    rm -f "$HOME/.claude/hooks/precompact-hook.sh"
    rm -f "$HOME/.claude/hooks/session-end-hook.sh"
    rm -f "$HOME/.claude/hooks/post-exitplanmode-hook.sh"
    rm -f "$HOME/.claude/hooks/post-todowrite-hook.sh"
    rm -f "$HOME/.claude/hooks/hook-lib.sh"
    rm -f "$HOME/.claude/commands/lessons.md"
    rm -f "$HOME/.claude/commands/implement.md"
    rm -f "$HOME/.claude/commands/delegate.md"
    rm -f "$HOME/.claude/commands/review.md"
    rm -f "$HOME/.claude/commands/test-first.md"

    # Selectively remove only Claude Recall hooks from settings.json
    # This preserves other user hooks while removing inject-hook, capture-hook, stop-hook, and reminder hooks
    if [[ -f "$HOME/.claude/settings.json" ]]; then
        local backup="$HOME/.claude/settings.json.backup.$(date +%Y%m%d_%H%M%S)"
        cp "$HOME/.claude/settings.json" "$backup"
        log_info "Backed up settings to $backup"

        # Remove hooks containing Claude Recall commands, preserving others
        jq '
          del(.claudeRecall) | del(.lessonsSystem) |
          if .hooks then
            .hooks |= (
              if .SessionStart then
                .SessionStart |= map(
                  .hooks |= map(select(.command | (contains("inject-hook.sh") or contains("reminder-state") or contains("lesson-reminder")) | not))
                ) | .SessionStart |= map(select(.hooks | length > 0))
              else . end |
              if .UserPromptSubmit then
                .UserPromptSubmit |= map(
                  .hooks |= map(select(.command | (contains("capture-hook.sh") or contains("smart-inject-hook.sh") or contains("lesson-reminder")) | not))
                ) | .UserPromptSubmit |= map(select(.hooks | length > 0))
              else . end |
              if .Stop then
                .Stop |= map(
                  .hooks |= map(select(.command | (contains("stop-hook.sh") or contains("session-end-hook.sh")) | not))
                ) | .Stop |= map(select(.hooks | length > 0))
              else . end |
              if .PreCompact then
                .PreCompact |= map(
                  .hooks |= map(select(.command | contains("precompact-hook.sh") | not))
                ) | .PreCompact |= map(select(.hooks | length > 0))
              else . end |
              if .PostToolUse then
                .PostToolUse |= map(
                  select(.hooks[0].command | (contains("post-exitplanmode-hook.sh") or contains("post-todowrite-hook.sh")) | not)
                )
              else . end |
              # Remove empty hook arrays
              with_entries(select(.value | length > 0))
            )
          else . end |
          # Remove hooks key if empty
          if .hooks and (.hooks | length == 0) then del(.hooks) else . end
        ' "$HOME/.claude/settings.json" > "$HOME/.claude/settings.json.tmp" 2>/dev/null

        if [[ -s "$HOME/.claude/settings.json.tmp" ]]; then
            mv "$HOME/.claude/settings.json.tmp" "$HOME/.claude/settings.json"
            log_success "Removed Claude Recall hooks from settings.json (other hooks preserved)"
        else
            rm -f "$HOME/.claude/settings.json.tmp"
            log_warn "Could not update settings.json - please manually remove Claude Recall hooks"
        fi
    fi

    # Remove OpenCode adapter
    rm -f "$HOME/.config/opencode/plugin/lessons.ts"
    rm -f "$HOME/.config/opencode/plugin/lesson-reminder.ts"
    rm -f "$HOME/.config/opencode/command/lessons.md"

    # Remove claude-recall command (and old recall-watch)
    if [[ -f "$HOME/.local/bin/claude-recall" ]]; then
        rm -f "$HOME/.local/bin/claude-recall"
        log_info "Removed claude-recall from ~/.local/bin/"
    fi
    if [[ -f "$HOME/.local/bin/recall-watch" ]]; then
        rm -f "$HOME/.local/bin/recall-watch"
        log_info "Removed recall-watch from ~/.local/bin/"
    fi

    # Helper function to clean up a config directory
    cleanup_config_dir() {
        local dir="$1"
        if [[ -d "$dir" ]]; then
            # Shell scripts at base level
            rm -f "$dir/lessons-manager.sh"
            rm -f "$dir/lesson-reminder-hook.sh"
            rm -f "$dir/.reminder-state"
            rm -rf "$dir/plugins"
            rm -rf "$dir/.venv"

            # New package structure (core/ subdirectory)
            rm -rf "$dir/core"

            # Old flat structure (for migration cleanup)
            rm -f "$dir/cli.py"
            rm -f "$dir/manager.py"
            rm -f "$dir/models.py"
            rm -f "$dir/parsing.py"
            rm -f "$dir/file_lock.py"
            rm -f "$dir/lessons.py"
            rm -f "$dir/handoffs.py"
            rm -f "$dir/debug_logger.py"
            rm -f "$dir/__init__.py"
            rm -f "$dir/_version.py"
            rm -f "$dir/context_extractor.py"
            rm -f "$dir/lessons_manager.py"
            rm -rf "$dir/tui"

            log_info "Cleaned up $dir"
        fi
    }

    # Clean up current and all old config locations
    cleanup_config_dir "$CLAUDE_RECALL_BASE"
    for old_path in "${OLD_SYSTEM_PATHS[@]}"; do
        cleanup_config_dir "$old_path"
    done

    # Clean up state directory (logs, decay state) but PRESERVE lessons
    if [[ -d "$CLAUDE_RECALL_STATE" ]]; then
        # Remove everything EXCEPT LESSONS.md
        find "$CLAUDE_RECALL_STATE" -type f ! -name "LESSONS.md" -delete 2>/dev/null || true
        find "$CLAUDE_RECALL_STATE" -type d -empty -delete 2>/dev/null || true
        if [[ -f "$CLAUDE_RECALL_STATE/LESSONS.md" ]]; then
            log_info "Preserved system lessons at: $CLAUDE_RECALL_STATE/LESSONS.md"
        else
            rmdir "$CLAUDE_RECALL_STATE" 2>/dev/null || true
        fi
    fi

    log_success "Uninstalled adapters. Lessons preserved."
    log_info "To fully remove project lessons: rm -rf $CLAUDE_RECALL_BASE"
    log_info "To fully remove system lessons: rm -rf $CLAUDE_RECALL_STATE"

    # Show any remaining old paths that might have lessons
    for old_path in "${OLD_SYSTEM_PATHS[@]}"; do
        if [[ -f "$old_path/LESSONS.md" ]]; then
            log_info "Old lessons found at: $old_path/LESSONS.md"
        fi
    done
}

main() {
    echo ""
    echo "========================================"
    echo "  Claude Recall - Install"
    echo "========================================"
    echo ""

    case "${1:-}" in
        --uninstall)
            uninstall
            exit 0
            ;;
        --migrate)
            check_deps
            migrate_config
            exit 0
            ;;
        --claude)
            check_deps
            migrate_config
            install_core
            install_venv
            install_claude
            ;;
        --opencode)
            check_deps
            migrate_config
            install_core
            install_venv
            install_opencode
            ;;
        --help|-h)
            echo "Usage: $0 [options]"
            echo ""
            echo "Options:"
            echo "  (none)       Auto-detect and install for available tools"
            echo "  --claude     Install Claude Code adapter only"
            echo "  --opencode   Install OpenCode adapter only"
            echo "  --migrate    Migrate from old config locations"
            echo "  --uninstall  Remove the system (keeps lessons)"
            echo ""
            echo "Migration:"
            echo "  Old locations (will be migrated):"
            echo "    ~/.config/coding-agent-lessons/"
            echo "    ~/.config/recall/"
            echo "    ~/.config/claude-recall/LESSONS.md"
            echo "    ~/.claude/LESSONS.md"
            echo "    .coding-agent-lessons/"
            echo "    .recall/"
            echo ""
            echo "  New locations:"
            echo "    ~/.local/state/claude-recall/LESSONS.md (system)"
            echo "    .claude-recall/LESSONS.md (project, gitignored)"
            exit 0
            ;;
        *)
            check_deps
            migrate_config
            install_core
            install_venv

            local tools=$(detect_tools)
            local installed=0

            if echo "$tools" | grep -q "claude"; then
                install_claude
                ((installed++))
            fi

            if echo "$tools" | grep -q "opencode"; then
                install_opencode
                ((installed++))
            fi

            if (( installed == 0 )); then
                log_warn "No supported tools detected (Claude Code or OpenCode)"
                log_info "Core manager installed. Run with --claude or --opencode to install adapters manually."
            fi
            ;;
    esac

    echo ""
    log_success "Installation complete!"
    echo ""
    echo "Claude Recall installed:"
    echo "  - Code: $CLAUDE_RECALL_BASE/"
    echo "  - System lessons: $CLAUDE_RECALL_STATE/LESSONS.md (XDG state)"
    echo "  - Project lessons: .claude-recall/LESSONS.md (per-project, gitignored)"
    echo "  - Debug logs: $CLAUDE_RECALL_STATE/debug.log"
    echo ""
    echo "Features:"
    echo "  - Lessons shown at session start"
    echo "  - Periodic reminders every 12 prompts (high-star lessons)"
    echo "  - Type 'LESSON: title - content' to add a lesson"
    echo "  - Use '/lessons' command to view all lessons"
    echo "  - Agent will cite [L###] when applying lessons"
    echo ""
    echo "Configure reminder frequency in ~/.claude/settings.json: claudeRecall.remindEvery"
    echo ""
}

main "$@"
