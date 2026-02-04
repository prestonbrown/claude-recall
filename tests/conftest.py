"""
Pytest configuration and fixtures for claude-recall tests.
"""

import sys
from pathlib import Path

# Ensure project root is in sys.path for 'core' module imports
# This must happen before any imports from core
_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import os
import pytest


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "slow: marks tests as slow")
    config.addinivalue_line("markers", "integration: marks integration tests")
    config.addinivalue_line("markers", "tui: marks TUI tests")


@pytest.fixture
def temp_state_dir(tmp_path: Path, monkeypatch) -> Path:
    """Create and return a temporary state directory.

    Sets CLAUDE_RECALL_STATE env var and resets debug logger.
    This is available for tests that need explicit access to the state dir.
    """
    state_dir = tmp_path / ".local" / "state" / "claude-recall"
    state_dir.mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_RECALL_STATE", str(state_dir))

    # Reset the debug logger so it picks up the new path
    from core.debug_logger import reset_logger
    reset_logger()

    return state_dir


@pytest.fixture(autouse=True)
def isolate_state_dir(temp_state_dir: Path):
    """Autouse fixture that ensures all tests use isolated state directory.

    This prevents tests from polluting the real ~/.local/state/claude-recall/debug.log
    Simply uses temp_state_dir which does all the actual work.
    """
    yield temp_state_dir

    # Reset logger after test
    from core.debug_logger import reset_logger
    reset_logger()


@pytest.fixture
def isolated_subprocess_env(tmp_path):
    """Fully isolated environment for subprocess tests.

    Uses whitelist approach to prevent env var leakage from parent process.
    """
    home = tmp_path / "home"
    home.mkdir()
    config = home / ".config" / "claude-recall"
    config.mkdir(parents=True)
    state = home / ".local" / "state" / "claude-recall"
    state.mkdir(parents=True)

    # Create empty debug.log to prevent errors
    (state / "debug.log").write_text("")

    # Create isolated TMPDIR
    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir(exist_ok=True)

    # Whitelist only essential system env vars
    safe_vars = {"PATH", "SHELL", "TERM", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE"}
    base_env = {k: v for k, v in os.environ.items() if k in safe_vars}

    return {
        **base_env,
        # Isolated paths
        "HOME": str(home),
        "TMPDIR": str(tmpdir),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_STATE_HOME": str(home / ".local" / "state"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        # Claude Recall specific
        "CLAUDE_RECALL_BASE": str(config),
        "CLAUDE_RECALL_STATE": str(state),
    }
