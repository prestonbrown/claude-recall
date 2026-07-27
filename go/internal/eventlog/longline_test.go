package eventlog

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// A single oversized line must not take the whole log down.
//
// The reader used bufio.Scanner with its default 64KB limit. Five injection
// events written on 2026-03-28 embedded a very long `query`, so every later
// read aborted with "token too long" - `recall stats` and `recall digest` were
// dead for four months against a log that was otherwise fine.
func writeLog(t *testing.T, lines ...string) *Log {
	t.Helper()
	path := filepath.Join(t.TempDir(), "session-log.jsonl")
	if err := os.WriteFile(path, []byte(strings.Join(lines, "\n")+"\n"), 0644); err != nil {
		t.Fatal(err)
	}
	return New(path)
}

func TestRead_OversizedLineDoesNotAbortTheLog(t *testing.T) {
	huge := strings.Repeat("x", 200*1024) // well past the 64KB default
	log := writeLog(t,
		`{"ts":"2026-03-28T14:25:11Z","type":"injection","session":"s1","lesson":"L001"}`,
		fmt.Sprintf(`{"ts":"2026-03-28T14:25:12Z","type":"injection","session":"s1","lesson":"L002","query":%q}`, huge),
		`{"ts":"2026-03-28T14:25:13Z","type":"citation","session":"s1","lesson":"L003"}`,
	)

	events, err := log.Read()
	if err != nil {
		t.Fatalf("an oversized line must not fail the read: %v", err)
	}

	var got []string
	for _, e := range events {
		got = append(got, e.Lesson)
	}
	// The long line is itself valid JSON, so all three should survive.
	if len(events) != 3 {
		t.Errorf("want 3 events, got %d (%v)", len(events), got)
	}
	// Events after the long line matter most: those were previously unreachable.
	var sawLast bool
	for _, e := range events {
		if e.Lesson == "L003" {
			sawLast = true
		}
	}
	if !sawLast {
		t.Errorf("events after the oversized line must still be read, got %v", got)
	}
}

func TestRead_LineBeyondTheHardCapIsSkippedNotFatal(t *testing.T) {
	// Past even the raised cap, drop the one line and keep going rather than
	// losing every event after it.
	huge := strings.Repeat("y", (maxLineBytes)+1024)
	log := writeLog(t,
		`{"ts":"2026-03-28T14:25:11Z","type":"injection","session":"s1","lesson":"L001"}`,
		fmt.Sprintf(`{"ts":"2026-03-28T14:25:12Z","type":"injection","session":"s1","query":%q}`, huge),
		`{"ts":"2026-03-28T14:25:13Z","type":"citation","session":"s1","lesson":"L003"}`,
	)

	events, err := log.Read()
	if err != nil {
		t.Fatalf("a monstrous line should be skipped, not returned as an error: %v", err)
	}
	var sawFirst, sawLast bool
	for _, e := range events {
		switch e.Lesson {
		case "L001":
			sawFirst = true
		case "L003":
			sawLast = true
		}
	}
	if !sawFirst || !sawLast {
		t.Errorf("events either side of the skipped line must survive, got %+v", events)
	}
}
