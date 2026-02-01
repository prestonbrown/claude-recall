package handoffs

import (
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"time"

	"github.com/pbrown/claude-recall/internal/lock"
	"github.com/pbrown/claude-recall/internal/models"
)

// Store manages handoffs in project and stealth HANDOFFS.md files
type Store struct {
	projectPath string // Path to HANDOFFS.md
	stealthPath string // Path to HANDOFFS_LOCAL.md (stealth handoffs)
}

// NewStore creates a store with paths to handoff files
func NewStore(projectPath, stealthPath string) *Store {
	return &Store{
		projectPath: projectPath,
		stealthPath: stealthPath,
	}
}

// List returns all active (non-completed) handoffs
func (s *Store) List() ([]*models.Handoff, error) {
	all, err := s.ListAll()
	if err != nil {
		return nil, err
	}

	var active []*models.Handoff
	for _, h := range all {
		if h.Status != "completed" {
			active = append(active, h)
		}
	}

	return active, nil
}

// ListAll returns all handoffs including completed
func (s *Store) ListAll() ([]*models.Handoff, error) {
	var all []*models.Handoff

	// Load project handoffs (NotExist is handled in loadHandoffs)
	projectHandoffs, err := s.loadHandoffs(s.projectPath, false)
	if err != nil {
		return nil, fmt.Errorf("loading project handoffs: %w", err)
	}
	all = append(all, projectHandoffs...)

	// Load stealth handoffs (NotExist is handled in loadHandoffs)
	stealthHandoffs, err := s.loadHandoffs(s.stealthPath, true)
	if err != nil {
		return nil, fmt.Errorf("loading stealth handoffs: %w", err)
	}
	all = append(all, stealthHandoffs...)

	// Sort by Updated date (most recent first)
	sort.Slice(all, func(i, j int) bool {
		return all[i].Updated.After(all[j].Updated)
	})

	return all, nil
}

// Get returns a handoff by ID
func (s *Store) Get(id string) (*models.Handoff, error) {
	handoffs, err := s.ListAll()
	if err != nil {
		return nil, err
	}

	for _, h := range handoffs {
		if h.ID == id {
			return h, nil
		}
	}

	return nil, fmt.Errorf("handoff %s not found", id)
}

// Add creates a new handoff (returns new ID)
func (s *Store) Add(title, description string, stealth bool) (*models.Handoff, error) {
	// Determine which file to use
	path := s.projectPath
	if stealth {
		path = s.stealthPath
	}

	// Ensure directory exists
	dir := filepath.Dir(path)
	if err := os.MkdirAll(dir, 0755); err != nil {
		return nil, fmt.Errorf("failed to create directory: %w", err)
	}

	// Generate new ID
	id := GenerateID()

	// Create new handoff with defaults
	handoff := models.NewHandoff(id, title)
	handoff.Description = description
	handoff.Stealth = stealth

	// Acquire lock and write
	lockPath := path + ".lock"
	fl, err := lock.Acquire(lockPath)
	if err != nil {
		return nil, fmt.Errorf("failed to acquire lock: %w", err)
	}
	defer fl.Release()

	// Load existing handoffs
	handoffs, _ := s.loadHandoffs(path, stealth)
	handoffs = append(handoffs, handoff)

	// Write back
	if err := s.writeHandoffs(path, handoffs); err != nil {
		return nil, fmt.Errorf("failed to write handoffs: %w", err)
	}

	return handoff, nil
}

// Update modifies an existing handoff
func (s *Store) Update(id string, updates map[string]interface{}) error {
	// Find the handoff and its file
	path, stealth, err := s.findHandoffFile(id)
	if err != nil {
		return err
	}

	// Acquire lock
	lockPath := path + ".lock"
	fl, err := lock.Acquire(lockPath)
	if err != nil {
		return fmt.Errorf("failed to acquire lock: %w", err)
	}
	defer fl.Release()

	// Load handoffs
	handoffs, err := s.loadHandoffs(path, stealth)
	if err != nil {
		return err
	}

	// Find and update the handoff
	found := false
	for _, h := range handoffs {
		if h.ID == id {
			applyHandoffUpdates(h, updates)
			h.Updated = time.Now()
			found = true
			break
		}
	}

	if !found {
		return fmt.Errorf("handoff %s not found", id)
	}

	// Write back
	return s.writeHandoffs(path, handoffs)
}

// AddTriedStep adds a tried step to a handoff
func (s *Store) AddTriedStep(id, outcome, description string) error {
	// Validate outcome
	if !models.IsValidTriedStepOutcome(outcome) {
		return fmt.Errorf("invalid outcome '%s': must be success, fail, or partial", outcome)
	}

	// Find the handoff and its file
	path, stealth, err := s.findHandoffFile(id)
	if err != nil {
		return err
	}

	// Acquire lock
	lockPath := path + ".lock"
	fl, err := lock.Acquire(lockPath)
	if err != nil {
		return fmt.Errorf("failed to acquire lock: %w", err)
	}
	defer fl.Release()

	// Load handoffs
	handoffs, err := s.loadHandoffs(path, stealth)
	if err != nil {
		return err
	}

	// Find and update the handoff
	found := false
	for _, h := range handoffs {
		if h.ID == id {
			h.Tried = append(h.Tried, models.TriedStep{
				Outcome:     outcome,
				Description: description,
			})
			h.Updated = time.Now()
			found = true
			break
		}
	}

	if !found {
		return fmt.Errorf("handoff %s not found", id)
	}

	// Write back
	return s.writeHandoffs(path, handoffs)
}

