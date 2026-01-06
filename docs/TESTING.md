# Testing Guide

Testing infrastructure, running tests, and writing new tests for the Claude Recall system.

## Test Framework

The test suite uses **pytest** with Python's standard library. Tests are organized by component:

```
tests/
├── test_lessons_manager.py   # Core lessons + CLI tests
├── test_handoffs.py          # Handoffs system tests
└── test_debug_logger.py      # Debug logger tests
```

## Running Tests

Use `./run-tests.sh` - it automatically creates a venv and installs dependencies from `requirements-dev.txt`:

```bash
# Run all tests (500+ tests)
./run-tests.sh

# Run with verbose output
./run-tests.sh -v --tb=short

# Run specific test file
./run-tests.sh tests/test_lessons_manager.py -v
./run-tests.sh tests/test_handoffs.py -v
./run-tests.sh tests/test_tui/ -v

# Run specific test class
./run-tests.sh tests/test_handoffs.py::TestPhaseDetectionFromTools -v

# Run specific test
./run-tests.sh tests/test_handoffs.py::TestPhaseDetectionFromTools::test_bash_pytest_is_review -v

# Run tests matching a pattern
./run-tests.sh -v -k "phase"

# Run with coverage
./run-tests.sh --cov=core --cov-report=term-missing
```

**Note:** TUI tests require `textual` (included in dev deps). If you run `pytest` directly without the wrapper, TUI tests will skip gracefully if textual is not installed.

## Test Categories

### Lessons Tests (test_lessons_manager.py)

| Category | Tests | Description |
|----------|-------|-------------|
| Basic CRUD | 12 | Add, edit, delete, list lessons |
| Citation | 8 | Cite lessons, increment uses/velocity |
| Injection | 10 | Generate context, top N, formatting |
| Decay | 8 | Velocity decay, stale lesson handling |
| Promotion | 6 | Project → system promotion |
| Rating | 10 | Dual-dimension [uses\|velocity] format |
| Tokens | 8 | Token estimation and heavy warnings |

### Handoffs Tests (test_handoffs.py)

| Category | Tests | Description |
|----------|-------|-------------|
| Basic CRUD | 15 | Add, update, complete, list handoffs |
| Status | 8 | Status transitions, validation |
| Tried/Next | 12 | Record attempts, set next steps |
| Code Snippets | 10 | Attach/parse code blocks |
| Phases | 18 | Phase values, transitions |
| Agents | 12 | Agent tracking per handoff |
| Phase Detection | 14 | Infer phase from tool usage |
| Plan Mode | 8 | PLAN MODE: integration |
| Injection | 12 | Handoff context generation |
| Visibility | 10 | Completed handoff decay rules |
| Archive | 8 | Archive and recent completions |
| Hook Patterns | 12 | Stop-hook pattern matching |

## Test Environment

Each test uses an isolated temporary directory:

```python
@pytest.fixture
def temp_env(tmp_path):
    """Create isolated test environment."""
    project_dir = tmp_path / "project"
    lessons_base = tmp_path / "system"
    project_dir.mkdir()
    lessons_base.mkdir()

    # Create lessons directories
    (project_dir / ".claude-recall").mkdir()

    return {
        "project_dir": str(project_dir),
        "lessons_base": str(lessons_base),
        "project_lessons": project_dir / ".claude-recall" / "LESSONS.md",
        "handoffs_file": project_dir / ".claude-recall" / "HANDOFFS.md",
        "system_lessons": lessons_base / "LESSONS.md",
    }
```

## Writing Tests

### Basic Test Structure

```python
def test_add_lesson(temp_env):
    """Test adding a project lesson."""
    # Arrange
    manager = LessonsManager(
        project_dir=temp_env["project_dir"],
        lessons_base=temp_env["lessons_base"]
    )

    # Act
    result = manager.add("pattern", "Test Title", "Test content")

    # Assert
    assert "L001" in result
    lessons = manager.list_lessons(scope="project")
    assert len(lessons) == 1
    assert lessons[0].title == "Test Title"
    assert lessons[0].content == "Test content"
```

### Testing Handoffs

```python
def test_handoff_phase_transition(temp_env):
    """Test updating handoff phase."""
    manager = LessonsManager(
        project_dir=temp_env["project_dir"],
        lessons_base=temp_env["lessons_base"]
    )

    # Create handoff
    result = manager.handoff_add("Test task", phase="research")
    handoff_id = result.split()[0]  # Extract hf-abc1234

    # Update phase
    manager.handoff_update(handoff_id, phase="implementing")

    # Verify
    handoffs = manager.handoff_list()
    assert handoffs[0].phase == "implementing"
```

### Testing CLI Integration

