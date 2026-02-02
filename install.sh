#!/bin/bash
# SPDX-License-Identifier: MIT
# install.sh - Install Claude Recall as a Claude Code plugin
#
# Usage:
#   ./install.sh              # Install as Claude Code plugin
#   ./install.sh --opencode   # Install OpenCode adapter only
#   ./install.sh --migrate    # Migrate from old config locations
#   ./install.sh --uninstall  # Remove the system

set -euo pipefail

# Paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_DIR="$HOME/.claude/plugins/claude-recall"
CLAUDE_RECALL_STATE="${CLAUDE_RECALL_STATE:-${XDG_STATE_HOME:-$HOME/.local/state}/claude-recall}"

# Legacy paths for migration
LEGACY_BASE="$HOME/.config/claude-recall"
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

find_project_root() {
    local dir="${1:-$(pwd)}"
    while [[ "$dir" != "/" ]]; do
        [[ -d "$dir/.git" ]] && { echo "$dir"; return 0; }
        dir=$(dirname "$dir")
    done
    echo "$1"
}

# ============================================================
# MIGRATION
# ============================================================

migrate_old_locations() {
    log_info "Checking for old config locations to migrate..."
    local migrated=0

    # Migrate from old system paths to state directory
    for old_path in "${OLD_SYSTEM_PATHS[@]}"; do
        if [[ -f "$old_path/LESSONS.md" && ! -f "$CLAUDE_RECALL_STATE/LESSONS.md" ]]; then
            mkdir -p "$CLAUDE_RECALL_STATE"
            cp "$old_path/LESSONS.md" "$CLAUDE_RECALL_STATE/"
            log_success "Migrated system lessons from $old_path"
            ((migrated++))
        fi
    done

    # Migrate from ~/.config/claude-recall/LESSONS.md to state
    if [[ -f "$LEGACY_BASE/LESSONS.md" && ! -f "$CLAUDE_RECALL_STATE/LESSONS.md" ]]; then
        mkdir -p "$CLAUDE_RECALL_STATE"
        cp "$LEGACY_BASE/LESSONS.md" "$CLAUDE_RECALL_STATE/"
        log_success "Migrated system lessons from $LEGACY_BASE"
        ((migrated++))
    fi

    # Migrate from ~/.claude/LESSONS.md (very old location)
    if [[ -f "$HOME/.claude/LESSONS.md" ]]; then
        mkdir -p "$CLAUDE_RECALL_STATE"
        if [[ -f "$CLAUDE_RECALL_STATE/LESSONS.md" ]]; then
            cat "$HOME/.claude/LESSONS.md" >> "$CLAUDE_RECALL_STATE/LESSONS.md"
            log_success "Merged system lessons from ~/.claude/LESSONS.md"
        else
            cp "$HOME/.claude/LESSONS.md" "$CLAUDE_RECALL_STATE/"
            log_success "Migrated system lessons from ~/.claude/LESSONS.md"
        fi
        mv "$HOME/.claude/LESSONS.md" "$HOME/.claude/LESSONS.md.migrated.$(date +%Y%m%d)"
        ((migrated++))
    fi

    # Migrate project dirs
    local project_root
    project_root=$(find_project_root "$(pwd)")
    local new_project_dir="$project_root/.claude-recall"

    for old_name in "${OLD_PROJECT_DIRS[@]}"; do
        local old_dir="$project_root/$old_name"
        if [[ -d "$old_dir" && ! -d "$new_project_dir" ]]; then
            mv "$old_dir" "$new_project_dir"
            log_success "Migrated project data from $old_name"
            ((migrated++))
            break
        fi
    done

    if (( migrated == 0 )); then
        log_info "No old config found to migrate"
    else
        log_success "Migration complete: $migrated item(s) migrated"
    fi
}

# Ensure shared config.json exists and is up to date
merge_config() {
    log_info "Ensuring shared configuration..."

    local config_dir="$HOME/.config/claude-recall"
    local config_file="$config_dir/config.json"
    local default_config="$SCRIPT_DIR/plugins/claude-recall/config.json"

    mkdir -p "$config_dir"

    if [[ ! -f "$default_config" ]]; then
        log_warn "Default config.json not found, skipping config creation"
        return 0
    fi

    if [[ -f "$config_file" ]]; then
        if jq -s '.[0] * .[1]' "$default_config" "$config_file" > "$config_file.tmp" 2>/dev/null; then
            mv "$config_file.tmp" "$config_file"
            log_success "Updated config.json with defaults"
        else
            rm -f "$config_file.tmp"
            log_warn "Could not merge config.json; keeping existing file"
        fi
    else
        cp "$default_config" "$config_file"
        log_success "Created config.json with defaults"
    fi
}
# ============================================================
# CLEANUP OLD INSTALLATION
# ============================================================

