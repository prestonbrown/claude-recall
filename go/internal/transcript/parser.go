package transcript

import (
	"bufio"
	"encoding/json"
	"io"
	"strings"
)

// Message represents a parsed transcript line.
type Message struct {
	Type    string // "user", "assistant", "progress", etc.
	Content string // Extracted text content (empty for non-assistant)
}

// transcriptLine is the top-level structure of a transcript JSONL line.
type transcriptLine struct {
	Type    string          `json:"type"`
	Message *messagePayload `json:"message,omitempty"`
}

// messagePayload is the message field within a transcript line.
type messagePayload struct {
	Role    string         `json:"role"`
	Content []contentBlock `json:"content"`
}

// contentBlock represents a content block within a message.
type contentBlock struct {
	Type     string `json:"type"`
	Text     string `json:"text,omitempty"`
	Thinking string `json:"thinking,omitempty"`
}

// MaxLineSize is the maximum buffer size for transcript lines (1MB).
// Transcript lines with very long assistant responses could exceed the default 64KB limit.
const MaxLineSize = 1024 * 1024

// Parse reads a JSONL transcript from the reader and returns all messages.
// Malformed lines are skipped without error.
func Parse(r io.Reader) ([]Message, error) {
	var messages []Message
	scanner := bufio.NewScanner(r)
	// Set buffer to handle large transcript lines
	buf := make([]byte, 0, MaxLineSize)
	scanner.Buffer(buf, MaxLineSize)

	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}

		msg, ok := parseLine(line)
		if ok {
			messages = append(messages, msg)
		}
	}

	if err := scanner.Err(); err != nil {
		return nil, err
	}

	return messages, nil
}

// ParseFrom reads a JSONL transcript starting from the given byte offset.
// Returns the parsed messages and the new offset after parsing.
func ParseFrom(r io.ReadSeeker, offset int64) ([]Message, int64, error) {
	// Seek to the offset
	_, err := r.Seek(offset, io.SeekStart)
	if err != nil {
		return nil, offset, err
	}

	var messages []Message
	scanner := bufio.NewScanner(r)
	// Set buffer to handle large transcript lines
	buf := make([]byte, 0, MaxLineSize)
	scanner.Buffer(buf, MaxLineSize)
	currentOffset := offset

	for scanner.Scan() {
		line := scanner.Text()
		lineLen := int64(len(line)) + 1 // +1 for newline

		trimmed := strings.TrimSpace(line)
		if trimmed == "" {
			currentOffset += lineLen
			continue
		}

		msg, ok := parseLine(trimmed)
		if ok {
			messages = append(messages, msg)
		}
		currentOffset += lineLen
	}

	if err := scanner.Err(); err != nil {
		return nil, currentOffset, err
	}

	return messages, currentOffset, nil
}

// parseLine attempts to parse a single JSONL line into a Message.
// Returns false if the line is malformed or cannot be parsed.
func parseLine(line string) (Message, bool) {
	var tl transcriptLine
	if err := json.Unmarshal([]byte(line), &tl); err != nil {
		return Message{}, false
	}

	msg := Message{
		Type: tl.Type,
	}

	// Only extract content from assistant messages
	if tl.Type == "assistant" && tl.Message != nil {
		var content strings.Builder
		for _, block := range tl.Message.Content {
			// Only include text blocks, not thinking blocks
			if block.Type == "text" {
				content.WriteString(block.Text)
			}
		}
		msg.Content = content.String()
	}

	return msg, true
}
