package main

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/pbrown/claude-recall/internal/anthropic"
	"github.com/pbrown/claude-recall/internal/config"
	"github.com/pbrown/claude-recall/internal/debuglog"
	"github.com/pbrown/claude-recall/internal/eventlog"
	"github.com/pbrown/claude-recall/internal/feedback"
	"github.com/pbrown/claude-recall/internal/lessons"
	"github.com/pbrown/claude-recall/internal/models"
	"github.com/pbrown/claude-recall/internal/scoring"
)

// App encapsulates CLI state and dependencies for testability
type App struct {
	stdin           io.Reader
	stdout          io.Writer
	stderr          io.Writer
	projectPath     string         // Path to project LESSONS.md
	systemPath      string         // Path to system LESSONS.md
	stateDir        string         // Path to state directory
	projectDir      string         // Project root directory
	debugLevel      int            // Debug level 0-3
	eventLogEnabled bool           // Whether event logging is enabled
	cfg             *config.Config // Loaded configuration
}

// NewApp creates a new App with default stdout/stderr/stdin
func NewApp() *App {
	return &App{
		stdin:  os.Stdin,
		stdout: os.Stdout,
		stderr: os.Stderr,
	}
}

// initPaths initializes paths from config if not already set
func (a *App) initPaths() error {
	if a.projectPath != "" && a.systemPath != "" {
		return nil
	}

	// Load config (from default path)
	homeDir, _ := os.UserHomeDir()
	configPath := filepath.Join(homeDir, ".config", "claude-recall", "config.json")
	cfg, err := config.Load(configPath)
	if err != nil {
		return fmt.Errorf("failed to load config: %w", err)
	}

	// Set paths based on config
	if a.projectPath == "" {
		a.projectPath = filepath.Join(cfg.ProjectDir, ".claude-recall", "LESSONS.md")
	}
	if a.systemPath == "" {
		a.systemPath = filepath.Join(cfg.StateDir, "LESSONS.md")
	}
	if a.stateDir == "" {
		a.stateDir = cfg.StateDir
	}
	a.projectDir = cfg.ProjectDir
	a.debugLevel = cfg.DebugLevel
	a.cfg = cfg
	a.eventLogEnabled = cfg.EventLogEnabled != nil && *cfg.EventLogEnabled

	return nil
}

// Run parses arguments and dispatches to commands
func (a *App) Run(args []string) int {
	if len(args) < 2 {
		a.printUsageTo(a.stderr)
		return 1
	}

	cmd := args[1]
	cmdArgs := args[2:]

	// Handle help flags before initializing paths
	if cmd == "help" || cmd == "--help" || cmd == "-h" {
		a.printHelp()
		return 0
	}

	if err := a.initPaths(); err != nil {
		fmt.Fprintf(a.stderr, "error: %v\n", err)
		return 1
	}

	switch cmd {
	case "inject":
		return a.runInject(cmdArgs)
	case "add":
		return a.runAdd(cmdArgs)
	case "cite":
		return a.runCite(cmdArgs)
	case "list":
		return a.runList(cmdArgs)
	case "show":
		return a.runShow(cmdArgs)
	case "edit":
		return a.runEdit(cmdArgs)
	case "delete":
		return a.runDelete(cmdArgs)
	case "supersede":
		return a.runSupersede(cmdArgs)
	case "validate":
		return a.runValidate(cmdArgs)
	case "decay":
		return a.runDecay(cmdArgs)
	case "debug":
		return a.runDebug(cmdArgs)
	case "score-relevance":
		return a.runScoreRelevance(cmdArgs)
	case "score-local":
		return a.runScoreLocal(cmdArgs)
	case "prescore-cache":
		return a.runPrescoreCache(cmdArgs)
	case "opencode":
		return a.runOpencode(cmdArgs)
	case "dismiss":
		return a.runDismiss(cmdArgs)
	case "stats":
		return a.runStats(cmdArgs)
	case "digest":
		return a.runDigest(cmdArgs)
	default:
		fmt.Fprintf(a.stderr, "unknown command: %s\n", cmd)
		a.printUsageTo(a.stderr)
		return 1
	}
}

// printHelp prints the help message
func (a *App) printHelp() {
	a.printUsageTo(a.stdout)
}

