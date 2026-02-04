package main

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/pbrown/claude-recall/internal/handoffs"
	"github.com/pbrown/claude-recall/internal/lessons"
)

// ============================================================================
// TestOpencodeSessionStart - Tests for the opencode session-start command
// ============================================================================

func TestOpencodeSessionStart_ReturnsJSONOutput(t *testing.T) {
	tmpDir := t.TempDir()
	projectDir := filepath.Join(tmpDir, "project", ".claude-recall")
	systemDir := filepath.Join(tmpDir, "system")
	stateDir := filepath.Join(tmpDir, "state")
	os.MkdirAll(projectDir, 0755)
	os.MkdirAll(systemDir, 0755)
	os.MkdirAll(stateDir, 0755)

	projectPath := filepath.Join(projectDir, "LESSONS.md")
	systemPath := filepath.Join(systemDir, "LESSONS.md")
	handoffsPath := filepath.Join(projectDir, "HANDOFFS.md")
	stealthPath := filepath.Join(projectDir, "HANDOFFS_LOCAL.md")

	// Create test lessons
	store := lessons.NewStore(projectPath, systemPath)
	store.Add("project", "pattern", "Test Lesson", "Test content")

	// Prepare JSON input
	input := map[string]interface{}{
		"cwd":            filepath.Dir(projectDir),
		"top_n":          5,
		"include_duties": true,
		"include_todos":  true,
	}
	inputJSON, _ := json.Marshal(input)

	var stdout, stderr bytes.Buffer
	app := NewApp()
	app.stdout = &stdout
	app.stderr = &stderr
	app.projectPath = projectPath
	app.systemPath = systemPath
	app.handoffsPath = handoffsPath
	app.stealthPath = stealthPath
	app.stateDir = stateDir

	// Run with stdin
	exitCode := app.runOpencodeSessionStart(strings.NewReader(string(inputJSON)))

	if exitCode != 0 {
		t.Errorf("expected exit code 0, got %d. stderr: %s", exitCode, stderr.String())
	}

	// Parse output JSON
	var result map[string]interface{}
	if err := json.Unmarshal(stdout.Bytes(), &result); err != nil {
		t.Fatalf("failed to parse output JSON: %v. output: %s", err, stdout.String())
	}

	// Should contain expected fields
	if _, ok := result["lessons_context"]; !ok {
		t.Error("expected 'lessons_context' in result")
	}
	if _, ok := result["handoffs_context"]; !ok {
		t.Error("expected 'handoffs_context' in result")
	}
	if _, ok := result["todos_prompt"]; !ok {
		t.Error("expected 'todos_prompt' in result")
	}
	if _, ok := result["duty_reminders"]; !ok {
		t.Error("expected 'duty_reminders' in result")
	}
}

func TestOpencodeSessionStart_EmptyLessonsReturnsEmptyString(t *testing.T) {
	tmpDir := t.TempDir()
	projectDir := filepath.Join(tmpDir, "project", ".claude-recall")
	systemDir := filepath.Join(tmpDir, "system")
	stateDir := filepath.Join(tmpDir, "state")
	os.MkdirAll(projectDir, 0755)
	os.MkdirAll(systemDir, 0755)
	os.MkdirAll(stateDir, 0755)

	projectPath := filepath.Join(projectDir, "LESSONS.md")
	systemPath := filepath.Join(systemDir, "LESSONS.md")
	handoffsPath := filepath.Join(projectDir, "HANDOFFS.md")
	stealthPath := filepath.Join(projectDir, "HANDOFFS_LOCAL.md")

	// No lessons created - test empty state

	input := map[string]interface{}{
		"cwd":            filepath.Dir(projectDir),
		"top_n":          5,
		"include_duties": true,
		"include_todos":  true,
	}
	inputJSON, _ := json.Marshal(input)

	var stdout, stderr bytes.Buffer
	app := NewApp()
	app.stdout = &stdout
	app.stderr = &stderr
	app.projectPath = projectPath
	app.systemPath = systemPath
	app.handoffsPath = handoffsPath
	app.stealthPath = stealthPath
	app.stateDir = stateDir

	exitCode := app.runOpencodeSessionStart(strings.NewReader(string(inputJSON)))

	if exitCode != 0 {
		t.Errorf("expected exit code 0, got %d", exitCode)
	}

	var result map[string]interface{}
	json.Unmarshal(stdout.Bytes(), &result)

	// lessons_context should be empty string (not error)
	lessonsContext, ok := result["lessons_context"].(string)
	if !ok {
		t.Error("expected lessons_context to be a string")
	}
	if lessonsContext != "" {
		t.Errorf("expected empty lessons_context, got '%s'", lessonsContext)
	}
}

func TestOpencodeSessionStart_DutyRemindersAlwaysPresent(t *testing.T) {
	tmpDir := t.TempDir()
	projectDir := filepath.Join(tmpDir, "project", ".claude-recall")
	systemDir := filepath.Join(tmpDir, "system")
	stateDir := filepath.Join(tmpDir, "state")
	os.MkdirAll(projectDir, 0755)
	os.MkdirAll(systemDir, 0755)
	os.MkdirAll(stateDir, 0755)

	projectPath := filepath.Join(projectDir, "LESSONS.md")
	systemPath := filepath.Join(systemDir, "LESSONS.md")
	handoffsPath := filepath.Join(projectDir, "HANDOFFS.md")
	stealthPath := filepath.Join(projectDir, "HANDOFFS_LOCAL.md")

	input := map[string]interface{}{
		"cwd":            filepath.Dir(projectDir),
		"top_n":          5,
		"include_duties": true,
		"include_todos":  true,
	}
	inputJSON, _ := json.Marshal(input)

	var stdout bytes.Buffer
	app := NewApp()
	app.stdout = &stdout
	app.projectPath = projectPath
	app.systemPath = systemPath
	app.handoffsPath = handoffsPath
	app.stealthPath = stealthPath
	app.stateDir = stateDir

	app.runOpencodeSessionStart(strings.NewReader(string(inputJSON)))

	var result map[string]interface{}
	json.Unmarshal(stdout.Bytes(), &result)

	// duty_reminders should always be present when include_duties=true
	dutyReminders, ok := result["duty_reminders"].(string)
	if !ok {
		t.Error("expected duty_reminders to be a string")
	}
	if dutyReminders == "" {
		t.Error("expected duty_reminders to be non-empty when include_duties=true")
	}
	if !strings.Contains(dutyReminders, "LESSON DUTY") {
		t.Error("expected duty_reminders to contain 'LESSON DUTY'")
	}
}

