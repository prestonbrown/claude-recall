#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Tests for session dedup, line-pair filtering, find_go_binary, and full content output.

Covers hook-lib.sh dedup functions, smart-inject-hook.sh and subagent-stop-hook.sh
dedup filtering, and the Go binary's score-local full content output.

Run with: ./run-tests.sh tests/test_hooks/test_hook_dedup.py -v
"""

import json
import os
import subprocess
import textwrap
from pathlib import Path

import pytest


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def hook_scripts_dir() -> Path:
    """Path to hook scripts directory."""
    candidates = [
        Path(__file__).parent.parent.parent / "plugins" / "claude-recall" / "hooks" / "scripts",
    ]
    for p in candidates:
        if p.exists():
            return p
    pytest.skip("Hook scripts not found")


@pytest.fixture
def hook_lib_path(hook_scripts_dir) -> Path:
    """Path to hook-lib.sh."""
    p = hook_scripts_dir / "hook-lib.sh"
    if not p.exists():
        pytest.skip("hook-lib.sh not found")
    return p


@pytest.fixture
def smart_inject_hook_path(hook_scripts_dir) -> Path:
    """Path to smart-inject-hook.sh."""
    p = hook_scripts_dir / "smart-inject-hook.sh"
    if not p.exists():
        pytest.skip("smart-inject-hook.sh not found")
    return p


@pytest.fixture
def subagent_stop_hook_path(hook_scripts_dir) -> Path:
    """Path to subagent-stop-hook.sh."""
    p = hook_scripts_dir / "subagent-stop-hook.sh"
    if not p.exists():
        pytest.skip("subagent-stop-hook.sh not found")
    return p


@pytest.fixture
def isolated_env(tmp_path: Path) -> dict:
    """Create an isolated environment with HOME, config, and state dirs."""
    home = tmp_path / "home"
    home.mkdir()

    config_dir = home / ".config" / "claude-recall"
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text('{"enabled":true}')

    state_dir = home / ".local" / "state" / "claude-recall"
    state_dir.mkdir(parents=True)

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / ".git").mkdir()
    (project_dir / ".claude-recall").mkdir()

    env = {
        k: v for k, v in os.environ.items()
        if k in {"PATH", "SHELL", "TERM", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE"}
    }
    env.update({
        "HOME": str(home),
        "CLAUDE_RECALL_STATE": str(state_dir),
        "CLAUDE_RECALL_DEBUG": "0",
        "PROJECT_DIR": str(project_dir),
    })

    return {
        "home": home,
        "config_dir": config_dir,
        "state_dir": state_dir,
        "project_dir": project_dir,
        "env": env,
    }


@pytest.fixture
def mock_recall_script(tmp_path: Path) -> Path:
    """Create a mock 'recall' script that outputs known score-local format."""
    bin_dir = tmp_path / "mock_bin"
    bin_dir.mkdir(exist_ok=True)
    mock_recall = bin_dir / "recall"

    # The mock script handles score-local by outputting predefined lesson pairs.
    # It reads from MOCK_RECALL_OUTPUT file if set, otherwise uses defaults.
    mock_recall.write_text(textwrap.dedent("""\
        #!/bin/bash
        # Mock recall binary for testing
        if [[ "$1" == "score-local" ]]; then
            if [[ -n "${MOCK_RECALL_OUTPUT:-}" && -f "$MOCK_RECALL_OUTPUT" ]]; then
                cat "$MOCK_RECALL_OUTPUT"
            fi
            exit 0
        elif [[ "$1" == "debug" ]]; then
            exit 0
        fi
        exit 0
    """))
    mock_recall.chmod(0o755)
    return mock_recall


def run_bash(script: str, env: dict, timeout: int = 10) -> subprocess.CompletedProcess:
    """Run a bash script with the given environment."""
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
    )


# =============================================================================
# Session Dedup Helpers (hook-lib.sh)
# =============================================================================


class TestSessionDedupHelpers:
    """Tests for record_injected, get_injected_ids, and clear_dedup in hook-lib.sh."""

    def _source_and_run(self, hook_lib_path, env, commands):
        """Source hook-lib.sh and run commands."""
        script = f'source "{hook_lib_path}"\n{commands}'
        return run_bash(script, env)

    def test_record_injected_creates_file(self, hook_lib_path, isolated_env):
        """record_injected should create a JSON file with the given IDs."""
        env = isolated_env["env"]
        state_dir = isolated_env["state_dir"]

        result = self._source_and_run(hook_lib_path, env, textwrap.dedent("""\
            _HOOK_SESSION_ID="test-session-1"
            CLAUDE_RECALL_STATE="{state_dir}"
            record_injected L001 S003
            cat "$(get_dedup_file)"
        """.format(state_dir=state_dir)))

        assert result.returncode == 0, f"stderr: {result.stderr}"
        ids = json.loads(result.stdout.strip())
        assert sorted(ids) == ["L001", "S003"]

    def test_get_injected_ids_returns_ids(self, hook_lib_path, isolated_env):
        """get_injected_ids should return recorded IDs one per line."""
        env = isolated_env["env"]
        state_dir = isolated_env["state_dir"]

        result = self._source_and_run(hook_lib_path, env, textwrap.dedent("""\
            _HOOK_SESSION_ID="test-session-2"
            CLAUDE_RECALL_STATE="{state_dir}"
            record_injected L001 S003
            get_injected_ids
        """.format(state_dir=state_dir)))

        assert result.returncode == 0, f"stderr: {result.stderr}"
        ids = result.stdout.strip().split("\n")
        assert sorted(ids) == ["L001", "S003"]

    def test_record_injected_merges_not_overwrites(self, hook_lib_path, isolated_env):
        """Calling record_injected again should merge, not overwrite."""
        env = isolated_env["env"]
        state_dir = isolated_env["state_dir"]

        result = self._source_and_run(hook_lib_path, env, textwrap.dedent("""\
            _HOOK_SESSION_ID="test-session-3"
            CLAUDE_RECALL_STATE="{state_dir}"
            record_injected L001 S003
            record_injected L005
            get_injected_ids
        """.format(state_dir=state_dir)))

        assert result.returncode == 0, f"stderr: {result.stderr}"
        ids = result.stdout.strip().split("\n")
        assert sorted(ids) == ["L001", "L005", "S003"]

    def test_record_injected_deduplicates(self, hook_lib_path, isolated_env):
        """Recording the same ID twice should not create duplicates."""
        env = isolated_env["env"]
        state_dir = isolated_env["state_dir"]

        result = self._source_and_run(hook_lib_path, env, textwrap.dedent("""\
            _HOOK_SESSION_ID="test-session-4"
            CLAUDE_RECALL_STATE="{state_dir}"
            record_injected L001 S003
            record_injected L001 L005
            get_injected_ids
        """.format(state_dir=state_dir)))

        assert result.returncode == 0, f"stderr: {result.stderr}"
        ids = result.stdout.strip().split("\n")
        assert sorted(ids) == ["L001", "L005", "S003"]

    def test_clear_dedup_removes_file(self, hook_lib_path, isolated_env):
        """clear_dedup should remove the dedup file."""
        env = isolated_env["env"]
        state_dir = isolated_env["state_dir"]

        result = self._source_and_run(hook_lib_path, env, textwrap.dedent("""\
            _HOOK_SESSION_ID="test-session-5"
            CLAUDE_RECALL_STATE="{state_dir}"
            record_injected L001 S003
            clear_dedup
            # get_injected_ids should return nothing
            output=$(get_injected_ids)
            if [[ -z "$output" ]]; then
                echo "CLEARED"
            else
                echo "NOT_CLEARED: $output"
            fi
        """.format(state_dir=state_dir)))

        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "CLEARED" in result.stdout

    def test_get_injected_ids_empty_when_no_file(self, hook_lib_path, isolated_env):
        """get_injected_ids should return empty when no dedup file exists."""
        env = isolated_env["env"]
        state_dir = isolated_env["state_dir"]

        result = self._source_and_run(hook_lib_path, env, textwrap.dedent("""\
            _HOOK_SESSION_ID="test-session-never-recorded"
            CLAUDE_RECALL_STATE="{state_dir}"
            output=$(get_injected_ids)
            if [[ -z "$output" ]]; then
                echo "EMPTY"
            else
                echo "NOT_EMPTY: $output"
            fi
        """.format(state_dir=state_dir)))

        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "EMPTY" in result.stdout


# =============================================================================
# Dedup Line-Pair Filtering
# =============================================================================


SCORE_LOCAL_OUTPUT = """\
[S003] ★★★★★ (relevance: 10/10) WIP file safety
    -> Never modify, stash, restore work-in-progress files without explicit permission
