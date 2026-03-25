// SPDX-License-Identifier: GPL-3.0-or-later
package eventlog

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestAppend_WritesJSONLLine(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "events.jsonl")
	log := New(path)

	ev := Event{
		Timestamp: time.Date(2026, 3, 25, 12, 0, 0, 0, time.UTC),
		Type:      "citation",
		Session:   "sess-001",
		Lesson:    "L042",
	}
	if err := log.Append(ev); err != nil {
		t.Fatalf("Append failed: %v", err)
	}

	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("ReadFile failed: %v", err)
	}
	line := string(data)

	for _, want := range []string{`"type":"citation"`, `"session":"sess-001"`, `"lesson":"L042"`, `"ts":"`} {
		if !strings.Contains(line, want) {
			t.Errorf("JSONL line missing %q:\n%s", want, line)
		}
	}
	if !strings.HasSuffix(strings.TrimSpace(line), "}") {
		t.Errorf("expected line to end with }, got: %s", line)
	}
}

func TestAppend_AppendsMultipleLines(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "events.jsonl")
	log := New(path)

	for i := 0; i < 3; i++ {
		ev := Event{
			Timestamp: time.Now(),
			Type:      "injection",
			Session:   "sess-002",
			Lesson:    "L001",
		}
		if err := log.Append(ev); err != nil {
			t.Fatalf("Append %d failed: %v", i, err)
		}
	}

	events, err := log.Read()
	if err != nil {
		t.Fatalf("Read failed: %v", err)
	}
	if len(events) != 3 {
		t.Fatalf("expected 3 events, got %d", len(events))
	}
}

func TestAppend_InjectionWithAllFields(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "events.jsonl")
	log := New(path)

	ev := Event{
		Timestamp: time.Date(2026, 3, 25, 14, 30, 0, 0, time.UTC),
		Type:      "injection",
		Session:   "sess-003",
		Lesson:    "L099",
		Score:     1250,
		Query:     "how to fix build",
		Hook:      "prompt_submit",
		Project:   "helixscreen",
	}
	if err := log.Append(ev); err != nil {
		t.Fatalf("Append failed: %v", err)
	}

	events, err := log.Read()
	if err != nil {
		t.Fatalf("Read failed: %v", err)
	}
	if len(events) != 1 {
		t.Fatalf("expected 1 event, got %d", len(events))
	}

	got := events[0]
	if got.Type != "injection" {
		t.Errorf("Type = %q, want injection", got.Type)
	}
	if got.Session != "sess-003" {
		t.Errorf("Session = %q, want sess-003", got.Session)
	}
	if got.Lesson != "L099" {
		t.Errorf("Lesson = %q, want L099", got.Lesson)
	}
	if got.Score != 1250 {
		t.Errorf("Score = %d, want 1250", got.Score)
	}
	if got.Query != "how to fix build" {
		t.Errorf("Query = %q, want 'how to fix build'", got.Query)
	}
	if got.Hook != "prompt_submit" {
		t.Errorf("Hook = %q, want prompt_submit", got.Hook)
	}
	if got.Project != "helixscreen" {
		t.Errorf("Project = %q, want helixscreen", got.Project)
	}
	if !got.Timestamp.Equal(ev.Timestamp) {
		t.Errorf("Timestamp = %v, want %v", got.Timestamp, ev.Timestamp)
	}
}

func TestRead_EmptyFile(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "events.jsonl")
	if err := os.WriteFile(path, []byte{}, 0644); err != nil {
		t.Fatal(err)
	}

	log := New(path)
	events, err := log.Read()
	if err != nil {
		t.Fatalf("Read returned error: %v", err)
	}
	if events != nil {
		t.Fatalf("expected nil, got %v", events)
	}
}

func TestRead_MissingFile(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "nonexistent.jsonl")

	log := New(path)
	events, err := log.Read()
	if err != nil {
		t.Fatalf("Read returned error for missing file: %v", err)
	}
	if events != nil {
		t.Fatalf("expected nil, got %v", events)
	}
}

func TestReadBySession(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "events.jsonl")
	log := New(path)

	for _, s := range []string{"sess-A", "sess-B", "sess-A"} {
		if err := log.Append(Event{
			Timestamp: time.Now(),
			Type:      "citation",
			Session:   s,
			Lesson:    "L001",
		}); err != nil {
			t.Fatalf("Append failed: %v", err)
		}
	}

	events, err := log.ReadFiltered(Filter{Session: "sess-A"})
	if err != nil {
		t.Fatalf("ReadFiltered failed: %v", err)
	}
	if len(events) != 2 {
		t.Fatalf("expected 2 events, got %d", len(events))
	}
	for _, ev := range events {
		if ev.Session != "sess-A" {
			t.Errorf("expected session sess-A, got %q", ev.Session)
		}
	}
}

