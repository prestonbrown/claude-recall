// SPDX-License-Identifier: GPL-3.0-or-later
package eventlog

import (
	"path/filepath"
	"testing"
	"time"
)

func TestFullFlow_InjectCiteStatsPrecision(t *testing.T) {
	dir := t.TempDir()
	logPath := filepath.Join(dir, "session-log.jsonl")
	log := New(logPath)
	now := time.Now()

	// Simulate a session: 4 injections, 2 citations, 1 dismiss
	log.Append(Event{Timestamp: now, Type: "session_start", Session: "s1", Lessons: []string{"L001", "L002", "L003", "L004"}})
	log.Append(Event{Timestamp: now, Type: "injection", Session: "s1", Lesson: "L001", Score: 9, Query: "safe_delete usage", Hook: "prompt_submit"})
	log.Append(Event{Timestamp: now, Type: "injection", Session: "s1", Lesson: "L002", Score: 7, Query: "safe_delete usage", Hook: "prompt_submit"})
	log.Append(Event{Timestamp: now, Type: "injection", Session: "s1", Lesson: "L003", Score: 6, Query: "improve lessons", Hook: "prompt_submit"})
	log.Append(Event{Timestamp: now, Type: "injection", Session: "s1", Lesson: "L004", Score: 5, Query: "improve lessons", Hook: "prompt_submit"})
	log.Append(Event{Timestamp: now, Type: "citation", Session: "s1", Lesson: "L001"})
	log.Append(Event{Timestamp: now, Type: "citation", Session: "s1", Lesson: "L002"})
	log.Append(Event{Timestamp: now, Type: "dismiss", Session: "s1", Lesson: "L003"})

	// Read all
	events, err := log.Read()
	if err != nil {
		t.Fatalf("Read failed: %v", err)
	}
	if len(events) != 8 {
		t.Fatalf("expected 8 events, got %d", len(events))
	}

	// Filter by session
	sessionEvents, err := log.ReadFiltered(Filter{Session: "s1"})
	if err != nil {
		t.Fatalf("ReadFiltered failed: %v", err)
	}
	if len(sessionEvents) != 8 {
		t.Errorf("expected 8 session events, got %d", len(sessionEvents))
	}

	// Precision
	precision := PrecisionByLesson(events)

	// L001: 1 cit / 1 inj = 100%
	if p := precision["L001"]; p == nil || p.Precision() != 1.0 {
		t.Errorf("L001: expected 100%% precision")
	}

	// L002: 1 cit / 1 inj = 100%
	if p := precision["L002"]; p == nil || p.Precision() != 1.0 {
		t.Errorf("L002: expected 100%% precision")
	}

	// L003: 0 cit / (1 inj + 1 dismiss) = 0%
	if p := precision["L003"]; p == nil || p.Precision() != 0.0 || p.Dismissals != 1 {
		t.Errorf("L003: expected 0%% with 1 dismiss, got %+v", precision["L003"])
	}

	// L004: 0 cit / 1 inj = 0%
	if p := precision["L004"]; p == nil || p.Precision() != 0.0 {
		t.Errorf("L004: expected 0%% precision")
	}

	// Verify query tracking
	if p := precision["L001"]; p != nil && len(p.Queries) > 0 {
		if p.Queries[0].Query != "safe_delete usage" {
			t.Errorf("expected query 'safe_delete usage', got '%s'", p.Queries[0].Query)
		}
	}
}
