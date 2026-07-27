# Injection Precision Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce noise in lesson injection by augmenting BM25 queries with file-path context from the session and penalizing chronically uncited lessons.

**Architecture:** Two independent features that stack. Feature 1 extends the transcript parser to extract file paths, caches them per-session, and appends path tokens to BM25 queries. Feature 2 tracks inject:cite ratios per lesson and applies a score multiplier when the ratio is poor. Both features touch the Go scoring/parsing layer, the shell hooks, and the config system.

**Tech Stack:** Go 1.21 (transcript parser, scoring, event logging), Bash (hook scripts), JSON (state files)

**Spec:** `docs/superpowers/specs/2026-03-31-injection-precision-design.md`

---

## File Structure

### New Files
| File | Responsibility |
|------|---------------|
| `go/internal/sessionfiles/sessionfiles.go` | Read/write/clear session file-path cache |
| `go/internal/sessionfiles/sessionfiles_test.go` | Unit tests for session file-path cache |
| `go/internal/sessionfiles/extract.go` | Extract path segments from file paths (tokenization) |
| `go/internal/sessionfiles/extract_test.go` | Unit tests for path segment extraction |
| `go/internal/feedback/feedback.go` | Read/write/query injection-stats, compute penalties |
| `go/internal/feedback/feedback_test.go` | Unit tests for feedback system |

### Modified Files
| File | Change |
|------|--------|
| `go/internal/transcript/parser.go` | Add `ToolUses` field to Message, parse `tool_use` blocks for `file_path` |
| `go/internal/transcript/parser_test.go` | Tests for tool_use extraction |
| `go/cmd/recall-hook/stopall.go` | After citation extraction, extract file paths and write session-files cache |
| `go/cmd/recall-hook/stop_test.go` | Tests for file path extraction in stop hook |
| `go/cmd/recall/app.go` | In score-local: read session-files, apply feedback penalty after BM25 |
| `go/internal/scoring/bm25.go` | Add `ScoreWithPenalty()` that accepts penalty map |
| `go/internal/scoring/bm25_test.go` | Tests for penalty application |
| `go/internal/config/config.go` | Add feedback config fields |
| `plugins/claude-recall/hooks/scripts/smart-inject-hook.sh` | Read session-files, git fallback, augment query, increment injection stats |
| `plugins/claude-recall/hooks/scripts/inject-hook.sh` | Clear session-files on SessionStart |
| `plugins/claude-recall/hooks/scripts/hook-lib.sh` | Add `clear_session_files()` and `get_session_files_path()` helpers |

---

## Task 1: Extend Transcript Parser to Extract File Paths from tool_use Blocks

**Files:**
- Modify: `go/internal/transcript/parser.go`
- Test: `go/internal/transcript/parser_test.go`

The transcript parser currently only extracts text content from assistant messages. We need it to also extract `file_path` values from `tool_use` blocks (Read, Edit, Write, Grep tool calls).

- [ ] **Step 1: Write failing tests for tool_use file path extraction**

Add to `go/internal/transcript/parser_test.go`:

```go
func Test_Parse_ExtractsToolUseFilePaths(t *testing.T) {
	input := `{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","name":"Read","input":{"file_path":"/home/user/src/api/handler.go"}},{"type":"text","text":"Reading the file"}]}}`
	r := strings.NewReader(input)
	msgs, err := transcript.Parse(r)
	if err != nil {
		t.Fatal(err)
	}
	if len(msgs) != 1 {
		t.Fatalf("expected 1 message, got %d", len(msgs))
	}
	if len(msgs[0].FilePaths) != 1 {
		t.Fatalf("expected 1 file path, got %d", len(msgs[0].FilePaths))
	}
	if msgs[0].FilePaths[0] != "/home/user/src/api/handler.go" {
		t.Errorf("expected /home/user/src/api/handler.go, got %s", msgs[0].FilePaths[0])
	}
	if msgs[0].Content != "Reading the file" {
		t.Errorf("expected text content preserved, got %s", msgs[0].Content)
	}
}

func Test_Parse_ExtractsMultipleFilePaths(t *testing.T) {
	input := `{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","name":"Read","input":{"file_path":"/src/a.go"}},{"type":"tool_use","name":"Edit","input":{"file_path":"/src/b.go","old_string":"x","new_string":"y"}},{"type":"tool_use","name":"Bash","input":{"command":"ls"}},{"type":"text","text":"Done"}]}}`
	r := strings.NewReader(input)
	msgs, err := transcript.Parse(r)
	if err != nil {
		t.Fatal(err)
	}
	if len(msgs[0].FilePaths) != 2 {
		t.Fatalf("expected 2 file paths (Read+Edit, not Bash), got %d: %v", len(msgs[0].FilePaths), msgs[0].FilePaths)
	}
}

func Test_Parse_DeduplicatesFilePaths(t *testing.T) {
	input := `{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","name":"Read","input":{"file_path":"/src/a.go"}},{"type":"tool_use","name":"Edit","input":{"file_path":"/src/a.go","old_string":"x","new_string":"y"}}]}}`
	r := strings.NewReader(input)
	msgs, err := transcript.Parse(r)
	if err != nil {
		t.Fatal(err)
	}
	if len(msgs[0].FilePaths) != 1 {
		t.Fatalf("expected 1 deduplicated path, got %d", len(msgs[0].FilePaths))
	}
}

func Test_Parse_SkipsToolUseWithoutFilePath(t *testing.T) {
	input := `{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","name":"Bash","input":{"command":"git status"}}]}}`
	r := strings.NewReader(input)
	msgs, err := transcript.Parse(r)
	if err != nil {
		t.Fatal(err)
	}
	if len(msgs[0].FilePaths) != 0 {
		t.Fatalf("expected 0 file paths for Bash tool, got %d", len(msgs[0].FilePaths))
	}
}

