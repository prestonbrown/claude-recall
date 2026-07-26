package validate

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"github.com/pbrown/claude-recall/internal/models"
)

// The fixture mirrors the parts of helixscreen that made the 2026-07-26 audit
// findings possible, including the trap that defeats the obvious oracle:
// scripts/check_doc_refs.py names the transposed symbol *in a comment* while
// explaining that it does not exist. Any "does this string appear in the repo"
// check calls that a hit and clears the broken lesson.
func fixtureRepo(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	write := func(rel, content string) {
		p := filepath.Join(dir, rel)
		if err := os.MkdirAll(filepath.Dir(p), 0755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(p, []byte(content), 0644); err != nil {
			t.Fatal(err)
		}
	}

	write("src/xml_registration.cpp", `
void register_xml() {
    if (lv_xml_register_component_from_file(path.c_str()) != LV_RESULT_OK) { return; }
}
`)
	write("src/system/cli_args.cpp", `
void parse(int argc, char** argv) {
    else if (strcmp(argv[i], "--test") == 0) { opts.test = true; }
    else if (strcmp(argv[i], "-vv") == 0) { opts.verbose = 2; }
    else if (strcmp(argv[i], "--sim-speed") == 0) { opts.sim = atoi(argv[++i]); }
}
`)
	// The trap: a comment naming a symbol that exists nowhere in real code.
	write("scripts/check_doc_refs.py", `#!/usr/bin/env python3
#   - a lesson taught lv_xml_component_register_from_file(), a transposed name
#     that exists nowhere
import sys
`)
	write("src/temperature.cpp", `
int deci_to_degrees(int deci) { return deci / 10; }
`)

	if err := exec.Command("git", "init", "-q", dir).Run(); err != nil {
		t.Skipf("git unavailable: %v", err)
	}
	cmd := exec.Command("git", "add", "-A")
	cmd.Dir = dir
	if err := cmd.Run(); err != nil {
		t.Fatal(err)
	}
	return dir
}

func testConfig(root string) Config {
	return Config{
		ProjectRoot: root,
		SourceRoots: []string{"src/", "include/", "tests/"},
		FlagSources: []string{"src/system/cli_args.cpp"},
		Vocab: []VocabRule{{
			Pattern: `(?i)centidegree`,
			Message: "the unit is decidegrees; 'centidegree' is forbidden by tests/shell/test_code_lint.bats",
		}},
	}
}

func lesson(id, body string) *models.Lesson {
	return &models.Lesson{ID: id, Title: id, Content: body, Uses: 10}
}

func findingTokens(fs []Finding) string {
	var b []string
	for _, f := range fs {
		b = append(b, string(f.Kind)+":"+f.Token)
	}
	return strings.Join(b, ", ")
}

func hasToken(fs []Finding, token string) bool {
	for _, f := range fs {
		if f.Token == token {
			return true
		}
	}
	return false
}

// --- must-flag: the three lessons that were actually wrong ---

func TestFlagsTransposedIdentifier(t *testing.T) {
	root := fixtureRepo(t)
	// L014 as it stood pre-audit.
	ls := []*models.Lesson{lesson("L014",
		"New XML components need `lv_xml_component_register_from_file()` in main.cpp. Forgetting = silent failure.")}

	got := Run(ls, testConfig(root), nil)
	if !hasToken(got, "lv_xml_component_register_from_file()") {
		t.Errorf("did not flag the transposed symbol; findings: %s\n"+
			"It appears only inside a comment in scripts/check_doc_refs.py, which must not count as evidence.",
			findingTokens(got))
	}
}

func TestFlagsRemovedCLIFlagInsideCommand(t *testing.T) {
	root := fixtureRepo(t)
	// L060 pre-audit: the dead flag lives inside a multi-token command span.
	ls := []*models.Lesson{lesson("L060",
		"1. `Bash` with `run_in_background: true`: `./build/bin/helix-screen --test -vv -p panel_name 2>&1 | tee /tmp/test.log` — NOT shell `&` or `timeout`.")}

	got := Run(ls, testConfig(root), nil)
	if !hasToken(got, "-p") {
		t.Errorf("did not flag the removed -p flag; findings: %s\n"+
			"Extraction must look inside multi-token code spans, not skip them.", findingTokens(got))
	}
	if hasToken(got, "--test") {
		t.Errorf("--test is registered in cli_args.cpp and must not be flagged; findings: %s", findingTokens(got))
	}
}

func TestFlagsForbiddenVocabularyInProse(t *testing.T) {
	root := fixtureRepo(t)
	// L021: no backticks at all - only a vocabulary rule can catch this.
	ls := []*models.Lesson{lesson("L021",
		"Centidegrees (int) for temp subjects to keep 0.1°C resolution.")}

	got := Run(ls, testConfig(root), nil)
	found := false
	for _, f := range got {
		if f.Kind == KindVocab {
			found = true
		}
	}
	if !found {
		t.Errorf("did not flag the forbidden term in prose; findings: %s", findingTokens(got))
	}
}

// --- must-not-flag: the corrected forms ---

func TestDoesNotFlagCorrectedLessons(t *testing.T) {
	root := fixtureRepo(t)
	ls := []*models.Lesson{
		lesson("L014", "New XML components need a `lv_xml_register_component_from_file()` call in `src/xml_registration.cpp` (via the local `register_xml()` helper)."),
		lesson("L060", "Launch with `./build/bin/helix-screen --test -vv` and drive it with `ctl`."),
	}
	got := Run(ls, testConfig(root), nil)
	if len(got) != 0 {
		t.Errorf("corrected lessons should produce no findings, got: %s", findingTokens(got))
	}
}

// --- false-positive families measured on the real lesson set ---

func TestDoesNotFlagDeviceOrRuntimePaths(t *testing.T) {
	root := fixtureRepo(t)
	ls := []*models.Lesson{lesson("L061",
		"Logs land in `/tmp/helixscreen.log` and `/var/log/messages`; the install lives at `/opt/helixscreen/`.")}

	got := Run(ls, testConfig(root), nil)
	if len(got) != 0 {
		t.Errorf("absolute device paths are not repo paths and must not be flagged: %s", findingTokens(got))
	}
}

func TestDoesNotFlagProseShorthandWithSlashes(t *testing.T) {
	root := fixtureRepo(t)
	ls := []*models.Lesson{lesson("L079",
		"Hooks fire between `DRAW_MAIN_END/DRAW_POST`; affects `lv_draw_rect/_triangle/_fill`.")}

	got := Run(ls, testConfig(root), nil)
	for _, f := range got {
		if f.Kind == KindPath {
			t.Errorf("prose shorthand classified as a path: %s", f.Token)
		}
	}
}

// --- the oracle must not accept a comment as proof ---

func TestCommentsAreNotEvidence(t *testing.T) {
	root := fixtureRepo(t)
	if identExistsInSource(root, testConfig(root).SourceRoots, "lv_xml_component_register_from_file") {
		t.Error("a symbol appearing only in a comment must not count as existing")
	}
	if !identExistsInSource(root, testConfig(root).SourceRoots, "lv_xml_register_component_from_file") {
		t.Error("the real symbol is called in src/xml_registration.cpp and must be found")
	}
}

// --- dismissal ledger ---

func TestDismissalSuppressesUntilTheBodyChanges(t *testing.T) {
	root := fixtureRepo(t)
	body := "New XML components need `lv_xml_component_register_from_file()` in main.cpp."
	ls := []*models.Lesson{lesson("L014", body)}
	cfg := testConfig(root)

	got := Run(ls, cfg, nil)
	if len(got) == 0 {
		t.Fatal("expected a finding to dismiss")
	}

	ledger := Ledger{}
	ledger.Dismiss(ls[0], got[0].Token)

	if len(Run(ls, cfg, ledger)) != 0 {
		t.Error("dismissed finding should stay suppressed")
	}

	// Editing the lesson re-opens every reference in it: the dismissal was a
	// judgement about that wording, not a permanent exemption for the token.
	edited := []*models.Lesson{lesson("L014", body+" Updated with more detail.")}
	if len(Run(edited, cfg, ledger)) == 0 {
		t.Error("editing the body must re-open its dismissed findings")
	}
}

// --- reverse direction: IDs cited in the tree with no lesson behind them ---

func TestReportsDanglingCitations(t *testing.T) {
	dir := t.TempDir()
	if err := os.MkdirAll(filepath.Join(dir, "include"), 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "include", "panel.h"),
		[]byte("// SubjectLifetime is mandatory (see [L084]: lifetime must outlive observer).\n"+
			"// destruction flag for async safety [L012]\n"), 0644); err != nil {
		t.Fatal(err)
	}
	if err := exec.Command("git", "init", "-q", dir).Run(); err != nil {
		t.Skipf("git unavailable: %v", err)
	}
	cmd := exec.Command("git", "add", "-A")
	cmd.Dir = dir
	if err := cmd.Run(); err != nil {
		t.Fatal(err)
	}

	known := []*models.Lesson{lesson("L012", "still here")}
	dangling := DanglingCitations(dir, known)

	if !containsID(dangling, "L084") {
		t.Errorf("L084 is cited in include/panel.h but has no lesson; got %v", dangling)
	}
	if containsID(dangling, "L012") {
		t.Errorf("L012 exists and must not be reported dangling; got %v", dangling)
	}
}

func containsID(ds []Dangling, id string) bool {
	for _, d := range ds {
		if d.ID == id {
			return true
		}
	}
	return false
}

// --- ranking inverts the trust curve ---

func TestFindingsRankHighTrafficFirst(t *testing.T) {
	root := fixtureRepo(t)
	low := lesson("L900", "uses `nonexistent_symbol_alpha()` here")
	low.Uses = 2
	high := lesson("L901", "uses `nonexistent_symbol_beta()` here")
	high.Uses = 90

	got := Run([]*models.Lesson{low, high}, testConfig(root), nil)
	if len(got) < 2 {
		t.Fatalf("expected both to be flagged, got: %s", findingTokens(got))
	}
	if got[0].LessonID != "L901" {
		t.Errorf("highest-traffic lesson should rank first, got %s - frequent citation "+
			"is a reason to re-check, not to trust", got[0].LessonID)
	}
}