// printUsageTo writes the usage text to w. Error paths pass stderr: hooks parse
// this CLI's stdout as JSON, so usage text there corrupts the payload.
func (a *App) printUsageTo(w io.Writer) {
	help := `Claude Recall - AI coding agent memory system

Usage: recall <command> [args...]

Commands:
  inject [n]                       Output top n lessons for context injection
  add <cat> <title> <content>      Add a new lesson (--system for system level)
  cite <id> [id...]                Cite one or more lessons (increment uses)
  list                             List all lessons with ratings
  show <id>                        Show detailed lesson information
  edit <id> [--title T] [...]      Edit a lesson's properties
  delete <id>                      Delete a lesson
  decay [--force]                  Run velocity decay cycle
  dismiss <id>                     Dismiss a lesson as noise for this session
  supersede <old> <new>            Retire <old>, redirecting it to <new>
  validate [--strict]              Check lessons against the current project tree
  validate --dismiss <id> <token>  Record a reviewed reference as fine


  debug log <message>              Log a debug message
  debug log-error <key> <msg>      Log an error event
  debug hook-phase <h> <p> <ms>    Log hook phase timing
  debug hook-end <h> <ms> [--phases json]  Log hook completion
  debug injection-budget <t> <l> <d>       Log token budget breakdown

  stats                            Session injection/citation breakdown
  stats <id>                       Lesson-specific precision stats
  stats --weekly                   Week-over-week trend report

  digest                           Show latest weekly precision digest
  digest --generate                Generate fresh digest for current week

  score-relevance <query> [opts]   Score lessons by relevance (Haiku API)
  score-local <query> [opts]       Score lessons locally using BM25 (no API key)
  prescore-cache --transcript <p>  Pre-warm relevance cache

Options:
  help, --help, -h                 Show this help message
`
	fmt.Fprint(w, help)
}

// runInject outputs top n lessons
func (a *App) runInject(args []string) int {
	n := 5
	if len(args) > 0 {
		if parsed, err := strconv.Atoi(args[0]); err == nil {
			n = parsed
		}
	}

	store := lessons.NewStore(a.projectPath, a.systemPath)
	allLessons, err := store.List()
	if err != nil {
		fmt.Fprintf(a.stderr, "error listing lessons: %v\n", err)
		return 1
	}

	// Sort by uses + velocity (combined score)
	sort.Slice(allLessons, func(i, j int) bool {
		scoreI := float64(allLessons[i].Uses) + allLessons[i].Velocity
		scoreJ := float64(allLessons[j].Uses) + allLessons[j].Velocity
		return scoreI > scoreJ
	})

	// Take top n
	if n > len(allLessons) {
		n = len(allLessons)
	}
	topLessons := allLessons[:n]

	// Log which lessons are being injected
	dlog := debuglog.New(a.stateDir, a.debugLevel)
	entries := make([]debuglog.LessonEntry, len(topLessons))
	for i, l := range topLessons {
		entries[i] = debuglog.LessonEntry{ID: l.ID, Title: l.Title}
	}
	dlog.LogInjection("session_start", a.projectDir, entries)

	// Output in inject format
	if len(topLessons) == 0 {
		fmt.Fprintln(a.stdout, "No lessons found.")
		return 0
	}

	fmt.Fprintln(a.stdout, "## Recent Lessons")
	fmt.Fprintln(a.stdout)

	for _, l := range topLessons {
		fmt.Fprintf(a.stdout, "### [%s] %s %s\n", l.ID, l.Rating(), l.Title)
		fmt.Fprintf(a.stdout, "> %s\n\n", l.Content)
	}

	return 0
}

// runAdd creates a new lesson
func (a *App) runAdd(args []string) int {
	if len(args) < 3 {
		fmt.Fprintln(a.stderr, "usage: recall add <category> <title> <content> [--system]")
		return 1
	}

	category := args[0]
	title := args[1]
	content := args[2]
	level := "project"

	// Check for --system flag
	for i := 3; i < len(args); i++ {
		if args[i] == "--system" {
			level = "system"
		}
	}

	store := lessons.NewStore(a.projectPath, a.systemPath)
	lesson, err := store.Add(level, category, title, content)
	if err != nil {
		fmt.Fprintf(a.stderr, "error adding lesson: %v\n", err)
		return 1
	}

	fmt.Fprintf(a.stdout, "Added lesson %s: %s\n", lesson.ID, title)
	return 0
}

// runCite cites one or more lessons
func (a *App) runCite(args []string) int {
	if len(args) < 1 {
		fmt.Fprintln(a.stderr, "usage: recall cite <id> [id...]")
		return 1
	}

	store := lessons.NewStore(a.projectPath, a.systemPath)

	for _, id := range args {
		if err := store.Cite(id); err != nil {
			fmt.Fprintf(a.stderr, "error citing %s: %v\n", id, err)
			return 1
		}
		fmt.Fprintf(a.stdout, "Cited lesson %s\n", id)
	}

	return 0
}