func Test_Parse_GrepPathExtraction(t *testing.T) {
	input := `{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","name":"Grep","input":{"pattern":"TODO","path":"/src/api/"}}]}}`
	r := strings.NewReader(input)
	msgs, err := transcript.Parse(r)
	if err != nil {
		t.Fatal(err)
	}
	if len(msgs[0].FilePaths) != 1 {
		t.Fatalf("expected 1 path from Grep, got %d", len(msgs[0].FilePaths))
	}
	if msgs[0].FilePaths[0] != "/src/api/" {
		t.Errorf("expected /src/api/, got %s", msgs[0].FilePaths[0])
	}
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/pbrown/Code/claude-recall/go && go test ./internal/transcript/ -run "Test_Parse_ExtractsToolUse|Test_Parse_DeduplicatesFilePaths|Test_Parse_SkipsToolUse|Test_Parse_GrepPathExtraction" -v`
Expected: Compilation error — `FilePaths` field does not exist on `Message`

- [ ] **Step 3: Implement tool_use file path extraction**

Modify `go/internal/transcript/parser.go`:

Add `FilePaths` to the Message struct:
```go
type Message struct {
	Type      string
	Content   string
	FilePaths []string // File paths from tool_use blocks (Read, Edit, Write, Grep)
}
```

Add `input` parsing to `contentBlock`:
```go
type contentBlock struct {
	Type     string          `json:"type"`
	Text     string          `json:"text"`
	Thinking string          `json:"thinking"`
	Name     string          `json:"name"`
	Input    json.RawMessage `json:"input"`
}
```

Add a helper struct and extraction function:
```go
type toolInput struct {
	FilePath string `json:"file_path"`
	Path     string `json:"path"` // Grep uses "path" instead of "file_path"
}

func extractFilePath(block contentBlock) string {
	if block.Type != "tool_use" || len(block.Input) == 0 {
		return ""
	}
	var ti toolInput
	if err := json.Unmarshal(block.Input, &ti); err != nil {
		return ""
	}
	if ti.FilePath != "" {
		return ti.FilePath
	}
	return ti.Path
}
```

Update `parseLine()` to collect file paths:
```go
func parseLine(line []byte) (Message, bool) {
	var tl transcriptLine
	if err := json.Unmarshal(line, &tl); err != nil {
		return Message{}, false
	}
	msg := Message{Type: tl.Type}
	if tl.Type != "assistant" {
		return msg, true
	}
	seen := make(map[string]bool)
	for _, block := range tl.Message.Content {
		switch block.Type {
		case "text":
			msg.Content += block.Text
		case "tool_use":
			if fp := extractFilePath(block); fp != "" && !seen[fp] {
				msg.FilePaths = append(msg.FilePaths, fp)
				seen[fp] = true
			}
		}
	}
	return msg, true
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/pbrown/Code/claude-recall/go && go test ./internal/transcript/ -v`
Expected: All tests pass (new tests + existing tests unchanged)

- [ ] **Step 5: Commit**

```bash
git add go/internal/transcript/parser.go go/internal/transcript/parser_test.go
git commit -m "feat(transcript): extract file paths from tool_use blocks"
```

---

## Task 2: Session File-Path Cache (Read/Write/Clear)

**Files:**
- Create: `go/internal/sessionfiles/sessionfiles.go`
- Create: `go/internal/sessionfiles/sessionfiles_test.go`

A small module to manage the per-session file-path cache JSON.

- [ ] **Step 1: Write failing tests**

Create `go/internal/sessionfiles/sessionfiles_test.go`:

```go
package sessionfiles

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestRead_MissingFile(t *testing.T) {
	paths, err := Read("/nonexistent/session-files-abc.json")
	if err != nil {
		t.Fatal(err)
	}
	if len(paths) != 0 {
		t.Errorf("expected empty paths for missing file, got %d", len(paths))
	}
}

func TestWriteAndRead(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "session-files-test.json")

	err := Write(path, []string{"/src/a.go", "/src/b.go"})
	if err != nil {
		t.Fatal(err)
	}

	paths, err := Read(path)
	if err != nil {
		t.Fatal(err)
	}
	if len(paths) != 2 {
		t.Fatalf("expected 2 paths, got %d", len(paths))
	}
	if paths[0] != "/src/a.go" || paths[1] != "/src/b.go" {
		t.Errorf("unexpected paths: %v", paths)
	}
}

func TestMerge_CombinesAndDeduplicates(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "session-files-test.json")

	err := Write(path, []string{"/src/a.go", "/src/b.go"})
	if err != nil {
		t.Fatal(err)
	}

	err = Merge(path, []string{"/src/b.go", "/src/c.go"})
	if err != nil {
		t.Fatal(err)
	}

	paths, err := Read(path)
	if err != nil {
		t.Fatal(err)
	}
	if len(paths) != 3 {
		t.Fatalf("expected 3 deduplicated paths, got %d: %v", len(paths), paths)
	}
}

func TestClear(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "session-files-test.json")

	err := Write(path, []string{"/src/a.go"})
	if err != nil {
		t.Fatal(err)
	}

	Clear(path)

	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Error("expected file to be deleted after Clear")
	}
}

func TestFilePath_ForSession(t *testing.T) {
	result := FilePath("/state/dir", "session-123")
	expected := "/state/dir/session-files-session-123.json"
	if result != expected {
		t.Errorf("expected %s, got %s", expected, result)
	}
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/pbrown/Code/claude-recall/go && go test ./internal/sessionfiles/ -v`
Expected: Compilation error — package does not exist

- [ ] **Step 3: Implement session files module**

Create `go/internal/sessionfiles/sessionfiles.go`:

```go
package sessionfiles

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
)

type sessionFileData struct {
	Paths   []string `json:"paths"`
	Updated string   `json:"updated"`
}

// FilePath returns the session-files cache path for a given session ID.
func FilePath(stateDir, sessionID string) string {
	return filepath.Join(stateDir, fmt.Sprintf("session-files-%s.json", sessionID))
}

