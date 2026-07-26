#!/bin/bash
# SPDX-License-Identifier: MIT
# lessons-manager.sh - Thin wrapper for the Claude Recall CLI
#
# Delegates to the Go `recall` binary for unified behavior across Claude Code
# and OpenCode. Debug logging is available via CLAUDE_RECALL_DEBUG.
#
# Usage: lessons-manager.sh <command> [args...]
# See: recall --help
#
# Resolution order lets a locally built binary win over an installed one, so
# `cd go && go build ./cmd/...` is enough to test a change through this wrapper.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

for candidate in \
    "${CLAUDE_RECALL_BIN:-}" \
    "$REPO_ROOT/go/bin/recall" \
    "$REPO_ROOT/go/recall" \
    "$HOME/.local/bin/recall"
do
    if [[ -n "$candidate" && -x "$candidate" ]]; then
        exec "$candidate" "$@"
    fi
done

if command -v recall >/dev/null 2>&1; then
    exec recall "$@"
fi

echo "Error: the 'recall' binary was not found." >&2
echo "Build it with: cd \"$REPO_ROOT/go\" && go build -o bin/recall ./cmd/recall" >&2
echo "Or set CLAUDE_RECALL_BIN to its path." >&2
exit 1
