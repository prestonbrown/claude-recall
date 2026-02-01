package handoffs

import (
	"strings"
	"testing"
	"time"

	"github.com/pbrown/claude-recall/internal/models"
)

func TestParse_SingleHandoff(t *testing.T) {
	input := `# HANDOFFS.md - Active Work Tracking

> Track ongoing work with tried steps and next steps.
> When completed, review for lessons to extract.

## Active Handoffs

### [hf-a1b2c3d] Implement Parser
- **Status**: in_progress | **Phase**: implementing | **Agent**: general-purpose
- **Created**: 2026-01-15 | **Updated**: 2026-01-20
- **Refs**: internal/handoffs/parser.go:1 | internal/handoffs/parser_test.go:1
- **Description**: Create parser for HANDOFFS.md format.

**Tried**:
1. [success] Initial implementation - worked

**Next**: Step 1: Add more tests.

---
`

	handoffs, err := Parse(strings.NewReader(input))
	if err != nil {
		t.Fatalf("Parse failed: %v", err)
	}

	if len(handoffs) != 1 {
		t.Fatalf("Expected 1 handoff, got %d", len(handoffs))
	}

	h := handoffs[0]
	if h.ID != "hf-a1b2c3d" {
		t.Errorf("Expected ID 'hf-a1b2c3d', got '%s'", h.ID)
	}
	if h.Title != "Implement Parser" {
		t.Errorf("Expected title 'Implement Parser', got '%s'", h.Title)
	}
	if h.Status != "in_progress" {
		t.Errorf("Expected status 'in_progress', got '%s'", h.Status)
	}
	if h.Phase != "implementing" {
		t.Errorf("Expected phase 'implementing', got '%s'", h.Phase)
	}
	if h.Agent != "general-purpose" {
		t.Errorf("Expected agent 'general-purpose', got '%s'", h.Agent)
	}
	if h.Description != "Create parser for HANDOFFS.md format." {
		t.Errorf("Expected description 'Create parser for HANDOFFS.md format.', got '%s'", h.Description)
	}
	if len(h.Refs) != 2 {
		t.Errorf("Expected 2 refs, got %d", len(h.Refs))
	}
	if len(h.Tried) != 1 {
		t.Errorf("Expected 1 tried step, got %d", len(h.Tried))
	}
	if h.NextSteps != "Step 1: Add more tests." {
		t.Errorf("Expected next steps 'Step 1: Add more tests.', got '%s'", h.NextSteps)
	}
}

func TestParse_MultipleHandoffs(t *testing.T) {
	input := `# HANDOFFS.md - Active Work Tracking

## Active Handoffs

### [hf-1111111] First Handoff
- **Status**: in_progress | **Phase**: research | **Agent**: explore
- **Created**: 2026-01-10 | **Updated**: 2026-01-15
- **Description**: First task.

**Next**: Do something.

---

### [hf-2222222] Second Handoff
- **Status**: blocked | **Phase**: planning | **Agent**: plan
- **Created**: 2026-01-12 | **Updated**: 2026-01-18
- **Description**: Second task.

**Next**: Do something else.

---
`

	handoffs, err := Parse(strings.NewReader(input))
	if err != nil {
		t.Fatalf("Parse failed: %v", err)
	}

	if len(handoffs) != 2 {
		t.Fatalf("Expected 2 handoffs, got %d", len(handoffs))
	}

	if handoffs[0].ID != "hf-1111111" {
		t.Errorf("Expected first ID 'hf-1111111', got '%s'", handoffs[0].ID)
	}
	if handoffs[1].ID != "hf-2222222" {
		t.Errorf("Expected second ID 'hf-2222222', got '%s'", handoffs[1].ID)
	}
}