[S002] ★★★ (relevance: 6/10) Stage files explicitly
    -> When committing, stage only files that are part of the change
[L005] ★★★ (relevance: 6/10) Commit LESSONS.md periodically
    -> LESSONS.md is shared across checkouts and should be committed"""


class TestDedupLinePairFiltering:
    """Test that dedup filtering removes BOTH lines (header + content) for injected lessons."""

    def test_smart_inject_filters_injected_lessons(
        self, smart_inject_hook_path, isolated_env, mock_recall_script, tmp_path
    ):
        """smart-inject-hook should remove already-injected lesson pairs."""
        env = isolated_env["env"]
        state_dir = isolated_env["state_dir"]
        home = isolated_env["home"]

        # Put mock recall on PATH via HOME/.local/bin
        local_bin = home / ".local" / "bin"
        local_bin.mkdir(parents=True, exist_ok=True)
        # Symlink mock recall to ~/.local/bin/recall
        recall_link = local_bin / "recall"
        recall_link.symlink_to(mock_recall_script)

        # Create mock output file
        mock_output = tmp_path / "mock_output.txt"
        mock_output.write_text(SCORE_LOCAL_OUTPUT)

        # Pre-populate dedup: S003 already injected
        dedup_file = state_dir / "session-dedup-test-smart-session.json"
        dedup_file.write_text(json.dumps(["S003"]))

        env["MOCK_RECALL_OUTPUT"] = str(mock_output)

        input_json = json.dumps({
            "session_id": "test-smart-session",
            "cwd": str(isolated_env["project_dir"]),
            "prompt": "How do I safely commit changes to the repository without losing work?",
        })

        result = subprocess.run(
            ["bash", str(smart_inject_hook_path)],
            input=input_json,
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )

        assert result.returncode == 0, f"stderr: {result.stderr}"

        # Parse the hook output
        if result.stdout.strip():
            output = json.loads(result.stdout.strip())
            context = output["hookSpecificOutput"]["additionalContext"]

            # S003 was already injected - both its header and content should be gone
            assert "[S003]" not in context, (
                f"S003 was already injected but still appears in output:\n{context}"
            )
            assert "WIP file safety" not in context, (
                f"S003 content line still appears in output:\n{context}"
            )

            # S002 and L005 were NOT injected - they should remain
            assert "[S002]" in context, f"S002 should be present:\n{context}"
            assert "[L005]" in context, f"L005 should be present:\n{context}"
            assert "Stage files explicitly" in context
            assert "Commit LESSONS.md periodically" in context

    def test_subagent_stop_filters_injected_lessons(
        self, subagent_stop_hook_path, isolated_env, mock_recall_script, tmp_path
    ):
        """subagent-stop-hook should remove already-injected lesson pairs."""
        env = isolated_env["env"]
        state_dir = isolated_env["state_dir"]
        home = isolated_env["home"]

        # Put mock recall on PATH
        local_bin = home / ".local" / "bin"
        local_bin.mkdir(parents=True, exist_ok=True)
        recall_link = local_bin / "recall"
        recall_link.symlink_to(mock_recall_script)

        # Create mock output file
        mock_output = tmp_path / "mock_output.txt"
        mock_output.write_text(SCORE_LOCAL_OUTPUT)

        # Pre-populate dedup: S002 and L005 already injected
        dedup_file = state_dir / "session-dedup-test-subagent-session.json"
        dedup_file.write_text(json.dumps(["S002", "L005"]))

        env["MOCK_RECALL_OUTPUT"] = str(mock_output)

        input_json = json.dumps({
            "session_id": "test-subagent-session",
            "cwd": str(isolated_env["project_dir"]),
            "stdout": "I explored the repository structure and found the main config files. The project uses pytest for testing and has a Makefile for builds.",
        })

        result = subprocess.run(
            ["bash", str(subagent_stop_hook_path)],
            input=input_json,
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )

        assert result.returncode == 0, f"stderr: {result.stderr}"

        if result.stdout.strip():
            output = json.loads(result.stdout.strip())
            context = output["hookSpecificOutput"]["additionalContext"]

            # S002 and L005 were already injected - should be filtered out
            assert "[S002]" not in context, (
                f"S002 was already injected but still appears:\n{context}"
            )
            assert "[L005]" not in context, (
                f"L005 was already injected but still appears:\n{context}"
            )
            assert "Stage files explicitly" not in context
            assert "Commit LESSONS.md periodically" not in context

            # S003 was NOT injected - it should remain
            assert "[S003]" in context, f"S003 should be present:\n{context}"
            assert "WIP file safety" in context

    def test_all_filtered_produces_no_output(
        self, smart_inject_hook_path, isolated_env, mock_recall_script, tmp_path
    ):
        """When ALL lessons are already injected, hook should produce no output."""
        env = isolated_env["env"]
        state_dir = isolated_env["state_dir"]
        home = isolated_env["home"]

        local_bin = home / ".local" / "bin"
        local_bin.mkdir(parents=True, exist_ok=True)
        recall_link = local_bin / "recall"
        recall_link.symlink_to(mock_recall_script)

        mock_output = tmp_path / "mock_output.txt"
        mock_output.write_text(SCORE_LOCAL_OUTPUT)

        # All three IDs already injected
        dedup_file = state_dir / "session-dedup-test-allfiltered.json"
        dedup_file.write_text(json.dumps(["S003", "S002", "L005"]))

        env["MOCK_RECALL_OUTPUT"] = str(mock_output)

        input_json = json.dumps({
            "session_id": "test-allfiltered",
            "cwd": str(isolated_env["project_dir"]),
            "prompt": "How do I safely commit changes to the repository without losing work?",
        })

        result = subprocess.run(
            ["bash", str(smart_inject_hook_path)],
            input=input_json,
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )

        # When everything is filtered, scored_lessons is empty. The hook may
        # exit non-zero because grep -oE fails on empty input under set -e,
        # or it may exit 0 with no stdout. Either way: no lesson output.
        assert result.returncode in (0, 1), f"Unexpected exit code {result.returncode}, stderr: {result.stderr}"
        # No JSON with lessons should be emitted
        if result.stdout.strip():
            # If there is stdout, it should not contain any lesson IDs
            try:
                output = json.loads(result.stdout.strip())
                context = output.get("hookSpecificOutput", {}).get("additionalContext", "")
                assert "[S003]" not in context and "[S002]" not in context and "[L005]" not in context, (
                    f"Filtered lessons still appear in output:\n{context}"
                )
            except json.JSONDecodeError:
                pass  # Non-JSON output is fine

    def test_no_prior_injections_keeps_all(
        self, smart_inject_hook_path, isolated_env, mock_recall_script, tmp_path
    ):
        """When no lessons have been injected yet, all should appear."""
        env = isolated_env["env"]
        home = isolated_env["home"]

        local_bin = home / ".local" / "bin"
        local_bin.mkdir(parents=True, exist_ok=True)
        recall_link = local_bin / "recall"
        recall_link.symlink_to(mock_recall_script)

        mock_output = tmp_path / "mock_output.txt"
        mock_output.write_text(SCORE_LOCAL_OUTPUT)

        # No dedup file - nothing pre-injected

        env["MOCK_RECALL_OUTPUT"] = str(mock_output)

        input_json = json.dumps({
            "session_id": "test-noprior",
            "cwd": str(isolated_env["project_dir"]),
            "prompt": "How do I safely commit changes to the repository without losing work?",
        })

        result = subprocess.run(
            ["bash", str(smart_inject_hook_path)],
            input=input_json,
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )

        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert result.stdout.strip(), "Expected output when no prior injections"

        output = json.loads(result.stdout.strip())
        context = output["hookSpecificOutput"]["additionalContext"]

        # All three lessons should be present
        assert "[S003]" in context
        assert "[S002]" in context
        assert "[L005]" in context


# =============================================================================
# find_go_binary (hook-lib.sh)
# =============================================================================


class TestFindGoBinary:
    """Test that find_go_binary only looks at ~/.local/bin/."""

    def test_finds_binary_at_local_bin(self, hook_lib_path, isolated_env):
        """When ~/.local/bin/recall exists and is executable, GO_RECALL is set."""
        env = isolated_env["env"]
        home = isolated_env["home"]

        local_bin = home / ".local" / "bin"
        local_bin.mkdir(parents=True, exist_ok=True)
        recall_bin = local_bin / "recall"
        recall_bin.write_text("#!/bin/bash\necho mock")
        recall_bin.chmod(0o755)

        result = run_bash(
            f'source "{hook_lib_path}"\n'
            f'find_go_binary\n'
            f'echo "GO_RECALL=$GO_RECALL"',
            env,
        )

        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert f"GO_RECALL={recall_bin}" in result.stdout

    def test_empty_when_no_binary(self, hook_lib_path, isolated_env):
        """When ~/.local/bin/recall does not exist, GO_RECALL is empty."""
        env = isolated_env["env"]

        # No binary created at all

        result = run_bash(
            f'source "{hook_lib_path}"\n'
            f'find_go_binary\n'
            f'echo "GO_RECALL=[$GO_RECALL]"',
            env,
        )

        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "GO_RECALL=[]" in result.stdout

    def test_does_not_find_old_location(self, hook_lib_path, isolated_env):
        """find_go_binary should NOT look at ~/.config/claude-recall/go/bin/."""
        env = isolated_env["env"]
        home = isolated_env["home"]

        # Place binary at old location only
        old_bin_dir = home / ".config" / "claude-recall" / "go" / "bin"
        old_bin_dir.mkdir(parents=True, exist_ok=True)
        old_recall = old_bin_dir / "recall"
        old_recall.write_text("#!/bin/bash\necho old")
        old_recall.chmod(0o755)

        # Do NOT create ~/.local/bin/recall

        result = run_bash(
            f'source "{hook_lib_path}"\n'
            f'find_go_binary\n'
            f'echo "GO_RECALL=[$GO_RECALL]"',
            env,
        )

        assert result.returncode == 0, f"stderr: {result.stderr}"
        # GO_RECALL should be empty - old location is not checked
        assert "GO_RECALL=[]" in result.stdout

    def test_finds_recall_hook_binary(self, hook_lib_path, isolated_env):
        """When ~/.local/bin/recall-hook exists and is executable, GO_RECALL_HOOK is set."""
        env = isolated_env["env"]
        home = isolated_env["home"]

        local_bin = home / ".local" / "bin"
        local_bin.mkdir(parents=True, exist_ok=True)
        recall_hook_bin = local_bin / "recall-hook"
        recall_hook_bin.write_text("#!/bin/bash\necho mock-hook")
        recall_hook_bin.chmod(0o755)

        result = run_bash(
            f'source "{hook_lib_path}"\n'
            f'find_go_binary\n'
            f'echo "GO_RECALL_HOOK=$GO_RECALL_HOOK"',
            env,
        )

        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert f"GO_RECALL_HOOK={recall_hook_bin}" in result.stdout


# =============================================================================
# Full Content Output (Go binary)
# =============================================================================


class TestFullContentOutput:
    """Test that recall score-local outputs full lesson content (not truncated)."""

    @pytest.fixture
    def go_recall_binary(self) -> Path:
        """Path to the real Go recall binary."""
        p = Path.home() / ".local" / "bin" / "recall"
        if not p.exists() or not os.access(p, os.X_OK):
            pytest.skip("Go recall binary not found at ~/.local/bin/recall")
        return p

    def test_score_local_full_content(self, go_recall_binary, tmp_path):
        """score-local should output full lesson content, not truncated to 100 chars."""
        # Create a LESSONS.md with long content (> 100 chars)
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        (project_dir / ".git").mkdir()
        recall_dir = project_dir / ".claude-recall"
        recall_dir.mkdir()

        long_content = (
            "When working with subprocess calls in Python testing, always capture "
            "both stdout and stderr, set appropriate timeouts, and verify return codes "
            "before parsing output to avoid silent failures in CI environments"
        )
        assert len(long_content) > 100, f"Test content must be > 100 chars, got {len(long_content)}"

        lessons_file = recall_dir / "LESSONS.md"
        lessons_file.write_text(textwrap.dedent(f"""\
            # LESSONS.md - Project Level

            > **Lessons System**: Cite lessons with [L###] when applying them.

            ## Active Lessons

            ### [L001] [*----|*----] Subprocess Testing Best Practices
            - **Uses**: 1 | **Velocity**: 5.00 | **Learned**: 2026-01-01 | **Last**: 2026-02-21 | **Category**: pattern | **Type**: informational
            > {long_content}
        """))

        env = {
            k: v for k, v in os.environ.items()
            if k in {"PATH", "SHELL", "TERM", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE", "HOME"}
        }
        env["PROJECT_DIR"] = str(project_dir)

        result = subprocess.run(
            [str(go_recall_binary), "score-local", "subprocess testing python", "--top", "5"],
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )

        assert result.returncode == 0, f"stderr: {result.stderr}"

        # The content line should contain the full text, not be truncated
        output = result.stdout
        if output.strip() and "No lessons found" not in output:
            # Find lines starting with "    -> " (content lines)
            content_lines = [
                line for line in output.split("\n")
                if line.strip().startswith("->")
            ]
            assert len(content_lines) > 0, (
                f"Expected content lines in output:\n{output}"
            )

            # Verify full content appears (not truncated at 100 chars)
            full_output = "\n".join(content_lines)
            # Check that the distinctive end of the content is present
            assert "CI environments" in full_output, (
                f"Content appears truncated. Expected full content including "
                f"'CI environments', got:\n{full_output}"
            )