cleanup_old_hooks() {
    log_info "Cleaning up old hook installation..."

    # Remove hook files from ~/.claude/hooks/
    local hooks_dir="$HOME/.claude/hooks"
    if [[ -d "$hooks_dir" ]]; then
        # Backup if any recall hooks exist
        local has_hooks=false
        for hook in inject-hook.sh capture-hook.sh smart-inject-hook.sh stop-hook.sh \
                    precompact-hook.sh session-end-hook.sh post-exitplanmode-hook.sh \
                    post-todowrite-hook.sh hook-lib.sh; do
            if [[ -f "$hooks_dir/$hook" ]]; then
                has_hooks=true
                break
            fi
        done

        if $has_hooks; then
            local backup_dir="$HOME/.claude/hooks.backup.$(date +%Y%m%d_%H%M%S)"
            mkdir -p "$backup_dir"
            for hook in inject-hook.sh capture-hook.sh smart-inject-hook.sh stop-hook.sh \
                        precompact-hook.sh session-end-hook.sh post-exitplanmode-hook.sh \
                        post-todowrite-hook.sh hook-lib.sh; do
                if [[ -f "$hooks_dir/$hook" ]]; then
                    mv "$hooks_dir/$hook" "$backup_dir/"
                fi
            done
            log_info "Backed up old hooks to $backup_dir"
        fi
    fi

    # Remove hook entries from settings.json
    local settings="$HOME/.claude/settings.json"
    if [[ -f "$settings" ]]; then
        local backup="${settings}.backup.$(date +%Y%m%d_%H%M%S)"
        cp "$settings" "$backup"
        log_info "Backed up settings to $backup"

        # Remove claudeRecall config and Claude Recall hooks
        jq '
            del(.claudeRecall) |
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
                    with_entries(select(.value | length > 0))
                )
            else . end |
            if .hooks and (.hooks | length == 0) then del(.hooks) else . end
        ' "$settings" > "$settings.tmp" 2>/dev/null

        if [[ -s "$settings.tmp" ]]; then
            mv "$settings.tmp" "$settings"
            log_success "Removed Claude Recall entries from settings.json"
        else
            rm -f "$settings.tmp"
            log_warn "Could not update settings.json"
        fi
    fi
}

cleanup_legacy_base() {
    # Clean up ~/.config/claude-recall/ (legacy install location)
    if [[ -d "$LEGACY_BASE" ]]; then
        # Keep LESSONS.md if it exists and wasn't migrated
        if [[ -f "$LEGACY_BASE/LESSONS.md" && ! -f "$CLAUDE_RECALL_STATE/LESSONS.md" ]]; then
            mkdir -p "$CLAUDE_RECALL_STATE"
            mv "$LEGACY_BASE/LESSONS.md" "$CLAUDE_RECALL_STATE/"
            log_info "Moved system lessons to $CLAUDE_RECALL_STATE/"
        fi

        # Remove code files
        rm -rf "$LEGACY_BASE/core" "$LEGACY_BASE/plugins" "$LEGACY_BASE/.venv" 2>/dev/null || true
        rm -f "$LEGACY_BASE/lessons-manager.sh" "$LEGACY_BASE/lesson-reminder-hook.sh" 2>/dev/null || true
        rm -f "$LEGACY_BASE/.reminder-state" 2>/dev/null || true

        # Remove directory if empty
        rmdir "$LEGACY_BASE" 2>/dev/null || true
        log_info "Cleaned up legacy install at $LEGACY_BASE"
    fi
}

# ============================================================
# INSTALLATION
# ============================================================

install_plugin() {
    log_info "Installing Claude Recall plugin via marketplace..."

    # Check if claude CLI is available
    if ! command -v claude >/dev/null 2>&1; then
        log_error "Claude CLI not found. Please install Claude Code first."
        exit 1
    fi

    # Add this repo as a marketplace (idempotent)
    if ! claude plugin marketplace list 2>/dev/null | grep -q "claude-recall"; then
        log_info "Adding claude-recall marketplace..."
        if ! claude plugin marketplace add "$SCRIPT_DIR" 2>&1; then
            log_error "Failed to add marketplace"
            exit 1
        fi
    else
        log_info "Marketplace already configured, updating..."
        claude plugin marketplace update claude-recall 2>/dev/null || true
    fi

    # Install the plugin
    log_info "Installing plugin from marketplace..."
    if claude plugin install claude-recall@claude-recall --scope user 2>&1; then
        log_success "Installed claude-recall plugin"
    else
        log_error "Failed to install plugin"
        exit 1
    fi
}

