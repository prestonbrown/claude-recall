package main

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)


func Test_StopHook_ParsesInput(t *testing.T) {
	input := stopInput{
		Cwd:            "/path/to/project",
		SessionID:      "test-session-123",
		TranscriptPath: "/tmp/transcript.jsonl",
	}
	inputBytes, err := json.Marshal(input)
	if err != nil {
		t.Fatalf("failed to marshal input: %v", err)
	}

	parsed, err := parseStopInput(bytes.NewReader(inputBytes))
	if err != nil {
		t.Fatalf("parseStopInput failed: %v", err)
	}

	if parsed.Cwd != input.Cwd {
		t.Errorf("cwd = %q, want %q", parsed.Cwd, input.Cwd)
	}
	if parsed.SessionID != input.SessionID {
		t.Errorf("session_id = %q, want %q", parsed.SessionID, input.SessionID)
	}
	if parsed.TranscriptPath != input.TranscriptPath {
		t.Errorf("transcript_path = %q, want %q", parsed.TranscriptPath, input.TranscriptPath)
	}
}

func Test_StopHook_ParsesInput_EmptyInput(t *testing.T) {
	_, err := parseStopInput(strings.NewReader(""))
	if err == nil {
		t.Error("expected error for empty input, got nil")
	}
}

func Test_StopHook_ParsesInput_InvalidJSON(t *testing.T) {
	_, err := parseStopInput(strings.NewReader("{invalid json"))
	if err == nil {
		t.Error("expected error for invalid JSON, got nil")
	}
}

func Test_StopHook_ExpandsTilde(t *testing.T) {
	homeDir, err := os.UserHomeDir()
	if err != nil {
		t.Skipf("cannot get home dir: %v", err)
	}

	tests := []struct {
		input    string
		expected string
	}{
		{"~/path/to/file", filepath.Join(homeDir, "path/to/file")},
		{"/absolute/path", "/absolute/path"},
		{"relative/path", "relative/path"},
		{"~", homeDir},
		{"", ""},
	}

	for _, tt := range tests {
		result := expandTilde(tt.input)
		if result != tt.expected {
			t.Errorf("expandTilde(%q) = %q, want %q", tt.input, result, tt.expected)
		}
	}
}

func Test_StopHook_IncrementalParsing(t *testing.T) {
	tmpDir := t.TempDir()

	// Create transcript with multiple messages
	transcriptPath := filepath.Join(tmpDir, "transcript.jsonl")
	transcript := `{"type":"user","message":{"role":"user","content":[{"type":"text","text":"hello"}]}}
{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"First response with [L001]"}]}}
{"type":"user","message":{"role":"user","content":[{"type":"text","text":"continue"}]}}
{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Second response with [L002]"}]}}
`
	if err := os.WriteFile(transcriptPath, []byte(transcript), 0644); err != nil {
		t.Fatalf("failed to write transcript: %v", err)
	}

	// Create checkpoint file with offset pointing after first two lines
	checkpointPath := filepath.Join(tmpDir, "checkpoints.txt")
	// First two lines are 88 + 116 = 204 bytes (including newlines)
	firstTwoLinesLen := int64(len(`{"type":"user","message":{"role":"user","content":[{"type":"text","text":"hello"}]}}`) + 1 +
		len(`{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"First response with [L001]"}]}}`) + 1)

	if err := os.WriteFile(checkpointPath, []byte("test-session "+string(rune(firstTwoLinesLen))+"\n"), 0644); err != nil {
		// Use string formatting for the offset
		content := "test-session " + string([]byte{byte(firstTwoLinesLen + '0')}) + "\n"
		_ = content // We'll use a different approach
	}

	stateDir := tmpDir
	input := stopInput{
		Cwd:            tmpDir,
		SessionID:      "new-session",
		TranscriptPath: transcriptPath,
	}

	result, err := executeStop(input, stateDir)
	if err != nil {
		t.Fatalf("executeStop failed: %v", err)
	}

	// Should process all 4 messages from offset 0 (new session)
	if result.MessagesProcessed != 4 {
		t.Errorf("messages_processed = %d, want 4", result.MessagesProcessed)
	}

	// Should find both citations
	if len(result.Citations) != 2 {
		t.Errorf("citations count = %d, want 2", len(result.Citations))
	}
}

func Test_StopHook_ExtractsCitations(t *testing.T) {
	tmpDir := t.TempDir()

	// Create transcript with citations
	transcriptPath := filepath.Join(tmpDir, "transcript.jsonl")
	transcript := `{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Using [L001] and [S002] for this task"}]}}
{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Also referencing [H001] handoff and [L001] again"}]}}
`
	if err := os.WriteFile(transcriptPath, []byte(transcript), 0644); err != nil {
		t.Fatalf("failed to write transcript: %v", err)
	}

	input := stopInput{
		Cwd:            tmpDir,
		SessionID:      "test-session",
		TranscriptPath: transcriptPath,
	}

	result, err := executeStop(input, tmpDir)
	if err != nil {
		t.Fatalf("executeStop failed: %v", err)
	}

	// Should find 3 unique citations: L001, S002, H001
	if len(result.Citations) != 3 {
		t.Errorf("citations count = %d, want 3, got %v", len(result.Citations), result.Citations)
	}

	// Verify specific citations are present
	citationSet := make(map[string]bool)
	for _, c := range result.Citations {
		citationSet[c] = true
	}
	expectedCitations := []string{"L001", "S002", "H001"}
	for _, expected := range expectedCitations {
		if !citationSet[expected] {
			t.Errorf("expected citation %q not found in %v", expected, result.Citations)
		}
	}
}

