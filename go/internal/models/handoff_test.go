package models

import (
	"testing"
	"time"
)

func TestHandoff_Defaults(t *testing.T) {
	h := NewHandoff("hf-a1b2c3d", "Test Handoff")

	if h.ID != "hf-a1b2c3d" {
		t.Errorf("ID = %q, want %q", h.ID, "hf-a1b2c3d")
	}
	if h.Title != "Test Handoff" {
		t.Errorf("Title = %q, want %q", h.Title, "Test Handoff")
	}
	if h.Status != "not_started" {
		t.Errorf("Status = %q, want %q", h.Status, "not_started")
	}
	if h.Phase != "research" {
		t.Errorf("Phase = %q, want %q", h.Phase, "research")
	}
	if h.Agent != "user" {
		t.Errorf("Agent = %q, want %q", h.Agent, "user")
	}
	if h.Created.IsZero() {
		t.Error("Created should be set to current time")
	}
	if h.Updated.IsZero() {
		t.Error("Updated should be set to current time")
	}
	if h.Refs == nil {
		t.Error("Refs should be initialized to empty slice")
	}
	if h.Tried == nil {
		t.Error("Tried should be initialized to empty slice")
	}
	if h.BlockedBy == nil {
		t.Error("BlockedBy should be initialized to empty slice")
	}
	if h.Sessions == nil {
		t.Error("Sessions should be initialized to empty slice")
	}
	if h.Stealth != false {
		t.Errorf("Stealth = %v, want %v", h.Stealth, false)
	}
	if h.LastSession != nil {
		t.Error("LastSession should be nil by default")
	}
	if h.Handoff != nil {
		t.Error("Handoff context should be nil by default")
	}
}

func TestTriedStep_Outcomes(t *testing.T) {
	validOutcomes := []string{"success", "fail", "partial"}

	for _, outcome := range validOutcomes {
		step := TriedStep{
			Outcome:     outcome,
			Description: "Test description",
		}

		if !IsValidTriedStepOutcome(step.Outcome) {
			t.Errorf("Outcome %q should be valid", outcome)
		}
	}

	invalidOutcomes := []string{"", "unknown", "completed", "failed"}
	for _, outcome := range invalidOutcomes {
		if IsValidTriedStepOutcome(outcome) {
			t.Errorf("Outcome %q should be invalid", outcome)
		}
	}
}

func TestHandoff_Constants(t *testing.T) {
	if HandoffMaxCompleted != 3 {
		t.Errorf("HandoffMaxCompleted = %d, want %d", HandoffMaxCompleted, 3)
	}
	if HandoffMaxAgeDays != 7 {
		t.Errorf("HandoffMaxAgeDays = %d, want %d", HandoffMaxAgeDays, 7)
	}
	if HandoffStaleDays != 7 {
		t.Errorf("HandoffStaleDays = %d, want %d", HandoffStaleDays, 7)
	}
}

func TestHandoffContext_Fields(t *testing.T) {
	ctx := HandoffContext{
		Summary:       "Test summary",
		CriticalFiles: []string{"file1.go", "file2.go"},
		RecentChanges: []string{"Added feature X"},
		Learnings:     []string{"Learned Y"},
		Blockers:      []string{"Blocked by Z"},
		GitRef:        "abc123",
	}

	if ctx.Summary != "Test summary" {
		t.Errorf("Summary = %q, want %q", ctx.Summary, "Test summary")
	}
	if len(ctx.CriticalFiles) != 2 {
		t.Errorf("CriticalFiles length = %d, want %d", len(ctx.CriticalFiles), 2)
	}
	if len(ctx.RecentChanges) != 1 {
		t.Errorf("RecentChanges length = %d, want %d", len(ctx.RecentChanges), 1)
	}
	if len(ctx.Learnings) != 1 {
		t.Errorf("Learnings length = %d, want %d", len(ctx.Learnings), 1)
	}
	if len(ctx.Blockers) != 1 {
		t.Errorf("Blockers length = %d, want %d", len(ctx.Blockers), 1)
	}
	if ctx.GitRef != "abc123" {
		t.Errorf("GitRef = %q, want %q", ctx.GitRef, "abc123")
	}
}

func TestHandoff_WithOptionalFields(t *testing.T) {
	now := time.Now()
	h := NewHandoff("hf-test", "Test")

	// Test setting optional fields
	h.LastSession = &now
	h.Handoff = &HandoffContext{
		Summary: "Context summary",
	}

	if h.LastSession == nil {
		t.Error("LastSession should be set")
	}
	if h.Handoff == nil {
		t.Error("Handoff context should be set")
	}
	if h.Handoff.Summary != "Context summary" {
		t.Errorf("Handoff.Summary = %q, want %q", h.Handoff.Summary, "Context summary")
	}
}

func TestHandoff_ValidStatuses(t *testing.T) {
	validStatuses := []string{
		"not_started",
		"in_progress",
		"blocked",
		"ready_for_review",
		"completed",
	}

	for _, status := range validStatuses {
		if !IsValidHandoffStatus(status) {
			t.Errorf("Status %q should be valid", status)
		}
	}

	invalidStatuses := []string{"", "pending", "done", "cancelled"}
	for _, status := range invalidStatuses {
		if IsValidHandoffStatus(status) {
			t.Errorf("Status %q should be invalid", status)
		}
	}
}

func TestHandoff_ValidPhases(t *testing.T) {
	validPhases := []string{
		"research",
		"planning",
		"implementing",
		"review",
	}

	for _, phase := range validPhases {
		if !IsValidHandoffPhase(phase) {
			t.Errorf("Phase %q should be valid", phase)
		}
	}

	invalidPhases := []string{"", "testing", "deployment", "done"}
	for _, phase := range invalidPhases {
		if IsValidHandoffPhase(phase) {
			t.Errorf("Phase %q should be invalid", phase)
		}
	}
}

func TestHandoff_ValidAgents(t *testing.T) {
	validAgents := []string{
		"explore",
		"general-purpose",
		"plan",
		"review",
		"user",
	}

	for _, agent := range validAgents {
		if !IsValidHandoffAgent(agent) {
			t.Errorf("Agent %q should be valid", agent)
		}
	}

	invalidAgents := []string{"", "bot", "ai", "assistant"}
	for _, agent := range invalidAgents {
		if IsValidHandoffAgent(agent) {
			t.Errorf("Agent %q should be invalid", agent)
		}
	}
}