cleanup_old_commands() {
    # Remove old slash commands from ~/.claude/commands/
    # Commands are now served via plugin namespace (e.g., /claude-recall:lessons)
    local commands_dir="$HOME/.claude/commands"
    local removed=0
    for cmd in lessons.md handoffs.md implement.md delegate.md review.md test-first.md; do
        if [[ -f "$commands_dir/$cmd" ]]; then
            rm -f "$commands_dir/$cmd"
            ((removed++))
        fi
    done
    if ((removed > 0)); then
        log_info "Cleaned up $removed old command(s) from $commands_dir"
    fi
}

install_state_dir() {
    # Create state directory structure
    mkdir -p "$CLAUDE_RECALL_STATE"

    # Create system lessons file if it doesn't exist
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
        log_success "Created system lessons file"
    fi
}

sync_working_dir() {
    # Copy working directory files to installed plugin cache
    # This ensures local development changes are immediately available
    local install_path
    install_path=$(jq -r '.plugins["claude-recall@claude-recall"][0].installPath // empty' \
        "$HOME/.claude/plugins/installed_plugins.json" 2>/dev/null)

    if [[ -z "$install_path" || ! -d "$install_path" ]]; then
        return 0
    fi

    # Sync Go source from working directory (for building on target)
    if [[ -d "$SCRIPT_DIR/go" ]]; then
        mkdir -p "$install_path/go"
        cp -R "$SCRIPT_DIR/go/"* "$install_path/go/" 2>/dev/null || true
        # Remove built binaries (will rebuild on install)
        rm -rf "$install_path/go/bin" 2>/dev/null || true
        log_success "Synced Go source to plugin cache"
    fi
}

install_cli() {
    # Install claude-recall TUI wrapper (Python-based, deps managed externally)
    if [[ -f "$SCRIPT_DIR/bin/claude-recall" ]]; then
        mkdir -p "$HOME/.local/bin"
        cp "$SCRIPT_DIR/bin/claude-recall" "$HOME/.local/bin/"
        chmod +x "$HOME/.local/bin/claude-recall"
        log_success "Installed claude-recall TUI to ~/.local/bin/"
    fi

    if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
        log_warn "Add ~/.local/bin to PATH for 'recall' and 'claude-recall' commands"
    fi
}

build_go_binaries() {
    # Build Go binaries for high-performance hooks
    if ! command -v go >/dev/null 2>&1; then
        log_error "Go not installed. Install Go first: https://go.dev/dl/"
        exit 1
    fi

    local go_dir="$SCRIPT_DIR/go"
    if [[ ! -f "$go_dir/go.mod" ]]; then
        log_error "Go source not found at $go_dir"
        exit 1
    fi

    log_info "Building Go binaries..."

    mkdir -p "$go_dir/bin"

    # Build recall-hook (for stop hooks)
    if (cd "$go_dir" && go build -o bin/recall-hook ./cmd/recall-hook 2>/dev/null); then
        log_success "Built recall-hook binary"
    else
        log_error "Failed to build recall-hook"
        exit 1
    fi

    # Build recall CLI
    if (cd "$go_dir" && go build -o bin/recall ./cmd/recall 2>/dev/null); then
        log_success "Built recall CLI binary"
    else
        log_warn "Failed to build recall CLI (hook will still work)"
    fi
}

