#!/bin/bash
# SPDX-License-Identifier: MIT
# install-lessons-system.sh - Install the Claude Code lessons system
#
# Usage:
#   ~/.claude/install-lessons-system.sh              # Install the system
#   ~/.claude/install-lessons-system.sh --export     # Export lessons to tarball
#   ~/.claude/install-lessons-system.sh --import-from user@host  # Pull from SSH host
#
# Options:
#   --export [file]           Export lessons to tarball (default: ~/claude-lessons-export.tar.gz)
#   --import [file]           Import lessons from local tarball
#   --import-from <host>      Pull lessons from SSH host (e.g., user@hostname)
#   --import-from <host> -p   Also import project lessons from host's current dir
#   --uninstall               Remove the lessons system

set -euo pipefail

CLAUDE_DIR="$HOME/.claude"
HOOKS_DIR="$CLAUDE_DIR/hooks"
SETTINGS_FILE="$CLAUDE_DIR/settings.json"
BACKUP_SUFFIX=".backup.$(date +%Y%m%d_%H%M%S)"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Check dependencies
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

# Create directory structure
create_dirs() {
    log_info "Creating directory structure..."
    mkdir -p "$HOOKS_DIR"
    log_success "Created $HOOKS_DIR"
}

# Write lessons-manager.sh
write_lessons_manager() {
    log_info "Writing lessons-manager.sh..."
    cat > "$HOOKS_DIR/lessons-manager.sh" << 'SCRIPT_EOF'
#!/bin/bash
# SPDX-License-Identifier: MIT
# lessons-manager.sh - Tiered lessons learning system

set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-$(pwd)}"
SYSTEM_LESSONS_FILE="$HOME/.claude/LESSONS.md"
MAX_LESSONS="${MAX_LESSONS:-30}"
SYSTEM_PROMOTION_THRESHOLD="${SYSTEM_PROMOTION_THRESHOLD:-50}"
STALE_DAYS="${STALE_DAYS:-60}"

find_project_root() {
    local dir="$PROJECT_DIR"
    while [[ "$dir" != "/" ]]; do
        [[ -d "$dir/.git" ]] && { echo "$dir"; return 0; }
        dir=$(dirname "$dir")
    done
    echo "$PROJECT_DIR"
}

PROJECT_ROOT=$(find_project_root)
PROJECT_LESSONS_FILE="$PROJECT_ROOT/.claude/LESSONS.md"

