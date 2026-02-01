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

// List returns all lessons (project + system) sorted by ID
func (s *Store) List() ([]*models.Lesson, error) {
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

// Get returns a lesson by ID (searches both project and system)
func (s *Store) Get(id string) (*models.Lesson, error) {
	lessons, err := s.List()
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
func (s *Store) Delete(id string) error {
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

	// Filter out the deleted lesson
	var remaining []*models.Lesson
	found := false
	for _, l := range lessons {
		if l.ID == id {
			found = true
		} else {
			remaining = append(remaining, l)
		}
	}

	if !found {
		return fmt.Errorf("lesson %s not found", id)
	}

	// Write back
	return s.writeLessons(path, remaining, level)
}

// NextID returns the next available ID for a level ("L" or "S")
func (s *Store) NextID(prefix string) (string, error) {
	lessons, err := s.List()
	if err != nil {
		return "", err
	}

	maxNum := 0
	for _, l := range lessons {
		if strings.HasPrefix(l.ID, prefix) {
			numStr := strings.TrimPrefix(l.ID, prefix)
			if num, err := strconv.Atoi(numStr); err == nil && num > maxNum {
				maxNum = num
			}
		}
	}

	return fmt.Sprintf("%s%03d", prefix, maxNum+1), nil
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

	return lessons, nil
}

// writeLessons writes lessons to a file
func (s *Store) writeLessons(path string, lessons []*models.Lesson, level string) error {
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