// runList lists all lessons
func (a *App) runList(args []string) int {
	// --search filters on ID, title and content, case-insensitively, so a
	// partial ID ("L00") and a word from the body both work. Documented in
	// commands/lessons.md.
	search := ""
	for i := 0; i < len(args); i++ {
		if args[i] != "--search" {
			continue
		}
		if i+1 >= len(args) {
			fmt.Fprintln(a.stderr, "usage: recall list [--search <term>]")
			return 1
		}
		search = args[i+1]
		i++
	}

	store := lessons.NewStore(a.projectPath, a.systemPath)
	allLessons, err := store.List()
	if err != nil {
		fmt.Fprintf(a.stderr, "error listing lessons: %v\n", err)
		return 1
	}

	if search != "" {
		term := strings.ToLower(search)
		matched := allLessons[:0:0]
		for _, l := range allLessons {
			haystack := strings.ToLower(l.ID + " " + l.Title + " " + l.Content)
			if strings.Contains(haystack, term) {
				matched = append(matched, l)
			}
		}
		allLessons = matched
	}

	if len(allLessons) == 0 {
		fmt.Fprintln(a.stdout, "No lessons found.")
		return 0
	}

	for _, l := range allLessons {
		fmt.Fprintf(a.stdout, "%s %s %s (%s)\n", l.ID, l.Rating(), l.Title, l.Category)
	}

	return 0
}

// runShow shows a single lesson in detail
func (a *App) runShow(args []string) int {
	if len(args) < 1 {
		fmt.Fprintln(a.stderr, "usage: recall show <id>")
		return 1
	}

	id := args[0]
	store := lessons.NewStore(a.projectPath, a.systemPath)

	lesson, err := store.Get(id)
	if err != nil {
		fmt.Fprintf(a.stderr, "error: %v\n", err)
		return 1
	}

	// A retired lesson still resolves so that a stale `[L###]` in a source
	// comment gets an answer. Lead with where the content went.
	if lesson.IsTombstone() {
		if lesson.Superseded == models.TombstoneDeleted {
			fmt.Fprintf(a.stdout, "RETIRED: %s was deleted and has no replacement.\n\n", lesson.ID)
		} else {
			fmt.Fprintf(a.stdout, "RETIRED: %s was superseded by %s - see that lesson instead.\n\n",
				lesson.ID, lesson.Superseded)
		}
	}

	fmt.Fprintf(a.stdout, "ID: %s\n", lesson.ID)
	fmt.Fprintf(a.stdout, "Title: %s\n", lesson.Title)
	fmt.Fprintf(a.stdout, "Category: %s\n", lesson.Category)
	fmt.Fprintf(a.stdout, "Level: %s\n", lesson.Level)
	fmt.Fprintf(a.stdout, "Uses: %d\n", lesson.Uses)
	fmt.Fprintf(a.stdout, "Velocity: %.2f\n", lesson.Velocity)
	fmt.Fprintf(a.stdout, "Learned: %s\n", lesson.Learned.Format("2006-01-02"))
	fmt.Fprintf(a.stdout, "Last Used: %s\n", lesson.LastUsed.Format("2006-01-02"))
	fmt.Fprintf(a.stdout, "Rating: %s\n", lesson.Rating())
	fmt.Fprintf(a.stdout, "\nContent:\n%s\n", lesson.Content)

	return 0
}

// runEdit modifies an existing lesson
func (a *App) runEdit(args []string) int {
	if len(args) < 1 {
		fmt.Fprintln(a.stderr, "usage: recall edit <id> [--title T] [--content C] [--category C]")
		return 1
	}

	id := args[0]
	updates := make(map[string]interface{})

	// Parse flags
	for i := 1; i < len(args); i++ {
		switch args[i] {
		case "--title":
			if i+1 < len(args) {
				updates["title"] = args[i+1]
				i++
			}
		case "--content":
			if i+1 < len(args) {
				updates["content"] = args[i+1]
				i++
			}
		case "--category":
			if i+1 < len(args) {
				updates["category"] = args[i+1]
				i++
			}
		}
	}

	if len(updates) == 0 {
		fmt.Fprintln(a.stderr, "no updates specified")
		return 1
	}

	store := lessons.NewStore(a.projectPath, a.systemPath)
	if err := store.Edit(id, updates); err != nil {
		fmt.Fprintf(a.stderr, "error editing lesson: %v\n", err)
		return 1
	}

	// Reset injection-stats when lesson content changes
	if strings.HasPrefix(id, "L") {
		projectStatsPath := feedback.StatsFilePath(filepath.Join(a.projectDir, ".claude-recall"))
		feedback.ResetLesson(projectStatsPath, id)
	} else {
		systemStatsPath := feedback.StatsFilePath(a.stateDir)
		feedback.ResetLesson(systemStatsPath, id)
	}

	fmt.Fprintf(a.stdout, "Updated lesson %s\n", id)
	return 0
}

