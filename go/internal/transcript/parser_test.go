package transcript

import (
	"strings"
	"testing"
)

func Test_Parse_AssistantMessage(t *testing.T) {
	input := `{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Hello world"}]}}`

	messages, err := Parse(strings.NewReader(input))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if len(messages) != 1 {
		t.Fatalf("expected 1 message, got %d", len(messages))
	}

	if messages[0].Type != "assistant" {
		t.Errorf("expected type 'assistant', got %q", messages[0].Type)
	}

	if messages[0].Content != "Hello world" {
		t.Errorf("expected content 'Hello world', got %q", messages[0].Content)
	}
}

func Test_Parse_MultipleTextBlocks(t *testing.T) {
	input := `{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"First"},{"type":"text","text":"Second"}]}}`

	messages, err := Parse(strings.NewReader(input))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if len(messages) != 1 {
		t.Fatalf("expected 1 message, got %d", len(messages))
	}

	expected := "FirstSecond"
	if messages[0].Content != expected {
		t.Errorf("expected content %q, got %q", expected, messages[0].Content)
	}
}

func Test_Parse_SkipUserMessages(t *testing.T) {
	input := `{"type":"user","message":{"role":"user","content":[{"type":"text","text":"User input"}]}}`

	messages, err := Parse(strings.NewReader(input))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if len(messages) != 1 {
		t.Fatalf("expected 1 message, got %d", len(messages))
	}

	if messages[0].Type != "user" {
		t.Errorf("expected type 'user', got %q", messages[0].Type)
	}

	if messages[0].Content != "" {
		t.Errorf("expected empty content for user message, got %q", messages[0].Content)
	}
}

func Test_Parse_SkipThinking(t *testing.T) {
	input := `{"type":"assistant","message":{"role":"assistant","content":[{"type":"thinking","thinking":"Internal thoughts"},{"type":"text","text":"Visible response"}]}}`

	messages, err := Parse(strings.NewReader(input))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if len(messages) != 1 {
		t.Fatalf("expected 1 message, got %d", len(messages))
	}

	if messages[0].Content != "Visible response" {
		t.Errorf("expected content 'Visible response', got %q", messages[0].Content)
	}
}

func Test_Parse_MalformedLine(t *testing.T) {
	input := `not valid json
{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Valid message"}]}}
also invalid {`

	messages, err := Parse(strings.NewReader(input))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if len(messages) != 1 {
		t.Fatalf("expected 1 message (skipping malformed), got %d", len(messages))
	}

	if messages[0].Content != "Valid message" {
		t.Errorf("expected content 'Valid message', got %q", messages[0].Content)
	}
}

func Test_Parse_ProgressType(t *testing.T) {
	input := `{"type":"progress","data":{"some":"data"}}`

	messages, err := Parse(strings.NewReader(input))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if len(messages) != 1 {
		t.Fatalf("expected 1 message, got %d", len(messages))
	}

	if messages[0].Type != "progress" {
		t.Errorf("expected type 'progress', got %q", messages[0].Type)
	}

	if messages[0].Content != "" {
		t.Errorf("expected empty content for progress, got %q", messages[0].Content)
	}
}

func Test_Parse_MultipleLines(t *testing.T) {
	input := `{"type":"user","message":{"role":"user","content":[{"type":"text","text":"Question"}]}}
{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Answer"}]}}
{"type":"progress","data":{}}`

	messages, err := Parse(strings.NewReader(input))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if len(messages) != 3 {
		t.Fatalf("expected 3 messages, got %d", len(messages))
	}

	if messages[0].Type != "user" || messages[0].Content != "" {
		t.Errorf("message 0: expected user with empty content, got %q/%q", messages[0].Type, messages[0].Content)
	}

	if messages[1].Type != "assistant" || messages[1].Content != "Answer" {
		t.Errorf("message 1: expected assistant with 'Answer', got %q/%q", messages[1].Type, messages[1].Content)
	}

	if messages[2].Type != "progress" || messages[2].Content != "" {
		t.Errorf("message 2: expected progress with empty content, got %q/%q", messages[2].Type, messages[2].Content)
	}
}

func Test_ParseFrom_Offset(t *testing.T) {
	line1 := `{"type":"user","message":{"role":"user","content":[{"type":"text","text":"First"}]}}`
	line2 := `{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Second"}]}}`
	input := line1 + "\n" + line2 + "\n"

	// Parse from start to get offset after first line
	reader := strings.NewReader(input)
	messages, newOffset, err := ParseFrom(reader, 0)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if len(messages) != 2 {
		t.Fatalf("expected 2 messages from start, got %d", len(messages))
	}

	// Now parse from after first line
	offset := int64(len(line1) + 1) // +1 for newline
	reader = strings.NewReader(input)
	messages, newOffset, err = ParseFrom(reader, offset)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if len(messages) != 1 {
		t.Fatalf("expected 1 message from offset, got %d", len(messages))
	}

	if messages[0].Type != "assistant" {
		t.Errorf("expected type 'assistant', got %q", messages[0].Type)
	}

	if messages[0].Content != "Second" {
		t.Errorf("expected content 'Second', got %q", messages[0].Content)
	}

	expectedOffset := int64(len(input))
	if newOffset != expectedOffset {
		t.Errorf("expected new offset %d, got %d", expectedOffset, newOffset)
	}
}

func Test_ParseFrom_EmptyFromOffset(t *testing.T) {
	input := `{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Only line"}]}}`

	reader := strings.NewReader(input)
	offset := int64(len(input)) // Start at end

	messages, newOffset, err := ParseFrom(reader, offset)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if len(messages) != 0 {
		t.Fatalf("expected 0 messages from end offset, got %d", len(messages))
	}

	if newOffset != offset {
		t.Errorf("expected offset to remain %d, got %d", offset, newOffset)
	}
}

func Test_Parse_EmptyInput(t *testing.T) {
	messages, err := Parse(strings.NewReader(""))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if len(messages) != 0 {
		t.Fatalf("expected 0 messages, got %d", len(messages))
	}
}

func Test_Parse_EmptyLines(t *testing.T) {
	input := `
{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Content"}]}}

`

	messages, err := Parse(strings.NewReader(input))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if len(messages) != 1 {
		t.Fatalf("expected 1 message (skipping empty lines), got %d", len(messages))
	}
}

func Test_Parse_LongLine(t *testing.T) {
	// Create a line with content larger than default 64KB buffer
	longText := strings.Repeat("x", 100*1024) // 100KB
	input := `{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"` + longText + `"}]}}`

	messages, err := Parse(strings.NewReader(input))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if len(messages) != 1 {
		t.Fatalf("expected 1 message, got %d", len(messages))
	}

	if len(messages[0].Content) != len(longText) {
		t.Errorf("expected content length %d, got %d", len(longText), len(messages[0].Content))
	}
}