```python
def test_cli_handoff_add(temp_env):
    """Test CLI command for adding handoff."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "core/lessons_manager.py", "handoff", "add",
         "--phase", "research", "--agent", "plan", "--", "Test handoff"],
        capture_output=True,
        text=True,
        env={
            "PROJECT_DIR": temp_env["project_dir"],
            "CLAUDE_RECALL_BASE": temp_env["lessons_base"],
        }
    )

    assert result.returncode == 0
    assert "hf-" in result.stdout
```

### Testing Hook Patterns

```python
def test_plan_mode_pattern(temp_env):
    """Test PLAN MODE: pattern creates handoff correctly."""
    manager = LessonsManager(
        project_dir=temp_env["project_dir"],
        lessons_base=temp_env["lessons_base"]
    )

    # Simulate hook pattern: PLAN MODE: Implement feature
    result = manager.handoff_add(
        "Implement feature",
        phase="research",
        agent="plan"
    )

    handoff_id = result.split()[0]
    handoffs = manager.handoff_list()

    assert handoffs[0].phase == "research"
    assert handoffs[0].agent == "plan"
```

## Test Fixtures

### Common Fixtures

```python
@pytest.fixture
def manager(temp_env):
    """Create a LessonsManager instance."""
    return LessonsManager(
        project_dir=temp_env["project_dir"],
        lessons_base=temp_env["lessons_base"]
    )

@pytest.fixture
def sample_lesson(manager):
    """Create a sample lesson for testing."""
    manager.add("pattern", "Sample Title", "Sample content")
    return manager.list_lessons(scope="project")[0]

@pytest.fixture
def sample_handoff(manager):
    """Create a sample handoff for testing."""
    manager.handoff_add("Sample task")
    return manager.handoff_list()[0]
```

### File Content Fixtures

```python
@pytest.fixture
def lessons_with_velocity(temp_env):
    """Create lessons file with velocity data."""
    content = """# Project Lessons

### [L001] [**---|++---] pattern: Test lesson
- **Uses**: 5 | **Velocity**: 2.5 | **Tokens**: 30 | **Learned**: 2025-12-01 | **Last**: 2025-12-28 | **Source**: user
- Test content
"""
    (temp_env["project_dir"] / ".claude-recall" / "LESSONS.md").write_text(content)
    return temp_env
```

## Assertions

### Common Patterns

```python
# Check lesson exists
assert any(l.id == "L001" for l in manager.list_lessons())

# Check handoff status
handoff = manager.handoff_list()[0]
assert handoff.status == "in_progress"

# Check injection output
output = manager.inject(5)
assert "L001" in output
assert "TOP LESSONS:" in output

# Check token warning
output = manager.inject(100)  # Many lessons
assert "CONTEXT HEAVY" in output or total_tokens < 2000
```

### Handoff-Specific

```python
# Check tried handoff recorded
handoff = manager.handoff_list()[0]
assert len(handoff.tried) == 1
assert handoff.tried[0].outcome == "fail"
```

## Mocking

### Mock File System

```python
def test_file_not_found(temp_env, monkeypatch):
    """Test graceful handling of missing files."""
    manager = LessonsManager(
        project_dir="/nonexistent/path",
        lessons_base=temp_env["lessons_base"]
    )

    # Should return empty list, not raise
    lessons = manager.list_lessons()
    assert lessons == []
```

### Mock Environment Variables

```python
def test_custom_lessons_base(temp_env, monkeypatch):
    """Test custom CLAUDE_RECALL_BASE location."""
    custom_base = temp_env["lessons_base"] + "/custom"
    monkeypatch.setenv("CLAUDE_RECALL_BASE", custom_base)

    # Manager should use custom location
    manager = LessonsManager()
    assert manager.lessons_base == custom_base
```

## Debugging Tests

### Verbose Output

```python
def test_debug_example(temp_env, capsys):
    """Debug test with output capture."""
    manager = LessonsManager(
        project_dir=temp_env["project_dir"],
        lessons_base=temp_env["lessons_base"]
    )

    result = manager.inject(5)
    print(f"Injection result: {result}")

    captured = capsys.readouterr()
    # Inspect captured.out for debugging
```

### Inspect Test Files

```python
def test_inspect_state(temp_env):
    """Test that can be paused for inspection."""
    manager = LessonsManager(
        project_dir=temp_env["project_dir"],
        lessons_base=temp_env["lessons_base"]
    )

    manager.add("pattern", "Test", "Content")

    # Print paths for manual inspection
    print(f"Project lessons: {temp_env['project_lessons']}")
    print(f"Content: {temp_env['project_lessons'].read_text()}")

    # Add breakpoint for interactive debugging
    # import pdb; pdb.set_trace()
```

### Common Issues

