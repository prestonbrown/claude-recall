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
