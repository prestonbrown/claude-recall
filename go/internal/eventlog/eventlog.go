// SPDX-License-Identifier: GPL-3.0-or-later
package eventlog

import (
	"bufio"
	"encoding/json"
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

// Read returns all events from the log file.
// Returns nil, nil for missing or empty files. Malformed lines are skipped.
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
	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		line := scanner.Bytes()
		if len(line) == 0 {
			continue
		}
		var ev Event
		if err := json.Unmarshal(line, &ev); err != nil {
			// Skip malformed lines
			continue
		}
		events = append(events, ev)
	}
	if err := scanner.Err(); err != nil {
		return events, err
	}
	return events, nil
}
