package lessons

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/pbrown/claude-recall/internal/lock"
	"github.com/pbrown/claude-recall/internal/models"
)

// Store manages lessons in project and system LESSONS.md files
type Store struct {
	projectPath string // Path to project LESSONS.md
	systemPath  string // Path to system LESSONS.md
}

// NewStore creates a store with paths to lesson files
func NewStore(projectPath, systemPath string) *Store {
	return &Store{
		projectPath: projectPath,
		systemPath:  systemPath,
	}
}

// List returns active lessons (project + system) sorted by ID. Tombstones are
// excluded so retired lessons cannot reach injection, scoring, or promotion.
// Use ListAll when you need retired entries too.
func (s *Store) List() ([]*models.Lesson, error) {
	all, err := s.ListAll()
	if err != nil {
		return nil, err
	}
	active := make([]*models.Lesson, 0, len(all))
	for _, l := range all {
		if !l.IsTombstone() {
			active = append(active, l)
		}
	}
	return active, nil
}

// ListAll returns every lesson including tombstones, sorted by ID.
func (s *Store) ListAll() ([]*models.Lesson, error) {
	var all []*models.Lesson

	// Load project lessons (NotExist is handled in loadLessons)
	projectLessons, err := s.loadLessons(s.projectPath, "project")
	if err != nil {
		return nil, fmt.Errorf("loading project lessons: %w", err)
	}
	all = append(all, projectLessons...)

	// Load system lessons (NotExist is handled in loadLessons)
	systemLessons, err := s.loadLessons(s.systemPath, "system")
	if err != nil {
		return nil, fmt.Errorf("loading system lessons: %w", err)
	}
	all = append(all, systemLessons...)

	// Sort by ID
	sort.Slice(all, func(i, j int) bool {
		return all[i].ID < all[j].ID
	})

	return all, nil
}

// Get returns a lesson by ID (searches both project and system). Tombstones
// resolve, so a stale `[L084]` in a source comment gets a redirect rather than
// "not found".
func (s *Store) Get(id string) (*models.Lesson, error) {
	lessons, err := s.ListAll()
	if err != nil {
		return nil, err
	}

	for _, l := range lessons {
		if l.ID == id {
			return l, nil
		}
	}

	return nil, fmt.Errorf("lesson %s not found", id)
}

// Add creates a new lesson (returns new ID)
func (s *Store) Add(level, category, title, content string) (*models.Lesson, error) {
	// Determine which file to use
	path := s.projectPath
	prefix := "L"
	if level == "system" {
		path = s.systemPath
		prefix = "S"
	}

	// Ensure directory exists
	dir := filepath.Dir(path)
	if err := os.MkdirAll(dir, 0755); err != nil {
		return nil, fmt.Errorf("failed to create directory: %w", err)
	}

	// Get next ID
	nextID, err := s.NextID(prefix)
	if err != nil {
		return nil, fmt.Errorf("failed to get next ID: %w", err)
	}

	// Create new lesson
	now := time.Now()
	lesson := &models.Lesson{
		ID:         nextID,
		Title:      title,
		Content:    content,
		Uses:       0,
		Velocity:   0.0,
		Learned:    now,
		LastUsed:   now,
		Category:   category,
		Source:     "human",
		Level:      level,
		Promotable: true,
		Triggers:   []string{},
	}

	// Acquire lock and write
	lockPath := path + ".lock"
	fl, err := lock.Acquire(lockPath)
	if err != nil {
		return nil, fmt.Errorf("failed to acquire lock: %w", err)
	}
	defer fl.Release()

	// Load existing lessons
	lessons, _ := s.loadLessons(path, level)
	lessons = append(lessons, lesson)

	// Write back
	if err := s.writeLessons(path, lessons, level); err != nil {
		return nil, fmt.Errorf("failed to write lessons: %w", err)
	}

	return lesson, nil
}

// Cite increments uses and velocity for a lesson
func (s *Store) Cite(id string) error {
	// Find the lesson and its file
	path, level, err := s.findLessonFile(id)
	if err != nil {
		return err
	}

	// Acquire lock
	lockPath := path + ".lock"
	fl, err := lock.Acquire(lockPath)
	if err != nil {
		return fmt.Errorf("failed to acquire lock: %w", err)
	}
	defer fl.Release()

	// Load lessons
	lessons, err := s.loadLessons(path, level)
	if err != nil {
		return err
	}

	// Find and update the lesson
	found := false
	for _, l := range lessons {
		if l.ID == id {
			l.Uses++
			if l.Uses > models.MaxUses {
				l.Uses = models.MaxUses
			}
			l.Velocity += 1.0
			l.LastUsed = time.Now()
			found = true
			break
		}
	}

	if !found {
		return fmt.Errorf("lesson %s not found", id)
	}

	// Write back
	return s.writeLessons(path, lessons, level)
}

// Edit modifies an existing lesson
func (s *Store) Edit(id string, updates map[string]interface{}) error {
	// Find the lesson and its file
	path, level, err := s.findLessonFile(id)
	if err != nil {
		return err
	}

	// Acquire lock
	lockPath := path + ".lock"
	fl, err := lock.Acquire(lockPath)
	if err != nil {
		return fmt.Errorf("failed to acquire lock: %w", err)
	}
	defer fl.Release()

	// Load lessons
	lessons, err := s.loadLessons(path, level)
	if err != nil {
		return err
	}

	// Find and update the lesson
	found := false
	for _, l := range lessons {
		if l.ID == id {
			applyUpdates(l, updates)
			found = true
			break
		}
	}

	if !found {
		return fmt.Errorf("lesson %s not found", id)
	}

	// Write back
	return s.writeLessons(path, lessons, level)
}

