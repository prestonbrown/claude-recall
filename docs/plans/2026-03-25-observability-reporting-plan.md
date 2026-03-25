# Observability & Reporting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add session event logging, precision tracking, `/recall stats` reporting, trigger keyword support, and weekly digest to claude-recall.

**Architecture:** New `eventlog` package writes/reads append-only JSONL. Hooks emit events during injection and citation. CLI `stats`/`dismiss`/`digest` commands consume the log. BM25 scorer gains trigger-aware tokenization. All changes are additive — no existing behavior changes.

**Tech Stack:** Go 1.21 stdlib only (no external deps). Standard `testing.T` tests. JSONL file format.

**Spec:** `docs/plans/2026-03-25-observability-reporting-design.md`

---

## File Structure

| File | Responsibility |
|------|---------------|
| `go/internal/eventlog/eventlog.go` | **New** — Event type, Append(), Read(), Prune() for session-log.jsonl |
| `go/internal/eventlog/eventlog_test.go` | **New** — Tests for event log I/O and pruning |
| `go/internal/eventlog/precision.go` | **New** — PrecisionByLesson(), TriggerSuggestions() |
| `go/internal/eventlog/precision_test.go` | **New** — Tests for precision computation |
| `go/internal/scoring/bm25.go` | **Modify** — Trigger-aware tokenization in NewBM25Scorer() |
| `go/internal/scoring/bm25_test.go` | **Modify** — Add trigger tokenization tests |
| `go/cmd/recall/app.go` | **Modify** — Add stats, dismiss, digest command dispatch + handlers |
| `go/cmd/recall-hook/inject.go` | **Modify** — Emit injection events from runInjectCombined() |
| `go/cmd/recall-hook/stopall.go` | **Modify** — Emit citation events after store.Cite() |
| `go/internal/lessons/decay.go` | **Modify** — Add eventlog.Prune() call in Decay() |
| `plugins/claude-recall/commands/stats.md` | **New** — `/recall stats` slash command |
| `plugins/claude-recall/commands/dismiss.md` | **New** — `/recall dismiss` slash command |
| `plugins/claude-recall/commands/digest.md` | **New** — `/recall digest` slash command |

---

## Phase 1: Event Log Foundation

### Task 1: Event Log Package — Data Model & Append

**Files:**
- Create: `go/internal/eventlog/eventlog.go`
- Create: `go/internal/eventlog/eventlog_test.go`

- [ ] **Step 1: Write failing test for Event struct and Append**

```go
// go/internal/eventlog/eventlog_test.go
package eventlog

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestAppend_WritesJSONLLine(t *testing.T) {
	dir := t.TempDir()
	logPath := filepath.Join(dir, "session-log.jsonl")
	log := New(logPath)

	err := log.Append(Event{
		Timestamp: time.Date(2026, 3, 25, 10, 0, 0, 0, time.UTC),
		Type:      "injection",
		Session:   "sess-123",
		Lesson:    "L059",
		Score:     8,
		Query:     "safe_delete vs deferred",
		Hook:      "prompt_submit",
		Project:   "/home/user/myproject",
	})
	if err != nil {
		t.Fatalf("Append failed: %v", err)
	}

	data, err := os.ReadFile(logPath)
	if err != nil {
		t.Fatalf("ReadFile failed: %v", err)
	}

	line := string(data)
	if line == "" {
		t.Fatal("log file is empty")
	}
	// Verify it contains expected fields
	for _, want := range []string{`"type":"injection"`, `"lesson":"L059"`, `"score":8`, `"session":"sess-123"`} {
		if !strings.Contains(line, want) {
			t.Errorf("log line missing %s, got: %s", want, line)
		}
	}
}

func TestAppend_AppendsMultipleLines(t *testing.T) {
	dir := t.TempDir()
	logPath := filepath.Join(dir, "session-log.jsonl")
	log := New(logPath)

	for i := 0; i < 3; i++ {
		err := log.Append(Event{
			Timestamp: time.Now(),
			Type:      "injection",
			Session:   "sess-123",
			Lesson:    "L001",
		})
		if err != nil {
			t.Fatalf("Append %d failed: %v", i, err)
		}
	}

	events, err := log.Read()
	if err != nil {
		t.Fatalf("Read failed: %v", err)
	}
	if len(events) != 3 {
		t.Errorf("expected 3 events, got %d", len(events))
	}
}

// Use strings.Contains — import "strings" at top of file
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/pbrown/Code/claude-recall && go test ./go/internal/eventlog/ -v -run TestAppend`
Expected: FAIL — package does not exist

- [ ] **Step 3: Implement Event struct, New(), Append(), Read()**

```go
// go/internal/eventlog/eventlog.go
package eventlog

import (
	"bufio"
	"encoding/json"
	"os"
	"time"
)

// Event represents a single event in the session log.
type Event struct {
	Timestamp time.Time `json:"ts"`
	Type      string    `json:"type"`                // injection, citation, dismiss, session_start
	Session   string    `json:"session"`
	Lesson    string    `json:"lesson,omitempty"`     // single ID for injection/citation/dismiss
	Lessons   []string  `json:"lessons,omitempty"`    // list for session_start
	Score     int       `json:"score,omitempty"`      // BM25 score (injections only)
	Query     string    `json:"query,omitempty"`      // query text (injections only)
	Hook      string    `json:"hook,omitempty"`       // session_start or prompt_submit
	Project   string    `json:"project,omitempty"`
}

// Log manages the session event log file.
type Log struct {
	path string
}

// New creates a Log pointing at the given file path.
func New(path string) *Log {
	return &Log{path: path}
}

// Append writes a single event as a JSONL line.
func (l *Log) Append(e Event) error {
	f, err := os.OpenFile(l.path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		return err
	}
	defer f.Close()

	data, err := json.Marshal(e)
	if err != nil {
		return err
	}
	_, err = f.WriteString(string(data) + "\n")
	return err
}

// Read returns all events from the log file.
func (l *Log) Read() ([]Event, error) {
	f, err := os.Open(l.path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, err
	}
	defer f.Close()

	var events []Event
	scanner := bufio.NewScanner(f)
	// Allow long lines (queries can be large)
	scanner.Buffer(make([]byte, 0, 64*1024), 1024*1024)
	for scanner.Scan() {
		var e Event
		if err := json.Unmarshal(scanner.Bytes(), &e); err != nil {
			continue // skip malformed lines
		}
		events = append(events, e)
	}
	return events, scanner.Err()
}
```

Note: The `Read()` function has a compile error (`return err` without the nil). Fix:
```go
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, err
	}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/pbrown/Code/claude-recall && go test ./go/internal/eventlog/ -v -run TestAppend`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /home/pbrown/Code/claude-recall
git add go/internal/eventlog/eventlog.go go/internal/eventlog/eventlog_test.go
git commit -m "feat(eventlog): add Event model, Append(), and Read() for session-log.jsonl"
```

---

### Task 2: Event Log — Read with Filters and Prune

**Files:**
- Modify: `go/internal/eventlog/eventlog.go`
- Modify: `go/internal/eventlog/eventlog_test.go`

- [ ] **Step 1: Write failing tests for ReadFiltered and Prune**

```go
// Add to go/internal/eventlog/eventlog_test.go

