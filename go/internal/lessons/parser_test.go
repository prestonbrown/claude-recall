package lessons

import (
	"strings"
	"testing"
	"time"

	"github.com/pbrown/claude-recall/internal/models"
)

func TestParse_SingleLesson(t *testing.T) {
	input := `# LESSONS.md - Project Level

> **Lessons System**: Cite lessons with [L###] when applying them.

## Active Lessons

### [L001] [***--|-----] Lesson Title
- **Uses**: 7 | **Velocity**: 0.01 | **Learned**: 2025-12-27 | **Last**: 2026-01-18 | **Category**: pattern
> Content line - description of the lesson.
`

	lessons, err := Parse(strings.NewReader(input))
	if err != nil {
		t.Fatalf("Parse failed: %v", err)
	}

	if len(lessons) != 1 {
		t.Fatalf("Expected 1 lesson, got %d", len(lessons))
	}

	l := lessons[0]
	if l.ID != "L001" {
		t.Errorf("Expected ID 'L001', got '%s'", l.ID)
	}
	if l.Title != "Lesson Title" {
		t.Errorf("Expected Title 'Lesson Title', got '%s'", l.Title)
	}
	if l.Uses != 7 {
		t.Errorf("Expected Uses 7, got %d", l.Uses)
	}
	if l.Velocity != 0.01 {
		t.Errorf("Expected Velocity 0.01, got %f", l.Velocity)
	}
	if l.Category != "pattern" {
		t.Errorf("Expected Category 'pattern', got '%s'", l.Category)
	}
	if l.Content != "Content line - description of the lesson." {
		t.Errorf("Expected Content 'Content line - description of the lesson.', got '%s'", l.Content)
	}

	expectedLearned, _ := time.Parse("2006-01-02", "2025-12-27")
	if !l.Learned.Equal(expectedLearned) {
		t.Errorf("Expected Learned %v, got %v", expectedLearned, l.Learned)
	}

	expectedLast, _ := time.Parse("2006-01-02", "2026-01-18")
	if !l.LastUsed.Equal(expectedLast) {
		t.Errorf("Expected LastUsed %v, got %v", expectedLast, l.LastUsed)
	}
}

func TestParse_MultipleLessons(t *testing.T) {
	input := `# LESSONS.md - Project Level

## Active Lessons

### [L001] [***--|-----] First Lesson
- **Uses**: 10 | **Velocity**: 0.5 | **Learned**: 2025-12-27 | **Last**: 2026-01-18 | **Category**: pattern
> First content.

### [L002] [**---|-----] Second Lesson
- **Uses**: 4 | **Velocity**: 0.1 | **Learned**: 2025-12-28 | **Last**: 2026-01-05 | **Category**: correction
> Second content.

### [S001] [*----|-----] System Lesson
- **Uses**: 1 | **Velocity**: 0.0 | **Learned**: 2025-01-01 | **Last**: 2025-12-01 | **Category**: decision
> System level content.
`

	lessons, err := Parse(strings.NewReader(input))
	if err != nil {
		t.Fatalf("Parse failed: %v", err)
	}

	if len(lessons) != 3 {
		t.Fatalf("Expected 3 lessons, got %d", len(lessons))
	}

	if lessons[0].ID != "L001" {
		t.Errorf("Expected first ID 'L001', got '%s'", lessons[0].ID)
	}
	if lessons[1].ID != "L002" {
		t.Errorf("Expected second ID 'L002', got '%s'", lessons[1].ID)
	}
	if lessons[2].ID != "S001" {
		t.Errorf("Expected third ID 'S001', got '%s'", lessons[2].ID)
	}
}

