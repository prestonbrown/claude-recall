#!/usr/bin/env bash
# Self-contained test runner - manages venv and dependencies automatically
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

# Create venv if missing
if [[ ! -d "$VENV_DIR" ]]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

# Activate venv
source "$VENV_DIR/bin/activate"

# Install/update deps if requirements changed
if [[ "$SCRIPT_DIR/requirements-dev.txt" -nt "$VENV_DIR/.deps-installed" ]]; then
    echo "Installing dependencies..."
    pip install -q -r "$SCRIPT_DIR/requirements-dev.txt"
    touch "$VENV_DIR/.deps-installed"
fi

# Run pytest with all args passed through
python -m pytest "$@"
