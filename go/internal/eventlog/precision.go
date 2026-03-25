// SPDX-License-Identifier: GPL-3.0-or-later
package eventlog

// LessonPrecision tracks injection, citation, and dismissal counts for a lesson.
type LessonPrecision struct {
	Injections int
	Citations  int
	Dismissals int
	Sessions   map[string]bool // unique sessions where injected
	Queries    []QueryHit      // queries that triggered injection
}

// QueryHit records a query that triggered an injection of a lesson.
type QueryHit struct {
	Query string
	Score int
	Cited bool
}

// Precision returns citations / (injections + dismissals). Returns 0.0 if denominator is 0.
func (lp *LessonPrecision) Precision() float64 {
	denom := lp.Injections + lp.Dismissals
	if denom == 0 {
		return 0.0
	}
	return float64(lp.Citations) / float64(denom)
}

// PrecisionByLesson computes precision metrics for each lesson from a slice of events.
// Pass 1: count injections, citations, dismissals per lesson; track sessions and queries.
// Pass 2: mark QueryHit.Cited true if the lesson was cited in the same session as the injection.
func PrecisionByLesson(events []Event) map[string]*LessonPrecision {
	result := make(map[string]*LessonPrecision)

	// Helper to ensure a LessonPrecision exists for a given lesson ID.
	get := func(lesson string) *LessonPrecision {
		lp, ok := result[lesson]
		if !ok {
			lp = &LessonPrecision{Sessions: make(map[string]bool)}
			result[lesson] = lp
		}
		return lp
	}

	// Pass 1: count events and record query hits (without Cited flag).
	for _, ev := range events {
		if ev.Lesson == "" {
			continue
		}
		lp := get(ev.Lesson)
		switch ev.Type {
		case "injection":
			lp.Injections++
			lp.Sessions[ev.Session] = true
			lp.Queries = append(lp.Queries, QueryHit{
				Query: ev.Query,
				Score: ev.Score,
			})
		case "citation":
			lp.Citations++
		case "dismissal":
			lp.Dismissals++
		}
	}

	// Build citedSessions: lesson -> set of sessions that have a citation.
	citedSessions := make(map[string]map[string]bool)
	for _, ev := range events {
		if ev.Type == "citation" && ev.Lesson != "" {
			if citedSessions[ev.Lesson] == nil {
				citedSessions[ev.Lesson] = make(map[string]bool)
			}
			citedSessions[ev.Lesson][ev.Session] = true
		}
	}

	// Pass 2: mark QueryHit.Cited by matching injection sessions to citation sessions.
	// Walk injections in the same order they were appended to Queries.
	idxMap := make(map[string]int) // lesson -> next QueryHit index
	for _, ev := range events {
		if ev.Type != "injection" || ev.Lesson == "" {
			continue
		}
		idx := idxMap[ev.Lesson]
		idxMap[ev.Lesson] = idx + 1

		cs := citedSessions[ev.Lesson]
		if cs != nil && cs[ev.Session] {
			result[ev.Lesson].Queries[idx].Cited = true
		}
	}

	return result
}
