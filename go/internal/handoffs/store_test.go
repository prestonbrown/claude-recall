package handoffs

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/pbrown/claude-recall/internal/models"
)

// Helper to create a test HANDOFFS.md file
func createTestHandoffsFile(t *testing.T, dir, filename, content string) string {
	t.Helper()
	path := filepath.Join(dir, filename)
	if err := os.WriteFile(path, []byte(content), 0644); err != nil {
		t.Fatalf("Failed to create test file: %v", err)
	}
	return path
}

// Helper to read file content
func readHandoffsFile(t *testing.T, path string) string {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("Failed to read file: %v", err)
	}
	return string(data)
}

func Test_Store_List_Empty(t *testing.T) {
	dir := t.TempDir()
	projectPath := filepath.Join(dir, "project", "HANDOFFS.md")
	stealthPath := filepath.Join(dir, "project", "HANDOFFS_LOCAL.md")

	store := NewStore(projectPath, stealthPath)
	handoffs, err := store.List()
	if err != nil {
		t.Fatalf("List failed: %v", err)
	}

	if len(handoffs) != 0 {
		t.Errorf("Expected 0 handoffs, got %d", len(handoffs))
	}
}

func Test_Store_List_Multiple(t *testing.T) {
	dir := t.TempDir()
	projectDir := filepath.Join(dir, "project")
	os.MkdirAll(projectDir, 0755)

	projectContent := `# HANDOFFS.md - Active Work Tracking

> Track ongoing work with tried steps and next steps.
> When completed, review for lessons to extract.

## Active Handoffs

### [hf-a1b2c3d] First Active Handoff
- **Status**: in_progress | **Phase**: implementing | **Agent**: general-purpose
- **Created**: 2026-01-15 | **Updated**: 2026-01-20
- **Description**: First active handoff description

**Next**: Continue implementing

---

### [hf-b2c3d4e] Second Active Handoff
- **Status**: not_started | **Phase**: research | **Agent**: user
- **Created**: 2026-01-18 | **Updated**: 2026-01-18
- **Description**: Second active handoff description

**Next**: Start research

---

### [hf-c3d4e5f] Completed Handoff
- **Status**: completed | **Phase**: review | **Agent**: user
- **Created**: 2026-01-10 | **Updated**: 2026-01-15
- **Description**: This is completed

**Next**: Done

---
`

	projectPath := createTestHandoffsFile(t, projectDir, "HANDOFFS.md", projectContent)
	stealthPath := filepath.Join(projectDir, "HANDOFFS_LOCAL.md")

	store := NewStore(projectPath, stealthPath)
	handoffs, err := store.List()
	if err != nil {
		t.Fatalf("List failed: %v", err)
	}

	// List returns only active (non-completed) handoffs
	if len(handoffs) != 2 {
		t.Fatalf("Expected 2 active handoffs, got %d", len(handoffs))
	}

	// Verify the handoffs are active
	for _, h := range handoffs {
		if h.Status == "completed" {
			t.Errorf("List should not return completed handoffs, got ID %s with status %s", h.ID, h.Status)
		}
	}
}

func Test_Store_ListAll(t *testing.T) {
	dir := t.TempDir()
	projectDir := filepath.Join(dir, "project")
	os.MkdirAll(projectDir, 0755)

	projectContent := `# HANDOFFS.md - Active Work Tracking

> Track ongoing work with tried steps and next steps.
> When completed, review for lessons to extract.

## Active Handoffs

### [hf-a1b2c3d] Active Handoff
- **Status**: in_progress | **Phase**: implementing | **Agent**: general-purpose
- **Created**: 2026-01-15 | **Updated**: 2026-01-20
- **Description**: Active handoff

**Next**: Continue

---

### [hf-c3d4e5f] Completed Handoff
- **Status**: completed | **Phase**: review | **Agent**: user
- **Created**: 2026-01-10 | **Updated**: 2026-01-15
- **Description**: Completed

**Next**: Done

---
`

	projectPath := createTestHandoffsFile(t, projectDir, "HANDOFFS.md", projectContent)
	stealthPath := filepath.Join(projectDir, "HANDOFFS_LOCAL.md")

	store := NewStore(projectPath, stealthPath)
	handoffs, err := store.ListAll()
	if err != nil {
		t.Fatalf("ListAll failed: %v", err)
	}

	// ListAll returns all handoffs including completed
	if len(handoffs) != 2 {
		t.Fatalf("Expected 2 handoffs, got %d", len(handoffs))
	}
}

