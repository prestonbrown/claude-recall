package checkpoint

import (
	"bufio"
	"fmt"
	"os"
	"strconv"
	"strings"
)

// GetOffset returns the byte offset for a session ID from the checkpoint file.
// Returns 0 if the file doesn't exist or the session ID is not found.
func GetOffset(checkpointPath, sessionID string) (int64, error) {
	file, err := os.Open(checkpointPath)
	if os.IsNotExist(err) {
		return 0, nil
	}
	if err != nil {
		return 0, err
	}
	defer file.Close()

	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		line := scanner.Text()
		parts := strings.SplitN(line, " ", 2)
		if len(parts) == 2 && parts[0] == sessionID {
			offset, err := strconv.ParseInt(parts[1], 10, 64)
			if err != nil {
				return 0, err
			}
			return offset, nil
		}
	}

	if err := scanner.Err(); err != nil {
		return 0, err
	}

	return 0, nil
}

// SetOffset saves the byte offset for a session ID to the checkpoint file.
// Creates the file if it doesn't exist, updates the line if the session exists.
// Uses atomic write (write to temp file, then rename) to prevent race conditions.
func SetOffset(checkpointPath, sessionID string, offset int64) error {
	// Read existing entries
	entries := make(map[string]int64)

	file, err := os.Open(checkpointPath)
	if err == nil {
		scanner := bufio.NewScanner(file)
		for scanner.Scan() {
			line := scanner.Text()
			parts := strings.SplitN(line, " ", 2)
			if len(parts) == 2 {
				existingOffset, err := strconv.ParseInt(parts[1], 10, 64)
				if err == nil {
					entries[parts[0]] = existingOffset
				}
			}
		}
		file.Close()
		if err := scanner.Err(); err != nil {
			return err
		}
	} else if !os.IsNotExist(err) {
		return err
	}

	// Update or add the entry
	entries[sessionID] = offset

	// Write to temp file first (atomic write pattern)
	tmpPath := checkpointPath + ".tmp"
	outFile, err := os.Create(tmpPath)
	if err != nil {
		return err
	}

	for sid, off := range entries {
		_, err := fmt.Fprintf(outFile, "%s %d\n", sid, off)
		if err != nil {
			outFile.Close()
			os.Remove(tmpPath)
			return err
		}
	}

	if err := outFile.Close(); err != nil {
		os.Remove(tmpPath)
		return err
	}

	// Atomic rename
	return os.Rename(tmpPath, checkpointPath)
}
