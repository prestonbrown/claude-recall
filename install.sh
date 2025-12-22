#!/bin/bash
# SPDX-License-Identifier: MIT
# install.sh - Install coding-agent-lessons for Claude Code, OpenCode, or both
#
# Usage:
#   ./install.sh              # Auto-detect and install for available tools
#   ./install.sh --claude     # Install Claude Code adapter only
#   ./install.sh --opencode   # Install OpenCode adapter only
#   ./install.sh --migrate    # Migrate from old ~/.claude/LESSONS.md locations
#   ./install.sh --uninstall  # Remove the system

set -euo pipefail

# Paths
LESSONS_BASE="$HOME/.config/coding-agent-lessons"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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

# Migrate lessons from old Claude Code locations to new tool-agnostic locations
migrate_lessons() {
    log_info "Checking for lessons to migrate..."
    
    local migrated=0
    
    # Migrate system lessons: ~/.claude/LESSONS.md -> ~/.config/coding-agent-lessons/LESSONS.md
    local old_system="$HOME/.claude/LESSONS.md"
    local new_system="$LESSONS_BASE/LESSONS.md"
    
    if [[ -f "$old_system" ]]; then
        mkdir -p "$LESSONS_BASE"
        if [[ -f "$new_system" ]]; then
            log_info "Merging $old_system into $new_system..."
            # Append old lessons (avoiding duplicates would require more logic)
            # For simplicity, we'll append and let user dedupe with /lessons
            cat "$old_system" >> "$new_system"
            log_success "Merged system lessons"
        else
            cp "$old_system" "$new_system"
            log_success "Migrated system lessons to $new_system"
        fi
        
        # Backup and remove old file
        mv "$old_system" "${old_system}.migrated.$(date +%Y%m%d)"
        log_info "Old file backed up to ${old_system}.migrated.*"
        ((migrated++))
    fi
    
    # Migrate project lessons: .claude/LESSONS.md -> .coding-agent-lessons/LESSONS.md
    local project_root=$(find_project_root "$(pwd)")
    local old_project="$project_root/.claude/LESSONS.md"
    local new_project="$project_root/.coding-agent-lessons/LESSONS.md"
    
    if [[ -f "$old_project" ]]; then
        mkdir -p "$project_root/.coding-agent-lessons"
        if [[ -f "$new_project" ]]; then
            log_info "Merging $old_project into $new_project..."
            cat "$old_project" >> "$new_project"
            log_success "Merged project lessons"
        else
            cp "$old_project" "$new_project"
            log_success "Migrated project lessons to $new_project"
        fi
        
        mv "$old_project" "${old_project}.migrated.$(date +%Y%m%d)"
        log_info "Old file backed up to ${old_project}.migrated.*"
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
    
    # Also check for old hook files to clean up
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
        log_info "No old lessons found to migrate"
    else
        log_success "Migration complete: $migrated item(s) migrated"
    fi
    
    return 0
}