func TestReadBySession(t *testing.T) {
	dir := t.TempDir()
	logPath := filepath.Join(dir, "session-log.jsonl")
	log := New(logPath)

	log.Append(Event{Timestamp: time.Now(), Type: "injection", Session: "s1", Lesson: "L001"})
	log.Append(Event{Timestamp: time.Now(), Type: "injection", Session: "s2", Lesson: "L002"})
	log.Append(Event{Timestamp: time.Now(), Type: "citation", Session: "s1", Lesson: "L001"})

	events, err := log.ReadFiltered(Filter{Session: "s1"})
	if err != nil {
		t.Fatalf("ReadFiltered failed: %v", err)
	}
	if len(events) != 2 {
		t.Errorf("expected 2 events for s1, got %d", len(events))
	}
}

func TestReadByLesson(t *testing.T) {
	dir := t.TempDir()
	logPath := filepath.Join(dir, "session-log.jsonl")
	log := New(logPath)

	log.Append(Event{Timestamp: time.Now(), Type: "injection", Session: "s1", Lesson: "L001"})
	log.Append(Event{Timestamp: time.Now(), Type: "injection", Session: "s1", Lesson: "L002"})
	log.Append(Event{Timestamp: time.Now(), Type: "citation", Session: "s1", Lesson: "L001"})

	events, err := log.ReadFiltered(Filter{Lesson: "L001"})
	if err != nil {
		t.Fatalf("ReadFiltered failed: %v", err)
	}
	if len(events) != 2 {
		t.Errorf("expected 2 events for L001, got %d", len(events))
	}
}

func TestReadBySince(t *testing.T) {
	dir := t.TempDir()
	logPath := filepath.Join(dir, "session-log.jsonl")
	log := New(logPath)

	old := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)
	recent := time.Date(2026, 3, 25, 0, 0, 0, 0, time.UTC)
	cutoff := time.Date(2026, 3, 1, 0, 0, 0, 0, time.UTC)

	log.Append(Event{Timestamp: old, Type: "injection", Session: "s1", Lesson: "L001"})
	log.Append(Event{Timestamp: recent, Type: "injection", Session: "s2", Lesson: "L002"})

	events, err := log.ReadFiltered(Filter{Since: cutoff})
	if err != nil {
		t.Fatalf("ReadFiltered failed: %v", err)
	}
	if len(events) != 1 {
		t.Errorf("expected 1 event since cutoff, got %d", len(events))
	}
	if events[0].Lesson != "L002" {
		t.Errorf("expected L002, got %s", events[0].Lesson)
	}
}

func TestPrune_RemovesOldEntries(t *testing.T) {
	dir := t.TempDir()
	logPath := filepath.Join(dir, "session-log.jsonl")
	log := New(logPath)

	old := time.Now().AddDate(0, 0, -100) // 100 days ago
	recent := time.Now()

	log.Append(Event{Timestamp: old, Type: "injection", Session: "s1", Lesson: "L001"})
	log.Append(Event{Timestamp: old, Type: "citation", Session: "s1", Lesson: "L001"})
	log.Append(Event{Timestamp: recent, Type: "injection", Session: "s2", Lesson: "L002"})

	pruned, err := log.Prune(90) // 90-day retention
	if err != nil {
		t.Fatalf("Prune failed: %v", err)
	}
	if pruned != 2 {
		t.Errorf("expected 2 pruned, got %d", pruned)
	}

	events, _ := log.Read()
	if len(events) != 1 {
		t.Errorf("expected 1 remaining event, got %d", len(events))
	}
}