func Test_Store_Get_Found(t *testing.T) {
	dir := t.TempDir()
	projectDir := filepath.Join(dir, "project")
	os.MkdirAll(projectDir, 0755)

	projectContent := `# HANDOFFS.md - Active Work Tracking

> Track ongoing work with tried steps and next steps.
> When completed, review for lessons to extract.

## Active Handoffs

### [hf-a1b2c3d] Test Handoff
- **Status**: in_progress | **Phase**: implementing | **Agent**: general-purpose
- **Created**: 2026-01-15 | **Updated**: 2026-01-20
- **Refs**: src/main.go:10 | src/util.go:25
- **Description**: Test description

**Tried**:
1. [success] First step worked
2. [fail] Second step failed

**Next**: Continue implementing

---
`

	projectPath := createTestHandoffsFile(t, projectDir, "HANDOFFS.md", projectContent)
	stealthPath := filepath.Join(projectDir, "HANDOFFS_LOCAL.md")

	store := NewStore(projectPath, stealthPath)
	handoff, err := store.Get("hf-a1b2c3d")
	if err != nil {
		t.Fatalf("Get failed: %v", err)
	}

	if handoff == nil {
		t.Fatal("Expected handoff, got nil")
	}
	if handoff.ID != "hf-a1b2c3d" {
		t.Errorf("Expected ID 'hf-a1b2c3d', got '%s'", handoff.ID)
	}
	if handoff.Title != "Test Handoff" {
		t.Errorf("Expected Title 'Test Handoff', got '%s'", handoff.Title)
	}
	if handoff.Status != "in_progress" {
		t.Errorf("Expected Status 'in_progress', got '%s'", handoff.Status)
	}
	if handoff.Phase != "implementing" {
		t.Errorf("Expected Phase 'implementing', got '%s'", handoff.Phase)
	}
	if handoff.Agent != "general-purpose" {
		t.Errorf("Expected Agent 'general-purpose', got '%s'", handoff.Agent)
	}
	if handoff.Description != "Test description" {
		t.Errorf("Expected Description 'Test description', got '%s'", handoff.Description)
	}
	if len(handoff.Refs) != 2 {
		t.Errorf("Expected 2 Refs, got %d", len(handoff.Refs))
	}
	if len(handoff.Tried) != 2 {
		t.Errorf("Expected 2 Tried steps, got %d", len(handoff.Tried))
	}
	if handoff.NextSteps != "Continue implementing" {
		t.Errorf("Expected NextSteps 'Continue implementing', got '%s'", handoff.NextSteps)
	}
}

func Test_Store_Get_NotFound(t *testing.T) {
	dir := t.TempDir()
	projectPath := filepath.Join(dir, "project", "HANDOFFS.md")
	stealthPath := filepath.Join(dir, "project", "HANDOFFS_LOCAL.md")

	store := NewStore(projectPath, stealthPath)
	_, err := store.Get("hf-9999999")
	if err == nil {
		t.Error("Expected error for missing ID, got nil")
	}
	if !strings.Contains(err.Error(), "not found") {
		t.Errorf("Expected 'not found' error, got: %v", err)
	}
}

