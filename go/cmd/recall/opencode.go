package main

import (
	"encoding/json"
	"fmt"
	"io"
	"regexp"
	"sort"
	"strings"

	"github.com/pbrown/claude-recall/internal/handoffs"
	"github.com/pbrown/claude-recall/internal/lessons"
	"github.com/pbrown/claude-recall/internal/models"
)

// Duty reminder constants
const lessonDutyReminder = `LESSON DUTY: When user corrects you, something fails, or you discover a pattern:
  ASK: "Should I record this as a lesson? [category]: title - content"
  CITE: When applying a lesson, say "Applying [L###]: ..."
  BEFORE git/implementing: Check if high-star lessons apply
  AFTER mistakes: Cite the violated lesson, propose new if novel

HANDOFF DUTY: For MAJOR work (3+ files, multi-step, integration), you MUST:
  1. Use TodoWrite to track progress - todos auto-sync to handoffs
  2. If working without TodoWrite, output: HANDOFF: title
  MAJOR = new feature, 4+ files, architectural, integration, refactoring
  MINOR = single-file fix, config, docs (no handoff needed)
  COMPLETION: When all todos done in this session:
    - If code changed, run /review
    - ASK: "Any lessons from this work?" (context is fresh now!)
    - Commit your changes (git commit auto-completes the handoff)
    - Or manually: HANDOFF COMPLETE <id>`

// Regex patterns for session-idle processing
var (
	// Citation pattern: [L001] or [S001]
	citationPattern = regexp.MustCompile(`\[([LS]\d{3})\]`)
	// Listing pattern: [L001] [*** - lesson listing format to skip
	listingPattern = regexp.MustCompile(`\[([LS]\d{3})\]\s+\[\*`)
	// LESSON: pattern - optional category, title - content
	lessonPattern = regexp.MustCompile(`(?:AI )?LESSON:\s*(?:([^:]+):\s*)?(.+?)\s*-\s*(.+)`)
	// HANDOFF: pattern - start a new handoff
	opencodeHandoffStartPattern = regexp.MustCompile(`HANDOFF:\s*(.+)`)
	// HANDOFF UPDATE <id>: tried <outcome> - <desc>
	opencodeHandoffUpdatePattern = regexp.MustCompile(`HANDOFF\s+UPDATE\s+([A-Za-z0-9-]+):\s*tried\s+(success|fail|partial)\s*-\s*(.+)`)
	// HANDOFF COMPLETE <id>
	opencodeHandoffCompletePattern = regexp.MustCompile(`HANDOFF\s+COMPLETE\s+([A-Za-z0-9-]+)`)
)

// runOpencode dispatches to opencode subcommands
func (a *App) runOpencode(args []string) int {
	if len(args) < 1 {
		fmt.Fprintln(a.stderr, "usage: recall opencode <subcommand> [args...]")
		fmt.Fprintln(a.stderr, "  session-start  - Initialize session context")
		fmt.Fprintln(a.stderr, "  session-idle   - Process messages during idle")
		fmt.Fprintln(a.stderr, "  pre-compact    - Prepare context for compaction")
		fmt.Fprintln(a.stderr, "  post-compact   - Process after compaction")
		fmt.Fprintln(a.stderr, "  session-end    - Cleanup at session end")
		return 1
	}

	subcmd := args[0]
	switch subcmd {
	case "session-start":
		return a.runOpencodeSessionStart(a.stdin)
	case "session-idle":
		return a.runOpencodeSessionIdle(a.stdin)
	case "pre-compact":
		return a.runOpencodePreCompact(a.stdin)
	case "post-compact":
		return a.runOpencodePostCompact(a.stdin)
	case "session-end":
		return a.runOpencodeSessionEnd(a.stdin)
	default:
		fmt.Fprintf(a.stderr, "unknown opencode subcommand: %s\n", subcmd)
		return 1
	}
}

// SessionStartInput is the JSON input for session-start
type SessionStartInput struct {
	Cwd          string `json:"cwd"`
	TopN         int    `json:"top_n"`
	IncludeDuties bool  `json:"include_duties"`
	IncludeTodos  bool  `json:"include_todos"`
}