// Read returns the cached file paths for a session. Returns empty slice if file missing.
func Read(path string) ([]string, error) {
	data, err := os.ReadFile(path)
	if os.IsNotExist(err) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	var sf sessionFileData
	if err := json.Unmarshal(data, &sf); err != nil {
		return nil, err
	}
	return sf.Paths, nil
}

// Write overwrites the session-files cache with the given paths.
func Write(path string, paths []string) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	sf := sessionFileData{
		Paths:   paths,
		Updated: timeNow(),
	}
	data, err := json.Marshal(sf)
	if err != nil {
		return err
	}
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, data, 0o644); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

// Merge reads existing paths, adds new ones (deduplicating), and writes back.
func Merge(path string, newPaths []string) error {
	existing, err := Read(path)
	if err != nil {
		return err
	}
	seen := make(map[string]bool, len(existing))
	for _, p := range existing {
		seen[p] = true
	}
	for _, p := range newPaths {
		if !seen[p] {
			existing = append(existing, p)
			seen[p] = true
		}
	}
	return Write(path, existing)
}

// Clear removes the session-files cache.
func Clear(path string) {
	os.Remove(path)
}

func timeNow() string {
	// Separate function for testability if needed later
	return time.Now().UTC().Format(time.RFC3339)
}
```

Add the missing `time` import at the top.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/pbrown/Code/claude-recall/go && go test ./internal/sessionfiles/ -v`
Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add go/internal/sessionfiles/
git commit -m "feat(sessionfiles): add session file-path cache module"
```

---

## Task 3: Path Segment Extraction

**Files:**
- Create: `go/internal/sessionfiles/extract.go`
- Create: `go/internal/sessionfiles/extract_test.go`

Extracts meaningful tokens from file paths for BM25 query augmentation.

- [ ] **Step 1: Write failing tests**

Create `go/internal/sessionfiles/extract_test.go`:

```go
package sessionfiles

import (
	"testing"
)

func TestExtractSegments_Basic(t *testing.T) {
	paths := []string{"/home/user/project/src/api/handler.go"}
	segments := ExtractSegments(paths, "/home/user/project")
	expected := map[string]bool{"src": true, "api": true, "handler": true}
	for _, s := range segments {
		if !expected[s] {
			t.Errorf("unexpected segment %q", s)
		}
	}
	if len(segments) != len(expected) {
		t.Errorf("expected %d segments, got %d: %v", len(expected), len(segments), segments)
	}
}

func TestExtractSegments_DropsExtensions(t *testing.T) {
	paths := []string{"/proj/src/main.py", "/proj/src/test.go", "/proj/docs/readme.md"}
	segments := ExtractSegments(paths, "/proj")
	for _, s := range segments {
		if s == "py" || s == "go" || s == "md" {
			t.Errorf("should not include extension: %s", s)
		}
	}
}

func TestExtractSegments_DropsCommonPrefixes(t *testing.T) {
	paths := []string{"/home/user/project/src/core.go"}
	segments := ExtractSegments(paths, "/home/user/project")
	for _, s := range segments {
		if s == "home" || s == "user" || s == "project" {
			t.Errorf("should not include common prefix segment: %s", s)
		}
	}
}

func TestExtractSegments_Deduplicates(t *testing.T) {
	paths := []string{"/proj/src/a.go", "/proj/src/b.go", "/proj/src/c.go"}
	segments := ExtractSegments(paths, "/proj")
	srcCount := 0
	for _, s := range segments {
		if s == "src" {
			srcCount++
		}
	}
	if srcCount != 1 {
		t.Errorf("expected 'src' once, got %d times", srcCount)
	}
}

func TestExtractSegments_CapsAt20(t *testing.T) {
	paths := make([]string, 30)
	for i := range paths {
		paths[i] = fmt.Sprintf("/proj/dir%d/file%d.go", i, i)
	}
	segments := ExtractSegments(paths, "/proj")
	if len(segments) > 20 {
		t.Errorf("expected max 20 segments, got %d", len(segments))
	}
}

func TestExtractSegments_EmptyPaths(t *testing.T) {
	segments := ExtractSegments(nil, "/proj")
	if len(segments) != 0 {
		t.Errorf("expected empty segments, got %v", segments)
	}
}

func TestExtractSegments_DropsShortSegments(t *testing.T) {
	paths := []string{"/proj/a/b/src/handler.go"}
	segments := ExtractSegments(paths, "/proj")
	for _, s := range segments {
		if len(s) < 2 {
			t.Errorf("should not include short segment: %q", s)
		}
	}
}
```

Add `"fmt"` import for the caps test.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/pbrown/Code/claude-recall/go && go test ./internal/sessionfiles/ -run "TestExtractSegments" -v`
Expected: Compilation error — `ExtractSegments` not defined

- [ ] **Step 3: Implement path segment extraction**

Create `go/internal/sessionfiles/extract.go`:

