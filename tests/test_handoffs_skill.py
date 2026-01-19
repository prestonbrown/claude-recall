#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Test suite for the /handoffs slash command skill.

These tests verify:
1. Skill files exist at expected paths
2. Frontmatter has required fields
3. Documented commands map to valid CLI subcommands
4. Internal commands are NOT exposed in skill
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest


# =============================================================================
# Constants
# =============================================================================

PROJECT_ROOT = Path(__file__).parent.parent

SKILL_PATHS = [
    PROJECT_ROOT / "plugins" / "claude-recall" / "commands" / "handoffs.md",
    PROJECT_ROOT / "adapters" / "claude-code" / "commands" / "handoffs.md",
]

# User-facing commands that SHOULD be in the skill (sorted for deterministic test order)
EXPECTED_USER_COMMANDS = [
    "add",
    "archive",
    "complete",
    "delete",
    "list",
    "ready",
    "show",
    "update",
]

# Internal commands that should NOT be exposed to users (sorted for deterministic test order)
INTERNAL_COMMANDS = [
    "add-transcript",
    "batch-process",
    "get-session-handoff",
    "inject",
    "inject-todos",
    "process-transcript",
    "resume",
    "set-context",
    "set-session",
    "sync-todos",
]

# Required frontmatter fields
REQUIRED_FRONTMATTER_FIELDS = ["description", "argument-hint", "allowed-tools"]


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def cli_handoff_subcommands() -> set:
    """Get valid handoff subcommands from CLI help."""
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "core" / "cli.py"), "handoff", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"CLI help failed: {result.stderr}"

    # Parse subcommands from help output
    # The help shows: {add,start,update,...} in positional arguments
    match = re.search(r"\{([^}]+)\}", result.stdout)
    if match:
        return {cmd.strip() for cmd in match.group(1).split(",")}
    return set()


def parse_frontmatter(content: str) -> dict:
    """Parse YAML frontmatter from markdown content."""
    if not content.startswith("---"):
        return {}

    end_idx = content.find("---", 3)
    if end_idx == -1:
        return {}

    frontmatter_text = content[3:end_idx].strip()
    result = {}
    for line in frontmatter_text.split("\n"):
        if ":" in line:
            key, value = line.split(":", 1)
            result[key.strip()] = value.strip()
    return result


def extract_commands_from_skill(content: str) -> set:
    """Extract command names mentioned in the skill documentation.

    Looks for commands in:
    - Command tables: | list | ... |
    - Code blocks: `handoff list`, `python3 ... list`
    - Quick reference: /handoffs list
    """
    commands = set()

    # Pattern 1: Table rows with action/command: | list | ...
    # Match rows like: | List all | (none) or `list` | `list` |
    table_pattern = re.compile(r"\|\s*\w[^|]*\|\s*[^|]*\|\s*`?(\w+)`?\s*\|", re.MULTILINE)
    for match in table_pattern.finditer(content):
        cmd = match.group(1).lower()
        if cmd not in {"action", "args", "cli"}:  # Skip header row
            commands.add(cmd)

    # Pattern 2: CLI command examples in code blocks
    # Match: python3 "$RECALL_CLI" list, python3 ... handoff list
    cli_pattern = re.compile(r'(?:handoff|"\$RECALL_CLI")\s+(\w+)', re.IGNORECASE)
    for match in cli_pattern.finditer(content):
        commands.add(match.group(1).lower())

    # Pattern 3: Quick reference: /handoffs list
    quickref_pattern = re.compile(r"/handoffs?\s+(\w+)", re.IGNORECASE)
    for match in quickref_pattern.finditer(content):
        commands.add(match.group(1).lower())

    return commands


# =============================================================================
# Test: Skill Files Exist
# =============================================================================


class TestSkillFilesExist:
    """Test that skill files exist at expected paths."""

    @pytest.mark.parametrize("skill_path", SKILL_PATHS)
    def test_skill_file_exists(self, skill_path: Path):
        """Skill file should exist at expected path."""
        assert skill_path.exists(), f"Skill file not found: {skill_path}"

    def test_both_locations_have_skill(self):
        """Both plugin and adapter locations should have the handoffs skill."""
        for path in SKILL_PATHS:
            assert path.exists(), f"Missing skill at: {path}"


