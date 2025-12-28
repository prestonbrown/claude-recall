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

# Generate lesson rating display: [total|velocity]
# Left side: logarithmic total uses (spreads high-value lessons better)
# Right side: velocity/recency (14-day activity indicator)
lesson_rating() {
    local uses=$1
    local velocity=${2:-0}

    # Left side: logarithmic total uses scale
    # 1-2=*, 3-5=**, 6-12=***, 13-30=****, 31+=*****
    local left=""
    if (( uses >= 31 )); then left="*****"
    elif (( uses >= 13 )); then left="****-"
    elif (( uses >= 6 )); then left="***--"
    elif (( uses >= 3 )); then left="**---"
    elif (( uses >= 1 )); then left="*----"
    else left="-----"; fi

    # Right side: velocity (recent 14-day citation activity)
    # Uses bc for float comparison, with fallback for missing bc
    local right="-----"
    if command -v bc >/dev/null 2>&1; then
        if (( $(echo "$velocity >= 4.5" | bc -l 2>/dev/null || echo 0) )); then right="****+"
        elif (( $(echo "$velocity >= 3.5" | bc -l 2>/dev/null || echo 0) )); then right="***--"
        elif (( $(echo "$velocity >= 2.5" | bc -l 2>/dev/null || echo 0) )); then right="**---"
        elif (( $(echo "$velocity >= 1.5" | bc -l 2>/dev/null || echo 0) )); then right="*----"
        elif (( $(echo "$velocity >= 0.5" | bc -l 2>/dev/null || echo 0) )); then right="+----"
        fi
    else
        # Fallback: treat velocity as integer
        local vel_int=${velocity%.*}
        if (( vel_int >= 5 )); then right="****+"
        elif (( vel_int >= 4 )); then right="***--"
        elif (( vel_int >= 3 )); then right="**---"
        elif (( vel_int >= 2 )); then right="*----"
        elif (( vel_int >= 1 )); then right="+----"
        fi
    fi

    echo "[$left|$right]"
}