func TestParse_AllFields(t *testing.T) {
	input := `# LESSONS.md - Project Level

## Active Lessons

### [L001] [***--|-----] Full Lesson
- **Uses**: 7 | **Velocity**: 0.5 | **Learned**: 2025-12-27 | **Last**: 2026-01-18 | **Category**: pattern | **Type**: constraint | **Source**: human | **Promotable**: no | **Triggers**: keyword1, keyword2, keyword3
> Content with all fields.
`

	lessons, err := Parse(strings.NewReader(input))
	if err != nil {
		t.Fatalf("Parse failed: %v", err)
	}

	if len(lessons) != 1 {
		t.Fatalf("Expected 1 lesson, got %d", len(lessons))
	}

	l := lessons[0]
	if l.LessonType != "constraint" {
		t.Errorf("Expected Type 'constraint', got '%s'", l.LessonType)
	}
	if l.Source != "human" {
		t.Errorf("Expected Source 'human', got '%s'", l.Source)
	}
	if l.Promotable != false {
		t.Errorf("Expected Promotable false, got %v", l.Promotable)
	}
	if len(l.Triggers) != 3 {
		t.Errorf("Expected 3 triggers, got %d", len(l.Triggers))
	}
	if l.Triggers[0] != "keyword1" || l.Triggers[1] != "keyword2" || l.Triggers[2] != "keyword3" {
		t.Errorf("Expected triggers [keyword1, keyword2, keyword3], got %v", l.Triggers)
	}
}

func TestParse_AISource(t *testing.T) {
	input := `# LESSONS.md - Project Level

## Active Lessons

### [L001] [***--|-----] AI Generated Lesson 🤖
- **Uses**: 5 | **Velocity**: 0.2 | **Learned**: 2025-12-27 | **Last**: 2026-01-18 | **Category**: pattern | **Source**: ai 🤖
> AI-generated content.
`

	lessons, err := Parse(strings.NewReader(input))
	if err != nil {
		t.Fatalf("Parse failed: %v", err)
	}

	if len(lessons) != 1 {
		t.Fatalf("Expected 1 lesson, got %d", len(lessons))
	}

	l := lessons[0]
	if l.Source != "ai" {
		t.Errorf("Expected Source 'ai', got '%s'", l.Source)
	}
	if l.Title != "AI Generated Lesson" {
		t.Errorf("Expected Title 'AI Generated Lesson', got '%s'", l.Title)
	}
}

func TestParse_MalformedLine(t *testing.T) {
	input := `# LESSONS.md - Project Level

## Active Lessons

### [L001] [***--|-----] Valid Lesson
- **Uses**: 7 | **Velocity**: 0.01 | **Learned**: 2025-12-27 | **Last**: 2026-01-18 | **Category**: pattern
> Valid content.

### This is not a valid header

### [L002] [**---|-----] Another Valid Lesson
- **Uses**: 4 | **Velocity**: 0.5 | **Learned**: 2025-12-27 | **Last**: 2026-01-05 | **Category**: correction
> Another valid content.
`

	lessons, err := Parse(strings.NewReader(input))
	if err != nil {
		t.Fatalf("Parse failed: %v", err)
	}

	if len(lessons) != 2 {
		t.Fatalf("Expected 2 lessons (skipping malformed), got %d", len(lessons))
	}

	if lessons[0].ID != "L001" {
		t.Errorf("Expected first ID 'L001', got '%s'", lessons[0].ID)
	}
	if lessons[1].ID != "L002" {
		t.Errorf("Expected second ID 'L002', got '%s'", lessons[1].ID)
	}
}

func TestSerialize_RoundTrip(t *testing.T) {
	learned, _ := time.Parse("2006-01-02", "2025-12-27")
	lastUsed, _ := time.Parse("2006-01-02", "2026-01-18")

	lessons := []*models.Lesson{
		{
			ID:         "L001",
			Title:      "First Lesson",
			Content:    "First content.",
			Uses:       10,
			Velocity:   0.5,
			Learned:    learned,
			LastUsed:   lastUsed,
			Category:   "pattern",
			Source:     "human",
			Level:      "project",
			Promotable: true,
			LessonType: "",
			Triggers:   []string{},
		},
		{
			ID:         "L002",
			Title:      "Second Lesson",
			Content:    "Second content.",
			Uses:       5,
			Velocity:   0.1,
			Learned:    learned,
			LastUsed:   lastUsed,
			Category:   "correction",
			Source:     "human",
			Level:      "project",
			Promotable: true,
			LessonType: "",
			Triggers:   []string{},
		},
	}

	serialized := Serialize(lessons, "project")
	parsed, err := Parse(strings.NewReader(serialized))
	if err != nil {
		t.Fatalf("Parse failed: %v", err)
	}

	if len(parsed) != len(lessons) {
		t.Fatalf("Expected %d lessons, got %d", len(lessons), len(parsed))
	}

	for i, original := range lessons {
		p := parsed[i]
		if p.ID != original.ID {
			t.Errorf("Lesson %d: Expected ID '%s', got '%s'", i, original.ID, p.ID)
		}
		if p.Title != original.Title {
			t.Errorf("Lesson %d: Expected Title '%s', got '%s'", i, original.Title, p.Title)
		}
		if p.Content != original.Content {
			t.Errorf("Lesson %d: Expected Content '%s', got '%s'", i, original.Content, p.Content)
		}
		if p.Uses != original.Uses {
			t.Errorf("Lesson %d: Expected Uses %d, got %d", i, original.Uses, p.Uses)
		}
		if p.Velocity != original.Velocity {
			t.Errorf("Lesson %d: Expected Velocity %f, got %f", i, original.Velocity, p.Velocity)
		}
		if p.Category != original.Category {
			t.Errorf("Lesson %d: Expected Category '%s', got '%s'", i, original.Category, p.Category)
		}
	}
}

