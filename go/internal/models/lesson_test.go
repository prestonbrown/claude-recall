package models

import (
	"testing"
	"time"
)

func TestLesson_Tokens(t *testing.T) {
	tests := []struct {
		name     string
		title    string
		content  string
		expected int
	}{
		{
			name:     "empty title and content",
			title:    "",
			content:  "",
			expected: 20, // base overhead only
		},
		{
			name:     "short title and content",
			title:    "Test",
			content:  "Content here",
			expected: (4 + 12) / 4 + 20, // 24
		},
		{
			name:     "longer content",
			title:    "A longer title here",
			content:  "This is some longer content that should result in more tokens",
			expected: (19 + 61) / 4 + 20, // 40
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			l := Lesson{
				Title:   tt.title,
				Content: tt.content,
			}
			got := l.Tokens()
			if got != tt.expected {
				t.Errorf("Tokens() = %d, want %d", got, tt.expected)
			}
		})
	}
}

func TestLesson_IsStale(t *testing.T) {
	now := time.Now()

	tests := []struct {
		name     string
		lastUsed time.Time
		days     int
		expected bool
	}{
		{
			name:     "recently used - not stale",
			lastUsed: now.AddDate(0, 0, -5),
			days:     60,
			expected: false,
		},
		{
			name:     "just inside threshold - not stale",
			lastUsed: now.AddDate(0, 0, -59),
			days:     60,
			expected: false,
		},
		{
			name:     "past threshold - stale",
			lastUsed: now.AddDate(0, 0, -61),
			days:     60,
			expected: true,
		},
		{
			name:     "custom threshold - stale",
			lastUsed: now.AddDate(0, 0, -8),
			days:     7,
			expected: true,
		},
		{
			name:     "zero time - stale",
			lastUsed: time.Time{},
			days:     60,
			expected: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			l := Lesson{
				LastUsed: tt.lastUsed,
			}
			got := l.IsStale(tt.days)
			if got != tt.expected {
				t.Errorf("IsStale(%d) = %v, want %v", tt.days, got, tt.expected)
			}
		})
	}
}

func TestLesson_Stars(t *testing.T) {
	tests := []struct {
		name     string
		uses     int
		expected string
	}{
		{
			name:     "zero uses",
			uses:     0,
			expected: "-----",
		},
		{
			name:     "one use",
			uses:     1,
			expected: "*----",
		},
		{
			name:     "five uses",
			uses:     5,
			expected: "**---",
		},
		{
			name:     "ten uses",
			uses:     10,
			expected: "***--",
		},
		{
			name:     "fifty uses",
			uses:     50,
			expected: "****-",
		},
		{
			name:     "max uses",
			uses:     100,
			expected: "*****",
		},
		{
			name:     "over max uses",
			uses:     150,
			expected: "*****",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			l := Lesson{
				Uses: tt.uses,
			}
			got := l.Stars()
			if got != tt.expected {
				t.Errorf("Stars() = %q, want %q", got, tt.expected)
			}
		})
	}
}

func TestLesson_VelocityStars(t *testing.T) {
	tests := []struct {
		name     string
		velocity float64
		expected string
	}{
		{
			name:     "zero velocity",
			velocity: 0.0,
			expected: "-----",
		},
		{
			name:     "very low velocity",
			velocity: 0.1,
			expected: "*----",
		},
		{
			name:     "low velocity",
			velocity: 0.5,
			expected: "**---",
		},
		{
			name:     "medium velocity",
			velocity: 1.0,
			expected: "***--",
		},
		{
			name:     "high velocity",
			velocity: 2.0,
			expected: "****-",
		},
		{
			name:     "max velocity",
			velocity: 4.0,
			expected: "*****",
		},
		{
			name:     "over max velocity",
			velocity: 10.0,
			expected: "*****",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			l := Lesson{
				Velocity: tt.velocity,
			}
			got := l.VelocityStars()
			if got != tt.expected {
				t.Errorf("VelocityStars() = %q, want %q (velocity=%f)", got, tt.expected, tt.velocity)
			}
		})
	}
}

func TestLesson_Rating(t *testing.T) {
	tests := []struct {
		name     string
		uses     int
		velocity float64
		expected string
	}{
		{
			name:     "zero values",
			uses:     0,
			velocity: 0.0,
			expected: "[-----|-----]",
		},
		{
			name:     "mixed values",
			uses:     10,
			velocity: 0.5,
			expected: "[***--|**---]",
		},
		{
			name:     "max values",
			uses:     100,
			velocity: 4.0,
			expected: "[*****|*****]",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			l := Lesson{
				Uses:     tt.uses,
				Velocity: tt.velocity,
			}
			got := l.Rating()
			if got != tt.expected {
				t.Errorf("Rating() = %q, want %q", got, tt.expected)
			}
		})
	}
}

func TestLesson_Defaults(t *testing.T) {
	l := NewLesson("L001", "Test Title", "Test Content")

	if l.ID != "L001" {
		t.Errorf("ID = %q, want %q", l.ID, "L001")
	}
	if l.Title != "Test Title" {
		t.Errorf("Title = %q, want %q", l.Title, "Test Title")
	}
	if l.Content != "Test Content" {
		t.Errorf("Content = %q, want %q", l.Content, "Test Content")
	}
	if l.Uses != 0 {
		t.Errorf("Uses = %d, want %d", l.Uses, 0)
	}
	if l.Velocity != 0.0 {
		t.Errorf("Velocity = %f, want %f", l.Velocity, 0.0)
	}
	if l.Source != "human" {
		t.Errorf("Source = %q, want %q", l.Source, "human")
	}
	if l.Level != "project" {
		t.Errorf("Level = %q, want %q", l.Level, "project")
	}
	if l.Promotable != true {
		t.Errorf("Promotable = %v, want %v", l.Promotable, true)
	}
	if l.Learned.IsZero() {
		t.Error("Learned should be set to current time")
	}
	if l.LastUsed.IsZero() {
		t.Error("LastUsed should be set to current time")
	}
}

func TestLesson_Constants(t *testing.T) {
	if MaxUses != 100 {
		t.Errorf("MaxUses = %d, want %d", MaxUses, 100)
	}
	if SystemPromotionThreshold != 50 {
		t.Errorf("SystemPromotionThreshold = %d, want %d", SystemPromotionThreshold, 50)
	}
	if VelocityDecayFactor != 0.5 {
		t.Errorf("VelocityDecayFactor = %f, want %f", VelocityDecayFactor, 0.5)
	}
	if VelocityEpsilon != 0.01 {
		t.Errorf("VelocityEpsilon = %f, want %f", VelocityEpsilon, 0.01)
	}
	if StaleDaysDefault != 60 {
		t.Errorf("StaleDaysDefault = %d, want %d", StaleDaysDefault, 60)
	}
}