// SessionStartOutput is the JSON output for session-start
type SessionStartOutput struct {
	LessonsContext  string `json:"lessons_context"`
	HandoffsContext string `json:"handoffs_context"`
	TodosPrompt     string `json:"todos_prompt"`
	DutyReminders   string `json:"duty_reminders"`
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

	// Create stores
	lessonStore := lessons.NewStore(a.projectPath, a.systemPath)
	handoffStore := handoffs.NewStore(a.handoffsPath, a.stealthPath)

	// Get lessons context
	lessonsContext := ""
	allLessons, err := lessonStore.List()
	if err == nil && len(allLessons) > 0 {
		lessonsContext = formatLessonsContext(allLessons, input.TopN)
	}

	// Get handoffs context
	handoffsContext := ""
	activeHandoffs, err := handoffStore.List()
	if err == nil && len(activeHandoffs) > 0 {
		handoffsContext = formatHandoffsContext(activeHandoffs)
	}

	// Get todos prompt
	todosPrompt := ""
	if input.IncludeTodos && len(activeHandoffs) > 0 {
		todosPrompt = formatTodosPrompt(activeHandoffs)
	}

	// Build duty reminders
	dutyReminders := ""
	if input.IncludeDuties {
		dutyReminders = lessonDutyReminder

		// Check for ready_for_review handoffs
		var reviewIDs []string
		for _, h := range activeHandoffs {
			if h.Status == "ready_for_review" {
				reviewIDs = append(reviewIDs, h.ID)
			}
		}
		if len(reviewIDs) > 0 {
			dutyReminders = fmt.Sprintf("LESSON REVIEW: [%s] is ready for review. Please review before making changes.\n\n%s",
				strings.Join(reviewIDs, ", "), dutyReminders)
		}
	}

	// Build output
	output := SessionStartOutput{
		LessonsContext:  lessonsContext,
		HandoffsContext: handoffsContext,
		TodosPrompt:     todosPrompt,
		DutyReminders:   dutyReminders,
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
	HandoffOps          []string `json:"handoff_ops"`
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
	handoffStore := handoffs.NewStore(a.handoffsPath, a.stealthPath)

	output := SessionIdleOutput{
		Citations:           []string{},
		LessonsAdded:        []string{},
		HandoffOps:          []string{},
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

		// Parse handoff patterns
		handoffOps := parseHandoffPatterns(content, handoffStore)
		output.HandoffOps = append(output.HandoffOps, handoffOps...)
	}

	data, err := json.Marshal(output)
	if err != nil {
		fmt.Fprintf(a.stderr, "error encoding output JSON: %v\n", err)
		return 1
	}
	fmt.Fprintln(a.stdout, string(data))

	return 0
}

// PreCompactInput is the JSON input for pre-compact
type PreCompactInput struct {
	Cwd           string                   `json:"cwd"`
	SessionID     string                   `json:"session_id"`
	HandoffID     string                   `json:"handoff_id"`
	FilesModified []string                 `json:"files_modified"`
	Todos         []map[string]interface{} `json:"todos"`
}

// PreCompactOutput is the JSON output for pre-compact
type PreCompactOutput struct {
	ContextToInject      string `json:"context_to_inject"`
	ShouldCreateHandoff  bool   `json:"should_create_handoff"`
}

// runOpencodePreCompact handles the pre-compact subcommand
func (a *App) runOpencodePreCompact(stdin io.Reader) int {
	var input PreCompactInput
	if err := json.NewDecoder(stdin).Decode(&input); err != nil {
		fmt.Fprintf(a.stderr, "error parsing input JSON: %v\n", err)
		return 1
	}

	handoffStore := handoffs.NewStore(a.handoffsPath, a.stealthPath)

	output := PreCompactOutput{
		ContextToInject:     "",
		ShouldCreateHandoff: false,
	}

	// Check if handoff exists
	if input.HandoffID != "" {
		h, err := handoffStore.Get(input.HandoffID)
		if err == nil && h.Status != "completed" {
			// Active handoff - prepare context for survival
			output.ContextToInject = formatHandoffForCompaction(h)
		}
	} else {
		// No handoff - check if major work indicators suggest creating one
		filesCount := len(input.FilesModified)
		todosCount := len(input.Todos)
		if filesCount >= 4 || todosCount >= 3 {
			output.ShouldCreateHandoff = true
		}
	}

	data, err := json.Marshal(output)
	if err != nil {
		fmt.Fprintf(a.stderr, "error encoding output JSON: %v\n", err)
		return 1
	}
	fmt.Fprintln(a.stdout, string(data))

	return 0
}

// PostCompactInput is the JSON input for post-compact
type PostCompactInput struct {
	Cwd                  string `json:"cwd"`
	SessionID            string `json:"session_id"`
	HandoffID            string `json:"handoff_id"`
	Phase                string `json:"phase"`
	Summary              string `json:"summary"`
	CompletionIndicators bool   `json:"completion_indicators"`
	AllTodosComplete     bool   `json:"all_todos_complete"`
}

// PostCompactOutput is the JSON output for post-compact
type PostCompactOutput struct {
	SuggestComplete bool `json:"suggest_complete"`
}

// runOpencodePostCompact handles the post-compact subcommand
func (a *App) runOpencodePostCompact(stdin io.Reader) int {
	var input PostCompactInput
	if err := json.NewDecoder(stdin).Decode(&input); err != nil {
		fmt.Fprintf(a.stderr, "error parsing input JSON: %v\n", err)
		return 1
	}

	handoffStore := handoffs.NewStore(a.handoffsPath, a.stealthPath)

	output := PostCompactOutput{
		SuggestComplete: false,
	}

	// Update handoff if exists
	if input.HandoffID != "" {
		updates := make(map[string]interface{})
		if input.Phase != "" {
			updates["phase"] = input.Phase
		}
		if input.Summary != "" {
			updates["checkpoint"] = input.Summary
		}
		if len(updates) > 0 {
			handoffStore.Update(input.HandoffID, updates)
		}

		// Check for completion indicators
		if input.CompletionIndicators || input.AllTodosComplete {
			output.SuggestComplete = true
		}
	}

	data, err := json.Marshal(output)
	if err != nil {
		fmt.Fprintf(a.stderr, "error encoding output JSON: %v\n", err)
		return 1
	}
	fmt.Fprintln(a.stdout, string(data))

	return 0
}

// SessionEndInput is the JSON input for session-end
type SessionEndInput struct {
	Cwd       string                   `json:"cwd"`
	SessionID string                   `json:"session_id"`
	HandoffID string                   `json:"handoff_id"`
	ExitType  string                   `json:"exit_type"`
	Summary   string                   `json:"summary"`
	NextSteps string                   `json:"next_steps"`
	Messages  []map[string]interface{} `json:"messages"`
}

// SessionEndOutput is the JSON output for session-end
type SessionEndOutput struct {
	Processed bool `json:"processed"`
}

// runOpencodeSessionEnd handles the session-end subcommand
func (a *App) runOpencodeSessionEnd(stdin io.Reader) int {
	var input SessionEndInput
	if err := json.NewDecoder(stdin).Decode(&input); err != nil {
		fmt.Fprintf(a.stderr, "error parsing input JSON: %v\n", err)
		return 1
	}

	handoffStore := handoffs.NewStore(a.handoffsPath, a.stealthPath)

	// Update handoff if exists and clean exit
	if input.HandoffID != "" && input.ExitType == "clean" {
		updates := make(map[string]interface{})
		if input.Summary != "" {
			updates["checkpoint"] = input.Summary
		}
		if input.NextSteps != "" {
			updates["next_steps"] = input.NextSteps
		}
		if len(updates) > 0 {
			handoffStore.Update(input.HandoffID, updates)
		}
	}

	output := SessionEndOutput{
		Processed: true,
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

// formatHandoffsContext formats handoffs for context injection
func formatHandoffsContext(handoffList []*models.Handoff) string {
	if len(handoffList) == 0 {
		return ""
	}

	var sb strings.Builder
	sb.WriteString("## Active Handoffs\n\n")

	for _, h := range handoffList {
		sb.WriteString(fmt.Sprintf("### [%s] %s\n", h.ID, h.Title))
		sb.WriteString(fmt.Sprintf("- **Status**: %s | **Phase**: %s\n", h.Status, h.Phase))

		if h.Description != "" {
			sb.WriteString(fmt.Sprintf("- **Description**: %s\n", h.Description))
		}

		if h.Checkpoint != "" {
			sb.WriteString(fmt.Sprintf("- **Checkpoint**: %s\n", h.Checkpoint))
		}

		if len(h.Tried) > 0 {
			sb.WriteString("\n**Tried**:\n")
			for i, t := range h.Tried {
				sb.WriteString(fmt.Sprintf("%d. [%s] %s\n", i+1, t.Outcome, t.Description))
			}
		}

		if h.NextSteps != "" {
			sb.WriteString(fmt.Sprintf("\n**Next**: %s\n", h.NextSteps))
		}

		sb.WriteString("\n")
	}

	return sb.String()
}

// formatTodosPrompt formats handoffs as TodoWrite continuation prompts
func formatTodosPrompt(handoffList []*models.Handoff) string {
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

	var sb strings.Builder
	sb.WriteString("## Todo Continuation\n\n")
	sb.WriteString(fmt.Sprintf("Continue work on: **%s** [%s]\n\n", activeHandoff.Title, activeHandoff.ID))

	if activeHandoff.NextSteps != "" {
		sb.WriteString(fmt.Sprintf("Next steps: %s\n\n", activeHandoff.NextSteps))
	}

	if len(activeHandoff.Tried) > 0 {
		sb.WriteString("Previous attempts:\n")
		// Show last 3 tried steps
		start := len(activeHandoff.Tried) - 3
		if start < 0 {
			start = 0
		}
		for i := start; i < len(activeHandoff.Tried); i++ {
			t := activeHandoff.Tried[i]
			sb.WriteString(fmt.Sprintf("- [%s] %s\n", t.Outcome, t.Description))
		}
	}

	return sb.String()
}

// formatHandoffForCompaction formats a handoff for compaction context
func formatHandoffForCompaction(h *models.Handoff) string {
	var sb strings.Builder
	sb.WriteString(fmt.Sprintf("## Active Work: %s [%s]\n\n", h.Title, h.ID))
	sb.WriteString(fmt.Sprintf("Status: %s | Phase: %s\n", h.Status, h.Phase))

	if h.Description != "" {
		sb.WriteString(fmt.Sprintf("Description: %s\n", h.Description))
	}

	if len(h.Tried) > 0 {
		sb.WriteString("\nTried:\n")
		for i, t := range h.Tried {
			sb.WriteString(fmt.Sprintf("%d. [%s] %s\n", i+1, t.Outcome, t.Description))
		}
	}

	if h.NextSteps != "" {
		sb.WriteString(fmt.Sprintf("\nNext: %s\n", h.NextSteps))
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

// parseHandoffPatterns parses handoff patterns and performs operations
func parseHandoffPatterns(text string, store *handoffs.Store) []string {
	var ops []string

	// HANDOFF: start
	startMatches := opencodeHandoffStartPattern.FindAllStringSubmatch(text, -1)
	for _, match := range startMatches {
		if len(match) > 1 {
			title := strings.TrimSpace(match[1])
			h, err := store.Add(title, "", false)
			if err == nil {
				ops = append(ops, fmt.Sprintf("started %s", h.ID))
			}
		}
	}

	// HANDOFF UPDATE: tried
	updateMatches := opencodeHandoffUpdatePattern.FindAllStringSubmatch(text, -1)
	for _, match := range updateMatches {
		if len(match) > 3 {
			id := match[1]
			outcome := match[2]
			desc := strings.TrimSpace(match[3])
			err := store.AddTriedStep(id, outcome, desc)
			if err == nil {
				ops = append(ops, fmt.Sprintf("updated %s (tried %s)", id, outcome))
			}
		}
	}

	// HANDOFF COMPLETE
	completeMatches := opencodeHandoffCompletePattern.FindAllStringSubmatch(text, -1)
	for _, match := range completeMatches {
		if len(match) > 1 {
			id := match[1]
			err := store.Complete(id)
			if err == nil {
				ops = append(ops, fmt.Sprintf("completed %s", id))
			}
		}
	}

	return ops
}