// Complete marks a handoff as completed
func (s *Store) Complete(id string) error {
	// Find the handoff and its file
	path, stealth, err := s.findHandoffFile(id)
	if err != nil {
		return err
	}

	// Acquire lock
	lockPath := path + ".lock"
	fl, err := lock.Acquire(lockPath)
	if err != nil {
		return fmt.Errorf("failed to acquire lock: %w", err)
	}
	defer fl.Release()

	// Load handoffs
	handoffs, err := s.loadHandoffs(path, stealth)
	if err != nil {
		return err
	}

	// Find and update the handoff
	found := false
	for _, h := range handoffs {
		if h.ID == id {
			h.Status = "completed"
			h.Updated = time.Now()
			found = true
			break
		}
	}

	if !found {
		return fmt.Errorf("handoff %s not found", id)
	}

	// Write back
	return s.writeHandoffs(path, handoffs)
}

// Archive removes old completed handoffs (keep last N or within N days)
func (s *Store) Archive() (int, error) {
	archived := 0

	// Archive from project file
	n, err := s.archiveFile(s.projectPath, false)
	if err != nil {
		return archived, err
	}
	archived += n

	// Archive from stealth file
	n, err = s.archiveFile(s.stealthPath, true)
	if err != nil {
		return archived, err
	}
	archived += n

	return archived, nil
}

// archiveFile archives completed handoffs from a single file
func (s *Store) archiveFile(path string, stealth bool) (int, error) {
	// Check if file exists
	if _, err := os.Stat(path); os.IsNotExist(err) {
		return 0, nil
	}

	// Acquire lock
	lockPath := path + ".lock"
	fl, err := lock.Acquire(lockPath)
	if err != nil {
		return 0, fmt.Errorf("failed to acquire lock: %w", err)
	}
	defer fl.Release()

	// Load handoffs
	handoffs, err := s.loadHandoffs(path, stealth)
	if err != nil {
		return 0, err
	}

	// Separate active and completed
	var active []*models.Handoff
	var completed []*models.Handoff
	for _, h := range handoffs {
		if h.Status == "completed" {
			completed = append(completed, h)
		} else {
			active = append(active, h)
		}
	}

	// Sort completed by Updated date (most recent first)
	sort.Slice(completed, func(i, j int) bool {
		return completed[i].Updated.After(completed[j].Updated)
	})

	// Keep completed that are:
	// 1. Within HandoffMaxAgeDays, OR
	// 2. Among the most recent HandoffMaxCompleted
	cutoffDate := time.Now().AddDate(0, 0, -models.HandoffMaxAgeDays)
	var keep []*models.Handoff
	for i, h := range completed {
		// Keep if within age limit
		if h.Updated.After(cutoffDate) || h.Updated.Equal(cutoffDate) {
			keep = append(keep, h)
			continue
		}
		// Keep if among the most recent HandoffMaxCompleted
		if i < models.HandoffMaxCompleted {
			keep = append(keep, h)
		}
	}

	archived := len(completed) - len(keep)

	// Combine active and kept completed
	remaining := append(active, keep...)

	// Write back
	if err := s.writeHandoffs(path, remaining); err != nil {
		return 0, err
	}

	return archived, nil
}

// GenerateID generates a new hf-XXXXXXX ID (7 random hex chars)
func GenerateID() string {
	bytes := make([]byte, 4) // 4 bytes = 8 hex chars, we'll use 7
	if _, err := rand.Read(bytes); err != nil {
		// Fallback to timestamp-based ID on crypto/rand failure
		ts := time.Now().UnixNano()
		return fmt.Sprintf("hf-%07x", ts&0xFFFFFFF)
	}
	return "hf-" + hex.EncodeToString(bytes)[:7]
}

// loadHandoffs reads handoffs from a file
func (s *Store) loadHandoffs(path string, stealth bool) ([]*models.Handoff, error) {
	handoffs, err := ParseFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return []*models.Handoff{}, nil
		}
		return nil, err
	}

	// Set stealth flag for all handoffs
	for _, h := range handoffs {
		h.Stealth = stealth
	}

	return handoffs, nil
}

// writeHandoffs writes handoffs to a file
func (s *Store) writeHandoffs(path string, handoffs []*models.Handoff) error {
	content := Serialize(handoffs)
	return os.WriteFile(path, []byte(content), 0644)
}

// findHandoffFile returns the path and stealth flag for a handoff ID
func (s *Store) findHandoffFile(id string) (string, bool, error) {
	// Check project file
	handoffs, _ := s.loadHandoffs(s.projectPath, false)
	for _, h := range handoffs {
		if h.ID == id {
			return s.projectPath, false, nil
		}
	}

	// Check stealth file
	handoffs, _ = s.loadHandoffs(s.stealthPath, true)
	for _, h := range handoffs {
		if h.ID == id {
			return s.stealthPath, true, nil
		}
	}

	return "", false, fmt.Errorf("handoff %s not found", id)
}

// applyHandoffUpdates applies update map to a handoff
func applyHandoffUpdates(h *models.Handoff, updates map[string]interface{}) {
	if status, ok := updates["status"].(string); ok {
		h.Status = status
	}
	if phase, ok := updates["phase"].(string); ok {
		h.Phase = phase
	}
	if agent, ok := updates["agent"].(string); ok {
		h.Agent = agent
	}
	if description, ok := updates["description"].(string); ok {
		h.Description = description
	}
	if nextSteps, ok := updates["next_steps"].(string); ok {
		h.NextSteps = nextSteps
	}
	if refs, ok := updates["refs"].([]string); ok {
		h.Refs = refs
	}
	if checkpoint, ok := updates["checkpoint"].(string); ok {
		h.Checkpoint = checkpoint
	}
	if blockedBy, ok := updates["blocked_by"].([]string); ok {
		h.BlockedBy = blockedBy
	}
	if sessions, ok := updates["sessions"].([]string); ok {
		h.Sessions = sessions
	}
}
