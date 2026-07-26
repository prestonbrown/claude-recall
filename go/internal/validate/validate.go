// Package validate checks lesson bodies against the project they describe.
//
// Lessons drift: they name a symbol that gets renamed, a flag that gets removed,
// a term the codebase later forbids. Nothing re-reads them, and because stars and
// velocity measure how often a lesson is used rather than whether it is still
// true, the most-cited lessons drift furthest. A 2026-07-26 audit of one project
// found the two worst offenders were its two most-cited lessons.
//
// Three things shape this package, all measured rather than assumed:
//
//  1. Resolving backticked references - the obvious approach, and the one an
//     existing doc linter uses - catches none of the three real failures. One was
//     prose with no backticks, one hid inside a multi-token command span, and one
//     "resolved" because a comment explaining that the symbol does not exist
//     contained the symbol. Hence: vocabulary rules, tokenizing inside code
//     spans, and an oracle that ignores comments.
//
//  2. Presence anywhere is a broken oracle. A phantom taught by a lesson
//     propagates into plans and docs, which then vouch for it. Only real build
//     inputs count as evidence.
//
//  3. Roughly eleven of fourteen flags on a real lesson set were false positives,
//     dominated by corrected lessons deliberately naming absent things ("NOT
//     `component_register`", "the `-p` flag is GONE"). A gate would flag exactly
//     the lessons that were just fixed, so this is advisory and dismissals are
//     remembered.
package validate

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"time"

	"github.com/pbrown/claude-recall/internal/models"
)

// Kind classifies what sort of reference a finding is about.
type Kind string

const (
	KindIdent Kind = "ident"
	KindPath  Kind = "path"
	KindFlag  Kind = "flag"
	KindVocab Kind = "vocab"
)

// Finding is one unresolved reference in one lesson.
type Finding struct {
	LessonID string
	Kind     Kind
	Token    string
	Reason   string
	Uses     int
	LastUsed time.Time
}

// VocabRule forbids a term in lesson bodies. These mirror gates the project
// already enforces on its own source, so lessons are held to the same standard
// as the code they describe.
type VocabRule struct {
	Pattern string
	Message string

	re *regexp.Regexp
}

// Config describes how to check lessons against one project.
type Config struct {
	ProjectRoot string
	// SourceRoots are the only places an identifier may count as existing.
	// Docs and plans are excluded deliberately - see the package comment.
	SourceRoots []string
	// FlagSources declare where CLI flags are registered. Empty disables flag
	// checking rather than guessing, so it is opt-in instead of noisy.
	FlagSources []string
	// FlagCommands name the binaries those flags belong to. Lessons quote other
	// tools' command lines constantly; without this, `git log -S` reports -S as
	// a missing flag of this project.
	FlagCommands []string
	// ExternalPrefixes mark symbols owned by dependencies (e.g. "lv_", "std::").
	// Vendored libs are usually submodules and absent from this repo's index, so
	// their symbols are unverifiable rather than broken.
	ExternalPrefixes []string
	Vocab            []VocabRule
}

var (
	codeSpanPattern = regexp.MustCompile("`([^`\n]+)`")
	identPattern    = regexp.MustCompile(`^[A-Za-z_][A-Za-z0-9_]*(::[A-Za-z_][A-Za-z0-9_]*)*(\(\))?$`)
	flagPattern     = regexp.MustCompile(`^--?[A-Za-z][A-Za-z0-9-]*$`)
	extPattern      = regexp.MustCompile(`\.(md|cpp|cc|h|hpp|c|xml|py|sh|json|mk|bats|yml|yaml|ts|go|txt|toml|cfg)$`)
	commentPattern  = regexp.MustCompile(`^\s*(//|#|\*|/\*|--|<!--)`)
	bracketIDRe     = regexp.MustCompile(`\[([LS]\d{3})\]`)
)

