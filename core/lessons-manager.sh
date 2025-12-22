#!/bin/bash
# SPDX-License-Identifier: MIT
# lessons-manager.sh - Tool-agnostic lessons learning system
#
# Stores lessons in ~/.config/coding-agent-lessons/ for use with any AI coding agent
# (Claude Code, OpenCode, Cursor, etc.)

set -euo pipefail

# Configuration - tool-agnostic paths
LESSONS_BASE="${LESSONS_BASE:-$HOME/.config/coding-agent-lessons}"
PROJECT_DIR="${PROJECT_DIR:-$(pwd)}"
SYSTEM_LESSONS_FILE="$LESSONS_BASE/LESSONS.md"
MAX_LESSONS="${MAX_LESSONS:-30}"
SYSTEM_PROMOTION_THRESHOLD="${SYSTEM_PROMOTION_THRESHOLD:-50}"
STALE_DAYS="${STALE_DAYS:-60}"

# Ensure base directory exists
mkdir -p "$LESSONS_BASE"

find_project_root() {
    local dir="$PROJECT_DIR"
    while [[ "$dir" != "/" ]]; do
        [[ -d "$dir/.git" ]] && { echo "$dir"; return 0; }
        dir=$(dirname "$dir")
    done
    echo "$PROJECT_DIR"
}

PROJECT_ROOT=$(find_project_root)
# Project lessons in tool-agnostic location within the project
PROJECT_LESSONS_FILE="$PROJECT_ROOT/.coding-agent-lessons/LESSONS.md"

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

days_since() {
    local date_str="$1"
    local today=$(date +%s)
    local then
    if date -j >/dev/null 2>&1; then
        then=$(date -j -f "%Y-%m-%d" "$date_str" +%s 2>/dev/null || echo "$today")
    else
        then=$(date -d "$date_str" +%s 2>/dev/null || echo "$today")
    fi
    echo $(( (today - then) / 86400 ))
}

