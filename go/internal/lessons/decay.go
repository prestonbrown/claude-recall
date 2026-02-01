package lessons

import (
	"encoding/json"
	"os"
	"path/filepath"
	"time"

	"github.com/pbrown/claude-recall/internal/lock"
	"github.com/pbrown/claude-recall/internal/models"
)

// DecayConfig configures decay behavior
type DecayConfig struct {
	StateFile     string        // Path to state file
	DecayInterval time.Duration // Time between decays (e.g., 7 days)
}

// DecayState tracks when decay was last run
type DecayState struct {
	LastDecay time.Time `json:"last_decay"`
}

// Decay applies decay logic to lessons if interval has passed
// Returns number of lessons decayed, or 0 if decay was skipped
func Decay(store *Store, config DecayConfig) (int, error) {
	if !NeedsDecay(config) {
		return 0, nil
	}

	count, err := ForceDecay(store)
	if err != nil {
		return 0, err
	}

	// Update state file
	if err := saveDecayState(config.StateFile); err != nil {
		return count, err
	}

	return count, nil
}

// ForceDecay applies decay logic regardless of interval
func ForceDecay(store *Store) (int, error) {
	count := 0

	// Decay project lessons
	projectCount, err := decayLessonsInFile(store.projectPath, "project")
	if err != nil {
		return 0, err
	}
	count += projectCount

	// Decay system lessons
	systemCount, err := decayLessonsInFile(store.systemPath, "system")
	if err != nil {
		return 0, err
	}
	count += systemCount

	return count, nil
}

// decayLessonsInFile applies decay to all lessons in a file
func decayLessonsInFile(path, level string) (int, error) {
	// Check if file exists
	if _, err := os.Stat(path); os.IsNotExist(err) {
		return 0, nil
	}

	// Acquire lock
	lockPath := path + ".lock"
	fl, err := lock.Acquire(lockPath)
	if err != nil {
		return 0, err
	}
	defer fl.Release()

	// Parse lessons
	lessons, err := ParseFile(path)
	if err != nil {
		return 0, err
	}

	// Apply decay to each lesson
	for _, l := range lessons {
		DecayLesson(l)
	}

	// Write back
	content := Serialize(lessons, level)
	if err := os.WriteFile(path, []byte(content), 0644); err != nil {
		return 0, err
	}

	return len(lessons), nil
}

// DecayLesson applies decay to a single lesson (modifies in place)
func DecayLesson(l *models.Lesson) {
	// Decay velocity by 50%
	l.Velocity *= models.VelocityDecayFactor

	// Floor velocity to zero if below epsilon
	if l.Velocity < models.VelocityEpsilon {
		l.Velocity = 0.0
	}

	// Decrement uses for low-velocity lessons
	if l.Velocity < 0.5 && l.Uses > 1 {
		l.Uses--
	}
}

// NeedsDecay checks if decay should run based on state file
func NeedsDecay(config DecayConfig) bool {
	state, err := loadDecayState(config.StateFile)
	if err != nil {
		// No state file or error reading - assume decay is needed
		return true
	}

	// Check if enough time has passed
	elapsed := time.Since(state.LastDecay)
	return elapsed >= config.DecayInterval
}

// loadDecayState reads the decay state from file
func loadDecayState(path string) (*DecayState, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}

	var state DecayState
	if err := json.Unmarshal(data, &state); err != nil {
		return nil, err
	}

	return &state, nil
}

// saveDecayState writes the decay state to file
func saveDecayState(path string) error {
	// Ensure directory exists
	dir := filepath.Dir(path)
	if err := os.MkdirAll(dir, 0755); err != nil {
		return err
	}

	state := DecayState{
		LastDecay: time.Now(),
	}

	data, err := json.Marshal(state)
	if err != nil {
		return err
	}

	return os.WriteFile(path, data, 0644)
}