func TestPrune_NoopOnEmptyFile(t *testing.T) {
	dir := t.TempDir()
	logPath := filepath.Join(dir, "session-log.jsonl")
	log := New(logPath)

	pruned, err := log.Prune(90)
	if err != nil {
		t.Fatalf("Prune failed: %v", err)
	}
	if pruned != 0 {
		t.Errorf("expected 0 pruned, got %d", pruned)
	}
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/pbrown/Code/claude-recall && go test ./go/internal/eventlog/ -v -run "TestRead|TestPrune"`
Expected: FAIL — Filter type and ReadFiltered/Prune not defined

- [ ] **Step 3: Implement Filter, ReadFiltered(), Prune()**

Add to `go/internal/eventlog/eventlog.go`:

```go
// Filter controls which events are returned by ReadFiltered.
type Filter struct {
	Session string    // filter by session ID
	Lesson  string    // filter by lesson ID
	Project string    // filter by project path
	Since   time.Time // only events on or after this time
	Type    string    // filter by event type
}

// ReadFiltered returns events matching the given filter.
func (l *Log) ReadFiltered(f Filter) ([]Event, error) {
	all, err := l.Read()
	if err != nil {
		return nil, err
	}

	var result []Event
	for _, e := range all {
		if f.Session != "" && e.Session != f.Session {
			continue
		}
		if f.Lesson != "" && e.Lesson != f.Lesson {
			continue
		}
		if f.Project != "" && e.Project != f.Project {
			continue
		}
		if !f.Since.IsZero() && e.Timestamp.Before(f.Since) {
			continue
		}
		if f.Type != "" && e.Type != f.Type {
			continue
		}
		result = append(result, e)
	}
	return result, nil
}

// Prune removes events older than retentionDays. Returns count of pruned entries.
func (l *Log) Prune(retentionDays int) (int, error) {
	all, err := l.Read()
	if err != nil {
		return 0, err
	}
	if len(all) == 0 {
		return 0, nil
	}

	cutoff := time.Now().AddDate(0, 0, -retentionDays)
	var kept []Event
	pruned := 0
	for _, e := range all {
		if e.Timestamp.Before(cutoff) {
			pruned++
		} else {
			kept = append(kept, e)
		}
	}

	if pruned == 0 {
		return 0, nil
	}

	// Rewrite file with only kept events
	f, err := os.Create(l.path)
	if err != nil {
		return 0, err
	}
	defer f.Close()

	for _, e := range kept {
		data, err := json.Marshal(e)
		if err != nil {
			continue
		}
		f.WriteString(string(data) + "\n")
	}

	return pruned, nil
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/pbrown/Code/claude-recall && go test ./go/internal/eventlog/ -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
cd /home/pbrown/Code/claude-recall
git add go/internal/eventlog/
git commit -m "feat(eventlog): add ReadFiltered() with session/lesson/time filters and Prune()"
```

---

### Task 2.5: Config — Add Event Log Settings

**Files:**
- Modify: `go/internal/config/config.go`

**Reference:** Read `config.go` to see existing Config struct and Load() function. Add three new fields.

- [ ] **Step 1: Add fields to Config struct**

Add to the `Config` struct in `config.go`:

```go
	EventLogEnabled      bool `json:"eventLogEnabled"`       // default: true
	EventLogRetentionDays int  `json:"eventLogRetentionDays"` // default: 90
	DigestEnabled        bool `json:"digestEnabled"`          // default: true
```

- [ ] **Step 2: Set defaults in Load()**

In the `Load()` function, after creating the Config, set defaults:

```go
	// Event log defaults
	if cfg.EventLogRetentionDays == 0 {
		cfg.EventLogRetentionDays = 90
	}
	// EventLogEnabled and DigestEnabled default to true (Go zero-value is false)
	// Handle via JSON unmarshaling: if field absent, set to true
	cfg.EventLogEnabled = true
	cfg.DigestEnabled = true
	// Re-unmarshal to let explicit false override
```

Note: The exact approach depends on how the existing config JSON unmarshaling works. Read `config.go` and follow the same pattern. If the config uses env var overrides, add `CLAUDE_RECALL_EVENT_LOG_ENABLED` and `CLAUDE_RECALL_EVENT_LOG_RETENTION_DAYS`.

- [ ] **Step 3: Build to verify**

Run: `cd /home/pbrown/Code/claude-recall && go build ./go/...`
Expected: Clean build

- [ ] **Step 4: Commit**

```bash
cd /home/pbrown/Code/claude-recall
git add go/internal/config/config.go
git commit -m "feat(config): add eventLogEnabled, eventLogRetentionDays, digestEnabled settings"
```

---

### Task 3: Hook Integration — Emit Injection Events

**Files:**
- Modify: `go/cmd/recall-hook/inject.go` (around `runInjectCombined()` and `runInject()`)

**Reference:** Read `go/cmd/recall-hook/inject.go` before editing. The key function is `runInjectCombined()` which formats lessons and outputs JSON. The `injectInput` struct already has `SessionID string` and `Cwd string` — use these for event logging. After the lessons are selected and formatted, emit injection events.

**Imports to add:** `"github.com/pbrown/claude-recall/internal/eventlog"` and `"time"`.

- [ ] **Step 1: Write failing test for injection event emission**

```go
// go/internal/eventlog/eventlog_test.go — add

func TestAppend_InjectionWithAllFields(t *testing.T) {
	dir := t.TempDir()
	logPath := filepath.Join(dir, "session-log.jsonl")
	log := New(logPath)

	err := log.Append(Event{
		Timestamp: time.Now(),
		Type:      "injection",
		Session:   "sess-abc",
		Lesson:    "L074",
		Score:     9,
		Query:     "generation counter for deferred callbacks",
		Hook:      "prompt_submit",
		Project:   "/home/user/helixscreen",
	})
	if err != nil {
		t.Fatalf("Append failed: %v", err)
	}

	events, _ := log.Read()
	if len(events) != 1 {
		t.Fatalf("expected 1 event, got %d", len(events))
	}
	e := events[0]
	if e.Type != "injection" || e.Lesson != "L074" || e.Score != 9 || e.Query == "" {
		t.Errorf("unexpected event: %+v", e)
	}
}
```

- [ ] **Step 2: Run test — should pass (Append already handles all fields)**

Run: `cd /home/pbrown/Code/claude-recall && go test ./go/internal/eventlog/ -v -run TestAppend_InjectionWithAllFields`
Expected: PASS

- [ ] **Step 3: Modify runInjectCombined() to emit injection events**

In `go/cmd/recall-hook/inject.go`, after the top-N lessons are selected and before output, add event logging. Read the current file first to find exact insertion point.

Key changes to `runInjectCombined()`:
1. Import `"github.com/pbrown/claude-recall/go/internal/eventlog"`
2. After `topLessons := allLessons[:n]` and before output marshaling, create event log and emit:

```go
// Emit injection events to session log
eventLogPath := filepath.Join(cfg.StateDir, "session-log.jsonl")
elog := eventlog.New(eventLogPath)
now := time.Now()
for _, lesson := range topLessons {
    elog.Append(eventlog.Event{
        Timestamp: now,
        Type:      "injection",
        Session:   input.SessionID,
        Lesson:    lesson.ID,
        Hook:      "session_start",
        Project:   projectDir,
    })
}
```

Similarly for the `score-local` path in `go/cmd/recall/app.go` `runScoreLocal()` — this needs the query text and BM25 scores. Read the function to find the exact integration point. The scored lessons and query are available after BM25 scoring. Add:

```go
// After scoring, emit injection events for lessons that will be output
eventLogPath := filepath.Join(a.stateDir, "session-log.jsonl")
elog := eventlog.New(eventLogPath)
now := time.Now()
for _, sl := range topResults {
    elog.Append(eventlog.Event{
        Timestamp: now,
        Type:      "injection",
        Session:   sessionID, // may need to pass through
        Lesson:    sl.Lesson.ID,
        Score:     sl.Score,
        Query:     query,
        Hook:      "prompt_submit",
        Project:   a.projectDir,
    })
}
```

Note: The `score-local` path may not have session ID available. Check the function signature — if not passed, use empty string (session-start events will provide session grouping).

- [ ] **Step 4: Build to verify compilation**

Run: `cd /home/pbrown/Code/claude-recall && go build ./go/cmd/recall-hook/ && go build ./go/cmd/recall/`
Expected: Clean build

- [ ] **Step 5: Commit**

```bash
cd /home/pbrown/Code/claude-recall
git add go/cmd/recall-hook/inject.go go/cmd/recall/app.go
git commit -m "feat(eventlog): emit injection events from session-start and score-local hooks"
```

---

### Task 4: Hook Integration — Emit Citation Events

**Files:**
- Modify: `go/cmd/recall-hook/stopall.go` (in `runStopAll()`)
- Modify: `go/cmd/recall-hook/stop.go` (in `executeStop()`)

**Reference:** Read both files before editing. In `stopall.go`, citations are extracted and processed in a loop calling `store.Cite(id)`. After each successful cite, also emit a citation event.

- [ ] **Step 1: Modify stopall.go to emit citation events**

In `runStopAll()`, after the citation processing loop, add event logging:

```go
// After successful citations are processed, emit to session log
eventLogPath := filepath.Join(cfg.StateDir, "session-log.jsonl")
elog := eventlog.New(eventLogPath)
now := time.Now()
for _, id := range processedCitationIDs {
    elog.Append(eventlog.Event{
        Timestamp: now,
        Type:      "citation",
        Session:   input.SessionID,
        Lesson:    id,
        Project:   projectDir,
    })
}
```

Similarly in `stop.go` `executeStop()`, after the `store.Cite(id)` loop at the end:

```go
// Emit citation events
eventLogPath := filepath.Join(stateDir, "session-log.jsonl")
elog := eventlog.New(eventLogPath)
now := time.Now()
for _, id := range uniqueCitations {
    elog.Append(eventlog.Event{
        Timestamp: now,
        Type:      "citation",
        Session:   input.SessionID,
        Lesson:    id,
        Project:   projectDir,
    })
}
```

- [ ] **Step 2: Build to verify compilation**

Run: `cd /home/pbrown/Code/claude-recall && go build ./go/cmd/recall-hook/`
Expected: Clean build

- [ ] **Step 3: Commit**

```bash
cd /home/pbrown/Code/claude-recall
git add go/cmd/recall-hook/stopall.go go/cmd/recall-hook/stop.go
git commit -m "feat(eventlog): emit citation events from stop hooks"
```

---

### Task 5: Prune Integration in Decay Cycle

**Files:**
- Modify: `go/internal/lessons/decay.go`

**Reference:** Read `decay.go`. The `Decay()` function checks `NeedsDecay()`, calls `ForceDecay()`, updates state. Add a `Prune()` call after decay completes.

- [ ] **Step 1: Write failing test for prune-on-decay**

```go
// go/internal/eventlog/eventlog_test.go — add

func TestPrune_IntegrationWithRetention(t *testing.T) {
	dir := t.TempDir()
	logPath := filepath.Join(dir, "session-log.jsonl")
	log := New(logPath)

	// Add events spanning 120 days
	for i := 0; i < 120; i++ {
		ts := time.Now().AddDate(0, 0, -i)
		log.Append(Event{Timestamp: ts, Type: "injection", Session: "s1", Lesson: "L001"})
	}

	events, _ := log.Read()
	if len(events) != 120 {
		t.Fatalf("expected 120 events, got %d", len(events))
	}

	pruned, err := log.Prune(90)
	if err != nil {
		t.Fatalf("Prune failed: %v", err)
	}
	if pruned != 30 {
		t.Errorf("expected 30 pruned, got %d", pruned)
	}

	remaining, _ := log.Read()
	if len(remaining) != 90 {
		t.Errorf("expected 90 remaining, got %d", len(remaining))
	}
}
```

- [ ] **Step 2: Run test**

Run: `cd /home/pbrown/Code/claude-recall && go test ./go/internal/eventlog/ -v -run TestPrune_Integration`
Expected: PASS (Prune already implemented)

- [ ] **Step 3: Add prune call to decay.go**

In `go/internal/lessons/decay.go`, in the `Decay()` function, after `ForceDecay()` returns and state is updated, add:

```go
// Prune old event log entries (opportunistic, non-fatal)
eventLogPath := filepath.Join(filepath.Dir(config.StateFile), "session-log.jsonl")
elog := eventlog.New(eventLogPath)
if pruned, err := elog.Prune(90); err == nil && pruned > 0 {
    // Logged but not returned — pruning is housekeeping, not core decay
}
```

Import: `"github.com/pbrown/claude-recall/go/internal/eventlog"`

- [ ] **Step 4: Build and run existing decay tests**

Run: `cd /home/pbrown/Code/claude-recall && go test ./go/internal/lessons/ -v -run TestDecay`
Expected: ALL PASS (existing tests unaffected)

- [ ] **Step 5: Commit**

```bash
cd /home/pbrown/Code/claude-recall
git add go/internal/lessons/decay.go go/internal/eventlog/eventlog_test.go
git commit -m "feat(eventlog): prune old events during weekly decay cycle"
```

---

### Task 6: `recall stats` — Session Mode

**Files:**
- Modify: `go/cmd/recall/app.go`

**Reference:** Read `app.go` command dispatch (around line 84-140). New command `stats` follows the same pattern as existing commands. The handler reads the event log, filters by session, and outputs a formatted report.

- [ ] **Step 1: Add stats command to dispatch**

In `app.go` `Run()` method, add to the switch:

```go
case "stats":
    return a.runStats()
```

- [ ] **Step 2: Implement runStats() — session mode**

```go
func (a *App) runStats() int {
	if err := a.initPaths(); err != nil {
		fmt.Fprintf(a.stderr, "error: %v\n", err)
		return 1
	}

	// Check for --lesson or --weekly flags
	args := os.Args[2:]
	if len(args) > 0 {
		switch {
		case args[0] == "--weekly":
			return a.runStatsWeekly()
		case args[0] == "--lesson" && len(args) > 1:
			return a.runStatsLesson(args[1])
		default:
			// Treat bare arg as lesson ID
			if len(args[0]) >= 2 && (args[0][0] == 'L' || args[0][0] == 'S') {
				return a.runStatsLesson(args[0])
			}
		}
	}

	return a.runStatsSession()
}

func (a *App) runStatsSession() int {
	eventLogPath := filepath.Join(a.stateDir, "session-log.jsonl")
	elog := eventlog.New(eventLogPath)

	// Read all events (session mode shows most recent session if no ID)
	events, err := elog.Read()
	if err != nil {
		fmt.Fprintf(a.stderr, "error reading event log: %v\n", err)
		return 1
	}

	if len(events) == 0 {
		fmt.Fprintln(a.stdout, "No events recorded yet. Events are logged after lessons are injected and cited.")
		return 0
	}

	// Find latest session
	sessionID := ""
	for i := len(events) - 1; i >= 0; i-- {
		if events[i].Session != "" {
			sessionID = events[i].Session
			break
		}
	}

	if sessionID == "" {
		fmt.Fprintln(a.stdout, "No session data found.")
		return 0
	}

	// Filter to this session
	var sessionEvents []eventlog.Event
	for _, e := range events {
		if e.Session == sessionID {
			sessionEvents = append(sessionEvents, e)
		}
	}

	// Count injections and citations
	injections := make(map[string]int)  // lesson -> count
	citations := make(map[string]bool)  // lesson -> cited?
	injectionScores := make(map[string]int) // lesson -> max score

	for _, e := range sessionEvents {
		switch e.Type {
		case "injection":
			injections[e.Lesson]++
			if e.Score > injectionScores[e.Lesson] {
				injectionScores[e.Lesson] = e.Score
			}
		case "citation":
			citations[e.Lesson] = true
		}
	}

	totalInjections := 0
	for _, count := range injections {
		totalInjections += count
	}

	fmt.Fprintf(a.stdout, "This Session\n")
	fmt.Fprintf(a.stdout, "  Injections: %d (%d unique lessons)\n", totalInjections, len(injections))
	fmt.Fprintf(a.stdout, "  Citations:  %d\n", len(citations))
	if totalInjections > 0 {
		precision := float64(len(citations)) / float64(totalInjections) * 100
		fmt.Fprintf(a.stdout, "  Precision:  %.1f%%\n", precision)
	}

	// Hits
	fmt.Fprintln(a.stdout)
	hasHits := false
	for lesson := range citations {
		if !hasHits {
			fmt.Fprintln(a.stdout, "  Hits:")
			hasHits = true
		}
		fmt.Fprintf(a.stdout, "    [%s] (score %d, cited)\n", lesson, injectionScores[lesson])
	}

	// Noise
	hasNoise := false
	for lesson, count := range injections {
		if citations[lesson] {
			continue
		}
		if !hasNoise {
			fmt.Fprintln(a.stdout, "  Noise:")
			hasNoise = true
		}
		if count > 1 {
			fmt.Fprintf(a.stdout, "    [%s] (score %d, injected %dx, never cited)\n", lesson, injectionScores[lesson], count)
		} else {
			fmt.Fprintf(a.stdout, "    [%s] (score %d, never cited)\n", lesson, injectionScores[lesson])
		}
	}

	return 0
}
```

Import: `"github.com/pbrown/claude-recall/go/internal/eventlog"`

- [ ] **Step 3: Update printHelp() in app.go**

Add `stats` to the help text alongside existing commands (find `printHelp()` function and add a line for `stats`).

- [ ] **Step 4: Build to verify compilation**

Run: `cd /home/pbrown/Code/claude-recall && go build ./go/cmd/recall/`
Expected: Clean build

- [ ] **Step 5: Add slash command**

```markdown
<!-- plugins/claude-recall/commands/stats.md -->
---
description: Show lesson injection/citation statistics and precision metrics
argument-hint: "[L###] [--weekly]"
---

# Recall Stats

Show how well lessons are being targeted — which get cited vs which are noise.

## Usage

- `/recall stats` — This session's injection/citation breakdown
- `/recall stats L059` — Lesson-specific precision, triggering queries, trigger suggestions
- `/recall stats --weekly` — Week-over-week trend report

## How It Works

The system logs every injection and citation event. Stats computes precision (citations / injections) to identify which lessons are well-targeted and which are noise.

## Commands

| Input | Action |
|-------|--------|
| `/recall stats` | `recall stats` — session summary |
| `/recall stats L059` | `recall stats L059` — lesson detail |
| `/recall stats --weekly` | `recall stats --weekly` — trend report |
```

- [ ] **Step 6: Commit**

```bash
cd /home/pbrown/Code/claude-recall
git add go/cmd/recall/app.go plugins/claude-recall/commands/stats.md
git commit -m "feat: add /recall stats session mode with injection/citation breakdown"
```

---

## Phase 2: Precision & Lesson/Trend Stats

### Task 7: Precision Computation Package

**Files:**
- Create: `go/internal/eventlog/precision.go`
- Create: `go/internal/eventlog/precision_test.go`

- [ ] **Step 1: Write failing tests for PrecisionByLesson**

```go
// go/internal/eventlog/precision_test.go
package eventlog

import (
	"testing"
	"time"
)

func TestPrecisionByLesson(t *testing.T) {
	now := time.Now()
	events := []Event{
		{Timestamp: now, Type: "injection", Session: "s1", Lesson: "L001"},
		{Timestamp: now, Type: "injection", Session: "s1", Lesson: "L001"},
		{Timestamp: now, Type: "injection", Session: "s1", Lesson: "L002"},
		{Timestamp: now, Type: "citation", Session: "s1", Lesson: "L001"},
		{Timestamp: now, Type: "dismiss", Session: "s1", Lesson: "L002"},
	}

	result := PrecisionByLesson(events)

	// L001: 1 citation / 2 injections = 50%
	if p, ok := result["L001"]; !ok {
		t.Error("missing L001")
	} else {
		if p.Injections != 2 || p.Citations != 1 || p.Dismissals != 0 {
			t.Errorf("L001: got inj=%d cit=%d dis=%d", p.Injections, p.Citations, p.Dismissals)
		}
		if got := p.Precision(); got < 0.49 || got > 0.51 {
			t.Errorf("L001 precision: expected ~0.5, got %f", got)
		}
	}

	// L002: 0 citations / (1 injection + 1 dismiss) = 0%
	if p, ok := result["L002"]; !ok {
		t.Error("missing L002")
	} else {
		if p.Injections != 1 || p.Dismissals != 1 {
			t.Errorf("L002: got inj=%d dis=%d", p.Injections, p.Dismissals)
		}
		if got := p.Precision(); got != 0.0 {
			t.Errorf("L002 precision: expected 0.0, got %f", got)
		}
	}
}

func TestPrecisionByLesson_Empty(t *testing.T) {
	result := PrecisionByLesson(nil)
	if len(result) != 0 {
		t.Errorf("expected empty map, got %d entries", len(result))
	}
}

func TestLessonPrecision_NoInjections(t *testing.T) {
	p := LessonPrecision{Citations: 3}
	if got := p.Precision(); got != 0.0 {
		t.Errorf("expected 0.0 for no injections, got %f", got)
	}
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/pbrown/Code/claude-recall && go test ./go/internal/eventlog/ -v -run TestPrecision`
Expected: FAIL — PrecisionByLesson not defined

- [ ] **Step 3: Implement PrecisionByLesson**

```go
// go/internal/eventlog/precision.go
package eventlog

// LessonPrecision holds injection/citation/dismiss counts for a single lesson.
type LessonPrecision struct {
	Injections int
	Citations  int
	Dismissals int
	Sessions   map[string]bool // unique sessions where injected
	Queries    []QueryHit      // queries that triggered injection
}

// QueryHit records a query and whether it led to a citation.
type QueryHit struct {
	Query string
	Score int
	Cited bool
}

// Precision returns citations / (injections + dismissals). Returns 0.0 if no injections.
func (lp *LessonPrecision) Precision() float64 {
	denom := lp.Injections + lp.Dismissals
	if denom == 0 {
		return 0.0
	}
	return float64(lp.Citations) / float64(denom)
}

// PrecisionByLesson aggregates events into per-lesson precision stats.
func PrecisionByLesson(events []Event) map[string]*LessonPrecision {
	result := make(map[string]*LessonPrecision)

	// First pass: count injections and dismissals
	for _, e := range events {
		id := e.Lesson
		if id == "" {
			continue
		}

		if _, ok := result[id]; !ok {
			result[id] = &LessonPrecision{Sessions: make(map[string]bool)}
		}
		p := result[id]

		switch e.Type {
		case "injection":
			p.Injections++
			if e.Session != "" {
				p.Sessions[e.Session] = true
			}
			if e.Query != "" {
				p.Queries = append(p.Queries, QueryHit{
					Query: e.Query,
					Score: e.Score,
				})
			}
		case "citation":
			p.Citations++
		case "dismiss":
			p.Dismissals++
		}
	}

	// Second pass: mark queries that led to citations
	// A query "led to citation" if the lesson was cited in the same session
	citedSessions := make(map[string]map[string]bool) // lesson -> set of sessions with citations
	for _, e := range events {
		if e.Type == "citation" && e.Lesson != "" && e.Session != "" {
			if citedSessions[e.Lesson] == nil {
				citedSessions[e.Lesson] = make(map[string]bool)
			}
			citedSessions[e.Lesson][e.Session] = true
		}
	}

	// Mark QueryHit.Cited for queries where the lesson was cited in that session
	for id, p := range result {
		if cited, ok := citedSessions[id]; ok {
			for i := range p.Queries {
				// Find the session for this query by matching injection events
				for _, e := range events {
					if e.Type == "injection" && e.Lesson == id && e.Query == p.Queries[i].Query && e.Session != "" {
						if cited[e.Session] {
							p.Queries[i].Cited = true
						}
						break
					}
				}
			}
		}
	}

	return result
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/pbrown/Code/claude-recall && go test ./go/internal/eventlog/ -v -run TestPrecision`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
cd /home/pbrown/Code/claude-recall
git add go/internal/eventlog/precision.go go/internal/eventlog/precision_test.go
git commit -m "feat(eventlog): add PrecisionByLesson() for injection/citation ratio tracking"
```

---

### Task 8: `recall stats` — Lesson Mode

**Files:**
- Modify: `go/cmd/recall/app.go`

- [ ] **Step 1: Implement runStatsLesson()**

```go
func (a *App) runStatsLesson(lessonID string) int {
	// Load lesson metadata
	store := lessons.NewStore(a.projectPath, a.systemPath)
	lesson, err := store.Get(lessonID)
	if err != nil {
		fmt.Fprintf(a.stderr, "error: lesson %s not found: %v\n", lessonID, err)
		return 1
	}

	// Load events for this lesson (30-day window)
	eventLogPath := filepath.Join(a.stateDir, "session-log.jsonl")
	elog := eventlog.New(eventLogPath)
	since := time.Now().AddDate(0, 0, -30)
	events, err := elog.ReadFiltered(eventlog.Filter{Lesson: lessonID, Since: since})
	if err != nil {
		fmt.Fprintf(a.stderr, "error reading event log: %v\n", err)
		return 1
	}

	// Compute precision
	allForLesson := eventlog.PrecisionByLesson(events)
	p := allForLesson[lessonID]

	fmt.Fprintf(a.stdout, "Lesson %s: %s\n", lessonID, lesson.Title)
	fmt.Fprintf(a.stdout, "  Rating: %s  Uses: %d  Velocity: %.1f\n\n", lesson.Rating(), lesson.Uses, lesson.Velocity)

	if p == nil {
		fmt.Fprintln(a.stdout, "  No injection/citation events in the last 30 days.")
		return 0
	}

	fmt.Fprintln(a.stdout, "  Injection History (30d):")
	fmt.Fprintf(a.stdout, "    Injected: %d times across %d sessions\n", p.Injections, len(p.Sessions))
	fmt.Fprintf(a.stdout, "    Cited:    %d times\n", p.Citations)
	if p.Dismissals > 0 {
		fmt.Fprintf(a.stdout, "    Dismissed: %d times\n", p.Dismissals)
	}
	fmt.Fprintf(a.stdout, "    Precision: %.1f%%\n", p.Precision()*100)

	// Show top triggering queries
	if len(p.Queries) > 0 {
		fmt.Fprintln(a.stdout, "\n  Top triggering queries (by BM25 score):")
		// Deduplicate and sort by score
		type queryInfo struct {
			query string
			score int
			count int
			cited bool
		}
		seen := make(map[string]*queryInfo)
		for _, q := range p.Queries {
			if q.Query == "" {
				continue
			}
			key := q.Query
			if qi, ok := seen[key]; ok {
				qi.count++
				if q.Score > qi.score {
					qi.score = q.Score
				}
				if q.Cited {
					qi.cited = true
				}
			} else {
				seen[key] = &queryInfo{query: q.Query, score: q.Score, count: 1, cited: q.Cited}
			}
		}

		// Sort by score descending, show top 5
		var sorted []*queryInfo
		for _, qi := range seen {
			sorted = append(sorted, qi)
		}
		sort.Slice(sorted, func(i, j int) bool {
			return sorted[i].score > sorted[j].score
		})
		limit := 5
		if len(sorted) < limit {
			limit = len(sorted)
		}
		for _, qi := range sorted[:limit] {
			truncated := qi.query
			if len(truncated) > 60 {
				truncated = truncated[:57] + "..."
			}
			cited := "NOT cited"
		if qi.cited {
			cited = "cited"
		}
		fmt.Fprintf(a.stdout, "    \"%s\" -> score %d, %s\n", truncated, qi.score, cited)
		}
	}

	// Show trigger info
	fmt.Fprintln(a.stdout)
	if len(lesson.Triggers) > 0 {
		fmt.Fprintf(a.stdout, "  Current triggers: %s\n", strings.Join(lesson.Triggers, ", "))
	} else {
		fmt.Fprintln(a.stdout, "  Current triggers: (none)")
	}

	return 0
}
```

- [ ] **Step 2: Build to verify compilation**

Run: `cd /home/pbrown/Code/claude-recall && go build ./go/cmd/recall/`
Expected: Clean build

- [ ] **Step 3: Commit**

```bash
cd /home/pbrown/Code/claude-recall
git add go/cmd/recall/app.go
git commit -m "feat: add /recall stats lesson mode with precision and query history"
```

---

### Task 9: `recall stats` — Weekly Trend Mode

**Files:**
- Modify: `go/cmd/recall/app.go`

- [ ] **Step 1: Implement runStatsWeekly()**

```go
func (a *App) runStatsWeekly() int {
	eventLogPath := filepath.Join(a.stateDir, "session-log.jsonl")
	elog := eventlog.New(eventLogPath)

	// Current week: last 7 days. Previous week: 7-14 days ago.
	now := time.Now()
	thisWeekStart := now.AddDate(0, 0, -7)
	lastWeekStart := now.AddDate(0, 0, -14)

	thisWeekEvents, err := elog.ReadFiltered(eventlog.Filter{Since: thisWeekStart})
	if err != nil {
		fmt.Fprintf(a.stderr, "error reading event log: %v\n", err)
		return 1
	}

	lastWeekEvents, err := elog.ReadFiltered(eventlog.Filter{Since: lastWeekStart})
	if err != nil {
		fmt.Fprintf(a.stderr, "error reading event log: %v\n", err)
		return 1
	}
	// Filter lastWeekEvents to only before thisWeekStart
	var lastWeekOnly []eventlog.Event
	for _, e := range lastWeekEvents {
		if e.Timestamp.Before(thisWeekStart) {
			lastWeekOnly = append(lastWeekOnly, e)
		}
	}

	// Count sessions, injections, citations for this week
	sessions := make(map[string]bool)
	var injCount, citCount int
	for _, e := range thisWeekEvents {
		if e.Session != "" {
			sessions[e.Session] = true
		}
		switch e.Type {
		case "injection":
			injCount++
		case "citation":
			citCount++
		}
	}

	// Same for last week
	var lastInjCount, lastCitCount int
	lastSessions := make(map[string]bool)
	for _, e := range lastWeekOnly {
		if e.Session != "" {
			lastSessions[e.Session] = true
		}
		switch e.Type {
		case "injection":
			lastInjCount++
		case "citation":
			lastCitCount++
		}
	}

	year, week := now.ISOWeek()
	fmt.Fprintf(a.stdout, "Weekly Report (%d-W%02d)\n", year, week)
	fmt.Fprintf(a.stdout, "  Sessions: %d\n", len(sessions))
	fmt.Fprintf(a.stdout, "  Injections: %d", injCount)
	if len(sessions) > 0 {
		fmt.Fprintf(a.stdout, " (avg %.1f/session)", float64(injCount)/float64(len(sessions)))
	}
	fmt.Fprintln(a.stdout)
	fmt.Fprintf(a.stdout, "  Citations: %d\n", citCount)

	if injCount > 0 {
		precision := float64(citCount) / float64(injCount) * 100
		fmt.Fprintf(a.stdout, "  Overall precision: %.1f%%\n", precision)
	}

	// Per-lesson precision for this week
	thisWeekPrecision := eventlog.PrecisionByLesson(thisWeekEvents)
	lastWeekPrecision := eventlog.PrecisionByLesson(lastWeekOnly)

	// Top performers and noise offenders
	type lessonStat struct {
		id        string
		precision float64
	}
	var performers, offenders []lessonStat
	for id, p := range thisWeekPrecision {
		if p.Injections < 2 {
			continue // skip low-confidence
		}
		prec := p.Precision()
		if prec >= 0.5 {
			performers = append(performers, lessonStat{id, prec})
		} else if prec < 0.2 {
			offenders = append(offenders, lessonStat{id, prec})
		}
	}

	sort.Slice(performers, func(i, j int) bool { return performers[i].precision > performers[j].precision })
	sort.Slice(offenders, func(i, j int) bool { return offenders[i].precision < offenders[j].precision })

	if len(performers) > 0 {
		fmt.Fprintln(a.stdout, "\n  Top performers:")
		limit := 5
		if len(performers) < limit {
			limit = len(performers)
		}
		for _, s := range performers[:limit] {
			fmt.Fprintf(a.stdout, "    [%s] (%.0f%%)\n", s.id, s.precision*100)
		}
	}

	if len(offenders) > 0 {
		fmt.Fprintln(a.stdout, "\n  Noise offenders:")
		limit := 5
		if len(offenders) < limit {
			limit = len(offenders)
		}
		for _, s := range offenders[:limit] {
			fmt.Fprintf(a.stdout, "    [%s] (%.0f%%)\n", s.id, s.precision*100)
		}
	}

	// Week-over-week comparison
	if lastInjCount > 0 {
		lastPrecision := float64(lastCitCount) / float64(lastInjCount) * 100
		thisPrecision := float64(citCount) / float64(injCount) * 100
		diff := thisPrecision - lastPrecision
		sign := "+"
		if diff < 0 {
			sign = ""
		}
		fmt.Fprintf(a.stdout, "\n  vs Last Week:\n")
		fmt.Fprintf(a.stdout, "    Precision: %.1f%% -> %.1f%% (%s%.1fpp)\n", lastPrecision, thisPrecision, sign, diff)
	}

	return 0
}
```

- [ ] **Step 2: Build to verify compilation**

Run: `cd /home/pbrown/Code/claude-recall && go build ./go/cmd/recall/`
Expected: Clean build

- [ ] **Step 3: Commit**

```bash
cd /home/pbrown/Code/claude-recall
git add go/cmd/recall/app.go
git commit -m "feat: add /recall stats --weekly trend mode with week-over-week comparison"
```

---

## Phase 3: Trigger Keywords

### Task 10: BM25 Trigger-Aware Tokenization

**Files:**
- Modify: `go/internal/scoring/bm25.go`
- Modify: `go/internal/scoring/bm25_test.go`

- [ ] **Step 1: Write failing test for trigger-weighted tokenization**

```go
// Add to go/internal/scoring/bm25_test.go

func TestBM25_TriggersBoostRelevance(t *testing.T) {
	// L001 has triggers matching the query
	// L002 has same content but no triggers
	l1 := &models.Lesson{ID: "L001", Title: "Object deletion", Content: "Multiple deletion strategies", Triggers: []string{"safe_delete", "delete_deferred"}}
	l2 := &models.Lesson{ID: "L002", Title: "Object deletion", Content: "Multiple deletion strategies"}

	scorer := NewBM25Scorer([]*models.Lesson{l1, l2})
	results := scorer.Score("safe_delete")

	if len(results) < 2 {
		t.Fatalf("expected 2 results, got %d", len(results))
	}
	// L001 should score higher because its triggers match
	if results[0].Lesson.ID != "L001" {
		t.Errorf("expected L001 first (has triggers), got %s", results[0].Lesson.ID)
	}
	if results[0].Score <= results[1].Score {
		t.Errorf("L001 (score %d) should beat L002 (score %d)", results[0].Score, results[1].Score)
	}
}

func TestBM25_NoTriggersUnchanged(t *testing.T) {
	// Without triggers, behavior should be identical to before
	l1 := &models.Lesson{ID: "L001", Title: "XML no recompile", Content: "XML files loaded at runtime"}
	l2 := &models.Lesson{ID: "L002", Title: "Icon font sync", Content: "After adding icon to codepoints"}

	scorer := NewBM25Scorer([]*models.Lesson{l1, l2})
	results := scorer.Score("XML runtime")

	if results[0].Lesson.ID != "L001" {
		t.Errorf("expected L001 first, got %s", results[0].Lesson.ID)
	}
}
```

- [ ] **Step 2: Run tests to verify first test fails**

Run: `cd /home/pbrown/Code/claude-recall && go test ./go/internal/scoring/ -v -run TestBM25_Triggers`
Expected: FAIL (triggers not used in scoring)

- [ ] **Step 3: Modify NewBM25Scorer to append trigger tokens**

In `go/internal/scoring/bm25.go`, modify the tokenization loop in `NewBM25Scorer()` (around line 64):

```go
	for _, l := range lessons {
		text := l.Title + " " + l.Content
		tokens := Tokenize(text)

		// Append trigger terms 3x for weighting
		if len(l.Triggers) > 0 {
			triggerTokens := Tokenize(strings.Join(l.Triggers, " "))
			for i := 0; i < 3; i++ {
				tokens = append(tokens, triggerTokens...)
			}
		}

		s.docTokens = append(s.docTokens, tokens)
		s.docLens = append(s.docLens, len(tokens))
		totalLen += len(tokens)
	}
```

Add `"strings"` to imports.

- [ ] **Step 4: Run all scoring tests**

Run: `cd /home/pbrown/Code/claude-recall && go test ./go/internal/scoring/ -v`
Expected: ALL PASS (including existing tests)

- [ ] **Step 5: Commit**

```bash
cd /home/pbrown/Code/claude-recall
git add go/internal/scoring/bm25.go go/internal/scoring/bm25_test.go
git commit -m "feat(scoring): append triple-weighted trigger tokens in BM25 tokenization"
```

---

## Phase 4: Feedback & Digest

### Task 11: Dismiss Command

**Files:**
- Modify: `go/cmd/recall/app.go`
- Create: `plugins/claude-recall/commands/dismiss.md`

- [ ] **Step 1: Add dismiss command to dispatch**

In `app.go` `Run()` switch, add:

```go
case "dismiss":
    if len(os.Args) < 3 {
        fmt.Fprintln(a.stderr, "usage: recall dismiss <ID>")
        return 1
    }
    return a.runDismiss(os.Args[2])
```

- [ ] **Step 2: Implement runDismiss()**

```go
func (a *App) runDismiss(lessonID string) int {
	if err := a.initPaths(); err != nil {
		fmt.Fprintf(a.stderr, "error: %v\n", err)
		return 1
	}

	// Verify lesson exists
	store := lessons.NewStore(a.projectPath, a.systemPath)
	lesson, err := store.Get(lessonID)
	if err != nil {
		fmt.Fprintf(a.stderr, "error: lesson %s not found: %v\n", lessonID, err)
		return 1
	}

	// Log dismiss event
	eventLogPath := filepath.Join(a.stateDir, "session-log.jsonl")
	elog := eventlog.New(eventLogPath)
	err = elog.Append(eventlog.Event{
		Timestamp: time.Now(),
		Type:      "dismiss",
		Lesson:    lessonID,
		Project:   a.projectDir,
	})
	if err != nil {
		fmt.Fprintf(a.stderr, "error logging dismiss: %v\n", err)
		return 1
	}

	fmt.Fprintf(a.stdout, "Dismissed [%s] %s for this session.\n", lessonID, lesson.Title)
	return 0
}
```

- [ ] **Step 3: Create slash command**

```markdown
<!-- plugins/claude-recall/commands/dismiss.md -->
---
description: Mark an injected lesson as noise for the current context
argument-hint: "<ID>"
---

# Recall Dismiss

Signal that a lesson injection was not relevant to what you're working on. This doesn't prevent future injections — it records a negative signal that helps track which lessons have high noise rates.

## Usage

`/recall dismiss L059` — mark L059 as noise for this session

## What It Does

- Logs a dismiss event to the session event log
- Increases the lesson's noise rate in `/recall stats`
- Does NOT remove, hide, or modify the lesson

Check `/recall stats L059` to see a lesson's overall precision (citations vs injections+dismissals).
```

- [ ] **Step 4: Build**

Run: `cd /home/pbrown/Code/claude-recall && go build ./go/cmd/recall/`
Expected: Clean build

- [ ] **Step 5: Commit**

```bash
cd /home/pbrown/Code/claude-recall
git add go/cmd/recall/app.go plugins/claude-recall/commands/dismiss.md
git commit -m "feat: add /recall dismiss to log noise signals for precision tracking"
```

---

### Task 12: Weekly Digest Generation

**Files:**
- Modify: `go/cmd/recall/app.go`
- Create: `plugins/claude-recall/commands/digest.md`

- [ ] **Step 1: Add digest command to dispatch**

In `app.go` `Run()` switch:

```go
case "digest":
    return a.runDigest()
```

- [ ] **Step 2: Implement runDigest()**

```go
func (a *App) runDigest() int {
	if err := a.initPaths(); err != nil {
		fmt.Fprintf(a.stderr, "error: %v\n", err)
		return 1
	}

	generate := false
	if len(os.Args) > 2 && os.Args[2] == "--generate" {
		generate = true
	}

	reportsDir := filepath.Join(a.stateDir, "reports")
	year, week := time.Now().ISOWeek()
	reportName := fmt.Sprintf("weekly-%d-W%02d.md", year, week)
	reportPath := filepath.Join(reportsDir, reportName)

	if generate {
		// Generate the report
		if err := os.MkdirAll(reportsDir, 0755); err != nil {
			fmt.Fprintf(a.stderr, "error creating reports dir: %v\n", err)
			return 1
		}

		// Capture stats --weekly output
		// Reuse runStatsWeekly logic but write to file
		eventLogPath := filepath.Join(a.stateDir, "session-log.jsonl")
		elog := eventlog.New(eventLogPath)
		events, err := elog.Read()
		if err != nil {
			fmt.Fprintf(a.stderr, "error reading event log: %v\n", err)
			return 1
		}

		if len(events) == 0 {
			fmt.Fprintln(a.stdout, "No events to generate digest from.")
			return 0
		}

		// Write report header + stats to file
		f, err := os.Create(reportPath)
		if err != nil {
			fmt.Fprintf(a.stderr, "error creating report: %v\n", err)
			return 1
		}

		fmt.Fprintf(f, "# Weekly Digest %d-W%02d\n\n", year, week)
		fmt.Fprintf(f, "Generated: %s\n\n", time.Now().Format(time.RFC3339))

		// Count totals
		sessions := make(map[string]bool)
		var injCount, citCount int
		for _, e := range events {
			if e.Timestamp.Before(time.Now().AddDate(0, 0, -7)) {
				continue
			}
			sessions[e.Session] = true
			switch e.Type {
			case "injection":
				injCount++
			case "citation":
				citCount++
			}
		}

		fmt.Fprintf(f, "## Summary\n\n")
		fmt.Fprintf(f, "- Sessions: %d\n", len(sessions))
		fmt.Fprintf(f, "- Injections: %d\n", injCount)
		fmt.Fprintf(f, "- Citations: %d\n", citCount)
		if injCount > 0 {
			fmt.Fprintf(f, "- Precision: %.1f%%\n", float64(citCount)/float64(injCount)*100)
		}

		f.Close()
		fmt.Fprintf(a.stdout, "Digest generated: %s\n", reportPath)

		// Update last-run timestamp
		os.WriteFile(filepath.Join(a.stateDir, ".digest-last-run"),
			[]byte(time.Now().Format(time.RFC3339)), 0644)

		return 0
	}

	// Display latest report
	data, err := os.ReadFile(reportPath)
	if err != nil {
		// Try to find any report
		entries, _ := os.ReadDir(reportsDir)
		if len(entries) == 0 {
			fmt.Fprintln(a.stdout, "No digest reports found. Run `recall digest --generate` to create one.")
			return 0
		}
		// Show latest
		latest := entries[len(entries)-1]
		data, err = os.ReadFile(filepath.Join(reportsDir, latest.Name()))
		if err != nil {
			fmt.Fprintf(a.stderr, "error reading report: %v\n", err)
			return 1
		}
	}

	fmt.Fprint(a.stdout, string(data))
	return 0
}
```

- [ ] **Step 3: Create slash command**

```markdown
<!-- plugins/claude-recall/commands/digest.md -->
---
description: View or generate the weekly lesson precision digest
argument-hint: "[--generate]"
---

# Recall Digest

View the latest weekly digest report showing lesson precision trends, noise offenders, and stale lessons.

## Usage

- `/recall digest` — show the latest weekly digest
- `/recall digest --generate` — generate a fresh digest for the current week

## What It Contains

- Session count and overall precision for the week
- Top performing lessons (high citation-to-injection ratio)
- Noise offenders (low precision, frequently injected)
- Stale lessons (no citations in 30+ days)
- Week-over-week comparison

Reports are saved to `~/.local/state/claude-recall/reports/` for historical review.
```

- [ ] **Step 4: Build**

Run: `cd /home/pbrown/Code/claude-recall && go build ./go/cmd/recall/`
Expected: Clean build

- [ ] **Step 5: Commit**

```bash
cd /home/pbrown/Code/claude-recall
git add go/cmd/recall/app.go plugins/claude-recall/commands/digest.md
git commit -m "feat: add /recall digest for weekly precision report generation and viewing"
```

---

## Phase 5: End-to-End Verification

### Task 13: Integration Test

**Files:**
- Create: `go/internal/eventlog/integration_test.go`

- [ ] **Step 1: Write integration test covering full flow**

```go
// go/internal/eventlog/integration_test.go
package eventlog

import (
	"path/filepath"
	"testing"
	"time"
)

func TestFullFlow_InjectCiteStatsPrecision(t *testing.T) {
	dir := t.TempDir()
	logPath := filepath.Join(dir, "session-log.jsonl")
	log := New(logPath)
	now := time.Now()

	// Simulate a session: 4 injections, 2 citations, 1 dismiss
	log.Append(Event{Timestamp: now, Type: "session_start", Session: "s1", Lessons: []string{"L001", "L002", "L003", "L004"}})
	log.Append(Event{Timestamp: now, Type: "injection", Session: "s1", Lesson: "L001", Score: 9, Query: "safe_delete usage", Hook: "prompt_submit"})
	log.Append(Event{Timestamp: now, Type: "injection", Session: "s1", Lesson: "L002", Score: 7, Query: "safe_delete usage", Hook: "prompt_submit"})
	log.Append(Event{Timestamp: now, Type: "injection", Session: "s1", Lesson: "L003", Score: 6, Query: "improve lessons", Hook: "prompt_submit"})
	log.Append(Event{Timestamp: now, Type: "injection", Session: "s1", Lesson: "L004", Score: 5, Query: "improve lessons", Hook: "prompt_submit"})
	log.Append(Event{Timestamp: now, Type: "citation", Session: "s1", Lesson: "L001"})
	log.Append(Event{Timestamp: now, Type: "citation", Session: "s1", Lesson: "L002"})
	log.Append(Event{Timestamp: now, Type: "dismiss", Session: "s1", Lesson: "L003"})

	// Read all events
	events, err := log.Read()
	if err != nil {
		t.Fatalf("Read failed: %v", err)
	}
	if len(events) != 8 {
		t.Fatalf("expected 8 events, got %d", len(events))
	}

	// Filter by session
	sessionEvents, err := log.ReadFiltered(Filter{Session: "s1"})
	if err != nil {
		t.Fatalf("ReadFiltered failed: %v", err)
	}
	if len(sessionEvents) != 8 {
		t.Errorf("expected 8 session events, got %d", len(sessionEvents))
	}

	// Compute precision
	precision := PrecisionByLesson(events)

	// L001: 1 cit / 1 inj = 100%
	if p := precision["L001"]; p == nil || p.Precision() != 1.0 {
		t.Errorf("L001 precision: expected 1.0, got %v", precision["L001"])
	}

	// L003: 0 cit / (1 inj + 1 dismiss) = 0%
	if p := precision["L003"]; p == nil || p.Precision() != 0.0 || p.Dismissals != 1 {
		t.Errorf("L003: expected 0%% with 1 dismiss, got %+v", precision["L003"])
	}

	// L004: 0 cit / 1 inj = 0%
	if p := precision["L004"]; p == nil || p.Precision() != 0.0 {
		t.Errorf("L004 precision: expected 0.0, got %v", precision["L004"])
	}
}
```

- [ ] **Step 2: Run integration test**

Run: `cd /home/pbrown/Code/claude-recall && go test ./go/internal/eventlog/ -v -run TestFullFlow`
Expected: PASS

- [ ] **Step 3: Run ALL tests to verify nothing is broken**

Run: `cd /home/pbrown/Code/claude-recall && go test ./go/... -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
cd /home/pbrown/Code/claude-recall
git add go/internal/eventlog/integration_test.go
git commit -m "test: add integration test for full inject-cite-stats-precision flow"
```

---

## Summary

| Phase | Tasks | What it delivers |
|-------|-------|-----------------|
| 1 (Foundation) | 1-6 | Event log package, hook integration, pruning, `/recall stats` session mode |
| 2 (Precision) | 7-9 | Precision computation, lesson mode, weekly trend mode |
| 3 (Triggers) | 10 | BM25 trigger-aware tokenization |
| 4 (Feedback) | 11-12 | `/recall dismiss`, `/recall digest` |
| 5 (Verify) | 13 | Integration test, full test suite verification |

Total: 13 tasks, ~65 steps. Each task produces a working commit.