check_duplicate() {
    local title="$1" file="$2"
    [[ ! -f "$file" ]] && return 1
    local normalized=$(echo "$title" | tr '[:upper:]' '[:lower:]' | tr -d '[:punct:]' | tr -s ' ')
    while IFS= read -r line; do
        if [[ "$line" =~ ^###[[:space:]]*\[[LS][0-9]+\][[:space:]]*\[[^\]]+\][[:space:]]*(.*) ]]; then
            local existing_title="${BASH_REMATCH[1]}"
            local existing_norm=$(echo "$existing_title" | tr '[:upper:]' '[:lower:]' | tr -d '[:punct:]' | tr -s ' ')
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
            IFS= read -r content_line
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

inject_context() {
    local top_n="${1:-5}"
    local tmp_all=$(mktemp)
    
    extract_lessons_for_inject() {
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
        done < "$file"
    }
    
    extract_lessons_for_inject "$SYSTEM_LESSONS_FILE" >> "$tmp_all"
    extract_lessons_for_inject "$PROJECT_LESSONS_FILE" >> "$tmp_all"
    sort -t'|' -k1 -nr "$tmp_all" -o "$tmp_all"
    
    local total=$(wc -l < "$tmp_all" | tr -d ' ')
    (( total == 0 )) && { rm -f "$tmp_all"; return; }

    local system_count=0 project_count=0
    [[ -f "$SYSTEM_LESSONS_FILE" ]] && system_count=$(grep -cE "^### \[S[0-9]+\]" "$SYSTEM_LESSONS_FILE" 2>/dev/null || echo 0)
    [[ -f "$PROJECT_LESSONS_FILE" ]] && project_count=$(grep -cE "^### \[L[0-9]+\]" "$PROJECT_LESSONS_FILE" 2>/dev/null || echo 0)

    echo "LESSONS ACTIVE: $system_count system (S###), $project_count project (L###)"
    echo "Cite with [L###] or [S###] when applying. Type LESSON: to add new."
    echo ""
    echo "TOP LESSONS:"
    head -n "$top_n" "$tmp_all" | while IFS='|' read -r uses id stars title content; do
        echo "  $id $stars $title"
        [[ -n "$content" ]] && echo "    -> $content"
    done
    
    local remaining=$((total - top_n))
    if (( remaining > 0 )); then
        echo ""
        echo "OTHER LESSONS (cite to use):"
        tail -n +"$((top_n + 1))" "$tmp_all" | while IFS='|' read -r uses id stars title content; do
            echo "  $id $stars $title"
        done
    fi
    
    rm -f "$tmp_all"
}

list_lessons() {
    local scope="--all" search="" category="" show_stale=false verbose=false
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

    local current_file="" total_count=0
    for file in "${files[@]}"; do
        local lesson_id="" stars="" title="" uses="" learned="" last="" cat="" content=""
        local file_label
        [[ "$file" == "$SYSTEM_LESSONS_FILE" ]] && file_label="SYSTEM" || file_label="PROJECT ($PROJECT_ROOT)"
        [[ "$current_file" != "$file" ]] && { echo "=== $file_label LESSONS ==="; current_file="$file"; }

        while IFS= read -r line; do
            if [[ "$line" =~ ^###[[:space:]]*(\[[LS][0-9]+\])[[:space:]]*(\[[^\]]+\])[[:space:]]*(.*) ]]; then
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

        if [[ -n "$lesson_id" ]]; then
            output_lesson "$lesson_id" "$stars" "$title" "$uses" "$learned" "$last" "$cat" "$content" \
                "$search" "$category" "$show_stale" "$verbose" && ((total_count++)) || true
        fi
        echo ""
    done
    echo "Total: $total_count lesson(s)"
}

output_lesson() {
    local id="$1" stars="$2" title="$3" uses="$4" learned="$5" last="$6" cat="$7" content="$8"
    local search="$9" category="${10}" show_stale="${11}" verbose="${12}"

    if [[ -n "$search" ]]; then
        local search_lower=$(echo "$search" | tr '[:upper:]' '[:lower:]')
        local title_lower=$(echo "$title" | tr '[:upper:]' '[:lower:]')
        local content_lower=$(echo "$content" | tr '[:upper:]' '[:lower:]')
        [[ "$title_lower" != *"$search_lower"* && "$content_lower" != *"$search_lower"* ]] && return 1
    fi

    [[ -n "$category" && "$cat" != "$category" ]] && return 1

    local days_ago=0 stale_marker=""
    if [[ -n "$last" ]]; then
        days_ago=$(days_since "$last")
        (( days_ago >= STALE_DAYS )) && stale_marker=" [STALE ${days_ago}d]"
    fi

    [[ "$show_stale" == "true" && $days_ago -lt $STALE_DAYS ]] && return 1

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
    echo "Eviction needed: $count > $max_count (not yet implemented)"
}

show_help() {
    cat << 'EOF'
lessons-manager.sh - Tool-agnostic AI coding agent lessons

STORAGE:
  System:  ~/.config/coding-agent-lessons/LESSONS.md
  Project: .coding-agent-lessons/LESSONS.md

COMMANDS:
  list [options]              List lessons
    --project|--system|--all  Scope (default: all)
    --search, -s <term>       Filter by keyword
    --category, -c <cat>      Filter by category
    --stale                   Show stale lessons (60+ days uncited)
    --verbose, -v             Show full details

  add <cat> <title> <content>       Add project lesson
  add --force <cat> <title> <content>  Skip duplicate check
  add-system <cat> <title> <content>   Add system lesson

  cite <id>                   Increment usage count
  edit <id> <content>         Edit lesson content
  delete <id>                 Delete a lesson
  inject [n]                  Output top N lessons for session injection
  reset-reminder              Reset the periodic reminder counter

CATEGORIES: pattern, correction, decision, gotcha, preference

EXAMPLES:
  lessons-manager.sh list --search "spdlog"
  lessons-manager.sh add gotcha "No printf" "Use spdlog instead"
  lessons-manager.sh cite L001
  lessons-manager.sh inject 5
EOF
}

main() {
    local cmd="${1:-help}"; shift || true
    case "$cmd" in
        add)
            if [[ "${1:-}" == "--force" ]]; then
                shift; [[ $# -lt 3 ]] && { echo "Usage: add --force <cat> <title> <content>" >&2; exit 1; }
                add_lesson_force "project" "$1" "$2" "$3"
            else
                [[ $# -lt 3 ]] && { echo "Usage: add <cat> <title> <content>" >&2; exit 1; }
                add_lesson "project" "$1" "$2" "$3"
            fi ;;
        add-system)
            [[ $# -lt 3 ]] && { echo "Usage: add-system <cat> <title> <content>" >&2; exit 1; }
            add_lesson "system" "$1" "$2" "$3" ;;
        cite)
            [[ $# -lt 1 ]] && { echo "Usage: cite <id>" >&2; exit 1; }
            cite_lesson "$1" ;;
        edit)
            [[ $# -lt 2 ]] && { echo "Usage: edit <id> <content>" >&2; exit 1; }
            edit_lesson "$1" "$2" ;;
        delete)
            [[ $# -lt 1 ]] && { echo "Usage: delete <id>" >&2; exit 1; }
            delete_lesson "$1" ;;
        inject) inject_context "${1:-5}" ;;
        list) list_lessons "$@" ;;
        evict) evict_lessons "${1:-}" ;;
        reset-reminder)
            rm -f "$LESSONS_BASE/.reminder-state"
            echo "Reminder counter reset" ;;
        help|--help|-h) show_help ;;
        *) show_help; exit 1 ;;
    esac
}

main "$@"
