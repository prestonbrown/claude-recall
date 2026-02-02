package anthropic

import (
	"encoding/json"
	"fmt"
	"os/exec"
	"regexp"
	"strings"
	"time"

	"github.com/pbrown/claude-recall/internal/models"
)

// garbagePhrases are phrases that indicate the summary is not meaningful
var garbagePhrases = []string{
	"no conversation occurred",
	"empty session",
	"no content to summarize",
	"nothing to summarize",
	"conversation is empty",
	"no work completed",
}

// ExtractContext extracts handoff context from transcript messages
func ExtractContext(assistantTexts []string, gitRef string, timeout time.Duration) (*models.HandoffContext, error) {
	if len(assistantTexts) == 0 {
		return nil, fmt.Errorf("no assistant texts provided")
	}

	client, err := NewClient()
	if err != nil {
		return nil, err
	}

	prompt := buildContextPrompt(assistantTexts)
	response, err := client.CompleteWithTimeout(prompt, timeout)
	if err != nil {
		return nil, err
	}

	context, err := parseContextResponse(response)
	if err != nil {
		return nil, err
	}

	// Validate summary
	if isGarbageSummary(context.Summary) {
		return nil, fmt.Errorf("summary indicates empty session")
	}

	// Set git ref if not already set
	if context.GitRef == "" && gitRef != "" {
		context.GitRef = gitRef
	}

	// Try to get git ref from current directory if still empty
	if context.GitRef == "" {
		if ref, err := getGitRef(); err == nil {
			context.GitRef = ref
		}
	}

	return context, nil
}

// buildContextPrompt creates the prompt for context extraction
func buildContextPrompt(assistantTexts []string) string {
	var sb strings.Builder

	sb.WriteString("Analyze this conversation and extract a structured handoff context for session continuity.\n\n")
	sb.WriteString("Return ONLY valid JSON with these fields:\n")
	sb.WriteString("{\n")
	sb.WriteString("  \"summary\": \"1-2 sentence progress summary\",\n")
	sb.WriteString("  \"critical_files\": [\"file.py:42\", \"other.py:100\"],\n")
	sb.WriteString("  \"recent_changes\": [\"Added X\", \"Fixed Y\"],\n")
	sb.WriteString("  \"learnings\": [\"Pattern found\", \"Gotcha discovered\"],\n")
	sb.WriteString("  \"blockers\": [\"Waiting for Z\"]\n")
	sb.WriteString("}\n\n")
	sb.WriteString("Important:\n")
	sb.WriteString("- Return ONLY the JSON object, no markdown code blocks\n")
	sb.WriteString("- Keep arrays short (2-5 items max)\n")
	sb.WriteString("- Use file:line format when line numbers are mentioned\n")
	sb.WriteString("- Leave arrays empty [] if nothing applies\n\n")
	sb.WriteString("Conversation:\n")

	// Include last 20 messages max
	start := len(assistantTexts) - 20
	if start < 0 {
		start = 0
	}

	for i := start; i < len(assistantTexts); i++ {
		text := assistantTexts[i]
		// Truncate long messages
		if len(text) > 2000 {
			text = text[:2000] + "..."
		}
		sb.WriteString(fmt.Sprintf("---\n%s\n", text))
	}

	return sb.String()
}

// parseContextResponse parses the JSON response into HandoffContext
func parseContextResponse(response string) (*models.HandoffContext, error) {
	// Try to extract JSON from the response
	// Sometimes the model wraps it in markdown code blocks
	response = strings.TrimSpace(response)

	// Remove markdown code blocks if present
	if strings.HasPrefix(response, "```json") {
		response = strings.TrimPrefix(response, "```json")
		if idx := strings.Index(response, "```"); idx >= 0 {
			response = response[:idx]
		}
	} else if strings.HasPrefix(response, "```") {
		response = strings.TrimPrefix(response, "```")
		if idx := strings.Index(response, "```"); idx >= 0 {
			response = response[:idx]
		}
	}

	response = strings.TrimSpace(response)

	// Parse JSON
	var result struct {
		Summary       string   `json:"summary"`
		CriticalFiles []string `json:"critical_files"`
		RecentChanges []string `json:"recent_changes"`
		Learnings     []string `json:"learnings"`
		Blockers      []string `json:"blockers"`
		GitRef        string   `json:"git_ref,omitempty"`
	}

	if err := json.Unmarshal([]byte(response), &result); err != nil {
		return nil, fmt.Errorf("failed to parse context JSON: %w", err)
	}

	return &models.HandoffContext{
		Summary:       result.Summary,
		CriticalFiles: result.CriticalFiles,
		RecentChanges: result.RecentChanges,
		Learnings:     result.Learnings,
		Blockers:      result.Blockers,
		GitRef:        result.GitRef,
	}, nil
}

// isGarbageSummary checks if the summary indicates an empty/invalid session
func isGarbageSummary(summary string) bool {
	lowerSummary := strings.ToLower(summary)
	for _, phrase := range garbagePhrases {
		if strings.Contains(lowerSummary, phrase) {
			return true
		}
	}
	return false
}

// getGitRef gets the current git commit hash
func getGitRef() (string, error) {
	cmd := exec.Command("git", "rev-parse", "--short", "HEAD")
	output, err := cmd.Output()
	if err != nil {
		return "", err
	}
	return strings.TrimSpace(string(output)), nil
}

// ExtractTriggers generates trigger keywords for a lesson
func ExtractTriggers(title, content string, timeout time.Duration) ([]string, error) {
	client, err := NewClient()
	if err != nil {
		return nil, err
	}

	prompt := fmt.Sprintf(`Generate 3-5 trigger keywords/phrases that would indicate when this lesson is relevant.

Lesson title: %s
Lesson content: %s

Output ONLY a comma-separated list of triggers, nothing else.
Example: typescript, type error, generic types

Triggers:`, title, content)

	response, err := client.CompleteWithTimeout(prompt, timeout)
	if err != nil {
		return nil, err
	}

	// Parse comma-separated triggers
	response = strings.TrimSpace(response)
	parts := strings.Split(response, ",")

	var triggers []string
	for _, p := range parts {
		p = strings.TrimSpace(p)
		if p != "" {
			triggers = append(triggers, p)
		}
	}

	return triggers, nil
}

// ClassifyLessonType determines if a lesson is constraint/informational/preference
func ClassifyLessonType(title, content string, timeout time.Duration) (string, error) {
	client, err := NewClient()
	if err != nil {
		return "", err
	}

	prompt := fmt.Sprintf(`Classify this lesson as one of: constraint, informational, preference

- constraint: Rules that MUST be followed (security, coding standards, required patterns)
- informational: Neutral facts, patterns, or context (how things work)
- preference: User preferences that should be followed when possible

Lesson title: %s
Lesson content: %s

Output ONLY one word: constraint, informational, or preference`, title, content)

	response, err := client.CompleteWithTimeout(prompt, timeout)
	if err != nil {
		return "informational", nil // Default on error
	}

	response = strings.ToLower(strings.TrimSpace(response))

	// Extract the type using regex to be flexible
	types := regexp.MustCompile(`(constraint|informational|preference)`)
	match := types.FindString(response)
	if match != "" {
		return match, nil
	}

	return "informational", nil // Default
}
