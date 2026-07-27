package main

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/pbrown/claude-recall/internal/lessons"
)

// createTestLessonsFile creates a LESSONS.md with test data
func Test_InjectCommand_OutputsLessons(t *testing.T) {
	// Setup temp dir
	tmpDir := t.TempDir()
	projectDir := filepath.Join(tmpDir, "project", ".claude-recall")
	systemDir := filepath.Join(tmpDir, "system")
	os.MkdirAll(projectDir, 0755)
	os.MkdirAll(systemDir, 0755)

	// Create test lessons
	projectPath := filepath.Join(projectDir, "LESSONS.md")
	systemPath := filepath.Join(systemDir, "LESSONS.md")

	store := lessons.NewStore(projectPath, systemPath)

	// Add some lessons with uses to ensure they show up
	l1, _ := store.Add("project", "pattern", "First Lesson", "Content A")
	_ = store.Cite(l1.ID)
	_ = store.Cite(l1.ID)

	l2, _ := store.Add("project", "gotcha", "Second Lesson", "Content B")
	_ = store.Cite(l2.ID)

	l3, _ := store.Add("project", "decision", "Third Lesson", "Content C")
	_ = store.Cite(l3.ID)
	_ = store.Cite(l3.ID)
	_ = store.Cite(l3.ID)

	// Run inject command
	var stdout bytes.Buffer
	app := NewApp()
	app.stdout = &stdout
	app.projectPath = projectPath
	app.systemPath = systemPath

	exitCode := app.Run([]string{"recall", "inject", "3"})

	if exitCode != 0 {
		t.Errorf("expected exit code 0, got %d", exitCode)
	}

	output := stdout.String()

	// Should contain lesson content
	if !strings.Contains(output, "First Lesson") && !strings.Contains(output, "Third Lesson") {
		t.Errorf("expected output to contain lessons, got: %s", output)
	}
}

func Test_AddCommand_CreatesLesson(t *testing.T) {
	tmpDir := t.TempDir()
	projectDir := filepath.Join(tmpDir, "project", ".claude-recall")
	systemDir := filepath.Join(tmpDir, "system")
	os.MkdirAll(projectDir, 0755)
	os.MkdirAll(systemDir, 0755)

	projectPath := filepath.Join(projectDir, "LESSONS.md")
	systemPath := filepath.Join(systemDir, "LESSONS.md")

	var stdout bytes.Buffer
	app := NewApp()
	app.stdout = &stdout
	app.projectPath = projectPath
	app.systemPath = systemPath

	exitCode := app.Run([]string{"recall", "add", "pattern", "Test Title", "Test Content"})

	if exitCode != 0 {
		t.Errorf("expected exit code 0, got %d", exitCode)
	}

	// Verify lesson was created
	store := lessons.NewStore(projectPath, systemPath)
	lessonList, err := store.List()
	if err != nil {
		t.Fatalf("failed to list lessons: %v", err)
	}

	if len(lessonList) != 1 {
		t.Errorf("expected 1 lesson, got %d", len(lessonList))
	}

	if lessonList[0].Title != "Test Title" {
		t.Errorf("expected title 'Test Title', got '%s'", lessonList[0].Title)
	}

	if lessonList[0].Content != "Test Content" {
		t.Errorf("expected content 'Test Content', got '%s'", lessonList[0].Content)
	}

	if lessonList[0].Category != "pattern" {
		t.Errorf("expected category 'pattern', got '%s'", lessonList[0].Category)
	}
}

