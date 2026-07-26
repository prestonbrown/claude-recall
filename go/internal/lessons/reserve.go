package lessons

import (
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
)

// Lesson IDs share a namespace with whatever the project already means by
// "L081". helixscreen, for instance, uses L081 as a permanent label for a
// bg-thread TOCTOU anti-pattern - baked into scripts/check_l081_anti_pattern.py,
// a `// L081_OK` convention, CLAUDE.md, and THREADING.md. When the allocator
// independently handed L081 to a lesson about deferred callbacks, `[L081]` had
// two meanings, and the Stop hook's citation regex could not tell them apart:
// any agent echoing the project's own label credited the unrelated lesson.
//
// So before handing out a number, look at what the project already uses. A
// bracketed ID that appears in the tree but not in the store is not a citation -
// nothing would be citing a lesson that does not exist - so it is either the
// project's own label or a reference to a retired lesson. Both are reasons not
// to reuse the number.

var bracketedIDPattern = regexp.MustCompile(`\[([LS]\d{3})\]`)

// ReservedIDs returns IDs that appear in the project tree but are not known
// lessons. `known` should contain every ID in the store, including tombstones.
//
// Uses `git grep` so the scan respects .gitignore and skips build output. A
// project that is not a git repo, or a missing git binary, yields no
// reservations rather than an error: failing to allocate an ID is worse than
// occasionally colliding, and the collision is reported by `recall validate`.
func ReservedIDs(projectRoot string, known map[string]bool) map[string]bool {
	reserved := make(map[string]bool)
	if projectRoot == "" {
		return reserved
	}

	cmd := exec.Command("git", "grep", "-hoIE", `\[[LS][0-9]{3}\]`,
		// The lessons file is the store's own serialization; every ID in it is
		// by definition known, so scanning it would add nothing but noise.
		"--", ":/", ":(glob)!.claude-recall/**")
	cmd.Dir = projectRoot
	out, err := cmd.Output()
	if err != nil {
		// Exit status 1 just means no matches; anything else means no git.
		return reserved
	}

	for _, m := range bracketedIDPattern.FindAllStringSubmatch(string(out), -1) {
		id := m[1]
		if !known[id] {
			reserved[id] = true
		}
	}
	return reserved
}

// projectRoot derives the repository root from the path to a project
// LESSONS.md (<root>/.claude-recall/LESSONS.md).
func projectRoot(lessonsPath string) string {
	if lessonsPath == "" {
		return ""
	}
	dir := filepath.Dir(lessonsPath)
	if strings.EqualFold(filepath.Base(dir), ".claude-recall") {
		return filepath.Dir(dir)
	}
	return dir
}