func TestOpencodeSessionStart_ReadyForReviewTriggersLessonReviewDuty(t *testing.T) {
	tmpDir := t.TempDir()
	projectDir := filepath.Join(tmpDir, "project", ".claude-recall")
	systemDir := filepath.Join(tmpDir, "system")
	stateDir := filepath.Join(tmpDir, "state")
	os.MkdirAll(projectDir, 0755)
	os.MkdirAll(systemDir, 0755)
	os.MkdirAll(stateDir, 0755)

	projectPath := filepath.Join(projectDir, "LESSONS.md")
	systemPath := filepath.Join(systemDir, "LESSONS.md")
	handoffsPath := filepath.Join(projectDir, "HANDOFFS.md")
	stealthPath := filepath.Join(projectDir, "HANDOFFS_LOCAL.md")

	// Create a handoff with ready_for_review status
	hStore := handoffs.NewStore(handoffsPath, stealthPath)
	h, _ := hStore.Add("Review Handoff", "Needs review", false)
	hStore.Update(h.ID, map[string]interface{}{"status": "ready_for_review"})

	input := map[string]interface{}{
		"cwd":            filepath.Dir(projectDir),
		"top_n":          5,
		"include_duties": true,
		"include_todos":  true,
	}
	inputJSON, _ := json.Marshal(input)

	var stdout bytes.Buffer
	app := NewApp()
	app.stdout = &stdout
	app.projectPath = projectPath
	app.systemPath = systemPath
	app.handoffsPath = handoffsPath
	app.stealthPath = stealthPath
	app.stateDir = stateDir

	app.runOpencodeSessionStart(strings.NewReader(string(inputJSON)))

	var result map[string]interface{}
	json.Unmarshal(stdout.Bytes(), &result)

	// Should trigger lesson review duty for ready_for_review handoffs
	dutyReminders := result["duty_reminders"].(string)
	if !strings.Contains(strings.ToLower(dutyReminders), "review") {
		t.Error("expected duty_reminders to contain review-related reminder for ready_for_review handoff")
	}
}

func TestOpencodeSessionStart_IncludesHandoffsContext(t *testing.T) {
	tmpDir := t.TempDir()
	projectDir := filepath.Join(tmpDir, "project", ".claude-recall")
	systemDir := filepath.Join(tmpDir, "system")
	stateDir := filepath.Join(tmpDir, "state")
	os.MkdirAll(projectDir, 0755)
	os.MkdirAll(systemDir, 0755)
	os.MkdirAll(stateDir, 0755)

	projectPath := filepath.Join(projectDir, "LESSONS.md")
	systemPath := filepath.Join(systemDir, "LESSONS.md")
	handoffsPath := filepath.Join(projectDir, "HANDOFFS.md")
	stealthPath := filepath.Join(projectDir, "HANDOFFS_LOCAL.md")

	// Create an active handoff
	hStore := handoffs.NewStore(handoffsPath, stealthPath)
	hStore.Add("Active Handoff", "Work in progress", false)

	input := map[string]interface{}{
		"cwd":            filepath.Dir(projectDir),
		"top_n":          5,
		"include_duties": true,
		"include_todos":  true,
	}
	inputJSON, _ := json.Marshal(input)

	var stdout bytes.Buffer
	app := NewApp()
	app.stdout = &stdout
	app.projectPath = projectPath
	app.systemPath = systemPath
	app.handoffsPath = handoffsPath
	app.stealthPath = stealthPath
	app.stateDir = stateDir

	app.runOpencodeSessionStart(strings.NewReader(string(inputJSON)))

	var result map[string]interface{}
	json.Unmarshal(stdout.Bytes(), &result)

	handoffsContext := result["handoffs_context"].(string)
	if !strings.Contains(handoffsContext, "Active Handoff") {
		t.Errorf("expected handoffs_context to contain 'Active Handoff', got: %s", handoffsContext)
	}
}

// ============================================================================
// TestOpencodeSessionIdle - Tests for the opencode session-idle command
// ============================================================================

func TestOpencodeSessionIdle_ExtractsLessonCitations(t *testing.T) {
	tmpDir := t.TempDir()
	projectDir := filepath.Join(tmpDir, "project", ".claude-recall")
	systemDir := filepath.Join(tmpDir, "system")
	stateDir := filepath.Join(tmpDir, "state")
	os.MkdirAll(projectDir, 0755)
	os.MkdirAll(systemDir, 0755)
	os.MkdirAll(stateDir, 0755)

	projectPath := filepath.Join(projectDir, "LESSONS.md")
	systemPath := filepath.Join(systemDir, "LESSONS.md")
	handoffsPath := filepath.Join(projectDir, "HANDOFFS.md")
	stealthPath := filepath.Join(projectDir, "HANDOFFS_LOCAL.md")

	// Create a lesson to cite
	lStore := lessons.NewStore(projectPath, systemPath)
	lesson, _ := lStore.Add("project", "pattern", "Test Lesson", "Content")

	input := map[string]interface{}{
		"cwd":        filepath.Dir(projectDir),
		"session_id": "test-session-123",
		"messages": []map[string]interface{}{
			{
				"role":    "assistant",
				"content": "Applying [" + lesson.ID + "]: lesson title to solve this problem.",
			},
		},
		"checkpoint_offset": 0,
	}
	inputJSON, _ := json.Marshal(input)

	var stdout bytes.Buffer
	app := NewApp()
	app.stdout = &stdout
	app.projectPath = projectPath
	app.systemPath = systemPath
	app.handoffsPath = handoffsPath
	app.stealthPath = stealthPath
	app.stateDir = stateDir

	exitCode := app.runOpencodeSessionIdle(strings.NewReader(string(inputJSON)))

	if exitCode != 0 {
		t.Errorf("expected exit code 0, got %d", exitCode)
	}

	var result map[string]interface{}
	json.Unmarshal(stdout.Bytes(), &result)

	citations, ok := result["citations"].([]interface{})
	if !ok {
		t.Fatal("expected citations to be an array")
	}

	found := false
	for _, c := range citations {
		if c.(string) == lesson.ID {
			found = true
			break
		}
	}
	if !found {
		t.Errorf("expected citations to contain '%s', got: %v", lesson.ID, citations)
	}
}

