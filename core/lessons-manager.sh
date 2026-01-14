#!/bin/bash
# SPDX-License-Identifier: MIT
# lessons-manager.sh - Thin wrapper for Python lessons manager
#
# This script delegates to the Python implementation for unified behavior
# across Claude Code and OpenCode. Debug logging is available via LESSONS_DEBUG.
#
# Usage: lessons-manager.sh <command> [args...]
# See: python3 lessons_manager.py --help

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Find cli.py - check same directory first, then core/ subdirectory
# (handles both development and installed layouts)
if [[ -f "$SCRIPT_DIR/cli.py" ]]; then
    PYTHON_MANAGER="$SCRIPT_DIR/cli.py"
elif [[ -f "$SCRIPT_DIR/core/cli.py" ]]; then
    PYTHON_MANAGER="$SCRIPT_DIR/core/cli.py"
else
    echo "Error: Python manager not found at $SCRIPT_DIR/cli.py or $SCRIPT_DIR/core/cli.py" >&2
    exit 1
fi

# Pass through all arguments to Python
exec python3 "$PYTHON_MANAGER" "$@"
