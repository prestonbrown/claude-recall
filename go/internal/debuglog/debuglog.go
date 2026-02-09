// Package debuglog provides structured JSONL logging for claude-recall.
// Writes to {stateDir}/recall.log at configurable debug levels.
package debuglog

import (
	"encoding/json"
	"os"
	"path/filepath"
	"time"
)

// Logger writes structured log entries to the debug log file.
type Logger struct {
	stateDir   string
	debugLevel int
}

// New creates a Logger. Logging is a no-op if debugLevel < minLevel on each call.
func New(stateDir string, debugLevel int) *Logger {
	return &Logger{stateDir: stateDir, debugLevel: debugLevel}
}

// LessonEntry is a compact representation of an injected lesson for logging.
type LessonEntry struct {
	ID    string `json:"id"`
	Title string `json:"title"`
}

// LogInjection logs which lessons were injected, when, and for which project.
// hook: "session_start" or "prompt_submit"
func (l *Logger) LogInjection(hook string, projectDir string, lessons []LessonEntry) {
	if l.debugLevel < 1 {
		return
	}

	ids := make([]string, len(lessons))
	for i, le := range lessons {
		ids[i] = le.ID
	}

	l.write(map[string]interface{}{
		"event":       "lessons_injected",
		"level":       "info",
		"hook":        hook,
		"project_dir": projectDir,
		"count":       len(lessons),
		"lesson_ids":  ids,
		"lessons":     lessons,
	})
}

// LogInjectionSkip logs when injection was skipped and why.
func (l *Logger) LogInjectionSkip(hook string, projectDir string, reason string, detail string) {
	if l.debugLevel < 1 {
		return
	}

	l.write(map[string]interface{}{
		"event":       "lessons_injection_skipped",
		"level":       "info",
		"hook":        hook,
		"project_dir": projectDir,
		"reason":      reason,
		"detail":      detail,
	})
}

// LogScoreRelevanceError logs errors from the score-relevance command.
func (l *Logger) LogScoreRelevanceError(query string, errMsg string) {
	if l.debugLevel < 1 {
		return
	}

	l.write(map[string]interface{}{
		"event": "score_relevance_error",
		"level": "warn",
		"query": query,
		"error": errMsg,
	})
}

// LogStopHook logs stop hook processing results.
func (l *Logger) LogStopHook(sessionID string, citationsProcessed int, citationIDs []string, lessonsAdded int, errors []string) {
	if l.debugLevel < 1 {
		return
	}

	l.write(map[string]interface{}{
		"event":               "stop_hook_processed",
		"level":               "info",
		"session_id":          sessionID,
		"citations_processed": citationsProcessed,
		"citation_ids":        citationIDs,
		"lessons_added":       lessonsAdded,
		"errors":              errors,
	})
}

func (l *Logger) write(entry map[string]interface{}) {
	entry["timestamp"] = time.Now().Format(time.RFC3339)

	logPath := filepath.Join(l.stateDir, "recall.log")
	f, err := os.OpenFile(logPath, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		return
	}
	defer f.Close()

	data, err := json.Marshal(entry)
	if err != nil {
		return
	}
	f.WriteString(string(data) + "\n")
}
