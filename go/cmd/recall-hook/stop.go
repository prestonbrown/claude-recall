package main

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	"github.com/pbrown/claude-recall/internal/checkpoint"
	"github.com/pbrown/claude-recall/internal/citations"
	"github.com/pbrown/claude-recall/internal/config"
	"github.com/pbrown/claude-recall/internal/transcript"
)

// stopInput matches the JSON input format from Claude Code
type stopInput struct {
	Cwd            string `json:"cwd"`
	SessionID      string `json:"session_id"`
	TranscriptPath string `json:"transcript_path"`
}

// stopOutput matches the JSON output format
type stopOutput struct {
	Citations         []string `json:"citations"`
	MessagesProcessed int      `json:"messages_processed"`
}

// runStop implements the stop hook command.
func runStop() int {
	// Load config to get state directory
	cfg, err := config.Load("")
	if err != nil {
		fmt.Fprintf(os.Stderr, "error loading config: %v\n", err)
		return 1
	}

	// Parse input from stdin
	input, err := parseStopInput(os.Stdin)
	if err != nil {
		fmt.Fprintf(os.Stderr, "error parsing input: %v\n", err)
		return 1
	}

	// Execute the stop hook
	result, err := executeStop(input, cfg.StateDir)
	if err != nil {
		fmt.Fprintf(os.Stderr, "error executing stop: %v\n", err)
		return 1
	}

	// Output JSON result
	outputBytes, err := json.Marshal(result)
	if err != nil {
		fmt.Fprintf(os.Stderr, "error marshaling output: %v\n", err)
		return 1
	}

	fmt.Println(string(outputBytes))
	return 0
}

// parseStopInput reads and parses the JSON input from the reader.
func parseStopInput(r io.Reader) (stopInput, error) {
	var input stopInput
	decoder := json.NewDecoder(r)
	if err := decoder.Decode(&input); err != nil {
		return stopInput{}, fmt.Errorf("failed to decode JSON input: %w", err)
	}
	return input, nil
}

// expandTilde expands ~ to the user's home directory.
func expandTilde(path string) string {
	if path == "" {
		return ""
	}
	if path == "~" {
		homeDir, err := os.UserHomeDir()
		if err != nil {
			return path
		}
		return homeDir
	}
	if strings.HasPrefix(path, "~/") {
		homeDir, err := os.UserHomeDir()
		if err != nil {
			return path
		}
		return filepath.Join(homeDir, path[2:])
	}
	return path
}

// executeStop performs the stop hook logic.
func executeStop(input stopInput, stateDir string) (stopOutput, error) {
	// Expand tilde in transcript path
	transcriptPath := expandTilde(input.TranscriptPath)

	// Ensure state directory exists
	if err := os.MkdirAll(stateDir, 0755); err != nil {
		return stopOutput{}, fmt.Errorf("failed to create state dir: %w", err)
	}

	// Get checkpoint offset for this session
	checkpointPath := filepath.Join(stateDir, "checkpoints.txt")
	offset, err := checkpoint.GetOffset(checkpointPath, input.SessionID)
	if err != nil {
		return stopOutput{}, fmt.Errorf("failed to get checkpoint: %w", err)
	}

	// Open transcript file
	file, err := os.Open(transcriptPath)
	if err != nil {
		return stopOutput{}, fmt.Errorf("failed to open transcript: %w", err)
	}
	defer file.Close()

	// Parse transcript from offset
	messages, newOffset, err := transcript.ParseFrom(file, offset)
	if err != nil {
		return stopOutput{}, fmt.Errorf("failed to parse transcript: %w", err)
	}

	// Extract citations from assistant messages
	extractedCitations := citations.ExtractFromMessages(messages)

	// Convert to string slice of IDs
	citationIDs := make([]string, 0, len(extractedCitations))
	for _, c := range extractedCitations {
		citationIDs = append(citationIDs, c.ID)
	}

	// Update checkpoint
	if err := checkpoint.SetOffset(checkpointPath, input.SessionID, newOffset); err != nil {
		return stopOutput{}, fmt.Errorf("failed to update checkpoint: %w", err)
	}

	return stopOutput{
		Citations:         citationIDs,
		MessagesProcessed: len(messages),
	}, nil
}
