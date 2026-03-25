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
