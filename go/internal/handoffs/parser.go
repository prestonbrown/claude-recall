package handoffs

import (
	"bufio"
	"fmt"
	"io"
	"os"
	"regexp"
	"strings"
	"time"

	"github.com/pbrown/claude-recall/internal/models"
)

var (
	// Header: ### [hf-a1b2c3d] Title or ### [A001] Title
	headerRegex = regexp.MustCompile(`^### \[([A-Z]\d{3}|hf-[0-9a-f]{7})\] (.+)$`)
	// Status line: - **Status**: in_progress | **Phase**: implementing | **Agent**: general-purpose
	statusRegex = regexp.MustCompile(`^- \*\*Status\*\*: (\w+) \| \*\*Phase\*\*: ([\w-]+) \| \*\*Agent\*\*: ([\w-]+)`)
	// Dates: - **Created**: 2026-01-15 | **Updated**: 2026-01-20
	datesRegex = regexp.MustCompile(`^- \*\*Created\*\*: (\d{4}-\d{2}-\d{2}) \| \*\*Updated\*\*: (\d{4}-\d{2}-\d{2})`)
	// Refs: - **Refs**: path:line | path:line
	refsRegex = regexp.MustCompile(`^- \*\*Refs\*\*: (.+)$`)
	// Description: - **Description**: text
	descRegex = regexp.MustCompile(`^- \*\*Description\*\*: (.+)$`)
	// Checkpoint: - **Checkpoint**: text
	checkpointRegex = regexp.MustCompile(`^- \*\*Checkpoint\*\*: (.+)$`)
	// Last Session: - **Last Session**: 2026-01-20
	lastSessionRegex = regexp.MustCompile(`^- \*\*Last Session\*\*: (\d{4}-\d{2}-\d{2})`)
	// Handoff context header: - **Handoff** (abc123def):
	handoffCtxRegex = regexp.MustCompile(`^- \*\*Handoff\*\* \(([a-f0-9]+)\):$`)
	// Handoff context lines
	handoffSummaryRegex  = regexp.MustCompile(`^\s+- Summary: (.+)$`)
	handoffRefsRegex     = regexp.MustCompile(`^\s+- Refs: (.+)$`)
	handoffChangesRegex  = regexp.MustCompile(`^\s+- Changes: (.+)$`)
	handoffLearningsRegex = regexp.MustCompile(`^\s+- Learnings: (.+)$`)
	handoffBlockersRegex = regexp.MustCompile(`^\s+- Blockers: (.+)$`)
	// Blocked By: - **Blocked By**: hf-xyz789, hf-abc123
	blockedByRegex = regexp.MustCompile(`^- \*\*Blocked By\*\*: (.+)$`)
	// Sessions: - **Sessions**: session-001, session-002
	sessionsRegex = regexp.MustCompile(`^- \*\*Sessions\*\*: (.+)$`)
	// Tried header
	triedHeaderRegex = regexp.MustCompile(`^\*\*Tried\*\*:$`)
	// Tried item: 1. [success] Description
	triedItemRegex = regexp.MustCompile(`^\d+\. \[(\w+)\] (.+)$`)
	// Next: **Next**: text
	nextRegex = regexp.MustCompile(`^\*\*Next\*\*: (.+)$`)
	// Separator
	separatorRegex = regexp.MustCompile(`^---$`)
)

const dateFormat = "2006-01-02"

// ParseFile reads and parses a HANDOFFS.md file
func ParseFile(path string) ([]*models.Handoff, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	return Parse(f)
}

