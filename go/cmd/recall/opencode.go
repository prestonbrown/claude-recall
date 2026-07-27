package main

import (
	"encoding/json"
	"fmt"
	"io"
	"regexp"
	"sort"
	"strings"

	"github.com/pbrown/claude-recall/internal/lessons"
	"github.com/pbrown/claude-recall/internal/models"
)

// Duty reminder constants
const lessonDutyReminder = `LESSON DUTY: When user corrects you, something fails, or you discover a pattern:
  ASK: "Should I record this as a lesson? [category]: title - content"
  CITE: When applying a lesson, say "Applying [L###]: ..."
  BEFORE git/implementing: Check if high-star lessons apply
  AFTER mistakes: Cite the violated lesson, propose new if novel`

// Regex patterns for session-idle processing
var (
	// Citation pattern: [L001] or [S001]
	citationPattern = regexp.MustCompile(`\[([LS]\d{3})\]`)
	// Listing pattern: [L001] [*** - lesson listing format to skip
	listingPattern = regexp.MustCompile(`\[([LS]\d{3})\]\s+\[\*`)
	// LESSON: pattern - optional category, title - content
	lessonPattern = regexp.MustCompile(`(?:AI )?LESSON:\s*(?:([^:]+):\s*)?(.+?)\s*-\s*(.+)`)
)

// runOpencode dispatches to opencode subcommands
func (a *App) runOpencode(args []string) int {
	if len(args) < 1 {
		fmt.Fprintln(a.stderr, "usage: recall opencode <subcommand> [args...]")
		fmt.Fprintln(a.stderr, "  session-start  - Initialize session context")
		fmt.Fprintln(a.stderr, "  session-idle   - Process messages during idle")
		return 1
	}

	subcmd := args[0]
	switch subcmd {
	case "session-start":
		return a.runOpencodeSessionStart(a.stdin)
	case "session-idle":
		return a.runOpencodeSessionIdle(a.stdin)
	default:
		fmt.Fprintf(a.stderr, "unknown opencode subcommand: %s\n", subcmd)
		return 1
	}
}

// SessionStartInput is the JSON input for session-start
type SessionStartInput struct {
	Cwd           string `json:"cwd"`
	TopN          int    `json:"top_n"`
	IncludeDuties bool   `json:"include_duties"`
}

// SessionStartOutput is the JSON output for session-start
type SessionStartOutput struct {
	LessonsContext string `json:"lessons_context"`
	DutyReminders  string `json:"duty_reminders"`
}

// runOpencodeSessionStart handles the session-start subcommand
func (a *App) runOpencodeSessionStart(stdin io.Reader) int {
	var input SessionStartInput
	if err := json.NewDecoder(stdin).Decode(&input); err != nil {
		fmt.Fprintf(a.stderr, "error parsing input JSON: %v\n", err)
		return 1
	}

	// Default top_n to 5
	if input.TopN <= 0 {
		input.TopN = 5
	}

	lessonStore := lessons.NewStore(a.projectPath, a.systemPath)

	// Get lessons context
	lessonsContext := ""
	allLessons, err := lessonStore.List()
	if err == nil && len(allLessons) > 0 {
		lessonsContext = formatLessonsContext(allLessons, input.TopN)
	}

	// Build duty reminders
	dutyReminders := ""
	if input.IncludeDuties {
		dutyReminders = lessonDutyReminder
	}

	// Build output
	output := SessionStartOutput{
		LessonsContext: lessonsContext,
		DutyReminders:  dutyReminders,
	}

	data, err := json.Marshal(output)
	if err != nil {
		fmt.Fprintf(a.stderr, "error encoding output JSON: %v\n", err)
		return 1
	}
	fmt.Fprintln(a.stdout, string(data))

	return 0
}

// SessionIdleInput is the JSON input for session-idle
type SessionIdleInput struct {
	Cwd              string                   `json:"cwd"`
	SessionID        string                   `json:"session_id"`
	Messages         []map[string]interface{} `json:"messages"`
	CheckpointOffset int                      `json:"checkpoint_offset"`
}

// SessionIdleOutput is the JSON output for session-idle
type SessionIdleOutput struct {
	Citations           []string `json:"citations"`
	LessonsAdded        []string `json:"lessons_added"`
	NewCheckpointOffset int      `json:"new_checkpoint_offset"`
	Error               string   `json:"error,omitempty"`
}