func TestParse_AllFields(t *testing.T) {
	input := `# HANDOFFS.md - Active Work Tracking

## Active Handoffs

### [hf-a1b2c3d] Full Handoff
- **Status**: blocked | **Phase**: implementing | **Agent**: general-purpose
- **Created**: 2026-01-15 | **Updated**: 2026-01-20
- **Refs**: core/main.py:50 | tests/test_foo.py:20-30
- **Description**: What we're trying to accomplish.
- **Checkpoint**: Progress summary here.
- **Last Session**: 2026-01-20
- **Handoff** (abc123def):
  - Summary: 1-2 sentence summary
  - Refs: core/file.py:100 | docs/plan.md:50
  - Changes: Modified X | Added Y | Fixed Z
  - Learnings: Discovered pattern | Found blocker
  - Blockers: Waiting for PR review | Need design decision
- **Blocked By**: hf-xyz789, hf-abc123
- **Sessions**: session-001, session-002

**Tried**:
1. [success] First approach - worked
2. [fail] Second approach - didn't work
3. [partial] Third approach - partly working

**Next**: Step 1: Do X. Step 2: Review with team.

---
`

	handoffs, err := Parse(strings.NewReader(input))
	if err != nil {
		t.Fatalf("Parse failed: %v", err)
	}

	if len(handoffs) != 1 {
		t.Fatalf("Expected 1 handoff, got %d", len(handoffs))
	}

	h := handoffs[0]

	// Check optional fields
	if h.Checkpoint != "Progress summary here." {
		t.Errorf("Expected checkpoint 'Progress summary here.', got '%s'", h.Checkpoint)
	}

	if h.LastSession == nil {
		t.Error("Expected LastSession to be set")
	} else {
		expected := time.Date(2026, 1, 20, 0, 0, 0, 0, time.UTC)
		if !h.LastSession.Equal(expected) {
			t.Errorf("Expected LastSession '2026-01-20', got '%v'", h.LastSession)
		}
	}

	if len(h.BlockedBy) != 2 {
		t.Errorf("Expected 2 BlockedBy, got %d", len(h.BlockedBy))
	} else {
		if h.BlockedBy[0] != "hf-xyz789" || h.BlockedBy[1] != "hf-abc123" {
			t.Errorf("BlockedBy mismatch: %v", h.BlockedBy)
		}
	}

	if len(h.Sessions) != 2 {
		t.Errorf("Expected 2 Sessions, got %d", len(h.Sessions))
	} else {
		if h.Sessions[0] != "session-001" || h.Sessions[1] != "session-002" {
			t.Errorf("Sessions mismatch: %v", h.Sessions)
		}
	}

	// Check HandoffContext
	if h.Handoff == nil {
		t.Error("Expected Handoff context to be set")
	} else {
		if h.Handoff.Summary != "1-2 sentence summary" {
			t.Errorf("Expected Handoff.Summary '1-2 sentence summary', got '%s'", h.Handoff.Summary)
		}
		if h.Handoff.GitRef != "abc123def" {
			t.Errorf("Expected Handoff.GitRef 'abc123def', got '%s'", h.Handoff.GitRef)
		}
		if len(h.Handoff.CriticalFiles) != 2 {
			t.Errorf("Expected 2 CriticalFiles, got %d", len(h.Handoff.CriticalFiles))
		}
		if len(h.Handoff.RecentChanges) != 3 {
			t.Errorf("Expected 3 RecentChanges, got %d", len(h.Handoff.RecentChanges))
		}
		if len(h.Handoff.Learnings) != 2 {
			t.Errorf("Expected 2 Learnings, got %d", len(h.Handoff.Learnings))
		}
		if len(h.Handoff.Blockers) != 2 {
			t.Errorf("Expected 2 Blockers, got %d", len(h.Handoff.Blockers))
		}
	}
}