# Backward compatibility alias
uses_to_stars() {
    lesson_rating "$1" 0
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
    local stars=$(lesson_rating 1 0)
    cat >> "$file" << EOF

### [$lesson_id] $stars $title
- **Uses**: 1 | **Velocity**: 0 | **Learned**: $date_learned | **Last**: $date_learned | **Category**: $category
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
    local stars=$(lesson_rating 1 0)
    cat >> "$file" << EOF

### [$lesson_id] $stars $title
- **Uses**: 1 | **Velocity**: 0 | **Learned**: $date_learned | **Last**: $date_learned | **Category**: $category
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

    local tmp_file=$(mktemp) found=false new_uses=0 new_velocity=0
    while IFS= read -r line || [[ -n "$line" ]]; do
        if [[ "$line" =~ ^###[[:space:]]*\[($lesson_id)\][[:space:]]*\[([*+|/\ -]+)\][[:space:]]*(.*) ]]; then
            found=true
            local title="${BASH_REMATCH[3]}"
            IFS= read -r meta_line
            if [[ "$meta_line" =~ \*\*Uses\*\*:[[:space:]]*([0-9]+) ]]; then
                local old_uses="${BASH_REMATCH[1]}"
                # Cap uses at 100 - no functional difference beyond that
                if (( old_uses >= 100 )); then
                    new_uses=100
                else
                    new_uses=$((old_uses + 1))
                fi

                # Parse velocity (default 0 for old-format lessons)
                local old_velocity=0
                if [[ "$meta_line" =~ \*\*Velocity\*\*:[[:space:]]*([0-9.]+) ]]; then
                    old_velocity="${BASH_REMATCH[1]}"
                fi
                # Increment velocity by 1
                if command -v bc >/dev/null 2>&1; then
                    new_velocity=$(echo "$old_velocity + 1" | bc -l)
                else
                    new_velocity=$((${old_velocity%.*} + 1))
                fi

                local new_stars=$(lesson_rating $new_uses $new_velocity)
                echo "### [$lesson_id] $new_stars $title" >> "$tmp_file"

                # Update metadata: Uses, Velocity, Last
                local updated_meta="$meta_line"
                updated_meta=$(echo "$updated_meta" | sed -E "s/\*\*Uses\*\*:[[:space:]]*[0-9]+/**Uses**: $new_uses/")
                updated_meta=$(echo "$updated_meta" | sed -E "s/\*\*Last\*\*:[[:space:]]*[0-9-]+/**Last**: $today/")

                # Handle Velocity field (add if missing, update if present)
                if [[ "$meta_line" =~ \*\*Velocity\*\* ]]; then
                    updated_meta=$(echo "$updated_meta" | sed -E "s/\*\*Velocity\*\*:[[:space:]]*[0-9.]+/**Velocity**: $new_velocity/")
                else
                    # Insert Velocity after Uses for old-format lessons
                    updated_meta=$(echo "$updated_meta" | sed -E "s/(\*\*Uses\*\*:[[:space:]]*[0-9]+)/\1 | **Velocity**: $new_velocity/")
                fi
                echo "$updated_meta" >> "$tmp_file"
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

promote_lesson() {
    local lesson_id="$1"

    # Validate: must be a project lesson (L###)
    [[ ! "$lesson_id" =~ ^L[0-9]+$ ]] && { echo "Error: Can only promote project lessons (L###)" >&2; return 1; }
    [[ ! -f "$PROJECT_LESSONS_FILE" ]] && { echo "Project lessons file not found" >&2; return 1; }
    grep -q "\[$lesson_id\]" "$PROJECT_LESSONS_FILE" || { echo "Lesson $lesson_id not found in project" >&2; return 1; }

    # Extract lesson data from project file
    local stars="" title="" uses="" velocity="" learned="" last="" category="" content=""
    local in_lesson=false
    while IFS= read -r line; do
        if [[ "$line" =~ ^###[[:space:]]*\[$lesson_id\][[:space:]]*(\[[^\]]+\])[[:space:]]*(.*) ]]; then
            in_lesson=true
            stars="${BASH_REMATCH[1]}"
            title="${BASH_REMATCH[2]}"
        elif $in_lesson; then
            if [[ "$line" =~ \*\*Uses\*\*:[[:space:]]*([0-9]+) ]]; then
                uses="${BASH_REMATCH[1]}"
                [[ "$line" =~ \*\*Velocity\*\*:[[:space:]]*([0-9.]+) ]] && velocity="${BASH_REMATCH[1]}"
                [[ "$line" =~ \*\*Learned\*\*:[[:space:]]*([0-9-]+) ]] && learned="${BASH_REMATCH[1]}"
                [[ "$line" =~ \*\*Last\*\*:[[:space:]]*([0-9-]+) ]] && last="${BASH_REMATCH[1]}"
                [[ "$line" =~ \*\*Category\*\*:[[:space:]]*([a-z]+) ]] && category="${BASH_REMATCH[1]}"
            elif [[ "$line" =~ ^\>[[:space:]]*(.*) ]]; then
                content="${BASH_REMATCH[1]}"
                break
            fi
        fi
    done < "$PROJECT_LESSONS_FILE"

    [[ -z "$title" ]] && { echo "Failed to extract lesson data" >&2; return 1; }

    # Initialize system file if needed
    init_lessons_file "$SYSTEM_LESSONS_FILE" "system"

    # Get next system lesson ID
    local new_id=$(get_next_id "$SYSTEM_LESSONS_FILE" "S")

    # Build metadata line (include Velocity if present)
    local meta_line="- **Uses**: $uses"
    [[ -n "$velocity" ]] && meta_line+=" | **Velocity**: $velocity"
    meta_line+=" | **Learned**: $learned | **Last**: $last | **Category**: $category"

    # Add to system file
    cat >> "$SYSTEM_LESSONS_FILE" << EOF

### [$new_id] $stars $title
$meta_line
> $content

EOF

    # Remove from project file
    local tmp_file=$(mktemp) skip_until_next=false
    while IFS= read -r line || [[ -n "$line" ]]; do
        if [[ "$line" =~ ^###[[:space:]]*\[$lesson_id\] ]]; then
            skip_until_next=true
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
    done < "$PROJECT_LESSONS_FILE"
    mv "$tmp_file" "$PROJECT_LESSONS_FILE"

    echo "Promoted $lesson_id -> $new_id: $title"
    echo "Uses: $uses (threshold: $SYSTEM_PROMOTION_THRESHOLD)"
}

inject_context() {
    local top_n="${1:-5}"
    local tmp_all=$(mktemp)
    
    extract_lessons_for_inject() {
        local file="$1"
        [[ ! -f "$file" ]] && return
        local lesson_id="" stars="" title="" uses="" content=""
        while IFS= read -r line; do
            # Match both old format [***--/-----] and new format [***--|-----]
            if [[ "$line" =~ ^###[[:space:]]*(\[[LS][0-9]+\])[[:space:]]*(\[[*+|/\ -]+\])[[:space:]]*(.*) ]]; then
                lesson_id="${BASH_REMATCH[1]}"; stars="${BASH_REMATCH[2]}"; title="${BASH_REMATCH[3]}"
            elif [[ -n "$lesson_id" && "$line" =~ \*\*Uses\*\*:[[:space:]]*([0-9]+) ]]; then
                uses="${BASH_REMATCH[1]}"
            elif [[ -n "$lesson_id" && "$line" =~ ^\>[[:space:]]*(.*) ]]; then
                content="${BASH_REMATCH[1]}"
                # Use ~ as delimiter (stars now contain | which conflicts with |)
                echo "$uses~$lesson_id~$stars~$title~$content"
                lesson_id=""
            fi
        done < "$file"
    }

    extract_lessons_for_inject "$SYSTEM_LESSONS_FILE" >> "$tmp_all"
    extract_lessons_for_inject "$PROJECT_LESSONS_FILE" >> "$tmp_all"
    sort -t'~' -k1 -nr "$tmp_all" -o "$tmp_all"
    
    local total=$(wc -l < "$tmp_all" | tr -d ' ')
    (( total == 0 )) && { rm -f "$tmp_all"; return; }

    local system_count=0 project_count=0
    [[ -f "$SYSTEM_LESSONS_FILE" ]] && system_count=$(grep -cE "^### \[S[0-9]+\]" "$SYSTEM_LESSONS_FILE" 2>/dev/null || echo 0)
    [[ -f "$PROJECT_LESSONS_FILE" ]] && project_count=$(grep -cE "^### \[L[0-9]+\]" "$PROJECT_LESSONS_FILE" 2>/dev/null || echo 0)

    echo "LESSONS ACTIVE: $system_count system (S###), $project_count project (L###)"
    echo "Cite with [L###] or [S###] when applying. Type LESSON: to add new."
    echo ""
    echo "TOP LESSONS:"
    head -n "$top_n" "$tmp_all" | while IFS='~' read -r uses id stars title content; do
        echo "  $id $stars $title"
        [[ -n "$content" ]] && echo "    -> $content"
    done

    local remaining=$((total - top_n))
    if (( remaining > 0 )); then
        echo ""
        echo "OTHER LESSONS (cite to use):"
        tail -n +"$((top_n + 1))" "$tmp_all" | while IFS='~' read -r uses id stars title content; do
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

# Update a lesson's uses and/or velocity (for decay)
# Usage: update_lesson_metadata <lesson_id> <new_uses> <new_velocity> <file>
# Pass empty string "" for uses or velocity to leave unchanged
update_lesson_metadata() {
    local lesson_id="$1" new_uses="$2" new_velocity="$3" file="$4"
    [[ ! -f "$file" ]] && return 1

    local tmp_file=$(mktemp) found=false
    while IFS= read -r line || [[ -n "$line" ]]; do
        if [[ "$line" =~ ^###[[:space:]]*\[($lesson_id)\][[:space:]]*\[([*+|/\ -]+)\][[:space:]]*(.*) ]]; then
            found=true
            local title="${BASH_REMATCH[3]}"
            IFS= read -r meta_line

            # Parse current values for rating calculation
            local uses_for_rating="$new_uses"
            local velocity_for_rating="$new_velocity"

            if [[ -z "$uses_for_rating" ]]; then
                [[ "$meta_line" =~ \*\*Uses\*\*:[[:space:]]*([0-9]+) ]] && uses_for_rating="${BASH_REMATCH[1]}"
            fi
            if [[ -z "$velocity_for_rating" ]]; then
                if [[ "$meta_line" =~ \*\*Velocity\*\*:[[:space:]]*([0-9.]+) ]]; then
                    velocity_for_rating="${BASH_REMATCH[1]}"
                else
                    velocity_for_rating="0"
                fi
            fi

            local new_stars=$(lesson_rating "${uses_for_rating:-1}" "${velocity_for_rating:-0}")
            echo "### [$lesson_id] $new_stars $title" >> "$tmp_file"

            # Update metadata fields as needed
            local updated_meta="$meta_line"
            if [[ -n "$new_uses" ]]; then
                updated_meta=$(echo "$updated_meta" | sed -E "s/\*\*Uses\*\*:[[:space:]]*[0-9]+/**Uses**: $new_uses/")
            fi
            if [[ -n "$new_velocity" ]]; then
                if [[ "$meta_line" =~ \*\*Velocity\*\* ]]; then
                    updated_meta=$(echo "$updated_meta" | sed -E "s/\*\*Velocity\*\*:[[:space:]]*[0-9.]+/**Velocity**: $new_velocity/")
                else
                    # Add Velocity field if missing
                    updated_meta=$(echo "$updated_meta" | sed -E "s/(\*\*Uses\*\*:[[:space:]]*[0-9]+)/\1 | **Velocity**: $new_velocity/")
                fi
            fi
            echo "$updated_meta" >> "$tmp_file"
        else
            echo "$line" >> "$tmp_file"
        fi
    done < "$file"

    if $found; then
        mv "$tmp_file" "$file"
        return 0
    else
        rm "$tmp_file"
        return 1
    fi
}

# Backward compatibility wrapper
update_lesson_uses() {
    local lesson_id="$1" new_uses="$2" file="$3"
    update_lesson_metadata "$lesson_id" "$new_uses" "" "$file"
}

# Decay lessons: velocity (50% half-life for all) and uses (stale lessons only)
# Only runs if there was coding activity since last decay (to avoid penalizing vacations)
decay_lessons() {
    local decay_period=${1:-30}  # Days of staleness before uses decay kicks in
    local state_dir="${LESSONS_BASE}/.citation-state"
    local decay_state="${LESSONS_BASE}/.decay-last-run"

    # Check if there was recent activity (sessions since last decay)
    local recent_sessions=0
    if [[ -d "$state_dir" && -f "$decay_state" ]]; then
        # Count checkpoint files modified since last decay
        recent_sessions=$(find "$state_dir" -type f -newer "$decay_state" 2>/dev/null | wc -l | tr -d ' ')
    elif [[ -d "$state_dir" ]]; then
        # First decay run - count all checkpoints as "recent"
        recent_sessions=$(find "$state_dir" -type f 2>/dev/null | wc -l | tr -d ' ')
    fi

    # Skip decay if no coding sessions occurred (vacation mode)
    if [[ $recent_sessions -eq 0 && -f "$decay_state" ]]; then
        echo "No sessions since last decay - skipping (vacation mode)"
        date +%s > "$decay_state"  # Update timestamp anyway
        return 0
    fi

    local decayed_uses=0 decayed_velocity=0
    for lessons_file in "$SYSTEM_LESSONS_FILE" "$PROJECT_LESSONS_FILE"; do
        [[ -f "$lessons_file" ]] || continue

        # PHASE 1: Collect all lessons and their metadata
        local all_lessons=()        # All lesson IDs (for velocity decay)
        local stale_lessons=()      # Stale lessons with uses > 1 (for uses decay)
        local lesson_id="" uses="" velocity="" last=""

        while IFS= read -r line; do
            if [[ "$line" =~ ^###[[:space:]]*\[([LS][0-9]+)\] ]]; then
                # Process previous lesson
                if [[ -n "$lesson_id" ]]; then
                    all_lessons+=("$lesson_id")
                    # Check if stale and needs uses decay
                    if [[ -n "$uses" && -n "$last" && $uses -gt 1 ]]; then
                        local days_stale=$(days_since "$last")
                        if [[ $days_stale -gt $decay_period ]]; then
                            stale_lessons+=("$lesson_id")
                        fi
                    fi
                fi
                lesson_id="${BASH_REMATCH[1]}"
                uses="" velocity="" last=""
            elif [[ -n "$lesson_id" && "$line" =~ \*\*Uses\*\*:[[:space:]]*([0-9]+) ]]; then
                uses="${BASH_REMATCH[1]}"
                [[ "$line" =~ \*\*Velocity\*\*:[[:space:]]*([0-9.]+) ]] && velocity="${BASH_REMATCH[1]}"
                [[ "$line" =~ \*\*Last\*\*:[[:space:]]*([0-9-]+) ]] && last="${BASH_REMATCH[1]}"
            fi
        done < "$lessons_file"

        # Process last lesson
        if [[ -n "$lesson_id" ]]; then
            all_lessons+=("$lesson_id")
            if [[ -n "$uses" && -n "$last" && $uses -gt 1 ]]; then
                local days_stale=$(days_since "$last")
                if [[ $days_stale -gt $decay_period ]]; then
                    stale_lessons+=("$lesson_id")
                fi
            fi
        fi

        # PHASE 2a: Decay velocity for ALL lessons (50% half-life)
        for lid in "${all_lessons[@]}"; do
            local current_velocity=$(grep -A1 "^### \[$lid\]" "$lessons_file" 2>/dev/null | \
                grep -oE '\*\*Velocity\*\*: [0-9.]+' | grep -oE '[0-9.]+' || echo "")

            # Only decay if velocity exists and is > 0.01 (avoid tiny values)
            if [[ -n "$current_velocity" ]]; then
                local new_velocity
                if command -v bc >/dev/null 2>&1; then
                    new_velocity=$(echo "scale=2; $current_velocity * 0.5" | bc -l)
                    # Round to 0 if very small
                    if (( $(echo "$new_velocity < 0.01" | bc -l) )); then
                        new_velocity="0"
                    fi
                else
                    # Integer fallback: divide by 2
                    new_velocity=$((${current_velocity%.*} / 2))
                fi

                if [[ "$new_velocity" != "$current_velocity" ]]; then
                    update_lesson_metadata "$lid" "" "$new_velocity" "$lessons_file" && ((decayed_velocity++)) || true
                fi
            fi
        done

        # PHASE 2b: Decay uses for stale lessons (uses -1, min 1)
        for lid in "${stale_lessons[@]}"; do
            local current_uses=$(grep -A1 "^### \[$lid\]" "$lessons_file" 2>/dev/null | \
                grep -oE '\*\*Uses\*\*: [0-9]+' | grep -oE '[0-9]+' || echo "0")
            if [[ $current_uses -gt 1 ]]; then
                local new_uses=$((current_uses - 1))
                update_lesson_metadata "$lid" "$new_uses" "" "$lessons_file" && ((decayed_uses++)) || true
            fi
        done
    done

    # Update decay timestamp
    date +%s > "$decay_state"
    echo "Decayed: $decayed_uses uses, $decayed_velocity velocities ($recent_sessions sessions since last run)"
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
  promote <id>                Promote project lesson to system scope
  inject [n]                  Output top N lessons for session injection
  decay [days]                Decay stale lessons (default: 30 days threshold)
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
        promote)
            [[ $# -lt 1 ]] && { echo "Usage: promote <id>" >&2; exit 1; }
            promote_lesson "$1" ;;
        inject) inject_context "${1:-5}" ;;
        list) list_lessons "$@" ;;
        evict) evict_lessons "${1:-}" ;;
        decay) decay_lessons "${1:-30}" ;;
        reset-reminder)
            rm -f "$LESSONS_BASE/.reminder-state"
            echo "Reminder counter reset" ;;
        help|--help|-h) show_help ;;
        *) show_help; exit 1 ;;
    esac
}

main "$@"
