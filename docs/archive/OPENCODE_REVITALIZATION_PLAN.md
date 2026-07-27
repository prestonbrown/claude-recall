# OpenCode Adapter Revitalization Plan

## Executive Summary

**Objective**: Bring OpenCode plugin from ~40% to ~95% feature parity with Claude Code adapter  
**Target**: OpenCode 1.1.20+  
**Method**: Test-Driven Development (TDD) with real subprocess calls  
**Delegation Strategy**: Implement via sub-agents in major chunks, review after each  
**Approach**: Clean break from legacy - NO backward compatibility with old OpenCode adapter  
**Current Context Usage**: 40% - Start fresh session after plan review  

---

## Current State Analysis

### Existing OpenCode Plugin
- **File**: `adapters/opencode/plugin.ts` (160 lines)
- **Handlers**: 3 basic events implemented
  - ✅ `session.created` - Injects top 5 lessons
  - ✅ `session.idle` - Tracks `[L###]`/`[S###]` citations with checkpointing
  - ✅ `message.updated` - Captures `LESSON:`/`SYSTEM LESSON:` commands
- **Status**: ~40% complete

### Critical Issues Identified
1. **Manager Path Error** (Line 11): References `~/.config/coding-agent-lessons/lessons-manager.sh` (old path)
2. **No Config System**: Doesn't read from `config.json`
3. **No Model Detection**: Assumes Haiku available (not always true)
4. **Missing Features** (~60% of Claude Code adapter):
   - ❌ Smart injection (relevance scoring on first prompt)
   - ❌ Lesson decay (weekly velocity decay)
   - ❌ AI lesson capture (`AI LESSON:` patterns)
   - ❌ Periodic reminders (high-star lesson display)
   - ❌ Token budget tracking
   - ❌ Handoffs injection
   - ❌ TodoWrite sync to handoffs
   - ❌ Handoff pattern capture (`HANDOFF:`, `UPDATE`, `COMPLETE`)
   - ❌ Tool execution hooks (`tool.execute.before`/`after`)
   - ❌ Compaction hooks (`experimental.session.compacting`, `session.compacted`)
   - ❌ Session snapshots
   - ❌ Debug logging
   - ❌ `/handoffs` command

### Dependencies & Integration Points
- **Python CLI**: `core/cli.py` (fully functional, 50+ commands)
- **Config File**: `plugins/claude-recall/config.json` (defaults available)
- **Test Framework**: pytest (`tests/`, `run-tests.sh`, 948 existing tests)
- **OpenCode API**: `@opencode-ai/plugin@1.1.20` (latest stable)
- **OpenCode Events**: 25+ event types available (session, message, tool, file, etc.)

---

## Goals & Success Criteria

### Primary Goals
1. **Lessons System Parity** (Highest Priority)
   - [ ] Lessons injected at session start (top N by stars)
   - [ ] Smart injection on first prompt (relevance scoring)
   - [ ] Citations tracked from assistant messages
   - [ ] AI lessons captured (`AI LESSON:` patterns)
   - [ ] Lesson decay runs weekly
   - [ ] Periodic reminders (high-star lessons shown every N prompts)
   - [ ] Token budget logged with warnings

2. **Handoffs System Parity** (Medium Priority)
   - [ ] Active handoffs injected at session start
   - [ ] TodoWrite syncs to handoffs automatically
   - [ ] Handoff patterns parsed (`HANDOFF:`, `UPDATE`, `COMPLETE`)
   - [ ] `/handoffs` command documented
   - [ ] ExitPlanMode creates handoff

3. **OpenCode-Specific Features** (Lower Priority)
   - [ ] Pre-compact context injection
   - [ ] Post-compact handoff update
   - [ ] Session snapshots when no active handoff
   - [ ] Debug logging (structured JSON)
   - [ ] Fast model detection (no Haiku assumption)

4. **Infrastructure** (Foundational)
   - [ ] Test infrastructure complete (76+ tests)
   - [ ] Configuration system reads from `config.json`
   - [ ] Documentation updated (README, DEPLOYMENT)
   - [ ] Install script verified

### Success Criteria
- ✅ All 76+ new tests pass (TDD cycle complete)
- ✅ Full test suite runs in <15 minutes (1024 tests total)
- ✅ No assumptions about Haiku availability
- ✅ Fast good model auto-detected (fallback to config)
- ✅ Zero backward compatibility with old adapter (clean break)
- ✅ OpenCode 1.1.20+ API compatibility verified
- ✅ Manual installation test passes (`./install.sh --opencode`)

