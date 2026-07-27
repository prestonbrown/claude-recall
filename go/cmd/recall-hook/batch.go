package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"

	"github.com/pbrown/claude-recall/internal/config"
	"github.com/pbrown/claude-recall/internal/lessons"
)

// batchInput is the JSON input for stop-hook-batch
type batchInput struct {
	// Pre-parsed transcript data
	AssistantTexts []string `json:"assistant_texts"`

	// Optional direct citations (skip transcript parsing)
	Citations []string `json:"citations"`

	// Session info
	SessionID string `json:"session_id"`
	Cwd       string `json:"cwd"`

	// AI lessons to add
	AILessons []aiLesson `json:"ai_lessons"`
}

// aiLesson represents an AI-generated lesson to add
type aiLesson struct {
	Category string `json:"category"`
	Title    string `json:"title"`
	Content  string `json:"content"`
	Type     string `json:"type,omitempty"`
}

// batchOutput is the JSON output for stop-hook-batch
type batchOutput struct {
	CitationsProcessed int      `json:"citations_processed"`
	LessonsAdded       int      `json:"lessons_added"`
	Errors             []string `json:"errors,omitempty"`
}

// runStopHookBatch processes multiple stop-hook operations in one call
func runStopHookBatch() int {
	// Read JSON input from stdin
	var input batchInput
	decoder := json.NewDecoder(os.Stdin)
	if err := decoder.Decode(&input); err != nil {
		fmt.Fprintf(os.Stderr, "error parsing input: %v\n", err)
		return 1
	}

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

	// Initialize output
	result := batchOutput{
		Errors: []string{},
	}

	// Set up stores
	projectLessonsPath := filepath.Join(projectDir, ".claude-recall", "LESSONS.md")
	systemLessonsPath := filepath.Join(cfg.StateDir, "LESSONS.md")
	lessonStore := lessons.NewStore(projectLessonsPath, systemLessonsPath)

	// Process citations
	citations := input.Citations
	if len(citations) == 0 && len(input.AssistantTexts) > 0 {
		// Extract citations from assistant texts
		citations = extractCitationsFromTexts(input.AssistantTexts)
	}

	// Deduplicate and process citations
	seen := make(map[string]bool)
	for _, id := range citations {
		if seen[id] {
			continue
		}
		seen[id] = true

		if err := lessonStore.Cite(id); err != nil {
			result.Errors = append(result.Errors, fmt.Sprintf("cite %s: %v", id, err))
			continue
		}
		result.CitationsProcessed++
	}

	// Add AI lessons
	for _, al := range input.AILessons {
		_, err := lessonStore.Add("project", al.Category, al.Title, al.Content)
		if err != nil {
			result.Errors = append(result.Errors, fmt.Sprintf("add lesson: %v", err))
			continue
		}
		result.LessonsAdded++
	}

	// Output JSON result
	output, err := json.Marshal(result)
	if err != nil {
		fmt.Fprintf(os.Stderr, "error marshaling output: %v\n", err)
		return 1
	}

	fmt.Println(string(output))
	return 0
}

// Citation patterns
var citationPattern = regexp.MustCompile(`\[([LS]\d{3})\]`)

// extractCitationsFromTexts extracts citation IDs from assistant texts
func extractCitationsFromTexts(texts []string) []string {
	var citations []string
	seen := make(map[string]bool)

	for _, text := range texts {
		matches := citationPattern.FindAllStringSubmatch(text, -1)
		for _, match := range matches {
			if len(match) > 1 {
				id := match[1]
				if !seen[id] {
					seen[id] = true
					citations = append(citations, id)
				}
			}
		}
	}

	return citations
}

var (
	// LESSON: [category:] title - content
	lessonPattern = regexp.MustCompile(`(?m)^LESSON:\s*(?:(\w+):\s*)?([^-]+)\s*-\s*(.+)$`)
)
