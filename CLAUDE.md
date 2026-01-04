# Claude Recall

A learning system for AI coding agents that captures lessons across sessions and tracks multi-step work via handoffs.

## Quick Reference

| Component | Location |
|-----------|----------|
| Core Python | `core/cli.py` (entry), `core/lessons.py`, `core/handoffs.py`, `core/debug_logger.py` |
| Claude hooks | `adapters/claude-code/inject-hook.sh`, `smart-inject-hook.sh`, `stop-hook.sh` |
| Tests | `tests/test_lessons_manager.py`, `tests/test_handoffs.py` |
| Project lessons | `.claude-recall/LESSONS.md` (gitignored by default) |
| System lessons | `~/.local/state/claude-recall/LESSONS.md` (XDG state) |
| Handoffs | `.claude-recall/HANDOFFS.md` |
| State files | `~/.local/state/claude-recall/` (decay, citation state, logs) |

## How It Works

```
SessionStart hook → injects top 3 lessons + active handoffs + duty reminder
UserPromptSubmit hook → on first prompt, scores lessons by relevance via Haiku
Agent works → cites [L###]/[S###], outputs LESSON:/APPROACH: commands
Stop hook → parses output, updates lessons/handoffs, tracks citations
```

**Lessons**: Dual-rated `[uses|velocity]` - left = total uses (log scale), right = recency (decays 50%/week). At 50 uses, project lessons promote to system.

**Handoffs**: Track multi-step work with status, phase (research→planning→implementing→review), tried steps, and next steps.

## Key Commands

```bash
# Run tests
python3 -m pytest tests/ -v

# CLI usage
python3 core/cli.py inject 5                          # Top 5 by stars
python3 core/cli.py score-relevance "query" --top 5   # Top 5 by relevance
python3 core/cli.py add pattern "Title" "Content"
python3 core/cli.py cite L001
python3 core/cli.py handoff list
```

## Writing Tests

**Read `docs/TESTING.md` before writing tests.** Key gotchas:

- Use `temp_lessons_base` + `temp_state_dir` + `temp_project_root` fixtures for CLI tests
- `add_lesson()` requires **keyword args**: `level=`, `category=`, `title=`, `content=`
- CLI subprocess tests need `env={**os.environ, "CLAUDE_RECALL_BASE": ..., "CLAUDE_RECALL_STATE": ..., "PROJECT_DIR": ...}`
- Dev paths (`core/...`) differ from installed paths (`~/.config/claude-recall/...`)

## Environment

| Variable | Purpose |
|----------|---------|
| `CLAUDE_RECALL_BASE` | Code directory - default: `~/.config/claude-recall` |
| `CLAUDE_RECALL_STATE` | State dir (lessons, decay, logs) - default: `~/.local/state/claude-recall` |
| `PROJECT_DIR` | Project root (default: git root or cwd) |
| `CLAUDE_RECALL_DEBUG` | Debug level - 0=off, 1=info, 2=debug, 3=trace |
| `RECALL_BASE` | Legacy alias for CLAUDE_RECALL_BASE |
| `LESSONS_BASE` | Legacy alias for CLAUDE_RECALL_BASE |
| `RECALL_DEBUG` | Legacy alias for CLAUDE_RECALL_DEBUG |
| `LESSONS_DEBUG` | Legacy alias for CLAUDE_RECALL_DEBUG |

## Agent Output Patterns

Stop hook parses these from agent output:
- `LESSON: [category:] title - content` → add project lesson
- `[L001]:` or `[S001]:` → cite (increments uses/velocity)
- `HANDOFF: title` → start tracking work
- `HANDOFF UPDATE H001: tried success|fail|partial - desc` → record attempt
- `HANDOFF COMPLETE H001` → finish and extract lessons
