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
	// Header pattern. The rating is derived from stats, which now live in the
	// sidecar, so current files omit it: `### [L001] Title`. Pre-split files
	// carry it inline (`### [L001] [***--|-----] Title`) and must still parse.
	headerPattern = regexp.MustCompile(`^### \[([LS]\d{3})\](?: \[([*+\-| ]+)\])? (.*)$`)

	// Any lesson metadata line. Fields are extracted individually below, so a
	// line carrying only durable fields parses the same as a legacy line that
	// still has Uses/Velocity/Last inline.
	metadataPattern = regexp.MustCompile(`^\- \*\*\w+\*\*:`)

	// Field patterns. Uses/Velocity/Last appear only in pre-split files.
	usesPattern     = regexp.MustCompile(`\*\*Uses\*\*: (\d+)`)
	velocityPattern = regexp.MustCompile(`\*\*Velocity\*\*: ([\d.]+)`)
	learnedPattern  = regexp.MustCompile(`\*\*Learned\*\*: (\d{4}-\d{2}-\d{2})`)
	lastPattern     = regexp.MustCompile(`\*\*Last\*\*: (\d{4}-\d{2}-\d{2})`)
	categoryPattern = regexp.MustCompile(`\*\*Category\*\*: (\w+)`)

	// Retired-lesson marker: a replacement ID, or "deleted".
	supersededPattern = regexp.MustCompile(`\*\*Superseded\*\*: (\S+)`)

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
			if metadataPattern.MatchString(line) {
				// Volatile fields: present only in pre-split files. The stats
				// sidecar overrides whatever is found here.
				if m := usesPattern.FindStringSubmatch(line); m != nil {
					current.Uses, _ = strconv.Atoi(m[1])
				}
				if m := velocityPattern.FindStringSubmatch(line); m != nil {
					current.Velocity, _ = strconv.ParseFloat(m[1], 64)
				}
				if m := lastPattern.FindStringSubmatch(line); m != nil {
					current.LastUsed, _ = time.Parse("2006-01-02", m[1])
				}

				// Durable fields.
				if m := learnedPattern.FindStringSubmatch(line); m != nil {
					current.Learned, _ = time.Parse("2006-01-02", m[1])
				}
				if m := categoryPattern.FindStringSubmatch(line); m != nil {
					current.Category = m[1]
				}
				if m := supersededPattern.FindStringSubmatch(line); m != nil {
					current.Superseded = m[1]
				}

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
	// The rating is derived from Uses/Velocity, so it is rendered at display and
	// injection time rather than stored - writing it here would reintroduce the
	// churn the stats sidecar exists to remove.
	sb.WriteString(fmt.Sprintf("### [%s] %s\n", l.ID, title))

	// Metadata line: durable fields only. Uses/Velocity/Last live in stats.json.
	sb.WriteString(fmt.Sprintf("- **Learned**: %s | **Category**: %s",
		l.Learned.Format("2006-01-02"),
		l.Category,
	))

	if l.Superseded != "" {
		sb.WriteString(fmt.Sprintf(" | **Superseded**: %s", l.Superseded))
	}

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