// runDelete deletes a lesson
func (a *App) runDelete(args []string) int {
	if len(args) < 1 {
		fmt.Fprintln(a.stderr, "usage: recall delete <id>")
		return 1
	}

	id := args[0]
	store := lessons.NewStore(a.projectPath, a.systemPath)

	if err := store.Delete(id); err != nil {
		fmt.Fprintf(a.stderr, "error deleting lesson: %v\n", err)
		return 1
	}

	fmt.Fprintf(a.stdout, "Retired lesson %s (ID kept so existing [%s] references still resolve)\n", id, id)
	return 0
}

// runSupersede retires a lesson and points it at its replacement.
func (a *App) runSupersede(args []string) int {
	if len(args) < 2 {
		fmt.Fprintln(a.stderr, "usage: recall supersede <old-id> <new-id>")
		return 1
	}

	oldID, newID := args[0], args[1]
	store := lessons.NewStore(a.projectPath, a.systemPath)

	if err := store.Supersede(oldID, newID); err != nil {
		fmt.Fprintf(a.stderr, "error: %v\n", err)
		return 1
	}

	fmt.Fprintf(a.stdout, "Superseded %s by %s - `recall show %s` now redirects\n", oldID, newID, oldID)
	return 0
}

// runDecay runs decay cycle
func (a *App) runDecay(args []string) int {
	force := false
	for _, arg := range args {
		if arg == "--force" {
			force = true
		}
	}

	store := lessons.NewStore(a.projectPath, a.systemPath)

	var count int
	var err error

	if force {
		count, err = lessons.ForceDecay(store)
	} else {
		cfg := lessons.DecayConfig{
			StateFile:     filepath.Join(a.stateDir, "decay_state.json"),
			DecayInterval: 7 * 24 * time.Hour, // 7 days
		}
		count, err = lessons.Decay(store, cfg)
	}

	if err != nil {
		fmt.Fprintf(a.stderr, "error running decay: %v\n", err)
		return 1
	}

	if count > 0 {
		fmt.Fprintf(a.stdout, "Decayed %d lessons\n", count)
	} else {
		fmt.Fprintln(a.stdout, "No decay needed")
	}

	return 0
}

// runDismiss logs a dismiss event for a lesson (noise signal)
func (a *App) runDismiss(args []string) int {
	if len(args) < 1 {
		fmt.Fprintln(a.stderr, "usage: recall dismiss <ID>")
		return 1
	}
	lessonID := args[0]

	store := lessons.NewStore(a.projectPath, a.systemPath)
	lesson, err := store.Get(lessonID)
	if err != nil {
		fmt.Fprintf(a.stderr, "error: lesson %s not found: %v\n", lessonID, err)
		return 1
	}

	eventLogPath := filepath.Join(a.stateDir, "session-log.jsonl")
	elog := eventlog.New(eventLogPath)
	err = elog.Append(eventlog.Event{
		Timestamp: time.Now(),
		Type:      "dismiss",
		Lesson:    lessonID,
		Project:   a.projectDir,
	})
	if err != nil {
		fmt.Fprintf(a.stderr, "error logging dismiss: %v\n", err)
		return 1
	}

	// Reset injection-stats for dismissed lesson
	if strings.HasPrefix(lessonID, "L") {
		projectStatsPath := feedback.StatsFilePath(filepath.Join(a.projectDir, ".claude-recall"))
		feedback.ResetLesson(projectStatsPath, lessonID)
	} else {
		systemStatsPath := feedback.StatsFilePath(a.stateDir)
		feedback.ResetLesson(systemStatsPath, lessonID)
	}

	fmt.Fprintf(a.stdout, "Dismissed [%s] %s for this session.\n", lessonID, lesson.Title)
	return 0
}