func TestParse_TriedSteps(t *testing.T) {
	input := `# HANDOFFS.md - Active Work Tracking

## Active Handoffs

### [hf-a1b2c3d] Test Tried Steps
- **Status**: in_progress | **Phase**: implementing | **Agent**: general-purpose
- **Created**: 2026-01-15 | **Updated**: 2026-01-20
- **Description**: Testing tried steps parsing.

**Tried**:
1. [success] First approach - worked perfectly
2. [fail] Second approach - failed due to X
3. [partial] Third approach - partly working, needs more work

**Next**: Continue with approach 3.

---
`

	handoffs, err := Parse(strings.NewReader(input))
	if err != nil {
		t.Fatalf("Parse failed: %v", err)
	}

	h := handoffs[0]
	if len(h.Tried) != 3 {
		t.Fatalf("Expected 3 tried steps, got %d", len(h.Tried))
	}

	tests := []struct {
		outcome string
		desc    string
	}{
		{"success", "First approach - worked perfectly"},
		{"fail", "Second approach - failed due to X"},
		{"partial", "Third approach - partly working, needs more work"},
	}

	for i, tt := range tests {
		if h.Tried[i].Outcome != tt.outcome {
			t.Errorf("Tried[%d].Outcome: expected '%s', got '%s'", i, tt.outcome, h.Tried[i].Outcome)
		}
		if h.Tried[i].Description != tt.desc {
			t.Errorf("Tried[%d].Description: expected '%s', got '%s'", i, tt.desc, h.Tried[i].Description)
		}
	}
}

func TestParse_LegacyID(t *testing.T) {
	input := `# HANDOFFS.md - Active Work Tracking

## Active Handoffs

### [A001] Legacy Format Handoff
- **Status**: in_progress | **Phase**: research | **Agent**: user
- **Created**: 2026-01-15 | **Updated**: 2026-01-20
- **Description**: Old style ID format.

**Next**: Migrate to new format.

---
`

	handoffs, err := Parse(strings.NewReader(input))
	if err != nil {
		t.Fatalf("Parse failed: %v", err)
	}

	if len(handoffs) != 1 {
		t.Fatalf("Expected 1 handoff, got %d", len(handoffs))
	}

	if handoffs[0].ID != "A001" {
		t.Errorf("Expected ID 'A001', got '%s'", handoffs[0].ID)
	}
}

func TestSerialize_RoundTrip(t *testing.T) {
	created := time.Date(2026, 1, 15, 0, 0, 0, 0, time.UTC)
	updated := time.Date(2026, 1, 20, 0, 0, 0, 0, time.UTC)

	original := []*models.Handoff{
		{
			ID:          "hf-a1b2c3d",
			Title:       "Test Handoff",
			Status:      "in_progress",
			Phase:       "implementing",
			Agent:       "general-purpose",
			Created:     created,
			Updated:     updated,
			Description: "Test description.",
			Refs:        []string{"file1.go:10", "file2.go:20"},
			Tried: []models.TriedStep{
				{Outcome: "success", Description: "First try - worked"},
				{Outcome: "fail", Description: "Second try - failed"},
			},
			NextSteps: "Step 1: Continue. Step 2: Test.",
			BlockedBy: []string{},
			Sessions:  []string{},
		},
	}

	serialized := Serialize(original)
	parsed, err := Parse(strings.NewReader(serialized))
	if err != nil {
		t.Fatalf("Parse failed after serialize: %v", err)
	}

	if len(parsed) != 1 {
		t.Fatalf("Expected 1 handoff after round-trip, got %d", len(parsed))
	}

	h := parsed[0]
	if h.ID != original[0].ID {
		t.Errorf("ID mismatch: expected '%s', got '%s'", original[0].ID, h.ID)
	}
	if h.Title != original[0].Title {
		t.Errorf("Title mismatch: expected '%s', got '%s'", original[0].Title, h.Title)
	}
	if h.Status != original[0].Status {
		t.Errorf("Status mismatch: expected '%s', got '%s'", original[0].Status, h.Status)
	}
	if h.Phase != original[0].Phase {
		t.Errorf("Phase mismatch: expected '%s', got '%s'", original[0].Phase, h.Phase)
	}
	if h.Agent != original[0].Agent {
		t.Errorf("Agent mismatch: expected '%s', got '%s'", original[0].Agent, h.Agent)
	}
	if h.Description != original[0].Description {
		t.Errorf("Description mismatch: expected '%s', got '%s'", original[0].Description, h.Description)
	}
	if len(h.Refs) != len(original[0].Refs) {
		t.Errorf("Refs count mismatch: expected %d, got %d", len(original[0].Refs), len(h.Refs))
	}
	if len(h.Tried) != len(original[0].Tried) {
		t.Errorf("Tried count mismatch: expected %d, got %d", len(original[0].Tried), len(h.Tried))
	}
	if h.NextSteps != original[0].NextSteps {
		t.Errorf("NextSteps mismatch: expected '%s', got '%s'", original[0].NextSteps, h.NextSteps)
	}
}

