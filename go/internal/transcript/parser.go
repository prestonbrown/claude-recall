package transcript

import (
	"bufio"
	"encoding/json"
	"io"
	"strings"
)

// Message represents a parsed transcript line.
type Message struct {
	Type      string   // "user", "assistant", "progress", etc.
	Content   string   // Extracted text content (empty for non-assistant)
	FilePaths []string // File paths from tool_use blocks (Read, Edit, Write, Glob, Grep)
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
	Type     string          `json:"type"`
	Text     string          `json:"text,omitempty"`
	Thinking string          `json:"thinking,omitempty"`
	Name     string          `json:"name,omitempty"`
	Input    json.RawMessage `json:"input,omitempty"`
}

// toolInput holds the file-path fields present in various tool_use inputs.
// Read/Edit/Write/Glob use "file_path"; Grep uses "path".
type toolInput struct {
	FilePath string `json:"file_path"`
	Path     string `json:"path"`
}

// extractFilePath returns the file path from a tool_use content block, or
// empty string if the block is not a tool_use or carries no path.
func extractFilePath(block contentBlock) string {
	if block.Type != "tool_use" || len(block.Input) == 0 {
		return ""
	}
	var ti toolInput
	if err := json.Unmarshal(block.Input, &ti); err != nil {
		return ""
	}
	if ti.FilePath != "" {
		return ti.FilePath
	}
	return ti.Path
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
		seen := make(map[string]bool)
		for _, block := range tl.Message.Content {
			switch block.Type {
			case "text":
				// Only include text blocks, not thinking blocks
				content.WriteString(block.Text)
			case "tool_use":
				if fp := extractFilePath(block); fp != "" && !seen[fp] {
					msg.FilePaths = append(msg.FilePaths, fp)
					seen[fp] = true
				}
			}
		}
		msg.Content = content.String()
	}

	return msg, true
}
