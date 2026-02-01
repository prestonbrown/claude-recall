package lessons

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// Helper to create a test LESSONS.md file
func createTestLessonsFile(t *testing.T, dir, filename, content string) string {
	t.Helper()
	path := filepath.Join(dir, filename)
	if err := os.WriteFile(path, []byte(content), 0644); err != nil {
		t.Fatalf("Failed to create test file: %v", err)
	}
	return path
}

// Helper to read file content
func readFile(t *testing.T, path string) string {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("Failed to read file: %v", err)
	}
	return string(data)
}

func Test_Store_List_Empty(t *testing.T) {
	dir := t.TempDir()
	projectPath := filepath.Join(dir, "project", "LESSONS.md")
	systemPath := filepath.Join(dir, "system", "LESSONS.md")

	store := NewStore(projectPath, systemPath)
	lessons, err := store.List()
	if err != nil {
		t.Fatalf("List failed: %v", err)
	}

	if len(lessons) != 0 {
		t.Errorf("Expected 0 lessons, got %d", len(lessons))
	}
}

func Test_Store_List_Multiple(t *testing.T) {
	dir := t.TempDir()
	projectDir := filepath.Join(dir, "project")
	systemDir := filepath.Join(dir, "system")
	os.MkdirAll(projectDir, 0755)
	os.MkdirAll(systemDir, 0755)

	projectContent := `# LESSONS.md - Project Level

## Active Lessons

### [L001] [***--|-----] First Project Lesson
- **Uses**: 10 | **Velocity**: 0.5 | **Learned**: 2025-12-27 | **Last**: 2026-01-18 | **Category**: pattern
> First project content.

### [L002] [**---|-----] Second Project Lesson
- **Uses**: 5 | **Velocity**: 0.1 | **Learned**: 2025-12-28 | **Last**: 2026-01-05 | **Category**: correction
> Second project content.
`

	systemContent := `# LESSONS.md - System Level

## Active Lessons

### [S001] [*----|-----] System Lesson
- **Uses**: 1 | **Velocity**: 0.0 | **Learned**: 2025-01-01 | **Last**: 2025-12-01 | **Category**: decision
> System content.
`

	projectPath := createTestLessonsFile(t, projectDir, "LESSONS.md", projectContent)
	systemPath := createTestLessonsFile(t, systemDir, "LESSONS.md", systemContent)

	store := NewStore(projectPath, systemPath)
	lessons, err := store.List()
	if err != nil {
		t.Fatalf("List failed: %v", err)
	}

	if len(lessons) != 3 {
		t.Fatalf("Expected 3 lessons, got %d", len(lessons))
	}

	// Should be sorted by ID: L001, L002, S001
	if lessons[0].ID != "L001" {
		t.Errorf("Expected first lesson ID 'L001', got '%s'", lessons[0].ID)
	}
	if lessons[1].ID != "L002" {
		t.Errorf("Expected second lesson ID 'L002', got '%s'", lessons[1].ID)
	}
	if lessons[2].ID != "S001" {
		t.Errorf("Expected third lesson ID 'S001', got '%s'", lessons[2].ID)
	}
}

func Test_Store_Get_Found(t *testing.T) {
	dir := t.TempDir()
	projectDir := filepath.Join(dir, "project")
	systemDir := filepath.Join(dir, "system")
	os.MkdirAll(projectDir, 0755)
	os.MkdirAll(systemDir, 0755)

	projectContent := `# LESSONS.md - Project Level

## Active Lessons

### [L001] [***--|-----] Test Lesson
- **Uses**: 10 | **Velocity**: 0.5 | **Learned**: 2025-12-27 | **Last**: 2026-01-18 | **Category**: pattern
> Test content.
`

	projectPath := createTestLessonsFile(t, projectDir, "LESSONS.md", projectContent)
	systemPath := filepath.Join(systemDir, "LESSONS.md")

	store := NewStore(projectPath, systemPath)
	lesson, err := store.Get("L001")
	if err != nil {
		t.Fatalf("Get failed: %v", err)
	}

	if lesson == nil {
		t.Fatal("Expected lesson, got nil")
	}
	if lesson.ID != "L001" {
		t.Errorf("Expected ID 'L001', got '%s'", lesson.ID)
	}
	if lesson.Title != "Test Lesson" {
		t.Errorf("Expected Title 'Test Lesson', got '%s'", lesson.Title)
	}
}

