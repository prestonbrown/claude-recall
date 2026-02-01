package models

import (
	"strings"
	"time"
)

// Lesson constants
const (
	MaxUses                  = 100
	SystemPromotionThreshold = 50
	VelocityDecayFactor      = 0.5
	VelocityEpsilon          = 0.01
	StaleDaysDefault         = 60
)

// Lesson represents a learned lesson from coding sessions
type Lesson struct {
	ID         string    // "L001" or "S001"
	Title      string
	Content    string
	Uses       int       // Total citations (capped at 100)
	Velocity   float64   // Recency score (decays 50% per cycle)
	Learned    time.Time // Date first learned
	LastUsed   time.Time // Date last cited
	Category   string    // pattern|correction|decision|gotcha|preference
	Source     string    // "human" or "ai" (default: "human")
	Level      string    // "project" or "system" (default: "project")
	Promotable bool      // false = never auto-promote (default: true)
	LessonType string    // constraint|informational|preference (auto-classified if empty)
	Triggers   []string  // Keywords for relevance matching
}

// NewLesson creates a new Lesson with default values
func NewLesson(id, title, content string) *Lesson {
	now := time.Now()
	return &Lesson{
		ID:         id,
		Title:      title,
		Content:    content,
		Uses:       0,
		Velocity:   0.0,
		Learned:    now,
		LastUsed:   now,
		Source:     "human",
		Level:      "project",
		Promotable: true,
		Triggers:   []string{},
	}
}

// Tokens estimates the token count for this lesson
func (l *Lesson) Tokens() int {
	return len(l.Title+l.Content)/4 + 20
}

// IsStale returns true if the lesson hasn't been cited in the given number of days
func (l *Lesson) IsStale(days int) bool {
	if l.LastUsed.IsZero() {
		return true
	}
	threshold := time.Now().AddDate(0, 0, -days)
	// Use Before with strict comparison - exactly at threshold is NOT stale
	return l.LastUsed.Before(threshold)
}

// Stars returns a 5-character star rating based on uses (log scale)
// 0 uses = "-----", 1 = "*----", 5 = "**---", 10 = "***--", 50 = "****-", 100 = "*****"
func (l *Lesson) Stars() string {
	var starCount int
	switch {
	case l.Uses >= 100:
		starCount = 5
	case l.Uses >= 50:
		starCount = 4
	case l.Uses >= 10:
		starCount = 3
	case l.Uses >= 5:
		starCount = 2
	case l.Uses >= 1:
		starCount = 1
	default:
		starCount = 0
	}
	return strings.Repeat("*", starCount) + strings.Repeat("-", 5-starCount)
}

// VelocityStars returns a 5-character star rating based on velocity
// 0 = "-----", 0.1 = "*----", 0.5 = "**---", 1.0 = "***--", 2.0 = "****-", 4.0+ = "*****"
func (l *Lesson) VelocityStars() string {
	var starCount int
	switch {
	case l.Velocity >= 4.0:
		starCount = 5
	case l.Velocity >= 2.0:
		starCount = 4
	case l.Velocity >= 1.0:
		starCount = 3
	case l.Velocity >= 0.5:
		starCount = 2
	case l.Velocity > 0:
		starCount = 1
	default:
		starCount = 0
	}
	return strings.Repeat("*", starCount) + strings.Repeat("-", 5-starCount)
}

// Rating returns the combined rating format "[uses|velocity]"
func (l *Lesson) Rating() string {
	return "[" + l.Stars() + "|" + l.VelocityStars() + "]"
}