func Test_AddCommand_SystemLevel(t *testing.T) {
	tmpDir := t.TempDir()
	projectDir := filepath.Join(tmpDir, "project", ".claude-recall")
	systemDir := filepath.Join(tmpDir, "system")
	os.MkdirAll(projectDir, 0755)
	os.MkdirAll(systemDir, 0755)

	projectPath := filepath.Join(projectDir, "LESSONS.md")
	systemPath := filepath.Join(systemDir, "LESSONS.md")

	var stdout bytes.Buffer
	app := NewApp()
	app.stdout = &stdout
	app.projectPath = projectPath
	app.systemPath = systemPath

	exitCode := app.Run([]string{"recall", "add", "gotcha", "System Title", "System Content", "--system"})

	if exitCode != 0 {
		t.Errorf("expected exit code 0, got %d", exitCode)
	}

	// Verify lesson was created in system file
	store := lessons.NewStore(projectPath, systemPath)
	lessonList, err := store.List()
	if err != nil {
		t.Fatalf("failed to list lessons: %v", err)
	}

	if len(lessonList) != 1 {
		t.Errorf("expected 1 lesson, got %d", len(lessonList))
	}

	if lessonList[0].Level != "system" {
		t.Errorf("expected level 'system', got '%s'", lessonList[0].Level)
	}

	if !strings.HasPrefix(lessonList[0].ID, "S") {
		t.Errorf("expected ID to start with 'S', got '%s'", lessonList[0].ID)
	}
}

// Test_ScoreLocal_TrustMultiplierDownranksUncited verifies the live score path applies
// the graduated trust multiplier: two lessons with identical BM25 relevance, where one is
// chronically injected-but-never-cited (past the min-injections gate), must rank the
// uncited lesson below the otherwise-equal fresh lesson.
func relevanceScoreOf(out, id string) (int, bool) {
	for _, line := range strings.Split(out, "\n") {
		if !strings.Contains(line, "["+id+"]") {
			continue
		}
		marker := "(relevance: "
		i := strings.Index(line, marker)
		if i == -1 {
			return 0, false
		}
		rest := line[i+len(marker):]
		j := strings.Index(rest, "/10)")
		if j == -1 {
			return 0, false
		}
		n := 0
		for _, c := range rest[:j] {
			if c < '0' || c > '9' {
				return 0, false
			}
			n = n*10 + int(c-'0')
		}
		return n, true
	}
	return 0, false
}

func Test_CiteCommand_IncrementsUses(t *testing.T) {
	tmpDir := t.TempDir()
	projectDir := filepath.Join(tmpDir, "project", ".claude-recall")
	systemDir := filepath.Join(tmpDir, "system")
	os.MkdirAll(projectDir, 0755)
	os.MkdirAll(systemDir, 0755)

	projectPath := filepath.Join(projectDir, "LESSONS.md")
	systemPath := filepath.Join(systemDir, "LESSONS.md")

	// Create a lesson first
	store := lessons.NewStore(projectPath, systemPath)
	lesson, err := store.Add("project", "pattern", "Test Lesson", "Test Content")
	if err != nil {
		t.Fatalf("failed to create lesson: %v", err)
	}

	initialUses := lesson.Uses

	var stdout bytes.Buffer
	app := NewApp()
	app.stdout = &stdout
	app.projectPath = projectPath
	app.systemPath = systemPath

	exitCode := app.Run([]string{"recall", "cite", lesson.ID})

	if exitCode != 0 {
		t.Errorf("expected exit code 0, got %d", exitCode)
	}

	// Verify uses was incremented
	updatedLesson, err := store.Get(lesson.ID)
	if err != nil {
		t.Fatalf("failed to get lesson: %v", err)
	}

	if updatedLesson.Uses != initialUses+1 {
		t.Errorf("expected uses %d, got %d", initialUses+1, updatedLesson.Uses)
	}
}

func Test_CiteCommand_MultipleLessons(t *testing.T) {
	tmpDir := t.TempDir()
	projectDir := filepath.Join(tmpDir, "project", ".claude-recall")
	systemDir := filepath.Join(tmpDir, "system")
	os.MkdirAll(projectDir, 0755)
	os.MkdirAll(systemDir, 0755)

	projectPath := filepath.Join(projectDir, "LESSONS.md")
	systemPath := filepath.Join(systemDir, "LESSONS.md")

	// Create lessons
	store := lessons.NewStore(projectPath, systemPath)
	lesson1, _ := store.Add("project", "pattern", "Lesson 1", "Content 1")
	lesson2, _ := store.Add("project", "pattern", "Lesson 2", "Content 2")

	var stdout bytes.Buffer
	app := NewApp()
	app.stdout = &stdout
	app.projectPath = projectPath
	app.systemPath = systemPath

	exitCode := app.Run([]string{"recall", "cite", lesson1.ID, lesson2.ID})

	if exitCode != 0 {
		t.Errorf("expected exit code 0, got %d", exitCode)
	}

	// Verify both were cited
	l1, _ := store.Get(lesson1.ID)
	l2, _ := store.Get(lesson2.ID)

	if l1.Uses != 1 {
		t.Errorf("expected lesson1 uses 1, got %d", l1.Uses)
	}
	if l2.Uses != 1 {
		t.Errorf("expected lesson2 uses 1, got %d", l2.Uses)
	}
}

