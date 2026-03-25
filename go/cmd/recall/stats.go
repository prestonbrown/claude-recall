package main

import (
	"fmt"
	"path/filepath"

	"github.com/pbrown/claude-recall/internal/eventlog"
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

// runStatsLesson shows lesson-specific precision stats (placeholder).
func (a *App) runStatsLesson(id string) int {
	fmt.Fprintf(a.stdout, "Lesson stats for %s not yet implemented.\n", id)
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
