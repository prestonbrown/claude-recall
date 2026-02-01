package lessons

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/pbrown/claude-recall/internal/models"
)

func TestDecayLesson_VelocityHalves(t *testing.T) {
	lesson := &models.Lesson{
		ID:       "L001",
		Velocity: 4.0,
		Uses:     10,
	}

	DecayLesson(lesson)

	if lesson.Velocity != 2.0 {
		t.Errorf("expected velocity 2.0, got %f", lesson.Velocity)
	}
}

func TestDecayLesson_VelocityFloorToZero(t *testing.T) {
	lesson := &models.Lesson{
		ID:       "L001",
		Velocity: 0.01, // At epsilon
		Uses:     10,
	}

	DecayLesson(lesson)

	// 0.01 * 0.5 = 0.005 < epsilon, should become 0
	if lesson.Velocity != 0.0 {
		t.Errorf("expected velocity 0.0 (below epsilon), got %f", lesson.Velocity)
	}
}

func TestDecayLesson_UsesDecrement(t *testing.T) {
	lesson := &models.Lesson{
		ID:       "L001",
		Velocity: 0.3, // Below 0.5 threshold
		Uses:     5,
	}

	DecayLesson(lesson)

	// Low velocity should cause uses to decrement
	if lesson.Uses != 4 {
		t.Errorf("expected uses 4, got %d", lesson.Uses)
	}
}

func TestDecayLesson_UsesNeverBelowOne(t *testing.T) {
	lesson := &models.Lesson{
		ID:       "L001",
		Velocity: 0.1, // Low velocity
		Uses:     1,   // Already at minimum
	}

	DecayLesson(lesson)

	// Uses should stay at 1
	if lesson.Uses != 1 {
		t.Errorf("expected uses 1 (minimum), got %d", lesson.Uses)
	}
}

func TestDecayLesson_HighVelocityNoUsesDecrement(t *testing.T) {
	lesson := &models.Lesson{
		ID:       "L001",
		Velocity: 1.0, // Above 0.5 threshold
		Uses:     5,
	}

	DecayLesson(lesson)

	// High velocity should not decrement uses
	if lesson.Uses != 5 {
		t.Errorf("expected uses 5 (no decrement), got %d", lesson.Uses)
	}
}

func TestNeedsDecay_NoStateFile(t *testing.T) {
	tmpDir := t.TempDir()
	stateFile := filepath.Join(tmpDir, "decay_state.json")

	config := DecayConfig{
		StateFile:     stateFile,
		DecayInterval: 7 * 24 * time.Hour,
	}

	// No state file exists - should return true (first run)
	if !NeedsDecay(config) {
		t.Error("expected NeedsDecay to return true when no state file exists")
	}
}

func TestNeedsDecay_RecentDecay(t *testing.T) {
	tmpDir := t.TempDir()
	stateFile := filepath.Join(tmpDir, "decay_state.json")

	// Write recent decay state
	state := DecayState{
		LastDecay: time.Now().Add(-1 * time.Hour), // 1 hour ago
	}
	data, _ := json.Marshal(state)
	os.WriteFile(stateFile, data, 0644)

	config := DecayConfig{
		StateFile:     stateFile,
		DecayInterval: 7 * 24 * time.Hour, // 7 days
	}

	// Recent decay - should return false
	if NeedsDecay(config) {
		t.Error("expected NeedsDecay to return false when decay was recent")
	}
}

func TestNeedsDecay_OldDecay(t *testing.T) {
	tmpDir := t.TempDir()
	stateFile := filepath.Join(tmpDir, "decay_state.json")

	// Write old decay state
	state := DecayState{
		LastDecay: time.Now().Add(-8 * 24 * time.Hour), // 8 days ago
	}
	data, _ := json.Marshal(state)
	os.WriteFile(stateFile, data, 0644)

	config := DecayConfig{
		StateFile:     stateFile,
		DecayInterval: 7 * 24 * time.Hour, // 7 days
	}

	// Old decay - should return true
	if !NeedsDecay(config) {
		t.Error("expected NeedsDecay to return true when decay interval has passed")
	}
}

func TestDecay_SkipsIfRecent(t *testing.T) {
	tmpDir := t.TempDir()
	projectPath := filepath.Join(tmpDir, "project", "LESSONS.md")
	systemPath := filepath.Join(tmpDir, "system", "LESSONS.md")
	stateFile := filepath.Join(tmpDir, "decay_state.json")

	// Create project directory and lessons file
	os.MkdirAll(filepath.Dir(projectPath), 0755)
	os.WriteFile(projectPath, []byte(`# LESSONS.md - Project Level

## Active Lessons

### [L001] [*****|*****] Test Lesson
- **Uses**: 100 | **Velocity**: 4.0 | **Learned**: 2024-01-01 | **Last**: 2024-01-15 | **Category**: pattern
> Test content
`), 0644)

	// Write recent decay state
	state := DecayState{
		LastDecay: time.Now().Add(-1 * time.Hour), // 1 hour ago
	}
	data, _ := json.Marshal(state)
	os.WriteFile(stateFile, data, 0644)

	store := NewStore(projectPath, systemPath)
	config := DecayConfig{
		StateFile:     stateFile,
		DecayInterval: 7 * 24 * time.Hour,
	}

	count, err := Decay(store, config)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	// Should skip decay and return 0
	if count != 0 {
		t.Errorf("expected 0 lessons decayed (skipped), got %d", count)
	}
}

