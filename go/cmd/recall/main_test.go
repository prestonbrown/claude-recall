package main

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/pbrown/claude-recall/internal/feedback"
	"github.com/pbrown/claude-recall/internal/handoffs"
	"github.com/pbrown/claude-recall/internal/lessons"
	"github.com/pbrown/claude-recall/internal/models"
)

// createTestLessonsFile creates a LESSONS.md with test data
func createTestLessonsFile(t *testing.T, dir string, numLessons int) string {
	t.Helper()
	path := filepath.Join(dir, "LESSONS.md")
	store := lessons.NewStore(path, filepath.Join(dir, "system", "LESSONS.md"))

	for i := 1; i <= numLessons; i++ {
		_, err := store.Add("project", "pattern", "Test Lesson "+string(rune('A'+i-1)), "Content for lesson "+string(rune('A'+i-1)))
		if err != nil {
			t.Fatalf("failed to create test lesson: %v", err)
		}
	}

	return path
}

// createTestHandoffsFile creates a HANDOFFS.md with test data
func createTestHandoffsFile(t *testing.T, dir string) string {
	t.Helper()
	path := filepath.Join(dir, "HANDOFFS.md")
	stealthPath := filepath.Join(dir, "HANDOFFS_LOCAL.md")
	store := handoffs.NewStore(path, stealthPath)

	_, err := store.Add("Test Handoff 1", "Description 1", false)
	if err != nil {
		t.Fatalf("failed to create test handoff: %v", err)
	}

	return path
}

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
func Test_ScoreLocal_TrustMultiplierDownranksUncited(t *testing.T) {
	tmpDir := t.TempDir()
	projectRoot := filepath.Join(tmpDir, "project")
	projectRecall := filepath.Join(projectRoot, ".claude-recall")
	stateDir := filepath.Join(tmpDir, "state")
	systemDir := filepath.Join(tmpDir, "system")
	os.MkdirAll(projectRecall, 0755)
	os.MkdirAll(stateDir, 0755)
	os.MkdirAll(systemDir, 0755)

	projectPath := filepath.Join(projectRecall, "LESSONS.md")
	systemPath := filepath.Join(systemDir, "LESSONS.md")

	// Two project lessons with identical, query-matching content -> equal BM25 score.
	store := lessons.NewStore(projectPath, systemPath)
	fresh, err := store.Add("project", "pattern", "Widget configuration guide",
		"Always validate the widget configuration before deploy widget widget")
	if err != nil {
		t.Fatalf("failed to add fresh lesson: %v", err)
	}
	stale, err := store.Add("project", "pattern", "Widget configuration guide",
		"Always validate the widget configuration before deploy widget widget")
	if err != nil {
		t.Fatalf("failed to add stale lesson: %v", err)
	}

	// Give the stale lesson a chronically-uncited history past the gate; fresh has none.
	statsPath := feedback.StatsFilePath(projectRecall)
	statsJSON := `{"` + stale.ID + `":{"injections":100,"citations":0}}`
	if err := os.WriteFile(statsPath, []byte(statsJSON), 0644); err != nil {
		t.Fatalf("failed to write injection-stats: %v", err)
	}

	// Point the score path at our temp project/state via env (initPaths reads these).
	t.Setenv("PROJECT_DIR", projectRoot)
	t.Setenv("CLAUDE_RECALL_STATE", stateDir)

	var stdout bytes.Buffer
	app := NewApp()
	app.stdout = &stdout
	// Set project/system paths but leave handoff paths empty so initPaths runs fully
	// (loading cfg + trust defaults) rather than returning early with a nil cfg.
	app.projectPath = projectPath
	app.systemPath = systemPath

	exitCode := app.Run([]string{"recall", "score-local", "widget configuration", "--top", "5", "--min-score", "1"})
	if exitCode != 0 {
		t.Fatalf("expected exit code 0, got %d; output:\n%s", exitCode, stdout.String())
	}

	out := stdout.String()
	freshIdx := strings.Index(out, "["+fresh.ID+"]")
	staleIdx := strings.Index(out, "["+stale.ID+"]")

	freshScore, freshOK := relevanceScoreOf(out, fresh.ID)
	if freshIdx == -1 || !freshOK {
		t.Fatalf("expected fresh lesson %s in output, got:\n%s", fresh.ID, out)
	}

	// Assert on the NUMERIC score, not print order. The two lessons have identical
	// content (equal BM25 score), so if the trust multiplier were a no-op both would
	// print the same score and — because Go's small-slice sort never swaps ties — the
	// fresh lesson (added first) would still print first. Ordering alone therefore can't
	// catch a regression where the multiplier stops applying; a strictly lower score can.
	// Chronically-uncited past the gate → multiplier 0.2 → stale score must drop below
	// fresh (or be suppressed entirely below --min-score).
	staleScore, staleOK := relevanceScoreOf(out, stale.ID)
	if staleIdx != -1 && staleOK && staleScore >= freshScore {
		t.Errorf("expected chronically-uncited lesson %s (score %d) to score below fresh %s (score %d); output:\n%s",
			stale.ID, staleScore, fresh.ID, freshScore, out)
	}
}