func TestOpencodeSessionIdle_ExtractsSystemLessonCitations(t *testing.T) {
	tmpDir := t.TempDir()
	projectDir := filepath.Join(tmpDir, "project", ".claude-recall")
	systemDir := filepath.Join(tmpDir, "system")
	stateDir := filepath.Join(tmpDir, "state")
	os.MkdirAll(projectDir, 0755)
	os.MkdirAll(systemDir, 0755)
	os.MkdirAll(stateDir, 0755)

	projectPath := filepath.Join(projectDir, "LESSONS.md")
	systemPath := filepath.Join(systemDir, "LESSONS.md")
	handoffsPath := filepath.Join(projectDir, "HANDOFFS.md")
	stealthPath := filepath.Join(projectDir, "HANDOFFS_LOCAL.md")

	// Create a system lesson
	lStore := lessons.NewStore(projectPath, systemPath)
	sysLesson, _ := lStore.Add("system", "pattern", "System Lesson", "Content")

	input := map[string]interface{}{
		"cwd":        filepath.Dir(projectDir),
		"session_id": "test-session-123",
		"messages": []map[string]interface{}{
			{
				"role":    "assistant",
				"content": "Using [" + sysLesson.ID + "]: system lesson here.",
			},
		},
		"checkpoint_offset": 0,
	}
	inputJSON, _ := json.Marshal(input)

	var stdout bytes.Buffer
	app := NewApp()
	app.stdout = &stdout
	app.projectPath = projectPath
	app.systemPath = systemPath
	app.handoffsPath = handoffsPath
	app.stealthPath = stealthPath
	app.stateDir = stateDir

	app.runOpencodeSessionIdle(strings.NewReader(string(inputJSON)))

	var result map[string]interface{}
	json.Unmarshal(stdout.Bytes(), &result)

	citations := result["citations"].([]interface{})
	found := false
	for _, c := range citations {
		if c.(string) == sysLesson.ID {
			found = true
			break
		}
	}
	if !found {
		t.Errorf("expected citations to contain '%s', got: %v", sysLesson.ID, citations)
	}
}

func TestOpencodeSessionIdle_SkipsCitationsInListings(t *testing.T) {
	tmpDir := t.TempDir()
	projectDir := filepath.Join(tmpDir, "project", ".claude-recall")
	systemDir := filepath.Join(tmpDir, "system")
	stateDir := filepath.Join(tmpDir, "state")
	os.MkdirAll(projectDir, 0755)
	os.MkdirAll(systemDir, 0755)
	os.MkdirAll(stateDir, 0755)

	projectPath := filepath.Join(projectDir, "LESSONS.md")
	systemPath := filepath.Join(systemDir, "LESSONS.md")
	handoffsPath := filepath.Join(projectDir, "HANDOFFS.md")
	stealthPath := filepath.Join(projectDir, "HANDOFFS_LOCAL.md")

	// Message containing a listing format that should be skipped
	input := map[string]interface{}{
		"cwd":        filepath.Dir(projectDir),
		"session_id": "test-session-123",
		"messages": []map[string]interface{}{
			{
				"role": "assistant",
				// This is a lesson listing format - should NOT be counted as citation
				"content": "[L001] [***--] Pattern Title - content here",
			},
		},
		"checkpoint_offset": 0,
	}
	inputJSON, _ := json.Marshal(input)

	var stdout bytes.Buffer
	app := NewApp()
	app.stdout = &stdout
	app.projectPath = projectPath
	app.systemPath = systemPath
	app.handoffsPath = handoffsPath
	app.stealthPath = stealthPath
	app.stateDir = stateDir

	app.runOpencodeSessionIdle(strings.NewReader(string(inputJSON)))

	var result map[string]interface{}
	json.Unmarshal(stdout.Bytes(), &result)

	citations := result["citations"].([]interface{})
	if len(citations) != 0 {
		t.Errorf("expected no citations for listing format, got: %v", citations)
	}
}

func TestOpencodeSessionIdle_ParsesLessonCommand(t *testing.T) {
	tmpDir := t.TempDir()
	projectDir := filepath.Join(tmpDir, "project", ".claude-recall")
	systemDir := filepath.Join(tmpDir, "system")
	stateDir := filepath.Join(tmpDir, "state")
	os.MkdirAll(projectDir, 0755)
	os.MkdirAll(systemDir, 0755)
	os.MkdirAll(stateDir, 0755)

	projectPath := filepath.Join(projectDir, "LESSONS.md")
	systemPath := filepath.Join(systemDir, "LESSONS.md")
	handoffsPath := filepath.Join(projectDir, "HANDOFFS.md")
	stealthPath := filepath.Join(projectDir, "HANDOFFS_LOCAL.md")

	input := map[string]interface{}{
		"cwd":        filepath.Dir(projectDir),
		"session_id": "test-session-123",
		"messages": []map[string]interface{}{
			{
				"role":    "assistant",
				"content": "LESSON: pattern: Always use error handling - wrap all API calls with try/catch blocks",
			},
		},
		"checkpoint_offset": 0,
	}
	inputJSON, _ := json.Marshal(input)

	var stdout bytes.Buffer
	app := NewApp()
	app.stdout = &stdout
	app.projectPath = projectPath
	app.systemPath = systemPath
	app.handoffsPath = handoffsPath
	app.stealthPath = stealthPath
	app.stateDir = stateDir

	app.runOpencodeSessionIdle(strings.NewReader(string(inputJSON)))

	var result map[string]interface{}
	json.Unmarshal(stdout.Bytes(), &result)

	lessonsAdded, ok := result["lessons_added"].([]interface{})
	if !ok {
		t.Fatal("expected lessons_added to be an array")
	}

	if len(lessonsAdded) != 1 {
		t.Errorf("expected 1 lesson added, got %d", len(lessonsAdded))
	}

	// Verify the lesson was actually created
	lStore := lessons.NewStore(projectPath, systemPath)
	allLessons, _ := lStore.List()
	found := false
	for _, l := range allLessons {
		if l.Title == "Always use error handling" {
			found = true
			break
		}
	}
	if !found {
		t.Error("expected lesson 'Always use error handling' to be created")
	}
}

