package main

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"time"

	"github.com/pbrown/claude-recall/internal/config"
	"github.com/pbrown/claude-recall/internal/debuglog"
	"github.com/pbrown/claude-recall/internal/eventlog"
	"github.com/pbrown/claude-recall/internal/lessons"
	"github.com/pbrown/claude-recall/internal/models"
)

// injectInput is the optional JSON input for inject commands
type injectInput struct {
	Cwd       string `json:"cwd"`
	SessionID string `json:"session_id"`
}

// injectCombinedOutput is the JSON output for inject-combined
type injectCombinedOutput struct {
	Lessons string `json:"lessons"`
}

// runInject outputs top n lessons for context injection
func runInject() int {
	// Parse optional n from args
	n := 5
	if len(os.Args) > 2 {
		if parsed, err := strconv.Atoi(os.Args[2]); err == nil && parsed > 0 {
			n = parsed
		}
	}

	// Load config
	cfg, err := config.Load("")
	if err != nil {
		fmt.Fprintf(os.Stderr, "error loading config: %v\n", err)
		return 1
	}

	// Set up lesson store paths
	projectLessonsPath := filepath.Join(cfg.ProjectDir, ".claude-recall", "LESSONS.md")
	systemLessonsPath := filepath.Join(cfg.StateDir, "LESSONS.md")
	store := lessons.NewStore(projectLessonsPath, systemLessonsPath)

	// Get and sort lessons
	allLessons, err := store.List()
	if err != nil {
		fmt.Fprintf(os.Stderr, "error listing lessons: %v\n", err)
		return 1
	}

	// Sort by combined score (uses + velocity)
	sort.Slice(allLessons, func(i, j int) bool {
		scoreI := float64(allLessons[i].Uses) + allLessons[i].Velocity
		scoreJ := float64(allLessons[j].Uses) + allLessons[j].Velocity
		return scoreI > scoreJ
	})

	// Take top n
	if n > len(allLessons) {
		n = len(allLessons)
	}
	topLessons := allLessons[:n]

	// Log which lessons are being injected
	dlog := debuglog.New(cfg.StateDir, cfg.DebugLevel)
	entries := make([]debuglog.LessonEntry, len(topLessons))
	for i, l := range topLessons {
		entries[i] = debuglog.LessonEntry{ID: l.ID, Title: l.Title}
	}
	dlog.LogInjection("session_start", cfg.ProjectDir, entries)

	// Emit injection events to session log
	if cfg.EventLogEnabled != nil && *cfg.EventLogEnabled {
		elog := eventlog.New(filepath.Join(cfg.StateDir, "session-log.jsonl"))
		now := time.Now()
		for _, lesson := range topLessons {
			if err := elog.Append(eventlog.Event{
				Timestamp: now,
				Type:      "injection",
				Lesson:    lesson.ID,
				Hook:      "session_start",
				Project:   cfg.ProjectDir,
			}); err != nil {
				fmt.Fprintf(os.Stderr, "warning: event log append failed: %v\n", err)
			}
		}
		lessonIDs := make([]string, len(topLessons))
		for i, l := range topLessons {
			lessonIDs[i] = l.ID
		}
		if err := elog.Append(eventlog.Event{
			Timestamp: now,
			Type:      "session_start",
			Lessons:   lessonIDs,
			Project:   cfg.ProjectDir,
		}); err != nil {
			fmt.Fprintf(os.Stderr, "warning: event log append failed: %v\n", err)
		}
	}

	// Output formatted lessons
	output := formatLessonsForInjection(topLessons)
	fmt.Print(output)

	return 0
}