func Test_Store_Get_NotFound(t *testing.T) {
	dir := t.TempDir()
	projectPath := filepath.Join(dir, "project", "LESSONS.md")
	systemPath := filepath.Join(dir, "system", "LESSONS.md")

	store := NewStore(projectPath, systemPath)
	_, err := store.Get("L999")
	if err == nil {
		t.Error("Expected error for missing ID, got nil")
	}
	if !strings.Contains(err.Error(), "not found") {
		t.Errorf("Expected 'not found' error, got: %v", err)
	}
}

func Test_Store_Add_CreatesLesson(t *testing.T) {
	dir := t.TempDir()
	projectDir := filepath.Join(dir, "project")
	systemDir := filepath.Join(dir, "system")
	os.MkdirAll(projectDir, 0755)
	os.MkdirAll(systemDir, 0755)

	projectPath := filepath.Join(projectDir, "LESSONS.md")
	systemPath := filepath.Join(systemDir, "LESSONS.md")

	store := NewStore(projectPath, systemPath)
	lesson, err := store.Add("project", "pattern", "New Lesson", "This is new content.")
	if err != nil {
		t.Fatalf("Add failed: %v", err)
	}

	if lesson == nil {
		t.Fatal("Expected lesson, got nil")
	}
	if lesson.ID != "L001" {
		t.Errorf("Expected ID 'L001', got '%s'", lesson.ID)
	}
	if lesson.Title != "New Lesson" {
		t.Errorf("Expected Title 'New Lesson', got '%s'", lesson.Title)
	}
	if lesson.Content != "This is new content." {
		t.Errorf("Expected Content 'This is new content.', got '%s'", lesson.Content)
	}
	if lesson.Category != "pattern" {
		t.Errorf("Expected Category 'pattern', got '%s'", lesson.Category)
	}
	if lesson.Source != "human" {
		t.Errorf("Expected Source 'human', got '%s'", lesson.Source)
	}
	if lesson.Promotable != true {
		t.Errorf("Expected Promotable true, got %v", lesson.Promotable)
	}
	if lesson.Uses != 0 {
		t.Errorf("Expected Uses 0, got %d", lesson.Uses)
	}
	if lesson.Velocity != 0.0 {
		t.Errorf("Expected Velocity 0.0, got %f", lesson.Velocity)
	}

	// Check dates are set to today
	today := time.Now().Format("2006-01-02")
	if lesson.Learned.Format("2006-01-02") != today {
		t.Errorf("Expected Learned date %s, got %s", today, lesson.Learned.Format("2006-01-02"))
	}
	if lesson.LastUsed.Format("2006-01-02") != today {
		t.Errorf("Expected LastUsed date %s, got %s", today, lesson.LastUsed.Format("2006-01-02"))
	}

	// Verify file was written
	content := readFile(t, projectPath)
	if !strings.Contains(content, "[L001]") {
		t.Error("Expected file to contain '[L001]'")
	}
	if !strings.Contains(content, "New Lesson") {
		t.Error("Expected file to contain 'New Lesson'")
	}
}

func Test_Store_Add_NextID(t *testing.T) {
	dir := t.TempDir()
	projectDir := filepath.Join(dir, "project")
	systemDir := filepath.Join(dir, "system")
	os.MkdirAll(projectDir, 0755)
	os.MkdirAll(systemDir, 0755)

	projectContent := `# LESSONS.md - Project Level

## Active Lessons

### [L001] [***--|-----] First Lesson
- **Uses**: 10 | **Velocity**: 0.5 | **Learned**: 2025-12-27 | **Last**: 2026-01-18 | **Category**: pattern
> First content.

### [L002] [**---|-----] Second Lesson
- **Uses**: 5 | **Velocity**: 0.1 | **Learned**: 2025-12-28 | **Last**: 2026-01-05 | **Category**: correction
> Second content.
`

	projectPath := createTestLessonsFile(t, projectDir, "LESSONS.md", projectContent)
	systemPath := filepath.Join(systemDir, "LESSONS.md")

	store := NewStore(projectPath, systemPath)
	lesson, err := store.Add("project", "gotcha", "Third Lesson", "Third content.")
	if err != nil {
		t.Fatalf("Add failed: %v", err)
	}

	if lesson.ID != "L003" {
		t.Errorf("Expected ID 'L003', got '%s'", lesson.ID)
	}

	// Add a system lesson
	systemContent := `# LESSONS.md - System Level

## Active Lessons

### [S001] [*----|-----] First System
- **Uses**: 1 | **Velocity**: 0.0 | **Learned**: 2025-01-01 | **Last**: 2025-12-01 | **Category**: decision
> System content.
`
	createTestLessonsFile(t, systemDir, "LESSONS.md", systemContent)

	systemLesson, err := store.Add("system", "pattern", "Second System", "System content 2.")
	if err != nil {
		t.Fatalf("Add system lesson failed: %v", err)
	}

	if systemLesson.ID != "S002" {
		t.Errorf("Expected ID 'S002', got '%s'", systemLesson.ID)
	}
}