func TestReadByLesson(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "events.jsonl")
	log := New(path)

	for _, l := range []string{"L010", "L020", "L010"} {
		if err := log.Append(Event{
			Timestamp: time.Now(),
			Type:      "citation",
			Session:   "sess-X",
			Lesson:    l,
		}); err != nil {
			t.Fatalf("Append failed: %v", err)
		}
	}

	events, err := log.ReadFiltered(Filter{Lesson: "L020"})
	if err != nil {
		t.Fatalf("ReadFiltered failed: %v", err)
	}
	if len(events) != 1 {
		t.Fatalf("expected 1 event, got %d", len(events))
	}
	if events[0].Lesson != "L020" {
		t.Errorf("expected lesson L020, got %q", events[0].Lesson)
	}
}

func TestReadBySince(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "events.jsonl")
	log := New(path)

	old := time.Date(2025, 1, 1, 0, 0, 0, 0, time.UTC)
	recent := time.Date(2026, 3, 20, 0, 0, 0, 0, time.UTC)

	for _, ts := range []time.Time{old, recent} {
		if err := log.Append(Event{
			Timestamp: ts,
			Type:      "injection",
			Session:   "sess-T",
		}); err != nil {
			t.Fatalf("Append failed: %v", err)
		}
	}

	cutoff := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)
	events, err := log.ReadFiltered(Filter{Since: cutoff})
	if err != nil {
		t.Fatalf("ReadFiltered failed: %v", err)
	}
	if len(events) != 1 {
		t.Fatalf("expected 1 event, got %d", len(events))
	}
	if !events[0].Timestamp.Equal(recent) {
		t.Errorf("expected recent timestamp, got %v", events[0].Timestamp)
	}
}

func TestPrune_RemovesOldEntries(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "events.jsonl")
	log := New(path)

	now := time.Now()
	oldTS := now.AddDate(0, 0, -100)
	recentTS := now.AddDate(0, 0, -10)

	for _, ts := range []time.Time{oldTS, oldTS, recentTS} {
		if err := log.Append(Event{
			Timestamp: ts,
			Type:      "citation",
			Session:   "sess-P",
			Lesson:    "L001",
		}); err != nil {
			t.Fatalf("Append failed: %v", err)
		}
	}

	pruned, err := log.Prune(90)
	if err != nil {
		t.Fatalf("Prune failed: %v", err)
	}
	if pruned != 2 {
		t.Fatalf("expected 2 pruned, got %d", pruned)
	}

	events, err := log.Read()
	if err != nil {
		t.Fatalf("Read after prune failed: %v", err)
	}
	if len(events) != 1 {
		t.Fatalf("expected 1 remaining event, got %d", len(events))
	}
}

func TestPrune_NoopOnEmptyFile(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "nonexistent.jsonl")
	log := New(path)

	pruned, err := log.Prune(90)
	if err != nil {
		t.Fatalf("Prune failed: %v", err)
	}
	if pruned != 0 {
		t.Fatalf("expected 0 pruned, got %d", pruned)
	}
}

func TestPrune_IntegrationWithRetention(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "events.jsonl")
	log := New(path)

	now := time.Now()
	for i := 0; i < 120; i++ {
		ts := now.AddDate(0, 0, -119+i) // day -119 through day 0
		if err := log.Append(Event{
			Timestamp: ts,
			Type:      "citation",
			Session:   "sess-I",
			Lesson:    "L001",
		}); err != nil {
			t.Fatalf("Append failed: %v", err)
		}
	}

	pruned, err := log.Prune(90)
	if err != nil {
		t.Fatalf("Prune failed: %v", err)
	}

	remaining, err := log.Read()
	if err != nil {
		t.Fatalf("Read after prune failed: %v", err)
	}

	// 120 days of events, keep last 90 days → prune ~30
	if pruned+len(remaining) != 120 {
		t.Fatalf("pruned (%d) + remaining (%d) != 120", pruned, len(remaining))
	}
	if pruned < 28 || pruned > 32 {
		t.Fatalf("expected ~30 pruned, got %d", pruned)
	}
	if len(remaining) < 88 || len(remaining) > 92 {
		t.Fatalf("expected ~90 remaining, got %d", len(remaining))
	}
}