// Run checks every lesson and returns findings ranked so the highest-traffic,
// longest-unverified lessons come first - the inverse of treating citation count
// as evidence of correctness.
func Run(lessons []*models.Lesson, cfg Config, ledger Ledger) []Finding {
	for i := range cfg.Vocab {
		if cfg.Vocab[i].re == nil {
			cfg.Vocab[i].re, _ = regexp.Compile(cfg.Vocab[i].Pattern)
		}
	}

	var out []Finding
	for _, l := range lessons {
		for _, f := range checkLesson(l, cfg) {
			if ledger.IsDismissed(l, f.Token) {
				continue
			}
			out = append(out, f)
		}
	}

	sort.SliceStable(out, func(i, j int) bool {
		if out[i].Uses != out[j].Uses {
			return out[i].Uses > out[j].Uses
		}
		return out[i].LastUsed.Before(out[j].LastUsed)
	})
	return out
}

func checkLesson(l *models.Lesson, cfg Config) []Finding {
	var out []Finding
	add := func(kind Kind, token, reason string) {
		out = append(out, Finding{
			LessonID: l.ID, Kind: kind, Token: token, Reason: reason,
			Uses: l.Uses, LastUsed: l.LastUsed,
		})
	}

	// Vocabulary runs over the whole body: the term that started this had no
	// backticks anywhere, so no reference-extraction scheme could see it.
	for _, rule := range cfg.Vocab {
		if rule.re != nil && rule.re.MatchString(l.Content) {
			add(KindVocab, rule.re.FindString(l.Content), rule.Message)
		}
	}

	seen := map[string]bool{}
	for _, r := range extractRefs(l.Content) {
		if seen[r.token] {
			continue
		}
		seen[r.token] = true

		switch classify(r.token) {
		case KindFlag:
			// Only check flags belonging to a command this project owns.
			// Lessons quote other tools constantly (`git log -S`, `tar -af`),
			// and their flags are not this project's to validate.
			if len(cfg.FlagSources) == 0 || !spanOwnsFlag(cfg, r.span) {
				continue
			}
			if !flagExists(cfg.ProjectRoot, cfg.FlagSources, r.token) {
				add(KindFlag, r.token, "flag is not registered in "+strings.Join(cfg.FlagSources, ", "))
			}
		case KindPath:
			if !pathExists(cfg.ProjectRoot, r.token) {
				add(KindPath, r.token, "path does not exist in the project")
			}
		case KindIdent:
			if isExternal(cfg, r.token) {
				continue
			}
			if !identExistsInSource(cfg.ProjectRoot, cfg.SourceRoots, r.token) {
				add(KindIdent, r.token, "identifier does not appear in "+strings.Join(cfg.SourceRoots, ", "))
			}
		}
	}
	return out
}

// spanOwnsFlag reports whether a code span invokes a command this project owns.
// With no FlagCommands declared, every span qualifies, which preserves the
// simple single-binary case.
func spanOwnsFlag(cfg Config, span string) bool {
	if len(cfg.FlagCommands) == 0 {
		return true
	}
	for _, c := range cfg.FlagCommands {
		if strings.Contains(span, c) {
			return true
		}
	}
	return false
}

// isExternal reports whether a symbol belongs to a dependency rather than this
// project. Vendored libraries are usually submodules, so their symbols are not
// in the superproject's index and cannot be verified either way. Asserting they
// are broken is worse than staying silent - the same call the project's own doc
// linter makes for uninitialized submodules.
func isExternal(cfg Config, tok string) bool {
	probe := strings.TrimSuffix(tok, "()")
	for _, p := range cfg.ExternalPrefixes {
		if strings.HasPrefix(probe, p) {
			return true
		}
	}
	return false
}

// ref is a candidate token plus the code span it came from. The span matters for
// flags: `-S` in a `git log -S` example is git's flag, not the project binary's,
// and checking it against the project's arg parser reports a fake break.
type ref struct {
	token string
	span  string
}

// extractRefs pulls candidates out of code spans. Multi-token spans are split
// rather than skipped: a removed CLI flag typically appears inside a full
// command line, which is exactly where a whole-span check stops looking.
func extractRefs(body string) []ref {
	var out []ref
	for _, m := range codeSpanPattern.FindAllStringSubmatch(body, -1) {
		span := strings.TrimSpace(m[1])
		if !strings.ContainsAny(span, " \t") {
			out = append(out, ref{token: span, span: span})
			continue
		}
		for _, word := range strings.Fields(span) {
			word = strings.Trim(word, ",;:\"'()")
			if word != "" {
				out = append(out, ref{token: word, span: span})
			}
		}
	}
	return out
}