// runDebug dispatches to debug subcommands
func (a *App) runDebug(args []string) int {
	if len(args) < 1 {
		fmt.Fprintln(a.stderr, "usage: recall debug <subcommand> [args...]")
		fmt.Fprintln(a.stderr, "  log <message>              - Log a debug message")
		fmt.Fprintln(a.stderr, "  log-error <key> <message>  - Log an error event")
		fmt.Fprintln(a.stderr, "  hook-phase <h> <p> <ms>    - Log hook phase timing")
		fmt.Fprintln(a.stderr, "  hook-end <h> <ms> [--phases json] - Log hook end")
		fmt.Fprintln(a.stderr, "  injection-budget <t> <l> <d>  - Log token budget")
		return 1
	}

	subcmd := args[0]
	subArgs := args[1:]

	switch subcmd {
	case "log":
		return a.runDebugLog(subArgs)
	case "log-error":
		return a.runDebugLogError(subArgs)
	case "hook-phase":
		return a.runDebugHookPhase(subArgs)
	case "hook-end":
		return a.runDebugHookEnd(subArgs)
	case "injection-budget":
		return a.runDebugInjectionBudget(subArgs)
	default:
		fmt.Fprintf(a.stderr, "unknown debug subcommand: %s\n", subcmd)
		return 1
	}
}

// runDebugLog logs a debug message
func (a *App) runDebugLog(args []string) int {
	if len(args) < 1 {
		fmt.Fprintln(a.stderr, "usage: recall debug log <message>")
		return 1
	}

	message := strings.Join(args, " ")

	logPath := filepath.Join(a.stateDir, "recall.log")
	f, err := os.OpenFile(logPath, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		fmt.Fprintf(a.stderr, "error opening log file: %v\n", err)
		return 1
	}
	defer f.Close()

	timestamp := time.Now().Format(time.RFC3339)
	logEntry := map[string]interface{}{
		"timestamp": timestamp,
		"event":     "log",
		"level":     "debug",
		"message":   message,
	}

	data, _ := json.Marshal(logEntry)
	f.WriteString(string(data) + "\n")

	return 0
}

// runDebugLogError logs an error event
func (a *App) runDebugLogError(args []string) int {
	if len(args) < 2 {
		fmt.Fprintln(a.stderr, "usage: recall debug log-error <key> <message>")
		return 1
	}

	key := args[0]
	message := strings.Join(args[1:], " ")

	logPath := filepath.Join(a.stateDir, "recall.log")
	f, err := os.OpenFile(logPath, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		fmt.Fprintf(a.stderr, "error opening log file: %v\n", err)
		return 1
	}
	defer f.Close()

	timestamp := time.Now().Format(time.RFC3339)
	logEntry := map[string]interface{}{
		"timestamp": timestamp,
		"event":     key,
		"level":     "error",
		"message":   message,
	}

	data, _ := json.Marshal(logEntry)
	f.WriteString(string(data) + "\n")

	return 0
}

// runDebugHookPhase logs hook phase timing
func (a *App) runDebugHookPhase(args []string) int {
	if len(args) < 3 {
		fmt.Fprintln(a.stderr, "usage: recall debug hook-phase <hook> <phase> <ms> [--details json]")
		return 1
	}

	hook := args[0]
	phase := args[1]
	ms, err := strconv.ParseFloat(args[2], 64)
	if err != nil {
		fmt.Fprintf(a.stderr, "error parsing ms: %v\n", err)
		return 1
	}

	var details map[string]interface{}
	for i := 3; i < len(args); i++ {
		if args[i] == "--details" && i+1 < len(args) {
			json.Unmarshal([]byte(args[i+1]), &details)
			i++
		}
	}

	logPath := filepath.Join(a.stateDir, "recall.log")
	f, err := os.OpenFile(logPath, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		fmt.Fprintf(a.stderr, "error opening log file: %v\n", err)
		return 1
	}
	defer f.Close()

	timestamp := time.Now().Format(time.RFC3339)
	logEntry := map[string]interface{}{
		"timestamp": timestamp,
		"event":     "hook_phase",
		"level":     "debug",
		"hook":      hook,
		"phase":     phase,
		"ms":        ms,
	}
	if details != nil {
		logEntry["details"] = details
	}

	data, _ := json.Marshal(logEntry)
	f.WriteString(string(data) + "\n")

	return 0
}

