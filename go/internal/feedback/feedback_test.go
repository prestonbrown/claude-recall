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

func TestPrecisionFlow_FeedbackPenalty(t *testing.T) {
	dir := t.TempDir()
	statsPath := filepath.Join(dir, "injection-stats.json")

	// Simulate 7 injections with 0 citations for L008
	for i := 0; i < 7; i++ {
		IncrementInjection(statsPath, "L008")
	}

	stats, _ := ReadStats(statsPath)

	// Should be penalized (7 injections, 0 citations, ratio 0.0 < 0.2)
	if !ShouldPenalize(stats, "L008", 5, 0.2) {
		t.Error("L008 should be penalized: 7 injections, 0 citations")
	}

	// Simulate 2 citations — ratio becomes 2/7 ≈ 0.29 > 0.2
	IncrementCitation(statsPath, "L008")
	IncrementCitation(statsPath, "L008")

	stats, _ = ReadStats(statsPath)
	if ShouldPenalize(stats, "L008", 5, 0.2) {
		t.Error("L008 should NOT be penalized after citations: ratio 0.29 > 0.2")
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
