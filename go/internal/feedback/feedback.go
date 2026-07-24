// Package feedback tracks injection and citation counts per lesson
// to support precision penalty calculations.
package feedback

import (
	"encoding/json"
	"os"
	"path/filepath"
)

// LessonStats holds injection and citation counts for a single lesson.
type LessonStats struct {
	Injections int `json:"injections"`
	Citations  int `json:"citations"`
}

// ReadStats reads the injection-stats JSON file at path.
// Returns an empty map (not an error) when the file does not exist.
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
		// Corrupted file: return empty map rather than an error.
		return make(map[string]LessonStats), nil
	}
	return stats, nil
}

// writeStats persists stats to path atomically via a temp-file rename.
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

// IncrementInjection increments the injection count for lessonID in the stats file at path.
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

// IncrementCitation increments the citation count for lessonID in the stats file at path.
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

// ShouldPenalize returns true when a lesson has been injected at least minInjections
// times and its citation ratio (citations/injections) is strictly below maxCiteRatio.
// Returns false for unknown lessons or lessons below the injection threshold.
func ShouldPenalize(stats map[string]LessonStats, lessonID string, minInjections int, maxCiteRatio float64) bool {
	s, ok := stats[lessonID]
	if !ok || s.Injections < minInjections {
		return false
	}
	ratio := float64(s.Citations) / float64(s.Injections)
	return ratio < maxCiteRatio
}

// Trust returns a smoothed precision estimate in [0,1] for a lesson:
// (Citations + alpha) / (Injections + alpha + beta). With alpha=beta=1 and zero
// stats it yields the neutral prior 0.5. It is monotonically increasing in
// citations and decreasing in (uncited) injections. A degenerate prior mass
// (alpha+beta <= 0) returns the neutral 0.5 rather than dividing by zero.
func Trust(stats LessonStats, alpha, beta float64) float64 {
	if alpha+beta <= 0 {
		return 0.5
	}
	return (float64(stats.Citations) + alpha) / (float64(stats.Injections) + alpha + beta)
}

// TrustMultiplier maps a lesson's stats to a penalty-only ranking multiplier in
// [floor, 1.0]. Below minInjections it returns 1.0 (a true no-op: gather evidence
// first, robust to silent-application label noise and cold start). At or above the
// gate it returns clamp(Trust(stats)/prior, floor, 1.0) where prior = alpha/(alpha+beta)
// (0.5 by default). The result is capped at 1.0 — promotion stays on the existing
// uses/velocity axis; trust only suppresses chronically-uncited lessons.
func TrustMultiplier(stats LessonStats, alpha, beta, floor float64, minInjections int) float64 {
	if stats.Injections < minInjections {
		return 1.0
	}
	if alpha+beta <= 0 {
		return 1.0
	}
	prior := alpha / (alpha + beta)
	m := Trust(stats, alpha, beta) / prior
	if m < floor {
		return floor
	}
	if m > 1.0 {
		return 1.0
	}
	return m
}

// ResetLesson removes lessonID from the stats file, clearing its counters.
func ResetLesson(path, lessonID string) error {
	stats, err := ReadStats(path)
	if err != nil {
		return err
	}
	delete(stats, lessonID)
	return writeStats(path, stats)
}

// StatsFilePath returns the canonical path for the injection-stats file within dir.
func StatsFilePath(dir string) string {
	return filepath.Join(dir, "injection-stats.json")
}