```go
package sessionfiles

import (
	"path/filepath"
	"strings"
)

const maxSegments = 20

// commonPrefixes are path segments to always drop.
var commonPrefixes = map[string]bool{
	".": true, "home": true, "users": true, "tmp": true, "var": true,
}

// knownExtensions are file extensions to strip (without dot).
var knownExtensions = map[string]bool{
	"go": true, "py": true, "js": true, "ts": true, "tsx": true, "jsx": true,
	"c": true, "h": true, "cpp": true, "rs": true, "rb": true, "java": true,
	"sh": true, "bash": true, "zsh": true, "md": true, "txt": true, "json": true,
	"yaml": true, "yml": true, "toml": true, "xml": true, "html": true, "css": true,
	"sql": true, "proto": true, "lua": true, "zig": true, "swift": true,
}

// ExtractSegments extracts meaningful path segments from file paths for BM25 query augmentation.
// It strips the project root prefix, file extensions, common directory names, and short segments.
// Returns at most maxSegments unique tokens.
func ExtractSegments(paths []string, projectRoot string) []string {
	if len(paths) == 0 {
		return nil
	}

	// Normalize project root for prefix stripping
	root := strings.TrimSuffix(projectRoot, "/") + "/"

	seen := make(map[string]bool)
	var segments []string

	for _, p := range paths {
		// Strip project root prefix
		rel := p
		if strings.HasPrefix(p, root) {
			rel = strings.TrimPrefix(p, root)
		}

		parts := strings.Split(rel, "/")
		for _, part := range parts {
			if part == "" {
				continue
			}

			// Strip file extension from last segment
			ext := filepath.Ext(part)
			if ext != "" && knownExtensions[ext[1:]] {
				part = strings.TrimSuffix(part, ext)
			}

			// Skip short, common, or already-seen segments
			if len(part) < 2 || commonPrefixes[part] || seen[part] {
				continue
			}

			seen[part] = true
			segments = append(segments, part)

			if len(segments) >= maxSegments {
				return segments
			}
		}
	}

	return segments
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/pbrown/Code/claude-recall/go && go test ./internal/sessionfiles/ -v`
Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add go/internal/sessionfiles/extract.go go/internal/sessionfiles/extract_test.go
git commit -m "feat(sessionfiles): add path segment extraction for BM25 augmentation"
```

---

## Task 4: Stop Hook Writes Session File-Path Cache

**Files:**
- Modify: `go/cmd/recall-hook/stopall.go`
- Test: `go/cmd/recall-hook/stop_test.go`

After extracting citations, the stop hook should also collect file paths from the parsed transcript messages and merge them into the session-files cache.

- [ ] **Step 1: Write failing test**

Add to `go/cmd/recall-hook/stop_test.go`:

```go
func Test_StopHook_WritesSessionFiles(t *testing.T) {
	// Create a transcript with tool_use blocks containing file paths
	dir := t.TempDir()
	transcriptPath := filepath.Join(dir, "transcript.jsonl")
	transcript := `{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","name":"Read","input":{"file_path":"/proj/src/api/handler.go"}},{"type":"text","text":"Reading file [L001]"}]}}
{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","name":"Edit","input":{"file_path":"/proj/src/api/router.go","old_string":"x","new_string":"y"}},{"type":"text","text":"Edited"}]}}`
	os.WriteFile(transcriptPath, []byte(transcript), 0644)

	stateDir := filepath.Join(dir, "state")
	os.MkdirAll(stateDir, 0755)

	// Set up minimal environment and run stop-all
	// (Use the same test pattern as existing Test_StopHook_ExtractsCitations)
	sessionID := "test-session-files"
	sfPath := sessionfiles.FilePath(stateDir, sessionID)

	// After running the stop hook, session-files should contain the file paths
	paths, err := sessionfiles.Read(sfPath)
	if err != nil {
		t.Fatal(err)
	}
	if len(paths) < 2 {
		t.Errorf("expected at least 2 file paths in session-files, got %d: %v", len(paths), paths)
	}
}
```

Note: The exact test structure will depend on how existing stop_test.go sets up the hook runner. Follow the pattern from `Test_StopHook_ExtractsCitations` — set up transcript, config, and state dirs, invoke `runStopAll()`, then check session-files output.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/pbrown/Code/claude-recall/go && go test ./cmd/recall-hook/ -run "Test_StopHook_WritesSessionFiles" -v`
Expected: FAIL — session-files not written

- [ ] **Step 3: Implement file path collection in stop hook**

Modify `go/cmd/recall-hook/stopall.go`. After the existing citation extraction (around line 121), add file path collection:

```go
// Collect file paths from transcript for session file-path cache
var allFilePaths []string
for _, msg := range messages {
	allFilePaths = append(allFilePaths, msg.FilePaths...)
}
if len(allFilePaths) > 0 {
	sfPath := sessionfiles.FilePath(stateDir, input.SessionID)
	if err := sessionfiles.Merge(sfPath, allFilePaths); err != nil {
		output.Errors = append(output.Errors, fmt.Sprintf("session-files merge: %v", err))
	}
}
```

Add import: `"github.com/pbrown/claude-recall/go/internal/sessionfiles"`

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/pbrown/Code/claude-recall/go && go test ./cmd/recall-hook/ -v`
Expected: All tests pass (new + existing)

- [ ] **Step 5: Commit**

```bash
git add go/cmd/recall-hook/stopall.go go/cmd/recall-hook/stop_test.go
git commit -m "feat(stop-hook): write session file-path cache from transcript tool_use blocks"
```

---

## Task 5: Smart-Inject Hook Reads Session Files + Git Fallback + Query Augmentation

**Files:**
- Modify: `plugins/claude-recall/hooks/scripts/smart-inject-hook.sh`
- Modify: `plugins/claude-recall/hooks/scripts/hook-lib.sh`

The smart-inject hook needs to read the session-files cache, fall back to git if empty, extract path segments, and append them to the BM25 query.

- [ ] **Step 1: Add helper functions to hook-lib.sh**

Add to `plugins/claude-recall/hooks/scripts/hook-lib.sh` near the existing dedup functions (around line 346):

```bash
# Session file-path cache helpers
get_session_files_path() {
    local session_id="${_HOOK_SESSION_ID:-}"
    if [[ -z "$session_id" ]]; then
        return
    fi
    echo "${CLAUDE_RECALL_STATE}/session-files-${session_id}.json"
}

clear_session_files() {
    local sf_path
    sf_path=$(get_session_files_path)
    if [[ -n "$sf_path" ]]; then
        rm -f "$sf_path"
    fi
}