func TestSerializeLesson_AllFields(t *testing.T) {
	learned, _ := time.Parse("2006-01-02", "2025-12-27")
	lastUsed, _ := time.Parse("2006-01-02", "2026-01-18")

	l := &models.Lesson{
		ID:         "L001",
		Title:      "Complete Lesson",
		Content:    "Full content here.",
		Uses:       10,
		Velocity:   1.0,
		Learned:    learned,
		LastUsed:   lastUsed,
		Category:   "pattern",
		Source:     "ai",
		Level:      "project",
		Promotable: false,
		LessonType: "constraint",
		Triggers:   []string{"trigger1", "trigger2"},
	}

	serialized := SerializeLesson(l)

	if !strings.Contains(serialized, "[L001]") {
		t.Error("Expected serialized to contain '[L001]'")
	}
	if !strings.Contains(serialized, "Complete Lesson") {
		t.Error("Expected serialized to contain 'Complete Lesson'")
	}
	if !strings.Contains(serialized, "**Uses**: 10") {
		t.Error("Expected serialized to contain '**Uses**: 10'")
	}
	if !strings.Contains(serialized, "**Velocity**: 1") {
		t.Error("Expected serialized to contain '**Velocity**: 1'")
	}
	if !strings.Contains(serialized, "**Learned**: 2025-12-27") {
		t.Error("Expected serialized to contain '**Learned**: 2025-12-27'")
	}
	if !strings.Contains(serialized, "**Last**: 2026-01-18") {
		t.Error("Expected serialized to contain '**Last**: 2026-01-18'")
	}
	if !strings.Contains(serialized, "**Category**: pattern") {
		t.Error("Expected serialized to contain '**Category**: pattern'")
	}
	if !strings.Contains(serialized, "**Type**: constraint") {
		t.Error("Expected serialized to contain '**Type**: constraint'")
	}
	if !strings.Contains(serialized, "**Source**: ai") {
		t.Error("Expected serialized to contain '**Source**: ai'")
	}
	if !strings.Contains(serialized, "🤖") {
		t.Error("Expected serialized to contain robot emoji for AI source")
	}
	if !strings.Contains(serialized, "**Promotable**: no") {
		t.Error("Expected serialized to contain '**Promotable**: no'")
	}
	if !strings.Contains(serialized, "**Triggers**: trigger1, trigger2") {
		t.Error("Expected serialized to contain '**Triggers**: trigger1, trigger2'")
	}
	if !strings.Contains(serialized, "> Full content here.") {
		t.Error("Expected serialized to contain '> Full content here.'")
	}
}

func TestParse_MultilineContent(t *testing.T) {
	input := `# LESSONS.md - Project Level

## Active Lessons

### [L001] [***--|-----] Multiline Lesson
- **Uses**: 7 | **Velocity**: 0.01 | **Learned**: 2025-12-27 | **Last**: 2026-01-18 | **Category**: pattern
> First line of content.
> Second line of content.
> Third line of content.
`

	lessons, err := Parse(strings.NewReader(input))
	if err != nil {
		t.Fatalf("Parse failed: %v", err)
	}

	if len(lessons) != 1 {
		t.Fatalf("Expected 1 lesson, got %d", len(lessons))
	}

	expectedContent := "First line of content.\nSecond line of content.\nThird line of content."
	if lessons[0].Content != expectedContent {
		t.Errorf("Expected Content '%s', got '%s'", expectedContent, lessons[0].Content)
	}
}