func Test_Store_Add_CreatesHandoff(t *testing.T) {
	dir := t.TempDir()
	projectDir := filepath.Join(dir, "project")
	os.MkdirAll(projectDir, 0755)

	projectPath := filepath.Join(projectDir, "HANDOFFS.md")
	stealthPath := filepath.Join(projectDir, "HANDOFFS_LOCAL.md")

	store := NewStore(projectPath, stealthPath)
	handoff, err := store.Add("New Handoff Title", "This is the description", false)
	if err != nil {
		t.Fatalf("Add failed: %v", err)
	}

	if handoff == nil {
		t.Fatal("Expected handoff, got nil")
	}

	// Check ID format: hf-XXXXXXX (7 hex chars)
	if !strings.HasPrefix(handoff.ID, "hf-") {
		t.Errorf("Expected ID to start with 'hf-', got '%s'", handoff.ID)
	}
	if len(handoff.ID) != 10 { // hf- + 7 chars
		t.Errorf("Expected ID length 10, got %d for '%s'", len(handoff.ID), handoff.ID)
	}

	if handoff.Title != "New Handoff Title" {
		t.Errorf("Expected Title 'New Handoff Title', got '%s'", handoff.Title)
	}
	if handoff.Description != "This is the description" {
		t.Errorf("Expected Description 'This is the description', got '%s'", handoff.Description)
	}
	if handoff.Status != "not_started" {
		t.Errorf("Expected Status 'not_started', got '%s'", handoff.Status)
	}
	if handoff.Phase != "research" {
		t.Errorf("Expected Phase 'research', got '%s'", handoff.Phase)
	}
	if handoff.Agent != "user" {
		t.Errorf("Expected Agent 'user', got '%s'", handoff.Agent)
	}
	if handoff.Stealth != false {
		t.Errorf("Expected Stealth false, got %v", handoff.Stealth)
	}

	// Check dates are set to today
	today := time.Now().Format("2006-01-02")
	if handoff.Created.Format("2006-01-02") != today {
		t.Errorf("Expected Created date %s, got %s", today, handoff.Created.Format("2006-01-02"))
	}
	if handoff.Updated.Format("2006-01-02") != today {
		t.Errorf("Expected Updated date %s, got %s", today, handoff.Updated.Format("2006-01-02"))
	}

	// Verify file was written
	content := readHandoffsFile(t, projectPath)
	if !strings.Contains(content, handoff.ID) {
		t.Errorf("Expected file to contain '%s'", handoff.ID)
	}
	if !strings.Contains(content, "New Handoff Title") {
		t.Error("Expected file to contain 'New Handoff Title'")
	}
}

func Test_Store_Add_Stealth(t *testing.T) {
	dir := t.TempDir()
	projectDir := filepath.Join(dir, "project")
	os.MkdirAll(projectDir, 0755)

	projectPath := filepath.Join(projectDir, "HANDOFFS.md")
	stealthPath := filepath.Join(projectDir, "HANDOFFS_LOCAL.md")

	store := NewStore(projectPath, stealthPath)
	handoff, err := store.Add("Stealth Handoff", "Private work", true)
	if err != nil {
		t.Fatalf("Add stealth failed: %v", err)
	}

	if handoff.Stealth != true {
		t.Errorf("Expected Stealth true, got %v", handoff.Stealth)
	}

	// Verify written to stealth file, not project file
	if _, err := os.Stat(projectPath); !os.IsNotExist(err) {
		content := readHandoffsFile(t, projectPath)
		if strings.Contains(content, handoff.ID) {
			t.Error("Stealth handoff should not be in project file")
		}
	}

	// Verify stealth file has the handoff
	stealthContent := readHandoffsFile(t, stealthPath)
	if !strings.Contains(stealthContent, handoff.ID) {
		t.Error("Expected stealth file to contain handoff ID")
	}
}

func Test_Store_Update_ModifiesFields(t *testing.T) {
	dir := t.TempDir()
	projectDir := filepath.Join(dir, "project")
	os.MkdirAll(projectDir, 0755)

	projectContent := `# HANDOFFS.md - Active Work Tracking

> Track ongoing work with tried steps and next steps.
> When completed, review for lessons to extract.

## Active Handoffs

### [hf-a1b2c3d] Original Title
- **Status**: not_started | **Phase**: research | **Agent**: user
- **Created**: 2026-01-15 | **Updated**: 2026-01-15
- **Description**: Original description

**Next**: Start work

---
`

	projectPath := createTestHandoffsFile(t, projectDir, "HANDOFFS.md", projectContent)
	stealthPath := filepath.Join(projectDir, "HANDOFFS_LOCAL.md")

	store := NewStore(projectPath, stealthPath)
	err := store.Update("hf-a1b2c3d", map[string]interface{}{
		"status":      "in_progress",
		"phase":       "implementing",
		"agent":       "general-purpose",
		"description": "Updated description",
		"next_steps":  "Continue implementing",
		"refs":        []string{"src/main.go:10", "src/util.go:25"},
	})
	if err != nil {
		t.Fatalf("Update failed: %v", err)
	}

	handoff, err := store.Get("hf-a1b2c3d")
	if err != nil {
		t.Fatalf("Get failed: %v", err)
	}

	if handoff.Status != "in_progress" {
		t.Errorf("Expected Status 'in_progress', got '%s'", handoff.Status)
	}
	if handoff.Phase != "implementing" {
		t.Errorf("Expected Phase 'implementing', got '%s'", handoff.Phase)
	}
	if handoff.Agent != "general-purpose" {
		t.Errorf("Expected Agent 'general-purpose', got '%s'", handoff.Agent)
	}
	if handoff.Description != "Updated description" {
		t.Errorf("Expected Description 'Updated description', got '%s'", handoff.Description)
	}
	if handoff.NextSteps != "Continue implementing" {
		t.Errorf("Expected NextSteps 'Continue implementing', got '%s'", handoff.NextSteps)
	}
	if len(handoff.Refs) != 2 {
		t.Errorf("Expected 2 Refs, got %d", len(handoff.Refs))
	}

	// Check Updated date is today
	today := time.Now().Format("2006-01-02")
	if handoff.Updated.Format("2006-01-02") != today {
		t.Errorf("Expected Updated date %s, got %s", today, handoff.Updated.Format("2006-01-02"))
	}
}