// Parse parses HANDOFFS.md content from a reader
func Parse(r io.Reader) ([]*models.Handoff, error) {
	var handoffs []*models.Handoff
	var current *models.Handoff
	var inTried bool
	var inHandoffCtx bool

	scanner := bufio.NewScanner(r)
	for scanner.Scan() {
		line := scanner.Text()

		// Check for new handoff header
		if matches := headerRegex.FindStringSubmatch(line); matches != nil {
			if current != nil {
				handoffs = append(handoffs, current)
			}
			current = models.NewHandoff(matches[1], matches[2])
			inTried = false
			inHandoffCtx = false
			continue
		}

		if current == nil {
			continue
		}

		// Check for separator (end of handoff)
		if separatorRegex.MatchString(line) {
			if current != nil {
				handoffs = append(handoffs, current)
				current = nil
			}
			inTried = false
			inHandoffCtx = false
			continue
		}

		// Status line
		if matches := statusRegex.FindStringSubmatch(line); matches != nil {
			current.Status = matches[1]
			current.Phase = matches[2]
			current.Agent = matches[3]
			continue
		}

		// Dates line
		if matches := datesRegex.FindStringSubmatch(line); matches != nil {
			if t, err := time.Parse(dateFormat, matches[1]); err == nil {
				current.Created = t
			}
			if t, err := time.Parse(dateFormat, matches[2]); err == nil {
				current.Updated = t
			}
			continue
		}

		// Refs line
		if matches := refsRegex.FindStringSubmatch(line); matches != nil {
			refs := strings.Split(matches[1], " | ")
			for i := range refs {
				refs[i] = strings.TrimSpace(refs[i])
			}
			current.Refs = refs
			continue
		}

		// Description line
		if matches := descRegex.FindStringSubmatch(line); matches != nil {
			current.Description = matches[1]
			continue
		}

		// Checkpoint line
		if matches := checkpointRegex.FindStringSubmatch(line); matches != nil {
			current.Checkpoint = matches[1]
			continue
		}

		// Last Session line
		if matches := lastSessionRegex.FindStringSubmatch(line); matches != nil {
			if t, err := time.Parse(dateFormat, matches[1]); err == nil {
				current.LastSession = &t
			}
			continue
		}

		// Handoff context header
		if matches := handoffCtxRegex.FindStringSubmatch(line); matches != nil {
			current.Handoff = &models.HandoffContext{
				GitRef: matches[1],
			}
			inHandoffCtx = true
			continue
		}

		// Handoff context lines (when in context)
		if inHandoffCtx && current.Handoff != nil {
			if matches := handoffSummaryRegex.FindStringSubmatch(line); matches != nil {
				current.Handoff.Summary = matches[1]
				continue
			}
			if matches := handoffRefsRegex.FindStringSubmatch(line); matches != nil {
				refs := splitPipe(matches[1])
				current.Handoff.CriticalFiles = refs
				continue
			}
			if matches := handoffChangesRegex.FindStringSubmatch(line); matches != nil {
				changes := splitPipe(matches[1])
				current.Handoff.RecentChanges = changes
				continue
			}
			if matches := handoffLearningsRegex.FindStringSubmatch(line); matches != nil {
				learnings := splitPipe(matches[1])
				current.Handoff.Learnings = learnings
				continue
			}
			if matches := handoffBlockersRegex.FindStringSubmatch(line); matches != nil {
				blockers := splitPipe(matches[1])
				current.Handoff.Blockers = blockers
				continue
			}
			// If line doesn't start with spaces, we're out of context
			if !strings.HasPrefix(line, "  ") && line != "" {
				inHandoffCtx = false
			}
		}

		// Blocked By line
		if matches := blockedByRegex.FindStringSubmatch(line); matches != nil {
			blockedBy := splitComma(matches[1])
			current.BlockedBy = blockedBy
			continue
		}

		// Sessions line
		if matches := sessionsRegex.FindStringSubmatch(line); matches != nil {
			sessions := splitComma(matches[1])
			current.Sessions = sessions
			continue
		}

		// Tried header
		if triedHeaderRegex.MatchString(line) {
			inTried = true
			continue
		}

		// Tried items
		if inTried {
			if matches := triedItemRegex.FindStringSubmatch(line); matches != nil {
				current.Tried = append(current.Tried, models.TriedStep{
					Outcome:     matches[1],
					Description: matches[2],
				})
				continue
			}
			// Empty line or non-matching line ends tried section
			if line == "" || !strings.HasPrefix(line, " ") {
				// Don't end on empty line, only on next section
			}
		}

		// Next line
		if matches := nextRegex.FindStringSubmatch(line); matches != nil {
			current.NextSteps = matches[1]
			inTried = false
			continue
		}
	}

	if err := scanner.Err(); err != nil {
		return nil, err
	}

	// Don't forget the last handoff if no trailing separator
	if current != nil {
		handoffs = append(handoffs, current)
	}

	return handoffs, nil
}

