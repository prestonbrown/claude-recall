package main

import (
	"fmt"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/pbrown/claude-recall/internal/eventlog"
	"github.com/pbrown/claude-recall/internal/lessons"
)

// runStats routes to the appropriate stats subcommand.
func (a *App) runStats(args []string) int {
	if len(args) > 0 {
		switch {
		case args[0] == "--weekly":
			return a.runStatsWeekly()
		default:
			// Treat bare arg as lesson ID (L### or S###)
			if len(args[0]) >= 2 && (args[0][0] == 'L' || args[0][0] == 'S') {
				return a.runStatsLesson(args[0])
			}
		}
	}
	return a.runStatsSession()
}

// runStatsWeekly shows week-over-week trend report (placeholder).
func (a *App) runStatsWeekly() int {
	fmt.Fprintln(a.stdout, "Weekly stats not yet implemented.")
	return 0
}

// runStatsLesson shows lesson-specific precision stats.
func (a *App) runStatsLesson(lessonID string) int {
	// 1. Load lesson metadata via store
	store := lessons.NewStore(a.projectPath, a.systemPath)
	lesson, err := store.Get(lessonID)
	if err != nil {
		fmt.Fprintf(a.stderr, "error: lesson %s not found: %v\n", lessonID, err)
		return 1
	}

	// 2. Load events for this lesson (30-day window)
	eventLogPath := filepath.Join(a.stateDir, "session-log.jsonl")
	elog := eventlog.New(eventLogPath)
	since := time.Now().AddDate(0, 0, -30)
	events, err := elog.ReadFiltered(eventlog.Filter{Lesson: lessonID, Since: since})
	if err != nil {
		fmt.Fprintf(a.stderr, "error reading event log: %v\n", err)
		return 1
	}

	// 3. Compute precision
	precisionMap := eventlog.PrecisionByLesson(events)
	p := precisionMap[lessonID]

	// 4. Output
	fmt.Fprintf(a.stdout, "Lesson %s: %s\n", lessonID, lesson.Title)
	fmt.Fprintf(a.stdout, "  Rating: %s  Uses: %d  Velocity: %.1f\n\n", lesson.Rating(), lesson.Uses, lesson.Velocity)

	if p == nil {
		fmt.Fprintln(a.stdout, "  No injection/citation events in the last 30 days.")
		return 0
	}

	fmt.Fprintln(a.stdout, "  Injection History (30d):")
	fmt.Fprintf(a.stdout, "    Injected: %d times across %d sessions\n", p.Injections, len(p.Sessions))
	fmt.Fprintf(a.stdout, "    Cited:    %d times\n", p.Citations)
	if p.Dismissals > 0 {
		fmt.Fprintf(a.stdout, "    Dismissed: %d times\n", p.Dismissals)
	}
	fmt.Fprintf(a.stdout, "    Precision: %.1f%%\n", p.Precision()*100)

	// 5. Top triggering queries (deduplicated, sorted by score, top 5)
	if len(p.Queries) > 0 {
		type queryInfo struct {
			query string
			score int
			count int
			cited bool
		}
		seen := make(map[string]*queryInfo)
		for _, q := range p.Queries {
			if q.Query == "" {
				continue
			}
			if qi, ok := seen[q.Query]; ok {
				qi.count++
				if q.Score > qi.score {
					qi.score = q.Score
				}
				if q.Cited {
					qi.cited = true
				}
			} else {
				seen[q.Query] = &queryInfo{query: q.Query, score: q.Score, count: 1, cited: q.Cited}
			}
		}

		// Sort by score descending
		var sorted []*queryInfo
		for _, qi := range seen {
			sorted = append(sorted, qi)
		}
		sort.Slice(sorted, func(i, j int) bool { return sorted[i].score > sorted[j].score })

		fmt.Fprintln(a.stdout, "\n  Top triggering queries (by BM25 score):")
		limit := 5
		if len(sorted) < limit {
			limit = len(sorted)
		}
		for _, qi := range sorted[:limit] {
			truncated := qi.query
			if len(truncated) > 60 {
				truncated = truncated[:57] + "..."
			}
			cited := "NOT cited"
			if qi.cited {
				cited = "cited"
			}
			fmt.Fprintf(a.stdout, "    \"%s\" -> score %d, %s\n", truncated, qi.score, cited)
		}
	}

	// 6. Trigger info
	fmt.Fprintln(a.stdout)
	if len(lesson.Triggers) > 0 {
		fmt.Fprintf(a.stdout, "  Current triggers: %s\n", strings.Join(lesson.Triggers, ", "))
	} else {
		fmt.Fprintln(a.stdout, "  Current triggers: (none)")
	}

	return 0
}

// runStatsSession shows injection/citation breakdown for the current session.
func (a *App) runStatsSession() int {
	eventLogPath := filepath.Join(a.stateDir, "session-log.jsonl")
	elog := eventlog.New(eventLogPath)
	events, err := elog.Read()
	if err != nil {
		fmt.Fprintf(a.stderr, "error reading event log: %v\n", err)
		return 1
	}
	if len(events) == 0 {
		fmt.Fprintln(a.stdout, "No events recorded yet.")
		return 0
	}

	// Find latest session ID
	sessionID := ""
	for i := len(events) - 1; i >= 0; i-- {
		if events[i].Session != "" {
			sessionID = events[i].Session
			break
		}
	}
	if sessionID == "" {
		fmt.Fprintln(a.stdout, "No session data found.")
		return 0
	}

	// Filter to this session
	var sessionEvents []eventlog.Event
	for _, e := range events {
		if e.Session == sessionID {
			sessionEvents = append(sessionEvents, e)
		}
	}

	// Count injections and citations
	injections := make(map[string]int)
	citations := make(map[string]bool)
	injectionScores := make(map[string]int)
	for _, e := range sessionEvents {
		switch e.Type {
		case "injection":
			injections[e.Lesson]++
			if e.Score > injectionScores[e.Lesson] {
				injectionScores[e.Lesson] = e.Score
			}
		case "citation":
			citations[e.Lesson] = true
		}
	}

	totalInjections := 0
	for _, count := range injections {
		totalInjections += count
	}

	fmt.Fprintln(a.stdout, "This Session")
	fmt.Fprintf(a.stdout, "  Injections: %d (%d unique lessons)\n", totalInjections, len(injections))
	fmt.Fprintf(a.stdout, "  Citations:  %d\n", len(citations))
	if totalInjections > 0 {
		precision := float64(len(citations)) / float64(totalInjections) * 100
		fmt.Fprintf(a.stdout, "  Precision:  %.1f%%\n", precision)
	}

	// Hits — injected lessons that were cited
	fmt.Fprintln(a.stdout)
	hasHits := false
	for lesson := range citations {
		if !hasHits {
			fmt.Fprintln(a.stdout, "  Hits:")
			hasHits = true
		}
		fmt.Fprintf(a.stdout, "    [%s] (score %d, cited)\n", lesson, injectionScores[lesson])
	}

	// Noise — injected lessons that were never cited
	hasNoise := false
	for lesson, count := range injections {
		if citations[lesson] {
			continue
		}
		if !hasNoise {
			fmt.Fprintln(a.stdout, "  Noise:")
			hasNoise = true
		}
		if count > 1 {
			fmt.Fprintf(a.stdout, "    [%s] (score %d, injected %dx, never cited)\n", lesson, injectionScores[lesson], count)
		} else {
			fmt.Fprintf(a.stdout, "    [%s] (score %d, never cited)\n", lesson, injectionScores[lesson])
		}
	}

	return 0
}