// Delete removes a lesson by ID
// retire marks a lesson superseded. replacement == "" means deleted outright.
func (s *Store) retire(id, replacement string) error {
	// Find the lesson and its file
	path, level, err := s.findLessonFile(id)
	if err != nil {
		return err
	}

	// Acquire lock
	lockPath := path + ".lock"
	fl, err := lock.Acquire(lockPath)
	if err != nil {
		return fmt.Errorf("failed to acquire lock: %w", err)
	}
	defer fl.Release()

	// Load lessons
	lessons, err := s.loadLessons(path, level)
	if err != nil {
		return err
	}

	// Retire in place rather than removing the entry: the ID stays resolvable
	// so existing `[L###]` references in source degrade to a redirect, and the
	// allocator can see the number is spoken for.
	found := false
	for _, l := range lessons {
		if l.ID == id {
			found = true
			if replacement == "" {
				l.Superseded = models.TombstoneDeleted
			} else {
				l.Superseded = replacement
			}
		}
	}

	if !found {
		return fmt.Errorf("lesson %s not found", id)
	}

	return s.writeLessons(path, lessons, level)
}

// Delete retires a lesson with no replacement.
func (s *Store) Delete(id string) error {
	return s.retire(id, "")
}

// Supersede retires a lesson and points it at the lesson that replaced it, so
// `recall show <old>` explains where the content went.
func (s *Store) Supersede(id, replacement string) error {
	if replacement == "" {
		return fmt.Errorf("supersede requires a replacement ID; use delete instead")
	}
	if id == replacement {
		return fmt.Errorf("cannot supersede %s with itself", id)
	}
	if _, err := s.Get(replacement); err != nil {
		return fmt.Errorf("replacement %s does not exist: %w", replacement, err)
	}
	return s.retire(id, replacement)
}

// NextID returns the next available ID for a level ("L" or "S").
//
// Two things make a number unavailable beyond simply being in use:
//   - tombstones, because their ID may still be cited in source comments
//   - numbers the project already uses for its own labels (see ReservedIDs)
//
// Both are skipped rather than merely counted past, so a gap left by an early
// reservation does not get handed out later.
func (s *Store) NextID(prefix string) (string, error) {
	lessons, err := s.ListAll()
	if err != nil {
		return "", err
	}

	taken := make(map[string]bool, len(lessons))
	maxNum := 0
	for _, l := range lessons {
		taken[l.ID] = true
		if strings.HasPrefix(l.ID, prefix) {
			numStr := strings.TrimPrefix(l.ID, prefix)
			if num, err := strconv.Atoi(numStr); err == nil && num > maxNum {
				maxNum = num
			}
		}
	}

	reserved := ReservedIDs(projectRoot(s.projectPath), taken)

	for num := maxNum + 1; num < 1000; num++ {
		candidate := fmt.Sprintf("%s%03d", prefix, num)
		if !taken[candidate] && !reserved[candidate] {
			return candidate, nil
		}
	}
	return "", fmt.Errorf("no available %s IDs below 1000", prefix)
}

// loadLessons reads lessons from a file
func (s *Store) loadLessons(path, level string) ([]*models.Lesson, error) {
	lessons, err := ParseFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return []*models.Lesson{}, nil
		}
		return nil, err
	}

	// Set level for all lessons
	for _, l := range lessons {
		l.Level = level
	}

	// Overlay volatile counters from the sidecar. Lessons missing there keep the
	// inline values the markdown supplied, which is how pre-split files load.
	LoadStats(StatsPath(path)).Apply(lessons)

	return lessons, nil
}

// writeLessons writes durable content to the markdown file and volatile counters
// to the sidecar. Splitting them is what keeps a stats-only update - the common
// case, since every injection bumps a counter - from dirtying the lessons file.
func (s *Store) writeLessons(path string, lessons []*models.Lesson, level string) error {
	statsPath := StatsPath(path)
	merged := ExtractStats(lessons).MergeInto(LoadStats(statsPath))
	if err := merged.Save(statsPath); err != nil {
		return err
	}

	content := Serialize(lessons, level)
	return os.WriteFile(path, []byte(content), 0644)
}

// findLessonFile returns the path and level for a lesson ID
func (s *Store) findLessonFile(id string) (string, string, error) {
	if strings.HasPrefix(id, "L") {
		// Check if it exists in project file
		lessons, _ := s.loadLessons(s.projectPath, "project")
		for _, l := range lessons {
			if l.ID == id {
				return s.projectPath, "project", nil
			}
		}
	} else if strings.HasPrefix(id, "S") {
		// Check if it exists in system file
		lessons, _ := s.loadLessons(s.systemPath, "system")
		for _, l := range lessons {
			if l.ID == id {
				return s.systemPath, "system", nil
			}
		}
	}

	return "", "", fmt.Errorf("lesson %s not found", id)
}

// applyUpdates applies update map to a lesson
func applyUpdates(l *models.Lesson, updates map[string]interface{}) {
	if title, ok := updates["title"].(string); ok {
		l.Title = title
	}
	if content, ok := updates["content"].(string); ok {
		l.Content = content
	}
	if category, ok := updates["category"].(string); ok {
		l.Category = category
	}
	if source, ok := updates["source"].(string); ok {
		l.Source = source
	}
	if lessonType, ok := updates["type"].(string); ok {
		l.LessonType = lessonType
	}
	if promotable, ok := updates["promotable"].(bool); ok {
		l.Promotable = promotable
	}
	if triggers, ok := updates["triggers"].([]string); ok {
		l.Triggers = triggers
	}
}
