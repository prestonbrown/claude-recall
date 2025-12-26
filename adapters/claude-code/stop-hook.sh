#!/bin/bash
# SPDX-License-Identifier: MIT
# Claude Code Stop hook - tracks lesson citations from AI responses

set -uo pipefail

MANAGER="$HOME/.config/coding-agent-lessons/lessons-manager.sh"

is_enabled() {
    local config="$HOME/.claude/settings.json"
    [[ -f "$config" ]] && {
        local enabled=$(jq -r '.lessonsSystem.enabled // true' "$config" 2>/dev/null || echo "true")
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

main() {
    is_enabled || exit 0

    local input=$(cat)
    local cwd=$(echo "$input" | jq -r '.cwd // "."' 2>/dev/null || echo ".")
    local project_root=$(find_project_root "$cwd")
    local transcript_path=$(echo "$input" | jq -r '.transcript_path // ""' 2>/dev/null || echo "")
    
    # Expand tilde
    transcript_path="${transcript_path/#\~/$HOME}"
    
    [[ -z "$transcript_path" || ! -f "$transcript_path" ]] && exit 0

    # Extract lesson citations from last 50KB of transcript
    # Strategy: find all [L###]/[S###], but EXCLUDE lesson listings
    # Listings have format: "[L010] [*****" (ID followed by star rating bracket)
    # Real citations: "[L010]:" or "[L010]," or "[L010] says" (no star bracket)
    local citations=$(tail -c 51200 "$transcript_path" 2>/dev/null | \
        grep -oE '\[[LS][0-9]{3}\] ?\[|\[[LS][0-9]{3}\][^[]' | \
        grep -v '\] \[' | grep -v '\]\[' | \
        grep -oE '\[[LS][0-9]{3}\]' | sort -u || true)
    
    [[ -z "$citations" ]] && exit 0

    # Cite each lesson
    local cited_count=0
    while IFS= read -r citation; do
        [[ -z "$citation" ]] && continue
        local lesson_id=$(echo "$citation" | tr -d '[]')
        local result=$(PROJECT_DIR="$project_root" "$MANAGER" cite "$lesson_id" 2>&1 || true)
        if [[ "$result" == OK:* ]]; then
            ((cited_count++)) || true
        fi
    done <<< "$citations"

    (( cited_count > 0 )) && echo "[lessons] $cited_count lesson(s) cited" >&2
    exit 0
}

main