# =============================================================================
# Test: Frontmatter Fields
# =============================================================================


class TestSkillFrontmatter:
    """Test that skill frontmatter has required fields."""

    @pytest.mark.parametrize("skill_path", SKILL_PATHS)
    def test_frontmatter_has_description(self, skill_path: Path):
        """Skill should have description field in frontmatter."""
        content = skill_path.read_text()
        frontmatter = parse_frontmatter(content)
        assert "description" in frontmatter, f"Missing 'description' in {skill_path}"
        assert len(frontmatter["description"]) > 0, "description should not be empty"

    @pytest.mark.parametrize("skill_path", SKILL_PATHS)
    def test_frontmatter_has_argument_hint(self, skill_path: Path):
        """Skill should have argument-hint field in frontmatter."""
        content = skill_path.read_text()
        frontmatter = parse_frontmatter(content)
        assert "argument-hint" in frontmatter, f"Missing 'argument-hint' in {skill_path}"
        assert len(frontmatter["argument-hint"]) > 0, "argument-hint should not be empty"

    @pytest.mark.parametrize("skill_path", SKILL_PATHS)
    def test_frontmatter_has_allowed_tools(self, skill_path: Path):
        """Skill should have allowed-tools field in frontmatter."""
        content = skill_path.read_text()
        frontmatter = parse_frontmatter(content)
        assert "allowed-tools" in frontmatter, f"Missing 'allowed-tools' in {skill_path}"

    @pytest.mark.parametrize("skill_path", SKILL_PATHS)
    def test_allowed_tools_includes_bash_python3(self, skill_path: Path):
        """allowed-tools should include Bash(python3:*)."""
        content = skill_path.read_text()
        frontmatter = parse_frontmatter(content)
        allowed_tools = frontmatter.get("allowed-tools", "")
        assert "Bash(python3:*)" in allowed_tools, (
            f"allowed-tools should include 'Bash(python3:*)' in {skill_path}"
        )


# =============================================================================
# Test: Commands Map to Valid CLI Subcommands
# =============================================================================


class TestCommandsMapToValidCLI:
    """Test that documented commands map to valid CLI subcommands."""

    @pytest.mark.parametrize("skill_path", SKILL_PATHS)
    def test_documented_commands_are_valid(
        self, skill_path: Path, cli_handoff_subcommands: set
    ):
        """All documented commands should be valid CLI subcommands."""
        content = skill_path.read_text()
        documented_commands = extract_commands_from_skill(content)

        invalid_commands = documented_commands - cli_handoff_subcommands
        assert not invalid_commands, (
            f"Invalid commands in {skill_path.name}: {invalid_commands}. "
            f"Valid subcommands are: {cli_handoff_subcommands}"
        )

    @pytest.mark.parametrize("expected_cmd", EXPECTED_USER_COMMANDS)
    def test_expected_user_command_is_documented(self, expected_cmd: str):
        """Each expected user command should be documented in at least one skill file."""
        found_in_any = False
        for skill_path in SKILL_PATHS:
            if skill_path.exists():
                content = skill_path.read_text()
                documented = extract_commands_from_skill(content)
                if expected_cmd in documented:
                    found_in_any = True
                    break

        assert found_in_any, (
            f"Expected user command '{expected_cmd}' not documented in any skill file"
        )

    def test_cli_has_expected_user_commands(self, cli_handoff_subcommands: set):
        """CLI should support all expected user-facing commands."""
        missing = set(EXPECTED_USER_COMMANDS) - cli_handoff_subcommands
        assert not missing, f"CLI missing expected commands: {missing}"


# =============================================================================
# Test: Internal Commands NOT Exposed
# =============================================================================