func TestOpencodeSessionIdle_ParsesHandoffStartPattern(t *testing.T) {
	tmpDir := t.TempDir()
	projectDir := filepath.Join(tmpDir, "project", ".claude-recall")
	systemDir := filepath.Join(tmpDir, "system")
	stateDir := filepath.Join(tmpDir, "state")
	os.MkdirAll(projectDir, 0755)
	os.MkdirAll(systemDir, 0755)
	os.MkdirAll(stateDir, 0755)

	projectPath := filepath.Join(projectDir, "LESSONS.md")
	systemPath := filepath.Join(systemDir, "LESSONS.md")
	handoffsPath := filepath.Join(projectDir, "HANDOFFS.md")
	stealthPath := filepath.Join(projectDir, "HANDOFFS_LOCAL.md")

	input := map[string]interface{}{
		"cwd":        filepath.Dir(projectDir),
		"session_id": "test-session-123",
		"messages": []map[string]interface{}{
			{
				"role":    "assistant",
				"content": "HANDOFF: Implement user authentication",
			},
		},
		"checkpoint_offset": 0,
	}
	inputJSON, _ := json.Marshal(input)

	var stdout bytes.Buffer
	app := NewApp()
	app.stdout = &stdout
	app.projectPath = projectPath
	app.systemPath = systemPath
	app.handoffsPath = handoffsPath
	app.stealthPath = stealthPath
	app.stateDir = stateDir

	app.runOpencodeSessionIdle(strings.NewReader(string(inputJSON)))

	var result map[string]interface{}
	json.Unmarshal(stdout.Bytes(), &result)

	handoffOps, ok := result["handoff_ops"].([]interface{})
	if !ok {
		t.Fatal("expected handoff_ops to be an array")
	}

	if len(handoffOps) != 1 {
		t.Errorf("expected 1 handoff op, got %d", len(handoffOps))
	}

	// Verify handoff was created
	hStore := handoffs.NewStore(handoffsPath, stealthPath)
	allHandoffs, _ := hStore.List()
	found := false
	for _, h := range allHandoffs {
		if h.Title == "Implement user authentication" {
			found = true
			break
		}
	}
	if !found {
		t.Error("expected handoff 'Implement user authentication' to be created")
	}
}

func TestOpencodeSessionIdle_ParsesHandoffUpdatePattern(t *testing.T) {
	tmpDir := t.TempDir()
	projectDir := filepath.Join(tmpDir, "project", ".claude-recall")
	systemDir := filepath.Join(tmpDir, "system")
	stateDir := filepath.Join(tmpDir, "state")
	os.MkdirAll(projectDir, 0755)
	os.MkdirAll(systemDir, 0755)
	os.MkdirAll(stateDir, 0755)

	projectPath := filepath.Join(projectDir, "LESSONS.md")
	systemPath := filepath.Join(systemDir, "LESSONS.md")
	handoffsPath := filepath.Join(projectDir, "HANDOFFS.md")
	stealthPath := filepath.Join(projectDir, "HANDOFFS_LOCAL.md")

	// Create a handoff first
	hStore := handoffs.NewStore(handoffsPath, stealthPath)
	h, _ := hStore.Add("Test Handoff", "Description", false)

	input := map[string]interface{}{
		"cwd":        filepath.Dir(projectDir),
		"session_id": "test-session-123",
		"messages": []map[string]interface{}{
			{
				"role":    "assistant",
				"content": "HANDOFF UPDATE " + h.ID + ": tried success - completed the authentication module",
			},
		},
		"checkpoint_offset": 0,
	}
	inputJSON, _ := json.Marshal(input)

	var stdout bytes.Buffer
	app := NewApp()
	app.stdout = &stdout
	app.projectPath = projectPath
	app.systemPath = systemPath
	app.handoffsPath = handoffsPath
	app.stealthPath = stealthPath
	app.stateDir = stateDir

	app.runOpencodeSessionIdle(strings.NewReader(string(inputJSON)))

	var result map[string]interface{}
	json.Unmarshal(stdout.Bytes(), &result)

	// Verify handoff was updated with tried step
	updated, _ := hStore.Get(h.ID)
	if len(updated.Tried) != 1 {
		t.Errorf("expected 1 tried step, got %d", len(updated.Tried))
	}
	if updated.Tried[0].Outcome != "success" {
		t.Errorf("expected outcome 'success', got '%s'", updated.Tried[0].Outcome)
	}
}

func TestOpencodeSessionIdle_ParsesHandoffCompletePattern(t *testing.T) {
	tmpDir := t.TempDir()
	projectDir := filepath.Join(tmpDir, "project", ".claude-recall")
	systemDir := filepath.Join(tmpDir, "system")
	stateDir := filepath.Join(tmpDir, "state")
	os.MkdirAll(projectDir, 0755)
	os.MkdirAll(systemDir, 0755)
	os.MkdirAll(stateDir, 0755)

	projectPath := filepath.Join(projectDir, "LESSONS.md")
	systemPath := filepath.Join(systemDir, "LESSONS.md")
	handoffsPath := filepath.Join(projectDir, "HANDOFFS.md")
	stealthPath := filepath.Join(projectDir, "HANDOFFS_LOCAL.md")

	// Create a handoff first
	hStore := handoffs.NewStore(handoffsPath, stealthPath)
	h, _ := hStore.Add("Test Handoff", "Description", false)

	input := map[string]interface{}{
		"cwd":        filepath.Dir(projectDir),
		"session_id": "test-session-123",
		"messages": []map[string]interface{}{
			{
				"role":    "assistant",
				"content": "HANDOFF COMPLETE " + h.ID,
			},
		},
		"checkpoint_offset": 0,
	}
	inputJSON, _ := json.Marshal(input)

	var stdout bytes.Buffer
	app := NewApp()
	app.stdout = &stdout
	app.projectPath = projectPath
	app.systemPath = systemPath
	app.handoffsPath = handoffsPath
	app.stealthPath = stealthPath
	app.stateDir = stateDir

	app.runOpencodeSessionIdle(strings.NewReader(string(inputJSON)))

	// Verify handoff was completed
	updated, _ := hStore.Get(h.ID)
	if updated.Status != "completed" {
		t.Errorf("expected status 'completed', got '%s'", updated.Status)
	}
}