func classify(tok string) Kind {
	// Placeholders and shell noise.
	if strings.ContainsAny(tok, "<>*${}…|") || tok == "" {
		return ""
	}
	if flagPattern.MatchString(tok) {
		return KindFlag
	}
	if strings.Contains(tok, "/") || extPattern.MatchString(tok) {
		// Absolute paths are device/runtime locations, not repo paths.
		if strings.HasPrefix(tok, "/") || strings.HasPrefix(tok, "~") {
			return ""
		}
		// `lv_draw_rect/_triangle/_fill` is prose shorthand, not a path. A real
		// relative path has a file extension somewhere in it.
		if !extPattern.MatchString(tok) {
			return ""
		}
		return KindPath
	}
	if identPattern.MatchString(tok) && (strings.Contains(tok, "_") ||
		strings.Contains(tok, "::") || strings.HasSuffix(tok, "()")) {
		return KindIdent
	}
	return ""
}

func pathExists(root, rel string) bool {
	clean := strings.TrimPrefix(rel, "./")
	if _, err := os.Stat(filepath.Join(root, clean)); err == nil {
		return true
	}
	// A bare or partial path is fine if exactly that suffix exists somewhere.
	var found bool
	filepath.Walk(root, func(p string, info os.FileInfo, err error) error {
		if err != nil || found {
			return nil
		}
		if info.IsDir() && (info.Name() == ".git" || info.Name() == "build") {
			return filepath.SkipDir
		}
		if strings.HasSuffix(filepath.ToSlash(p), "/"+clean) {
			found = true
		}
		return nil
	})
	return found
}

// identExistsInSource reports whether a symbol appears in real code.
//
// Comment lines are stripped before deciding. That is not a refinement: the
// transposed symbol in the original audit appeared exactly once in the tree, in
// a comment written to record that it does not exist. Counting that as evidence
// clears the very lesson the check exists to catch.
func identExistsInSource(root string, sourceRoots []string, symbol string) bool {
	symbol = strings.TrimSuffix(symbol, "()")
	if symbol == "" {
		return false
	}

	// A qualified name is rarely written out in full at the definition site:
	// `AsyncLifetimeGuard::token()` is declared as `LifetimeToken token() const`
	// inside the class. Verify the parts instead - if every component exists,
	// the reference is sound enough not to report.
	if strings.Contains(symbol, "::") {
		for _, part := range strings.Split(symbol, "::") {
			if part == "" {
				continue
			}
			if !identExistsInSource(root, sourceRoots, part) {
				return false
			}
		}
		return true
	}
	// Substring, not whole-word. C and C++ symbols routinely appear suffixed at
	// their definition (`lv_subject` is declared as `lv_subject_t`), and
	// whole-word matching reported those as missing. A phantom is almost always
	// a distinct string rather than a substring of something real - the
	// transposed name that motivated this check occurs in zero source files
	// under either rule - so the looser match costs nothing here.
	//
	// -e is required: a symbol beginning with '-' is otherwise parsed as a git
	// option (`-vv` silently became grep's invert-match).
	args := []string{"grep", "-nI", "-F", "-e", symbol, "--"}
	if len(sourceRoots) == 0 {
		args = append(args, ":/")
	} else {
		args = append(args, sourceRoots...)
	}

	cmd := exec.Command("git", args...)
	cmd.Dir = root
	out, err := cmd.Output()
	if err != nil {
		return false
	}
	for _, line := range strings.Split(string(out), "\n") {
		// git grep -n gives path:line:content
		parts := strings.SplitN(line, ":", 3)
		if len(parts) < 3 {
			continue
		}
		if !commentPattern.MatchString(parts[2]) {
			return true
		}
	}
	return false
}

func flagExists(root string, flagSources []string, flag string) bool {
	// Whole-word here, unlike identifiers: without it `-p` matches inside
	// `--x-pos` and a removed flag reads as still registered.
	args := append([]string{"grep", "-qIwF", "-e", flag, "--"}, flagSources...)
	cmd := exec.Command("git", args...)
	cmd.Dir = root
	return cmd.Run() == nil
}