# Read file paths from session-files cache, one per line
read_session_file_paths() {
    local sf_path
    sf_path=$(get_session_files_path)
    if [[ -n "$sf_path" && -f "$sf_path" ]]; then
        jq -r '.paths[]' "$sf_path" 2>/dev/null
    fi
}
```

- [ ] **Step 2: Add git fallback and query augmentation to smart-inject-hook.sh**

Add a new function to `plugins/claude-recall/hooks/scripts/smart-inject-hook.sh` before the `main()` function:

```bash
# Get file-path context tokens to augment BM25 query.
# Reads session-files cache first, falls back to git diff/status.
get_file_context_tokens() {
    local project_root="$1"
    local file_paths=""

    # Try session-files cache first
    file_paths=$(read_session_file_paths 2>/dev/null)

    # Fallback: git diff + status if no session files yet
    if [[ -z "$file_paths" && -d "$project_root/.git" ]]; then
        file_paths=$(cd "$project_root" && {
            git diff --name-only 2>/dev/null
            git status --porcelain 2>/dev/null | awk '{print $2}'
        } | sort -u)
    fi

    if [[ -z "$file_paths" ]]; then
        return
    fi

    # Extract path segments: strip extensions, split on /, deduplicate
    # Drop segments shorter than 2 chars
    echo "$file_paths" | while IFS= read -r path; do
        # Strip project root prefix
        path="${path#$project_root/}"
        # Split on / and process each segment
        echo "$path" | tr '/' '\n'
    done | sed 's/\.[a-zA-Z]*$//' | awk 'length >= 2' | sort -u | head -20 | tr '\n' ' '
}
```

Then modify the `main()` function where the query is assembled (around line 130, before calling `score_and_format_lessons`):

```bash
# Augment query with file-path context tokens
local file_tokens
file_tokens=$(get_file_context_tokens "$project_root")
local augmented_prompt="$prompt"
if [[ -n "$file_tokens" ]]; then
    augmented_prompt="$prompt $file_tokens"
    log_debug "$project_root" "query_augmented" "file_tokens=$file_tokens"
fi
```

Update the scoring call to use `$augmented_prompt` instead of `$prompt`:

```bash
scored_lessons=$(score_and_format_lessons "$augmented_prompt" "$cwd")
```

- [ ] **Step 3: Test manually**

```bash
# Create a test session-files cache
mkdir -p ~/.local/state/claude-recall
echo '{"paths":["/home/user/proj/src/api/handler.go","/home/user/proj/src/system/usb.c"],"updated":"2026-03-31T10:00:00Z"}' > ~/.local/state/claude-recall/session-files-test-manual.json

# Verify the function works (source the hook lib)
cd /home/pbrown/Code/claude-recall
source plugins/claude-recall/hooks/scripts/hook-lib.sh
_HOOK_SESSION_ID="test-manual"
read_session_file_paths

# Clean up
rm ~/.local/state/claude-recall/session-files-test-manual.json
```

- [ ] **Step 4: Commit**

```bash
git add plugins/claude-recall/hooks/scripts/smart-inject-hook.sh plugins/claude-recall/hooks/scripts/hook-lib.sh
git commit -m "feat(smart-inject): augment BM25 query with file-path context tokens"
```

---

## Task 6: Clear Session Files on SessionStart

**Files:**
- Modify: `plugins/claude-recall/hooks/scripts/inject-hook.sh`

- [ ] **Step 1: Add clear_session_files call to inject-hook.sh**

In `plugins/claude-recall/hooks/scripts/inject-hook.sh`, right after the `clear_dedup` call on line 139, add:

```bash
clear_session_files
```

So lines 138-140 become:
```bash
_HOOK_SESSION_ID="$claude_session_id"
clear_dedup
clear_session_files
```

- [ ] **Step 2: Verify inject-hook still runs correctly**

```bash
# Quick smoke test - ensure the hook doesn't error
echo '{"cwd":"/tmp","session_id":"test-123"}' | bash plugins/claude-recall/hooks/scripts/inject-hook.sh
```

Expected: JSON output with `hookSpecificOutput` (or graceful exit if Go binary not available)

- [ ] **Step 3: Commit**

```bash
git add plugins/claude-recall/hooks/scripts/inject-hook.sh
git commit -m "feat(inject-hook): clear session file-path cache on SessionStart"
```

---

## Task 7: Feedback Module (Injection Stats Read/Write/Penalty)

**Files:**
- Create: `go/internal/feedback/feedback.go`
- Create: `go/internal/feedback/feedback_test.go`

Manages injection-stats.json files and computes penalties.

- [ ] **Step 1: Write failing tests**

Create `go/internal/feedback/feedback_test.go`:

```go
package feedback

import (
	"path/filepath"
	"testing"
)

func TestRead_MissingFile(t *testing.T) {
	stats, err := ReadStats("/nonexistent/injection-stats.json")
	if err != nil {
		t.Fatal(err)
	}
	if len(stats) != 0 {
		t.Errorf("expected empty stats for missing file, got %d", len(stats))
	}
}

func TestIncrementInjection(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "injection-stats.json")

	err := IncrementInjection(path, "L001")
	if err != nil {
		t.Fatal(err)
	}
	err = IncrementInjection(path, "L001")
	if err != nil {
		t.Fatal(err)
	}

	stats, err := ReadStats(path)
	if err != nil {
		t.Fatal(err)
	}
	if stats["L001"].Injections != 2 {
		t.Errorf("expected 2 injections, got %d", stats["L001"].Injections)
	}
	if stats["L001"].Citations != 0 {
		t.Errorf("expected 0 citations, got %d", stats["L001"].Citations)
	}
}

func TestIncrementCitation(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "injection-stats.json")

	IncrementInjection(path, "L001")
	IncrementInjection(path, "L001")
	err := IncrementCitation(path, "L001")
	if err != nil {
		t.Fatal(err)
	}

	stats, _ := ReadStats(path)
	if stats["L001"].Citations != 1 {
		t.Errorf("expected 1 citation, got %d", stats["L001"].Citations)
	}
}

func TestShouldPenalize_BelowThreshold(t *testing.T) {
	stats := map[string]LessonStats{
		"L001": {Injections: 3, Citations: 0},
	}
	if ShouldPenalize(stats, "L001", 5, 0.2) {
		t.Error("should not penalize with only 3 injections (threshold 5)")
	}
}

