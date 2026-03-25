// SPDX-License-Identifier: GPL-3.0-or-later
package eventlog

import (
	"testing"
	"time"
)

func TestPrecisionByLesson(t *testing.T) {
	now := time.Now()
	events := []Event{
		{Timestamp: now, Type: "injection", Session: "s1", Lesson: "L001", Score: 800, Query: "build error"},
		{Timestamp: now, Type: "injection", Session: "s2", Lesson: "L001", Score: 750, Query: "compile fail"},
		{Timestamp: now, Type: "injection", Session: "s3", Lesson: "L002", Score: 600, Query: "deploy issue"},
		{Timestamp: now, Type: "citation", Session: "s1", Lesson: "L001"},
		{Timestamp: now, Type: "dismissal", Session: "s3", Lesson: "L002"},
	}

	result := PrecisionByLesson(events)

	// L001: 1 citation / (2 injections + 0 dismissals) = 0.5
	lp1, ok := result["L001"]
	if !ok {
		t.Fatal("expected L001 in result")
	}
	if lp1.Injections != 2 {
		t.Errorf("L001 injections = %d, want 2", lp1.Injections)
	}
	if lp1.Citations != 1 {
		t.Errorf("L001 citations = %d, want 1", lp1.Citations)
	}
	if lp1.Dismissals != 0 {
		t.Errorf("L001 dismissals = %d, want 0", lp1.Dismissals)
	}
	if p := lp1.Precision(); p != 0.5 {
		t.Errorf("L001 precision = %f, want 0.5", p)
	}

	// L002: 0 citations / (1 injection + 1 dismissal) = 0.0
	lp2, ok := result["L002"]
	if !ok {
		t.Fatal("expected L002 in result")
	}
	if lp2.Injections != 1 {
		t.Errorf("L002 injections = %d, want 1", lp2.Injections)
	}
	if lp2.Dismissals != 1 {
		t.Errorf("L002 dismissals = %d, want 1", lp2.Dismissals)
	}
	if p := lp2.Precision(); p != 0.0 {
		t.Errorf("L002 precision = %f, want 0.0", p)
	}
}

func TestPrecisionByLesson_Empty(t *testing.T) {
	result := PrecisionByLesson(nil)
	if len(result) != 0 {
		t.Errorf("expected empty map, got %d entries", len(result))
	}
}

func TestLessonPrecision_NoInjections(t *testing.T) {
	lp := &LessonPrecision{}
	if p := lp.Precision(); p != 0.0 {
		t.Errorf("precision = %f, want 0.0", p)
	}
}

func TestPrecisionByLesson_QueryCited(t *testing.T) {
	now := time.Now()
	events := []Event{
		{Timestamp: now, Type: "injection", Session: "s1", Lesson: "L001", Score: 900, Query: "test query"},
		{Timestamp: now, Type: "citation", Session: "s1", Lesson: "L001"},
	}

	result := PrecisionByLesson(events)
	lp, ok := result["L001"]
	if !ok {
		t.Fatal("expected L001 in result")
	}
	if len(lp.Queries) != 1 {
		t.Fatalf("expected 1 query hit, got %d", len(lp.Queries))
	}
	qh := lp.Queries[0]
	if qh.Query != "test query" {
		t.Errorf("query = %q, want 'test query'", qh.Query)
	}
	if qh.Score != 900 {
		t.Errorf("score = %d, want 900", qh.Score)
	}
	if !qh.Cited {
		t.Error("expected QueryHit.Cited to be true")
	}
}
