package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/pbrown/claude-recall/internal/lessons"
	"github.com/pbrown/claude-recall/internal/validate"
)

// Defaults aim to be useful in a fresh project without configuration. Flag
// checking and vocabulary rules stay off unless declared, because guessing at
// them produces exactly the noise that gets a check switched off.
var defaultSourceRoots = []string{
	"src/", "include/", "lib/", "tests/", "test/", "scripts/",
	"core/", "internal/", "cmd/", "pkg/", "app/",
}

// validateConfigFile is the optional per-project config.
type validateConfigFile struct {
	SourceRoots      []string `json:"source_roots"`
	FlagSources      []string `json:"flag_sources"`
	FlagCommands     []string `json:"flag_commands"`
	ExternalPrefixes []string `json:"external_prefixes"`
	Vocab            []struct {
		Pattern string `json:"pattern"`
		Message string `json:"message"`
	} `json:"vocab"`
}

func (a *App) loadValidateConfig(root string) validate.Config {
	cfg := validate.Config{ProjectRoot: root, SourceRoots: defaultSourceRoots}

	path := filepath.Join(root, ".claude-recall", "validate.json")
	data, err := os.ReadFile(path)
	if err != nil {
		return cfg
	}
	var f validateConfigFile
	if err := json.Unmarshal(data, &f); err != nil {
		fmt.Fprintf(a.stderr, "warning: ignoring malformed %s: %v\n", path, err)
		return cfg
	}
	if len(f.SourceRoots) > 0 {
		cfg.SourceRoots = f.SourceRoots
	}
	cfg.FlagSources = f.FlagSources
	cfg.FlagCommands = f.FlagCommands
	cfg.ExternalPrefixes = f.ExternalPrefixes
	for _, v := range f.Vocab {
		cfg.Vocab = append(cfg.Vocab, validate.VocabRule{Pattern: v.Pattern, Message: v.Message})
	}
	return cfg
}

// runValidate checks lessons against the project they describe.
//
// Advisory by default. On a real lesson set roughly eleven of fourteen flags
// were false positives - mostly corrected lessons deliberately naming things
// that no longer exist - so failing the build here would flag precisely the
// lessons someone had just fixed, and the check would be switched off within a
// week. --strict is available for anyone who wants it in CI.
func (a *App) runValidate(args []string) int {
	strict := false
	var dismiss []string
	for i := 0; i < len(args); i++ {
		switch args[i] {
		case "--strict":
			strict = true
		case "--dismiss":
			if i+2 >= len(args) {
				fmt.Fprintln(a.stderr, "usage: recall validate --dismiss <lesson-id> <token>")
				return 1
			}
			dismiss = []string{args[i+1], args[i+2]}
			i += 2
		}
	}

	root := projectRootFrom(a.projectPath)
	if root == "" {
		fmt.Fprintln(a.stderr, "error: could not determine the project root")
		return 1
	}

	store := lessons.NewStore(a.projectPath, a.systemPath)
	all, err := store.List()
	if err != nil {
		fmt.Fprintf(a.stderr, "error loading lessons: %v\n", err)
		return 1
	}

	ledgerPath := validate.LedgerPath(root)
	ledger := validate.LoadLedger(ledgerPath)

	if len(dismiss) == 2 {
		target, err := store.Get(dismiss[0])
		if err != nil {
			fmt.Fprintf(a.stderr, "error: %v\n", err)
			return 1
		}
		ledger.Dismiss(target, dismiss[1])
		if err := ledger.Save(ledgerPath); err != nil {
			fmt.Fprintf(a.stderr, "error saving ledger: %v\n", err)
			return 1
		}
		fmt.Fprintf(a.stdout, "Dismissed %q for %s. It returns if the lesson is edited.\n",
			dismiss[1], dismiss[0])
		return 0
	}

	cfg := a.loadValidateConfig(root)
	findings := validate.Run(all, cfg, ledger)
	dangling := validate.DanglingCitations(root, all)

	if len(findings) == 0 && len(dangling) == 0 {
		fmt.Fprintf(a.stdout, "✅ %d lessons check out against %s\n", len(all), root)
		return 0
	}

	if len(findings) > 0 {
		fmt.Fprintf(a.stdout, "Unresolved references (%d), highest-traffic first:\n\n", len(findings))
		for _, f := range findings {
			fmt.Fprintf(a.stdout, "  [%s] uses=%-3d %-6s %s\n", f.LessonID, f.Uses, f.Kind, f.Token)
			fmt.Fprintf(a.stdout, "         %s\n", f.Reason)
		}
		fmt.Fprintln(a.stdout, "\n  Fix the lesson, or record a review:")
		fmt.Fprintln(a.stdout, "    recall validate --dismiss <lesson-id> <token>")
		fmt.Fprintln(a.stdout, "  A dismissal lasts until the lesson body changes.")
	}

	if len(dangling) > 0 {
		fmt.Fprintf(a.stdout, "\nCited but missing (%d) - these IDs appear in the tree with no lesson:\n\n", len(dangling))
		for _, d := range dangling {
			shown := d.Files
			if len(shown) > 3 {
				shown = shown[:3]
			}
			fmt.Fprintf(a.stdout, "  %s  %s", d.ID, strings.Join(shown, ", "))
			if len(d.Files) > 3 {
				fmt.Fprintf(a.stdout, " (+%d more)", len(d.Files)-3)
			}
			fmt.Fprintln(a.stdout)
		}
		fmt.Fprintln(a.stdout, "\n  Repoint them, or `recall supersede <old> <new>` if the content moved.")
	}

	if strict {
		return 1
	}
	return 0
}

// projectRootFrom derives the repo root from <root>/.claude-recall/LESSONS.md.
func projectRootFrom(lessonsPath string) string {
	if lessonsPath == "" {
		return ""
	}
	dir := filepath.Dir(lessonsPath)
	if strings.EqualFold(filepath.Base(dir), ".claude-recall") {
		return filepath.Dir(dir)
	}
	return dir
}
