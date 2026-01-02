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
PYTHON_MANAGER="$SCRIPT_DIR/cli.py"

# Verify Python manager exists
if [[ ! -f "$PYTHON_MANAGER" ]]; then
    echo "Error: Python manager not found at $PYTHON_MANAGER" >&2
    exit 1
fi

# Pass through all arguments to Python
exec python3 "$PYTHON_MANAGER" "$@"