func TestOpencodeSessionIdle_UpdatesCheckpointOffset(t *testing.T) {
	tmpDir := t.TempDir()
	projectDir := filepath.Join(tmpDir, "project", ".claude-recall")
	systemDir := filepath.Join(tmpDir, "system")
	stateDir := filepath.Join(tmpDir, "state")
	os.MkdirAll(projectDir, 0755)
	os.MkdirAll(systemDir, 0755)
	os.MkdirAll(stateDir, 0755)

	projectPath := filepath.Join(projectDir, "LESSONS.md")
	systemPath := filepath.Join(systemDir, "LESSONS.md")
	handoffsPath := filepath.Join(projectDir, "HANDOFFS.md")
	stealthPath := filepath.Join(projectDir, "HANDOFFS_LOCAL.md")

	input := map[string]interface{}{
		"cwd":        filepath.Dir(projectDir),
		"session_id": "test-session-123",
		"messages": []map[string]interface{}{
			{"role": "assistant", "content": "message 1"},
			{"role": "assistant", "content": "message 2"},
			{"role": "assistant", "content": "message 3"},
		},
		"checkpoint_offset": 0,
	}
	inputJSON, _ := json.Marshal(input)

	var stdout bytes.Buffer
	app := NewApp()
	app.stdout = &stdout
	app.projectPath = projectPath
	app.systemPath = systemPath
	app.handoffsPath = handoffsPath
	app.stealthPath = stealthPath
	app.stateDir = stateDir

	app.runOpencodeSessionIdle(strings.NewReader(string(inputJSON)))

	var result map[string]interface{}
	json.Unmarshal(stdout.Bytes(), &result)

	newOffset, ok := result["new_checkpoint_offset"].(float64)
	if !ok {
		t.Fatal("expected new_checkpoint_offset to be a number")
	}
	if int(newOffset) != 3 {
		t.Errorf("expected new_checkpoint_offset 3, got %d", int(newOffset))
	}
}

func TestOpencodeSessionIdle_HandlesArrayContentBlocks(t *testing.T) {
	tmpDir := t.TempDir()
	projectDir := filepath.Join(tmpDir, "project", ".claude-recall")
	systemDir := filepath.Join(tmpDir, "system")
	stateDir := filepath.Join(tmpDir, "state")
	os.MkdirAll(projectDir, 0755)
	os.MkdirAll(systemDir, 0755)
	os.MkdirAll(stateDir, 0755)

	projectPath := filepath.Join(projectDir, "LESSONS.md")
	systemPath := filepath.Join(systemDir, "LESSONS.md")
	handoffsPath := filepath.Join(projectDir, "HANDOFFS.md")
	stealthPath := filepath.Join(projectDir, "HANDOFFS_LOCAL.md")

	// Create a lesson to cite
	lStore := lessons.NewStore(projectPath, systemPath)
	lesson, _ := lStore.Add("project", "pattern", "Test Lesson", "Content")

	// Message with array content blocks (like Anthropic API format)
	input := map[string]interface{}{
		"cwd":        filepath.Dir(projectDir),
		"session_id": "test-session-123",
		"messages": []map[string]interface{}{
			{
				"role": "assistant",
				"content": []interface{}{
					map[string]interface{}{
						"type": "text",
						"text": "Applying [" + lesson.ID + "]: lesson title to solve this problem.",
					},
				},
			},
		},
		"checkpoint_offset": 0,
	}
	inputJSON, _ := json.Marshal(input)

	var stdout bytes.Buffer
	app := NewApp()
	app.stdout = &stdout
	app.projectPath = projectPath
	app.systemPath = systemPath
	app.handoffsPath = handoffsPath
	app.stealthPath = stealthPath
	app.stateDir = stateDir

	exitCode := app.runOpencodeSessionIdle(strings.NewReader(string(inputJSON)))

	if exitCode != 0 {
		t.Errorf("expected exit code 0, got %d", exitCode)
	}

	var result map[string]interface{}
	json.Unmarshal(stdout.Bytes(), &result)

	citations, ok := result["citations"].([]interface{})
	if !ok {
		t.Fatal("expected citations to be an array")
	}

	found := false
	for _, c := range citations {
		if c.(string) == lesson.ID {
			found = true
			break
		}
	}
	if !found {
		t.Errorf("expected citations to contain '%s' from array content, got: %v", lesson.ID, citations)
	}
}

func TestOpencodeSessionIdle_HandlesMultipleContentBlocks(t *testing.T) {
	tmpDir := t.TempDir()
	projectDir := filepath.Join(tmpDir, "project", ".claude-recall")
	systemDir := filepath.Join(tmpDir, "system")
	stateDir := filepath.Join(tmpDir, "state")
	os.MkdirAll(projectDir, 0755)
	os.MkdirAll(systemDir, 0755)
	os.MkdirAll(stateDir, 0755)

	projectPath := filepath.Join(projectDir, "LESSONS.md")
	systemPath := filepath.Join(systemDir, "LESSONS.md")
	handoffsPath := filepath.Join(projectDir, "HANDOFFS.md")
	stealthPath := filepath.Join(projectDir, "HANDOFFS_LOCAL.md")

	// Create lessons to cite
	lStore := lessons.NewStore(projectPath, systemPath)
	lesson1, _ := lStore.Add("project", "pattern", "Test Lesson 1", "Content 1")
	lesson2, _ := lStore.Add("project", "pattern", "Test Lesson 2", "Content 2")

	// Message with multiple content blocks
	input := map[string]interface{}{
		"cwd":        filepath.Dir(projectDir),
		"session_id": "test-session-123",
		"messages": []map[string]interface{}{
			{
				"role": "assistant",
				"content": []interface{}{
					map[string]interface{}{
						"type": "text",
						"text": "First, applying [" + lesson1.ID + "]: lesson one.",
					},
					map[string]interface{}{
						"type": "tool_use",
						"id":   "tool_123",
						"name": "some_tool",
					},
					map[string]interface{}{
						"type": "text",
						"text": "Then, using [" + lesson2.ID + "]: lesson two.",
					},
				},
			},
		},
		"checkpoint_offset": 0,
	}
	inputJSON, _ := json.Marshal(input)

	var stdout bytes.Buffer
	app := NewApp()
	app.stdout = &stdout
	app.projectPath = projectPath
	app.systemPath = systemPath
	app.handoffsPath = handoffsPath
	app.stealthPath = stealthPath
	app.stateDir = stateDir

	exitCode := app.runOpencodeSessionIdle(strings.NewReader(string(inputJSON)))

	if exitCode != 0 {
		t.Errorf("expected exit code 0, got %d", exitCode)
	}

	var result map[string]interface{}
	json.Unmarshal(stdout.Bytes(), &result)

	citations, ok := result["citations"].([]interface{})
	if !ok {
		t.Fatal("expected citations to be an array")
	}

	// Should have both citations
	if len(citations) != 2 {
		t.Errorf("expected 2 citations from multiple content blocks, got %d: %v", len(citations), citations)
	}
}

