package models

import (
	"fmt"
	"time"
)

// Handoff constants
const (
	HandoffMaxCompleted = 3
	HandoffMaxAgeDays   = 7
	HandoffStaleDays    = 7
)

// Valid handoff statuses
var validHandoffStatuses = map[string]bool{
	"not_started":      true,
	"in_progress":      true,
	"blocked":          true,
	"ready_for_review": true,
	"completed":        true,
}

// Valid handoff phases
var validHandoffPhases = map[string]bool{
	"research":     true,
	"planning":     true,
	"implementing": true,
	"review":       true,
}

// Valid handoff agents
var validHandoffAgents = map[string]bool{
	"explore":         true,
	"general-purpose": true,
	"plan":            true,
	"review":          true,
	"user":            true,
}

// Valid tried step outcomes
var validTriedStepOutcomes = map[string]bool{
	"success": true,
	"fail":    true,
	"partial": true,
}

// TriedStep represents an attempted step in a handoff
type TriedStep struct {
	Outcome     string // "success", "fail", "partial"
	Description string
}

// HandoffContext contains rich context for handoff continuation
type HandoffContext struct {
	Summary       string
	CriticalFiles []string
	RecentChanges []string
	Learnings     []string
	Blockers      []string
	GitRef        string
}

// Handoff represents a multi-step work item tracked across sessions
type Handoff struct {
	ID          string          // "hf-a1b2c3d" or legacy "A001"
	Title       string
	Status      string          // not_started|in_progress|blocked|ready_for_review|completed
	Created     time.Time
	Updated     time.Time
	Description string
	NextSteps   string
	Phase       string          // research|planning|implementing|review (default: "research")
	Agent       string          // explore|general-purpose|plan|review|user (default: "user")
	Refs        []string        // File references
	Tried       []TriedStep
	Checkpoint  string          // Legacy progress summary
	LastSession *time.Time      // When checkpoint was last updated (nil if not set)
	Handoff     *HandoffContext // Rich context (nil if not set)
	BlockedBy   []string        // IDs of blocking handoffs
	Stealth     bool            // If true, stored in HANDOFFS_LOCAL.md
	Sessions    []string        // Session IDs linked
}

// NewHandoff creates a new Handoff with default values
func NewHandoff(id, title string) *Handoff {
	now := time.Now()
	return &Handoff{
		ID:        id,
		Title:     title,
		Status:    "not_started",
		Created:   now,
		Updated:   now,
		Phase:     "research",
		Agent:     "user",
		Refs:      []string{},
		Tried:     []TriedStep{},
		BlockedBy: []string{},
		Sessions:  []string{},
		Stealth:   false,
	}
}

// IsValidTriedStepOutcome checks if the outcome is valid
func IsValidTriedStepOutcome(outcome string) bool {
	return validTriedStepOutcomes[outcome]
}

// IsValidHandoffStatus checks if the status is valid
func IsValidHandoffStatus(status string) bool {
	return validHandoffStatuses[status]
}

// IsValidHandoffPhase checks if the phase is valid
func IsValidHandoffPhase(phase string) bool {
	return validHandoffPhases[phase]
}

// IsValidHandoffAgent checks if the agent is valid
func IsValidHandoffAgent(agent string) bool {
	return validHandoffAgents[agent]
}

// ValidateStatusPhase checks if status and phase are compatible.
// Returns corrected phase if auto-fixable, or error if invalid.
// Rules:
//   - not_started: only research or planning allowed
//   - in_progress/blocked: any phase allowed
//   - ready_for_review/completed: should be review phase
func ValidateStatusPhase(status, phase string) (string, error) {
	switch status {
	case "not_started":
		// Can only be in research or planning if not started
		if phase == "implementing" || phase == "review" {
			// Auto-fix: if implementing, status should be in_progress
			return phase, fmt.Errorf("status 'not_started' incompatible with phase '%s'", phase)
		}
	case "ready_for_review", "completed":
		// Should be in review phase
		if phase != "review" {
			return "review", nil // Auto-fix to review
		}
	}
	return phase, nil
}

// NormalizeHandoffState ensures status and phase are compatible.
// Modifies the handoff in place if needed.
func (h *Handoff) NormalizeState() {
	// If implementing but not_started, upgrade to in_progress
	if h.Status == "not_started" && (h.Phase == "implementing" || h.Phase == "review") {
		h.Status = "in_progress"
	}
	// If completed/ready_for_review, ensure review phase
	if h.Status == "completed" || h.Status == "ready_for_review" {
		h.Phase = "review"
	}
}
