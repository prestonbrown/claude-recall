package main

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/pbrown/claude-recall/internal/anthropic"
	"github.com/pbrown/claude-recall/internal/config"
	"github.com/pbrown/claude-recall/internal/debuglog"
	"github.com/pbrown/claude-recall/internal/handoffs"
	"github.com/pbrown/claude-recall/internal/lessons"
	"github.com/pbrown/claude-recall/internal/models"
	"github.com/pbrown/claude-recall/internal/scoring"
)

// App encapsulates CLI state and dependencies for testability
type App struct {
	stdin        io.Reader
	stdout       io.Writer
	stderr       io.Writer
	projectPath  string // Path to project LESSONS.md
	systemPath   string // Path to system LESSONS.md
	handoffsPath string // Path to HANDOFFS.md
	stealthPath  string // Path to HANDOFFS_LOCAL.md (stealth)
	stateDir     string // Path to state directory
	projectDir   string // Project root directory
	debugLevel   int    // Debug level 0-3
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
	if a.projectPath != "" && a.systemPath != "" && a.handoffsPath != "" && a.stealthPath != "" {
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
	if a.handoffsPath == "" {
		a.handoffsPath = filepath.Join(cfg.ProjectDir, ".claude-recall", "HANDOFFS.md")
	}
	if a.stealthPath == "" {
		a.stealthPath = filepath.Join(cfg.ProjectDir, ".claude-recall", "HANDOFFS_LOCAL.md")
	}
	if a.stateDir == "" {
		a.stateDir = cfg.StateDir
	}
	a.projectDir = cfg.ProjectDir
	a.debugLevel = cfg.DebugLevel

	return nil
}

// Run parses arguments and dispatches to commands
func (a *App) Run(args []string) int {
	if len(args) < 2 {
		a.printHelp()
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
	case "decay":
		return a.runDecay(cmdArgs)
	case "handoff":
		return a.runHandoff(cmdArgs)
	case "debug":
		return a.runDebug(cmdArgs)
	case "score-relevance":
		return a.runScoreRelevance(cmdArgs)
	case "score-local":
		return a.runScoreLocal(cmdArgs)
	case "extract-context":
		return a.runExtractContext(cmdArgs)
	case "prescore-cache":
		return a.runPrescoreCache(cmdArgs)
	case "opencode":
		return a.runOpencode(cmdArgs)
	default:
		fmt.Fprintf(a.stderr, "unknown command: %s\n", cmd)
		a.printHelp()
		return 1
	}
}

// printHelp prints the help message
func (a *App) printHelp() {
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

  handoff list                     List active handoffs
  handoff add <title> [opts]       Add new handoff (--desc D, --stealth)
  handoff update <id> [opts]       Update handoff (--status, --phase, --next)
  handoff tried <id> <out> <desc>  Log attempt (outcome: success/fail/partial)
  handoff complete <id>            Mark handoff completed
  handoff archive                  Archive old completed handoffs
  handoff inject                   Output handoffs for context injection
  handoff inject-todos             Format todos for continuation prompt
  handoff sync-todos <json>        Sync TodoWrite output to handoff
  handoff set-context <id> --json  Set structured context from precompact
  handoff set-session <hf> <sess>  Link session to handoff
  handoff get-session-handoff <s>  Lookup handoff for session
  handoff process-transcript       Parse transcript for handoff patterns

  debug log <message>              Log a debug message
  debug log-error <key> <msg>      Log an error event
  debug hook-phase <h> <p> <ms>    Log hook phase timing
  debug hook-end <h> <ms> [--phases json]  Log hook completion
  debug injection-budget <t> <l> <h> <d>   Log token budget breakdown

  score-relevance <query> [opts]   Score lessons by relevance (Haiku API)
  score-local <query> [opts]       Score lessons locally using BM25 (no API key)
  extract-context <path> [opts]    Extract handoff context from transcript
  prescore-cache --transcript <p>  Pre-warm relevance cache

Options:
  help, --help, -h                 Show this help message
`
	fmt.Fprint(a.stdout, help)
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

	fmt.Fprintf(a.stdout, "Deleted lesson %s\n", id)
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

// runHandoff dispatches to handoff subcommands
func (a *App) runHandoff(args []string) int {
	if len(args) < 1 {
		fmt.Fprintln(a.stderr, "usage: recall handoff <subcommand> [args...]")
		fmt.Fprintln(a.stderr, "  list              - List active handoffs")
		fmt.Fprintln(a.stderr, "  add               - Add new handoff")
		fmt.Fprintln(a.stderr, "  update            - Update a handoff")
		fmt.Fprintln(a.stderr, "  tried             - Add a tried step")
		fmt.Fprintln(a.stderr, "  complete          - Mark handoff completed")
		fmt.Fprintln(a.stderr, "  archive           - Archive old completed")
		fmt.Fprintln(a.stderr, "  inject            - Output handoffs for context injection")
		fmt.Fprintln(a.stderr, "  inject-todos      - Format todos for continuation prompt")
		fmt.Fprintln(a.stderr, "  sync-todos        - Sync TodoWrite output to handoff")
		fmt.Fprintln(a.stderr, "  set-context       - Set structured context")
		fmt.Fprintln(a.stderr, "  set-session       - Link session to handoff")
		fmt.Fprintln(a.stderr, "  get-session-handoff - Lookup handoff for session")
		fmt.Fprintln(a.stderr, "  process-transcript  - Parse transcript for handoff patterns")
		return 1
	}

	subcmd := args[0]
	subArgs := args[1:]

	switch subcmd {
	case "list":
		return a.runHandoffList(subArgs)
	case "add":
		return a.runHandoffAdd(subArgs)
	case "update":
		return a.runHandoffUpdate(subArgs)
	case "tried":
		return a.runHandoffTried(subArgs)
	case "complete":
		return a.runHandoffComplete(subArgs)
	case "archive":
		return a.runHandoffArchive(subArgs)
	case "inject":
		return a.runHandoffInject(subArgs)
	case "inject-todos":
		return a.runHandoffInjectTodos(subArgs)
	case "sync-todos":
		return a.runHandoffSyncTodos(subArgs)
	case "set-context":
		return a.runHandoffSetContext(subArgs)
	case "set-session":
		return a.runHandoffSetSession(subArgs)
	case "get-session-handoff":
		return a.runHandoffGetSessionHandoff(subArgs)
	case "process-transcript":
		return a.runHandoffProcessTranscript(subArgs)
	default:
		fmt.Fprintf(a.stderr, "unknown handoff subcommand: %s\n", subcmd)
		return 1
	}
}

// runHandoffList lists active handoffs
func (a *App) runHandoffList(args []string) int {
	store := handoffs.NewStore(a.handoffsPath, a.stealthPath)

	handoffList, err := store.List()
	if err != nil {
		fmt.Fprintf(a.stderr, "error listing handoffs: %v\n", err)
		return 1
	}

	if len(handoffList) == 0 {
		fmt.Fprintln(a.stdout, "No active handoffs.")
		return 0
	}

	for _, h := range handoffList {
		stealthFlag := ""
		if h.Stealth {
			stealthFlag = " [stealth]"
		}
		fmt.Fprintf(a.stdout, "%s [%s] %s%s\n", h.ID, h.Status, h.Title, stealthFlag)
		if h.Description != "" {
			fmt.Fprintf(a.stdout, "  %s\n", h.Description)
		}
	}

	return 0
}

// runHandoffAdd adds a new handoff
func (a *App) runHandoffAdd(args []string) int {
	if len(args) < 1 {
		fmt.Fprintln(a.stderr, "usage: recall handoff add <title> [--desc D] [--stealth]")
		return 1
	}

	title := args[0]
	description := ""
	stealth := false

	for i := 1; i < len(args); i++ {
		switch args[i] {
		case "--desc":
			if i+1 < len(args) {
				description = args[i+1]
				i++
			}
		case "--stealth":
			stealth = true
		}
	}

	store := handoffs.NewStore(a.handoffsPath, a.stealthPath)
	handoff, err := store.Add(title, description, stealth)
	if err != nil {
		fmt.Fprintf(a.stderr, "error adding handoff: %v\n", err)
		return 1
	}

	fmt.Fprintf(a.stdout, "Added handoff %s: %s\n", handoff.ID, title)
	return 0
}

// runHandoffUpdate updates a handoff
func (a *App) runHandoffUpdate(args []string) int {
	if len(args) < 1 {
		fmt.Fprintln(a.stderr, "usage: recall handoff update <id> [--status S] [--phase P] [--desc D] [--next N]")
		return 1
	}

	id := args[0]
	updates := make(map[string]interface{})

	for i := 1; i < len(args); i++ {
		switch args[i] {
		case "--status":
			if i+1 < len(args) {
				updates["status"] = args[i+1]
				i++
			}
		case "--phase":
			if i+1 < len(args) {
				updates["phase"] = args[i+1]
				i++
			}
		case "--desc":
			if i+1 < len(args) {
				updates["description"] = args[i+1]
				i++
			}
		case "--next":
			if i+1 < len(args) {
				updates["next_steps"] = args[i+1]
				i++
			}
		}
	}

	if len(updates) == 0 {
		fmt.Fprintln(a.stderr, "no updates specified")
		return 1
	}

	store := handoffs.NewStore(a.handoffsPath, a.stealthPath)
	if err := store.Update(id, updates); err != nil {
		fmt.Fprintf(a.stderr, "error updating handoff: %v\n", err)
		return 1
	}

	fmt.Fprintf(a.stdout, "Updated handoff %s\n", id)
	return 0
}

// runHandoffTried adds a tried step to a handoff
func (a *App) runHandoffTried(args []string) int {
	if len(args) < 3 {
		fmt.Fprintln(a.stderr, "usage: recall handoff tried <id> <outcome> <description>")
		fmt.Fprintln(a.stderr, "  outcome: success, fail, partial")
		return 1
	}

	id := args[0]
	outcome := args[1]
	description := args[2]

	store := handoffs.NewStore(a.handoffsPath, a.stealthPath)
	if err := store.AddTriedStep(id, outcome, description); err != nil {
		fmt.Fprintf(a.stderr, "error adding tried step: %v\n", err)
		return 1
	}

	fmt.Fprintf(a.stdout, "Added tried step [%s] to handoff %s\n", outcome, id)
	return 0
}

// runHandoffComplete marks a handoff as completed
func (a *App) runHandoffComplete(args []string) int {
	if len(args) < 1 {
		fmt.Fprintln(a.stderr, "usage: recall handoff complete <id>")
		return 1
	}

	id := args[0]
	store := handoffs.NewStore(a.handoffsPath, a.stealthPath)

	if err := store.Complete(id); err != nil {
		fmt.Fprintf(a.stderr, "error completing handoff: %v\n", err)
		return 1
	}

	fmt.Fprintf(a.stdout, "Completed handoff %s\n", id)
	return 0
}

// runHandoffArchive archives old completed handoffs
func (a *App) runHandoffArchive(args []string) int {
	store := handoffs.NewStore(a.handoffsPath, a.stealthPath)

	count, err := store.Archive()
	if err != nil {
		fmt.Fprintf(a.stderr, "error archiving: %v\n", err)
		return 1
	}

	if count > 0 {
		fmt.Fprintf(a.stdout, "Archived %d handoffs\n", count)
	} else {
		fmt.Fprintln(a.stdout, "No handoffs to archive")
	}

	return 0
}

// runHandoffInject outputs handoffs for context injection
func (a *App) runHandoffInject(args []string) int {
	store := handoffs.NewStore(a.handoffsPath, a.stealthPath)

	handoffList, err := store.List()
	if err != nil {
		fmt.Fprintf(a.stderr, "error listing handoffs: %v\n", err)
		return 1
	}

	if len(handoffList) == 0 {
		fmt.Fprintln(a.stdout, "(no active handoffs)")
		return 0
	}

	fmt.Fprintln(a.stdout, "## Active Handoffs")
	fmt.Fprintln(a.stdout)

	for _, h := range handoffList {
		fmt.Fprintf(a.stdout, "### [%s] %s\n", h.ID, h.Title)
		fmt.Fprintf(a.stdout, "- **Status**: %s | **Phase**: %s\n", h.Status, h.Phase)

		if h.Description != "" {
			fmt.Fprintf(a.stdout, "- **Description**: %s\n", h.Description)
		}

		if h.Checkpoint != "" {
			fmt.Fprintf(a.stdout, "- **Checkpoint**: %s\n", h.Checkpoint)
		}

		if len(h.Tried) > 0 {
			fmt.Fprintln(a.stdout, "\n**Tried**:")
			for i, t := range h.Tried {
				fmt.Fprintf(a.stdout, "%d. [%s] %s\n", i+1, t.Outcome, t.Description)
			}
		}

		if h.NextSteps != "" {
			fmt.Fprintf(a.stdout, "\n**Next**: %s\n", h.NextSteps)
		}

		fmt.Fprintln(a.stdout)
	}

	return 0
}

// runHandoffInjectTodos formats active handoff as TodoWrite continuation prompt
func (a *App) runHandoffInjectTodos(args []string) int {
	store := handoffs.NewStore(a.handoffsPath, a.stealthPath)

	handoffList, err := store.List()
	if err != nil {
		fmt.Fprintf(a.stderr, "error listing handoffs: %v\n", err)
		return 1
	}

	// Find the most recent in_progress handoff
	var activeHandoff *models.Handoff
	for _, h := range handoffList {
		if h.Status == "in_progress" {
			activeHandoff = h
			break
		}
	}

	if activeHandoff == nil {
		// No output if no active handoff
		return 0
	}

	fmt.Fprintln(a.stdout, "## Todo Continuation")
	fmt.Fprintln(a.stdout)
	fmt.Fprintf(a.stdout, "Continue work on: **%s** [%s]\n\n", activeHandoff.Title, activeHandoff.ID)

	if activeHandoff.NextSteps != "" {
		fmt.Fprintf(a.stdout, "Next steps: %s\n\n", activeHandoff.NextSteps)
	}

	if len(activeHandoff.Tried) > 0 {
		fmt.Fprintln(a.stdout, "Previous attempts:")
		// Show last 3 tried steps
		start := len(activeHandoff.Tried) - 3
		if start < 0 {
			start = 0
		}
		for i := start; i < len(activeHandoff.Tried); i++ {
			t := activeHandoff.Tried[i]
			fmt.Fprintf(a.stdout, "- [%s] %s\n", t.Outcome, t.Description)
		}
	}

	return 0
}

// runHandoffSyncTodos syncs TodoWrite todos to handoff
func (a *App) runHandoffSyncTodos(args []string) int {
	if len(args) < 1 {
		fmt.Fprintln(a.stderr, "usage: recall handoff sync-todos <json> [--session-handoff ID] [--session-id ID]")
		return 1
	}

	todosJSON := args[0]
	var sessionHandoff, sessionID string

	for i := 1; i < len(args); i++ {
		switch args[i] {
		case "--session-handoff":
			if i+1 < len(args) {
				sessionHandoff = args[i+1]
				i++
			}
		case "--session-id":
			if i+1 < len(args) {
				sessionID = args[i+1]
				i++
			}
		}
	}

	// Parse todos JSON
	var todos []map[string]interface{}
	if err := json.Unmarshal([]byte(todosJSON), &todos); err != nil {
		fmt.Fprintf(a.stderr, "error parsing todos JSON: %v\n", err)
		return 1
	}

	store := handoffs.NewStore(a.handoffsPath, a.stealthPath)

	// Determine which handoff to sync to
	var handoffID string
	if sessionHandoff != "" {
		handoffID = sessionHandoff
	} else if sessionID != "" {
		// Look up handoff from session mapping
		id, err := a.getSessionHandoff(sessionID)
		if err == nil && id != "" {
			handoffID = id
		}
	}

	if handoffID == "" {
		// Fall back to most recent in_progress handoff
		handoffList, err := store.List()
		if err == nil && len(handoffList) > 0 {
			for _, h := range handoffList {
				if h.Status == "in_progress" {
					handoffID = h.ID
					break
				}
			}
		}
	}

	if handoffID == "" {
		// No handoff to sync to
		return 0
	}

	// Build next steps from todos
	var nextSteps []string
	for _, todo := range todos {
		if subject, ok := todo["subject"].(string); ok {
			status := ""
			if s, ok := todo["status"].(string); ok {
				status = s
			}
			if status != "completed" {
				nextSteps = append(nextSteps, subject)
			}
		}
	}

	if len(nextSteps) > 0 {
		// Update handoff's next_steps
		updates := map[string]interface{}{
			"next_steps": strings.Join(nextSteps, "; "),
		}
		if err := store.Update(handoffID, updates); err != nil {
			fmt.Fprintf(a.stderr, "error updating handoff: %v\n", err)
			return 1
		}
		fmt.Fprintf(a.stdout, "Synced %d todo(s) to handoff %s\n", len(nextSteps), handoffID)
	}

	return 0
}

// runHandoffSetContext sets structured handoff context
func (a *App) runHandoffSetContext(args []string) int {
	if len(args) < 1 {
		fmt.Fprintln(a.stderr, "usage: recall handoff set-context <id> --json <context_json>")
		return 1
	}

	id := args[0]
	var contextJSON string

	for i := 1; i < len(args); i++ {
		if args[i] == "--json" && i+1 < len(args) {
			contextJSON = args[i+1]
			i++
		}
	}

	if contextJSON == "" {
		fmt.Fprintln(a.stderr, "error: --json is required")
		return 1
	}

	// Parse context JSON
	var context models.HandoffContext
	if err := json.Unmarshal([]byte(contextJSON), &context); err != nil {
		fmt.Fprintf(a.stderr, "error parsing context JSON: %v\n", err)
		return 1
	}

	store := handoffs.NewStore(a.handoffsPath, a.stealthPath)

	// Get handoff and update context
	h, err := store.Get(id)
	if err != nil {
		fmt.Fprintf(a.stderr, "error getting handoff: %v\n", err)
		return 1
	}

	h.Handoff = &context
	updates := map[string]interface{}{
		"context": &context,
	}

	if err := store.Update(id, updates); err != nil {
		fmt.Fprintf(a.stderr, "error updating handoff: %v\n", err)
		return 1
	}

	fmt.Fprintf(a.stdout, "Set context for %s (git ref: %s)\n", id, context.GitRef)
	return 0
}

// runHandoffSetSession stores session -> handoff mapping
func (a *App) runHandoffSetSession(args []string) int {
	if len(args) < 2 {
		fmt.Fprintln(a.stderr, "usage: recall handoff set-session <handoff_id> <session_id> [--transcript path]")
		return 1
	}

	handoffID := args[0]
	sessionID := args[1]
	var transcriptPath string

	for i := 2; i < len(args); i++ {
		if args[i] == "--transcript" && i+1 < len(args) {
			transcriptPath = args[i+1]
			i++
		}
	}

	// Store in session-handoffs.json
	if err := a.setSessionHandoff(sessionID, handoffID, transcriptPath); err != nil {
		fmt.Fprintf(a.stderr, "error setting session mapping: %v\n", err)
		return 1
	}

	// Update handoff's sessions list
	store := handoffs.NewStore(a.handoffsPath, a.stealthPath)
	h, err := store.Get(handoffID)
	if err == nil {
		// Add session to list if not already present
		found := false
		for _, s := range h.Sessions {
			if s == sessionID {
				found = true
				break
			}
		}
		if !found {
			h.Sessions = append(h.Sessions, sessionID)
			updates := map[string]interface{}{
				"sessions": h.Sessions,
			}
			store.Update(handoffID, updates)
		}
	}

	fmt.Fprintf(a.stdout, "Linked session %s to handoff %s\n", sessionID, handoffID)
	return 0
}

// runHandoffGetSessionHandoff looks up handoff for session
func (a *App) runHandoffGetSessionHandoff(args []string) int {
	if len(args) < 1 {
		fmt.Fprintln(a.stderr, "usage: recall handoff get-session-handoff <session_id>")
		return 1
	}

	sessionID := args[0]

	handoffID, err := a.getSessionHandoff(sessionID)
	if err != nil {
		// Not found - silent failure (exit 0, no output)
		return 0
	}

	if handoffID != "" {
		fmt.Fprintln(a.stdout, handoffID)
	}

	return 0
}

// runHandoffProcessTranscript parses transcript for handoff patterns
func (a *App) runHandoffProcessTranscript(args []string) int {
	var sessionID string

	for i := 0; i < len(args); i++ {
		if args[i] == "--session-id" && i+1 < len(args) {
			sessionID = args[i+1]
			i++
		}
	}

	// Read transcript JSON from stdin
	var transcriptData struct {
		AssistantTexts []string `json:"assistant_texts"`
	}

	decoder := json.NewDecoder(os.Stdin)
	if err := decoder.Decode(&transcriptData); err != nil {
		fmt.Fprintf(a.stderr, "error parsing transcript JSON: %v\n", err)
		return 1
	}

	store := handoffs.NewStore(a.handoffsPath, a.stealthPath)

	// Parse handoff operations from assistant texts
	var results []string

	for _, text := range transcriptData.AssistantTexts {
		// HANDOFF: title
		if matches := handoffStartPattern.FindAllStringSubmatch(text, -1); len(matches) > 0 {
			for _, match := range matches {
				if len(match) > 1 {
					title := strings.TrimSpace(match[1])
					h, err := store.Add(title, "", false)
					if err == nil {
						results = append(results, fmt.Sprintf("added %s", h.ID))
						// Link to session if provided
						if sessionID != "" {
							a.setSessionHandoff(sessionID, h.ID, "")
						}
					}
				}
			}
		}

		// HANDOFF UPDATE <id>: tried <outcome> - <desc>
		if matches := handoffUpdatePattern.FindAllStringSubmatch(text, -1); len(matches) > 0 {
			for _, match := range matches {
				if len(match) > 1 {
					id := match[1]
					isTried := strings.TrimSpace(match[2]) != ""
					outcome := strings.TrimSpace(match[3])
					desc := strings.TrimSpace(match[4])

					if isTried && outcome != "" {
						if err := store.AddTriedStep(id, outcome, desc); err == nil {
							results = append(results, fmt.Sprintf("tried %s (%s)", id, outcome))
						}
					} else if desc != "" {
						updates := map[string]interface{}{
							"description": desc,
						}
						if outcome != "" {
							updates["status"] = outcome
						}
						if err := store.Update(id, updates); err == nil {
							results = append(results, fmt.Sprintf("updated %s", id))
						}
					}
				}
			}
		}

		// HANDOFF COMPLETE <id>
		if matches := handoffCompletePattern.FindAllStringSubmatch(text, -1); len(matches) > 0 {
			for _, match := range matches {
				if len(match) > 1 {
					id := match[1]
					if err := store.Complete(id); err == nil {
						results = append(results, fmt.Sprintf("completed %s", id))
					}
				}
			}
		}
	}

	// Output JSON result
	output := map[string]interface{}{
		"results": results,
		"last_id": nil,
	}
	if len(results) > 0 {
		// Extract last ID from results
		parts := strings.Fields(results[len(results)-1])
		if len(parts) > 1 {
			output["last_id"] = parts[1]
		}
	}

	jsonOutput, _ := json.Marshal(output)
	fmt.Fprintln(a.stdout, string(jsonOutput))

	return 0
}

// Session-handoff mapping helpers

type sessionHandoffMapping struct {
	HandoffID      string `json:"handoff_id"`
	TranscriptPath string `json:"transcript_path,omitempty"`
}

func (a *App) getSessionHandoffsPath() string {
	return filepath.Join(a.stateDir, "session-handoffs.json")
}

func (a *App) loadSessionHandoffs() (map[string]sessionHandoffMapping, error) {
	path := a.getSessionHandoffsPath()
	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return make(map[string]sessionHandoffMapping), nil
		}
		return nil, err
	}

	var mappings map[string]sessionHandoffMapping
	if err := json.Unmarshal(data, &mappings); err != nil {
		return nil, err
	}

	return mappings, nil
}

func (a *App) saveSessionHandoffs(mappings map[string]sessionHandoffMapping) error {
	path := a.getSessionHandoffsPath()

	// Ensure directory exists
	if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		return err
	}

	data, err := json.MarshalIndent(mappings, "", "  ")
	if err != nil {
		return err
	}

	return os.WriteFile(path, data, 0644)
}

func (a *App) setSessionHandoff(sessionID, handoffID, transcriptPath string) error {
	mappings, err := a.loadSessionHandoffs()
	if err != nil {
		return err
	}

	mappings[sessionID] = sessionHandoffMapping{
		HandoffID:      handoffID,
		TranscriptPath: transcriptPath,
	}

	return a.saveSessionHandoffs(mappings)
}

func (a *App) getSessionHandoff(sessionID string) (string, error) {
	mappings, err := a.loadSessionHandoffs()
	if err != nil {
		return "", err
	}

	if mapping, ok := mappings[sessionID]; ok {
		return mapping.HandoffID, nil
	}

	return "", nil
}

// Handoff patterns for transcript parsing
var (
	handoffStartPattern    = regexp.MustCompile(`(?m)^HANDOFF:\s*(.+)$`)
	handoffUpdatePattern   = regexp.MustCompile(`(?m)^HANDOFF\s+UPDATE\s+([A-Za-z0-9-]+):\s*(tried\s+)?(success|fail|partial)?\s*[-–]?\s*(.*)$`)
	handoffCompletePattern = regexp.MustCompile(`(?m)^HANDOFF\s+COMPLETE\s+([A-Za-z0-9-]+)`)
)

// runDebug dispatches to debug subcommands
func (a *App) runDebug(args []string) int {
	if len(args) < 1 {
		fmt.Fprintln(a.stderr, "usage: recall debug <subcommand> [args...]")
		fmt.Fprintln(a.stderr, "  log <message>              - Log a debug message")
		fmt.Fprintln(a.stderr, "  log-error <key> <message>  - Log an error event")
		fmt.Fprintln(a.stderr, "  hook-phase <h> <p> <ms>    - Log hook phase timing")
		fmt.Fprintln(a.stderr, "  hook-end <h> <ms> [--phases json] - Log hook end")
		fmt.Fprintln(a.stderr, "  injection-budget <t> <l> <h> <d>  - Log token budget")
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
	if len(args) < 4 {
		fmt.Fprintln(a.stderr, "usage: recall debug injection-budget <total> <lessons> <handoffs> <duties>")
		return 1
	}

	total, _ := strconv.Atoi(args[0])
	lessonsTokens, _ := strconv.Atoi(args[1])
	handoffsTokens, _ := strconv.Atoi(args[2])
	dutiesTokens, _ := strconv.Atoi(args[3])

	logPath := filepath.Join(a.stateDir, "recall.log")
	f, err := os.OpenFile(logPath, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		fmt.Fprintf(a.stderr, "error opening log file: %v\n", err)
		return 1
	}
	defer f.Close()

	timestamp := time.Now().Format(time.RFC3339)
	logEntry := map[string]interface{}{
		"timestamp":       timestamp,
		"event":           "injection_budget",
		"level":           "debug",
		"total_tokens":    total,
		"lessons_tokens":  lessonsTokens,
		"handoffs_tokens": handoffsTokens,
		"duties_tokens":   dutiesTokens,
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

	// Filter and limit results
	count := 0
	for _, sl := range results {
		if sl.Score < minScore {
			continue
		}
		if count >= topN {
			break
		}

		// Format stars based on score (same as score-relevance)
		stars := strings.Repeat("\u2b50", (sl.Score+1)/2)
		if stars == "" {
			stars = "-"
		}

		fmt.Fprintf(a.stdout, "[%s] %s (relevance: %d/10) %s\n", sl.Lesson.ID, stars, sl.Score, sl.Lesson.Title)
		fmt.Fprintf(a.stdout, "    -> %s\n", sl.Lesson.Content)
		count++
	}

	if count == 0 {
		fmt.Fprintln(a.stdout, "No relevant lessons found.")
	}

	fmt.Fprintf(a.stderr, "\nShowing %d results (local BM25)\n", count)

	return 0
}

// runExtractContext extracts handoff context from a transcript
func (a *App) runExtractContext(args []string) int {
	if len(args) < 1 {
		fmt.Fprintln(a.stderr, "usage: recall extract-context <transcript_path> [--git-ref REF]")
		return 1
	}

	transcriptPath := args[0]
	var gitRef string

	for i := 1; i < len(args); i++ {
		if args[i] == "--git-ref" && i+1 < len(args) {
			gitRef = args[i+1]
			i++
		}
	}

	// Read transcript and extract assistant texts
	assistantTexts, err := a.readTranscriptTexts(transcriptPath)
	if err != nil {
		fmt.Fprintf(a.stderr, "error reading transcript: %v\n", err)
		return 1
	}

	if len(assistantTexts) == 0 {
		fmt.Fprintln(a.stdout, "{}")
		return 0
	}

	context, err := anthropic.ExtractContext(assistantTexts, gitRef, 30*time.Second)
	if err != nil {
		fmt.Fprintf(a.stderr, "error extracting context: %v\n", err)
		fmt.Fprintln(a.stdout, "{}")
		return 0
	}

	// Output as JSON
	result := map[string]interface{}{
		"summary":        context.Summary,
		"critical_files": context.CriticalFiles,
		"recent_changes": context.RecentChanges,
		"learnings":      context.Learnings,
		"blockers":       context.Blockers,
		"git_ref":        context.GitRef,
	}

	output, _ := json.Marshal(result)
	fmt.Fprintln(a.stdout, string(output))

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
