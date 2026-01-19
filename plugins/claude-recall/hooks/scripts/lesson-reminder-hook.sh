#!/bin/bash
# SPDX-License-Identifier: MIT
# lesson-reminder-hook.sh - Periodic lesson reminders for Claude Recall
#
# Called on each UserPromptSubmit. Shows high-star lessons every Nth prompt.
# Counter resets on session start via SessionStart hook.

set -euo pipefail

# Guard against recursive calls from Haiku subprocesses
[[ -n "${LESSONS_SCORING_ACTIVE:-}" ]] && exit 0

# Support new (CLAUDE_RECALL_*), transitional (RECALL_*), and legacy (LESSONS_*) env vars
CLAUDE_RECALL_BASE="${CLAUDE_RECALL_BASE:-${RECALL_BASE:-${LESSONS_BASE:-$HOME/.config/claude-recall}}}"
CLAUDE_RECALL_DEBUG="${CLAUDE_RECALL_DEBUG:-${RECALL_DEBUG:-${LESSONS_DEBUG:-}}}"
# Export legacy names for downstream compatibility
LESSONS_BASE="$CLAUDE_RECALL_BASE"
LESSONS_DEBUG="$CLAUDE_RECALL_DEBUG"

STATE_FILE="$CLAUDE_RECALL_BASE/.reminder-state"
CONFIG_FILE="$HOME/.claude/settings.json"

# Priority: env var > config file > default (12)
if [[ -n "${LESSON_REMIND_EVERY:-}" ]]; then
  REMIND_EVERY="$LESSON_REMIND_EVERY"
elif [[ -f "$CONFIG_FILE" ]]; then
  REMIND_EVERY=$(jq -r '.claudeRecall.remindEvery // 12' "$CONFIG_FILE" 2>/dev/null || echo 12)
else
  REMIND_EVERY=12
fi

# Read current count
COUNT=0
[[ -f "$STATE_FILE" ]] && COUNT=$(cat "$STATE_FILE" 2>/dev/null || echo 0)

# Increment and save
COUNT=$((COUNT + 1))

# Atomic write using temp file + rename
TEMP_FILE="${STATE_FILE}.$$"
echo "$COUNT" > "$TEMP_FILE" && mv "$TEMP_FILE" "$STATE_FILE"

# Only remind on Nth prompt
if (( COUNT % REMIND_EVERY != 0 )); then
  exit 0
fi

# Find lessons file (project first with fallback to legacy paths, then system)
LESSONS_FILE=""
if [[ -n "${PROJECT_ROOT:-}" ]]; then
  # Check new path first, fall back to legacy paths
  if [[ -f "$PROJECT_ROOT/.claude-recall/LESSONS.md" ]]; then
    LESSONS_FILE="$PROJECT_ROOT/.claude-recall/LESSONS.md"
  elif [[ -f "$PROJECT_ROOT/.recall/LESSONS.md" ]]; then
    LESSONS_FILE="$PROJECT_ROOT/.recall/LESSONS.md"
  elif [[ -f "$PROJECT_ROOT/.coding-agent-lessons/LESSONS.md" ]]; then
    LESSONS_FILE="$PROJECT_ROOT/.coding-agent-lessons/LESSONS.md"
  fi
elif [[ -f ".claude-recall/LESSONS.md" ]]; then
  LESSONS_FILE=".claude-recall/LESSONS.md"
elif [[ -f ".recall/LESSONS.md" ]]; then
  LESSONS_FILE=".recall/LESSONS.md"
elif [[ -f ".coding-agent-lessons/LESSONS.md" ]]; then
  LESSONS_FILE=".coding-agent-lessons/LESSONS.md"
fi
# Fall back to system lessons
if [[ -z "$LESSONS_FILE" ]] && [[ -f "$CLAUDE_RECALL_BASE/LESSONS.md" ]]; then
  LESSONS_FILE="$CLAUDE_RECALL_BASE/LESSONS.md"
fi

if [[ -z "$LESSONS_FILE" ]]; then
  exit 0  # No lessons file found, exit silently
fi

# Extract lessons with 3+ stars (pattern: ### [L###] [***...])
# The star pattern in lessons is like [*****/-----] or [***--/-----]
HIGH_STAR=$(grep -E '^###\s*\[[LS][0-9]+\].*\[\*{3,}' "$LESSONS_FILE" 2>/dev/null | head -3)

if [[ -n "$HIGH_STAR" ]]; then
  echo "📚 LESSON CHECK - High-priority lessons to keep in mind:"
  echo "$HIGH_STAR"
  echo ""

  # Log reminded lessons for effectiveness tracking (if debug enabled)
  if [[ "${CLAUDE_RECALL_DEBUG:-0}" -ge 1 ]]; then
    DEBUG_LOG="$CLAUDE_RECALL_BASE/debug.log"
    LESSON_IDS=$(echo "$HIGH_STAR" | grep -oE '\[[LS][0-9]+\]' | tr -d '[]' | tr '\n' ',' | sed 's/,$//')
    TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    echo "{\"timestamp\":\"$TIMESTAMP\",\"event\":\"reminder\",\"lesson_ids\":\"$LESSON_IDS\",\"prompt_count\":$COUNT}" >> "$DEBUG_LOG"
  fi
fi

exit 0
