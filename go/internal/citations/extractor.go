package citations

import (
	"regexp"

	"github.com/pbrown/claude-recall/internal/transcript"
)

// Citation represents a lesson or handoff citation.
type Citation struct {
	Type string // "L", "S", or "H"
	ID   string // Full ID like "L001", "S002", "H001"
}

// citationPattern matches valid citations: [L001], [S002], [H001]
// Uses word boundary to ensure we match the full pattern
var citationPattern = regexp.MustCompile(`\[([LSH])(\d{3})\]`)

// Extract extracts all valid citations from text.
// It filters out star ratings, numeric patterns, and template text.
// Returns deduplicated citations in order of first occurrence.
func Extract(text string) []Citation {
	if text == "" {
		return nil
	}

	matches := citationPattern.FindAllStringSubmatch(text, -1)
	if len(matches) == 0 {
		return nil
	}

	seen := make(map[string]bool)
	var citations []Citation

	for _, match := range matches {
		// match[0] is full match like "[L001]"
		// match[1] is type like "L"
		// match[2] is digits like "001"
		citationType := match[1]
		id := citationType + match[2]

		// Skip if already seen (deduplicate)
		if seen[id] {
			continue
		}
		seen[id] = true

		citations = append(citations, Citation{
			Type: citationType,
			ID:   id,
		})
	}

	return citations
}

// ExtractFromMessages extracts citations from a slice of transcript messages.
// Only processes assistant messages. Returns deduplicated citations.
func ExtractFromMessages(messages []transcript.Message) []Citation {
	seen := make(map[string]bool)
	var citations []Citation

	for _, msg := range messages {
		if msg.Type != "assistant" {
			continue
		}

		msgCitations := Extract(msg.Content)
		for _, c := range msgCitations {
			if seen[c.ID] {
				continue
			}
			seen[c.ID] = true
			citations = append(citations, c)
		}
	}

	return citations
}