func Test_Store_AddTriedStep(t *testing.T) {
	dir := t.TempDir()
	projectDir := filepath.Join(dir, "project")
	os.MkdirAll(projectDir, 0755)

	projectContent := `# HANDOFFS.md - Active Work Tracking

> Track ongoing work with tried steps and next steps.
> When completed, review for lessons to extract.

## Active Handoffs

### [hf-a1b2c3d] Test Handoff
- **Status**: in_progress | **Phase**: implementing | **Agent**: general-purpose
- **Created**: 2026-01-15 | **Updated**: 2026-01-15
- **Description**: Test description

**Tried**:
1. [success] First step worked

**Next**: Continue

---
`

	projectPath := createTestHandoffsFile(t, projectDir, "HANDOFFS.md", projectContent)
	stealthPath := filepath.Join(projectDir, "HANDOFFS_LOCAL.md")

	store := NewStore(projectPath, stealthPath)
	err := store.AddTriedStep("hf-a1b2c3d", "partial", "Second step partially worked")
	if err != nil {
		t.Fatalf("AddTriedStep failed: %v", err)
	}

	handoff, err := store.Get("hf-a1b2c3d")
	if err != nil {
		t.Fatalf("Get failed: %v", err)
	}

	if len(handoff.Tried) != 2 {
		t.Fatalf("Expected 2 Tried steps, got %d", len(handoff.Tried))
	}
	if handoff.Tried[1].Outcome != "partial" {
		t.Errorf("Expected second Tried step outcome 'partial', got '%s'", handoff.Tried[1].Outcome)
	}
	if handoff.Tried[1].Description != "Second step partially worked" {
		t.Errorf("Expected second Tried step description, got '%s'", handoff.Tried[1].Description)
	}
}

func Test_Store_AddTriedStep_InvalidOutcome(t *testing.T) {
	dir := t.TempDir()
	projectDir := filepath.Join(dir, "project")
	os.MkdirAll(projectDir, 0755)

	projectContent := `# HANDOFFS.md - Active Work Tracking

> Track ongoing work with tried steps and next steps.
> When completed, review for lessons to extract.

## Active Handoffs

### [hf-a1b2c3d] Test Handoff
- **Status**: in_progress | **Phase**: implementing | **Agent**: general-purpose
- **Created**: 2026-01-15 | **Updated**: 2026-01-15
- **Description**: Test description

**Next**: Continue

---
`

	projectPath := createTestHandoffsFile(t, projectDir, "HANDOFFS.md", projectContent)
	stealthPath := filepath.Join(projectDir, "HANDOFFS_LOCAL.md")

	store := NewStore(projectPath, stealthPath)
	err := store.AddTriedStep("hf-a1b2c3d", "invalid", "This should fail")
	if err == nil {
		t.Error("Expected error for invalid outcome, got nil")
	}
	if !strings.Contains(err.Error(), "invalid outcome") {
		t.Errorf("Expected 'invalid outcome' error, got: %v", err)
	}
}