func TestOpencodeSessionIdle_OnlyProcessesMessagesAfterCheckpoint(t *testing.T) {
	tmpDir := t.TempDir()
	projectDir := filepath.Join(tmpDir, "project", ".claude-recall")
	systemDir := filepath.Join(tmpDir, "system")
	stateDir := filepath.Join(tmpDir, "state")
	os.MkdirAll(projectDir, 0755)
	os.MkdirAll(systemDir, 0755)
	os.MkdirAll(stateDir, 0755)

	projectPath := filepath.Join(projectDir, "LESSONS.md")
	systemPath := filepath.Join(systemDir, "LESSONS.md")
	handoffsPath := filepath.Join(projectDir, "HANDOFFS.md")
	stealthPath := filepath.Join(projectDir, "HANDOFFS_LOCAL.md")

	// Create a lesson to cite
	lStore := lessons.NewStore(projectPath, systemPath)
	lesson, _ := lStore.Add("project", "pattern", "Test Lesson", "Content")

	input := map[string]interface{}{
		"cwd":        filepath.Dir(projectDir),
		"session_id": "test-session-123",
		"messages": []map[string]interface{}{
			{"role": "assistant", "content": "[" + lesson.ID + "]: already processed"},
			{"role": "assistant", "content": "[" + lesson.ID + "]: already processed"},
			{"role": "assistant", "content": "[" + lesson.ID + "]: new message to process"},
		},
		"checkpoint_offset": 2, // Skip first 2 messages
	}
	inputJSON, _ := json.Marshal(input)

	var stdout bytes.Buffer
	app := NewApp()
	app.stdout = &stdout
	app.projectPath = projectPath
	app.systemPath = systemPath
	app.handoffsPath = handoffsPath
	app.stealthPath = stealthPath
	app.stateDir = stateDir

	app.runOpencodeSessionIdle(strings.NewReader(string(inputJSON)))

	var result map[string]interface{}
	json.Unmarshal(stdout.Bytes(), &result)

	citations := result["citations"].([]interface{})
	// Should only have 1 citation (from the 3rd message, after checkpoint)
	if len(citations) != 1 {
		t.Errorf("expected 1 citation (after checkpoint), got %d", len(citations))
	}
}

// ============================================================================
// TestOpencodePreCompact - Tests for the opencode pre-compact command
// ============================================================================

func TestOpencodePreCompact_ExtractsContextWithHandoff(t *testing.T) {
	tmpDir := t.TempDir()
	projectDir := filepath.Join(tmpDir, "project", ".claude-recall")
	systemDir := filepath.Join(tmpDir, "system")
	stateDir := filepath.Join(tmpDir, "state")
	os.MkdirAll(projectDir, 0755)
	os.MkdirAll(systemDir, 0755)
	os.MkdirAll(stateDir, 0755)

	projectPath := filepath.Join(projectDir, "LESSONS.md")
	systemPath := filepath.Join(systemDir, "LESSONS.md")
	handoffsPath := filepath.Join(projectDir, "HANDOFFS.md")
	stealthPath := filepath.Join(projectDir, "HANDOFFS_LOCAL.md")

	// Create an active handoff
	hStore := handoffs.NewStore(handoffsPath, stealthPath)
	h, _ := hStore.Add("Active Work", "In progress task", false)
	hStore.Update(h.ID, map[string]interface{}{"status": "in_progress"})

	input := map[string]interface{}{
		"cwd":            filepath.Dir(projectDir),
		"session_id":     "test-session-123",
		"handoff_id":     h.ID,
		"files_modified": []string{"file1.go", "file2.go", "file3.go", "file4.go"},
		"todos": []map[string]interface{}{
			{"subject": "Task 1", "status": "completed"},
			{"subject": "Task 2", "status": "in_progress"},
			{"subject": "Task 3", "status": "pending"},
		},
	}
	inputJSON, _ := json.Marshal(input)

	var stdout bytes.Buffer
	app := NewApp()
	app.stdout = &stdout
	app.projectPath = projectPath
	app.systemPath = systemPath
	app.handoffsPath = handoffsPath
	app.stealthPath = stealthPath
	app.stateDir = stateDir

	exitCode := app.runOpencodePreCompact(strings.NewReader(string(inputJSON)))

	if exitCode != 0 {
		t.Errorf("expected exit code 0, got %d", exitCode)
	}

	var result map[string]interface{}
	json.Unmarshal(stdout.Bytes(), &result)

	// Should return context_to_inject
	if _, ok := result["context_to_inject"]; !ok {
		t.Error("expected 'context_to_inject' in result")
	}
}

func TestOpencodePreCompact_DetectsMajorWorkIndicators(t *testing.T) {
	tmpDir := t.TempDir()
	projectDir := filepath.Join(tmpDir, "project", ".claude-recall")
	systemDir := filepath.Join(tmpDir, "system")
	stateDir := filepath.Join(tmpDir, "state")
	os.MkdirAll(projectDir, 0755)
	os.MkdirAll(systemDir, 0755)
	os.MkdirAll(stateDir, 0755)

	projectPath := filepath.Join(projectDir, "LESSONS.md")
	systemPath := filepath.Join(systemDir, "LESSONS.md")
	handoffsPath := filepath.Join(projectDir, "HANDOFFS.md")
	stealthPath := filepath.Join(projectDir, "HANDOFFS_LOCAL.md")

	// No handoff exists - major work indicators should suggest creating one
	input := map[string]interface{}{
		"cwd":        filepath.Dir(projectDir),
		"session_id": "test-session-123",
		// 4+ files = major work indicator
		"files_modified": []string{"file1.go", "file2.go", "file3.go", "file4.go"},
		// 3+ todos = major work indicator
		"todos": []map[string]interface{}{
			{"subject": "Task 1", "status": "in_progress"},
			{"subject": "Task 2", "status": "pending"},
			{"subject": "Task 3", "status": "pending"},
		},
	}
	inputJSON, _ := json.Marshal(input)

	var stdout bytes.Buffer
	app := NewApp()
	app.stdout = &stdout
	app.projectPath = projectPath
	app.systemPath = systemPath
	app.handoffsPath = handoffsPath
	app.stealthPath = stealthPath
	app.stateDir = stateDir

	app.runOpencodePreCompact(strings.NewReader(string(inputJSON)))

	var result map[string]interface{}
	json.Unmarshal(stdout.Bytes(), &result)

	shouldCreate, ok := result["should_create_handoff"].(bool)
	if !ok {
		t.Fatal("expected 'should_create_handoff' in result")
	}
	if !shouldCreate {
		t.Error("expected should_create_handoff=true for major work without handoff")
	}
}

