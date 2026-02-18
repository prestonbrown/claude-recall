# Claude Recall

A learning system for AI coding agents that captures lessons across sessions.

## Quick Reference

| Component | Location |
|-----------|----------|
| Core Python | `core/cli.py` (entry), `core/lessons.py`, `core/handoffs.py`, `core/debug_logger.py` |
| Claude hooks | `adapters/claude-code/inject-hook.sh`, `smart-inject-hook.sh` (BM25, every prompt), `subagent-stop-hook.sh`, `stop-hook.sh` |
| Tests | `tests/test_lessons_manager.py`, `tests/test_handoffs.py` |
| Project lessons | `.claude-recall/LESSONS.md` (gitignored by default) |
| System lessons | `~/.local/state/claude-recall/LESSONS.md` (XDG state) |
| Handoffs | `.claude-recall/HANDOFFS.md` (library exists, hooks removed) |
| State files | `~/.local/state/claude-recall/` (decay, citation state, session dedup, logs) |

## How It Works

```
SessionStart hook → injects top N lessons by star rating + duty reminder
UserPromptSubmit hook → scores lessons by relevance via BM25 (every prompt)
SubagentStop hook → injects lessons relevant to subagent output
Agent works → cites [L###]/[S###], outputs LESSON: commands
Stop hook → parses output, updates lessons, tracks citations
```

**Lessons**: Dual-rated `[uses|velocity]` - left = total uses (log scale), right = recency (decays 50%/week). At 50 uses, project lessons promote to system.

**Session deduplication**: Tracks which lessons have been injected this session to avoid repeating them across prompts.

## Key Commands

```bash
# Run tests (auto-manages venv and dependencies)
./run-tests.sh                    # All tests
./run-tests.sh -v --tb=short      # With verbose output
./run-tests.sh tests/test_tui/    # TUI tests only

# CLI usage
python3 core/cli.py inject 5                          # Top 5 by stars
python3 core/cli.py score-local "query" --top 5       # Top 5 by BM25 relevance (local)
python3 core/cli.py score-relevance "query" --top 5   # Top 5 by relevance (requires API key)
python3 core/cli.py add pattern "Title" "Content"
python3 core/cli.py cite L001
python3 core/cli.py handoff list
```

## Writing Tests

**Read `docs/TESTING.md` before writing tests.** Use `./run-tests.sh` - it auto-creates a venv and installs deps from `requirements-dev.txt`.

Key gotchas:
- Use `temp_lessons_base` + `temp_state_dir` + `temp_project_root` fixtures for CLI tests
- `add_lesson()` requires **keyword args**: `level=`, `category=`, `title=`, `content=`
- CLI subprocess tests need `env={**os.environ, "CLAUDE_RECALL_BASE": ..., "CLAUDE_RECALL_STATE": ..., "PROJECT_DIR": ...}`
- Dev paths (`core/...`) differ from installed paths (`~/.config/claude-recall/...`)
- TUI tests require `textual` (included in dev deps) - they skip gracefully if missing

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

## OpenCode Adapter

Claude Recall is also available as an OpenCode plugin. Installation and configuration differ slightly:

- **Installation**: `./install.sh --opencode`
- **Configuration**: `~/.config/claude-recall/config.json`
- **Plugin source**: `adapters/opencode/plugin.ts` → installed to `~/.config/opencode/plugins/lessons.ts`
- **CLI**: `claude-recall`
- **Commands**: `/lessons`, `/handoffs`

**Development workflow:**
```bash
# Edit the source
vim adapters/opencode/plugin.ts

# Install to OpenCode's plugin directory (no separate build step - OpenCode loads .ts directly)
./install.sh --opencode

# Test by running opencode in any project
opencode
```

The install copies `adapters/opencode/plugin.ts` → `~/.config/opencode/plugins/lessons.ts`. There's no TypeScript compilation step - OpenCode loads `.ts` files directly via its plugin system.

**Gotchas:**
- **Never block plugin initialization** - OpenCode plugins are async functions that must return quickly. Blocking calls (like `await client.provider.list()`) during init will hang the entire UI. Use fire-and-forget patterns (`.then()`) for slow operations.
- **Session state types** - Ensure all properties in session state type are initialized (e.g., `compactionOccurred: false`)

See docs/DEPLOYMENT.md for detailed instructions.
