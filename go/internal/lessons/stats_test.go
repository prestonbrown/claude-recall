package lessons

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/pbrown/claude-recall/internal/models"
)

// Legacy on-disk form: stats live inline on the metadata line and the header
// carries a rendered rating. Files written before the split look like this.
const legacyFile = `# LESSONS.md - Project Level

## Active Lessons

### [L001] [***--|**---] Delimiter conflicts
- **Uses**: 12 | **Velocity**: 1.5 | **Learned**: 2025-12-14 | **Last**: 2026-07-20 | **Category**: pattern
> Check for conflicts with internal delimiters.

### [L002] [*----|-----] Two-phase file updates
- **Uses**: 3 | **Velocity**: 0.25 | **Learned**: 2025-12-15 | **Last**: 2026-07-21 | **Category**: gotcha
> Collect first, then apply with fresh reads.
`

func mkLesson(id string, uses int, velocity float64) *models.Lesson {
	learned, _ := time.Parse("2006-01-02", "2025-12-14")
	last, _ := time.Parse("2006-01-02", "2026-07-20")
	return &models.Lesson{
		ID: id, Title: "T " + id, Content: "body " + id,
		Uses: uses, Velocity: velocity, Learned: learned, LastUsed: last,
		Category: "pattern", Level: "project", Promotable: true,
	}
}

func TestStatsRoundTripKeepsValues(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "LESSONS.md")
	s := NewStore(path, filepath.Join(dir, "system.md"))

	in := []*models.Lesson{mkLesson("L001", 12, 1.5), mkLesson("L002", 3, 0.25)}
	if err := s.writeLessons(path, in, "project"); err != nil {
		t.Fatalf("write: %v", err)
	}

	out, err := s.loadLessons(path, "project")
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	if len(out) != 2 {
		t.Fatalf("got %d lessons, want 2", len(out))
	}
	for i, want := range in {
		if out[i].Uses != want.Uses || out[i].Velocity != want.Velocity {
			t.Errorf("%s: got uses=%d velocity=%g, want uses=%d velocity=%g",
				want.ID, out[i].Uses, out[i].Velocity, want.Uses, want.Velocity)
		}
		if !out[i].LastUsed.Equal(want.LastUsed) {
			t.Errorf("%s: LastUsed %v, want %v", want.ID, out[i].LastUsed, want.LastUsed)
		}
	}
}

func TestVolatileStatsLeaveTheMarkdown(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "LESSONS.md")
	s := NewStore(path, filepath.Join(dir, "system.md"))

	if err := s.writeLessons(path, []*models.Lesson{mkLesson("L001", 12, 1.5)}, "project"); err != nil {
		t.Fatalf("write: %v", err)
	}
	body, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	text := string(body)
	for _, banned := range []string{"**Uses**", "**Velocity**", "**Last**"} {
		if strings.Contains(text, banned) {
			t.Errorf("LESSONS.md still carries %s - that is the churn the split removes:\n%s", banned, text)
		}
	}
	// Durable fields must survive.
	for _, want := range []string{"### [L001]", "**Learned**", "**Category**: pattern", "body L001"} {
		if !strings.Contains(text, want) {
			t.Errorf("LESSONS.md lost durable field %q:\n%s", want, text)
		}
	}
	if _, err := os.Stat(filepath.Join(dir, "stats.json")); err != nil {
		t.Errorf("stats sidecar not written: %v", err)
	}
}

// The whole point: re-citing a lesson must not touch the markdown file.
func TestCitationChurnDoesNotTouchMarkdown(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "LESSONS.md")
	s := NewStore(path, filepath.Join(dir, "system.md"))

	l := mkLesson("L001", 12, 1.5)
	if err := s.writeLessons(path, []*models.Lesson{l}, "project"); err != nil {
		t.Fatal(err)
	}
	before, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}

	l.Uses += 7
	l.Velocity += 3.25
	l.LastUsed = l.LastUsed.AddDate(0, 0, 5)
	if err := s.writeLessons(path, []*models.Lesson{l}, "project"); err != nil {
		t.Fatal(err)
	}
	after, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if string(before) != string(after) {
		t.Errorf("markdown changed on a stats-only update:\nbefore:\n%s\nafter:\n%s", before, after)
	}

	out, err := s.loadLessons(path, "project")
	if err != nil {
		t.Fatal(err)
	}
	if out[0].Uses != 19 || out[0].Velocity != 4.75 {
		t.Errorf("stats not persisted: uses=%d velocity=%g, want 19 / 4.75", out[0].Uses, out[0].Velocity)
	}
}