func TestOpencodePreCompact_ReturnsContextToInject(t *testing.T) {
	tmpDir := t.TempDir()
	projectDir := filepath.Join(tmpDir, "project", ".claude-recall")
	systemDir := filepath.Join(tmpDir, "system")
	stateDir := filepath.Join(tmpDir, "state")
	os.MkdirAll(projectDir, 0755)
	os.MkdirAll(systemDir, 0755)
	os.MkdirAll(stateDir, 0755)

	projectPath := filepath.Join(projectDir, "LESSONS.md")
	systemPath := filepath.Join(systemDir, "LESSONS.md")
	handoffsPath := filepath.Join(projectDir, "HANDOFFS.md")
	stealthPath := filepath.Join(projectDir, "HANDOFFS_LOCAL.md")

	// Create handoff with context
	hStore := handoffs.NewStore(handoffsPath, stealthPath)
	h, _ := hStore.Add("Work Item", "Important context", false)

	input := map[string]interface{}{
		"cwd":            filepath.Dir(projectDir),
		"session_id":     "test-session-123",
		"handoff_id":     h.ID,
		"files_modified": []string{"file1.go"},
		"todos":          []map[string]interface{}{},
	}
	inputJSON, _ := json.Marshal(input)

	var stdout bytes.Buffer
	app := NewApp()
	app.stdout = &stdout
	app.projectPath = projectPath
	app.systemPath = systemPath
	app.handoffsPath = handoffsPath
	app.stealthPath = stealthPath
	app.stateDir = stateDir

	app.runOpencodePreCompact(strings.NewReader(string(inputJSON)))

	var result map[string]interface{}
	json.Unmarshal(stdout.Bytes(), &result)

	contextToInject, ok := result["context_to_inject"].(string)
	if !ok {
		t.Fatal("expected 'context_to_inject' to be a string")
	}
	if contextToInject == "" {
		t.Error("expected non-empty context_to_inject for active handoff")
	}
}

// ============================================================================
// TestOpencodePostCompact - Tests for the opencode post-compact command
// ============================================================================

func TestOpencodePostCompact_UpdatesHandoffPhase(t *testing.T) {
	tmpDir := t.TempDir()
	projectDir := filepath.Join(tmpDir, "project", ".claude-recall")
	systemDir := filepath.Join(tmpDir, "system")
	stateDir := filepath.Join(tmpDir, "state")
	os.MkdirAll(projectDir, 0755)
	os.MkdirAll(systemDir, 0755)
	os.MkdirAll(stateDir, 0755)

	projectPath := filepath.Join(projectDir, "LESSONS.md")
	systemPath := filepath.Join(systemDir, "LESSONS.md")
	handoffsPath := filepath.Join(projectDir, "HANDOFFS.md")
	stealthPath := filepath.Join(projectDir, "HANDOFFS_LOCAL.md")

	// Create handoff
	hStore := handoffs.NewStore(handoffsPath, stealthPath)
	h, _ := hStore.Add("Work Item", "Description", false)

	input := map[string]interface{}{
		"cwd":        filepath.Dir(projectDir),
		"session_id": "test-session-123",
		"handoff_id": h.ID,
		"phase":      "implementing",
		"summary":    "Started implementing the feature",
	}
	inputJSON, _ := json.Marshal(input)

	var stdout bytes.Buffer
	app := NewApp()
	app.stdout = &stdout
	app.projectPath = projectPath
	app.systemPath = systemPath
	app.handoffsPath = handoffsPath
	app.stealthPath = stealthPath
	app.stateDir = stateDir

	exitCode := app.runOpencodePostCompact(strings.NewReader(string(inputJSON)))

	if exitCode != 0 {
		t.Errorf("expected exit code 0, got %d", exitCode)
	}

	// Verify handoff phase was updated
	updated, _ := hStore.Get(h.ID)
	if updated.Phase != "implementing" {
		t.Errorf("expected phase 'implementing', got '%s'", updated.Phase)
	}
}

func TestOpencodePostCompact_DetectsCompletionIndicators(t *testing.T) {
	tmpDir := t.TempDir()
	projectDir := filepath.Join(tmpDir, "project", ".claude-recall")
	systemDir := filepath.Join(tmpDir, "system")
	stateDir := filepath.Join(tmpDir, "state")
	os.MkdirAll(projectDir, 0755)
	os.MkdirAll(systemDir, 0755)
	os.MkdirAll(stateDir, 0755)

	projectPath := filepath.Join(projectDir, "LESSONS.md")
	systemPath := filepath.Join(systemDir, "LESSONS.md")
	handoffsPath := filepath.Join(projectDir, "HANDOFFS.md")
	stealthPath := filepath.Join(projectDir, "HANDOFFS_LOCAL.md")

	// Create handoff
	hStore := handoffs.NewStore(handoffsPath, stealthPath)
	h, _ := hStore.Add("Work Item", "Description", false)

	input := map[string]interface{}{
		"cwd":                   filepath.Dir(projectDir),
		"session_id":            "test-session-123",
		"handoff_id":            h.ID,
		"completion_indicators": true,
		"all_todos_complete":    true,
	}
	inputJSON, _ := json.Marshal(input)

	var stdout bytes.Buffer
	app := NewApp()
	app.stdout = &stdout
	app.projectPath = projectPath
	app.systemPath = systemPath
	app.handoffsPath = handoffsPath
	app.stealthPath = stealthPath
	app.stateDir = stateDir

	app.runOpencodePostCompact(strings.NewReader(string(inputJSON)))

	var result map[string]interface{}
	json.Unmarshal(stdout.Bytes(), &result)

	// Should suggest completion
	suggestComplete, ok := result["suggest_complete"].(bool)
	if !ok || !suggestComplete {
		t.Error("expected suggest_complete=true when completion indicators present")
	}
}

// ============================================================================
// TestOpencodeSessionEnd - Tests for the opencode session-end command
// ============================================================================