func Test_Store_Cite_IncrementsValues(t *testing.T) {
	dir := t.TempDir()
	projectDir := filepath.Join(dir, "project")
	systemDir := filepath.Join(dir, "system")
	os.MkdirAll(projectDir, 0755)
	os.MkdirAll(systemDir, 0755)

	projectContent := `# LESSONS.md - Project Level

## Active Lessons

### [L001] [***--|-----] Test Lesson
- **Uses**: 10 | **Velocity**: 0.5 | **Learned**: 2025-12-27 | **Last**: 2025-12-01 | **Category**: pattern
> Test content.
`

	projectPath := createTestLessonsFile(t, projectDir, "LESSONS.md", projectContent)
	systemPath := filepath.Join(systemDir, "LESSONS.md")

	store := NewStore(projectPath, systemPath)
	err := store.Cite("L001")
	if err != nil {
		t.Fatalf("Cite failed: %v", err)
	}

	lesson, err := store.Get("L001")
	if err != nil {
		t.Fatalf("Get failed: %v", err)
	}

	if lesson.Uses != 11 {
		t.Errorf("Expected Uses 11, got %d", lesson.Uses)
	}
	if lesson.Velocity != 1.5 {
		t.Errorf("Expected Velocity 1.5, got %f", lesson.Velocity)
	}

	// Check LastUsed is updated to today
	today := time.Now().Format("2006-01-02")
	if lesson.LastUsed.Format("2006-01-02") != today {
		t.Errorf("Expected LastUsed date %s, got %s", today, lesson.LastUsed.Format("2006-01-02"))
	}
}

func Test_Store_Cite_CapsUses(t *testing.T) {
	dir := t.TempDir()
	projectDir := filepath.Join(dir, "project")
	systemDir := filepath.Join(dir, "system")
	os.MkdirAll(projectDir, 0755)
	os.MkdirAll(systemDir, 0755)

	projectContent := `# LESSONS.md - Project Level

## Active Lessons

### [L001] [*****|-----] Max Uses Lesson
- **Uses**: 100 | **Velocity**: 0.5 | **Learned**: 2025-12-27 | **Last**: 2025-12-01 | **Category**: pattern
> Test content.
`

	projectPath := createTestLessonsFile(t, projectDir, "LESSONS.md", projectContent)
	systemPath := filepath.Join(systemDir, "LESSONS.md")

	store := NewStore(projectPath, systemPath)
	err := store.Cite("L001")
	if err != nil {
		t.Fatalf("Cite failed: %v", err)
	}

	lesson, err := store.Get("L001")
	if err != nil {
		t.Fatalf("Get failed: %v", err)
	}

	if lesson.Uses != 100 {
		t.Errorf("Expected Uses to be capped at 100, got %d", lesson.Uses)
	}
}