// runOpencodeSessionIdle handles the session-idle subcommand
func (a *App) runOpencodeSessionIdle(stdin io.Reader) int {
	var input SessionIdleInput
	if err := json.NewDecoder(stdin).Decode(&input); err != nil {
		fmt.Fprintf(a.stderr, "error parsing input JSON: %v\n", err)
		return 1
	}

	// Create stores
	lessonStore := lessons.NewStore(a.projectPath, a.systemPath)
	output := SessionIdleOutput{
		Citations:           []string{},
		LessonsAdded:        []string{},
		NewCheckpointOffset: len(input.Messages),
	}

	// Process messages starting from checkpoint_offset
	for i := input.CheckpointOffset; i < len(input.Messages); i++ {
		msg := input.Messages[i]

		// Handle both string and array content types
		var content string
		if str, ok := msg["content"].(string); ok {
			content = str
		} else if arr, ok := msg["content"].([]interface{}); ok {
			// Extract text from content blocks
			var texts []string
			for _, block := range arr {
				if b, ok := block.(map[string]interface{}); ok {
					if t, ok := b["type"].(string); ok && t == "text" {
						if text, ok := b["text"].(string); ok {
							texts = append(texts, text)
						}
					}
				}
			}
			content = strings.Join(texts, " ")
		} else {
			continue
		}

		// Extract citations
		citations := extractCitations(content)
		for _, cid := range citations {
			output.Citations = append(output.Citations, cid)
			// Cite the lesson (errors logged but don't fail the operation)
			if err := lessonStore.Cite(cid); err != nil {
				// Log but continue - non-existent lesson citations are not fatal
				fmt.Fprintf(a.stderr, "warning: failed to cite %s: %v\n", cid, err)
			}
		}

		// Parse LESSON: commands
		lessonsAdded := parseLessonCommands(content, lessonStore)
		output.LessonsAdded = append(output.LessonsAdded, lessonsAdded...)
	}

	data, err := json.Marshal(output)
	if err != nil {
		fmt.Fprintf(a.stderr, "error encoding output JSON: %v\n", err)
		return 1
	}
	fmt.Fprintln(a.stdout, string(data))

	return 0
}

// Helper functions

// formatLessonsContext formats lessons for context injection
func formatLessonsContext(allLessons []*models.Lesson, topN int) string {
	if len(allLessons) == 0 {
		return ""
	}

	// Sort by combined score (uses + velocity)
	type scoredLesson struct {
		lesson *models.Lesson
		score  float64
	}
	var scored []scoredLesson
	for _, l := range allLessons {
		scored = append(scored, scoredLesson{
			lesson: l,
			score:  float64(l.Uses) + l.Velocity,
		})
	}
	// Sort descending by score
	sort.Slice(scored, func(i, j int) bool {
		return scored[i].score > scored[j].score
	})

	// Take top N
	if topN > len(scored) {
		topN = len(scored)
	}

	var sb strings.Builder
	sb.WriteString("## Recent Lessons\n\n")
	for i := 0; i < topN; i++ {
		l := scored[i].lesson
		sb.WriteString(fmt.Sprintf("### [%s] %s %s\n", l.ID, l.Rating(), l.Title))
		sb.WriteString(fmt.Sprintf("> %s\n\n", l.Content))
	}

	return sb.String()
}

// extractCitations extracts lesson citations from text
// Skips listings format like "[L001] [***--]"
func extractCitations(text string) []string {
	var citations []string
	seen := make(map[string]bool)

	// Find all citation matches with their positions
	matches := citationPattern.FindAllStringSubmatchIndex(text, -1)
	for _, match := range matches {
		if len(match) >= 4 {
			// match[0:2] is the full match, match[2:4] is the captured group
			cid := text[match[2]:match[3]]

			// Check if this is a listing format (followed by space + [*)
			endPos := match[1]
			if endPos < len(text) {
				// Check what follows
				remaining := text[endPos:]
				if strings.HasPrefix(remaining, " [*") || strings.HasPrefix(remaining, "  [*") {
					// This is a listing format, skip it
					continue
				}
			}

			if !seen[cid] {
				citations = append(citations, cid)
				seen[cid] = true
			}
		}
	}

	return citations
}

// parseLessonCommands parses LESSON: commands and adds lessons
func parseLessonCommands(text string, store *lessons.Store) []string {
	var added []string

	matches := lessonPattern.FindAllStringSubmatch(text, -1)
	for _, match := range matches {
		if len(match) >= 4 {
			category := strings.TrimSpace(match[1])
			if category == "" {
				category = "pattern"
			}
			title := strings.TrimSpace(match[2])
			content := strings.TrimSpace(match[3])

			lesson, err := store.Add("project", category, title, content)
			if err == nil {
				added = append(added, lesson.ID)
			}
		}
	}

	return added
}
