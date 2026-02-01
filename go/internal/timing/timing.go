package timing

import (
	"sync"
	"time"
)

// Timer tracks elapsed time and named phases
type Timer struct {
	start       time.Time
	phaseStarts map[string]time.Time
	phases      map[string]int64
	mu          sync.Mutex
}

// New creates a new Timer with the current time as the start point
func New() *Timer {
	return &Timer{
		start:       time.Now(),
		phaseStarts: make(map[string]time.Time),
		phases:      make(map[string]int64),
	}
}

// ElapsedMs returns the number of milliseconds since the timer was created
func (t *Timer) ElapsedMs() int64 {
	return time.Since(t.start).Milliseconds()
}

// StartPhase begins timing a named phase
func (t *Timer) StartPhase(name string) {
	t.mu.Lock()
	defer t.mu.Unlock()
	t.phaseStarts[name] = time.Now()
}

// EndPhase ends a named phase and returns its duration in milliseconds
func (t *Timer) EndPhase(name string) int64 {
	t.mu.Lock()
	defer t.mu.Unlock()

	start, ok := t.phaseStarts[name]
	if !ok {
		return 0
	}

	duration := time.Since(start).Milliseconds()
	t.phases[name] = duration
	delete(t.phaseStarts, name)
	return duration
}

// Phases returns a copy of all recorded phase durations
func (t *Timer) Phases() map[string]int64 {
	t.mu.Lock()
	defer t.mu.Unlock()

	result := make(map[string]int64, len(t.phases))
	for k, v := range t.phases {
		result[k] = v
	}
	return result
}