func Test_Store_Edit_UpdatesFields(t *testing.T) {
	dir := t.TempDir()
	projectDir := filepath.Join(dir, "project")
	systemDir := filepath.Join(dir, "system")
	os.MkdirAll(projectDir, 0755)
	os.MkdirAll(systemDir, 0755)

	projectContent := `# LESSONS.md - Project Level

## Active Lessons

### [L001] [***--|-----] Original Title
- **Uses**: 10 | **Velocity**: 0.5 | **Learned**: 2025-12-27 | **Last**: 2026-01-18 | **Category**: pattern
> Original content.
`

	projectPath := createTestLessonsFile(t, projectDir, "LESSONS.md", projectContent)
	systemPath := filepath.Join(systemDir, "LESSONS.md")

	store := NewStore(projectPath, systemPath)
	err := store.Edit("L001", map[string]interface{}{
		"title":    "Updated Title",
		"content":  "Updated content.",
		"category": "correction",
		"triggers": []string{"trigger1", "trigger2"},
	})
	if err != nil {
		t.Fatalf("Edit failed: %v", err)
	}

	lesson, err := store.Get("L001")
	if err != nil {
		t.Fatalf("Get failed: %v", err)
	}

	if lesson.Title != "Updated Title" {
		t.Errorf("Expected Title 'Updated Title', got '%s'", lesson.Title)
	}
	if lesson.Content != "Updated content." {
		t.Errorf("Expected Content 'Updated content.', got '%s'", lesson.Content)
	}
	if lesson.Category != "correction" {
		t.Errorf("Expected Category 'correction', got '%s'", lesson.Category)
	}
	if len(lesson.Triggers) != 2 || lesson.Triggers[0] != "trigger1" || lesson.Triggers[1] != "trigger2" {
		t.Errorf("Expected Triggers ['trigger1', 'trigger2'], got %v", lesson.Triggers)
	}
}

func Test_Store_Delete_RemovesLesson(t *testing.T) {
	dir := t.TempDir()
	projectDir := filepath.Join(dir, "project")
	systemDir := filepath.Join(dir, "system")
	os.MkdirAll(projectDir, 0755)
	os.MkdirAll(systemDir, 0755)

	projectContent := `# LESSONS.MD - Project Level

## Active Lessons

### [L001] [***--|-----] First Lesson
- **Uses**: 10 | **Velocity**: 0.5 | **Learned**: 2025-12-27 | **Last**: 2026-01-18 | **Category**: pattern
> First content.

### [L002] [**---|-----] Second Lesson
- **Uses**: 5 | **Velocity**: 0.1 | **Learned**: 2025-12-28 | **Last**: 2026-01-05 | **Category**: correction
> Second content.
`

	projectPath := createTestLessonsFile(t, projectDir, "LESSONS.md", projectContent)
	systemPath := filepath.Join(systemDir, "LESSONS.md")

	store := NewStore(projectPath, systemPath)
	err := store.Delete("L001")
	if err != nil {
		t.Fatalf("Delete failed: %v", err)
	}

	// Verify L001 is gone
	_, err = store.Get("L001")
	if err == nil {
		t.Error("Expected error for deleted lesson, got nil")
	}

	// Verify L002 still exists
	lesson, err := store.Get("L002")
	if err != nil {
		t.Fatalf("Get L002 failed: %v", err)
	}
	if lesson.ID != "L002" {
		t.Errorf("Expected ID 'L002', got '%s'", lesson.ID)
	}

	// Verify file content
	content := readFile(t, projectPath)
	if strings.Contains(content, "[L001]") {
		t.Error("Expected file to not contain '[L001]' after delete")
	}
	if !strings.Contains(content, "[L002]") {
		t.Error("Expected file to still contain '[L002]'")
	}
}

func Test_Store_NextID(t *testing.T) {
	dir := t.TempDir()
	projectDir := filepath.Join(dir, "project")
	systemDir := filepath.Join(dir, "system")
	os.MkdirAll(projectDir, 0755)
	os.MkdirAll(systemDir, 0755)

	projectContent := `# LESSONS.md - Project Level

## Active Lessons

### [L001] [***--|-----] First Lesson
- **Uses**: 10 | **Velocity**: 0.5 | **Learned**: 2025-12-27 | **Last**: 2026-01-18 | **Category**: pattern
> First content.

### [L003] [**---|-----] Third Lesson (gap)
- **Uses**: 5 | **Velocity**: 0.1 | **Learned**: 2025-12-28 | **Last**: 2026-01-05 | **Category**: correction
> Third content.
`

	projectPath := createTestLessonsFile(t, projectDir, "LESSONS.md", projectContent)
	systemPath := filepath.Join(systemDir, "LESSONS.md")

	store := NewStore(projectPath, systemPath)

	// NextID should return L004 (after highest existing)
	nextID, err := store.NextID("L")
	if err != nil {
		t.Fatalf("NextID failed: %v", err)
	}
	if nextID != "L004" {
		t.Errorf("Expected NextID 'L004', got '%s'", nextID)
	}

	// NextID for system should return S001 (none exist)
	nextSystemID, err := store.NextID("S")
	if err != nil {
		t.Fatalf("NextID for system failed: %v", err)
	}
	if nextSystemID != "S001" {
		t.Errorf("Expected NextID 'S001', got '%s'", nextSystemID)
	}
}