// --- dismissal ledger ---

// Entry records that a token was reviewed and judged fine for one exact wording.
type Entry struct {
	Token string `json:"token"`
	Hash  string `json:"hash"`
}

// Ledger maps lesson ID to reviewed tokens.
//
// Keying on a hash of the body is what makes negative references workable: a
// corrected lesson that says "NOT `component_register`" is dismissed once, and
// if anyone rewrites that lesson the hash changes and every reference in it is
// re-opened. The dismissal is a judgement about that wording, not a permanent
// exemption for the token.
type Ledger map[string][]Entry

func bodyHash(l *models.Lesson) string {
	sum := sha256.Sum256([]byte(l.Content))
	return hex.EncodeToString(sum[:8])
}

// Dismiss records a reviewed token for a lesson's current wording.
func (le Ledger) Dismiss(l *models.Lesson, token string) {
	h := bodyHash(l)
	for _, e := range le[l.ID] {
		if e.Token == token && e.Hash == h {
			return
		}
	}
	le[l.ID] = append(le[l.ID], Entry{Token: token, Hash: h})
}

// IsDismissed reports whether this token was reviewed for this exact wording.
func (le Ledger) IsDismissed(l *models.Lesson, token string) bool {
	if le == nil {
		return false
	}
	h := bodyHash(l)
	for _, e := range le[l.ID] {
		if e.Token == token && e.Hash == h {
			return true
		}
	}
	return false
}

// LoadLedger reads the sidecar; a missing or corrupt file yields an empty
// ledger, so a bad file costs re-review rather than silently hiding findings.
func LoadLedger(path string) Ledger {
	data, err := os.ReadFile(path)
	if err != nil {
		return Ledger{}
	}
	var le Ledger
	if err := json.Unmarshal(data, &le); err != nil || le == nil {
		return Ledger{}
	}
	return le
}

// Save writes the ledger.
func (le Ledger) Save(path string) error {
	data, err := json.MarshalIndent(le, "", "  ")
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		return err
	}
	return os.WriteFile(path, append(data, '\n'), 0644)
}

// LedgerPath returns the ledger location for a project.
func LedgerPath(projectRoot string) string {
	return filepath.Join(projectRoot, ".claude-recall", "validate-dismissed.json")
}

// --- reverse direction ---

// Dangling is a lesson ID cited in the tree with no lesson behind it.
type Dangling struct {
	ID    string
	Files []string
}

// DanglingCitations finds IDs referenced in source that no longer resolve.
//
// Rot runs both ways. Because IDs get written into code comments, retiring a
// lesson strands every reference to it - one audit created fourteen such
// references in a single commit. Tombstones keep those resolvable; this reports
// the ones that predate tombstoning.
func DanglingCitations(projectRoot string, known []*models.Lesson) []Dangling {
	have := make(map[string]bool, len(known))
	for _, l := range known {
		have[l.ID] = true
	}

	cmd := exec.Command("git", "grep", "-noIE", `\[[LS][0-9]{3}\]`,
		"--", ":/", ":(glob)!.claude-recall/**")
	cmd.Dir = projectRoot
	out, err := cmd.Output()
	if err != nil {
		return nil
	}

	byID := map[string]map[string]bool{}
	for _, line := range strings.Split(string(out), "\n") {
		parts := strings.SplitN(line, ":", 3)
		if len(parts) < 3 {
			continue
		}
		for _, m := range bracketIDRe.FindAllStringSubmatch(parts[2], -1) {
			id := m[1]
			if have[id] {
				continue
			}
			if byID[id] == nil {
				byID[id] = map[string]bool{}
			}
			byID[id][parts[0]] = true
		}
	}

	var out2 []Dangling
	for id, files := range byID {
		d := Dangling{ID: id}
		for f := range files {
			d.Files = append(d.Files, f)
		}
		sort.Strings(d.Files)
		out2 = append(out2, d)
	}
	sort.Slice(out2, func(i, j int) bool { return out2[i].ID < out2[j].ID })
	return out2
}