install_core() {
    log_info "Installing core lessons manager..."
    mkdir -p "$LESSONS_BASE" "$LESSONS_BASE/plugins"
    cp "$SCRIPT_DIR/core/lessons-manager.sh" "$LESSONS_BASE/"
    cp "$SCRIPT_DIR/core/lesson-reminder-hook.sh" "$LESSONS_BASE/"
    chmod +x "$LESSONS_BASE/lessons-manager.sh" "$LESSONS_BASE/lesson-reminder-hook.sh"
    log_success "Installed lessons-manager.sh to $LESSONS_BASE/"
    log_success "Installed lesson-reminder-hook.sh to $LESSONS_BASE/"

    # Install OpenCode plugin to core location (adapters will symlink/copy)
    if [[ -f "$SCRIPT_DIR/plugins/opencode-lesson-reminder.ts" ]]; then
        cp "$SCRIPT_DIR/plugins/opencode-lesson-reminder.ts" "$LESSONS_BASE/plugins/"
        log_success "Installed OpenCode reminder plugin"
    fi

    if [[ ! -f "$LESSONS_BASE/LESSONS.md" ]]; then
        cat > "$LESSONS_BASE/LESSONS.md" << 'EOF'
# LESSONS.md - System Level

> **Lessons System**: Cite lessons with [S###] when applying them.
> Stars accumulate with each use. System lessons apply to all projects.
>
> **Add lessons**: `SYSTEM LESSON: [category:] title - content`
> **Categories**: pattern, correction, decision, gotcha, preference

## Active Lessons

EOF
        log_success "Created system lessons file"
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
    cp "$SCRIPT_DIR/adapters/claude-code/stop-hook.sh" "$hooks_dir/"
    chmod +x "$hooks_dir"/*.sh
    
    # Create /lessons command
    cat > "$commands_dir/lessons.md" << 'EOF'
# Lessons Manager

Manage the coding-agent-lessons system.

**Arguments**: $ARGUMENTS

Based on arguments, run the appropriate command:

- No args or "list": `~/.config/coding-agent-lessons/lessons-manager.sh list --verbose`
- "search <term>": `~/.config/coding-agent-lessons/lessons-manager.sh list --search "<term>"`
- "category <cat>": `~/.config/coding-agent-lessons/lessons-manager.sh list --category <cat>`
- "stale": `~/.config/coding-agent-lessons/lessons-manager.sh list --stale --verbose`
- "edit <id> <content>": `~/.config/coding-agent-lessons/lessons-manager.sh edit <id> "<content>"`
- "delete <id>": Show lesson, confirm, then `~/.config/coding-agent-lessons/lessons-manager.sh delete <id>`

Format list output as a markdown table. Valid categories: pattern, correction, gotcha, preference, decision.
EOF
    
    # Update settings.json with hooks (including periodic reminder)
    local settings_file="$claude_dir/settings.json"
    local hooks_config='{
  "lessonsSystem": {"enabled": true},
  "hooks": {
    "SessionStart": [{"hooks": [
      {"type": "command", "command": "bash '"$hooks_dir"'/inject-hook.sh", "timeout": 5000},
      {"type": "command", "command": "rm -f ~/.config/coding-agent-lessons/.reminder-state", "timeout": 1000}
    ]}],
    "UserPromptSubmit": [{"hooks": [
      {"type": "command", "command": "bash '"$hooks_dir"'/capture-hook.sh", "timeout": 5000},
      {"type": "command", "command": "~/.config/coding-agent-lessons/lesson-reminder-hook.sh", "timeout": 2000}
    ]}],
    "Stop": [{"hooks": [{"type": "command", "command": "bash '"$hooks_dir"'/stop-hook.sh", "timeout": 5000}]}]
  }
}'
    
    if [[ -f "$settings_file" ]]; then
        local backup="${settings_file}.backup.$(date +%Y%m%d_%H%M%S)"
        cp "$settings_file" "$backup"
        log_info "Backed up settings to $backup"
        jq -s '.[0] * .[1]' "$settings_file" <(echo "$hooks_config") > "${settings_file}.tmp"
        mv "${settings_file}.tmp" "$settings_file"
    else
        echo "$hooks_config" | jq '.' > "$settings_file"
    fi
    
    # Add instructions to CLAUDE.md
    local claude_md="$claude_dir/CLAUDE.md"
    local lessons_section='
## Lessons System (Dynamic Learning)

A tiered cache that tracks corrections/patterns across sessions.

- **Project lessons** (`[L###]`): `.coding-agent-lessons/LESSONS.md`
- **System lessons** (`[S###]`): `~/.config/coding-agent-lessons/LESSONS.md`

**Commands**: `LESSON: title - content` or `SYSTEM LESSON: title - content`
**Cite**: Reference `[L001]` when applying lessons.
**View**: `/lessons` command
'
    
    if [[ -f "$claude_md" ]]; then
        # Check if old locations are referenced and need updating
        if grep -q "\.claude/LESSONS\.md" "$claude_md" || grep -q "~/.claude/LESSONS\.md" "$claude_md"; then
            log_info "Updating old LESSONS.md paths in CLAUDE.md..."
            sed -i.bak \
                -e 's|\.claude/LESSONS\.md|.coding-agent-lessons/LESSONS.md|g' \
                -e 's|~/.claude/LESSONS\.md|~/.config/coding-agent-lessons/LESSONS.md|g' \
                "$claude_md"
            rm -f "${claude_md}.bak"
            log_success "Updated CLAUDE.md with new paths"
        elif ! grep -q "Lessons System" "$claude_md"; then
            echo "$lessons_section" >> "$claude_md"
        fi
    else
        echo "# Global Claude Code Instructions" > "$claude_md"
        echo "$lessons_section" >> "$claude_md"
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
## Lessons System

A tiered learning cache that tracks corrections/patterns across sessions.

- **Project lessons** (`[L###]`): `.coding-agent-lessons/LESSONS.md`
- **System lessons** (`[S###]`): `~/.config/coding-agent-lessons/LESSONS.md`

**Add**: Type `LESSON: title - content` or `SYSTEM LESSON: title - content`
**Cite**: Reference `[L001]` when applying lessons (stars increase with use)
**View**: `/lessons` command
'
    
    if [[ -f "$agents_md" ]]; then
        # Check if old locations are referenced and need updating
        if grep -q "\.claude/LESSONS\.md" "$agents_md" || grep -q "~/.claude/LESSONS\.md" "$agents_md"; then
            log_info "Updating old LESSONS.md paths in AGENTS.md..."
            sed -i.bak \
                -e 's|\.claude/LESSONS\.md|.coding-agent-lessons/LESSONS.md|g' \
                -e 's|~/.claude/LESSONS\.md|~/.config/coding-agent-lessons/LESSONS.md|g' \
                "$agents_md"
            rm -f "${agents_md}.bak"
            log_success "Updated AGENTS.md with new paths"
        elif ! grep -q "Lessons System" "$agents_md"; then
            echo "$lessons_section" >> "$agents_md"
        fi
    else
        echo "# Global OpenCode Instructions" > "$agents_md"
        echo "$lessons_section" >> "$agents_md"
    fi
    
    log_success "Installed OpenCode adapter"
}

uninstall() {
    log_warn "Uninstalling coding-agent-lessons..."

    # Remove Claude Code adapter files
    rm -f "$HOME/.claude/hooks/inject-hook.sh"
    rm -f "$HOME/.claude/hooks/capture-hook.sh"
    rm -f "$HOME/.claude/hooks/stop-hook.sh"
    rm -f "$HOME/.claude/commands/lessons.md"

    # Selectively remove only lessons-related hooks from settings.json
    # This preserves other user hooks while removing inject-hook, capture-hook, stop-hook, and reminder hooks
    if [[ -f "$HOME/.claude/settings.json" ]]; then
        local backup="$HOME/.claude/settings.json.backup.$(date +%Y%m%d_%H%M%S)"
        cp "$HOME/.claude/settings.json" "$backup"
        log_info "Backed up settings to $backup"

        # Remove hooks containing lessons-related commands, preserving others
        jq '
          del(.lessonsSystem) |
          if .hooks then
            .hooks |= (
              if .SessionStart then
                .SessionStart |= map(
                  .hooks |= map(select(.command | (contains("inject-hook.sh") or contains("reminder-state") or contains("lesson-reminder")) | not))
                ) | .SessionStart |= map(select(.hooks | length > 0))
              else . end |
              if .UserPromptSubmit then
                .UserPromptSubmit |= map(
                  .hooks |= map(select(.command | (contains("capture-hook.sh") or contains("lesson-reminder")) | not))
                ) | .UserPromptSubmit |= map(select(.hooks | length > 0))
              else . end |
              if .Stop then
                .Stop |= map(
                  .hooks |= map(select(.command | contains("stop-hook.sh") | not))
                ) | .Stop |= map(select(.hooks | length > 0))
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
            log_success "Removed lessons hooks from settings.json (other hooks preserved)"
        else
            rm -f "$HOME/.claude/settings.json.tmp"
            log_warn "Could not update settings.json - please manually remove lessons hooks"
        fi
    fi

    # Remove OpenCode adapter
    rm -f "$HOME/.config/opencode/plugin/lessons.ts"
    rm -f "$HOME/.config/opencode/plugin/lesson-reminder.ts"
    rm -f "$HOME/.config/opencode/command/lessons.md"

    # Remove core (but NOT the lessons themselves)
    rm -f "$LESSONS_BASE/lessons-manager.sh"
    rm -f "$LESSONS_BASE/lesson-reminder-hook.sh"
    rm -f "$LESSONS_BASE/.reminder-state"
    rm -rf "$LESSONS_BASE/plugins"

    log_success "Uninstalled adapters. Lessons preserved in $LESSONS_BASE/"
    log_info "To fully remove lessons: rm -rf $LESSONS_BASE"
}

main() {
    echo ""
    echo "========================================"
    echo "  Coding Agent Lessons - Installer"
    echo "========================================"
    echo ""
    
    case "${1:-}" in
        --uninstall)
            uninstall
            exit 0
            ;;
        --migrate)
            check_deps
            migrate_lessons
            exit 0
            ;;
        --claude)
            check_deps
            migrate_lessons
            install_core
            install_claude
            ;;
        --opencode)
            check_deps
            migrate_lessons
            install_core
            install_opencode
            ;;
        --help|-h)
            echo "Usage: $0 [options]"
            echo ""
            echo "Options:"
            echo "  (none)       Auto-detect and install for available tools"
            echo "  --claude     Install Claude Code adapter only"
            echo "  --opencode   Install OpenCode adapter only"
            echo "  --migrate    Migrate from old ~/.claude/LESSONS.md locations"
            echo "  --uninstall  Remove the system (keeps lessons)"
            echo ""
            echo "Migration:"
            echo "  Old locations (Claude Code specific):"
            echo "    ~/.claude/LESSONS.md"
            echo "    .claude/LESSONS.md"
            echo ""
            echo "  New locations (tool-agnostic):"
            echo "    ~/.config/coding-agent-lessons/LESSONS.md"
            echo "    .coding-agent-lessons/LESSONS.md"
            exit 0
            ;;
        *)
            check_deps
            migrate_lessons
            install_core
            
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
    echo "Lessons stored in: $LESSONS_BASE/"
    echo "  - System: $LESSONS_BASE/LESSONS.md"
    echo "  - Project: .coding-agent-lessons/LESSONS.md (per-project)"
    echo ""
    echo "Features:"
    echo "  - Lessons shown at session start"
    echo "  - Periodic reminders every 12 prompts (high-star lessons)"
    echo "  - Type 'LESSON: title - content' to add a lesson"
    echo "  - Use '/lessons' command to view all lessons"
    echo "  - Agent will cite [L###] when applying lessons"
    echo ""
    echo "Configure reminder frequency: export LESSON_REMIND_EVERY=12"
    echo ""
}

main "$@"