func Test_Store_Add_SystemLesson(t *testing.T) {
	dir := t.TempDir()
	projectDir := filepath.Join(dir, "project")
	systemDir := filepath.Join(dir, "system")
	os.MkdirAll(projectDir, 0755)
	os.MkdirAll(systemDir, 0755)

	projectPath := filepath.Join(projectDir, "LESSONS.md")
	systemPath := filepath.Join(systemDir, "LESSONS.md")

	store := NewStore(projectPath, systemPath)
	lesson, err := store.Add("system", "pattern", "System Lesson", "System content.")
	if err != nil {
		t.Fatalf("Add system lesson failed: %v", err)
	}

	if lesson.ID != "S001" {
		t.Errorf("Expected ID 'S001', got '%s'", lesson.ID)
	}
	if lesson.Level != "system" {
		t.Errorf("Expected Level 'system', got '%s'", lesson.Level)
	}

	// Verify file was written to system path
	content := readFile(t, systemPath)
	if !strings.Contains(content, "[S001]") {
		t.Error("Expected system file to contain '[S001]'")
	}
}

func Test_Store_Cite_NotFound(t *testing.T) {
	dir := t.TempDir()
	projectPath := filepath.Join(dir, "project", "LESSONS.md")
	systemPath := filepath.Join(dir, "system", "LESSONS.md")

	store := NewStore(projectPath, systemPath)
	err := store.Cite("L999")
	if err == nil {
		t.Error("Expected error for citing non-existent lesson")
	}
}

func Test_Store_Edit_NotFound(t *testing.T) {
	dir := t.TempDir()
	projectPath := filepath.Join(dir, "project", "LESSONS.md")
	systemPath := filepath.Join(dir, "system", "LESSONS.md")

	store := NewStore(projectPath, systemPath)
	err := store.Edit("L999", map[string]interface{}{"title": "New Title"})
	if err == nil {
		t.Error("Expected error for editing non-existent lesson")
	}
}

func Test_Store_Delete_NotFound(t *testing.T) {
	dir := t.TempDir()
	projectPath := filepath.Join(dir, "project", "LESSONS.md")
	systemPath := filepath.Join(dir, "system", "LESSONS.md")

	store := NewStore(projectPath, systemPath)
	err := store.Delete("L999")
	if err == nil {
		t.Error("Expected error for deleting non-existent lesson")
	}
}

func Test_Store_Get_SystemLesson(t *testing.T) {
	dir := t.TempDir()
	projectDir := filepath.Join(dir, "project")
	systemDir := filepath.Join(dir, "system")
	os.MkdirAll(projectDir, 0755)
	os.MkdirAll(systemDir, 0755)

	systemContent := `# LESSONS.md - System Level

## Active Lessons

### [S001] [*----|-----] System Lesson
- **Uses**: 1 | **Velocity**: 0.0 | **Learned**: 2025-01-01 | **Last**: 2025-12-01 | **Category**: decision
> System content.
`

	projectPath := filepath.Join(projectDir, "LESSONS.md")
	systemPath := createTestLessonsFile(t, systemDir, "LESSONS.md", systemContent)

	store := NewStore(projectPath, systemPath)
	lesson, err := store.Get("S001")
	if err != nil {
		t.Fatalf("Get system lesson failed: %v", err)
	}

	if lesson == nil {
		t.Fatal("Expected lesson, got nil")
	}
	if lesson.ID != "S001" {
		t.Errorf("Expected ID 'S001', got '%s'", lesson.ID)
	}
	if lesson.Level != "system" {
		t.Errorf("Expected Level 'system', got '%s'", lesson.Level)
	}
}
