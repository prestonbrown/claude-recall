#!/usr/bin/env bash
# Self-contained test runner - manages venv and dependencies automatically
#
# Usage: ./run-tests.sh [mode] [pytest-args...]
#
# Modes:
#   fast        Unit tests only, parallel (default)
#   full        All tests, parallel
#   integration Integration tests only
#   e2e         Live OpenCode adapter e2e (real model calls, NOT hermetic CI)
#   bun         TypeScript unit tests only (tests/plugin_ts/, tsc + node)
#
# Examples:
#   ./run-tests.sh              # Fast mode (unit tests)
#   ./run-tests.sh full         # All tests
#   ./run-tests.sh fast -v      # Verbose unit tests
#   ./run-tests.sh full -k foo  # All tests matching 'foo'
#   ./run-tests.sh e2e          # Live adapter proof (E2E_MODEL=provider/model)
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

# Optional TypeScript unit tests (tests/plugin_ts/). Runs on stock Node via
# tsc + node --test (typescript fetched by npm on first run). Skips cleanly
# when node/npm are unavailable; set RUN_TS_TESTS=0 to disable explicitly.
run_ts_tests() {
    if [[ "${RUN_TS_TESTS:-1}" == "0" ]]; then
        echo "Skipping TypeScript tests (RUN_TS_TESTS=0)"
        return 0
    fi
    if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
        echo "Skipping TypeScript tests (node/npm not found)"
        return 0
    fi
    local ts_dir="$SCRIPT_DIR/tests/plugin_ts"
    if [[ ! -f "$ts_dir/node_modules/.package-lock.json" ]]; then
        (cd "$ts_dir" && npm install --no-audit --no-fund >/dev/null) || {
            echo "Skipping TypeScript tests (npm install failed)"
            return 0
        }
    fi
    echo "Running TypeScript unit tests (node $(node --version))..."
    (cd "$ts_dir" && npm test --silent)
}

# Parse mode argument. NOTE: bare `shift` under `set -e` kills the script when
# no positional args were given - only shift when $1 is a known mode keyword.
MODE="fast"
case "${1:-}" in
    full|integration|e2e|bun|ts|fast)
        MODE="$1"
        shift
        ;;
esac
case "$MODE" in
    full)
        echo "Running full test suite (parallel, no live e2e)..."
        python -m pytest -n auto -m "not e2e" "$@"
        run_ts_tests
        ;;
    integration)
        echo "Running integration tests..."
        python -m pytest tests/test_integration.py "$@"
        ;;
    e2e)
        echo "Running live OpenCode adapter e2e (real model calls; E2E_MODEL=${E2E_MODEL:-moonshotai/kimi-k3})..."
        python -m pytest tests/test_opencode_e2e.py -m e2e -v "$@"
        ;;
    bun|ts)
        run_ts_tests
        ;;
    fast)
        echo "Running fast tests (parallel, no TUI/integration/e2e)..."
        python -m pytest -n auto -m "not integration and not e2e" "$@"
        run_ts_tests
        ;;
esac
