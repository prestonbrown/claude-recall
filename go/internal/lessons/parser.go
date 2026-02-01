package lessons

import (
	"bufio"
	"fmt"
	"io"
	"os"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/pbrown/claude-recall/internal/models"
)

var (
	// Header pattern: ### [L001] [***--|-----] Lesson Title
	headerPattern = regexp.MustCompile(`^### \[([LS]\d{3})\] \[([*+\-| ]+)\] (.*)$`)

	// Metadata pattern: - **Uses**: 7 | **Velocity**: 0.01 | **Learned**: 2025-12-27 | **Last**: 2026-01-18 | **Category**: pattern
	metadataPattern = regexp.MustCompile(`^\- \*\*Uses\*\*: (\d+) \| \*\*Velocity\*\*: ([\d.]+) \| \*\*Learned\*\*: (\d{4}-\d{2}-\d{2}) \| \*\*Last\*\*: (\d{4}-\d{2}-\d{2}) \| \*\*Category\*\*: (\w+)`)

	// Optional field patterns
	typePattern       = regexp.MustCompile(`\*\*Type\*\*: (\w+)`)
	sourcePattern     = regexp.MustCompile(`\*\*Source\*\*: (\w+)`)
	promotablePattern = regexp.MustCompile(`\*\*Promotable\*\*: (yes|no)`)
	triggersPattern   = regexp.MustCompile(`\*\*Triggers\*\*: (.+?)(?:\s*\||\s*$)`)

	// Content pattern: > Content line
	contentPattern = regexp.MustCompile(`^> (.*)$`)
)

// ParseFile reads and parses a LESSONS.md file
func ParseFile(path string) ([]*models.Lesson, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()

	return Parse(f)
}

// Parse parses LESSONS.md content from a reader
func Parse(r io.Reader) ([]*models.Lesson, error) {
	var lessons []*models.Lesson
	var current *models.Lesson

	scanner := bufio.NewScanner(r)
	for scanner.Scan() {
		line := scanner.Text()

		// Try to parse header
		if matches := headerPattern.FindStringSubmatch(line); matches != nil {
			// Save previous lesson if exists
			if current != nil {
				lessons = append(lessons, current)
			}

			id := matches[1]
			title := strings.TrimSpace(matches[3])

			// Remove robot emoji from title if present
			title = strings.TrimSuffix(title, " 🤖")
			title = strings.TrimSuffix(title, "🤖")
			title = strings.TrimSpace(title)

			current = &models.Lesson{
				ID:         id,
				Title:      title,
				Source:     "human",
				Level:      "project",
				Promotable: true,
				Triggers:   []string{},
			}

			// Determine level from ID
			if strings.HasPrefix(id, "S") {
				current.Level = "system"
			}

			continue
		}

		// Try to parse metadata (only if we have a current lesson)
		if current != nil {
			if matches := metadataPattern.FindStringSubmatch(line); matches != nil {
				current.Uses, _ = strconv.Atoi(matches[1])
				current.Velocity, _ = strconv.ParseFloat(matches[2], 64)
				current.Learned, _ = time.Parse("2006-01-02", matches[3])
				current.LastUsed, _ = time.Parse("2006-01-02", matches[4])
				current.Category = matches[5]

				// Parse optional fields from the rest of the line
				if typeMatch := typePattern.FindStringSubmatch(line); typeMatch != nil {
					current.LessonType = typeMatch[1]
				}

				if sourceMatch := sourcePattern.FindStringSubmatch(line); sourceMatch != nil {
					current.Source = sourceMatch[1]
				}

				if promMatch := promotablePattern.FindStringSubmatch(line); promMatch != nil {
					current.Promotable = promMatch[1] == "yes"
				}

				if trigMatch := triggersPattern.FindStringSubmatch(line); trigMatch != nil {
					triggers := strings.Split(trigMatch[1], ",")
					for i, t := range triggers {
						triggers[i] = strings.TrimSpace(t)
					}
					current.Triggers = triggers
				}

				continue
			}

			// Try to parse content
			if matches := contentPattern.FindStringSubmatch(line); matches != nil {
				if current.Content != "" {
					current.Content += "\n"
				}
				current.Content += matches[1]
				continue
			}
		}
	}

	// Don't forget the last lesson
	if current != nil {
		lessons = append(lessons, current)
	}

	if err := scanner.Err(); err != nil {
		return nil, err
	}

	return lessons, nil
}

// Serialize writes lessons back to LESSONS.md format
func Serialize(lessons []*models.Lesson, level string) string {
	var sb strings.Builder

	// Write header
	levelTitle := "Project"
	if level == "system" {
		levelTitle = "System"
	}

	sb.WriteString(fmt.Sprintf("# LESSONS.md - %s Level\n\n", levelTitle))
	sb.WriteString("> **Lessons System**: Cite lessons with [L###] when applying them.\n")
	sb.WriteString("> Stars accumulate with each use. At 50 uses, project lessons promote to system.\n")
	sb.WriteString(">\n")
	sb.WriteString("> **Add lessons**: `LESSON: [category:] title - content`\n")
	sb.WriteString("> **Categories**: pattern, correction, decision, gotcha, preference\n\n")
	sb.WriteString("## Active Lessons\n\n")

	// Write each lesson
	for _, l := range lessons {
		sb.WriteString(SerializeLesson(l))
		sb.WriteString("\n")
	}

	return sb.String()
}

// SerializeLesson formats a single lesson entry
func SerializeLesson(l *models.Lesson) string {
	var sb strings.Builder

	// Header line
	title := l.Title
	if l.Source == "ai" {
		title += " 🤖"
	}
	sb.WriteString(fmt.Sprintf("### [%s] %s %s\n", l.ID, l.Rating(), title))

	// Metadata line
	sb.WriteString(fmt.Sprintf("- **Uses**: %d | **Velocity**: %g | **Learned**: %s | **Last**: %s | **Category**: %s",
		l.Uses,
		l.Velocity,
		l.Learned.Format("2006-01-02"),
		l.LastUsed.Format("2006-01-02"),
		l.Category,
	))

	// Optional fields
	if l.LessonType != "" {
		sb.WriteString(fmt.Sprintf(" | **Type**: %s", l.LessonType))
	}

	if l.Source == "ai" {
		sb.WriteString(" | **Source**: ai 🤖")
	}

	if !l.Promotable {
		sb.WriteString(" | **Promotable**: no")
	}

	if len(l.Triggers) > 0 {
		sb.WriteString(fmt.Sprintf(" | **Triggers**: %s", strings.Join(l.Triggers, ", ")))
	}

	sb.WriteString("\n")

	// Content lines
	contentLines := strings.Split(l.Content, "\n")
	for _, line := range contentLines {
		sb.WriteString(fmt.Sprintf("> %s\n", line))
	}

	return sb.String()
}
