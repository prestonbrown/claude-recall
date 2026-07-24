package feedback

import (
	"math"
	"path/filepath"
	"testing"
)

const eps = 1e-9

func TestTrust_ZeroStatsNeutralPrior(t *testing.T) {
	got := Trust(LessonStats{Injections: 0, Citations: 0}, 1, 1)
	if math.Abs(got-0.5) > eps {
		t.Errorf("expected neutral prior 0.5 for zero stats, got %g", got)
	}
}

func TestTrust_ExactValues(t *testing.T) {
	cases := []struct {
		c, i int
		want float64
	}{
		{c: 0, i: 2, want: 0.25},              // (0+1)/(2+2)
		{c: 1, i: 1, want: 2.0 / 3.0},         // (1+1)/(1+2)
		{c: 3, i: 10, want: 4.0 / 12.0},       // (3+1)/(10+2)
	}
	for _, tc := range cases {
		got := Trust(LessonStats{Injections: tc.i, Citations: tc.c}, 1, 1)
		if math.Abs(got-tc.want) > eps {
			t.Errorf("Trust(C=%d,I=%d)=%g, want %g", tc.c, tc.i, got, tc.want)
		}
	}
}

func TestTrust_MonotonicInCitations(t *testing.T) {
	prev := Trust(LessonStats{Injections: 10, Citations: 0}, 1, 1)
	for c := 1; c <= 10; c++ {
		cur := Trust(LessonStats{Injections: 10, Citations: c}, 1, 1)
		if cur <= prev {
			t.Errorf("Trust not increasing in citations at C=%d: %g <= %g", c, cur, prev)
		}
		prev = cur
	}
}

func TestTrust_MonotonicDecreasingInInjections(t *testing.T) {
	// Holding citations fixed, more uncited injections must lower trust.
	prev := Trust(LessonStats{Injections: 2, Citations: 1}, 1, 1)
	for i := 3; i <= 20; i++ {
		cur := Trust(LessonStats{Injections: i, Citations: 1}, 1, 1)
		if cur >= prev {
			t.Errorf("Trust not decreasing in injections at I=%d: %g >= %g", i, cur, prev)
		}
		prev = cur
	}
}

func TestTrust_GuardNonPositivePriorMass(t *testing.T) {
	// alpha+beta <= 0 is degenerate; must not divide-by-zero or NaN — returns neutral 0.5.
	got := Trust(LessonStats{Injections: 5, Citations: 1}, 0, 0)
	if math.Abs(got-0.5) > eps {
		t.Errorf("expected 0.5 for degenerate alpha+beta<=0, got %g", got)
	}
}

func TestTrustMultiplier_BelowGateIsNoOp(t *testing.T) {
	// Below trustMinInjections, multiplier is always 1.0 regardless of cite ratio.
	for _, c := range []int{0, 1, 2} {
		m := TrustMultiplier(LessonStats{Injections: 2, Citations: c}, 1, 1, 0.2, 3)
		if math.Abs(m-1.0) > eps {
			t.Errorf("below-gate multiplier should be 1.0, got %g (C=%d)", m, c)
		}
	}
}

func TestTrustMultiplier_ClampsToFloor(t *testing.T) {
	// Large injection count, zero citations, past the gate -> clamps to floor.
	m := TrustMultiplier(LessonStats{Injections: 100, Citations: 0}, 1, 1, 0.2, 3)
	if math.Abs(m-0.2) > eps {
		t.Errorf("chronically-uncited past gate should clamp to floor 0.2, got %g", m)
	}
}

func TestTrustMultiplier_NeverBoostsAboveOne(t *testing.T) {
	// High cite ratio would push Trust/prior above 1; penalty-only caps at 1.0.
	m := TrustMultiplier(LessonStats{Injections: 10, Citations: 10}, 1, 1, 0.2, 3)
	if math.Abs(m-1.0) > eps {
		t.Errorf("high-cite lesson should cap at 1.0, got %g", m)
	}
}

func TestTrustMultiplier_MidGraduated(t *testing.T) {
	// I=10, C=1: Trust=(1+1)/(10+2)=1/6; prior=0.5; m=(1/6)/0.5=1/3, within [floor,1].
	m := TrustMultiplier(LessonStats{Injections: 10, Citations: 1}, 1, 1, 0.2, 3)
	want := (2.0 / 12.0) / 0.5
	if math.Abs(m-want) > eps {
		t.Errorf("mid case multiplier=%g, want %g", m, want)
	}
}

func TestTrustMultiplier_AtGateBoundary(t *testing.T) {
	// Injections exactly == minInjections is at/above the gate (not below), so it applies.
	m := TrustMultiplier(LessonStats{Injections: 3, Citations: 0}, 1, 1, 0.2, 3)
	// Trust=(0+1)/(3+2)=0.2; m=0.2/0.5=0.4; within range.
	if math.Abs(m-0.4) > eps {
		t.Errorf("at-gate multiplier=%g, want 0.4", m)
	}
}

func TestTrustMultiplier_UnknownLessonZeroStatsNoOp(t *testing.T) {
	// A zeroed LessonStats (unknown lesson) is below the gate -> 1.0 no-op.
	m := TrustMultiplier(LessonStats{}, 1, 1, 0.2, 3)
	if math.Abs(m-1.0) > eps {
		t.Errorf("unknown/zero-stats lesson should be a 1.0 no-op, got %g", m)
	}
}

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
