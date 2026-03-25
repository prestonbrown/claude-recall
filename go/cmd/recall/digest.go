package main

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"time"

	"github.com/pbrown/claude-recall/internal/eventlog"
)

// runDigest generates or displays the weekly precision digest report.
func (a *App) runDigest(args []string) int {
	generate := len(args) > 0 && args[0] == "--generate"
	reportsDir := filepath.Join(a.stateDir, "reports")
	year, week := time.Now().ISOWeek()
	reportName := fmt.Sprintf("weekly-%d-W%02d.md", year, week)
	reportPath := filepath.Join(reportsDir, reportName)

	if generate {
		os.MkdirAll(reportsDir, 0755)

		eventLogPath := filepath.Join(a.stateDir, "session-log.jsonl")
		elog := eventlog.New(eventLogPath)
		since := time.Now().AddDate(0, 0, -7)
		events, err := elog.ReadFiltered(eventlog.Filter{Since: since})
		if err != nil || len(events) == 0 {
			fmt.Fprintln(a.stdout, "No events to generate digest from.")
			return 0
		}

		// Count totals
		sessions := make(map[string]bool)
		var injCount, citCount int
		for _, e := range events {
			sessions[e.Session] = true
			switch e.Type {
			case "injection":
				injCount++
			case "citation":
				citCount++
			}
		}

		f, err := os.Create(reportPath)
		if err != nil {
			fmt.Fprintf(a.stderr, "error creating report: %v\n", err)
			return 1
		}
		defer f.Close()

		fmt.Fprintf(f, "# Weekly Digest %d-W%02d\n\n", year, week)
		fmt.Fprintf(f, "Generated: %s\n\n", time.Now().Format(time.RFC3339))
		fmt.Fprintf(f, "## Summary\n\n")
		fmt.Fprintf(f, "- Sessions: %d\n", len(sessions))
		fmt.Fprintf(f, "- Injections: %d\n", injCount)
		fmt.Fprintf(f, "- Citations: %d\n", citCount)
		if injCount > 0 {
			fmt.Fprintf(f, "- Precision: %.1f%%\n", float64(citCount)/float64(injCount)*100)
		}

		// Per-lesson precision
		precisionMap := eventlog.PrecisionByLesson(events)
		type ls struct {
			id   string
			prec float64
		}
		var performers, offenders []ls
		for id, p := range precisionMap {
			if p.Injections < 2 {
				continue
			}
			pr := p.Precision()
			if pr >= 0.5 {
				performers = append(performers, ls{id, pr})
			}
			if pr < 0.2 {
				offenders = append(offenders, ls{id, pr})
			}
		}
		sort.Slice(performers, func(i, j int) bool { return performers[i].prec > performers[j].prec })
		sort.Slice(offenders, func(i, j int) bool { return offenders[i].prec < offenders[j].prec })

		if len(performers) > 0 {
			fmt.Fprintf(f, "\n## Top Performers\n\n")
			for i, s := range performers {
				if i >= 5 {
					break
				}
				fmt.Fprintf(f, "- [%s] (%.0f%%)\n", s.id, s.prec*100)
			}
		}
		if len(offenders) > 0 {
			fmt.Fprintf(f, "\n## Noise Offenders\n\n")
			for i, s := range offenders {
				if i >= 5 {
					break
				}
				fmt.Fprintf(f, "- [%s] (%.0f%%)\n", s.id, s.prec*100)
			}
		}

		// Update last-run timestamp
		os.WriteFile(filepath.Join(a.stateDir, ".digest-last-run"), []byte(time.Now().Format(time.RFC3339)), 0644)

		fmt.Fprintf(a.stdout, "Digest generated: %s\n", reportPath)
		return 0
	}

	// Display mode: show latest report
	data, err := os.ReadFile(reportPath)
	if err != nil {
		// Try to find any report
		entries, _ := os.ReadDir(reportsDir)
		if len(entries) == 0 {
			fmt.Fprintln(a.stdout, "No digest reports found. Run `recall digest --generate` to create one.")
			return 0
		}
		latest := entries[len(entries)-1]
		data, err = os.ReadFile(filepath.Join(reportsDir, latest.Name()))
		if err != nil {
			fmt.Fprintf(a.stderr, "error reading report: %v\n", err)
			return 1
		}
	}
	fmt.Fprint(a.stdout, string(data))
	return 0
}
