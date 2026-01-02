# Coding Agent Lessons

A learning system for AI coding agents that captures lessons across sessions and tracks multi-step work via approaches.

## Quick Reference

| Component | Location |
|-----------|----------|
| Core Python | `core/cli.py` (entry), `core/lessons.py`, `core/approaches.py`, `core/debug_logger.py` |
| Claude hooks | `adapters/claude-code/inject-hook.sh`, `smart-inject-hook.sh`, `stop-hook.sh` |
| Tests | `tests/test_lessons_manager.py`, `tests/test_approaches.py` |
| Project lessons | `.coding-agent-lessons/LESSONS.md` |
| System lessons | `~/.config/coding-agent-lessons/LESSONS.md` |
| Approaches | `.coding-agent-lessons/APPROACHES.md` |

## How It Works

```
SessionStart hook → injects top 3 lessons + active approaches + duty reminder
UserPromptSubmit hook → on first prompt, scores lessons by relevance via Haiku
Agent works → cites [L###]/[S###], outputs LESSON:/APPROACH: commands
Stop hook → parses output, updates lessons/approaches, tracks citations
```

**Lessons**: Dual-rated `[uses|velocity]` - left = total uses (log scale), right = recency (decays 50%/week). At 50 uses, project lessons promote to system.

**Approaches**: Track multi-step work with status, phase (research→planning→implementing→review), tried attempts, and next steps.

## Key Commands

```bash
# Run tests
python3 -m pytest tests/ -v

# CLI usage
python3 core/cli.py inject 5                          # Top 5 by stars
python3 core/cli.py score-relevance "query" --top 5   # Top 5 by relevance
python3 core/cli.py add pattern "Title" "Content"
python3 core/cli.py cite L001
python3 core/cli.py approach list
```

## Writing Tests

**Read `docs/TESTING.md` before writing tests.** Key gotchas:

- Use `temp_lessons_base` + `temp_project_root` fixtures for CLI tests
- `add_lesson()` requires **keyword args**: `level=`, `category=`, `title=`, `content=`
- CLI subprocess tests need `env={**os.environ, "LESSONS_BASE": ..., "PROJECT_DIR": ...}`
- Dev paths (`core/...`) differ from installed paths (`~/.config/coding-agent-lessons/...`)

## Environment

| Variable | Purpose |
|----------|---------|
| `LESSONS_BASE` | System lessons dir (default: `~/.config/coding-agent-lessons`) |
| `PROJECT_DIR` | Project root (default: git root or cwd) |
| `LESSONS_DEBUG` | 0=off, 1=info, 2=debug, 3=trace → writes to `$LESSONS_BASE/debug.log` |

## Agent Output Patterns

Stop hook parses these from agent output:
- `LESSON: [category:] title - content` → add project lesson
- `[L001]:` or `[S001]:` → cite (increments uses/velocity)
- `APPROACH: title` → start tracking work
- `APPROACH UPDATE A001: tried success|fail|partial - desc` → record attempt
- `APPROACH COMPLETE A001` → finish and extract lessons