---

## Detailed Phase Breakdown

---

### Phase 0: Test Infrastructure Setup (Week 1)

#### Overview
Create foundational test framework for OpenCode adapter. All subsequent phases will follow TDD: write test → run (FAIL) → implement → run (PASS).

#### Deliverables
- [ ] `tests/test_opencode_adapter.py` (~400 lines)
- [ ] Fixtures for temp directories, CLI helpers
- [ ] 15 initial failing tests for Phase 1
- [ ] Test execution time <2s per test suite

#### Tasks

**Task 0.1: Create Test Framework File**
- [ ] Create `tests/test_opencode_adapter.py`
- [ ] Add pytest imports (pytest, subprocess, tempfile, os, pathlib, json)
- [ ] Add docstring explaining TDD approach
- [ ] Structure: imports → fixtures → test classes → helper functions

**Task 0.2: Create Fixtures (Following conftest.py pattern)**
- [ ] `temp_lessons_base(tmp_path)` - Creates lessons directory with LESSONS.md
- [ ] `temp_state_dir(tmp_path)` - Creates state directory
- [ ] `temp_project_root(tmp_path)` - Creates project with .git and .claude-recall
- [ ] `temp_opencode_config(tmp_path)` - Creates config.json with config key
- [ ] `mock_providers()` - Mock provider.list() response for model detection
- [ ] All fixtures follow existing patterns from `tests/conftest.py`

**Task 0.3: Create Helper Functions**
- [ ] `run_cli(command, env=None)` - Run Python CLI, return (stdout, stderr, returncode)
- [ ] `add_lesson(title, content, **kwargs)` - Wrapper for CLI `add` command
- [ ] `create_handoff(title, **kwargs)` - Wrapper for CLI `handoff add` command
- [ ] `get_lesson(lesson_id)` - Get lesson by ID
- [ ] `list_lessons()` - List all lessons
- [ ] `get_active_handoff()` - Get currently active handoff
- [ ] `call_count(command)` - Count CLI invocations (mock tracking)
- [ ] `simulate_session(**kwargs)` - Simulate OpenCode session events

**Task 0.4: Write Phase 1 Failing Tests**
- [ ] Test 1.1: `test_plugin_uses_python_cli_not_old_bash_script()`
  - **Purpose**: Verify plugin doesn't reference old path
  - **Expected**: Plugin file contains `python3` or `core/cli.py`, NOT `lessons-manager.sh`
  - **Input**: Read `adapters/opencode/plugin.ts`
  - **Output**: PASS when path fixed in Phase 1.2
  
- [ ] Test 1.2: `test_lessons_command_uses_opencode_paths()`
  - **Purpose**: Verify /lessons command doesn't reference Claude Code paths
  - **Expected**: lessons.md contains `python3`, NOT `~/.claude/plugins/cache/`
  - **Input**: Read `adapters/opencode/command/lessons.md`
  - **Output**: PASS when fixed in Phase 1.3

- [ ] Test 1.3: `test_config_reads_from_shared_config_json()`
  - **Purpose**: Verify config reading from config.json
  - **Expected**: Config reads `config.enabled`, `config.topLessonsToShow`
  - **Input**: Create temp config.json, mock config loading
  - **Output**: PASS when implemented in Phase 2.2

- [ ] Test 1.4: `test_config_merges_with_defaults()`
  - **Purpose**: Verify config.json merges with defaults
  - **Expected**: Custom value overrides default, other defaults preserved
  - **Input**: Create config.json with partial config
  - **Output**: PASS when implemented in Phase 2.2

- [ ] Test 1.5: `test_detects_fast_model_from_providers()`
  - **Purpose**: Verify fast model detection from providers
  - **Expected**: Returns quality model (tool_call=true, reasoning=true)
  - **Input**: Mock provider.list() with various models
  - **Output**: PASS when implemented in Phase 2.4

- [ ] Test 1.6: `test_small_model_config_overrides_detection()`
  - **Purpose**: Verify small_model config overrides auto-detection
  - **Expected**: Returns configured model if available
  - **Input**: Set small_model in config.json, mock providers
  - **Output**: PASS when implemented in Phase 2.4

- [ ] Test 1.7: `test_filters_out_bad_models()`
  - **Purpose**: Verify quality filtering (tool_call + reasoning)
  - **Expected**: Only models with both capabilities returned
  - **Input**: Mock providers with mixed good/bad models
  - **Output**: PASS when implemented in Phase 2.4

