package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"github.com/pbrown/claude-recall/internal/checkpoint"
	"github.com/pbrown/claude-recall/internal/citations"
	"github.com/pbrown/claude-recall/internal/config"
	"github.com/pbrown/claude-recall/internal/debuglog"
	"github.com/pbrown/claude-recall/internal/lessons"
	"github.com/pbrown/claude-recall/internal/transcript"
)

// stopAllInput is the raw Claude Code hook input
type stopAllInput struct {
	Cwd            string `json:"cwd"`
	SessionID      string `json:"session_id"`
	TranscriptPath string `json:"transcript_path"`
}

// stopAllOutput is the JSON output
type stopAllOutput struct {
	CitationsProcessed int      `json:"citations_processed"`
	LessonsAdded       int      `json:"lessons_added"`
	CitationIDs        []string `json:"citation_ids"`
	Errors             []string `json:"errors,omitempty"`
}

// AI LESSON pattern: "AI LESSON: category: title - content"
// or "AI LESSON [type]: category: title - content"
var aiLessonPattern = regexp.MustCompile(`(?m)AI LESSON(?:\s+\[[a-z]+\])?:\s*(.+)`)

// runStopAll replaces the entire bash stop hook with a single Go call.
// Reads raw Claude Code hook input, parses transcript, extracts citations
// and AI lessons, processes everything, updates checkpoint.
func runStopAll() int {
	// Parse input from stdin
	var input stopAllInput
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

	// Resolve project dir
	projectDir := input.Cwd
	if projectDir == "" {
		projectDir = cfg.ProjectDir
	}

	// Expand tilde in transcript path
	transcriptPath := expandTilde(input.TranscriptPath)
	if transcriptPath == "" {
		fmt.Fprintf(os.Stderr, "no transcript path\n")
		return 1
	}

	// Check transcript exists
	if _, err := os.Stat(transcriptPath); err != nil {
		// No transcript yet, nothing to do
		return 0
	}

	result := stopAllOutput{
		CitationIDs: []string{},
		Errors:      []string{},
	}

	// Get checkpoint offset
	checkpointPath := filepath.Join(cfg.StateDir, "checkpoints.txt")
	offset, err := checkpoint.GetOffset(checkpointPath, input.SessionID)
	if err != nil {
		result.Errors = append(result.Errors, fmt.Sprintf("checkpoint read: %v", err))
		offset = 0
	}

	// Open and parse transcript from offset
	file, err := os.Open(transcriptPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "error opening transcript: %v\n", err)
		return 1
	}
	defer file.Close()

	messages, newOffset, err := transcript.ParseFrom(file, offset)
	if err != nil {
		result.Errors = append(result.Errors, fmt.Sprintf("transcript parse: %v", err))
	}

	// Set up lesson store
	projectLessonsPath := filepath.Join(projectDir, ".claude-recall", "LESSONS.md")
	systemLessonsPath := filepath.Join(cfg.StateDir, "LESSONS.md")
	lessonStore := lessons.NewStore(projectLessonsPath, systemLessonsPath)

	// Extract and process citations
	extractedCitations := citations.ExtractFromMessages(messages)
	for _, c := range extractedCitations {
		result.CitationIDs = append(result.CitationIDs, c.ID)
		if err := lessonStore.Cite(c.ID); err != nil {
			result.Errors = append(result.Errors, fmt.Sprintf("cite %s: %v", c.ID, err))
			continue
		}
		result.CitationsProcessed++
	}

	// Extract and add AI lessons from assistant text
	for _, msg := range messages {
		if msg.Type != "assistant" {
			continue
		}
		matches := aiLessonPattern.FindAllStringSubmatch(msg.Content, -1)
		for _, match := range matches {
			if len(match) < 2 {
				continue
			}
			remainder := strings.TrimSpace(match[1])
			category, title, content := parseAILesson(remainder)
			if title == "" {
				continue
			}
			if _, err := lessonStore.Add("project", category, title, content); err != nil {
				result.Errors = append(result.Errors, fmt.Sprintf("add lesson: %v", err))
				continue
			}
			result.LessonsAdded++
		}
	}

	// Update checkpoint
	if err := checkpoint.SetOffset(checkpointPath, input.SessionID, newOffset); err != nil {
		result.Errors = append(result.Errors, fmt.Sprintf("checkpoint write: %v", err))
	}

	// Log injection stats
	dlog := debuglog.New(cfg.StateDir, cfg.DebugLevel)
	if result.CitationsProcessed > 0 {
		fmt.Fprintf(os.Stderr, "[lessons] %d lesson(s) cited\n", result.CitationsProcessed)
	}
	if result.LessonsAdded > 0 {
		fmt.Fprintf(os.Stderr, "[lessons] %d AI lesson(s) added\n", result.LessonsAdded)
	}
	dlog.LogStopHook(input.SessionID, result.CitationsProcessed, result.CitationIDs, result.LessonsAdded, result.Errors)

	// Output JSON result
	output, err := json.Marshal(result)
	if err != nil {
		fmt.Fprintf(os.Stderr, "error marshaling output: %v\n", err)
		return 1
	}
	fmt.Println(string(output))
	return 0
}

// parseAILesson parses "category: title - content" from an AI LESSON match
func parseAILesson(remainder string) (category, title, content string) {
	// Split on first colon for category
	parts := strings.SplitN(remainder, ":", 2)
	if len(parts) < 2 {
		// No category, treat whole thing as title
		category = "pattern"
		title = strings.TrimSpace(remainder)
		return
	}

	category = strings.ToLower(strings.TrimSpace(parts[0]))
	titleContent := strings.TrimSpace(parts[1])

	// Validate category
	switch category {
	case "pattern", "correction", "decision", "gotcha", "preference":
		// valid
	default:
		category = "pattern"
	}

	// Split on " - " for title vs content
	titleParts := strings.SplitN(titleContent, " - ", 2)
	title = strings.TrimSpace(titleParts[0])
	if len(titleParts) > 1 {
		content = strings.TrimSpace(titleParts[1])
	}

	return
}
