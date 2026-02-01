package main

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"time"

	"github.com/pbrown/claude-recall/internal/config"
	"github.com/pbrown/claude-recall/internal/handoffs"
	"github.com/pbrown/claude-recall/internal/lessons"
)

// App encapsulates CLI state and dependencies for testability
type App struct {
	stdout       io.Writer
	stderr       io.Writer
	projectPath  string // Path to project LESSONS.md
	systemPath   string // Path to system LESSONS.md
	handoffsPath string // Path to HANDOFFS.md
	stealthPath  string // Path to HANDOFFS_LOCAL.md (stealth)
	stateDir     string // Path to state directory
}

// NewApp creates a new App with default stdout/stderr
func NewApp() *App {
	return &App{
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

	return nil
}

// Run parses arguments and dispatches to commands
func (a *App) Run(args []string) int {
	if len(args) < 2 {
		fmt.Fprintln(a.stderr, "usage: recall <command> [args...]")
		return 1
	}

	if err := a.initPaths(); err != nil {
		fmt.Fprintf(a.stderr, "error: %v\n", err)
		return 1
	}

	cmd := args[1]
	cmdArgs := args[2:]

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
	default:
		fmt.Fprintf(a.stderr, "unknown command: %s\n", cmd)
		return 1
	}
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
		fmt.Fprintln(a.stderr, "  list      - List active handoffs")
		fmt.Fprintln(a.stderr, "  add       - Add new handoff")
		fmt.Fprintln(a.stderr, "  update    - Update a handoff")
		fmt.Fprintln(a.stderr, "  tried     - Add a tried step")
		fmt.Fprintln(a.stderr, "  complete  - Mark handoff completed")
		fmt.Fprintln(a.stderr, "  archive   - Archive old completed")
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