func Test_ListCommand_ShowsAllLessons(t *testing.T) {
	tmpDir := t.TempDir()
	projectDir := filepath.Join(tmpDir, "project", ".claude-recall")
	systemDir := filepath.Join(tmpDir, "system")
	os.MkdirAll(projectDir, 0755)
	os.MkdirAll(systemDir, 0755)

	projectPath := filepath.Join(projectDir, "LESSONS.md")
	systemPath := filepath.Join(systemDir, "LESSONS.md")

	// Create lessons
	store := lessons.NewStore(projectPath, systemPath)
	store.Add("project", "pattern", "Project Lesson", "Content")
	store.Add("system", "gotcha", "System Lesson", "Content")

	var stdout bytes.Buffer
	app := NewApp()
	app.stdout = &stdout
	app.projectPath = projectPath
	app.systemPath = systemPath

	exitCode := app.Run([]string{"recall", "list", "--all"})

	if exitCode != 0 {
		t.Errorf("expected exit code 0, got %d", exitCode)
	}

	output := stdout.String()

	if !strings.Contains(output, "L001") {
		t.Errorf("expected output to contain L001, got: %s", output)
	}
	if !strings.Contains(output, "S001") {
		t.Errorf("expected output to contain S001, got: %s", output)
	}
	if !strings.Contains(output, "Project Lesson") {
		t.Errorf("expected output to contain 'Project Lesson', got: %s", output)
	}
	if !strings.Contains(output, "System Lesson") {
		t.Errorf("expected output to contain 'System Lesson', got: %s", output)
	}
}

func Test_ShowCommand_ShowsSingleLesson(t *testing.T) {
	tmpDir := t.TempDir()
	projectDir := filepath.Join(tmpDir, "project", ".claude-recall")
	systemDir := filepath.Join(tmpDir, "system")
	os.MkdirAll(projectDir, 0755)
	os.MkdirAll(systemDir, 0755)

	projectPath := filepath.Join(projectDir, "LESSONS.md")
	systemPath := filepath.Join(systemDir, "LESSONS.md")

	store := lessons.NewStore(projectPath, systemPath)
	lesson, _ := store.Add("project", "pattern", "Specific Lesson", "Detailed content here")

	var stdout bytes.Buffer
	app := NewApp()
	app.stdout = &stdout
	app.projectPath = projectPath
	app.systemPath = systemPath

	exitCode := app.Run([]string{"recall", "show", lesson.ID})

	if exitCode != 0 {
		t.Errorf("expected exit code 0, got %d", exitCode)
	}

	output := stdout.String()

	if !strings.Contains(output, "Specific Lesson") {
		t.Errorf("expected output to contain 'Specific Lesson', got: %s", output)
	}
	if !strings.Contains(output, "Detailed content here") {
		t.Errorf("expected output to contain 'Detailed content here', got: %s", output)
	}
}