func TestForceDecay_AlwaysRuns(t *testing.T) {
	tmpDir := t.TempDir()
	projectPath := filepath.Join(tmpDir, "project", "LESSONS.md")
	systemPath := filepath.Join(tmpDir, "system", "LESSONS.md")

	// Create project directory and lessons file with high velocity
	os.MkdirAll(filepath.Dir(projectPath), 0755)
	os.WriteFile(projectPath, []byte(`# LESSONS.md - Project Level

## Active Lessons

### [L001] [*****|*****] Test Lesson
- **Uses**: 100 | **Velocity**: 4.0 | **Learned**: 2024-01-01 | **Last**: 2024-01-15 | **Category**: pattern
> Test content
`), 0644)

	store := NewStore(projectPath, systemPath)

	count, err := ForceDecay(store)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	// Should decay 1 lesson
	if count != 1 {
		t.Errorf("expected 1 lesson decayed, got %d", count)
	}

	// Verify velocity was halved
	lessons, err := store.List()
	if err != nil {
		t.Fatalf("failed to list lessons: %v", err)
	}

	if len(lessons) != 1 {
		t.Fatalf("expected 1 lesson, got %d", len(lessons))
	}

	if lessons[0].Velocity != 2.0 {
		t.Errorf("expected velocity 2.0, got %f", lessons[0].Velocity)
	}
}

func TestDecay_UpdatesStateFile(t *testing.T) {
	tmpDir := t.TempDir()
	projectPath := filepath.Join(tmpDir, "project", "LESSONS.md")
	systemPath := filepath.Join(tmpDir, "system", "LESSONS.md")
	stateFile := filepath.Join(tmpDir, "decay_state.json")

	// Create project directory and lessons file
	os.MkdirAll(filepath.Dir(projectPath), 0755)
	os.WriteFile(projectPath, []byte(`# LESSONS.md - Project Level

## Active Lessons

### [L001] [*****|****-] Test Lesson
- **Uses**: 100 | **Velocity**: 2.0 | **Learned**: 2024-01-01 | **Last**: 2024-01-15 | **Category**: pattern
> Test content
`), 0644)

	store := NewStore(projectPath, systemPath)
	config := DecayConfig{
		StateFile:     stateFile,
		DecayInterval: 7 * 24 * time.Hour,
	}

	before := time.Now()
	_, err := Decay(store, config)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	after := time.Now()

	// Read state file
	data, err := os.ReadFile(stateFile)
	if err != nil {
		t.Fatalf("failed to read state file: %v", err)
	}

	var state DecayState
	if err := json.Unmarshal(data, &state); err != nil {
		t.Fatalf("failed to parse state file: %v", err)
	}

	// Verify last decay time was updated
	if state.LastDecay.Before(before) || state.LastDecay.After(after) {
		t.Errorf("expected last decay time between %v and %v, got %v", before, after, state.LastDecay)
	}
}

func TestDecay_DecaysAllLessons(t *testing.T) {
	tmpDir := t.TempDir()
	projectPath := filepath.Join(tmpDir, "project", "LESSONS.md")
	systemPath := filepath.Join(tmpDir, "system", "LESSONS.md")

	// Create project and system directories
	os.MkdirAll(filepath.Dir(projectPath), 0755)
	os.MkdirAll(filepath.Dir(systemPath), 0755)

	// Create project lessons
	os.WriteFile(projectPath, []byte(`# LESSONS.md - Project Level

## Active Lessons

### [L001] [*****|*****] First
- **Uses**: 100 | **Velocity**: 4.0 | **Learned**: 2024-01-01 | **Last**: 2024-01-15 | **Category**: pattern
> Content 1

### [L002] [*****|****-] Second
- **Uses**: 100 | **Velocity**: 2.0 | **Learned**: 2024-01-01 | **Last**: 2024-01-15 | **Category**: pattern
> Content 2
`), 0644)

	// Create system lessons
	os.WriteFile(systemPath, []byte(`# LESSONS.md - System Level

## Active Lessons

### [S001] [*****|***--] System Lesson
- **Uses**: 100 | **Velocity**: 1.0 | **Learned**: 2024-01-01 | **Last**: 2024-01-15 | **Category**: pattern
> System content
`), 0644)

	store := NewStore(projectPath, systemPath)

	count, err := ForceDecay(store)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	// Should decay 3 lessons
	if count != 3 {
		t.Errorf("expected 3 lessons decayed, got %d", count)
	}

	// Verify all velocities were halved
	lessons, _ := store.List()
	expected := map[string]float64{
		"L001": 2.0,
		"L002": 1.0,
		"S001": 0.5,
	}

	for _, l := range lessons {
		if exp, ok := expected[l.ID]; ok {
			if l.Velocity != exp {
				t.Errorf("lesson %s: expected velocity %f, got %f", l.ID, exp, l.Velocity)
			}
		}
	}
}