class TestInternalCommandsNotExposed:
    """Test that internal commands are not exposed in skill documentation."""

    @pytest.mark.parametrize("internal_cmd", INTERNAL_COMMANDS)
    @pytest.mark.parametrize("skill_path", SKILL_PATHS)
    def test_internal_command_not_documented(
        self, internal_cmd: str, skill_path: Path
    ):
        """Internal commands should not be mentioned as user commands."""
        if not skill_path.exists():
            pytest.skip(f"Skill file does not exist: {skill_path}")

        content = skill_path.read_text()
        documented = extract_commands_from_skill(content)

        assert internal_cmd not in documented, (
            f"Internal command '{internal_cmd}' should not be exposed "
            f"as a user command in {skill_path.name}"
        )

    def test_internal_commands_are_valid_cli_subcommands(
        self, cli_handoff_subcommands: set
    ):
        """Verify our list of internal commands are actually valid CLI subcommands."""
        # This ensures our test data is accurate
        invalid = set(INTERNAL_COMMANDS) - cli_handoff_subcommands
        assert not invalid, (
            f"These 'internal' commands don't exist in CLI: {invalid}. "
            "Update INTERNAL_COMMANDS constant."
        )


# =============================================================================
# Test: Content Quality
# =============================================================================


class TestSkillContentQuality:
    """Test skill content quality and structure."""

    @pytest.mark.parametrize("skill_path", SKILL_PATHS)
    def test_skill_has_commands_section(self, skill_path: Path):
        """Skill should have a commands or usage section."""
        content = skill_path.read_text()
        # Look for section headers related to commands
        has_commands_section = any(
            header in content.lower()
            for header in ["## commands", "## usage", "## quick reference"]
        )
        assert has_commands_section, (
            f"Skill should have Commands, Usage, or Quick Reference section: {skill_path}"
        )

    @pytest.mark.parametrize("skill_path", SKILL_PATHS)
    def test_skill_has_examples(self, skill_path: Path):
        """Skill should include example commands."""
        content = skill_path.read_text()
        # Look for code blocks or example sections
        has_examples = "```" in content or "example" in content.lower()
        assert has_examples, f"Skill should include examples: {skill_path}"

    @pytest.mark.parametrize("skill_path", SKILL_PATHS)
    def test_skill_mentions_cli_path(self, skill_path: Path):
        """Skill should explain how to find/use the CLI."""
        content = skill_path.read_text()
        # Should mention RECALL_CLI or the plugin path pattern
        mentions_cli = (
            "RECALL_CLI" in content
            or "cli.py" in content
            or "~/.claude/plugins" in content
        )
        assert mentions_cli, (
            f"Skill should explain how to find/use the CLI: {skill_path}"
        )


# =============================================================================
# Test: Status and Phase Values
# =============================================================================


class TestStatusAndPhaseValues:
    """Test that documented status and phase values match CLI."""

    VALID_STATUSES = ["not_started", "in_progress", "blocked", "ready_for_review", "completed"]
    VALID_PHASES = ["research", "planning", "implementing", "review"]

    @pytest.mark.parametrize("skill_path", SKILL_PATHS)
    def test_documented_statuses_are_valid(self, skill_path: Path):
        """Documented statuses should match actual CLI statuses."""
        content = skill_path.read_text()
        for status in self.VALID_STATUSES:
            # Status should appear in the Statuses section
            assert f"**{status}**" in content, (
                f"Status '{status}' should be documented in {skill_path.name}"
            )

    @pytest.mark.parametrize("skill_path", SKILL_PATHS)
    def test_documented_phases_are_valid(self, skill_path: Path):
        """Documented phases should be mentioned."""
        content = skill_path.read_text()
        for phase in self.VALID_PHASES:
            assert f"**{phase}**" in content.lower() or phase in content.lower(), (
                f"Phase '{phase}' should be documented in {skill_path.name}"
            )

    @pytest.mark.parametrize("skill_path", SKILL_PATHS)
    def test_archived_is_not_listed_as_status(self, skill_path: Path):
        """Archived is a command, not a status - shouldn't be in Statuses section."""
        content = skill_path.read_text()
        # Find the Statuses section
        if "## Statuses" in content:
            statuses_section = content.split("## Statuses")[1].split("##")[0]
            assert "archived" not in statuses_section.lower(), (
                "'archived' should not be listed as a status (it's a separate command)"
            )