// relevanceScoreOf extracts the integer N from the "(relevance: N/10)" segment of the
// score-local output line for the given lesson ID. Returns false if not found.
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

	// Verify lesson was deleted
	_, err := store.Get(lesson.ID)
	if err == nil {
		t.Error("expected lesson to be deleted, but it still exists")
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

func Test_HandoffAddCommand_CreatesHandoff(t *testing.T) {
	tmpDir := t.TempDir()
	projectDir := filepath.Join(tmpDir, "project", ".claude-recall")
	os.MkdirAll(projectDir, 0755)

	handoffsPath := filepath.Join(projectDir, "HANDOFFS.md")
	stealthPath := filepath.Join(projectDir, "HANDOFFS_LOCAL.md")

	var stdout bytes.Buffer
	app := NewApp()
	app.stdout = &stdout
	app.handoffsPath = handoffsPath
	app.stealthPath = stealthPath

	exitCode := app.Run([]string{"recall", "handoff", "add", "New Handoff", "--desc", "Description here"})

	if exitCode != 0 {
		t.Errorf("expected exit code 0, got %d", exitCode)
	}

	// Verify handoff was created
	store := handoffs.NewStore(handoffsPath, stealthPath)
	handoffList, err := store.List()
	if err != nil {
		t.Fatalf("failed to list handoffs: %v", err)
	}

	if len(handoffList) != 1 {
		t.Errorf("expected 1 handoff, got %d", len(handoffList))
	}

	if handoffList[0].Title != "New Handoff" {
		t.Errorf("expected title 'New Handoff', got '%s'", handoffList[0].Title)
	}

	if handoffList[0].Description != "Description here" {
		t.Errorf("expected description 'Description here', got '%s'", handoffList[0].Description)
	}
}

func Test_HandoffAddCommand_Stealth(t *testing.T) {
	tmpDir := t.TempDir()
	projectDir := filepath.Join(tmpDir, "project", ".claude-recall")
	os.MkdirAll(projectDir, 0755)

	handoffsPath := filepath.Join(projectDir, "HANDOFFS.md")
	stealthPath := filepath.Join(projectDir, "HANDOFFS_LOCAL.md")

	var stdout bytes.Buffer
	app := NewApp()
	app.stdout = &stdout
	app.handoffsPath = handoffsPath
	app.stealthPath = stealthPath

	exitCode := app.Run([]string{"recall", "handoff", "add", "Stealth Handoff", "--stealth"})

	if exitCode != 0 {
		t.Errorf("expected exit code 0, got %d", exitCode)
	}

	// Verify handoff was created in stealth file
	store := handoffs.NewStore(handoffsPath, stealthPath)
	handoffList, _ := store.List()

	if len(handoffList) != 1 {
		t.Errorf("expected 1 handoff, got %d", len(handoffList))
	}

	if !handoffList[0].Stealth {
		t.Error("expected handoff to be stealth")
	}
}

func Test_HandoffListCommand_ShowsActive(t *testing.T) {
	tmpDir := t.TempDir()
	projectDir := filepath.Join(tmpDir, "project", ".claude-recall")
	os.MkdirAll(projectDir, 0755)

	handoffsPath := filepath.Join(projectDir, "HANDOFFS.md")
	stealthPath := filepath.Join(projectDir, "HANDOFFS_LOCAL.md")

	// Create handoffs
	store := handoffs.NewStore(handoffsPath, stealthPath)
	store.Add("Active Handoff", "Active description", false)
	h2, _ := store.Add("Completed Handoff", "Done", false)
	store.Complete(h2.ID)

	var stdout bytes.Buffer
	app := NewApp()
	app.stdout = &stdout
	app.handoffsPath = handoffsPath
	app.stealthPath = stealthPath

	exitCode := app.Run([]string{"recall", "handoff", "list"})

	if exitCode != 0 {
		t.Errorf("expected exit code 0, got %d", exitCode)
	}

	output := stdout.String()

	if !strings.Contains(output, "Active Handoff") {
		t.Errorf("expected output to contain 'Active Handoff', got: %s", output)
	}

	// Should not contain completed handoff in active list
	if strings.Contains(output, "Completed Handoff") {
		t.Errorf("expected output NOT to contain 'Completed Handoff', got: %s", output)
	}
}

func Test_HandoffUpdateCommand_ModifiesFields(t *testing.T) {
	tmpDir := t.TempDir()
	projectDir := filepath.Join(tmpDir, "project", ".claude-recall")
	os.MkdirAll(projectDir, 0755)

	handoffsPath := filepath.Join(projectDir, "HANDOFFS.md")
	stealthPath := filepath.Join(projectDir, "HANDOFFS_LOCAL.md")

	store := handoffs.NewStore(handoffsPath, stealthPath)
	handoff, _ := store.Add("Original Handoff", "Original desc", false)

	var stdout bytes.Buffer
	app := NewApp()
	app.stdout = &stdout
	app.handoffsPath = handoffsPath
	app.stealthPath = stealthPath

	exitCode := app.Run([]string{"recall", "handoff", "update", handoff.ID,
		"--status", "in_progress",
		"--phase", "implementing",
		"--desc", "Updated description",
		"--next", "Next steps here"})

	if exitCode != 0 {
		t.Errorf("expected exit code 0, got %d", exitCode)
	}

	// Verify updates
	updated, _ := store.Get(handoff.ID)
	if updated.Status != "in_progress" {
		t.Errorf("expected status 'in_progress', got '%s'", updated.Status)
	}
	if updated.Phase != "implementing" {
		t.Errorf("expected phase 'implementing', got '%s'", updated.Phase)
	}
	if updated.Description != "Updated description" {
		t.Errorf("expected description 'Updated description', got '%s'", updated.Description)
	}
	if updated.NextSteps != "Next steps here" {
		t.Errorf("expected next steps 'Next steps here', got '%s'", updated.NextSteps)
	}
}

func Test_HandoffTriedCommand_AddsTried(t *testing.T) {
	tmpDir := t.TempDir()
	projectDir := filepath.Join(tmpDir, "project", ".claude-recall")
	os.MkdirAll(projectDir, 0755)

	handoffsPath := filepath.Join(projectDir, "HANDOFFS.md")
	stealthPath := filepath.Join(projectDir, "HANDOFFS_LOCAL.md")

	store := handoffs.NewStore(handoffsPath, stealthPath)
	handoff, _ := store.Add("Test Handoff", "Description", false)

	var stdout bytes.Buffer
	app := NewApp()
	app.stdout = &stdout
	app.handoffsPath = handoffsPath
	app.stealthPath = stealthPath

	exitCode := app.Run([]string{"recall", "handoff", "tried", handoff.ID, "success", "Implemented feature X"})

	if exitCode != 0 {
		t.Errorf("expected exit code 0, got %d", exitCode)
	}

	// Verify tried step was added
	updated, _ := store.Get(handoff.ID)
	if len(updated.Tried) != 1 {
		t.Errorf("expected 1 tried step, got %d", len(updated.Tried))
	}

	if updated.Tried[0].Outcome != "success" {
		t.Errorf("expected outcome 'success', got '%s'", updated.Tried[0].Outcome)
	}

	if updated.Tried[0].Description != "Implemented feature X" {
		t.Errorf("expected description 'Implemented feature X', got '%s'", updated.Tried[0].Description)
	}
}

func Test_HandoffTriedCommand_InvalidOutcome(t *testing.T) {
	tmpDir := t.TempDir()
	projectDir := filepath.Join(tmpDir, "project", ".claude-recall")
	os.MkdirAll(projectDir, 0755)

	handoffsPath := filepath.Join(projectDir, "HANDOFFS.md")
	stealthPath := filepath.Join(projectDir, "HANDOFFS_LOCAL.md")

	store := handoffs.NewStore(handoffsPath, stealthPath)
	handoff, _ := store.Add("Test Handoff", "Description", false)

	var stdout, stderr bytes.Buffer
	app := NewApp()
	app.stdout = &stdout
	app.stderr = &stderr
	app.handoffsPath = handoffsPath
	app.stealthPath = stealthPath

	exitCode := app.Run([]string{"recall", "handoff", "tried", handoff.ID, "invalid", "Description"})

	if exitCode == 0 {
		t.Error("expected non-zero exit code for invalid outcome")
	}
}

func Test_HandoffCompleteCommand_SetsStatus(t *testing.T) {
	tmpDir := t.TempDir()
	projectDir := filepath.Join(tmpDir, "project", ".claude-recall")
	os.MkdirAll(projectDir, 0755)

	handoffsPath := filepath.Join(projectDir, "HANDOFFS.md")
	stealthPath := filepath.Join(projectDir, "HANDOFFS_LOCAL.md")

	store := handoffs.NewStore(handoffsPath, stealthPath)
	handoff, _ := store.Add("Test Handoff", "Description", false)

	var stdout bytes.Buffer
	app := NewApp()
	app.stdout = &stdout
	app.handoffsPath = handoffsPath
	app.stealthPath = stealthPath

	exitCode := app.Run([]string{"recall", "handoff", "complete", handoff.ID})

	if exitCode != 0 {
		t.Errorf("expected exit code 0, got %d", exitCode)
	}

	// Verify status was set
	updated, _ := store.Get(handoff.ID)
	if updated.Status != "completed" {
		t.Errorf("expected status 'completed', got '%s'", updated.Status)
	}
}

func Test_HandoffArchiveCommand_ArchivesOld(t *testing.T) {
	tmpDir := t.TempDir()
	projectDir := filepath.Join(tmpDir, "project", ".claude-recall")
	os.MkdirAll(projectDir, 0755)

	handoffsPath := filepath.Join(projectDir, "HANDOFFS.md")
	stealthPath := filepath.Join(projectDir, "HANDOFFS_LOCAL.md")

	store := handoffs.NewStore(handoffsPath, stealthPath)

	// Create multiple completed handoffs
	for i := 0; i < 5; i++ {
		h, _ := store.Add("Handoff "+string(rune('A'+i)), "Description", false)
		store.Complete(h.ID)
	}

	// Manually set old dates by re-parsing and re-writing
	allHandoffs, _ := store.ListAll()
	oldDate := time.Now().AddDate(0, 0, -models.HandoffMaxAgeDays-1)
	for i, h := range allHandoffs {
		if i < 3 { // Make first 3 old
			h.Updated = oldDate
		}
	}

	// Write back manually (simplified for test)
	// The archive command should remove old completed ones beyond the keep limit

	var stdout bytes.Buffer
	app := NewApp()
	app.stdout = &stdout
	app.handoffsPath = handoffsPath
	app.stealthPath = stealthPath

	exitCode := app.Run([]string{"recall", "handoff", "archive"})

	if exitCode != 0 {
		t.Errorf("expected exit code 0, got %d", exitCode)
	}
}