// Serialize writes handoffs back to HANDOFFS.md format
func Serialize(handoffs []*models.Handoff) string {
	var sb strings.Builder

	sb.WriteString("# HANDOFFS.md - Active Work Tracking\n\n")
	sb.WriteString("> Track ongoing work with tried steps and next steps.\n")
	sb.WriteString("> When completed, review for lessons to extract.\n\n")
	sb.WriteString("## Active Handoffs\n\n")

	for _, h := range handoffs {
		sb.WriteString(SerializeHandoff(h))
	}

	return sb.String()
}

// SerializeHandoff formats a single handoff entry
func SerializeHandoff(h *models.Handoff) string {
	var sb strings.Builder

	// Header
	sb.WriteString(fmt.Sprintf("### [%s] %s\n", h.ID, h.Title))

	// Status line
	sb.WriteString(fmt.Sprintf("- **Status**: %s | **Phase**: %s | **Agent**: %s\n",
		h.Status, h.Phase, h.Agent))

	// Dates
	sb.WriteString(fmt.Sprintf("- **Created**: %s | **Updated**: %s\n",
		h.Created.Format(dateFormat), h.Updated.Format(dateFormat)))

	// Refs (optional)
	if len(h.Refs) > 0 {
		sb.WriteString(fmt.Sprintf("- **Refs**: %s\n", strings.Join(h.Refs, " | ")))
	}

	// Description
	sb.WriteString(fmt.Sprintf("- **Description**: %s\n", h.Description))

	// Checkpoint (optional)
	if h.Checkpoint != "" {
		sb.WriteString(fmt.Sprintf("- **Checkpoint**: %s\n", h.Checkpoint))
	}

	// Last Session (optional)
	if h.LastSession != nil {
		sb.WriteString(fmt.Sprintf("- **Last Session**: %s\n", h.LastSession.Format(dateFormat)))
	}

	// Handoff context (optional)
	if h.Handoff != nil {
		sb.WriteString(fmt.Sprintf("- **Handoff** (%s):\n", h.Handoff.GitRef))
		if h.Handoff.Summary != "" {
			sb.WriteString(fmt.Sprintf("  - Summary: %s\n", h.Handoff.Summary))
		}
		if len(h.Handoff.CriticalFiles) > 0 {
			sb.WriteString(fmt.Sprintf("  - Refs: %s\n", strings.Join(h.Handoff.CriticalFiles, " | ")))
		}
		if len(h.Handoff.RecentChanges) > 0 {
			sb.WriteString(fmt.Sprintf("  - Changes: %s\n", strings.Join(h.Handoff.RecentChanges, " | ")))
		}
		if len(h.Handoff.Learnings) > 0 {
			sb.WriteString(fmt.Sprintf("  - Learnings: %s\n", strings.Join(h.Handoff.Learnings, " | ")))
		}
		if len(h.Handoff.Blockers) > 0 {
			sb.WriteString(fmt.Sprintf("  - Blockers: %s\n", strings.Join(h.Handoff.Blockers, " | ")))
		}
	}

	// Blocked By (optional)
	if len(h.BlockedBy) > 0 {
		sb.WriteString(fmt.Sprintf("- **Blocked By**: %s\n", strings.Join(h.BlockedBy, ", ")))
	}

	// Sessions (optional)
	if len(h.Sessions) > 0 {
		sb.WriteString(fmt.Sprintf("- **Sessions**: %s\n", strings.Join(h.Sessions, ", ")))
	}

	// Tried section
	if len(h.Tried) > 0 {
		sb.WriteString("\n**Tried**:\n")
		for i, step := range h.Tried {
			sb.WriteString(fmt.Sprintf("%d. [%s] %s\n", i+1, step.Outcome, step.Description))
		}
	}

	// Next steps
	sb.WriteString(fmt.Sprintf("\n**Next**: %s\n", h.NextSteps))

	// Separator
	sb.WriteString("\n---\n")

	return sb.String()
}

// splitPipe splits a string by " | " and trims whitespace
func splitPipe(s string) []string {
	parts := strings.Split(s, " | ")
	result := make([]string, 0, len(parts))
	for _, p := range parts {
		p = strings.TrimSpace(p)
		if p != "" {
			result = append(result, p)
		}
	}
	return result
}

// splitComma splits a string by ", " and trims whitespace
func splitComma(s string) []string {
	parts := strings.Split(s, ", ")
	result := make([]string, 0, len(parts))
	for _, p := range parts {
		p = strings.TrimSpace(p)
		if p != "" {
			result = append(result, p)
		}
	}
	return result
}
