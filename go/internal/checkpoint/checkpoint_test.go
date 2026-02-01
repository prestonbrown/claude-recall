package checkpoint

import (
	"path/filepath"
	"testing"
)

func Test_GetOffset_MissingFile_ReturnsZero(t *testing.T) {
	dir := t.TempDir()
	checkpointPath := filepath.Join(dir, "checkpoints.txt")

	offset, err := GetOffset(checkpointPath, "session-123")
	if err != nil {
		t.Fatalf("expected no error, got %v", err)
	}
	if offset != 0 {
		t.Fatalf("expected offset 0, got %d", offset)
	}
}

func Test_SetOffset_CreatesFile(t *testing.T) {
	dir := t.TempDir()
	checkpointPath := filepath.Join(dir, "checkpoints.txt")

	err := SetOffset(checkpointPath, "session-123", 100)
	if err != nil {
		t.Fatalf("expected no error, got %v", err)
	}

	// Verify file was created by reading it back
	offset, err := GetOffset(checkpointPath, "session-123")
	if err != nil {
		t.Fatalf("expected no error, got %v", err)
	}
	if offset != 100 {
		t.Fatalf("expected offset 100, got %d", offset)
	}
}

func Test_GetOffset_AfterSet_ReturnsValue(t *testing.T) {
	dir := t.TempDir()
	checkpointPath := filepath.Join(dir, "checkpoints.txt")

	err := SetOffset(checkpointPath, "session-abc", 500)
	if err != nil {
		t.Fatalf("expected no error, got %v", err)
	}

	offset, err := GetOffset(checkpointPath, "session-abc")
	if err != nil {
		t.Fatalf("expected no error, got %v", err)
	}
	if offset != 500 {
		t.Fatalf("expected offset 500, got %d", offset)
	}
}

func Test_SetOffset_UpdatesExisting(t *testing.T) {
	dir := t.TempDir()
	checkpointPath := filepath.Join(dir, "checkpoints.txt")

	// Set initial value
	err := SetOffset(checkpointPath, "session-xyz", 100)
	if err != nil {
		t.Fatalf("expected no error, got %v", err)
	}

	// Update to new value
	err = SetOffset(checkpointPath, "session-xyz", 200)
	if err != nil {
		t.Fatalf("expected no error, got %v", err)
	}

	offset, err := GetOffset(checkpointPath, "session-xyz")
	if err != nil {
		t.Fatalf("expected no error, got %v", err)
	}
	if offset != 200 {
		t.Fatalf("expected offset 200, got %d", offset)
	}
}

func Test_MultipleSessionIDs(t *testing.T) {
	dir := t.TempDir()
	checkpointPath := filepath.Join(dir, "checkpoints.txt")

	// Set offsets for multiple sessions
	err := SetOffset(checkpointPath, "session-1", 100)
	if err != nil {
		t.Fatalf("expected no error, got %v", err)
	}

	err = SetOffset(checkpointPath, "session-2", 200)
	if err != nil {
		t.Fatalf("expected no error, got %v", err)
	}

	err = SetOffset(checkpointPath, "session-3", 300)
	if err != nil {
		t.Fatalf("expected no error, got %v", err)
	}

	// Verify each session has correct offset
	offset1, err := GetOffset(checkpointPath, "session-1")
	if err != nil {
		t.Fatalf("expected no error, got %v", err)
	}
	if offset1 != 100 {
		t.Fatalf("expected offset 100 for session-1, got %d", offset1)
	}

	offset2, err := GetOffset(checkpointPath, "session-2")
	if err != nil {
		t.Fatalf("expected no error, got %v", err)
	}
	if offset2 != 200 {
		t.Fatalf("expected offset 200 for session-2, got %d", offset2)
	}

	offset3, err := GetOffset(checkpointPath, "session-3")
	if err != nil {
		t.Fatalf("expected no error, got %v", err)
	}
	if offset3 != 300 {
		t.Fatalf("expected offset 300 for session-3, got %d", offset3)
	}

	// Update one session and verify others unchanged
	err = SetOffset(checkpointPath, "session-2", 999)
	if err != nil {
		t.Fatalf("expected no error, got %v", err)
	}

	offset1, _ = GetOffset(checkpointPath, "session-1")
	offset2, _ = GetOffset(checkpointPath, "session-2")
	offset3, _ = GetOffset(checkpointPath, "session-3")

	if offset1 != 100 {
		t.Fatalf("expected offset 100 for session-1, got %d", offset1)
	}
	if offset2 != 999 {
		t.Fatalf("expected offset 999 for session-2, got %d", offset2)
	}
	if offset3 != 300 {
		t.Fatalf("expected offset 300 for session-3, got %d", offset3)
	}
}