install_go_binaries() {
    # Install Go binaries to locations where hooks can find them
    local go_bin_dir="$SCRIPT_DIR/go/bin"

    if [[ ! -f "$go_bin_dir/recall-hook" ]]; then
        return 0
    fi

    # Install to LESSONS_BASE (where stop-hook.sh looks first)
    # This is the primary location hooks check: $LESSONS_BASE/go/bin/recall-hook
    local config_go_bin="$HOME/.config/claude-recall/go/bin"
    mkdir -p "$config_go_bin"
    cp "$go_bin_dir/recall-hook" "$config_go_bin/"
    if [[ -f "$go_bin_dir/recall" ]]; then
        cp "$go_bin_dir/recall" "$config_go_bin/"
    fi
    log_success "Installed Go binaries to ~/.config/claude-recall/go/bin/"

    # Also install to plugin cache path (for future-proofing)
    local install_path
    install_path=$(jq -r '.plugins["claude-recall@claude-recall"][0].installPath // empty' \
        "$HOME/.claude/plugins/installed_plugins.json" 2>/dev/null)

    if [[ -n "$install_path" && -d "$install_path" ]]; then
        mkdir -p "$install_path/go/bin"
        cp "$go_bin_dir/recall-hook" "$install_path/go/bin/"
        if [[ -f "$go_bin_dir/recall" ]]; then
            cp "$go_bin_dir/recall" "$install_path/go/bin/"
        fi
        log_success "Installed Go binaries to plugin cache"
    fi

    # Also install recall CLI to ~/.local/bin for command-line use
    if [[ -f "$go_bin_dir/recall" ]]; then
        mkdir -p "$HOME/.local/bin"
        cp "$go_bin_dir/recall" "$HOME/.local/bin/recall"
        chmod +x "$HOME/.local/bin/recall"
        log_success "Installed recall (Go) CLI to ~/.local/bin/"
    fi
}

install_claude() {
    log_info "Installing Claude Code plugin..."

    # Migrate old locations first
    migrate_old_locations

    # Clean up old hook-based installation
    cleanup_old_hooks
    cleanup_legacy_base

    # Install plugin via marketplace (handles registration and enabling)
    install_plugin

    # Sync working directory changes to plugin cache (for local development)
    sync_working_dir

    # Ensure shared config exists
    merge_config

    # Install supporting files
    cleanup_old_commands
    install_state_dir
    install_cli

    # Build and install Go binaries
    build_go_binaries
    install_go_binaries

    log_success "Installed Claude Code plugin"
}

# ============================================================
# OPENCODE ADAPTER (unchanged from original)
# ============================================================

install_opencode() {
    log_info "Installing OpenCode adapter..."

    local opencode_dir="$HOME/.config/opencode"
    local plugin_dir="$opencode_dir/plugins"
    local command_dir="$opencode_dir/command"

    mkdir -p "$plugin_dir" "$command_dir"

    # Install from adapters directory
    if [[ -f "$SCRIPT_DIR/adapters/opencode/plugin.ts" ]]; then
        cp "$SCRIPT_DIR/adapters/opencode/plugin.ts" "$plugin_dir/lessons.ts"
        log_success "Installed lessons.ts plugin"
    fi

    if [[ -f "$SCRIPT_DIR/adapters/opencode/command/lessons.md" ]]; then
        cp "$SCRIPT_DIR/adapters/opencode/command/lessons.md" "$command_dir/"
        log_success "Installed /lessons command"
    fi

    if [[ -f "$SCRIPT_DIR/adapters/opencode/command/handoffs.md" ]]; then
        cp "$SCRIPT_DIR/adapters/opencode/command/handoffs.md" "$command_dir/"
        log_success "Installed /handoffs command"
    fi

    # Ensure shared config exists
    merge_config

    # Ensure AGENTS.md exists and update Claude Recall section
    local agents_md="$opencode_dir/AGENTS.md"
    if [[ ! -f "$agents_md" ]]; then
        echo "# Global OpenCode Instructions" > "$agents_md"
    fi

    # Remove old "Lessons System" section if it exists (deprecated)
    if grep -q "^## Lessons System$" "$agents_md" 2>/dev/null; then
        sed -i.tmp '/^## Lessons System$/,/^$/d' "$agents_md"
        rm -f "${agents_md}.tmp"
        log_info "Removed old Lessons System section from AGENTS.md"
    fi

    local claude_recall_section='
## Claude Recall

A learning system that tracks lessons and handoffs across sessions.

**Lessons System** - Track corrections/patterns:
- Project lessons (`[L###]`): `.claude-recall/LESSONS.md`
- System lessons (`[S###]`): `~/.local/state/claude-recall/LESSONS.md`
- Add: Type `LESSON: title - content` or `SYSTEM LESSON: title - content`
- Cite: Reference `[L001]` when applying lessons
- View: `/lessons` command

**Handoffs System** - Track multi-step work:
- Active handoffs: `.claude-recall/HANDOFFS.md`
- Create: Type `HANDOFF: title` or use `/handoffs add`
- Update: `HANDOFF UPDATE H001: tried success - description`
- Complete: `HANDOFF COMPLETE H001`
- View: `/handoffs` command
'

    if ! grep -q "^## Claude Recall$" "$agents_md" 2>/dev/null; then
        echo "$claude_recall_section" >> "$agents_md"
        log_success "Added Claude Recall section to AGENTS.md"
    fi

    install_cli

    log_success "Installed OpenCode adapter"
}

