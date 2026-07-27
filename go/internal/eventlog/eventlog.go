// SPDX-License-Identifier: GPL-3.0-or-later
package eventlog

import (
	"bufio"
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"os"
	"time"
)

// Event represents a single event in the session log.
type Event struct {
	Timestamp time.Time `json:"ts"`
	Type      string    `json:"type"`
	Session   string    `json:"session"`
	Lesson    string    `json:"lesson,omitempty"`
	Lessons   []string  `json:"lessons,omitempty"`
	Score     int       `json:"score,omitempty"`
	Query     string    `json:"query,omitempty"`
	Hook      string    `json:"hook,omitempty"`
	Project   string    `json:"project,omitempty"`
}

// Log manages the session event log file.
type Log struct {
	path string
}

// New creates a Log that writes to the given file path.
func New(path string) *Log {
	return &Log{path: path}
}

// Append writes one event as a JSONL line to the log file.
func (l *Log) Append(e Event) error {
	f, err := os.OpenFile(l.path, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)
	if err != nil {
		return err
	}
	defer f.Close()

	data, err := json.Marshal(e)
	if err != nil {
		return err
	}
	data = append(data, '\n')
	_, err = f.Write(data)
	return err
}

// Filter specifies criteria for ReadFiltered. Zero-value fields are ignored.
type Filter struct {
	Session string
	Lesson  string
	Project string
	Since   time.Time
	Type    string
}

// maxLineBytes caps a single event line. bufio.Scanner defaults to 64KB, and
// injection events embed the user's query verbatim, so a long prompt produced
// lines past that limit - which aborted the whole read and silently killed
// `recall stats` and `recall digest`. A line beyond even this cap is skipped
// rather than fatal: one unreadable event must not cost every event after it.
const maxLineBytes = 4 * 1024 * 1024

// Read returns all events from the log file.
// Returns nil, nil for missing or empty files. Malformed and oversized lines
// are skipped.
func (l *Log) Read() ([]Event, error) {
	f, err := os.Open(l.path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, err
	}
	defer f.Close()

	var events []Event
	r := bufio.NewReaderSize(f, 64*1024)
	for {
		line, err := r.ReadBytes('\n')
		if len(line) > 0 {
			// A line past the cap is dropped on its own; bufio.Scanner used to
			// abort here, which cost every event after it.
			if len(line) <= maxLineBytes {
				trimmed := bytes.TrimRight(line, "\r\n")
				if len(trimmed) > 0 {
					var ev Event
					if jsonErr := json.Unmarshal(trimmed, &ev); jsonErr == nil {
						events = append(events, ev)
					}
					// Malformed lines are skipped.
				}
			}
		}
		if err != nil {
			if errors.Is(err, io.EOF) {
				break
			}
			return events, err
		}
	}
	return events, nil
}

// ReadFiltered returns events matching all non-zero fields in the filter (AND logic).
func (l *Log) ReadFiltered(f Filter) ([]Event, error) {
	all, err := l.Read()
	if err != nil {
		return nil, err
	}

	var result []Event
	for _, ev := range all {
		if f.Session != "" && ev.Session != f.Session {
			continue
		}
		if f.Lesson != "" && ev.Lesson != f.Lesson {
			continue
		}
		if f.Project != "" && ev.Project != f.Project {
			continue
		}
		if f.Type != "" && ev.Type != f.Type {
			continue
		}
		if !f.Since.IsZero() && ev.Timestamp.Before(f.Since) {
			continue
		}
		result = append(result, ev)
	}
	return result, nil
}

// Prune removes events older than retentionDays and rewrites the file.
// Returns the count of pruned entries. Returns 0, nil for missing or empty files.
func (l *Log) Prune(retentionDays int) (int, error) {
	all, err := l.Read()
	if err != nil {
		return 0, err
	}
	if len(all) == 0 {
		return 0, nil
	}

	cutoff := time.Now().AddDate(0, 0, -retentionDays)
	var kept []Event
	pruned := 0
	for _, ev := range all {
		if ev.Timestamp.Before(cutoff) {
			pruned++
		} else {
			kept = append(kept, ev)
		}
	}

	if pruned == 0 {
		return 0, nil
	}

	f, err := os.Create(l.path)
	if err != nil {
		return 0, err
	}
	defer f.Close()

	for _, ev := range kept {
		data, err := json.Marshal(ev)
		if err != nil {
			return 0, err
		}
		data = append(data, '\n')
		if _, err := f.Write(data); err != nil {
			return 0, err
		}
	}

	return pruned, nil
}