func TestShouldPenalize_AboveThresholdNoCitations(t *testing.T) {
	stats := map[string]LessonStats{
		"L001": {Injections: 7, Citations: 0},
	}
	if !ShouldPenalize(stats, "L001", 5, 0.2) {
		t.Error("should penalize: 7 injections, 0 citations")
	}
}

func TestShouldPenalize_AboveThresholdGoodRatio(t *testing.T) {
	stats := map[string]LessonStats{
		"L001": {Injections: 10, Citations: 5},
	}
	if ShouldPenalize(stats, "L001", 5, 0.2) {
		t.Error("should not penalize: ratio 0.5 > 0.2")
	}
}

func TestShouldPenalize_ExactThreshold(t *testing.T) {
	stats := map[string]LessonStats{
		"L001": {Injections: 5, Citations: 1},
	}
	// 1/5 = 0.2, exactly at threshold => no penalty
	if ShouldPenalize(stats, "L001", 5, 0.2) {
		t.Error("should not penalize at exact threshold (0.2 is not < 0.2)")
	}
}

func TestShouldPenalize_UnknownLesson(t *testing.T) {
	stats := map[string]LessonStats{}
	if ShouldPenalize(stats, "L999", 5, 0.2) {
		t.Error("should not penalize unknown lesson")
	}
}

func TestResetLesson(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "injection-stats.json")

	IncrementInjection(path, "L001")
	IncrementInjection(path, "L001")
	IncrementInjection(path, "L001")

	err := ResetLesson(path, "L001")
	if err != nil {
		t.Fatal(err)
	}

	stats, _ := ReadStats(path)
	if _, exists := stats["L001"]; exists {
		t.Error("expected L001 to be removed after reset")
	}
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/pbrown/Code/claude-recall/go && go test ./internal/feedback/ -v`
Expected: Compilation error — package does not exist

- [ ] **Step 3: Implement feedback module**

Create `go/internal/feedback/feedback.go`:

```go
package feedback

import (
	"encoding/json"
	"os"
	"path/filepath"
)

// LessonStats tracks injection and citation counts for a lesson.
type LessonStats struct {
	Injections int `json:"injections"`
	Citations  int `json:"citations"`
}

// ReadStats reads injection stats from a JSON file. Returns empty map if file missing.
func ReadStats(path string) (map[string]LessonStats, error) {
	data, err := os.ReadFile(path)
	if os.IsNotExist(err) {
		return make(map[string]LessonStats), nil
	}
	if err != nil {
		return nil, err
	}
	var stats map[string]LessonStats
	if err := json.Unmarshal(data, &stats); err != nil {
		return make(map[string]LessonStats), nil
	}
	return stats, nil
}

// writeStats writes injection stats atomically.
func writeStats(path string, stats map[string]LessonStats) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	data, err := json.Marshal(stats)
	if err != nil {
		return err
	}
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, data, 0o644); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

// IncrementInjection increments the injection count for a lesson.
func IncrementInjection(path, lessonID string) error {
	stats, err := ReadStats(path)
	if err != nil {
		return err
	}
	s := stats[lessonID]
	s.Injections++
	stats[lessonID] = s
	return writeStats(path, stats)
}

// IncrementCitation increments the citation count for a lesson.
func IncrementCitation(path, lessonID string) error {
	stats, err := ReadStats(path)
	if err != nil {
		return err
	}
	s := stats[lessonID]
	s.Citations++
	stats[lessonID] = s
	return writeStats(path, stats)
}

// ShouldPenalize returns true if a lesson should receive a score penalty.
// Penalty applies when injections >= minInjections and cite ratio < maxCiteRatio.
func ShouldPenalize(stats map[string]LessonStats, lessonID string, minInjections int, maxCiteRatio float64) bool {
	s, ok := stats[lessonID]
	if !ok || s.Injections < minInjections {
		return false
	}
	ratio := float64(s.Citations) / float64(s.Injections)
	return ratio < maxCiteRatio
}

// ResetLesson removes a lesson's injection stats (used by dismiss and edit).
func ResetLesson(path, lessonID string) error {
	stats, err := ReadStats(path)
	if err != nil {
		return err
	}
	delete(stats, lessonID)
	return writeStats(path, stats)
}