func TestSerializeHandoff_AllFields(t *testing.T) {
	created := time.Date(2026, 1, 15, 0, 0, 0, 0, time.UTC)
	updated := time.Date(2026, 1, 20, 0, 0, 0, 0, time.UTC)
	lastSession := time.Date(2026, 1, 20, 0, 0, 0, 0, time.UTC)

	h := &models.Handoff{
		ID:          "hf-a1b2c3d",
		Title:       "Full Handoff",
		Status:      "blocked",
		Phase:       "implementing",
		Agent:       "general-purpose",
		Created:     created,
		Updated:     updated,
		Description: "Complete handoff with all fields.",
		Refs:        []string{"core/main.py:50", "tests/test_foo.py:20-30"},
		Checkpoint:  "Progress summary.",
		LastSession: &lastSession,
		Handoff: &models.HandoffContext{
			Summary:       "Summary of handoff context.",
			CriticalFiles: []string{"core/file.py:100", "docs/plan.md:50"},
			RecentChanges: []string{"Modified X", "Added Y"},
			Learnings:     []string{"Discovered pattern"},
			Blockers:      []string{"Waiting for PR review"},
			GitRef:        "abc123def",
		},
		BlockedBy: []string{"hf-xyz789", "hf-abc123"},
		Sessions:  []string{"session-001", "session-002"},
		Tried: []models.TriedStep{
			{Outcome: "success", Description: "First approach - worked"},
			{Outcome: "fail", Description: "Second approach - failed"},
		},
		NextSteps: "Step 1: Do X.",
	}

	result := SerializeHandoff(h)

	// Check that all fields are present
	checks := []string{
		"### [hf-a1b2c3d] Full Handoff",
		"**Status**: blocked",
		"**Phase**: implementing",
		"**Agent**: general-purpose",
		"**Created**: 2026-01-15",
		"**Updated**: 2026-01-20",
		"**Refs**: core/main.py:50 | tests/test_foo.py:20-30",
		"**Description**: Complete handoff with all fields.",
		"**Checkpoint**: Progress summary.",
		"**Last Session**: 2026-01-20",
		"**Handoff** (abc123def):",
		"Summary: Summary of handoff context.",
		"Refs: core/file.py:100 | docs/plan.md:50",
		"Changes: Modified X | Added Y",
		"Learnings: Discovered pattern",
		"Blockers: Waiting for PR review",
		"**Blocked By**: hf-xyz789, hf-abc123",
		"**Sessions**: session-001, session-002",
		"1. [success] First approach - worked",
		"2. [fail] Second approach - failed",
		"**Next**: Step 1: Do X.",
	}

	for _, check := range checks {
		if !strings.Contains(result, check) {
			t.Errorf("Expected output to contain '%s', but it didn't.\nGot:\n%s", check, result)
		}
	}
}

func TestParse_EmptyFile(t *testing.T) {
	input := ``
	handoffs, err := Parse(strings.NewReader(input))
	if err != nil {
		t.Fatalf("Parse failed: %v", err)
	}
	if len(handoffs) != 0 {
		t.Errorf("Expected 0 handoffs, got %d", len(handoffs))
	}
}

func TestParse_HeaderOnly(t *testing.T) {
	input := `# HANDOFFS.md - Active Work Tracking

> Track ongoing work with tried steps and next steps.
> When completed, review for lessons to extract.

## Active Handoffs
`
	handoffs, err := Parse(strings.NewReader(input))
	if err != nil {
		t.Fatalf("Parse failed: %v", err)
	}
	if len(handoffs) != 0 {
		t.Errorf("Expected 0 handoffs, got %d", len(handoffs))
	}
}
