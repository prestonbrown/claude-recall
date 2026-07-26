#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The version is declared in three places and they must agree.

Claude Code resolves a plugin's cache path from its declared version, so a
stale declaration installs into a directory nobody else writes to: hooks get
synced to one path while the runtime loads another. That is exactly how the
installed cache ended up pinned at 1.2.0 while plugin.json said 1.4.0 and the
marketplace entry still said 0.9.6.

plugin.json is the source of truth - `claude plugin tag` validates it against
the enclosing marketplace entry, and install.sh regenerates the marketplace
version from it. This test is the backstop that catches drift in CI.
"""

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
PLUGIN_JSON = REPO_ROOT / "plugins" / "claude-recall" / ".claude-plugin" / "plugin.json"
MARKETPLACE_JSON = REPO_ROOT / ".claude-plugin" / "marketplace.json"
VERSION_PY = REPO_ROOT / "core" / "_version.py"

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def plugin_version() -> str:
    return json.loads(PLUGIN_JSON.read_text())["version"]


def marketplace_version() -> str:
    entries = json.loads(MARKETPLACE_JSON.read_text())["plugins"]
    matching = [e for e in entries if e["name"] == "claude-recall"]
    assert matching, "marketplace.json has no claude-recall entry"
    return matching[0]["version"]


def python_version() -> str:
    match = re.search(r'__version__\s*=\s*"([^"]+)"', VERSION_PY.read_text())
    assert match, f"no __version__ found in {VERSION_PY}"
    return match.group(1)


def test_plugin_version_is_semver():
    assert SEMVER.match(plugin_version()), (
        f"plugin.json version {plugin_version()!r} is not MAJOR.MINOR.PATCH; "
        f"the cache directory is named after it"
    )


def test_marketplace_matches_plugin():
    assert marketplace_version() == plugin_version(), (
        f"marketplace.json declares {marketplace_version()} but plugin.json declares "
        f"{plugin_version()}. Claude Code resolves the cache path from the marketplace "
        f"entry at install time, so a mismatch installs into the wrong directory. "
        f"install.sh regenerates this - run it, or sync by hand."
    )


def test_python_version_matches_plugin():
    assert python_version() == plugin_version(), (
        f"core/_version.py declares {python_version()} but plugin.json declares "
        f"{plugin_version()}"
    )


@pytest.mark.parametrize("path", [PLUGIN_JSON, MARKETPLACE_JSON])
def test_manifests_are_valid_json(path):
    """A malformed manifest makes `claude plugin install` fail opaquely."""
    json.loads(path.read_text())