// runInjectCombined outputs lessons as JSON
func runInjectCombined() int {
	// Parse optional n from args
	n := 5
	if len(os.Args) > 2 {
		if parsed, err := strconv.Atoi(os.Args[2]); err == nil && parsed > 0 {
			n = parsed
		}
	}

	// Try to read optional JSON input from stdin (non-blocking)
	var input injectInput
	_ = parseInjectInput(os.Stdin, &input)

	// Load config
	cfg, err := config.Load("")
	if err != nil {
		fmt.Fprintf(os.Stderr, "error loading config: %v\n", err)
		return 1
	}

	// Use cwd from input if provided
	projectDir := cfg.ProjectDir
	if input.Cwd != "" {
		projectDir = input.Cwd
	}

	// Set up lesson store paths
	projectLessonsPath := filepath.Join(projectDir, ".claude-recall", "LESSONS.md")
	systemLessonsPath := filepath.Join(cfg.StateDir, "LESSONS.md")
	lessonStore := lessons.NewStore(projectLessonsPath, systemLessonsPath)

	// Get and sort lessons
	allLessons, err := lessonStore.List()
	if err != nil {
		fmt.Fprintf(os.Stderr, "error listing lessons: %v\n", err)
		return 1
	}

	// Sort by combined score
	sort.Slice(allLessons, func(i, j int) bool {
		scoreI := float64(allLessons[i].Uses) + allLessons[i].Velocity
		scoreJ := float64(allLessons[j].Uses) + allLessons[j].Velocity
		return scoreI > scoreJ
	})

	// Take top n
	if n > len(allLessons) {
		n = len(allLessons)
	}
	topLessons := allLessons[:n]

	// Log which lessons are being injected
	dlog := debuglog.New(cfg.StateDir, cfg.DebugLevel)
	entries := make([]debuglog.LessonEntry, len(topLessons))
	for i, l := range topLessons {
		entries[i] = debuglog.LessonEntry{ID: l.ID, Title: l.Title}
	}
	dlog.LogInjection("session_start", projectDir, entries)

	// Emit injection events to session log
	if cfg.EventLogEnabled != nil && *cfg.EventLogEnabled {
		elog := eventlog.New(filepath.Join(cfg.StateDir, "session-log.jsonl"))
		now := time.Now()
		for _, lesson := range topLessons {
			if err := elog.Append(eventlog.Event{
				Timestamp: now,
				Type:      "injection",
				Session:   input.SessionID,
				Lesson:    lesson.ID,
				Hook:      "session_start",
				Project:   projectDir,
			}); err != nil {
				fmt.Fprintf(os.Stderr, "warning: event log append failed: %v\n", err)
			}
		}
		lessonIDs := make([]string, len(topLessons))
		for i, l := range topLessons {
			lessonIDs[i] = l.ID
		}
		if err := elog.Append(eventlog.Event{
			Timestamp: now,
			Type:      "session_start",
			Session:   input.SessionID,
			Lessons:   lessonIDs,
			Project:   projectDir,
		}); err != nil {
			fmt.Fprintf(os.Stderr, "warning: event log append failed: %v\n", err)
		}
	}

	// Build output
	result := injectCombinedOutput{
		Lessons: formatLessonsForInjection(topLessons),
	}

	// Output JSON
	output, err := json.Marshal(result)
	if err != nil {
		fmt.Fprintf(os.Stderr, "error marshaling output: %v\n", err)
		return 1
	}

	fmt.Println(string(output))
	return 0
}

// parseInjectInput attempts to parse JSON input from a reader
func parseInjectInput(r io.Reader, input *injectInput) error {
	// Check if stdin has data (for piped input)
	stat, _ := os.Stdin.Stat()
	if (stat.Mode() & os.ModeCharDevice) != 0 {
		// Terminal input, no JSON expected
		return nil
	}

	decoder := json.NewDecoder(r)
	return decoder.Decode(input)
}

// formatLessonsForInjection formats lessons in markdown for context injection
func formatLessonsForInjection(lessons []*models.Lesson) string {
	if len(lessons) == 0 {
		return ""
	}

	output := "## Recent Lessons\n\n"
	for _, l := range lessons {
		output += fmt.Sprintf("### [%s] %s %s\n", l.ID, l.Rating(), l.Title)
		output += fmt.Sprintf("> %s\n\n", l.Content)
	}

	return output
}
