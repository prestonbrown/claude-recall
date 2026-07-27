# Plan: Fix Flaky Tests

## Problem

Several tests fail intermittently when run in parallel with pytest-xdist (16 workers):

1. **TestReminderHook tests** - `test_lessons_manager.py`
   - `test_reminder_default_when_no_config`
   - `test_reminder_env_var_overrides_config`
   - `test_reminder_logs_when_debug_enabled`

2. **TestCaptureHook tests** - `test_lessons_manager.py`
   - `test_capture_hook_parses_no_promote`

3. **Performance tests** - `test_stop_hook_performance.py`
   - `test_stop_hook_completes_under_2_seconds` (timing sensitive)

## Root Causes

### 1. Subprocess tests with shared environment
- Tests spawn bash subprocesses that read/write shared resources
- Parallel workers compete for these resources
- Environment variable pollution between tests

### 2. Insufficient HOME isolation
- Some tests don't override `HOME`, causing subprocess to read live user config
- Parallel tests may interfere via shared temp directories

### 3. Timing-sensitive assertions
- Performance tests fail when system is under load from parallel execution
- 5s threshold too tight when 16 workers compete for CPU

## Solutions

### Option A: Serial Execution (Quick Fix)
Mark flaky tests to run sequentially:

```python
@pytest.mark.serial  # Requires pytest-xdist plugin
class TestReminderHook:
    ...
```

Or exclude from parallel runs in `pytest.ini`:
```ini
[pytest]
addopts = --ignore=tests/test_lessons_manager.py::TestReminderHook
```

### Option B: Better Isolation (Recommended)
Fix each test to properly isolate:

```python
@pytest.fixture
def isolated_subprocess_env(tmp_path):
    """Fully isolated environment for subprocess tests."""
    home = tmp_path / "home"
    home.mkdir()
    config = home / ".config" / "claude-recall"
    config.mkdir(parents=True)
    state = home / ".local" / "state" / "claude-recall"
    state.mkdir(parents=True)

    return {
        **os.environ,
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_STATE_HOME": str(home / ".local" / "state"),
        "CLAUDE_RECALL_BASE": str(config),
        "CLAUDE_RECALL_STATE": str(state),
    }
```

### Option C: Increase Performance Thresholds
For timing tests, either:
- Increase threshold from 5s to 10s
- Mark as `@pytest.mark.slow` and skip in fast runs
- Add `@pytest.mark.flaky(reruns=2)` with pytest-rerunfailures

## Recommended Implementation

1. **Create shared fixture** in `tests/conftest.py`:
   ```python
   @pytest.fixture
   def isolated_subprocess_env(tmp_path):
       # ... as above
   ```

2. **Update affected tests** to use fixture:
   - `TestReminderHook` - all methods
   - `TestCaptureHook` - all methods

3. **Mark performance tests** as slow:
   ```python
   @pytest.mark.slow
   def test_stop_hook_completes_under_2_seconds(...):
       ...
   ```

4. **Update CI/run-tests.sh** to skip slow tests by default:
   ```bash
   pytest -m "not slow" ...
   ```

## Files to Modify

- `tests/conftest.py` - Add `isolated_subprocess_env` fixture
- `tests/test_lessons_manager.py` - Update TestReminderHook, TestCaptureHook
- `tests/test_hooks/test_stop_hook_performance.py` - Mark as slow
- `run-tests.sh` - Add `-m "not slow"` to fast test command

## Verification

After fixes:
```bash
# Run all tests in parallel multiple times
for i in {1..5}; do ./run-tests.sh; done

# Should have 0 failures
```