init_lessons_file() {
    local file="$1" level="$2"
    mkdir -p "$(dirname "$file")"
    if [[ ! -f "$file" ]]; then
        local prefix="L" level_cap="Project"
        [[ "$level" == "system" ]] && { prefix="S"; level_cap="System"; }
        cat > "$file" << EOF
# LESSONS.md - $level_cap Level

> **Lessons System**: Cite lessons with [${prefix}###] when applying them.
> Stars accumulate with each use. At 50 uses, project lessons promote to system.
>
> **Add lessons**: \`LESSON: [category:] title - content\`
> **Categories**: pattern, correction, decision, gotcha, preference

## Active Lessons

EOF
    fi
}

uses_to_stars() {
    local uses=$1 left="" right=""
    for i in 1 2 3 4 5; do
        local threshold=$((i * 2))
        if (( uses >= threshold )); then left+="*"
        elif (( uses >= threshold - 1 )); then left+="+"
        else left+="-"; fi
    done
    for i in 1 2 3 4 5; do
        local threshold=$(( (i * 2) + 10 ))
        if (( uses >= threshold )); then right+="*"
        elif (( uses >= threshold - 1 )); then right+="+"
        else right+="-"; fi
    done
    echo "[$left/$right]"
}

get_next_id() {
    local file="$1" prefix="$2" max_id=0
    if [[ -f "$file" ]]; then
        while IFS= read -r line; do
            if [[ "$line" =~ \[${prefix}([0-9]+)\] ]]; then
                local id=$((10#${BASH_REMATCH[1]}))
                (( id > max_id )) && max_id=$id
            fi
        done < "$file"
    fi
    printf "%s%03d" "$prefix" $((max_id + 1))
}

# Calculate days between two dates (YYYY-MM-DD format)
days_since() {
    local date_str="$1"
    local today=$(date +%s)
    local then
    # macOS and Linux compatible date parsing
    if date -j >/dev/null 2>&1; then
        # macOS
        then=$(date -j -f "%Y-%m-%d" "$date_str" +%s 2>/dev/null || echo "$today")
    else
        # Linux
        then=$(date -d "$date_str" +%s 2>/dev/null || echo "$today")
    fi
    echo $(( (today - then) / 86400 ))
}

# Check for duplicate lessons by title similarity
check_duplicate() {
    local title="$1" file="$2"
    [[ ! -f "$file" ]] && return 1

    # Normalize title for comparison (lowercase, remove punctuation)
    local normalized=$(echo "$title" | tr '[:upper:]' '[:lower:]' | tr -d '[:punct:]' | tr -s ' ')

    while IFS= read -r line; do
        if [[ "$line" =~ ^###[[:space:]]*\[[LS][0-9]+\][[:space:]]*\[[^\]]+\][[:space:]]*(.*) ]]; then
            local existing_title="${BASH_REMATCH[1]}"
            local existing_norm=$(echo "$existing_title" | tr '[:upper:]' '[:lower:]' | tr -d '[:punct:]' | tr -s ' ')
            # Check if titles are very similar (one contains the other or exact match)
            if [[ "$normalized" == "$existing_norm" ]] || \
               [[ "$normalized" == *"$existing_norm"* && ${#existing_norm} -gt 10 ]] || \
               [[ "$existing_norm" == *"$normalized"* && ${#normalized} -gt 10 ]]; then
                echo "$existing_title"
                return 0
            fi
        fi
    done < "$file"
    return 1
}

add_lesson() {
    local level="$1" category="$2" title="$3" content="$4"
    local file prefix
    if [[ "$level" == "system" ]]; then
        file="$SYSTEM_LESSONS_FILE"; prefix="S"
    else
        file="$PROJECT_LESSONS_FILE"; prefix="L"
    fi
    init_lessons_file "$file" "$level"

    # Check for duplicates
    local duplicate
    if duplicate=$(check_duplicate "$title" "$file"); then
        echo "WARNING: Similar lesson already exists: '$duplicate'" >&2
        echo "Add anyway? Use 'add --force' to skip this check" >&2
        return 1
    fi

    local lesson_id=$(get_next_id "$file" "$prefix")
    local date_learned=$(date +%Y-%m-%d)
    local stars=$(uses_to_stars 1)
    cat >> "$file" << EOF

### [$lesson_id] $stars $title
- **Uses**: 1 | **Learned**: $date_learned | **Last**: $date_learned | **Category**: $category
> $content

EOF
    echo "Added $level lesson $lesson_id: $title"
}

add_lesson_force() {
    local level="$1" category="$2" title="$3" content="$4"
    local file prefix
    if [[ "$level" == "system" ]]; then
        file="$SYSTEM_LESSONS_FILE"; prefix="S"
    else
        file="$PROJECT_LESSONS_FILE"; prefix="L"
    fi
    init_lessons_file "$file" "$level"
    local lesson_id=$(get_next_id "$file" "$prefix")
    local date_learned=$(date +%Y-%m-%d)
    local stars=$(uses_to_stars 1)
    cat >> "$file" << EOF

### [$lesson_id] $stars $title
- **Uses**: 1 | **Learned**: $date_learned | **Last**: $date_learned | **Category**: $category
> $content

EOF
    echo "Added $level lesson $lesson_id: $title"
}

cite_lesson() {
    local lesson_id="$1" today=$(date +%Y-%m-%d)
    local file
    [[ "$lesson_id" =~ ^S ]] && file="$SYSTEM_LESSONS_FILE" || file="$PROJECT_LESSONS_FILE"
    [[ ! -f "$file" ]] && { echo "Lessons file not found: $file" >&2; return 1; }
    grep -q "\[$lesson_id\]" "$file" || { echo "Lesson $lesson_id not found" >&2; return 1; }

    local tmp_file=$(mktemp) found=false new_uses=0
    while IFS= read -r line || [[ -n "$line" ]]; do
        if [[ "$line" =~ ^###[[:space:]]*\[($lesson_id)\][[:space:]]*\[([*+/\ -]+)\][[:space:]]*(.*) ]]; then
            found=true
            local title="${BASH_REMATCH[3]}"
            IFS= read -r meta_line
            if [[ "$meta_line" =~ \*\*Uses\*\*:[[:space:]]*([0-9]+) ]]; then
                local old_uses="${BASH_REMATCH[1]}"
                new_uses=$((old_uses + 1))
                local new_stars=$(uses_to_stars $new_uses)
                echo "### [$lesson_id] $new_stars $title" >> "$tmp_file"
                echo "$meta_line" | sed -E "s/\*\*Uses\*\*:[[:space:]]*[0-9]+/**Uses**: $new_uses/" | \
                    sed -E "s/\*\*Last\*\*:[[:space:]]*[0-9-]+/**Last**: $today/" >> "$tmp_file"
            fi
        else
            echo "$line" >> "$tmp_file"
        fi
    done < "$file"

    if $found; then
        mv "$tmp_file" "$file"
        if [[ "$lesson_id" =~ ^L ]] && (( new_uses >= SYSTEM_PROMOTION_THRESHOLD )); then
            echo "PROMOTION_READY:$lesson_id:$new_uses"
        else
            echo "OK:$new_uses"
        fi
    else
        rm "$tmp_file"
        return 1
    fi
}

# Edit a lesson's content
edit_lesson() {
    local lesson_id="$1" new_content="$2"
    local file
    [[ "$lesson_id" =~ ^S ]] && file="$SYSTEM_LESSONS_FILE" || file="$PROJECT_LESSONS_FILE"
    [[ ! -f "$file" ]] && { echo "Lessons file not found: $file" >&2; return 1; }
    grep -q "\[$lesson_id\]" "$file" || { echo "Lesson $lesson_id not found" >&2; return 1; }

    local tmp_file=$(mktemp) found=false
    while IFS= read -r line || [[ -n "$line" ]]; do
        if [[ "$line" =~ ^###[[:space:]]*\[$lesson_id\] ]]; then
            found=true
            echo "$line" >> "$tmp_file"
            IFS= read -r meta_line
            echo "$meta_line" >> "$tmp_file"
            IFS= read -r content_line  # Skip old content
            echo "> $new_content" >> "$tmp_file"
        else
            echo "$line" >> "$tmp_file"
        fi
    done < "$file"

    if $found; then
        mv "$tmp_file" "$file"
        echo "Updated $lesson_id content"
    else
        rm "$tmp_file"
        return 1
    fi
}

# Delete a lesson
delete_lesson() {
    local lesson_id="$1"
    local file
    [[ "$lesson_id" =~ ^S ]] && file="$SYSTEM_LESSONS_FILE" || file="$PROJECT_LESSONS_FILE"
    [[ ! -f "$file" ]] && { echo "Lessons file not found: $file" >&2; return 1; }
    grep -q "\[$lesson_id\]" "$file" || { echo "Lesson $lesson_id not found" >&2; return 1; }

    local tmp_file=$(mktemp) skip_until_next=false deleted_title=""
    while IFS= read -r line || [[ -n "$line" ]]; do
        if [[ "$line" =~ ^###[[:space:]]*\[$lesson_id\][[:space:]]*\[[^\]]+\][[:space:]]*(.*) ]]; then
            skip_until_next=true
            deleted_title="${BASH_REMATCH[1]}"
            continue
        fi
        if $skip_until_next; then
            # Skip until we hit next lesson header or end of lessons section
            if [[ "$line" =~ ^###[[:space:]]*\[[LS][0-9]+\] ]] || [[ -z "$line" && $(tail -1 "$tmp_file" 2>/dev/null) == "" ]]; then
                skip_until_next=false
                [[ "$line" =~ ^### ]] && echo "$line" >> "$tmp_file"
            fi
            continue
        fi
        echo "$line" >> "$tmp_file"
    done < "$file"

    mv "$tmp_file" "$file"
    echo "Deleted $lesson_id: $deleted_title"
}

# Enhanced list with search, category filter, and staleness
list_lessons() {
    local scope="--all" search="" category="" show_stale=false verbose=false

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --project|--system|--all) scope="$1"; shift ;;
            --search|-s) search="$2"; shift 2 ;;
            --category|-c) category="$2"; shift 2 ;;
            --stale) show_stale=true; shift ;;
            --verbose|-v) verbose=true; shift ;;
            *) shift ;;
        esac
    done

    # Collect lessons from appropriate files
    local files=()
    case "$scope" in
        --project) [[ -f "$PROJECT_LESSONS_FILE" ]] && files+=("$PROJECT_LESSONS_FILE") ;;
        --system) [[ -f "$SYSTEM_LESSONS_FILE" ]] && files+=("$SYSTEM_LESSONS_FILE") ;;
        *)
            [[ -f "$PROJECT_LESSONS_FILE" ]] && files+=("$PROJECT_LESSONS_FILE")
            [[ -f "$SYSTEM_LESSONS_FILE" ]] && files+=("$SYSTEM_LESSONS_FILE")
            ;;
    esac

    (( ${#files[@]} == 0 )) && { echo "(no lessons found)"; return; }

    local current_file="" stale_count=0 total_count=0
    for file in "${files[@]}"; do
        local lesson_id="" stars="" title="" uses="" learned="" last="" cat="" content=""
        local file_label
        [[ "$file" == "$SYSTEM_LESSONS_FILE" ]] && file_label="SYSTEM" || file_label="PROJECT ($PROJECT_ROOT)"

        [[ "$current_file" != "$file" ]] && { echo "=== $file_label LESSONS ==="; current_file="$file"; }

        while IFS= read -r line; do
            if [[ "$line" =~ ^###[[:space:]]*(\[[LS][0-9]+\])[[:space:]]*(\[[^\]]+\])[[:space:]]*(.*) ]]; then
                # Output previous lesson if we have one
                if [[ -n "$lesson_id" ]]; then
                    output_lesson "$lesson_id" "$stars" "$title" "$uses" "$learned" "$last" "$cat" "$content" \
                        "$search" "$category" "$show_stale" "$verbose" && ((total_count++)) || true
                fi
                lesson_id="${BASH_REMATCH[1]}"
                stars="${BASH_REMATCH[2]}"
                title="${BASH_REMATCH[3]}"
                uses="" learned="" last="" cat="" content=""
            elif [[ -n "$lesson_id" && "$line" =~ \*\*Uses\*\*:[[:space:]]*([0-9]+) ]]; then
                uses="${BASH_REMATCH[1]}"
                [[ "$line" =~ \*\*Learned\*\*:[[:space:]]*([0-9-]+) ]] && learned="${BASH_REMATCH[1]}"
                [[ "$line" =~ \*\*Last\*\*:[[:space:]]*([0-9-]+) ]] && last="${BASH_REMATCH[1]}"
                [[ "$line" =~ \*\*Category\*\*:[[:space:]]*([a-z]+) ]] && cat="${BASH_REMATCH[1]}"
            elif [[ -n "$lesson_id" && "$line" =~ ^\>[[:space:]]*(.*) ]]; then
                content="${BASH_REMATCH[1]}"
            fi
        done < "$file"

        # Output last lesson
        if [[ -n "$lesson_id" ]]; then
            output_lesson "$lesson_id" "$stars" "$title" "$uses" "$learned" "$last" "$cat" "$content" \
                "$search" "$category" "$show_stale" "$verbose" && ((total_count++)) || true
        fi
        echo ""
    done

    echo "Total: $total_count lesson(s)"
}

# Helper to output a single lesson with filtering
output_lesson() {
    local id="$1" stars="$2" title="$3" uses="$4" learned="$5" last="$6" cat="$7" content="$8"
    local search="$9" category="${10}" show_stale="${11}" verbose="${12}"

    # Apply search filter
    if [[ -n "$search" ]]; then
        local search_lower=$(echo "$search" | tr '[:upper:]' '[:lower:]')
        local title_lower=$(echo "$title" | tr '[:upper:]' '[:lower:]')
        local content_lower=$(echo "$content" | tr '[:upper:]' '[:lower:]')
        [[ "$title_lower" != *"$search_lower"* && "$content_lower" != *"$search_lower"* ]] && return 1
    fi

    # Apply category filter
    if [[ -n "$category" ]]; then
        [[ "$cat" != "$category" ]] && return 1
    fi

    # Calculate staleness
    local days_ago=0 stale_marker=""
    if [[ -n "$last" ]]; then
        days_ago=$(days_since "$last")
        (( days_ago >= STALE_DAYS )) && stale_marker=" ⚠️ STALE(${days_ago}d)"
    fi

    # Apply stale filter
    if [[ "$show_stale" == "true" ]]; then
        (( days_ago < STALE_DAYS )) && return 1
    fi

    # Output
    if [[ "$verbose" == "true" ]]; then
        echo "$id $stars $title$stale_marker"
        echo "    Uses: $uses | Category: $cat | Last: $last (${days_ago}d ago)"
        echo "    -> $content"
    else
        echo "$id $stars $title$stale_marker"
        [[ -n "$content" ]] && echo "    -> $content"
    fi
    return 0
}

evict_lessons() {
    local max_count="${1:-$MAX_LESSONS}" file="$PROJECT_LESSONS_FILE"
    [[ ! -f "$file" ]] && return
    local count=$(grep -cE "^### \[L[0-9]+\]" "$file" 2>/dev/null || echo 0)
    (( count <= max_count )) && { echo "No eviction needed ($count <= $max_count)"; return; }
    echo "Eviction: removing $((count - max_count)) lowest-star lessons..."
    # TODO: Implement actual eviction
}

show_help() {
    cat << 'HELPEOF'
lessons-manager.sh - Manage Claude Code lessons

COMMANDS:
  list [options]           List lessons with optional filters
    --project              Show only project lessons
    --system               Show only system lessons
    --search, -s <term>    Filter by title/content
    --category, -c <cat>   Filter by category (pattern|correction|gotcha|preference|decision)
    --stale                Show only stale lessons (uncited 60+ days)
    --verbose, -v          Show full details

  add <category> <title> <content>
                           Add a project lesson (checks for duplicates)
  add --force <category> <title> <content>
                           Add without duplicate check
  add-system <category> <title> <content>
                           Add a system lesson

  edit <id> <new_content>  Edit a lesson's content
  delete <id>              Delete a lesson
  cite <id>                Increment a lesson's usage count
  evict [max]              Remove lowest-star lessons over limit

EXAMPLES:
  lessons-manager.sh list --search "spdlog"
  lessons-manager.sh list --category gotcha --verbose
  lessons-manager.sh list --stale
  lessons-manager.sh edit L005 "New content for this lesson"
  lessons-manager.sh delete L003
HELPEOF
}

main() {
    local cmd="${1:-help}"; shift || true
    case "$cmd" in
        add)
            if [[ "${1:-}" == "--force" ]]; then
                shift
                [[ $# -lt 3 ]] && { echo "Usage: add --force <category> <title> <content>" >&2; exit 1; }
                add_lesson_force "project" "$1" "$2" "$3"
            else
                [[ $# -lt 3 ]] && { echo "Usage: add <category> <title> <content>" >&2; exit 1; }
                add_lesson "project" "$1" "$2" "$3"
            fi
            ;;
        add-system)
            [[ $# -lt 3 ]] && { echo "Usage: add-system <cat> <title> <content>" >&2; exit 1; }
            add_lesson "system" "$1" "$2" "$3"
            ;;
        edit)
            [[ $# -lt 2 ]] && { echo "Usage: edit <lesson_id> <new_content>" >&2; exit 1; }
            edit_lesson "$1" "$2"
            ;;
        delete)
            [[ $# -lt 1 ]] && { echo "Usage: delete <lesson_id>" >&2; exit 1; }
            delete_lesson "$1"
            ;;
        cite)
            [[ $# -lt 1 ]] && { echo "Usage: cite <lesson_id>" >&2; exit 1; }
            cite_lesson "$1"
            ;;
        list) list_lessons "$@" ;;
        evict) evict_lessons "${1:-}" ;;
        help|--help|-h) show_help ;;
        *) show_help; exit 1 ;;
    esac
}

main "$@"
SCRIPT_EOF
    chmod +x "$HOOKS_DIR/lessons-manager.sh"
    log_success "Written lessons-manager.sh"
}

# Write lessons-inject-hook.sh (SessionStart)
write_inject_hook() {
    log_info "Writing lessons-inject-hook.sh..."
    cat > "$HOOKS_DIR/lessons-inject-hook.sh" << 'SCRIPT_EOF'
#!/bin/bash
# SPDX-License-Identifier: MIT
# lessons-inject-hook.sh - SessionStart hook to inject lessons context

set -euo pipefail

CONFIG_FILE="$HOME/.claude/settings.json"
SYSTEM_LESSONS_FILE="$HOME/.claude/LESSONS.md"

is_enabled() {
    [[ -f "$CONFIG_FILE" ]] && {
        local enabled=$(jq -r '.lessonsSystem.enabled // true' "$CONFIG_FILE" 2>/dev/null || echo "true")
        [[ "$enabled" == "true" ]]
    } || return 0
}

find_project_root() {
    local dir="${1:-$(pwd)}"
    while [[ "$dir" != "/" ]]; do
        [[ -d "$dir/.git" ]] && { echo "$dir"; return 0; }
        dir=$(dirname "$dir")
    done
    echo "$1"
}

extract_lessons() {
    local file="$1"
    [[ ! -f "$file" ]] && return
    local lesson_id="" stars="" title="" uses="" content=""
    while IFS= read -r line; do
        if [[ "$line" =~ ^###[[:space:]]*(\[[LS][0-9]+\])[[:space:]]*(\[[*+/\ -]+\])[[:space:]]*(.*) ]]; then
            lesson_id="${BASH_REMATCH[1]}"; stars="${BASH_REMATCH[2]}"; title="${BASH_REMATCH[3]}"
        elif [[ -n "$lesson_id" && "$line" =~ \*\*Uses\*\*:[[:space:]]*([0-9]+) ]]; then
            uses="${BASH_REMATCH[1]}"
        elif [[ -n "$lesson_id" && "$line" =~ ^\>[[:space:]]*(.*) ]]; then
            content="${BASH_REMATCH[1]}"
            echo "$uses|$lesson_id|$stars|$title|$content"
            lesson_id=""
        fi
    done < "$file" | sort -t'|' -k1 -nr
}

generate_summary() {
    local project_root="$1" project_file="$project_root/.claude/LESSONS.md" top_n=5
    local tmp_all=$(mktemp)
    extract_lessons "$SYSTEM_LESSONS_FILE" >> "$tmp_all"
    extract_lessons "$project_file" >> "$tmp_all"
    sort -t'|' -k1 -nr "$tmp_all" -o "$tmp_all"
    local total=$(wc -l < "$tmp_all" | tr -d ' ')
    (( total == 0 )) && { rm -f "$tmp_all"; return; }

    local system_count=0 project_count=0
    [[ -f "$SYSTEM_LESSONS_FILE" ]] && system_count=$(grep -cE "^### \[S[0-9]+\]" "$SYSTEM_LESSONS_FILE" 2>/dev/null || echo 0)
    [[ -f "$project_file" ]] && project_count=$(grep -cE "^### \[L[0-9]+\]" "$project_file" 2>/dev/null || echo 0)

    echo "LESSONS ACTIVE: $system_count system (S###), $project_count project (L###)"
    echo "Cite with [L###] or [S###] when applying. LESSON: to add new."
    echo ""
    echo "⚠️ LESSON DUTY: When user corrects you, something fails, or you discover a pattern:"
    echo "   ASK: \"📝 Should I record this as a lesson? [category]: title - content\""
    echo ""
    echo "TOP LESSONS:"
    head -n "$top_n" "$tmp_all" | while IFS='|' read -r uses id stars title content; do
        echo "  $id $stars $title"
        [[ -n "$content" ]] && echo "    -> $content"
    done
    local remaining=$((total - top_n))
    if (( remaining > 0 )); then
        echo ""; echo "OTHER LESSONS (cite to use):"
        tail -n +"$((top_n + 1))" "$tmp_all" | while IFS='|' read -r uses id stars title content; do
            echo "  $id $stars $title"
        done
    fi
    rm -f "$tmp_all"
    echo ""; echo "Files: ~/.claude/LESSONS.md (system), .claude/LESSONS.md (project)"
}

main() {
    is_enabled || exit 0
    local input=$(cat)
    local cwd=$(echo "$input" | jq -r '.cwd // "."' 2>/dev/null || echo ".")
    local project_root=$(find_project_root "$cwd")
    local summary=$(generate_summary "$project_root")
    if [[ -n "$summary" ]]; then
        local escaped=$(printf '%s' "$summary" | jq -Rs .)
        cat << EOF
{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":$escaped}}
EOF
    fi
    exit 0
}

main
SCRIPT_EOF
    chmod +x "$HOOKS_DIR/lessons-inject-hook.sh"
    log_success "Written lessons-inject-hook.sh"
}

# Write lessons-capture-hook.sh (UserPromptSubmit)
write_capture_hook() {
    log_info "Writing lessons-capture-hook.sh..."
    cat > "$HOOKS_DIR/lessons-capture-hook.sh" << 'SCRIPT_EOF'
#!/bin/bash
# SPDX-License-Identifier: MIT
# lessons-capture-hook.sh - UserPromptSubmit hook to capture new lessons

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANAGER="$SCRIPT_DIR/lessons-manager.sh"
CONFIG_FILE="$HOME/.claude/settings.json"

is_enabled() {
    [[ -f "$CONFIG_FILE" ]] && {
        local enabled=$(jq -r '.lessonsSystem.enabled // true' "$CONFIG_FILE" 2>/dev/null || echo "true")
        [[ "$enabled" == "true" ]]
    } || return 0
}

find_project_root() {
    local dir="${1:-$(pwd)}"
    while [[ "$dir" != "/" ]]; do
        [[ -d "$dir/.git" ]] && { echo "$dir"; return 0; }
        dir=$(dirname "$dir")
    done
    echo "$1"
}

parse_lesson() {
    local prompt="$1" level="project" lesson_text=""
    if echo "$prompt" | grep -qi "^SYSTEM LESSON:"; then
        level="system"
        lesson_text=$(echo "$prompt" | sed -E 's/^SYSTEM LESSON:[[:space:]]*//i')
    elif echo "$prompt" | grep -qi "^LESSON:"; then
        lesson_text=$(echo "$prompt" | sed -E 's/^LESSON:[[:space:]]*//i')
    else
        return 1
    fi
    local category="correction"
    if [[ "$lesson_text" =~ ^([a-z]+):[[:space:]]*(.*)$ ]]; then
        category="${BASH_REMATCH[1]}"; lesson_text="${BASH_REMATCH[2]}"
    fi
    local title="" content=""
    if [[ "$lesson_text" =~ ^([^-]+)[[:space:]]*-[[:space:]]*(.+)$ ]]; then
        title="${BASH_REMATCH[1]}"; content="${BASH_REMATCH[2]}"
    else
        title="$lesson_text"; content="$lesson_text"
    fi
    title=$(echo "$title" | sed -E 's/^[[:space:]]+|[[:space:]]+$//g')
    content=$(echo "$content" | sed -E 's/^[[:space:]]+|[[:space:]]+$//g')
    [[ -n "$title" && -n "$content" ]] && { echo "$level"; echo "$category"; echo "$title"; echo "$content"; return 0; }
    return 1
}

main() {
    is_enabled || exit 0
    local input=$(cat)
    local prompt=$(echo "$input" | jq -r '.prompt // ""' 2>/dev/null || echo "")
    local cwd=$(echo "$input" | jq -r '.cwd // "."' 2>/dev/null || echo ".")
    [[ -z "$prompt" ]] && exit 0

    if parsed=$(parse_lesson "$prompt"); then
        local level=$(echo "$parsed" | sed -n '1p')
        local category=$(echo "$parsed" | sed -n '2p')
        local title=$(echo "$parsed" | sed -n '3p')
        local content=$(echo "$parsed" | sed -n '4p')
        local project_root=$(find_project_root "$cwd")
        local result
        if [[ "$level" == "system" ]]; then
            result=$(PROJECT_DIR="$project_root" "$MANAGER" add-system "$category" "$title" "$content" 2>&1)
        else
            result=$(PROJECT_DIR="$project_root" "$MANAGER" add "$category" "$title" "$content" 2>&1)
        fi
        local lesson_id=$(echo "$result" | grep -oE '\[[LS][0-9]+\]' | head -1 || echo "")
        cat << EOF
{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":"LESSON RECORDED: $lesson_id [$title] added as $level lesson (category: $category). Cite using $lesson_id when applying."}}
EOF
    fi
    exit 0
}

main
SCRIPT_EOF
    chmod +x "$HOOKS_DIR/lessons-capture-hook.sh"
    log_success "Written lessons-capture-hook.sh"
}

# Write lessons-stop-hook.sh (Stop)
write_stop_hook() {
    log_info "Writing lessons-stop-hook.sh..."
    cat > "$HOOKS_DIR/lessons-stop-hook.sh" << 'SCRIPT_EOF'
#!/bin/bash
# SPDX-License-Identifier: MIT
# lessons-stop-hook.sh - Stop hook to parse Claude output for lesson citations

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANAGER="$SCRIPT_DIR/lessons-manager.sh"
CONFIG_FILE="$HOME/.claude/settings.json"
DEBUG_LOG="${LESSONS_DEBUG_LOG:-}"  # Set to a path to enable debug logging

debug() {
    [[ -n "$DEBUG_LOG" ]] && echo "[$(date +%H:%M:%S)] $*" >> "$DEBUG_LOG"
}

is_enabled() {
    [[ -f "$CONFIG_FILE" ]] && {
        local enabled=$(jq -r '.lessonsSystem.enabled // true' "$CONFIG_FILE" 2>/dev/null || echo "true")
        [[ "$enabled" == "true" ]]
    } || return 0
}

find_project_root() {
    local dir="${1:-$(pwd)}"
    while [[ "$dir" != "/" ]]; do
        [[ -d "$dir/.git" ]] && { echo "$dir"; return 0; }
        dir=$(dirname "$dir")
    done
    echo "$1"
}

extract_citations_from_transcript() {
    local transcript_path="$1"
    transcript_path="${transcript_path/#\~/$HOME}"  # Expand tilde

    [[ -z "$transcript_path" || ! -f "$transcript_path" ]] && return 1

    debug "Scanning transcript: $transcript_path"

    # Use grep to find citations directly - much faster than parsing JSON
    # Only scan last 50KB to keep it fast
    tail -c 51200 "$transcript_path" 2>/dev/null | \
        grep -oE '\[[LS][0-9]{3}\]' | \
        sort -u || true
}

extract_confirm_lesson() {
    local transcript_path="$1"
    transcript_path="${transcript_path/#\~/$HOME}"

    [[ -z "$transcript_path" || ! -f "$transcript_path" ]] && return 1

    # Only scan last 20KB for CONFIRM-LESSON
    tail -c 20480 "$transcript_path" 2>/dev/null | \
        grep -i "CONFIRM-LESSON:" | \
        tail -1 || true
}

process_citations() {
    local citations="$1"
    local project_root="$2"

    [[ -z "$citations" ]] && return 0

    debug "Found citations: $citations"
    echo "[lessons] Processing citations..." >&2

    local cited_count=0
    while IFS= read -r citation; do
        [[ -z "$citation" ]] && continue
        local lesson_id=$(echo "$citation" | tr -d '[]')
        local result=$(PROJECT_DIR="$project_root" "$MANAGER" cite "$lesson_id" 2>&1 || true)
        if [[ "$result" == OK:* ]]; then
            local uses=$(echo "$result" | cut -d: -f2)
            echo "[lessons] $lesson_id cited (now $uses uses)" >&2
            ((cited_count++)) || true
        else
            debug "Failed to cite $lesson_id: $result"
        fi
    done <<< "$citations"

    (( cited_count > 0 )) && echo "[lessons] $cited_count lesson(s) cited" >&2
}

process_confirm_lesson() {
    local lesson_line="$1"
    local project_root="$2"

    [[ -z "$lesson_line" ]] && return 0

    echo "[lessons] Adding confirmed lesson..." >&2

    local lesson_text=$(echo "$lesson_line" | sed -E 's/.*CONFIRM-LESSON:[[:space:]]*//i')
    local category="discovery"
    if [[ "$lesson_text" =~ ^([a-z]+):[[:space:]]*(.*)$ ]]; then
        category="${BASH_REMATCH[1]}"
        lesson_text="${BASH_REMATCH[2]}"
    fi

    local title="" content=""
    if [[ "$lesson_text" =~ ^([^-]+)[[:space:]]*-[[:space:]]*(.+)$ ]]; then
        title="${BASH_REMATCH[1]}"
        content="${BASH_REMATCH[2]}"
    else
        title="$lesson_text"
        content="$lesson_text"
    fi

    title=$(echo "$title" | sed -E 's/^[[:space:]]+|[[:space:]]+$//g')
    content=$(echo "$content" | sed -E 's/^[[:space:]]+|[[:space:]]+$//g')

    [[ -n "$title" && -n "$content" ]] && {
        local result=$(PROJECT_DIR="$project_root" "$MANAGER" add "$category" "$title" "$content" 2>&1)
        echo "[lessons] ADDED: $result" >&2
    }
}

main() {
    is_enabled || exit 0

    local input=$(cat)
    debug "Hook input: ${#input} chars"

    local cwd=$(echo "$input" | jq -r '.cwd // "."' 2>/dev/null || echo ".")
    local project_root=$(find_project_root "$cwd")
    local transcript_path=$(echo "$input" | jq -r '.transcript_path // ""' 2>/dev/null || echo "")
    debug "Project root: $project_root, transcript: $transcript_path"

    # Fast path: grep citations directly from transcript (50KB tail)
    local citations=$(extract_citations_from_transcript "$transcript_path")

    # Process CONFIRM-LESSON if present (20KB tail)
    local confirm_line=$(extract_confirm_lesson "$transcript_path")
    [[ -n "$confirm_line" ]] && process_confirm_lesson "$confirm_line" "$project_root"

    # Process citations
    process_citations "$citations" "$project_root"

    exit 0
}

main
SCRIPT_EOF
    chmod +x "$HOOKS_DIR/lessons-stop-hook.sh"
    log_success "Written lessons-stop-hook.sh"
}

# Update settings.json
update_settings() {
    log_info "Updating settings.json..."

    local hooks_config='{
  "lessonsSystem": {
    "enabled": true,
    "maxLessons": 30,
    "topLessonsToShow": 5,
    "evictionIntervalHours": 24,
    "promotionThreshold": 50
  },
  "hooks": {
    "SessionStart": [{"hooks": [{"type": "command", "command": "bash '"$HOOKS_DIR"'/lessons-inject-hook.sh", "timeout": 5000}]}],
    "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "bash '"$HOOKS_DIR"'/lessons-capture-hook.sh", "timeout": 5000}]}],
    "Stop": [{"hooks": [{"type": "command", "command": "bash '"$HOOKS_DIR"'/lessons-stop-hook.sh", "timeout": 5000}]}]
  }
}'

    if [[ -f "$SETTINGS_FILE" ]]; then
        # Backup existing
        cp "$SETTINGS_FILE" "${SETTINGS_FILE}${BACKUP_SUFFIX}"
        log_info "Backed up existing settings to ${SETTINGS_FILE}${BACKUP_SUFFIX}"

        # Merge with existing settings
        local merged=$(jq -s '.[0] * .[1]' "$SETTINGS_FILE" <(echo "$hooks_config"))
        echo "$merged" > "$SETTINGS_FILE"
    else
        echo "$hooks_config" | jq '.' > "$SETTINGS_FILE"
    fi

    log_success "Updated settings.json with hooks configuration"
}

# Initialize empty system lessons file
init_system_lessons() {
    local file="$CLAUDE_DIR/LESSONS.md"
    if [[ ! -f "$file" ]]; then
        log_info "Creating system lessons file..."
        cat > "$file" << 'EOF'
# LESSONS.md - System Level

> **Lessons System**: Cite lessons with [S###] when applying them.
> Stars accumulate with each use. System lessons apply to all projects.
>
> **Add lessons**: `SYSTEM LESSON: [category:] title - content`
> **Categories**: pattern, correction, decision, gotcha, preference

## Active Lessons

EOF
        log_success "Created ~/.claude/LESSONS.md"
    else
        log_info "System lessons file already exists"
    fi
}

# Add CLAUDE.md instructions
add_claude_md_instructions() {
    local claude_md="$CLAUDE_DIR/CLAUDE.md"
    local lessons_section='
## Lessons System (Dynamic Learning)

⚠️ **LESSON DUTY** - BE PROACTIVE!
When user corrects you, something fails, or you discover a pattern:
→ ASK: "📝 Should I record this as a lesson? category: title - content"

A tiered cache that tracks corrections/patterns you teach Claude. **Survives across sessions.**

### How It Works
- **Project lessons** (`[L###]`): Stored in `.claude/LESSONS.md`, project-specific
- **System lessons** (`[S###]`): Stored in `~/.claude/LESSONS.md`, apply everywhere
- **Star rating**: Each citation increments stars. 50+ uses → promote to system

### Your Commands
```
LESSON: title - content                    # Add project lesson
LESSON: category: title - content          # Add with category (pattern|correction|gotcha|preference)
SYSTEM LESSON: title - content             # Add system lesson directly
```

### Claude'\''s Responsibilities
- **CITE** lessons when applying: "Applying [L001]: ..."
- **PROPOSE** lessons when corrected or discovering patterns
- **NEVER** output `CONFIRM-LESSON:` without explicit approval
'

    if [[ -f "$claude_md" ]]; then
        if ! grep -q "Lessons System" "$claude_md"; then
            log_info "Adding lessons instructions to CLAUDE.md..."
            echo "$lessons_section" >> "$claude_md"
            log_success "Updated CLAUDE.md"
        else
            log_info "CLAUDE.md already has lessons instructions"
        fi
    else
        log_info "Creating CLAUDE.md with lessons instructions..."
        echo "# Global Claude Code Instructions" > "$claude_md"
        echo "$lessons_section" >> "$claude_md"
        log_success "Created CLAUDE.md"
    fi
}

# Create /lessons slash command
write_lessons_command() {
    local commands_dir="$CLAUDE_DIR/commands"
    local command_file="$commands_dir/lessons.md"

    mkdir -p "$commands_dir"

    log_info "Creating /lessons slash command..."
    cat > "$command_file" << 'EOF'
# Lessons Manager

Manage the lessons system. Parse the arguments to determine the action.

**Arguments provided**: $ARGUMENTS

## Instructions

Based on the arguments, run the appropriate command:

### No arguments or "list"
Run: `~/.claude/hooks/lessons-manager.sh list --verbose`
Then format the output as a markdown table with columns: ID, Stars, Title, Days Since Cited, Content

### "search <term>"
Run: `~/.claude/hooks/lessons-manager.sh list --search "<term>"`
Show matching lessons in a table.

### "category <cat>" or "cat <cat>"
Run: `~/.claude/hooks/lessons-manager.sh list --category <cat>`
Valid categories: pattern, correction, gotcha, preference, decision

### "stale"
Run: `~/.claude/hooks/lessons-manager.sh list --stale --verbose`
Show lessons that haven't been cited in 60+ days, suggest cleanup.

### "edit <id> <content>"
Run: `~/.claude/hooks/lessons-manager.sh edit <id> "<content>"`
Confirm the edit was successful.

### "delete <id>"
First show the lesson content, ask for confirmation, then run:
`~/.claude/hooks/lessons-manager.sh delete <id>`

### "help"
Show available subcommands:
- `/lessons` - List all lessons with details
- `/lessons search <term>` - Search by keyword
- `/lessons category <cat>` - Filter by category
- `/lessons stale` - Show stale lessons
- `/lessons edit <id> <content>` - Edit a lesson
- `/lessons delete <id>` - Delete a lesson (with confirmation)

## Execution

Run the command and present the results clearly. For list operations, always format as a table.
EOF
    log_success "Created /lessons command"
}

# Export lessons to tarball
export_lessons() {
    local output_file="${1:-$HOME/claude-lessons-export.tar.gz}"
    local tmp_dir=$(mktemp -d)

    log_info "Exporting lessons..."

    # Copy system lessons
    if [[ -f "$CLAUDE_DIR/LESSONS.md" ]]; then
        cp "$CLAUDE_DIR/LESSONS.md" "$tmp_dir/system-LESSONS.md"
        log_success "Included system lessons"
    else
        log_warn "No system lessons found"
    fi

    # Copy CLAUDE.md if it exists
    if [[ -f "$CLAUDE_DIR/CLAUDE.md" ]]; then
        cp "$CLAUDE_DIR/CLAUDE.md" "$tmp_dir/CLAUDE.md"
        log_success "Included CLAUDE.md"
    fi

    # Find and copy project lessons from current directory
    local project_root=$(find_project_root_export "$(pwd)")
    if [[ -f "$project_root/.claude/LESSONS.md" ]]; then
        cp "$project_root/.claude/LESSONS.md" "$tmp_dir/project-LESSONS.md"
        log_success "Included project lessons from $project_root"
    fi

    # Create manifest
    cat > "$tmp_dir/manifest.json" << EOF
{
  "exported_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "exported_from": "$(hostname)",
  "exported_by": "$(whoami)",
  "version": "1.0",
  "contents": {
    "system_lessons": $([ -f "$tmp_dir/system-LESSONS.md" ] && echo "true" || echo "false"),
    "project_lessons": $([ -f "$tmp_dir/project-LESSONS.md" ] && echo "true" || echo "false"),
    "claude_md": $([ -f "$tmp_dir/CLAUDE.md" ] && echo "true" || echo "false")
  }
}
EOF

    # Create tarball
    tar -czf "$output_file" -C "$tmp_dir" .
    rm -rf "$tmp_dir"

    log_success "Exported to: $output_file"
    echo ""
    echo "Contents:"
    tar -tzf "$output_file" | sed 's/^/  /'
    echo ""
    echo "To import on another machine:"
    echo "  scp $output_file user@host:~/"
    echo "  ssh user@host '~/.claude/install-lessons-system.sh --import ~/$(basename "$output_file")'"
}

# Find project root (standalone version for export)
find_project_root_export() {
    local dir="${1:-$(pwd)}"
    while [[ "$dir" != "/" ]]; do
        [[ -d "$dir/.git" ]] && { echo "$dir"; return 0; }
        dir=$(dirname "$dir")
    done
    echo "$1"
}

# Import lessons from tarball
import_lessons() {
    local input_file="$1"
    local merge_mode="${2:-merge}"  # merge or replace

    if [[ ! -f "$input_file" ]]; then
        log_error "File not found: $input_file"
        exit 1
    fi

    log_info "Importing lessons from $input_file..."

    local tmp_dir=$(mktemp -d)
    tar -xzf "$input_file" -C "$tmp_dir"

    # Show manifest
    if [[ -f "$tmp_dir/manifest.json" ]]; then
        echo ""
        log_info "Export info:"
        jq -r '"  From: \(.exported_from) by \(.exported_by)\n  Date: \(.exported_at)"' "$tmp_dir/manifest.json"
        echo ""
    fi

    # Import system lessons
    if [[ -f "$tmp_dir/system-LESSONS.md" ]]; then
        if [[ -f "$CLAUDE_DIR/LESSONS.md" ]]; then
            log_info "Merging system lessons..."
            merge_lessons_files "$CLAUDE_DIR/LESSONS.md" "$tmp_dir/system-LESSONS.md" "S"
        else
            mkdir -p "$CLAUDE_DIR"
            cp "$tmp_dir/system-LESSONS.md" "$CLAUDE_DIR/LESSONS.md"
            log_success "Imported system lessons"
        fi
    fi

    # Import project lessons (to current project if in a git repo)
    if [[ -f "$tmp_dir/project-LESSONS.md" ]]; then
        local project_root=$(find_project_root_export "$(pwd)")
        if [[ -d "$project_root/.git" ]]; then
            mkdir -p "$project_root/.claude"
            if [[ -f "$project_root/.claude/LESSONS.md" ]]; then
                log_info "Merging project lessons..."
                merge_lessons_files "$project_root/.claude/LESSONS.md" "$tmp_dir/project-LESSONS.md" "L"
            else
                cp "$tmp_dir/project-LESSONS.md" "$project_root/.claude/LESSONS.md"
                log_success "Imported project lessons to $project_root"
            fi
        else
            log_warn "Not in a git repo, skipping project lessons"
        fi
    fi

    rm -rf "$tmp_dir"
    log_success "Import complete!"

    # Show current state
    echo ""
    "$HOOKS_DIR/lessons-manager.sh" list 2>/dev/null || true
}

# Merge two lessons files, avoiding duplicates by title
merge_lessons_files() {
    local target="$1"
    local source="$2"
    local prefix="$3"  # L or S

    # Extract titles from target to avoid duplicates
    local existing_titles=$(grep -E "^### \[${prefix}[0-9]+\]" "$target" | sed -E 's/^### \[[LS][0-9]+\] \[[^]]+\] //' || true)

    local added=0
    local skipped=0
    local in_lesson=false
    local current_lesson=""
    local current_title=""

    while IFS= read -r line || [[ -n "$line" ]]; do
        if [[ "$line" =~ ^###[[:space:]]*\[${prefix}[0-9]+\] ]]; then
            # Save previous lesson if any
            if [[ -n "$current_lesson" && -n "$current_title" ]]; then
                if echo "$existing_titles" | grep -qF "$current_title"; then
                    ((skipped++)) || true
                else
                    echo "$current_lesson" >> "$target"
                    ((added++)) || true
                fi
            fi
            # Start new lesson
            in_lesson=true
            current_title=$(echo "$line" | sed -E 's/^### \[[LS][0-9]+\] \[[^]]+\] //')
            # Renumber with next available ID
            local next_id=$("$HOOKS_DIR/lessons-manager.sh" list "--$([ "$prefix" = "S" ] && echo "system" || echo "project")" 2>/dev/null | grep -cE "^### \[${prefix}[0-9]+\]" || echo 0)
            next_id=$((next_id + added + 1))
            local new_id=$(printf "%s%03d" "$prefix" "$next_id")
            current_lesson=$(echo "$line" | sed -E "s/\[${prefix}[0-9]+\]/[$new_id]/")
            current_lesson+=$'\n'
        elif $in_lesson; then
            if [[ -z "$line" && "$current_lesson" =~ ^\> ]]; then
                # End of lesson block
                current_lesson+=$'\n'
                in_lesson=false
            else
                current_lesson+="$line"$'\n'
            fi
        fi
    done < "$source"

    # Don't forget last lesson
    if [[ -n "$current_lesson" && -n "$current_title" ]]; then
        if echo "$existing_titles" | grep -qF "$current_title"; then
            ((skipped++)) || true
        else
            echo "$current_lesson" >> "$target"
            ((added++)) || true
        fi
    fi

    log_success "Merged: $added added, $skipped duplicates skipped"
}

# Import from SSH host
import_from_ssh() {
    local ssh_host="$1"
    local include_project="${2:-false}"

    log_info "Connecting to $ssh_host..."

    # Test SSH connection
    if ! ssh -o ConnectTimeout=5 -o BatchMode=yes "$ssh_host" "echo ok" >/dev/null 2>&1; then
        log_error "Cannot connect to $ssh_host (check SSH keys)"
        exit 1
    fi

    local tmp_dir=$(mktemp -d)
    local remote_tmp="/tmp/claude-lessons-export-$$.tar.gz"

    log_info "Fetching lessons from $ssh_host..."

    # Create export on remote and fetch
    ssh "$ssh_host" bash -s << 'REMOTE_SCRIPT'
set -e
TMP_DIR=$(mktemp -d)
EXPORT_FILE="/tmp/claude-lessons-export-$$.tar.gz"

# System lessons
[ -f ~/.claude/LESSONS.md ] && cp ~/.claude/LESSONS.md "$TMP_DIR/system-LESSONS.md"

# CLAUDE.md
[ -f ~/.claude/CLAUDE.md ] && cp ~/.claude/CLAUDE.md "$TMP_DIR/CLAUDE.md"

# Project lessons from current dir (if requested via env var)
if [ "${INCLUDE_PROJECT:-false}" = "true" ]; then
    PROJECT_ROOT=$(pwd)
    while [ "$PROJECT_ROOT" != "/" ]; do
        [ -d "$PROJECT_ROOT/.git" ] && break
        PROJECT_ROOT=$(dirname "$PROJECT_ROOT")
    done
    [ -f "$PROJECT_ROOT/.claude/LESSONS.md" ] && cp "$PROJECT_ROOT/.claude/LESSONS.md" "$TMP_DIR/project-LESSONS.md"
fi

# Manifest
cat > "$TMP_DIR/manifest.json" << EOF
{
  "exported_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "exported_from": "$(hostname)",
  "exported_by": "$(whoami)",
  "version": "1.0"
}
EOF

tar -czf "$EXPORT_FILE" -C "$TMP_DIR" .
rm -rf "$TMP_DIR"
echo "$EXPORT_FILE"
REMOTE_SCRIPT

    # Fetch the tarball
    local remote_file=$(ssh "$ssh_host" "ls /tmp/claude-lessons-export-*.tar.gz 2>/dev/null | tail -1")
    if [[ -z "$remote_file" ]]; then
        log_error "Failed to create export on remote"
        exit 1
    fi

    scp -q "$ssh_host:$remote_file" "$tmp_dir/import.tar.gz"
    ssh "$ssh_host" "rm -f $remote_file" 2>/dev/null || true

    # Import locally
    import_lessons "$tmp_dir/import.tar.gz"

    rm -rf "$tmp_dir"
}

# Uninstall
uninstall() {
    log_warn "Uninstalling lessons system..."

    # Remove hooks
    rm -f "$HOOKS_DIR/lessons-manager.sh"
    rm -f "$HOOKS_DIR/lessons-inject-hook.sh"
    rm -f "$HOOKS_DIR/lessons-capture-hook.sh"
    rm -f "$HOOKS_DIR/lessons-stop-hook.sh"

    # Remove hooks from settings (but keep the file)
    if [[ -f "$SETTINGS_FILE" ]]; then
        jq 'del(.hooks.SessionStart) | del(.hooks.UserPromptSubmit) | del(.hooks.Stop) | del(.lessonsSystem)' \
            "$SETTINGS_FILE" > "${SETTINGS_FILE}.tmp" && mv "${SETTINGS_FILE}.tmp" "$SETTINGS_FILE"
    fi

    log_success "Uninstalled. Lessons files preserved in ~/.claude/LESSONS.md"
}

# Main
main() {
    echo ""
    echo "╔══════════════════════════════════════════════╗"
    echo "║   Claude Code Lessons System Installer       ║"
    echo "╚══════════════════════════════════════════════╝"
    echo ""

    case "${1:-}" in
        --uninstall)
            uninstall
            exit 0
            ;;
        --export)
            export_lessons "${2:-}"
            exit 0
            ;;
        --import)
            if [[ -z "${2:-}" ]]; then
                log_error "Usage: $0 --import <file.tar.gz>"
                exit 1
            fi
            import_lessons "$2"
            exit 0
            ;;
        --import-from)
            if [[ -z "${2:-}" ]]; then
                log_error "Usage: $0 --import-from <user@host>"
                exit 1
            fi
            include_project="false"
            [[ "${3:-}" == "-p" || "${3:-}" == "--project" ]] && include_project="true"
            import_from_ssh "$2" "$include_project"
            exit 0
            ;;
        --help|-h)
            echo "Usage: $0 [command] [options]"
            echo ""
            echo "Commands:"
            echo "  (none)                  Install the lessons system"
            echo "  --export [file]         Export lessons to tarball"
            echo "                          Default: ~/claude-lessons-export.tar.gz"
            echo "  --import <file>         Import lessons from tarball"
            echo "  --import-from <host>    Pull lessons from SSH host"
            echo "                          Add -p to include project lessons"
            echo "  --uninstall             Remove the lessons system"
            echo ""
            echo "Examples:"
            echo "  $0                              # Install"
            echo "  $0 --export                     # Export to default location"
            echo "  $0 --export ~/backup.tar.gz    # Export to specific file"
            echo "  $0 --import ~/backup.tar.gz    # Import from file"
            echo "  $0 --import-from pbrown@mac    # Pull from SSH host"
            echo "  $0 --import-from pbrown@mac -p # Include project lessons"
            exit 0
            ;;
    esac

    check_deps
    create_dirs
    write_lessons_manager
    write_inject_hook
    write_capture_hook
    write_stop_hook
    update_settings
    init_system_lessons
    add_claude_md_instructions
    write_lessons_command

    echo ""
    log_success "Installation complete!"
    echo ""
    echo "Usage:"
    echo "  • Start a new Claude Code session to see lessons"
    echo "  • Type 'LESSON: title - content' to add a lesson"
    echo "  • Type '/lessons' to view all lessons with star ratings"
    echo "  • Claude will cite [L###] when applying lessons"
    echo ""
    echo "Files created:"
    echo "  • $HOOKS_DIR/lessons-*.sh (4 hook scripts)"
    echo "  • $SETTINGS_FILE (hooks configuration)"
    echo "  • $CLAUDE_DIR/LESSONS.md (system lessons)"
    echo "  • $CLAUDE_DIR/commands/lessons.md (slash command)"
    echo ""
}

main "$@"
