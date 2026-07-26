package lessons

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

// Lesson IDs get written into source comments ("// see [L084]"), which makes them
// a load-bearing reference rather than an internal key. Deleting a lesson breaks
// those the way removing a function does, so removal leaves a redirect behind.

func newStoreWith(t *testing.T, content string) (*Store, string, string) {
	t.Helper()
	dir := t.TempDir()
	proj := filepath.Join(dir, ".claude-recall")
	if err := os.MkdirAll(proj, 0755); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(proj, "LESSONS.md")
	if err := os.WriteFile(path, []byte(content), 0644); err != nil {
		t.Fatal(err)
	}
	sysPath := filepath.Join(dir, "system", "LESSONS.md")
	return NewStore(path, sysPath), path, dir
}

const twoLessons = `## Active Lessons

### [L001] First
- **Learned**: 2025-12-14 | **Category**: pattern
> Body one.

### [L002] Second
- **Learned**: 2025-12-15 | **Category**: gotcha
> Body two.
`

func TestDeleteLeavesATombstone(t *testing.T) {
	s, path, _ := newStoreWith(t, twoLessons)

	if err := s.Delete("L001"); err != nil {
		t.Fatalf("delete: %v", err)
	}

	// The ID must still resolve, so a stale `[L001]` in source gets an answer.
	got, err := s.Get("L001")
	if err != nil {
		t.Fatalf("tombstoned lesson should still resolve: %v", err)
	}
	if !got.IsTombstone() {
		t.Errorf("L001 should be a tombstone, Superseded=%q", got.Superseded)
	}

	// ...but it must not reach injection or scoring.
	active, err := s.List()
	if err != nil {
		t.Fatal(err)
	}
	for _, l := range active {
		if l.ID == "L001" {
			t.Errorf("tombstone leaked into List(): %+v", l)
		}
	}
	if len(active) != 1 {
		t.Errorf("List() = %d lessons, want 1", len(active))
	}

	body, _ := os.ReadFile(path)
	if !strings.Contains(string(body), "**Superseded**") {
		t.Errorf("tombstone not persisted:\n%s", body)
	}
}

func TestSupersedePointsAtReplacement(t *testing.T) {
	s, _, _ := newStoreWith(t, twoLessons)

	if err := s.Supersede("L001", "L002"); err != nil {
		t.Fatalf("supersede: %v", err)
	}
	got, err := s.Get("L001")
	if err != nil {
		t.Fatal(err)
	}
	if got.Superseded != "L002" {
		t.Errorf("Superseded = %q, want L002", got.Superseded)
	}
	if !got.IsTombstone() {
		t.Error("superseded lesson should be a tombstone")
	}
}

func TestTombstonedIDIsNeverReused(t *testing.T) {
	s, _, _ := newStoreWith(t, twoLessons)

	// L002 is the highest; delete it and the next ID must still be L003.
	if err := s.Delete("L002"); err != nil {
		t.Fatal(err)
	}
	next, err := s.NextID("L")
	if err != nil {
		t.Fatal(err)
	}
	if next != "L003" {
		t.Errorf("NextID = %s, want L003 - reusing a tombstoned ID would silently "+
			"repoint every existing [L002] reference at a different lesson", next)
	}
}

func TestTombstoneRoundTripsThroughSerialization(t *testing.T) {
	s, path, _ := newStoreWith(t, twoLessons)
	if err := s.Supersede("L001", "L002"); err != nil {
		t.Fatal(err)
	}
	reloaded, err := ParseFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var found bool
	for _, l := range reloaded {
		if l.ID == "L001" {
			found = true
			if l.Superseded != "L002" {
				t.Errorf("Superseded lost on round trip: %q", l.Superseded)
			}
		}
	}
	if !found {
		t.Error("tombstone vanished from the file")
	}
}

// --- reserve-on-allocate ---

func TestReservedIDsFindsProjectClaimedNumbers(t *testing.T) {
	dir := t.TempDir()
	if err := exec.Command("git", "init", "-q", dir).Run(); err != nil {
		t.Skipf("git unavailable: %v", err)
	}
	src := filepath.Join(dir, "src")
	if err := os.MkdirAll(src, 0755); err != nil {
		t.Fatal(err)
	}
	// The project uses [L081] as its own anti-pattern label, unrelated to any lesson.
	if err := os.WriteFile(filepath.Join(src, "a.cpp"),
		[]byte("// bg-thread TOCTOU, see [L081] Mechanism C\nint x; // also [L012]\n"), 0644); err != nil {
		t.Fatal(err)
	}
	cmd := exec.Command("git", "add", "-A")
	cmd.Dir = dir
	if err := cmd.Run(); err != nil {
		t.Fatal(err)
	}

	known := map[string]bool{"L012": true} // L012 is a real lesson; L081 is not
	reserved := ReservedIDs(dir, known)

	if !reserved["L081"] {
		t.Error("L081 is used by the project but absent from the store - must be reserved")
	}
	if reserved["L012"] {
		t.Error("L012 is a known lesson - it is a citation, not a claim, and must not be reserved")
	}
}

func TestNextIDSkipsReservedNumbers(t *testing.T) {
	dir := t.TempDir()
	if err := exec.Command("git", "init", "-q", dir).Run(); err != nil {
		t.Skipf("git unavailable: %v", err)
	}
	proj := filepath.Join(dir, ".claude-recall")
	if err := os.MkdirAll(proj, 0755); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(proj, "LESSONS.md")
	if err := os.WriteFile(path, []byte(twoLessons), 0644); err != nil {
		t.Fatal(err)
	}
	// The project already means something else by [L003].
	if err := os.WriteFile(filepath.Join(dir, "NOTES.md"), []byte("see [L003]\n"), 0644); err != nil {
		t.Fatal(err)
	}
	cmd := exec.Command("git", "add", "-A")
	cmd.Dir = dir
	if err := cmd.Run(); err != nil {
		t.Fatal(err)
	}

	s := NewStore(path, filepath.Join(dir, "system", "LESSONS.md"))
	next, err := s.NextID("L")
	if err != nil {
		t.Fatal(err)
	}
	if next == "L003" {
		t.Error("NextID handed out L003, which the project already uses for something else")
	}
	if next != "L004" {
		t.Errorf("NextID = %s, want L004", next)
	}
}