- [ ] Test 1.8: `test_returns_none_if_no_good_models()`
  - **Purpose**: Verify graceful handling when no quality models
  - **Expected**: Returns None, logs warning
  - **Input**: Mock providers with no quality models
  - **Output**: PASS when implemented in Phase 2.4

**Task 0.5: Run Initial Tests (All Should FAIL)**
- [ ] Execute: `./run-tests.sh tests/test_opencode_adapter.py`
- [ ] Verify: All 8+ tests FAIL (red) - confirms TDD setup
- [ ] Verify: Test execution time <30s for 8 tests (~3.75s per test)
- [ ] Record: Baseline test times for performance tracking

#### Delegation Strategy (Phase 0)
```
DELEGATE TO: general-purpose agent
SCOPE: Implement Phase 0 tasks 0.1-0.5
CONTEXT: "Create test infrastructure for OpenCode adapter. Follow existing patterns from tests/conftest.py and tests/test_cli_commands.py. Write 15 failing tests for Phase 1 critical fixes. All tests should use real subprocess calls to Python CLI, not mocks. Estimated test time: <30s for initial run."
REVIEW POINT: After all tasks complete, review test file structure and fixture design before proceeding to Phase 1.
```

#### Review Checklist (After Phase 0)
- [ ] Test file created at correct location
- [ ] All fixtures follow existing patterns
- [ ] Helper functions documented with docstrings
- [ ] Initial tests FAIL (TDD confirmed)
- [ ] Test execution time acceptable
- [ ] Ready to proceed to Phase 1

---

### Phase 1: Critical Fixes (Week 1)

#### Overview
Fix three critical issues that block all other features:
1. Manager path points to old bash script → change to Python CLI
2. /lessons command docs reference Claude Code paths → update for OpenCode
3. Install script needs verification → ensure all files copied correctly

#### Deliverables
- [ ] Fixed manager path in `plugin.ts` (line 11)
- [ ] Updated CLI detection logic (~40 lines)
- [ ] Fixed /lessons command documentation (lines 13-26)
- [ ] Updated install script opencode function (lines 487-520)
- [ ] All Phase 1 tests PASS

#### Tasks

**Task 1.1: Fix Manager Path in plugin.ts**
- [ ] **File**: `adapters/opencode/plugin.ts`
- [ ] **Line**: 11
- [ ] **Before**:
  ```typescript
  const MANAGER = "~/.config/coding-agent-lessons/lessons-manager.sh"
  ```
- [ ] **After**:
  ```typescript
  // Detect Python CLI: installed → legacy → dev
  function findPythonManager(): string {
    const fs = require('fs');
    const path = require('path');
    
    const installed = path.join(os.homedir(), '.config', 'claude-recall', 'core', 'cli.py');
    const legacy = path.join(os.homedir(), '.config', 'claude-recall', 'cli.py');
    const dev = path.join(__dirname, '..', '..', 'core', 'cli.py');
    
    if (fs.existsSync(installed)) return installed;
    if (fs.existsSync(legacy)) return legacy;
    return dev;
  }
  
  const MANAGER = findPythonManager();
  ```
- [ ] **Test verification**: `test_plugin_uses_python_cli_not_old_bash_script` should PASS
- [ ] **Manual test**: Verify `findPythonManager()` returns valid path