// runDebugHookEnd logs hook end timing
func (a *App) runDebugHookEnd(args []string) int {
	if len(args) < 2 {
		fmt.Fprintln(a.stderr, "usage: recall debug hook-end <hook> <total_ms> [--phases json]")
		return 1
	}

	hook := args[0]
	totalMs, err := strconv.ParseFloat(args[1], 64)
	if err != nil {
		fmt.Fprintf(a.stderr, "error parsing total_ms: %v\n", err)
		return 1
	}

	var phases map[string]float64
	for i := 2; i < len(args); i++ {
		if args[i] == "--phases" && i+1 < len(args) {
			json.Unmarshal([]byte(args[i+1]), &phases)
			i++
		}
	}

	logPath := filepath.Join(a.stateDir, "recall.log")
	f, err := os.OpenFile(logPath, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		fmt.Fprintf(a.stderr, "error opening log file: %v\n", err)
		return 1
	}
	defer f.Close()

	timestamp := time.Now().Format(time.RFC3339)
	logEntry := map[string]interface{}{
		"timestamp": timestamp,
		"event":     "hook_end",
		"level":     "debug",
		"hook":      hook,
		"total_ms":  totalMs,
	}
	if phases != nil {
		logEntry["phases"] = phases
	}

	data, _ := json.Marshal(logEntry)
	f.WriteString(string(data) + "\n")

	return 0
}

// runDebugInjectionBudget logs injection token budget breakdown
func (a *App) runDebugInjectionBudget(args []string) int {
	if len(args) < 3 {
		fmt.Fprintln(a.stderr, "usage: recall debug injection-budget <total> <lessons> <duties>")
		return 1
	}

	total, _ := strconv.Atoi(args[0])
	lessonsTokens, _ := strconv.Atoi(args[1])
	dutiesTokens, _ := strconv.Atoi(args[2])

	logPath := filepath.Join(a.stateDir, "recall.log")
	f, err := os.OpenFile(logPath, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		fmt.Fprintf(a.stderr, "error opening log file: %v\n", err)
		return 1
	}
	defer f.Close()

	timestamp := time.Now().Format(time.RFC3339)
	logEntry := map[string]interface{}{
		"timestamp":      timestamp,
		"event":          "injection_budget",
		"level":          "debug",
		"total_tokens":   total,
		"lessons_tokens": lessonsTokens,
		"duties_tokens":  dutiesTokens,
	}

	data, _ := json.Marshal(logEntry)
	f.WriteString(string(data) + "\n")

	return 0
}

// runScoreRelevance scores lessons by relevance to a query
func (a *App) runScoreRelevance(args []string) int {
	if len(args) < 1 {
		fmt.Fprintln(a.stderr, "usage: recall score-relevance <query> [--top N] [--min-score N] [--timeout N]")
		return 1
	}

	query := args[0]
	topN := 10
	minScore := 0
	timeout := 30 * time.Second

	for i := 1; i < len(args); i++ {
		switch args[i] {
		case "--top":
			if i+1 < len(args) {
				if n, err := strconv.Atoi(args[i+1]); err == nil {
					topN = n
				}
				i++
			}
		case "--min-score":
			if i+1 < len(args) {
				if n, err := strconv.Atoi(args[i+1]); err == nil {
					minScore = n
				}
				i++
			}
		case "--timeout":
			if i+1 < len(args) {
				if n, err := strconv.Atoi(args[i+1]); err == nil {
					timeout = time.Duration(n) * time.Second
				}
				i++
			}
		}
	}

	store := lessons.NewStore(a.projectPath, a.systemPath)
	allLessons, err := store.List()
	if err != nil {
		fmt.Fprintf(a.stderr, "error listing lessons: %v\n", err)
		return 1
	}

	if len(allLessons) == 0 {
		fmt.Fprintln(a.stdout, "No lessons found.")
		return 0
	}

	result, err := anthropic.ScoreRelevance(allLessons, query, a.stateDir, timeout)
	if err != nil {
		dlog := debuglog.New(a.stateDir, a.debugLevel)
		dlog.LogScoreRelevanceError(query, err.Error())
		fmt.Fprintf(a.stderr, "error scoring relevance: %v\n", err)
		return 1
	}

	if result.Error != "" {
		dlog := debuglog.New(a.stateDir, a.debugLevel)
		dlog.LogScoreRelevanceError(query, result.Error)
		fmt.Fprintf(a.stderr, "warning: %s\n", result.Error)
	}

	// Filter and limit results
	count := 0
	for _, sl := range result.ScoredLessons {
		if sl.Score < minScore {
			continue
		}
		if count >= topN {
			break
		}

		// Format stars based on score
		stars := strings.Repeat("⭐", (sl.Score+1)/2)
		if stars == "" {
			stars = "-"
		}

		fmt.Fprintf(a.stdout, "[%s] %s (relevance: %d/10) %s\n", sl.Lesson.ID, stars, sl.Score, sl.Lesson.Title)
		fmt.Fprintf(a.stdout, "    -> %s\n", sl.Lesson.Content)
		count++
	}

	// Log which lessons were injected via relevance scoring
	dlog := debuglog.New(a.stateDir, a.debugLevel)
	var injectedEntries []debuglog.LessonEntry
	for _, sl := range result.ScoredLessons {
		if sl.Score < minScore {
			continue
		}
		if len(injectedEntries) >= topN {
			break
		}
		injectedEntries = append(injectedEntries, debuglog.LessonEntry{
			ID:    sl.Lesson.ID,
			Title: sl.Lesson.Title,
		})
	}
	dlog.LogInjection("prompt_submit", a.projectDir, injectedEntries)

	if count == 0 {
		fmt.Fprintln(a.stdout, "No relevant lessons found.")
	}

	cacheIndicator := ""
	if result.CacheHit {
		cacheIndicator = " (cached)"
	}
	fmt.Fprintf(a.stdout, "\nShowing %d results%s\n", count, cacheIndicator)

	return 0
}

