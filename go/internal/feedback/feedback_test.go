package feedback

import (
	"path/filepath"
	"testing"
)

func TestRead_MissingFile(t *testing.T) {
	stats, err := ReadStats("/nonexistent/injection-stats.json")
	if err != nil {
		t.Fatal(err)
	}
	if len(stats) != 0 {
		t.Errorf("expected empty stats for missing file, got %d", len(stats))
	}
}

func TestIncrementInjection(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "injection-stats.json")
	err := IncrementInjection(path, "L001")
	if err != nil {
		t.Fatal(err)
	}
	err = IncrementInjection(path, "L001")
	if err != nil {
		t.Fatal(err)
	}
	stats, err := ReadStats(path)
	if err != nil {
		t.Fatal(err)
	}
	if stats["L001"].Injections != 2 {
		t.Errorf("expected 2 injections, got %d", stats["L001"].Injections)
	}
	if stats["L001"].Citations != 0 {
		t.Errorf("expected 0 citations, got %d", stats["L001"].Citations)
	}
}

func TestIncrementCitation(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "injection-stats.json")
	IncrementInjection(path, "L001")
	IncrementInjection(path, "L001")
	err := IncrementCitation(path, "L001")
	if err != nil {
		t.Fatal(err)
	}
	stats, _ := ReadStats(path)
	if stats["L001"].Citations != 1 {
		t.Errorf("expected 1 citation, got %d", stats["L001"].Citations)
	}
}

func TestShouldPenalize_BelowThreshold(t *testing.T) {
	stats := map[string]LessonStats{
		"L001": {Injections: 3, Citations: 0},
	}
	if ShouldPenalize(stats, "L001", 5, 0.2) {
		t.Error("should not penalize with only 3 injections (threshold 5)")
	}
}

func TestShouldPenalize_AboveThresholdNoCitations(t *testing.T) {
	stats := map[string]LessonStats{
		"L001": {Injections: 7, Citations: 0},
	}
	if !ShouldPenalize(stats, "L001", 5, 0.2) {
		t.Error("should penalize: 7 injections, 0 citations")
	}
}

func TestShouldPenalize_AboveThresholdGoodRatio(t *testing.T) {
	stats := map[string]LessonStats{
		"L001": {Injections: 10, Citations: 5},
	}
	if ShouldPenalize(stats, "L001", 5, 0.2) {
		t.Error("should not penalize: ratio 0.5 > 0.2")
	}
}

func TestShouldPenalize_ExactThreshold(t *testing.T) {
	stats := map[string]LessonStats{
		"L001": {Injections: 5, Citations: 1},
	}
	if ShouldPenalize(stats, "L001", 5, 0.2) {
		t.Error("should not penalize at exact threshold (0.2 is not < 0.2)")
	}
}

func TestShouldPenalize_UnknownLesson(t *testing.T) {
	stats := map[string]LessonStats{}
	if ShouldPenalize(stats, "L999", 5, 0.2) {
		t.Error("should not penalize unknown lesson")
	}
}

func TestResetLesson(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "injection-stats.json")
	IncrementInjection(path, "L001")
	IncrementInjection(path, "L001")
	IncrementInjection(path, "L001")
	err := ResetLesson(path, "L001")
	if err != nil {
		t.Fatal(err)
	}
	stats, _ := ReadStats(path)
	if _, exists := stats["L001"]; exists {
		t.Error("expected L001 to be removed after reset")
	}
}