**Task 1.2: Update /lessons Command Documentation**
- [ ] **File**: `adapters/opencode/command/lessons.md`
- [ ] **Lines**: 13-26
- [ ] **Before**:
  ```markdown
  ## Finding the CLI
  
  The CLI location varies by installation. Use this pattern to find and run it:
  
  ```bash
  RECALL_CLI=$(ls ~/.claude/plugins/cache/claude-recall/claude-recall/*/core/cli.py 2>/dev/null | head -1)
  python3 "$RECALL_CLI" <command> [args...]
  ```
  ```
- [ ] **After**:
  ```markdown
  ## Finding the CLI
  
  The CLI is managed by the plugin. Use subprocess calls:
  
  ```bash
  python3 ~/.config/claude-recall/core/cli.py <command> [args...]
  ```
  
  Or detect installed location:
  
  ```bash
  PYTHON_CLI=$(find ~/.config/claude-recall -name "cli.py" 2>/dev/null | head -1)
  python3 "$PYTHON_CLI" <command>
  ```
  ```
- [ ] **Test verification**: `test_lessons_command_uses_opencode_paths` should PASS
- [ ] **Manual test**: Copy CLI path detection command, verify it finds installed CLI

**Task 1.3: Update Install Script (opencode function)**
- [ ] **File**: `install.sh`
- [ ] **Lines**: 487-520 (opencode function)
- [ ] **Changes**:
  1. Verify `~/.config/opencode/` directory creation
  2. Ensure `plugin/` and `command/` subdirectories created
  3. Copy correct files from `adapters/opencode/`
  4. Append to `AGENTS.md` (not overwrite)
  5. Create placeholder `config.json` if missing
- [ ] **Implementation details**:
  ```bash
  install_opencode() {
      log_info "Installing OpenCode adapter..."
      
      local opencode_dir="$HOME/.config/opencode"
      local plugin_dir="$opencode_dir/plugin"
      local command_dir="$opencode_dir/command"
      
      mkdir -p "$plugin_dir" "$command_dir"
      
      # Install from adapters directory
      if [[ -f "$SCRIPT_DIR/adapters/opencode/plugin.ts" ]]; then
          cp "$SCRIPT_DIR/adapters/opencode/plugin.ts" "$plugin_dir/lessons.ts"
          log_success "Installed lessons.ts plugin"
      fi
      
      if [[ -f "$SCRIPT_DIR/adapters/opencode/command/lessons.md" ]]; then
          cp "$SCRIPT_DIR/adapters/opencode/command/lessons.md" "$command_dir/"
          log_success "Installed /lessons command"
      fi
      
      # Ensure AGENTS.md exists and append lessons section
      local agents_md="$opencode_dir/AGENTS.md"
      if [[ ! -f "$agents_md" ]]; then
          echo "# Global OpenCode Instructions" > "$agents_md"
      fi
      
      local lessons_section='
  ## Claude Recall
  
  A tiered learning cache that tracks corrections/patterns across sessions.
  
  - **Project lessons** (`[L###]`): `.claude-recall/LESSONS.md`
  - **System lessons** (`[S###]`): `~/.local/state/claude-recall/LESSONS.md`
  
  **Add**: Type `LESSON: title - content` or `SYSTEM LESSON: title - content`
  **Cite**: Reference `[L001]` when applying lessons (stars increase with use)
  **View**: `/lessons` command
  '
      
      if ! grep -q "Claude Recall" "$agents_md" 2>/dev/null; then
          echo "$lessons_section" >> "$agents_md"
          log_success "Added Claude Recall section to AGENTS.md"
      fi
      
      log_success "Installed OpenCode adapter"
  }
  ```
- [ ] **Test verification**: Manual install test
  - Run: `./install.sh --opencode` in temp env
  - Verify: `~/.config/opencode/plugins/lessons.ts` exists
  - Verify: `~/.config/opencode/command/lessons.md` exists
  - Verify: `~/.config/opencode/AGENTS.md` contains Claude Recall section

#### Delegation Strategy (Phase 1)
```
DELEGATE TO: general-purpose agent
SCOPE: Implement Phase 1 tasks 1.1-1.3
CONTEXT: "Fix three critical issues in OpenCode adapter: 1) Update manager path from old bash script to Python CLI with fallback logic (installed → legacy → dev). 2) Update /lessons command documentation to remove Claude Code-specific paths and use direct Python CLI calls. 3) Update install.sh opencode function to verify directory creation, file copying, and AGENTS.md appending. Follow exact before/after states specified in the plan. All changes should make existing Phase 1 tests PASS."
REVIEW POINT: After all tasks complete, review each file change and verify tests pass before proceeding to Phase 2.
```

#### Review Checklist (After Phase 1)
- [ ] `plugin.ts` line 11 uses `findPythonManager()` function
- [ ] Fallback logic works for all three paths (installed, legacy, dev)
- [ ] `lessons.md` has no Claude Code path references
- [ ] `lessons.md` documents OpenCode-specific CLI usage
- [ ] Install script creates all directories correctly
- [ ] `AGENTS.md` appended (not overwritten)
- [ ] All Phase 1 tests PASS
- [ ] Ready to proceed to Phase 2

---

### Phase 2: Configuration System (Week 1-2)

#### Overview
Implement configuration system that reads from `config.json`, merges with defaults, and provides fast model detection without assuming Haiku availability.

#### Deliverables
- [ ] Config loading function in `plugin.ts` (~50 lines)
- [ ] Fast model detection function (~80 lines)
- [ ] Model filtering logic (tool_call + reasoning required)
- [ ] Preferred model ordering (grok-code-fast-1 → haiku → gpt-5-mini)
- [ ] All Phase 2 tests PASS

#### Tasks

**Task 2.1: Add Configuration Loading**
- [ ] **File**: `adapters/opencode/plugin.ts`
- [ ] **Location**: After imports, before plugin function
- [ ] **Implementation** (~50 lines):
  ```typescript
  import { readFileSync, existsSync, writeFileSync } from 'fs';
  import { join } from 'path';
  import { homedir } from 'os';
  
  interface Config {
    enabled: boolean;
    maxLessons: number;
    topLessonsToShow: number;
    relevanceTopN: number;
    remindEvery: number;
    promotionThreshold: number;
    decayIntervalDays: number;
    debugLevel: number;
    small_model?: string;
  }
  
  const DEFAULT_CONFIG: Config = {
    enabled: true,
    maxLessons: 30,
    topLessonsToShow: 5,
    relevanceTopN: 5,
    remindEvery: 12,
    promotionThreshold: 50,
    decayIntervalDays: 7,
    debugLevel: 1,
  };
  
  function loadConfig(): Config {
    const configPath = join(homedir(), '.config', 'claude-recall', 'config.json');
    
    if (!existsSync(configPath)) {
      console.warn('[claude-recall] No config.json found, using defaults');
      return DEFAULT_CONFIG;
    }
    
    try {
      const configValues = JSON.parse(readFileSync(configPath, 'utf8'));
      
      const merged = { ...DEFAULT_CONFIG, ...configValues };
      
      if (merged.debugLevel >= 2) {
        console.log('[claude-recall] Loaded config:', merged);
      }
      
      return merged;
    } catch (e) {
      console.error('[claude-recall] Failed to load config:', e);
      return DEFAULT_CONFIG;
    }
  }
  
  const CONFIG = loadConfig();
  ```
- [ ] **Test verification**: `test_config_reads_from_shared_config_json` should PASS
- [ ] **Test verification**: `test_config_merges_with_defaults` should PASS

**Task 2.2: Add Fast Model Detection**
- [ ] **File**: `adapters/opencode/plugin.ts`
- [ ] **Location**: After config loading
- [ ] **Implementation** (~80 lines):
  ```typescript
  interface ModelInfo {
    name: string;
    tool_call: boolean;
    reasoning: boolean;
    cost?: { input: number; output: number };
  }
  
  interface Provider {
    id: string;
    models: Record<string, ModelInfo>;
  }
  
  interface ProviderListResponse {
    data: {
      all: Provider[];
      default: { [providerId: string]: string };
      connected: string[];
    };
  }
  
  // Quality filters for "good" models
  const MIN_QUALITY = {
    tool_call: true,
    reasoning: true,
  };
  
  // Preferred models (in order of preference - free, fast, capable)
  const PREFERRED_MODELS = [
    'grok-code-fast-1',        // Free, fast, capable (rivals Opus 4.1)
    'claude-3-5-haiku-latest', // Haiku if available
    'gpt-5-mini',              // Free with Copilot
    'gpt-4o-mini',             // Good free fallback
  ];
  
  let cachedFastModel: string | null = null;
  
  async function detectFastModel(
    client: any,
    configuredSmallModel?: string
  ): Promise<string | null> {
    // If small_model configured and available, use it
    if (configuredSmallModel) {
      try {
        const providers = await client.provider.list() as ProviderListResponse;
        const isAvailable = providers.data.all.some(p =>
          configuredSmallModel in p.models
        );
        if (isAvailable) {
          if (CONFIG.debugLevel >= 2) {
            console.log(`[claude-recall] Using configured small_model: ${configuredSmallModel}`);
          }
          return configuredSmallModel;
        }
      } catch (e) {
        console.warn('[claude-recall] Failed to check small_model availability:', e);
      }
    }
    
    // Query available providers
    try {
      const providers = await client.provider.list() as ProviderListResponse;
      
      // Collect all models with minimum quality
      const qualityModels: Array<{provider: string; model: string; info: ModelInfo}> = [];
      for (const provider of providers.data.all) {
        for (const [modelId, info] of Object.entries(provider.models)) {
          if (info.tool_call && info.reasoning) {
            qualityModels.push({ provider: provider.id, model: modelId, info });
          }
        }
      }
      
      if (qualityModels.length === 0) {
        console.warn('[claude-recall] No quality models available');
        return null;
      }
      
      if (CONFIG.debugLevel >= 2) {
        console.log(`[claude-recall] Found ${qualityModels.length} quality models`);
      }
      
      // Prefer known fast models
      for (const pref of PREFERRED_MODELS) {
        const found = qualityModels.find(m => m.model === pref);
        if (found) {
          if (CONFIG.debugLevel >= 2) {
            console.log(`[claude-recall] Using preferred model: ${found.model}`);
          }
          return found.model;
        }
      }
      
      // Otherwise, pick first quality model (provider order determines)
      const fallback = qualityModels[0];
      if (CONFIG.debugLevel >= 2) {
        console.log(`[claude-recall] Using fallback model: ${fallback.model}`);
      }
      return fallback.model;
      
    } catch (e) {
      console.error('[claude-recall] Failed to detect fast model:', e);
      return null;
    }
  }
  ```
- [ ] **Test verification**: `test_detects_fast_model_from_providers` should PASS
- [ ] **Test verification**: `test_small_model_config_overrides_detection` should PASS
- [ ] **Test verification**: `test_filters_out_bad_models` should PASS
- [ ] **Test verification**: `test_returns_none_if_no_good_models` should PASS

**Task 2.3: Integrate Config and Model Detection into Plugin**
- [ ] **File**: `adapters/opencode/plugin.ts`
- [ ] **Location**: Inside plugin function, before return statement
- [ ] **Implementation** (~20 lines):
  ```typescript
  export const LessonsPlugin: Plugin = async ({ $, client }) => {
    // Detect fast model at initialization
    const fastModel = await detectFastModel(client, CONFIG.small_model);
    
    if (!fastModel) {
      console.warn('[claude-recall] No fast model available, some features may be disabled');
    }
    
    // Initialize state
    const sessionCheckpoints = new Map<string, number>();
    let isFirstPrompt = true;
    let promptCount = 0;
    
    return {
      // handlers will use CONFIG and fastModel
      ...
    };
  };
  ```
- [ ] **Manual test**: Verify plugin initializes without errors
- [ ] **Manual test**: Check debug logs show model detection

#### Delegation Strategy (Phase 2)
```
DELEGATE TO: general-purpose agent
SCOPE: Implement Phase 2 tasks 2.1-2.3
CONTEXT: "Implement configuration system for OpenCode adapter: 1) Add loadConfig() function that reads ~/.config/claude-recall/config.json, parses config key, merges with DEFAULT_CONFIG from plugins/claude-recall/config.json. 2) Add detectFastModel() function that queries OpenCode's client.provider.list(), filters for models with tool_call=true AND reasoning=true, prefers PREFERRED_MODELS in order, falls back to first quality model. 3) Integrate config and model detection into plugin initialization. Follow exact code specifications in the plan. All changes should make existing Phase 2 tests PASS."
REVIEW POINT: After all tasks complete, review config loading and model detection logic, verify tests pass, and verify plugin initializes correctly before proceeding to Phase 3.
```

#### Review Checklist (After Phase 2)
- [ ] Config loads from correct path (`~/.config/claude-recall/config.json`)
- [ ] Config merges with defaults correctly
- [ ] `config` key parsed properly
- [ ] Model detection queries `client.provider.list()`
- [ ] Quality filtering works (tool_call + reasoning)
- [ ] Preferred models checked in order
- [ ] Fallback to first quality model works
- [ ] `small_model` config overrides detection
- [ ] All Phase 2 tests PASS
- [ ] Ready to proceed to Phase 3

---

## APPENDIX: Remaining Phases (Draft Outline)

**Note**: Phases 3-7 are outlined here. Full specifications will be written in subsequent plan updates.

### Phase 3: Core Lessons Features (Week 2-3)
**Tasks**:
- Smart injection (relevance scoring on first prompt)
- AI lesson capture from assistant output
- Lesson decay (weekly)
- Periodic reminders (high-star lessons)

### Phase 4: Handoffs System (Week 3-4)
**Tasks**:
- Handoff injection at session start
- TodoWrite sync to active handoff
- Handoff pattern capture from assistant output
- `/handoffs` command documentation

### Phase 5: Compaction & Context (Week 4)
**Tasks**:
- Pre-compact context injection
- Post-compact handoff update
- Session snapshot when no active handoff

### Phase 6: Debug Logging (Week 5)
**Tasks**:
- Structured JSON logging
- Log to debug.log
- Configurable log levels

### Phase 7: Documentation & Verification (Week 6)
**Tasks**:
- Update README.md
- Update docs/DEPLOYMENT.md
- Update CLAUDE.md
- Full test suite verification
- Manual installation testing

---

**PLAN END - Phase 0-2 detailed specifications complete. Phases 3-7 will be expanded as work progresses.**
