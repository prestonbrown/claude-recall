package main

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/pbrown/claude-recall/internal/lessons"
)

// newListTestApp builds an App over a throwaway store containing three lessons
// that differ in ID, title, and content, so a filter can be shown to match on
// each field independently.
func newListTestApp(t *testing.T) (*App, *bytes.Buffer) {
	t.Helper()

	tmp := t.TempDir()
	projectDir := filepath.Join(tmp, "project", ".claude-recall")
	systemDir := filepath.Join(tmp, "system")
	if err := os.MkdirAll(projectDir, 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(systemDir, 0755); err != nil {
		t.Fatal(err)
	}

	projectPath := filepath.Join(projectDir, "LESSONS.md")
	systemPath := filepath.Join(systemDir, "LESSONS.md")
	store := lessons.NewStore(projectPath, systemPath)

	if _, err := store.Add("project", "pattern", "Delimiter conflicts", "Watch out for pipe characters"); err != nil {
		t.Fatal(err)
	}
	if _, err := store.Add("project", "gotcha", "Silent hook failures", "Always log before returning"); err != nil {
		t.Fatal(err)
	}
	if _, err := store.Add("system", "pattern", "System lesson", "Applies everywhere"); err != nil {
		t.Fatal(err)
	}

	stdout := &bytes.Buffer{}
	app := &App{
		stdout:      stdout,
		stderr:      &bytes.Buffer{},
		projectPath: projectPath,
		systemPath:  systemPath,
	}
	return app, stdout
}

func TestList_NoFilter_ShowsEverything(t *testing.T) {
	app, stdout := newListTestApp(t)

	if code := app.runList(nil); code != 0 {
		t.Fatalf("runList returned %d", code)
	}

	out := stdout.String()
	for _, want := range []string{"Delimiter conflicts", "Silent hook failures", "System lesson"} {
		if !strings.Contains(out, want) {
			t.Errorf("unfiltered list missing %q\ngot:\n%s", want, out)
		}
	}
}

func TestList_SearchFiltersByTitle(t *testing.T) {
	app, stdout := newListTestApp(t)

	if code := app.runList([]string{"--search", "delimiter"}); code != 0 {
		t.Fatalf("runList returned %d", code)
	}

	out := stdout.String()
	if !strings.Contains(out, "Delimiter conflicts") {
		t.Errorf("--search should match the title case-insensitively\ngot:\n%s", out)
	}
	if strings.Contains(out, "Silent hook failures") {
		t.Errorf("--search must exclude non-matching lessons\ngot:\n%s", out)
	}
}

func TestList_SearchFiltersByContent(t *testing.T) {
	app, stdout := newListTestApp(t)

	if code := app.runList([]string{"--search", "returning"}); code != 0 {
		t.Fatalf("runList returned %d", code)
	}

	out := stdout.String()
	if !strings.Contains(out, "Silent hook failures") {
		t.Errorf("--search should match lesson content\ngot:\n%s", out)
	}
	if strings.Contains(out, "Delimiter conflicts") {
		t.Errorf("--search must exclude non-matching lessons\ngot:\n%s", out)
	}
}

func TestList_SearchByID(t *testing.T) {
	app, stdout := newListTestApp(t)

	if code := app.runList([]string{"--search", "L001"}); code != 0 {
		t.Fatalf("runList returned %d", code)
	}

	out := stdout.String()
	if !strings.Contains(out, "L001") {
		t.Errorf("--search should match an exact ID\ngot:\n%s", out)
	}
	if strings.Contains(out, "L002") {
		t.Errorf("searching L001 must not return L002\ngot:\n%s", out)
	}
}

func TestList_SearchByPartialIDAndCase(t *testing.T) {
	app, stdout := newListTestApp(t)

	// Partial prefix matches every project lesson; the system lesson does not
	// share the prefix and must be excluded.
	if code := app.runList([]string{"--search", "l00"}); code != 0 {
		t.Fatalf("runList returned %d", code)
	}

	out := stdout.String()
	if !strings.Contains(out, "L001") || !strings.Contains(out, "L002") {
		t.Errorf("partial, lowercase ID search should match both project lessons\ngot:\n%s", out)
	}
	if strings.Contains(out, "S001") {
		t.Errorf("searching l00 must not return system lessons\ngot:\n%s", out)
	}
}

func TestList_SearchWithNoMatchesIsNotAnError(t *testing.T) {
	app, stdout := newListTestApp(t)

	code := app.runList([]string{"--search", "nothingmatchesthis"})

	if code != 0 {
		t.Errorf("an empty result is not a failure, got exit %d", code)
	}
	if strings.Contains(stdout.String(), "Delimiter") {
		t.Errorf("no lesson should match\ngot:\n%s", stdout.String())
	}
}

func TestList_SearchMissingTermIsAnError(t *testing.T) {
	app, _ := newListTestApp(t)

	// A trailing --search with no term is a usage mistake. Silently listing
	// everything is how the missing flag went unnoticed in the first place.
	if code := app.runList([]string{"--search"}); code == 0 {
		t.Error("--search with no term should exit non-zero")
	}
}
