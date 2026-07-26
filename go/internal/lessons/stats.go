package lessons

import (
	"encoding/json"
	"os"
	"path/filepath"
	"time"

	"github.com/pbrown/claude-recall/internal/models"
)

// Volatile per-lesson counters live beside LESSONS.md rather than inside it.
//
// Uses/Velocity/Last change on every injection, so keeping them inline made the
// lessons file permanently dirty in git: a project could not have a clean tree
// while the plugin was running, and stat bumps interleaved with real edits in
// the same hunks. LESSONS.md now holds only durable content, which means it
// changes when a human changes a lesson and at no other time.
//
// The sidecar sits in .claude-recall/ alongside the lessons file, where the
// existing '*' .gitignore already covers it.

// StatEntry is one lesson's volatile counters.
type StatEntry struct {
	Uses     int     `json:"uses"`
	Velocity float64 `json:"velocity"`
	Last     string  `json:"last"` // YYYY-MM-DD
}

// Stats maps lesson ID to its counters.
type Stats map[string]StatEntry

const statsFileName = "stats.json"

// StatsPath returns the sidecar path for a given LESSONS.md path.
func StatsPath(lessonsPath string) string {
	return filepath.Join(filepath.Dir(lessonsPath), statsFileName)
}

// LoadStats reads the sidecar. A missing or unreadable sidecar is not an error:
// callers fall back to whatever inline values the markdown still carries, which
// is what makes a pre-split file load correctly.
func LoadStats(path string) Stats {
	data, err := os.ReadFile(path)
	if err != nil {
		return Stats{}
	}
	var s Stats
	if err := json.Unmarshal(data, &s); err != nil {
		return Stats{}
	}
	if s == nil {
		return Stats{}
	}
	return s
}

// Save writes the sidecar atomically, so a crash mid-write cannot leave a
// truncated file that would silently reset every counter to zero.
func (s Stats) Save(path string) error {
	data, err := json.MarshalIndent(s, "", "  ")
	if err != nil {
		return err
	}
	data = append(data, '\n')

	if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		return err
	}
	tmp, err := os.CreateTemp(filepath.Dir(path), statsFileName+".tmp*")
	if err != nil {
		return err
	}
	tmpName := tmp.Name()
	if _, err := tmp.Write(data); err != nil {
		tmp.Close()
		os.Remove(tmpName)
		return err
	}
	if err := tmp.Close(); err != nil {
		os.Remove(tmpName)
		return err
	}
	if err := os.Chmod(tmpName, 0644); err != nil {
		os.Remove(tmpName)
		return err
	}
	return os.Rename(tmpName, path)
}

// Apply overlays sidecar values onto parsed lessons. Lessons absent from the
// sidecar keep whatever the markdown supplied, so a half-migrated file - some
// entries moved, some still inline - resolves correctly either way.
func (s Stats) Apply(lessons []*models.Lesson) {
	for _, l := range lessons {
		entry, ok := s[l.ID]
		if !ok {
			continue
		}
		l.Uses = entry.Uses
		l.Velocity = entry.Velocity
		if entry.Last != "" {
			if t, err := time.Parse("2006-01-02", entry.Last); err == nil {
				l.LastUsed = t
			}
		}
	}
}

// ExtractStats pulls the volatile counters out of a lesson set for persisting.
func ExtractStats(lessons []*models.Lesson) Stats {
	s := make(Stats, len(lessons))
	for _, l := range lessons {
		entry := StatEntry{Uses: l.Uses, Velocity: l.Velocity}
		if !l.LastUsed.IsZero() {
			entry.Last = l.LastUsed.Format("2006-01-02")
		}
		s[l.ID] = entry
	}
	return s
}

// MergeInto folds a level's stats into an existing sidecar, leaving entries for
// other levels untouched. Project and system lessons share one sidecar per
// directory, so a write of one must not drop the other's counters.
func (s Stats) MergeInto(existing Stats) Stats {
	if existing == nil {
		existing = Stats{}
	}
	for id, entry := range s {
		existing[id] = entry
	}
	return existing
}