func Test_Store_Complete_SetsStatus(t *testing.T) {
	dir := t.TempDir()
	projectDir := filepath.Join(dir, "project")
	os.MkdirAll(projectDir, 0755)

	projectContent := `# HANDOFFS.md - Active Work Tracking

> Track ongoing work with tried steps and next steps.
> When completed, review for lessons to extract.

## Active Handoffs

### [hf-a1b2c3d] Test Handoff
- **Status**: in_progress | **Phase**: implementing | **Agent**: general-purpose
- **Created**: 2026-01-15 | **Updated**: 2026-01-15
- **Description**: Test description

**Next**: Continue

---
`

	projectPath := createTestHandoffsFile(t, projectDir, "HANDOFFS.md", projectContent)
	stealthPath := filepath.Join(projectDir, "HANDOFFS_LOCAL.md")

	store := NewStore(projectPath, stealthPath)
	err := store.Complete("hf-a1b2c3d")
	if err != nil {
		t.Fatalf("Complete failed: %v", err)
	}

	handoff, err := store.Get("hf-a1b2c3d")
	if err != nil {
		t.Fatalf("Get failed: %v", err)
	}

	if handoff.Status != "completed" {
		t.Errorf("Expected Status 'completed', got '%s'", handoff.Status)
	}

	// Check Updated date is today
	today := time.Now().Format("2006-01-02")
	if handoff.Updated.Format("2006-01-02") != today {
		t.Errorf("Expected Updated date %s, got %s", today, handoff.Updated.Format("2006-01-02"))
	}
}

func Test_Store_Archive_KeepsRecent(t *testing.T) {
	dir := t.TempDir()
	projectDir := filepath.Join(dir, "project")
	os.MkdirAll(projectDir, 0755)

	// Create file with 5 completed handoffs (more than HandoffMaxCompleted=3)
	// and some active ones
	projectContent := `# HANDOFFS.md - Active Work Tracking

> Track ongoing work with tried steps and next steps.
> When completed, review for lessons to extract.

## Active Handoffs

### [hf-0000001] Active Handoff
- **Status**: in_progress | **Phase**: implementing | **Agent**: general-purpose
- **Created**: 2026-01-20 | **Updated**: 2026-01-25
- **Description**: Active work

**Next**: Continue

---

### [hf-0000002] Completed Recent 1
- **Status**: completed | **Phase**: review | **Agent**: user
- **Created**: 2026-01-20 | **Updated**: 2026-01-25
- **Description**: Recent completed 1

**Next**: Done

---

### [hf-0000003] Completed Recent 2
- **Status**: completed | **Phase**: review | **Agent**: user
- **Created**: 2026-01-18 | **Updated**: 2026-01-23
- **Description**: Recent completed 2

**Next**: Done

---

### [hf-0000004] Completed Recent 3
- **Status**: completed | **Phase**: review | **Agent**: user
- **Created**: 2026-01-15 | **Updated**: 2026-01-20
- **Description**: Recent completed 3

**Next**: Done

---

### [hf-0000005] Completed Old 1
- **Status**: completed | **Phase**: review | **Agent**: user
- **Created**: 2025-12-01 | **Updated**: 2025-12-10
- **Description**: Old completed 1

**Next**: Done

---

### [hf-0000006] Completed Old 2
- **Status**: completed | **Phase**: review | **Agent**: user
- **Created**: 2025-11-01 | **Updated**: 2025-11-10
- **Description**: Old completed 2

**Next**: Done

---
`

	projectPath := createTestHandoffsFile(t, projectDir, "HANDOFFS.md", projectContent)
	stealthPath := filepath.Join(projectDir, "HANDOFFS_LOCAL.md")

	store := NewStore(projectPath, stealthPath)
	archived, err := store.Archive()
	if err != nil {
		t.Fatalf("Archive failed: %v", err)
	}

	// Should archive 2 old completed handoffs (keeping 3 most recent completed)
	if archived != 2 {
		t.Errorf("Expected 2 archived, got %d", archived)
	}

	// Verify active handoff is still there
	handoffs, err := store.ListAll()
	if err != nil {
		t.Fatalf("ListAll failed: %v", err)
	}

	// Should have: 1 active + 3 recent completed = 4
	if len(handoffs) != 4 {
		t.Errorf("Expected 4 handoffs after archive, got %d", len(handoffs))
	}

	// Verify old completed are removed
	for _, h := range handoffs {
		if h.ID == "hf-0000005" || h.ID == "hf-0000006" {
			t.Errorf("Expected handoff %s to be archived", h.ID)
		}
	}
}