// runScoreLocal scores lessons locally using BM25 (no API key required)
func (a *App) runScoreLocal(args []string) int {
	if len(args) < 1 {
		fmt.Fprintln(a.stderr, "usage: recall score-local <query> [--top N] [--min-score N]")
		return 1
	}

	query := args[0]
	topN := 5
	minScore := 1

	for i := 1; i < len(args); i++ {
		switch args[i] {
		case "--top":
			if i+1 < len(args) {
				if n, err := strconv.Atoi(args[i+1]); err == nil {
					topN = n
				}
				i++
			}
		case "--min-score":
			if i+1 < len(args) {
				if n, err := strconv.Atoi(args[i+1]); err == nil {
					minScore = n
				}
				i++
			}
		}
	}

	store := lessons.NewStore(a.projectPath, a.systemPath)
	allLessons, err := store.List()
	if err != nil {
		fmt.Fprintf(a.stderr, "error listing lessons: %v\n", err)
		return 1
	}

	if len(allLessons) == 0 {
		fmt.Fprintln(a.stdout, "No lessons found.")
		return 0
	}

	scorer := scoring.NewBM25Scorer(allLessons)
	results := scorer.Score(query)

	// Apply feedback penalties to reduce scores of frequently-injected but rarely-cited lessons
	projectStatsPath := feedback.StatsFilePath(filepath.Join(a.projectDir, ".claude-recall"))
	systemStatsPath := feedback.StatsFilePath(a.stateDir)
	projectStats, _ := feedback.ReadStats(projectStatsPath)
	systemStats, _ := feedback.ReadStats(systemStatsPath)

	// Graduated per-lesson trust multiplier: chronically injected-but-uncited lessons
	// are down-ranked toward TrustFloor; fresh lessons (below the injection gate) and
	// well-cited ones stay at 1.0 (no-op). Project L### stats vs system S### stats are
	// kept separate, matching where each lesson's injections are counted.
	penalties := make(map[string]float64)
	for _, r := range results {
		id := r.Lesson.ID
		var stats feedback.LessonStats
		if strings.HasPrefix(id, "L") {
			stats = projectStats[id]
		} else {
			stats = systemStats[id]
		}
		penalties[id] = feedback.TrustMultiplier(stats, a.cfg.TrustAlpha, a.cfg.TrustBeta, a.cfg.TrustFloor, a.cfg.TrustMinInjections)
	}
	if len(penalties) > 0 {
		results = scoring.ApplyPenalties(results, penalties)
	}

	// Filter and limit results, collecting output for injection tracking
	var outputResults []scoring.ScoredLesson
	for _, sl := range results {
		if sl.Score < minScore {
			continue
		}
		if len(outputResults) >= topN {
			break
		}

		// Format stars based on score (same as score-relevance)
		stars := strings.Repeat("\u2b50", (sl.Score+1)/2)
		if stars == "" {
			stars = "-"
		}

		fmt.Fprintf(a.stdout, "[%s] %s (relevance: %d/10) %s\n", sl.Lesson.ID, stars, sl.Score, sl.Lesson.Title)
		fmt.Fprintf(a.stdout, "    -> %s\n", sl.Lesson.Content)
		outputResults = append(outputResults, sl)
	}

	if len(outputResults) == 0 {
		fmt.Fprintln(a.stdout, "No relevant lessons found.")
	}

	fmt.Fprintf(a.stderr, "\nShowing %d results (local BM25)\n", len(outputResults))

	// Track injection counts for feedback loop
	for _, sl := range outputResults {
		id := sl.Lesson.ID
		if strings.HasPrefix(id, "L") {
			feedback.IncrementInjection(projectStatsPath, id)
		} else {
			feedback.IncrementInjection(systemStatsPath, id)
		}
	}

	// Emit injection events to session log
	if a.eventLogEnabled {
		eventLogPath := filepath.Join(a.stateDir, "session-log.jsonl")
		elog := eventlog.New(eventLogPath)
		now := time.Now()
		for _, sl := range outputResults {
			elog.Append(eventlog.Event{
				Timestamp: now,
				Type:      "injection",
				Session:   os.Getenv("CLAUDE_SESSION_ID"),
				Lesson:    sl.Lesson.ID,
				Score:     sl.Score,
				Query:     query,
				Hook:      "prompt_submit",
				Project:   a.projectDir,
			})
		}
	}

	return 0
}

