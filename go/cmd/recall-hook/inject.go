package main

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strconv"

	"github.com/pbrown/claude-recall/internal/config"
	"github.com/pbrown/claude-recall/internal/debuglog"
	"github.com/pbrown/claude-recall/internal/handoffs"
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
	Lessons  string `json:"lessons"`
	Handoffs string `json:"handoffs"`
	Todos    string `json:"todos"`
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

	// Output formatted lessons
	output := formatLessonsForInjection(topLessons)
	fmt.Print(output)

	return 0
}

// runInjectCombined outputs lessons, handoffs, and todos as JSON
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

	// Set up handoff store paths
	handoffsPath := filepath.Join(projectDir, ".claude-recall", "HANDOFFS.md")
	stealthPath := filepath.Join(projectDir, ".claude-recall", "HANDOFFS_LOCAL.md")
	handoffStore := handoffs.NewStore(handoffsPath, stealthPath)

	// Get active handoffs
	activeHandoffs, err := handoffStore.List()
	if err != nil {
		// Non-fatal - continue without handoffs
		activeHandoffs = []*models.Handoff{}
	}

	// Log which lessons are being injected
	dlog := debuglog.New(cfg.StateDir, cfg.DebugLevel)
	entries := make([]debuglog.LessonEntry, len(topLessons))
	for i, l := range topLessons {
		entries[i] = debuglog.LessonEntry{ID: l.ID, Title: l.Title}
	}
	dlog.LogInjection("session_start", projectDir, entries)

	// Build output
	result := injectCombinedOutput{
		Lessons:  formatLessonsForInjection(topLessons),
		Handoffs: formatHandoffsForInjection(activeHandoffs),
		Todos:    formatTodosForInjection(activeHandoffs),
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

// formatHandoffsForInjection formats handoffs in markdown for context injection
func formatHandoffsForInjection(handoffList []*models.Handoff) string {
	if len(handoffList) == 0 {
		return ""
	}

	output := "## Active Handoffs\n\n"
	for _, h := range handoffList {
		output += fmt.Sprintf("### [%s] %s\n", h.ID, h.Title)
		output += fmt.Sprintf("- **Status**: %s | **Phase**: %s\n", h.Status, h.Phase)

		if h.Description != "" {
			output += fmt.Sprintf("- **Description**: %s\n", h.Description)
		}

		if h.Checkpoint != "" {
			output += fmt.Sprintf("- **Checkpoint**: %s\n", h.Checkpoint)
		}

		if len(h.Tried) > 0 {
			output += "\n**Tried**:\n"
			for i, t := range h.Tried {
				output += fmt.Sprintf("%d. [%s] %s\n", i+1, t.Outcome, t.Description)
			}
		}

		if h.NextSteps != "" {
			output += fmt.Sprintf("\n**Next**: %s\n", h.NextSteps)
		}

		output += "\n"
	}

	return output
}

// formatTodosForInjection formats handoffs as TodoWrite continuation prompts
func formatTodosForInjection(handoffList []*models.Handoff) string {
	if len(handoffList) == 0 {
		return ""
	}

	// Find the most recent in_progress handoff
	var activeHandoff *models.Handoff
	for _, h := range handoffList {
		if h.Status == "in_progress" {
			activeHandoff = h
			break
		}
	}

	if activeHandoff == nil {
		return ""
	}

	output := "## Todo Continuation\n\n"
	output += fmt.Sprintf("Continue work on: **%s** [%s]\n\n", activeHandoff.Title, activeHandoff.ID)

	if activeHandoff.NextSteps != "" {
		output += fmt.Sprintf("Next steps: %s\n\n", activeHandoff.NextSteps)
	}

	if len(activeHandoff.Tried) > 0 {
		output += "Previous attempts:\n"
		// Show last 3 tried steps
		start := len(activeHandoff.Tried) - 3
		if start < 0 {
			start = 0
		}
		for i := start; i < len(activeHandoff.Tried); i++ {
			t := activeHandoff.Tried[i]
			output += fmt.Sprintf("- [%s] %s\n", t.Outcome, t.Description)
		}
	}

	return output
}