// StatsFilePath returns the injection-stats.json path for a given scope directory.
func StatsFilePath(dir string) string {
	return filepath.Join(dir, "injection-stats.json")
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/pbrown/Code/claude-recall/go && go test ./internal/feedback/ -v`
Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add go/internal/feedback/
git commit -m "feat(feedback): add injection-stats tracking and penalty calculation"
```

---

## Task 8: Add Feedback Config Fields

**Files:**
- Modify: `go/internal/config/config.go`

- [ ] **Step 1: Add feedback fields to Config struct**

In `go/internal/config/config.go`, add to the Config struct:

```go
FeedbackMinInjections int     `json:"feedbackMinInjections"` // Min injections before penalty (default: 5)
FeedbackMaxCiteRatio  float64 `json:"feedbackMaxCiteRatio"`  // Max cite ratio before penalty (default: 0.2)
FeedbackPenalty       float64 `json:"feedbackPenalty"`        // Score multiplier when penalized (default: 0.5)
```

- [ ] **Step 2: Add defaults in applyDefaults()**

In `applyDefaults()`, add:

```go
if c.FeedbackMinInjections == 0 {
	c.FeedbackMinInjections = 5
}
if c.FeedbackMaxCiteRatio == 0 {
	c.FeedbackMaxCiteRatio = 0.2
}
if c.FeedbackPenalty == 0 {
	c.FeedbackPenalty = 0.5
}
```

- [ ] **Step 3: Run existing config tests**

Run: `cd /home/pbrown/Code/claude-recall/go && go test ./internal/config/ -v`
Expected: All existing tests pass (new fields have defaults, no breaking changes)

- [ ] **Step 4: Commit**

```bash
git add go/internal/config/config.go
git commit -m "feat(config): add feedback penalty configuration fields"
```

---

## Task 9: Apply Feedback Penalty in Score-Local

**Files:**
- Modify: `go/cmd/recall/app.go`
- Modify: `go/internal/scoring/bm25.go`
- Test: `go/internal/scoring/bm25_test.go`

Score-local needs to: (1) read injection-stats, (2) apply penalty multiplier after BM25 scoring, (3) increment injection count for lessons that pass scoring.

- [ ] **Step 1: Write failing test for penalty application in BM25**

Add to `go/internal/scoring/bm25_test.go`:

```go
func TestApplyPenalties(t *testing.T) {
	results := []ScoredLesson{
		{Lesson: &models.Lesson{ID: "L001"}, Score: 8},
		{Lesson: &models.Lesson{ID: "L002"}, Score: 6},
		{Lesson: &models.Lesson{ID: "L003"}, Score: 4},
	}
	penalties := map[string]float64{
		"L002": 0.5,
	}
	penalized := ApplyPenalties(results, penalties)

	if penalized[0].Score != 8 {
		t.Errorf("L001 should be unchanged, got %d", penalized[0].Score)
	}
	if penalized[1].Score != 3 {
		t.Errorf("L002 should be 6*0.5=3, got %d", penalized[1].Score)
	}
	if penalized[2].Score != 4 {
		t.Errorf("L003 should be unchanged, got %d", penalized[2].Score)
	}
}

func TestApplyPenalties_ResortsAfterPenalty(t *testing.T) {
	results := []ScoredLesson{
		{Lesson: &models.Lesson{ID: "L001"}, Score: 8},
		{Lesson: &models.Lesson{ID: "L002"}, Score: 7},
		{Lesson: &models.Lesson{ID: "L003"}, Score: 6},
	}
	penalties := map[string]float64{
		"L001": 0.5, // 8*0.5=4, should drop below L003
	}
	penalized := ApplyPenalties(results, penalties)

	if penalized[0].Lesson.ID != "L002" {
		t.Errorf("L002 should be first after L001 penalized, got %s", penalized[0].Lesson.ID)
	}
	if penalized[2].Lesson.ID != "L001" {
		t.Errorf("L001 should be last after penalty, got %s", penalized[2].Lesson.ID)
	}
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/pbrown/Code/claude-recall/go && go test ./internal/scoring/ -run "TestApplyPenalties" -v`
Expected: Compilation error — `ApplyPenalties` not defined

- [ ] **Step 3: Implement ApplyPenalties in bm25.go**

Add to `go/internal/scoring/bm25.go`:

```go
// ApplyPenalties applies score multipliers to specific lessons and re-sorts.
func ApplyPenalties(results []ScoredLesson, penalties map[string]float64) []ScoredLesson {
	for i, r := range results {
		if mult, ok := penalties[r.Lesson.ID]; ok {
			results[i].Score = int(float64(r.Score) * mult)
		}
	}
	sort.SliceStable(results, func(i, j int) bool {
		if results[i].Score != results[j].Score {
			return results[i].Score > results[j].Score
		}
		return results[i].Lesson.Uses > results[j].Lesson.Uses
	})
	return results
}
```

Ensure `"sort"` is imported (likely already is from Score()).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/pbrown/Code/claude-recall/go && go test ./internal/scoring/ -v`
Expected: All tests pass

- [ ] **Step 5: Integrate penalty + injection tracking in score-local command**

Modify `go/cmd/recall/app.go` in `runScoreLocal()`. After BM25 scoring (around line 1608) and before output formatting:

```go
// Load injection stats and compute penalties
projectStatsPath := feedback.StatsFilePath(filepath.Join(a.projectDir, ".claude-recall"))
systemStatsPath := feedback.StatsFilePath(a.stateDir)

projectStats, _ := feedback.ReadStats(projectStatsPath)
systemStats, _ := feedback.ReadStats(systemStatsPath)

penalties := make(map[string]float64)
for _, r := range results {
	id := r.Lesson.ID
	var penalized bool
	if strings.HasPrefix(id, "L") {
		penalized = feedback.ShouldPenalize(projectStats, id, cfg.FeedbackMinInjections, cfg.FeedbackMaxCiteRatio)
	} else {
		penalized = feedback.ShouldPenalize(systemStats, id, cfg.FeedbackMinInjections, cfg.FeedbackMaxCiteRatio)
	}
	if penalized {
		penalties[id] = cfg.FeedbackPenalty
		// Log penalty at debug level 2
		debugLog(2, "feedback_penalty lesson=%s injections=%d citations=%d penalty=%.1f",
			id, getInjections(projectStats, systemStats, id), getCitations(projectStats, systemStats, id), cfg.FeedbackPenalty)
	}
}

if len(penalties) > 0 {
	results = scoring.ApplyPenalties(results, penalties)
}
```

Add imports: `"github.com/pbrown/claude-recall/go/internal/feedback"` and `"strings"`.

After formatting output (the existing loop that emits injection events), also increment injection stats:

```go
// Increment injection counts for lessons that will be shown
for _, sl := range outputResults {
	id := sl.Lesson.ID
	if strings.HasPrefix(id, "L") {
		feedback.IncrementInjection(projectStatsPath, id)
	} else {
		feedback.IncrementInjection(systemStatsPath, id)
	}
}
```

- [ ] **Step 6: Run all Go tests**

Run: `cd /home/pbrown/Code/claude-recall/go && go test ./... -v`
Expected: All tests pass

- [ ] **Step 7: Commit**

```bash
git add go/internal/scoring/bm25.go go/internal/scoring/bm25_test.go go/cmd/recall/app.go
git commit -m "feat(score-local): apply feedback penalty and track injection counts"
```

---

## Task 10: Increment Citation Counts in Stop Hook

**Files:**
- Modify: `go/cmd/recall-hook/stopall.go`

The stop hook already extracts citations and calls `lessonStore.Cite()`. It should also increment the citation counter in injection-stats.

- [ ] **Step 1: Add citation counter increment after existing cite call**

In `go/cmd/recall-hook/stopall.go`, in the citation processing loop (around line 118):

```go
// Increment citation count in feedback stats
citationID := c.ID
if strings.HasPrefix(citationID, "L") {
	projectStatsPath := feedback.StatsFilePath(filepath.Join(input.Cwd, ".claude-recall"))
	feedback.IncrementCitation(projectStatsPath, citationID)
} else {
	systemStatsPath := feedback.StatsFilePath(stateDir)
	feedback.IncrementCitation(systemStatsPath, citationID)
}
```

Add imports: `"github.com/pbrown/claude-recall/go/internal/feedback"` and `"strings"`.

- [ ] **Step 2: Write test for citation counter increment**

Add to `go/cmd/recall-hook/stop_test.go`:

```go
func Test_StopHook_IncrementsCitationStats(t *testing.T) {
	// Create a transcript with a citation
	dir := t.TempDir()
	transcriptPath := filepath.Join(dir, "transcript.jsonl")
	transcript := `{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Applying [L001]: some lesson"}]}}`
	os.WriteFile(transcriptPath, []byte(transcript), 0644)

	projectDir := filepath.Join(dir, "project")
	os.MkdirAll(filepath.Join(projectDir, ".claude-recall"), 0755)

	// Run stop hook...
	// (Follow existing test patterns for setting up and invoking runStopAll)

	// Verify citation count incremented
	statsPath := feedback.StatsFilePath(filepath.Join(projectDir, ".claude-recall"))
	stats, err := feedback.ReadStats(statsPath)
	if err != nil {
		t.Fatal(err)
	}
	if stats["L001"].Citations != 1 {
		t.Errorf("expected 1 citation for L001, got %d", stats["L001"].Citations)
	}
}
```

- [ ] **Step 3: Run tests**

Run: `cd /home/pbrown/Code/claude-recall/go && go test ./cmd/recall-hook/ -v`
Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add go/cmd/recall-hook/stopall.go go/cmd/recall-hook/stop_test.go
git commit -m "feat(stop-hook): increment citation counts in injection-stats"
```

---

## Task 11: Integration Test — Full Precision Flow

**Files:**
- Create or modify: `go/internal/eventlog/integration_test.go` (or a new top-level integration test)

End-to-end test that verifies both features work together.

- [ ] **Step 1: Write integration test**

```go
func TestPrecisionFlow_FilePathAugmentation(t *testing.T) {
	dir := t.TempDir()

	// Set up session-files cache with API-related paths
	stateDir := filepath.Join(dir, "state")
	os.MkdirAll(stateDir, 0755)
	sfPath := sessionfiles.FilePath(stateDir, "test-session")
	sessionfiles.Write(sfPath, []string{"/proj/src/api/handler.go", "/proj/src/api/router.go"})

	// Read and extract segments
	paths, _ := sessionfiles.Read(sfPath)
	segments := sessionfiles.ExtractSegments(paths, "/proj")

	// Verify segments include "api", "handler", "router" but not extensions
	segSet := make(map[string]bool)
	for _, s := range segments {
		segSet[s] = true
	}
	if !segSet["api"] || !segSet["handler"] || !segSet["router"] {
		t.Errorf("expected api/handler/router segments, got %v", segments)
	}
	if segSet["go"] {
		t.Error("should not include file extension 'go'")
	}
}

func TestPrecisionFlow_FeedbackPenalty(t *testing.T) {
	dir := t.TempDir()
	statsPath := filepath.Join(dir, "injection-stats.json")

	// Simulate 7 injections with 0 citations for L008
	for i := 0; i < 7; i++ {
		feedback.IncrementInjection(statsPath, "L008")
	}

	stats, _ := feedback.ReadStats(statsPath)

	// Should be penalized (7 injections, 0 citations, ratio 0.0 < 0.2)
	if !feedback.ShouldPenalize(stats, "L008", 5, 0.2) {
		t.Error("L008 should be penalized: 7 injections, 0 citations")
	}

	// Simulate 2 citations — ratio becomes 2/7 ≈ 0.29 > 0.2
	feedback.IncrementCitation(statsPath, "L008")
	feedback.IncrementCitation(statsPath, "L008")

	stats, _ = feedback.ReadStats(statsPath)
	if feedback.ShouldPenalize(stats, "L008", 5, 0.2) {
		t.Error("L008 should NOT be penalized after citations: ratio 0.29 > 0.2")
	}
}
```

- [ ] **Step 2: Run integration test**

Run: `cd /home/pbrown/Code/claude-recall/go && go test ./... -run "TestPrecisionFlow" -v`
Expected: All pass

- [ ] **Step 3: Commit**

```bash
git add go/internal/feedback/feedback_test.go
git commit -m "test: add integration tests for precision flow"
```

---

## Task 12: Rebuild and Install Go Binaries

**Files:** None (build step only)

- [ ] **Step 1: Build recall and recall-hook binaries**

```bash
cd /home/pbrown/Code/claude-recall/go
go build -o ~/.local/bin/recall ./cmd/recall/
go build -o ~/.local/bin/recall-hook ./cmd/recall-hook/
```

- [ ] **Step 2: Run full test suite**

```bash
cd /home/pbrown/Code/claude-recall
go test ./go/... -v
./run-tests.sh -v --tb=short
```

Expected: All Go and Python tests pass

- [ ] **Step 3: Smoke test with real hook**

```bash
# Test score-local with augmented context (session-files present)
echo '{"prompt":"fix the USB scanner timeout","cwd":"/home/user/helixscreen","session_id":"smoke-test"}' | bash plugins/claude-recall/hooks/scripts/smart-inject-hook.sh
```

- [ ] **Step 4: Commit build artifacts if needed**

No commit needed — binaries are in ~/.local/bin, not in repo.

---

Plan complete and saved to `docs/superpowers/plans/2026-03-31-injection-precision.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?