func TestLegacyInlineStatsStillLoad(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "LESSONS.md")
	if err := os.WriteFile(path, []byte(legacyFile), 0644); err != nil {
		t.Fatal(err)
	}
	s := NewStore(path, filepath.Join(dir, "system.md"))

	out, err := s.loadLessons(path, "project")
	if err != nil {
		t.Fatalf("load legacy: %v", err)
	}
	if len(out) != 2 {
		t.Fatalf("got %d lessons, want 2", len(out))
	}
	if out[0].Uses != 12 || out[0].Velocity != 1.5 {
		t.Errorf("L001 inline stats lost: uses=%d velocity=%g", out[0].Uses, out[0].Velocity)
	}
	if out[1].Uses != 3 || out[1].Velocity != 0.25 {
		t.Errorf("L002 inline stats lost: uses=%d velocity=%g", out[1].Uses, out[1].Velocity)
	}
}

func TestSidecarWinsOverInline(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "LESSONS.md")
	if err := os.WriteFile(path, []byte(legacyFile), 0644); err != nil {
		t.Fatal(err)
	}
	sc := Stats{"L001": StatEntry{Uses: 99, Velocity: 9.5, Last: "2026-07-25"}}
	if err := sc.Save(StatsPath(path)); err != nil {
		t.Fatal(err)
	}
	s := NewStore(path, filepath.Join(dir, "system.md"))

	out, err := s.loadLessons(path, "project")
	if err != nil {
		t.Fatal(err)
	}
	if out[0].Uses != 99 || out[0].Velocity != 9.5 {
		t.Errorf("sidecar should win: got uses=%d velocity=%g, want 99 / 9.5", out[0].Uses, out[0].Velocity)
	}
	// L002 has no sidecar entry, so it must fall back to its inline values.
	if out[1].Uses != 3 {
		t.Errorf("L002 should fall back to inline uses=3, got %d", out[1].Uses)
	}
}

func TestMigrationIsIdempotent(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "LESSONS.md")
	if err := os.WriteFile(path, []byte(legacyFile), 0644); err != nil {
		t.Fatal(err)
	}
	s := NewStore(path, filepath.Join(dir, "system.md"))

	load := func() []*models.Lesson {
		out, err := s.loadLessons(path, "project")
		if err != nil {
			t.Fatal(err)
		}
		return out
	}
	first := load()
	if err := s.writeLessons(path, first, "project"); err != nil {
		t.Fatal(err)
	}
	afterFirst, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}

	second := load()
	if err := s.writeLessons(path, second, "project"); err != nil {
		t.Fatal(err)
	}
	afterSecond, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}

	if string(afterFirst) != string(afterSecond) {
		t.Errorf("migration not idempotent:\nfirst:\n%s\nsecond:\n%s", afterFirst, afterSecond)
	}
	if second[0].Uses != 12 || second[1].Uses != 3 {
		t.Errorf("stats lost across migration: %d / %d", second[0].Uses, second[1].Uses)
	}
}

func TestParserAcceptsHeaderWithoutRating(t *testing.T) {
	const noRating = `## Active Lessons

### [L001] Delimiter conflicts
- **Learned**: 2025-12-14 | **Category**: pattern
> Body text.
`
	got, err := Parse(strings.NewReader(noRating))
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	if len(got) != 1 {
		t.Fatalf("got %d lessons, want 1", len(got))
	}
	if got[0].ID != "L001" || got[0].Title != "Delimiter conflicts" {
		t.Errorf("got id=%q title=%q", got[0].ID, got[0].Title)
	}
	if got[0].Category != "pattern" {
		t.Errorf("category not parsed without inline stats: %q", got[0].Category)
	}
}