func TestOpencodeSessionEnd_ExtractsContextOnCleanExit(t *testing.T) {
	tmpDir := t.TempDir()
	projectDir := filepath.Join(tmpDir, "project", ".claude-recall")
	systemDir := filepath.Join(tmpDir, "system")
	stateDir := filepath.Join(tmpDir, "state")
	os.MkdirAll(projectDir, 0755)
	os.MkdirAll(systemDir, 0755)
	os.MkdirAll(stateDir, 0755)

	projectPath := filepath.Join(projectDir, "LESSONS.md")
	systemPath := filepath.Join(systemDir, "LESSONS.md")
	handoffsPath := filepath.Join(projectDir, "HANDOFFS.md")
	stealthPath := filepath.Join(projectDir, "HANDOFFS_LOCAL.md")

	input := map[string]interface{}{
		"cwd":        filepath.Dir(projectDir),
		"session_id": "test-session-123",
		"exit_type":  "clean",
		"messages": []map[string]interface{}{
			{"role": "assistant", "content": "Completed the task successfully."},
		},
	}
	inputJSON, _ := json.Marshal(input)

	var stdout bytes.Buffer
	app := NewApp()
	app.stdout = &stdout
	app.projectPath = projectPath
	app.systemPath = systemPath
	app.handoffsPath = handoffsPath
	app.stealthPath = stealthPath
	app.stateDir = stateDir

	exitCode := app.runOpencodeSessionEnd(strings.NewReader(string(inputJSON)))

	if exitCode != 0 {
		t.Errorf("expected exit code 0, got %d", exitCode)
	}

	var result map[string]interface{}
	if err := json.Unmarshal(stdout.Bytes(), &result); err != nil {
		t.Fatalf("failed to parse output JSON: %v", err)
	}

	// Should have processed field
	if _, ok := result["processed"]; !ok {
		t.Error("expected 'processed' field in result")
	}
}

func TestOpencodeSessionEnd_UpdatesHandoffWithSummary(t *testing.T) {
	tmpDir := t.TempDir()
	projectDir := filepath.Join(tmpDir, "project", ".claude-recall")
	systemDir := filepath.Join(tmpDir, "system")
	stateDir := filepath.Join(tmpDir, "state")
	os.MkdirAll(projectDir, 0755)
	os.MkdirAll(systemDir, 0755)
	os.MkdirAll(stateDir, 0755)

	projectPath := filepath.Join(projectDir, "LESSONS.md")
	systemPath := filepath.Join(systemDir, "LESSONS.md")
	handoffsPath := filepath.Join(projectDir, "HANDOFFS.md")
	stealthPath := filepath.Join(projectDir, "HANDOFFS_LOCAL.md")

	// Create handoff
	hStore := handoffs.NewStore(handoffsPath, stealthPath)
	h, _ := hStore.Add("Work Item", "Description", false)

	input := map[string]interface{}{
		"cwd":        filepath.Dir(projectDir),
		"session_id": "test-session-123",
		"handoff_id": h.ID,
		"exit_type":  "clean",
		"summary":    "Completed authentication module",
		"next_steps": "Need to add tests",
	}
	inputJSON, _ := json.Marshal(input)

	var stdout bytes.Buffer
	app := NewApp()
	app.stdout = &stdout
	app.projectPath = projectPath
	app.systemPath = systemPath
	app.handoffsPath = handoffsPath
	app.stealthPath = stealthPath
	app.stateDir = stateDir

	app.runOpencodeSessionEnd(strings.NewReader(string(inputJSON)))

	// Verify handoff was updated
	updated, _ := hStore.Get(h.ID)
	if updated.Checkpoint == "" {
		t.Error("expected handoff checkpoint to be updated with summary")
	}
	if updated.NextSteps != "Need to add tests" {
		t.Errorf("expected next_steps 'Need to add tests', got '%s'", updated.NextSteps)
	}
}

// ============================================================================
// Integration Tests
// ============================================================================

func TestOpencodeCommand_DispatchesToSubcommands(t *testing.T) {
	tmpDir := t.TempDir()
	projectDir := filepath.Join(tmpDir, "project", ".claude-recall")
	systemDir := filepath.Join(tmpDir, "system")
	stateDir := filepath.Join(tmpDir, "state")
	os.MkdirAll(projectDir, 0755)
	os.MkdirAll(systemDir, 0755)
	os.MkdirAll(stateDir, 0755)

	projectPath := filepath.Join(projectDir, "LESSONS.md")
	systemPath := filepath.Join(systemDir, "LESSONS.md")
	handoffsPath := filepath.Join(projectDir, "HANDOFFS.md")
	stealthPath := filepath.Join(projectDir, "HANDOFFS_LOCAL.md")

	var stderr bytes.Buffer
	app := NewApp()
	app.stderr = &stderr
	app.projectPath = projectPath
	app.systemPath = systemPath
	app.handoffsPath = handoffsPath
	app.stealthPath = stealthPath
	app.stateDir = stateDir

	// Test unknown subcommand
	exitCode := app.Run([]string{"recall", "opencode", "unknown"})
	if exitCode == 0 {
		t.Error("expected non-zero exit code for unknown subcommand")
	}
}

func TestOpencodeCommand_RequiresSubcommand(t *testing.T) {
	tmpDir := t.TempDir()
	projectDir := filepath.Join(tmpDir, "project", ".claude-recall")
	systemDir := filepath.Join(tmpDir, "system")
	stateDir := filepath.Join(tmpDir, "state")
	os.MkdirAll(projectDir, 0755)
	os.MkdirAll(systemDir, 0755)
	os.MkdirAll(stateDir, 0755)

	projectPath := filepath.Join(projectDir, "LESSONS.md")
	systemPath := filepath.Join(systemDir, "LESSONS.md")
	handoffsPath := filepath.Join(projectDir, "HANDOFFS.md")
	stealthPath := filepath.Join(projectDir, "HANDOFFS_LOCAL.md")

	var stderr bytes.Buffer
	app := NewApp()
	app.stderr = &stderr
	app.projectPath = projectPath
	app.systemPath = systemPath
	app.handoffsPath = handoffsPath
	app.stealthPath = stealthPath
	app.stateDir = stateDir

	// Test missing subcommand
	exitCode := app.Run([]string{"recall", "opencode"})
	if exitCode == 0 {
		t.Error("expected non-zero exit code for missing subcommand")
	}
}