| Issue | Cause | Fix |
|-------|-------|-----|
| FileNotFoundError | Missing temp directory | Check fixture creates dirs |
| AssertionError on ID | ID format changed | Update expected pattern |
| Empty list returned | File not created/parsed | Check file path and content |
| Subprocess test fails | Wrong Python path | Use `sys.executable` |

## Test Fixtures Reference

The test suite uses two fixture patterns. Use the correct one for your test:

### `temp_lessons_base` + `temp_project_root` (Preferred for CLI tests)

```python
def test_cli_example(self, temp_lessons_base: Path, temp_project_root: Path):
    """CLI tests use separate Path fixtures."""
    result = subprocess.run(
        ["python3", "core/lessons_manager.py", "list"],
        env={
            **os.environ,
            "CLAUDE_RECALL_BASE": str(temp_lessons_base),
            "PROJECT_DIR": str(temp_project_root),
        },
    )
```

- `temp_lessons_base`: System lessons location (`~/.config/claude-recall` equivalent)
- `temp_project_root`: Project root containing `.claude-recall/`
- Both are `Path` objects - convert with `str()` for subprocess env

### `temp_env` (Dict-based, for internal tests)

```python
def test_internal_example(temp_env):
    """Internal tests use the temp_env dict."""
    manager = LessonsManager(
        project_dir=temp_env["project_dir"],
        lessons_base=temp_env["lessons_base"]
    )
```

- Returns a dict with string paths
- Keys: `project_dir`, `lessons_base`, `project_lessons`, `handoffs_file`, `system_lessons`

### `add_lesson` Method Signature

The `add_lesson` method uses **keyword arguments**:

```python
# CORRECT - keyword arguments
manager.add_lesson(
    level="project",      # or "system"
    category="pattern",   # pattern|correction|gotcha|preference|decision
    title="My Title",
    content="My content"
)

# WRONG - positional arguments
manager.add_lesson("pattern", "Title", "Content")  # TypeError!
```

## File Paths and Locations

### Development vs Installed Paths

| Component | Development Path | Installed Path |
|-----------|-----------------|----------------|
| Python CLI | `core/cli.py` | `~/.config/claude-recall/cli.py` |
| Debug logger | `core/debug_logger.py` | `~/.config/claude-recall/debug_logger.py` |
| Debug logs | N/A | `~/.local/state/claude-recall/debug.log` |
| Inject hook | `adapters/claude-code/inject-hook.sh` | `~/.claude/hooks/inject-hook.sh` |
| Smart inject | `adapters/claude-code/smart-inject-hook.sh` | `~/.claude/hooks/smart-inject-hook.sh` |
| Stop hook | `adapters/claude-code/stop-hook.sh` | `~/.claude/hooks/stop-hook.sh` |

### Import Paths in cli.py

The Python manager handles both dev and installed environments:

```python
# First try dev path (running from repo)
from core.debug_logger import get_logger

# Fall back to installed path (running from ~/.config)
from debug_logger import get_logger
```

### CLI Test Environment

When testing CLI commands via subprocess, always set both environment variables:

```python
env={
    **os.environ,  # Preserve PATH, HOME, etc.
    "CLAUDE_RECALL_BASE": str(temp_lessons_base),
    "PROJECT_DIR": str(temp_project_root),
}
```

**Common gotcha**: Forgetting `**os.environ` breaks Python imports because `PATH` is lost.

## Continuous Integration

Tests can run in CI environments:

```yaml
# .github/workflows/test.yml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.9", "3.10", "3.11", "3.12"]

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}

      - name: Run tests
        run: ./run-tests.sh -v --cov=core --cov-report=xml

      - name: Upload coverage
        uses: codecov/codecov-action@v3
        with:
          file: ./coverage.xml
```

The `run-tests.sh` script handles venv creation and dependency installation automatically.

## Test Coverage

Current coverage targets:

| Module | Target | Current |
|--------|--------|---------|
| lessons_manager.py | 90% | ~92% |
| Overall | 85% | ~90% |

Run coverage report:
```bash
./run-tests.sh --cov=core --cov-report=html
open htmlcov/index.html
```

## Adding New Tests

1. **Identify the component**: lessons, handoffs, hooks, CLI
2. **Choose the test file**: `test_lessons_manager.py` or `test_handoffs.py`
3. **Find related tests**: Group with similar functionality
4. **Write the test**: Follow AAA pattern (Arrange, Act, Assert)
5. **Run the test**: Verify it passes
6. **Check coverage**: Ensure new code is covered

### Checklist for New Features

- [ ] Unit tests for core functionality
- [ ] Edge case tests (empty input, missing files)
- [ ] Integration tests (CLI, subprocess)
- [ ] Tests for error handling
- [ ] Tests for hook patterns (if applicable)
