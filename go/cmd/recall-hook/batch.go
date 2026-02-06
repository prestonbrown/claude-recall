package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"github.com/pbrown/claude-recall/internal/config"
	"github.com/pbrown/claude-recall/internal/handoffs"
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

	// Skip handoff processing (for performance)
	SkipHandoffs bool `json:"skip_handoffs"`
}

// aiLesson represents an AI-generated lesson to add
type aiLesson struct {
	Category string `json:"category"`
	Title    string `json:"title"`
	Content  string `json:"content"`
	Type     string `json:"type,omitempty"`
}

// handoffOp represents a parsed handoff operation
type handoffOp struct {
	Op          string            `json:"op"`           // add, update, complete, tried
	ID          string            `json:"id,omitempty"` // for update/complete/tried
	Title       string            `json:"title,omitempty"`
	Description string            `json:"description,omitempty"`
	Status      string            `json:"status,omitempty"`
	Phase       string            `json:"phase,omitempty"`
	Outcome     string            `json:"outcome,omitempty"` // for tried
	Updates     map[string]string `json:"updates,omitempty"`
}

// batchOutput is the JSON output for stop-hook-batch
type batchOutput struct {
	CitationsProcessed int          `json:"citations_processed"`
	LessonsAdded       int          `json:"lessons_added"`
	HandoffOps         []handoffOp  `json:"handoff_ops"`
	HandoffResults     []string     `json:"handoff_results"`
	Errors             []string     `json:"errors,omitempty"`
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
		HandoffOps:     []handoffOp{},
		HandoffResults: []string{},
		Errors:         []string{},
	}

	// Set up stores
	projectLessonsPath := filepath.Join(projectDir, ".claude-recall", "LESSONS.md")
	systemLessonsPath := filepath.Join(cfg.StateDir, "LESSONS.md")
	lessonStore := lessons.NewStore(projectLessonsPath, systemLessonsPath)

	handoffsPath := filepath.Join(projectDir, ".claude-recall", "HANDOFFS.md")
	stealthPath := filepath.Join(projectDir, ".claude-recall", "HANDOFFS_LOCAL.md")
	handoffStore := handoffs.NewStore(handoffsPath, stealthPath)

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

	// Parse and process handoff operations from assistant texts (if enabled)
	if !input.SkipHandoffs && len(input.AssistantTexts) > 0 {
		ops := parseHandoffOps(input.AssistantTexts)
		result.HandoffOps = ops

		for _, op := range ops {
			opResult, err := executeHandoffOp(handoffStore, op)
			if err != nil {
				result.Errors = append(result.Errors, fmt.Sprintf("handoff %s: %v", op.Op, err))
				continue
			}
			result.HandoffResults = append(result.HandoffResults, opResult)
		}
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

// Handoff patterns
var (
	// HANDOFF: title - starts a new handoff
	handoffStartPattern = regexp.MustCompile(`(?m)^HANDOFF:\s*(.+)$`)

	// HANDOFF UPDATE <id>: <status> - <description>
	handoffUpdatePattern = regexp.MustCompile(`(?m)^HANDOFF\s+UPDATE\s+([A-Za-z0-9-]+):\s*(tried\s+)?(success|fail|partial)?\s*[-–]?\s*(.*)$`)

	// HANDOFF COMPLETE <id>
	handoffCompletePattern = regexp.MustCompile(`(?m)^HANDOFF\s+COMPLETE\s+([A-Za-z0-9-]+)`)

	// LESSON: [category:] title - content
	lessonPattern = regexp.MustCompile(`(?m)^LESSON:\s*(?:(\w+):\s*)?([^-]+)\s*-\s*(.+)$`)
)

// parseHandoffOps parses handoff operations from assistant texts
func parseHandoffOps(texts []string) []handoffOp {
	var ops []handoffOp

	for _, text := range texts {
		// Check for HANDOFF: (new handoff)
		startMatches := handoffStartPattern.FindAllStringSubmatch(text, -1)
		for _, match := range startMatches {
			if len(match) > 1 {
				ops = append(ops, handoffOp{
					Op:    "add",
					Title: strings.TrimSpace(match[1]),
				})
			}
		}

		// Check for HANDOFF UPDATE
		updateMatches := handoffUpdatePattern.FindAllStringSubmatch(text, -1)
		for _, match := range updateMatches {
			if len(match) > 1 {
				op := handoffOp{
					Op: "update",
					ID: match[1],
				}

				// Check if this is a "tried" operation
				if strings.TrimSpace(match[2]) != "" {
					op.Op = "tried"
					if len(match) > 3 {
						op.Outcome = strings.ToLower(strings.TrimSpace(match[3]))
					}
					if op.Outcome == "" {
						op.Outcome = "partial" // default
					}
					if len(match) > 4 {
						op.Description = strings.TrimSpace(match[4])
					}
				} else {
					// Regular update
					if len(match) > 3 && match[3] != "" {
						// Status is specified
						op.Status = strings.ToLower(strings.TrimSpace(match[3]))
					}
					if len(match) > 4 {
						op.Description = strings.TrimSpace(match[4])
					}
				}

				ops = append(ops, op)
			}
		}

		// Check for HANDOFF COMPLETE
		completeMatches := handoffCompletePattern.FindAllStringSubmatch(text, -1)
		for _, match := range completeMatches {
			if len(match) > 1 {
				ops = append(ops, handoffOp{
					Op: "complete",
					ID: match[1],
				})
			}
		}
	}

	return ops
}

// executeHandoffOp executes a single handoff operation
func executeHandoffOp(store *handoffs.Store, op handoffOp) (string, error) {
	switch op.Op {
	case "add":
		h, err := store.Add(op.Title, op.Description, false)
		if err != nil {
			return "", err
		}
		return fmt.Sprintf("added %s", h.ID), nil

	case "update":
		updates := make(map[string]interface{})
		if op.Status != "" {
			updates["status"] = op.Status
		}
		if op.Phase != "" {
			updates["phase"] = op.Phase
		}
		if op.Description != "" {
			updates["description"] = op.Description
		}
		if len(updates) > 0 {
			if err := store.Update(op.ID, updates); err != nil {
				return "", err
			}
		}
		return fmt.Sprintf("updated %s", op.ID), nil

	case "tried":
		if err := store.AddTriedStep(op.ID, op.Outcome, op.Description); err != nil {
			return "", err
		}
		return fmt.Sprintf("tried %s (%s)", op.ID, op.Outcome), nil

	case "complete":
		if err := store.Complete(op.ID); err != nil {
			return "", err
		}
		return fmt.Sprintf("completed %s", op.ID), nil

	default:
		return "", fmt.Errorf("unknown operation: %s", op.Op)
	}
}
