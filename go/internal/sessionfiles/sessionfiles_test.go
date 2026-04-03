package sessionfiles

import (
	"os"
	"path/filepath"
	"testing"
)

func TestRead_MissingFile(t *testing.T) {
	paths, err := Read("/nonexistent/session-files-abc.json")
	if err != nil {
		t.Fatal(err)
	}
	if len(paths) != 0 {
		t.Errorf("expected empty paths for missing file, got %d", len(paths))
	}
}

func TestWriteAndRead(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "session-files-test.json")

	err := Write(path, []string{"/src/a.go", "/src/b.go"})
	if err != nil {
		t.Fatal(err)
	}

	paths, err := Read(path)
	if err != nil {
		t.Fatal(err)
	}
	if len(paths) != 2 {
		t.Fatalf("expected 2 paths, got %d", len(paths))
	}
	if paths[0] != "/src/a.go" || paths[1] != "/src/b.go" {
		t.Errorf("unexpected paths: %v", paths)
	}
}

func TestMerge_CombinesAndDeduplicates(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "session-files-test.json")

	err := Write(path, []string{"/src/a.go", "/src/b.go"})
	if err != nil {
		t.Fatal(err)
	}

	err = Merge(path, []string{"/src/b.go", "/src/c.go"})
	if err != nil {
		t.Fatal(err)
	}

	paths, err := Read(path)
	if err != nil {
		t.Fatal(err)
	}
	if len(paths) != 3 {
		t.Fatalf("expected 3 deduplicated paths, got %d: %v", len(paths), paths)
	}
}

func TestClear(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "session-files-test.json")

	err := Write(path, []string{"/src/a.go"})
	if err != nil {
		t.Fatal(err)
	}

	Clear(path)

	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Error("expected file to be deleted after Clear")
	}
}

func TestFilePath_ForSession(t *testing.T) {
	result := FilePath("/state/dir", "session-123")
	expected := "/state/dir/session-files-session-123.json"
	if result != expected {
		t.Errorf("expected %s, got %s", expected, result)
	}
}