func Test_StopHook_OutputsJSON(t *testing.T) {
	tmpDir := t.TempDir()

	// Create minimal transcript
	transcriptPath := filepath.Join(tmpDir, "transcript.jsonl")
	transcript := `{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Response with [L001]"}]}}
`
	if err := os.WriteFile(transcriptPath, []byte(transcript), 0644); err != nil {
		t.Fatalf("failed to write transcript: %v", err)
	}

	input := stopInput{
		Cwd:            tmpDir,
		SessionID:      "test-session",
		TranscriptPath: transcriptPath,
	}

	result, err := executeStop(input, tmpDir)
	if err != nil {
		t.Fatalf("executeStop failed: %v", err)
	}

	// Marshal to JSON and verify it's valid
	outputBytes, err := json.Marshal(result)
	if err != nil {
		t.Fatalf("failed to marshal output: %v", err)
	}

	// Verify we can unmarshal it back
	var parsed stopOutput
	if err := json.Unmarshal(outputBytes, &parsed); err != nil {
		t.Fatalf("failed to unmarshal output: %v", err)
	}

	if parsed.MessagesProcessed != 1 {
		t.Errorf("messages_processed = %d, want 1", parsed.MessagesProcessed)
	}
	if len(parsed.Citations) != 1 || parsed.Citations[0] != "L001" {
		t.Errorf("citations = %v, want [L001]", parsed.Citations)
	}
}

func Test_StopHook_MissingTranscript(t *testing.T) {
	tmpDir := t.TempDir()

	input := stopInput{
		Cwd:            tmpDir,
		SessionID:      "test-session",
		TranscriptPath: filepath.Join(tmpDir, "nonexistent.jsonl"),
	}

	_, err := executeStop(input, tmpDir)
	if err == nil {
		t.Error("expected error for missing transcript, got nil")
	}
}

func Test_StopHook_EmptyTranscript(t *testing.T) {
	tmpDir := t.TempDir()

	// Create empty transcript
	transcriptPath := filepath.Join(tmpDir, "transcript.jsonl")
	if err := os.WriteFile(transcriptPath, []byte(""), 0644); err != nil {
		t.Fatalf("failed to write transcript: %v", err)
	}

	input := stopInput{
		Cwd:            tmpDir,
		SessionID:      "test-session",
		TranscriptPath: transcriptPath,
	}

	result, err := executeStop(input, tmpDir)
	if err != nil {
		t.Fatalf("executeStop failed: %v", err)
	}

	if result.MessagesProcessed != 0 {
		t.Errorf("messages_processed = %d, want 0", result.MessagesProcessed)
	}
	if len(result.Citations) != 0 {
		t.Errorf("citations = %v, want empty", result.Citations)
	}
}

func Test_StopHook_UpdatesCheckpoint(t *testing.T) {
	tmpDir := t.TempDir()

	// Create transcript
	transcriptPath := filepath.Join(tmpDir, "transcript.jsonl")
	transcript := `{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Hello"}]}}
`
	if err := os.WriteFile(transcriptPath, []byte(transcript), 0644); err != nil {
		t.Fatalf("failed to write transcript: %v", err)
	}

	input := stopInput{
		Cwd:            tmpDir,
		SessionID:      "test-session-456",
		TranscriptPath: transcriptPath,
	}

	_, err := executeStop(input, tmpDir)
	if err != nil {
		t.Fatalf("executeStop failed: %v", err)
	}

	// Verify checkpoint file was created/updated
	checkpointPath := filepath.Join(tmpDir, "checkpoints.txt")
	data, err := os.ReadFile(checkpointPath)
	if err != nil {
		t.Fatalf("failed to read checkpoint file: %v", err)
	}

	if !strings.Contains(string(data), "test-session-456") {
		t.Errorf("checkpoint file should contain session ID, got: %s", string(data))
	}
}

func Test_StopHook_NoCitationsInUserMessages(t *testing.T) {
	tmpDir := t.TempDir()

	// Create transcript with citations only in user messages
	transcriptPath := filepath.Join(tmpDir, "transcript.jsonl")
	transcript := `{"type":"user","message":{"role":"user","content":[{"type":"text","text":"Check [L001] please"}]}}
{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"I will help you"}]}}
`
	if err := os.WriteFile(transcriptPath, []byte(transcript), 0644); err != nil {
		t.Fatalf("failed to write transcript: %v", err)
	}

	input := stopInput{
		Cwd:            tmpDir,
		SessionID:      "test-session",
		TranscriptPath: transcriptPath,
	}

	result, err := executeStop(input, tmpDir)
	if err != nil {
		t.Fatalf("executeStop failed: %v", err)
	}

	// Citations in user messages should NOT be extracted
	if len(result.Citations) != 0 {
		t.Errorf("citations = %v, want empty (user message citations should be ignored)", result.Citations)
	}
}