// runPrescoreCache warms the relevance cache
func (a *App) runPrescoreCache(args []string) int {
	var transcriptPath string
	maxQueries := 3

	for i := 0; i < len(args); i++ {
		switch args[i] {
		case "--transcript":
			if i+1 < len(args) {
				transcriptPath = args[i+1]
				i++
			}
		case "--max-queries":
			if i+1 < len(args) {
				if n, err := strconv.Atoi(args[i+1]); err == nil {
					maxQueries = n
				}
				i++
			}
		}
	}

	if transcriptPath == "" {
		fmt.Fprintln(a.stderr, "usage: recall prescore-cache --transcript <path> [--max-queries N]")
		return 1
	}

	// Read transcript and extract user queries
	queries, err := a.readTranscriptQueries(transcriptPath, maxQueries)
	if err != nil {
		fmt.Fprintf(a.stderr, "error reading transcript: %v\n", err)
		return 1
	}

	store := lessons.NewStore(a.projectPath, a.systemPath)
	allLessons, err := store.List()
	if err != nil {
		fmt.Fprintf(a.stderr, "error listing lessons: %v\n", err)
		return 1
	}

	if len(allLessons) == 0 {
		fmt.Fprintln(a.stdout, "No lessons to pre-score.")
		return 0
	}

	prescored := 0
	for _, query := range queries {
		if len(query) < 10 {
			continue
		}

		_, err := anthropic.ScoreRelevance(allLessons, query, a.stateDir, 30*time.Second)
		if err == nil {
			prescored++
			fmt.Fprintf(a.stdout, "Pre-scored: %s\n", truncateContent(query, 50))
		}
	}

	fmt.Fprintf(a.stdout, "Pre-scored %d queries\n", prescored)
	return 0
}

// Helper functions

func truncateContent(content string, maxLen int) string {
	if len(content) <= maxLen {
		return content
	}
	return content[:maxLen-3] + "..."
}

func (a *App) readTranscriptTexts(path string) ([]string, error) {
	// Expand tilde
	if strings.HasPrefix(path, "~/") {
		homeDir, _ := os.UserHomeDir()
		path = filepath.Join(homeDir, path[2:])
	}

	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()

	var texts []string
	decoder := json.NewDecoder(file)

	for {
		var entry map[string]interface{}
		if err := decoder.Decode(&entry); err != nil {
			break
		}

		// Look for assistant messages
		if msg, ok := entry["message"].(map[string]interface{}); ok {
			if role, ok := msg["role"].(string); ok && role == "assistant" {
				if content, ok := msg["content"].([]interface{}); ok {
					for _, block := range content {
						if b, ok := block.(map[string]interface{}); ok {
							if t, ok := b["type"].(string); ok && t == "text" {
								if text, ok := b["text"].(string); ok {
									texts = append(texts, text)
								}
							}
						}
					}
				}
			}
		}
	}

	return texts, nil
}

func (a *App) readTranscriptQueries(path string, maxQueries int) ([]string, error) {
	// Expand tilde
	if strings.HasPrefix(path, "~/") {
		homeDir, _ := os.UserHomeDir()
		path = filepath.Join(homeDir, path[2:])
	}

	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()

	var queries []string
	decoder := json.NewDecoder(file)

	for {
		var entry map[string]interface{}
		if err := decoder.Decode(&entry); err != nil {
			break
		}

		if len(queries) >= maxQueries {
			break
		}

		// Look for user messages
		if msg, ok := entry["message"].(map[string]interface{}); ok {
			if role, ok := msg["role"].(string); ok && role == "user" {
				if content, ok := msg["content"].([]interface{}); ok {
					for _, block := range content {
						if b, ok := block.(map[string]interface{}); ok {
							if t, ok := b["type"].(string); ok && t == "text" {
								if text, ok := b["text"].(string); ok {
									queries = append(queries, text)
								}
							}
						}
					}
				} else if content, ok := msg["content"].(string); ok {
					queries = append(queries, content)
				}
			}
		}
	}

	return queries, nil
}