# ============================================================
# UNINSTALL
# ============================================================

uninstall() {
    log_warn "Uninstalling Claude Recall..."

    # Uninstall plugin via claude CLI
    if command -v claude >/dev/null 2>&1; then
        claude plugin uninstall claude-recall@claude-recall 2>/dev/null && \
            log_info "Uninstalled plugin" || true
        claude plugin marketplace remove claude-recall 2>/dev/null && \
            log_info "Removed marketplace" || true
    fi

    # Clean up old manual installation (if any)
    if [[ -d "$PLUGIN_DIR" ]]; then
        rm -rf "$PLUGIN_DIR"
        log_info "Removed legacy plugin directory"
    fi

    # Clean up old hook-based installation
    cleanup_old_hooks
    cleanup_legacy_base

    # Remove slash commands (legacy - now served via plugin namespace)
    rm -f "$HOME/.claude/commands/lessons.md"
    rm -f "$HOME/.claude/commands/handoffs.md"
    rm -f "$HOME/.claude/commands/implement.md"
    rm -f "$HOME/.claude/commands/delegate.md"
    rm -f "$HOME/.claude/commands/review.md"
    rm -f "$HOME/.claude/commands/test-first.md"

    # Remove OpenCode adapter
    rm -f "$HOME/.config/opencode/plugins/lessons.ts"
    rm -f "$HOME/.config/opencode/plugins/lesson-reminder.ts"
    rm -f "$HOME/.config/opencode/plugin/lessons.ts"
    rm -f "$HOME/.config/opencode/plugin/lesson-reminder.ts"
    rm -f "$HOME/.config/opencode/command/lessons.md"

    # Remove CLI
    rm -f "$HOME/.local/bin/claude-recall"

    # Clean up state (preserve lessons)
    if [[ -d "$CLAUDE_RECALL_STATE" ]]; then
        find "$CLAUDE_RECALL_STATE" -type f ! -name "LESSONS.md" -delete 2>/dev/null || true
        find "$CLAUDE_RECALL_STATE" -type d -empty -delete 2>/dev/null || true
        if [[ -f "$CLAUDE_RECALL_STATE/LESSONS.md" ]]; then
            log_info "Preserved system lessons at: $CLAUDE_RECALL_STATE/LESSONS.md"
        fi
    fi

    log_success "Uninstalled Claude Recall"
    log_info "To fully remove system lessons: rm -rf $CLAUDE_RECALL_STATE"
}

# ============================================================
# MAIN
# ============================================================

main() {
    echo ""
    echo "========================================"
    echo "  Claude Recall - Plugin Install"
    echo "========================================"
    echo ""

    case "${1:-}" in
        --uninstall)
            uninstall
            exit 0
            ;;
        --migrate)
            check_deps
            migrate_old_locations
            exit 0
            ;;
        --opencode)
            check_deps
            migrate_old_locations
            install_state_dir
            install_opencode
            ;;
        --help|-h)
            echo "Usage: $0 [options]"
            echo ""
            echo "Options:"
            echo "  (none)       Install as Claude Code plugin"
            echo "  --opencode   Install OpenCode adapter only"
            echo "  --migrate    Migrate from old config locations"
            echo "  --uninstall  Remove the system (keeps lessons)"
            echo ""
            echo "Plugin: claude-recall@claude-recall (installed via marketplace)"
            echo "System lessons: ~/.local/state/claude-recall/LESSONS.md"
            echo "Project lessons: .claude-recall/LESSONS.md (gitignored)"
            exit 0
            ;;
        *)
            check_deps
            install_claude
            ;;
    esac

    echo ""
    log_success "Installation complete!"
    echo ""
    echo "Claude Recall installed as plugin:"
    echo "  - Marketplace: claude-recall (local)"
    echo "  - Plugin: claude-recall@claude-recall"
    echo "  - System lessons: $CLAUDE_RECALL_STATE/LESSONS.md"
    echo "  - Project lessons: .claude-recall/LESSONS.md (per-project)"
    echo ""
    echo "Features:"
    echo "  - Lessons injected at session start"
    echo "  - Type 'LESSON: title - content' to add lessons"
    echo "  - Use '/lessons' command to view all lessons"
    echo ""
    echo "Verify with: claude plugin list"
    echo ""
}

main "$@"