func Test_Store_List_IncludesStealth(t *testing.T) {
	dir := t.TempDir()
	projectDir := filepath.Join(dir, "project")
	os.MkdirAll(projectDir, 0755)

	projectContent := `# HANDOFFS.md - Active Work Tracking

> Track ongoing work with tried steps and next steps.
> When completed, review for lessons to extract.

## Active Handoffs

### [hf-a1b2c3d] Project Handoff
- **Status**: in_progress | **Phase**: implementing | **Agent**: general-purpose
- **Created**: 2026-01-15 | **Updated**: 2026-01-20
- **Description**: Public work

**Next**: Continue

---
`

	stealthContent := `# HANDOFFS.md - Active Work Tracking

> Track ongoing work with tried steps and next steps.
> When completed, review for lessons to extract.

## Active Handoffs

### [hf-e1f2a3b] Stealth Handoff
- **Status**: in_progress | **Phase**: research | **Agent**: user
- **Created**: 2026-01-18 | **Updated**: 2026-01-18
- **Description**: Private work

**Next**: Research

---
`

	projectPath := createTestHandoffsFile(t, projectDir, "HANDOFFS.md", projectContent)
	stealthPath := createTestHandoffsFile(t, projectDir, "HANDOFFS_LOCAL.md", stealthContent)

	store := NewStore(projectPath, stealthPath)
	handoffs, err := store.List()
	if err != nil {
		t.Fatalf("List failed: %v", err)
	}

	// Should include both project and stealth handoffs
	if len(handoffs) != 2 {
		t.Fatalf("Expected 2 handoffs, got %d", len(handoffs))
	}

	// Verify stealth handoff has Stealth=true
	var stealthHandoff *models.Handoff
	for _, h := range handoffs {
		if h.ID == "hf-e1f2a3b" {
			stealthHandoff = h
			break
		}
	}
	if stealthHandoff == nil {
		t.Fatal("Expected to find stealth handoff")
	}
	if !stealthHandoff.Stealth {
		t.Error("Expected stealth handoff to have Stealth=true")
	}
}

func Test_Store_Update_NotFound(t *testing.T) {
	dir := t.TempDir()
	projectPath := filepath.Join(dir, "project", "HANDOFFS.md")
	stealthPath := filepath.Join(dir, "project", "HANDOFFS_LOCAL.md")

	store := NewStore(projectPath, stealthPath)
	err := store.Update("hf-9999999", map[string]interface{}{"status": "in_progress"})
	if err == nil {
		t.Error("Expected error for updating non-existent handoff")
	}
}

func Test_Store_Complete_NotFound(t *testing.T) {
	dir := t.TempDir()
	projectPath := filepath.Join(dir, "project", "HANDOFFS.md")
	stealthPath := filepath.Join(dir, "project", "HANDOFFS_LOCAL.md")

	store := NewStore(projectPath, stealthPath)
	err := store.Complete("hf-9999999")
	if err == nil {
		t.Error("Expected error for completing non-existent handoff")
	}
}

func Test_Store_AddTriedStep_NotFound(t *testing.T) {
	dir := t.TempDir()
	projectPath := filepath.Join(dir, "project", "HANDOFFS.md")
	stealthPath := filepath.Join(dir, "project", "HANDOFFS_LOCAL.md")

	store := NewStore(projectPath, stealthPath)
	err := store.AddTriedStep("hf-9999999", "success", "This should fail")
	if err == nil {
		t.Error("Expected error for adding tried step to non-existent handoff")
	}
}

func Test_GenerateID(t *testing.T) {
	id1 := GenerateID()
	id2 := GenerateID()

	// Check format
	if !strings.HasPrefix(id1, "hf-") {
		t.Errorf("Expected ID to start with 'hf-', got '%s'", id1)
	}
	if len(id1) != 10 { // hf- + 7 chars
		t.Errorf("Expected ID length 10, got %d for '%s'", len(id1), id1)
	}

	// Check uniqueness
	if id1 == id2 {
		t.Errorf("Expected unique IDs, got same: '%s'", id1)
	}

	// Check hex chars only
	suffix := strings.TrimPrefix(id1, "hf-")
	for _, c := range suffix {
		if !((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f')) {
			t.Errorf("Expected hex char, got '%c' in '%s'", c, id1)
		}
	}
}
