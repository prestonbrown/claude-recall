---
description: Test-first development discipline. Write failing tests BEFORE implementation. No exceptions for MAJOR work.
allowed-tools: Task, Bash(./run-tests.sh:*), Bash(pytest:*), Bash(npm test:*)
---

# TEST-FIRST PROTOCOL

> **No exceptions** for MAJOR work. Tests come first.

## The Discipline

```
1. Write test that describes desired behavior
2. Run test → verify it FAILS
3. Implement minimum code to pass
4. Run test → verify it PASSES
5. Refactor if needed (tests still pass)
```

## Why Tests Must Fail First

A test that passes before implementation proves nothing. It might:
- Test the wrong thing
- Have a bug that makes it always pass
- Not actually exercise your code

**The red-green cycle is the proof.**

## What Makes a Good Test

**GOOD** - Fails if feature removed:
```python
def test_rate_limit_blocks_excess_requests():
    for _ in range(10):
        client.post("/api/submit")  # Fill quota
    response = client.post("/api/submit")  # 11th request
    assert response.status_code == 429
    assert "Retry-After" in response.headers
```

**BAD** - Always passes:
```python
def test_rate_limit_exists():
    assert hasattr(app, 'rate_limiter')  # Implementation detail
```

## Test Categories

| Type | What to Test | When |
|------|--------------|------|
| Unit | Single function/class in isolation | Always |
| Integration | Components working together | When crossing boundaries |
| Edge cases | Boundaries, empty, null, max values | Always |
| Error paths | What happens when things fail | Always |

## Running Tests

```bash
# Python
./run-tests.sh                    # All tests
./run-tests.sh -v tests/test_x.py # Specific file

# Node
npm test
npm test -- --watch              # Watch mode
```

## When You're Tempted to Skip

**"I'll add tests after"** → You won't. And if you do, they'll be weaker.

**"It's too simple to test"** → Simple things break too. And tests document behavior.

**"I don't know how to test this"** → That's a design smell. Refactor for testability.