func Test_EditCommand_ModifiesLesson(t *testing.T) {
	tmpDir := t.TempDir()
	projectDir := filepath.Join(tmpDir, "project", ".claude-recall")
	systemDir := filepath.Join(tmpDir, "system")
	os.MkdirAll(projectDir, 0755)
	os.MkdirAll(systemDir, 0755)

	projectPath := filepath.Join(projectDir, "LESSONS.md")
	systemPath := filepath.Join(systemDir, "LESSONS.md")

	store := lessons.NewStore(projectPath, systemPath)
	lesson, _ := store.Add("project", "pattern", "Original Title", "Original content")

	var stdout bytes.Buffer
	app := NewApp()
	app.stdout = &stdout
	app.projectPath = projectPath
	app.systemPath = systemPath

	exitCode := app.Run([]string{"recall", "edit", lesson.ID, "--title", "Updated Title", "--content", "Updated content"})

	if exitCode != 0 {
		t.Errorf("expected exit code 0, got %d", exitCode)
	}

	// Verify lesson was updated
	updated, _ := store.Get(lesson.ID)
	if updated.Title != "Updated Title" {
		t.Errorf("expected title 'Updated Title', got '%s'", updated.Title)
	}
	if updated.Content != "Updated content" {
		t.Errorf("expected content 'Updated content', got '%s'", updated.Content)
	}
}

func Test_DeleteCommand_DeletesLesson(t *testing.T) {
	tmpDir := t.TempDir()
	projectDir := filepath.Join(tmpDir, "project", ".claude-recall")
	systemDir := filepath.Join(tmpDir, "system")
	os.MkdirAll(projectDir, 0755)
	os.MkdirAll(systemDir, 0755)

	projectPath := filepath.Join(projectDir, "LESSONS.md")
	systemPath := filepath.Join(systemDir, "LESSONS.md")

	store := lessons.NewStore(projectPath, systemPath)
	lesson, _ := store.Add("project", "pattern", "To Delete", "Content")

	var stdout bytes.Buffer
	app := NewApp()
	app.stdout = &stdout
	app.projectPath = projectPath
	app.systemPath = systemPath

	exitCode := app.Run([]string{"recall", "delete", lesson.ID})

	if exitCode != 0 {
		t.Errorf("expected exit code 0, got %d", exitCode)
	}

	// Deleting retires the lesson rather than erasing it: the ID keeps
	// resolving so cited references degrade to a redirect, but it drops out of
	// the active set that feeds injection and scoring.
	retired, err := store.Get(lesson.ID)
	if err != nil {
		t.Fatalf("deleted lesson should still resolve as a tombstone: %v", err)
	}
	if !retired.IsTombstone() {
		t.Errorf("expected a tombstone, Superseded=%q", retired.Superseded)
	}

	active, err := store.List()
	if err != nil {
		t.Fatal(err)
	}
	for _, l := range active {
		if l.ID == lesson.ID {
			t.Error("deleted lesson still appears among active lessons")
		}
	}
}

func Test_DecayCommand_RunsDecay(t *testing.T) {
	tmpDir := t.TempDir()
	projectDir := filepath.Join(tmpDir, "project", ".claude-recall")
	systemDir := filepath.Join(tmpDir, "system")
	stateDir := filepath.Join(tmpDir, "state")
	os.MkdirAll(projectDir, 0755)
	os.MkdirAll(systemDir, 0755)
	os.MkdirAll(stateDir, 0755)

	projectPath := filepath.Join(projectDir, "LESSONS.md")
	systemPath := filepath.Join(systemDir, "LESSONS.md")

	// Create a lesson with velocity
	store := lessons.NewStore(projectPath, systemPath)
	lesson, _ := store.Add("project", "pattern", "Test Lesson", "Content")
	store.Cite(lesson.ID)
	store.Cite(lesson.ID)

	// Check velocity before
	before, _ := store.Get(lesson.ID)
	initialVelocity := before.Velocity

	var stdout bytes.Buffer
	app := NewApp()
	app.stdout = &stdout
	app.projectPath = projectPath
	app.systemPath = systemPath
	app.stateDir = stateDir

	exitCode := app.Run([]string{"recall", "decay", "--force"})

	if exitCode != 0 {
		t.Errorf("expected exit code 0, got %d", exitCode)
	}

	// Verify velocity was decayed
	after, _ := store.Get(lesson.ID)
	if after.Velocity >= initialVelocity {
		t.Errorf("expected velocity to decrease from %f, got %f", initialVelocity, after.Velocity)
	}
}
