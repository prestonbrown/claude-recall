# Better Lesson Injection - Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace dead Haiku-based relevance scoring with local BM25, inject lessons at more points (every prompt + SubagentStop), and strip handoff code from hooks.

**Architecture:** Pure Python BM25 scorer in `core/scoring.py`, Go native BM25 in `go/internal/scoring/`, called from hooks via Go binary `score-local` command. Session dedup via state file. Handoff hook code removed but core library kept.

**Tech Stack:** Python 3, Go, bash hooks, BM25 algorithm (no external deps)

---

### Task 1: Python BM25 Scorer - Tests

**Files:**
- Create: `tests/test_scoring.py`
- Reference: `core/models.py:471` (ScoredLesson dataclass)

**Step 1: Write failing tests for BM25 scorer**

```python
"""Tests for core/scoring.py - BM25 local relevance scoring."""
import pytest
from core.scoring import BM25Scorer, score_lessons_local
from core.models import Lesson, LessonRating, ScoredLesson


def _make_lesson(id, title, content, uses=5, velocity=3.0):
    """Helper to create a Lesson for testing."""
    return Lesson(
        id=id,
        title=title,
        content=content,
        category="pattern",
        rating=LessonRating(uses=uses, velocity=velocity),
        level="project",
    )


class TestBM25Scorer:
    def test_tokenize_basic(self):
        scorer = BM25Scorer()
        tokens = scorer.tokenize("Fix the authentication bug in login")
        assert "fix" in tokens
        assert "authentication" in tokens
        assert "bug" in tokens
        assert "login" in tokens
        # Stop words removed
        assert "the" not in tokens
        assert "in" not in tokens

    def test_tokenize_punctuation(self):
        scorer = BM25Scorer()
        tokens = scorer.tokenize("error-handling: use try/catch")
        assert "error" in tokens
        assert "handling" in tokens
        assert "use" in tokens
        assert "try" in tokens
        assert "catch" in tokens

    def test_tokenize_empty(self):
        scorer = BM25Scorer()
        assert scorer.tokenize("") == []
        assert scorer.tokenize("the a is") == []

    def test_score_single_lesson_relevant(self):
        lessons = [_make_lesson("L001", "Git commit format", "Use conventional commits with type(scope): description")]
        scorer = BM25Scorer(lessons)
        scores = scorer.score("How should I format git commits?")
        assert len(scores) == 1
        assert scores[0].score > 0

    def test_score_single_lesson_irrelevant(self):
        lessons = [_make_lesson("L001", "Git commit format", "Use conventional commits")]
        scorer = BM25Scorer(lessons)
        scores = scorer.score("database connection pooling")
        assert len(scores) == 1
        assert scores[0].score == 0 or scores[0].score < scores[0].score  # score is 0 or very low
        # More precise: irrelevant query should score 0
        assert scores[0].score == 0

    def test_score_ranks_by_relevance(self):
        lessons = [
            _make_lesson("L001", "Git commit format", "Use conventional commits with type(scope): description"),
            _make_lesson("L002", "Database indexing", "Add indexes on frequently queried columns"),
            _make_lesson("L003", "Git branch naming", "Use feature/fix/chore prefixes for branch names"),
        ]
        scorer = BM25Scorer(lessons)
        scores = scorer.score("git commit message conventions")
        # L001 (git + commit) should rank highest
        sorted_scores = sorted(scores, key=lambda s: s.score, reverse=True)
        assert sorted_scores[0].lesson.id == "L001"

    def test_score_empty_query(self):
        lessons = [_make_lesson("L001", "Test", "Content")]
        scorer = BM25Scorer(lessons)
        scores = scorer.score("")
        assert all(s.score == 0 for s in scores)

    def test_score_empty_lessons(self):
        scorer = BM25Scorer([])
        scores = scorer.score("anything")
        assert scores == []

    def test_score_tiebreak_by_uses(self):
        lessons = [
            _make_lesson("L001", "Same keywords here", "testing content", uses=10),
            _make_lesson("L002", "Same keywords here", "testing content", uses=5),
        ]
        scorer = BM25Scorer(lessons)
        scores = scorer.score("same keywords testing")
        sorted_scores = sorted(scores, key=lambda s: (-s.score, -s.lesson.rating.uses))
        assert sorted_scores[0].lesson.id == "L001"


class TestScoreLessonsLocal:
    def test_returns_top_n(self):
        lessons = [
            _make_lesson(f"L{i:03d}", f"Lesson {i} about git", f"Content about git workflow {i}")
            for i in range(1, 11)
        ]
        result = score_lessons_local(lessons, "git workflow", top_n=3)
        assert len(result) <= 3

    def test_filters_by_min_score(self):
        lessons = [
            _make_lesson("L001", "Git commit", "Use conventional commits"),
            _make_lesson("L002", "Unrelated topic", "Something about cooking recipes"),
        ]
        result = score_lessons_local(lessons, "git commit format", min_score=1)
        # Only relevant lesson should pass min_score filter
        ids = [s.lesson.id for s in result]
        assert "L001" in ids

    def test_returns_sorted_descending(self):
        lessons = [
            _make_lesson("L001", "Python testing", "Use pytest for testing"),
            _make_lesson("L002", "Git commits", "Use conventional commits"),
            _make_lesson("L003", "Python pytest fixtures", "Use fixtures for test setup in pytest"),
        ]
        result = score_lessons_local(lessons, "pytest fixtures for testing", top_n=10, min_score=0)
        scores = [s.score for s in result if s.score > 0]
        assert scores == sorted(scores, reverse=True)
```

**Step 2: Run tests to verify they fail**

Run: `./run-tests.sh tests/test_scoring.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.scoring'`

**Step 3: Commit test file**

```bash
git add tests/test_scoring.py
git commit -m "test: add BM25 scoring tests"
```

---

### Task 2: Python BM25 Scorer - Implementation

**Files:**
- Create: `core/scoring.py`
- Reference: `core/models.py:471` (ScoredLesson), `core/models.py:478` (RelevanceResult)

**Step 1: Implement BM25 scorer**

```python
"""BM25 local relevance scoring for lessons.

Scores lesson titles + content against a query using the BM25 algorithm.
No external dependencies - pure Python implementation.
"""
import math
import re
from collections import Counter
from typing import List, Optional

try:
    from core.models import Lesson, ScoredLesson
except ImportError:
    from models import Lesson, ScoredLesson


# Standard BM25 parameters
K1 = 1.5  # Term frequency saturation
B = 0.75  # Length normalization

# Common English stop words (keep small - corpus is tiny)
STOP_WORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "must",
    "in", "on", "at", "to", "for", "of", "with", "by", "from", "as",
    "into", "about", "between", "through", "during", "before", "after",
    "and", "but", "or", "nor", "not", "so", "yet", "both", "either",
    "it", "its", "this", "that", "these", "those",
    "i", "you", "he", "she", "we", "they", "me", "him", "her", "us", "them",
    "my", "your", "his", "our", "their",
    "if", "then", "else", "when", "where", "how", "what", "which", "who",
})

_SPLIT_RE = re.compile(r"[^a-z0-9]+")


class BM25Scorer:
    """BM25 scorer for a corpus of lessons."""

    def __init__(self, lessons: Optional[List[Lesson]] = None):
        self._lessons = lessons or []
        self._doc_tokens: List[List[str]] = []
        self._doc_freqs: dict[str, int] = Counter()  # term -> num docs containing it
        self._avg_dl = 0.0
        self._n = len(self._lessons)

        if self._lessons:
            self._index()

    def tokenize(self, text: str) -> List[str]:
        """Tokenize text: lowercase, split on non-alphanumeric, remove stop words."""
        if not text:
            return []
        tokens = _SPLIT_RE.split(text.lower())
        return [t for t in tokens if t and t not in STOP_WORDS and len(t) > 1]

    def _index(self):
        """Build the index from lessons."""
        for lesson in self._lessons:
            doc_text = f"{lesson.title} {lesson.content}"
            tokens = self.tokenize(doc_text)
            self._doc_tokens.append(tokens)
            # Count unique terms per doc for document frequency
            for term in set(tokens):
                self._doc_freqs[term] += 1

        total_len = sum(len(dt) for dt in self._doc_tokens)
        self._avg_dl = total_len / self._n if self._n > 0 else 0.0

    def _idf(self, term: str) -> float:
        """Inverse document frequency with smoothing."""
        df = self._doc_freqs.get(term, 0)
        # BM25 IDF: log((N - df + 0.5) / (df + 0.5) + 1)
        return math.log((self._n - df + 0.5) / (df + 0.5) + 1.0)

    def score(self, query: str) -> List[ScoredLesson]:
        """Score all lessons against the query. Returns ScoredLesson list."""
        if not self._lessons:
            return []

        query_tokens = self.tokenize(query)
        if not query_tokens:
            return [ScoredLesson(lesson=l, score=0) for l in self._lessons]

        results = []
        for i, lesson in enumerate(self._lessons):
            doc_tokens = self._doc_tokens[i]
            dl = len(doc_tokens)
            tf_map = Counter(doc_tokens)

            raw_score = 0.0
            for term in query_tokens:
                if term not in tf_map:
                    continue
                tf = tf_map[term]
                idf = self._idf(term)
                # BM25 term score
                numerator = tf * (K1 + 1)
                denominator = tf + K1 * (1 - B + B * dl / self._avg_dl) if self._avg_dl > 0 else tf + K1
                raw_score += idf * numerator / denominator

            # Normalize to 0-10 integer scale
            # Use a sigmoid-like mapping: score of ~3 raw -> ~5 normalized
            if raw_score > 0:
                normalized = min(10, int(raw_score * 2 + 0.5))
                normalized = max(1, normalized)  # At least 1 if any match
            else:
                normalized = 0

            results.append(ScoredLesson(lesson=lesson, score=normalized))

        return results


def score_lessons_local(
    lessons: List[Lesson],
    query: str,
    top_n: int = 5,
    min_score: int = 1,
) -> List[ScoredLesson]:
    """Score lessons against query using BM25, return top results.

    This is the main entry point for local scoring.
    """
    scorer = BM25Scorer(lessons)
    all_scores = scorer.score(query)

    # Filter by min_score
    filtered = [s for s in all_scores if s.score >= min_score]

    # Sort by score desc, then by uses desc for tiebreaking
    filtered.sort(key=lambda s: (-s.score, -s.lesson.rating.uses))

    return filtered[:top_n]
```

**Step 2: Run tests to verify they pass**

Run: `./run-tests.sh tests/test_scoring.py -v`
Expected: All PASS

**Step 3: Commit**

```bash
git add core/scoring.py
git commit -m "feat: add BM25 local relevance scoring"
```

---

### Task 3: Wire BM25 into LessonsManager

**Files:**
- Modify: `core/lessons.py` (~line 864, `score_relevance` method)
- Modify: `core/commands.py` (add `score-local` CLI command)
- Test: `tests/test_scoring.py` (add integration test)

**Step 1: Add `score_relevance_local` method to LessonsManager**

In `core/lessons.py`, add after the existing `score_relevance` method:

```python
def score_relevance_local(self, query_text: str, top_n: int = 5, min_score: int = 1) -> RelevanceResult:
    """Score lessons locally using BM25 (no API key needed)."""
    from core.scoring import score_lessons_local

    query_text = query_text[:SCORE_RELEVANCE_MAX_QUERY_LEN]
    all_lessons = self.list_lessons(scope="all")
    if not all_lessons:
        return RelevanceResult(scored_lessons=[], query_text=query_text)

    scored = score_lessons_local(all_lessons, query_text, top_n=top_n, min_score=min_score)
    return RelevanceResult(scored_lessons=scored, query_text=query_text)
```

**Step 2: Add `score-local` CLI command**

In `core/commands.py`, add handler for `score-local` that calls `manager.score_relevance_local()` and outputs formatted results using `RelevanceResult.format()`.

**Step 3: Run all tests**

Run: `./run-tests.sh -v --tb=short`
Expected: All PASS

**Step 4: Commit**

```bash
git add core/lessons.py core/commands.py
git commit -m "feat: add score-local command using BM25"
```

---

### Task 4: Go BM25 Scorer

**Files:**
- Create: `go/internal/scoring/bm25.go`
- Create: `go/internal/scoring/bm25_test.go`
- Modify: `go/cmd/recall/app.go` (add `score-local` command)

**Step 1: Write Go BM25 test**

```go
// go/internal/scoring/bm25_test.go
package scoring

import (
    "testing"
    "github.com/your-module/go/internal/models"
)

func TestTokenize(t *testing.T) {
    tokens := Tokenize("Fix the authentication bug in login")
    if !contains(tokens, "fix") || !contains(tokens, "authentication") {
        t.Errorf("expected key tokens, got %v", tokens)
    }
    if contains(tokens, "the") || contains(tokens, "in") {
        t.Errorf("stop words not removed: %v", tokens)
    }
}

func TestScoreRanking(t *testing.T) {
    lessons := []*models.Lesson{
        {ID: "L001", Title: "Git commit format", Content: "Use conventional commits"},
        {ID: "L002", Title: "Database indexing", Content: "Add indexes on columns"},
    }
    scorer := NewBM25Scorer(lessons)
    scores := scorer.Score("git commit conventions")
    if scores[0].Lesson.ID == "L002" {
        t.Error("L001 should rank higher for git query")
    }
}
```

**Step 2: Implement Go BM25**

Mirror the Python implementation: same tokenizer, stop words, k1/b parameters. Read lessons from LESSONS.md files (reuse existing `store.Load()`).

**Step 3: Add `score-local` command to `app.go`**

Add to command dispatch (around line 180 in `app.go`):
```go
case "score-local":
    return a.runScoreLocal(args[2:])
```

Handler: load lessons, create `BM25Scorer`, score query, output formatted results matching Python's `RelevanceResult.format()` output.

**Step 4: Run Go tests**

Run: `cd go && go test ./internal/scoring/ -v`
Expected: All PASS

**Step 5: Build and test CLI**

Run: `cd go && go build -o ../bin/recall-hook ./cmd/recall-hook && cd .. && ./bin/recall-hook score-local "git commit format" --top 5`

**Step 6: Commit**

```bash
git add go/internal/scoring/ go/cmd/recall/app.go
git commit -m "feat(go): add BM25 local scoring command"
```

---

### Task 5: Remove Handoffs from Hooks

**Files:**
- Modify: `plugins/claude-recall/hooks/scripts/stop-hook.sh` (remove `process_handoffs`, `capture_todowrite`, `detect_and_warn_missing_handoff`)
- Modify: `plugins/claude-recall/hooks/scripts/inject-hook.sh` (remove handoff injection, HANDOFF DUTY)
- Delete: `plugins/claude-recall/hooks/scripts/session-end-hook.sh`
- Delete: `plugins/claude-recall/hooks/scripts/post-todowrite-hook.sh`
- Delete: `plugins/claude-recall/hooks/scripts/post-exitplanmode-hook.sh`
- Modify: `adapters/claude-code/hooks-config.json` (remove Stop[1], PostToolUse entries)

**Step 1: Strip handoff code from stop-hook.sh**

Remove these functions (keep citation tracking and AI lesson capture):
- `process_handoffs()` (lines ~387-443)
- `capture_todowrite()` (lines ~450-480)
- `detect_and_warn_missing_handoff()` (lines ~483-507)
- Remove calls to these functions from `main()`

In `main()` bash fallback path, remove handoff-related processing. Keep: citation parsing, AI lesson parsing.

For the Go fast path (`GO_RECALL_HOOK stop-all`), the Go binary still has handoff code but it's harmless - it just won't find any patterns. Can clean Go side separately.

**Step 2: Strip handoff injection from inject-hook.sh**

In `generate_combined_context()` and `generate_context_fallback()`:
- Remove `handoff inject` and `handoff inject-todos` calls
- Remove `HANDOFFS_SUMMARY` and `TODOS_PROMPT` variables

In `main()`:
- Remove handoff summary appending (lines ~184-192)
- Remove `ready_for_review` check and LESSON REVIEW DUTY (lines ~248-265)
- Remove HANDOFF DUTY block (lines ~278-291)
- Remove todo continuation (lines ~293-298)

**Step 3: Delete hook scripts**

```bash
rm plugins/claude-recall/hooks/scripts/session-end-hook.sh
rm plugins/claude-recall/hooks/scripts/post-todowrite-hook.sh
rm plugins/claude-recall/hooks/scripts/post-exitplanmode-hook.sh
```

**Step 4: Update hooks-config.json**

Remove from `adapters/claude-code/hooks-config.json`:
- `Stop` array: remove `session-end-hook.sh` entry (keep `stop-hook.sh`)
- `PostToolUse` array: remove both entries entirely
- Remove `PreCompact` if it only serves handoffs (check `precompact-hook.sh` - if it does handoff context extraction, remove it)

**Step 5: Run existing tests to verify nothing breaks**

Run: `./run-tests.sh -v --tb=short`
Expected: All PASS (handoff tests still pass since core library untouched)

**Step 6: Commit**

```bash
git add plugins/claude-recall/hooks/scripts/stop-hook.sh plugins/claude-recall/hooks/scripts/inject-hook.sh adapters/claude-code/hooks-config.json
git rm plugins/claude-recall/hooks/scripts/session-end-hook.sh plugins/claude-recall/hooks/scripts/post-todowrite-hook.sh plugins/claude-recall/hooks/scripts/post-exitplanmode-hook.sh
git commit -m "refactor: remove handoff processing from hooks"
```

---

### Task 6: Update smart-inject-hook to Use Local Scoring

**Files:**
- Modify: `plugins/claude-recall/hooks/scripts/smart-inject-hook.sh`

**Step 1: Remove first-prompt restriction**

In `main()`, remove the `is_first_prompt` check (line ~120). Remove the `is_first_prompt()` function entirely.

**Step 2: Replace Haiku scoring with local scoring**

Replace `score_and_format_lessons()` function body:
- Remove `ANTHROPIC_API_KEY` check
- Change from `$GO_RECALL score-relevance` to `$GO_RECALL score-local`
- Remove `LESSONS_SCORING_ACTIVE=1` env guard (no API call = no recursion risk)
- Reduce timeout from 10s to 2s (local scoring is fast)

```bash
score_and_format_lessons() {
    local prompt="$1"
    local cwd="$2"

    local result stderr_file
    stderr_file=$(mktemp)
    result=$(PROJECT_DIR="$cwd" LESSONS_BASE="$LESSONS_BASE" LESSONS_DEBUG="${LESSONS_DEBUG:-}" \
        timeout 2 \
        "$GO_RECALL" score-local "$prompt" \
            --top "$TOP_LESSONS" \
            --min-score "$MIN_RELEVANCE_SCORE" 2>"$stderr_file") || {
        local stderr_content
        stderr_content=$(cat "$stderr_file" 2>/dev/null)
        rm -f "$stderr_file"
        if [[ -n "$stderr_content" ]]; then
            log_injection_skip "$cwd" "score_local_error" "$stderr_content"
        fi
        return 1
    }
    rm -f "$stderr_file"

    [[ -z "$result" ]] && return 1
    [[ "$result" == *"No lessons found"* ]] && return 1

    echo "$result"
}
```

**Step 3: Optional Haiku upgrade**

Keep the old Haiku path accessible via a config flag. In `main()`:
```bash
# Use Haiku if API key is set AND useHaikuScoring is enabled
if [[ -n "${ANTHROPIC_API_KEY:-}" ]] && [[ "$(get_setting 'useHaikuScoring' 'false')" == "true" ]]; then
    # existing Haiku path...
else
    # local BM25 path (default)
fi
```

**Step 4: Test manually**

Run: `echo '{"prompt":"how do I format git commits?","cwd":"/tmp","transcript_path":""}' | bash plugins/claude-recall/hooks/scripts/smart-inject-hook.sh`
Expected: JSON output with relevant lessons

**Step 5: Commit**

```bash
git add plugins/claude-recall/hooks/scripts/smart-inject-hook.sh
git commit -m "feat: switch to local BM25 scoring, run on every prompt"
```

---

### Task 7: Add SubagentStop Hook

**Files:**
- Create: `plugins/claude-recall/hooks/scripts/subagent-stop-hook.sh`
- Modify: `adapters/claude-code/hooks-config.json`

**Step 1: Create SubagentStop hook script**

```bash
#!/bin/bash
# Claude Recall SubagentStop hook - injects relevant lessons after subagent completes
set -euo pipefail

HOOK_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HOOK_LIB_DIR/hook-lib.sh"

hook_lib_check_recursion
setup_env

RELEVANCE_TOP_N=$(get_setting "relevanceTopN" 3)  # Fewer for subagent context
MIN_RELEVANCE_SCORE=3

main() {
    is_enabled || exit 0

    local input=$(cat)
    local cwd=$(echo "$input" | jq -r '.cwd // "."' 2>/dev/null || echo ".")
    # SubagentStop provides the subagent's output
    local subagent_output=$(echo "$input" | jq -r '.output // ""' 2>/dev/null || echo "")

    [[ -z "$subagent_output" ]] && exit 0
    # Only score if output is substantial
    [[ ${#subagent_output} -lt 50 ]] && exit 0

    local project_root=$(find_project_root "$cwd")

    [[ -z "$GO_RECALL" || ! -x "$GO_RECALL" ]] && exit 0

    # Truncate long output for scoring (first 2000 chars)
    local query="${subagent_output:0:2000}"

    local result stderr_file
    stderr_file=$(mktemp)
    result=$(PROJECT_DIR="$project_root" LESSONS_BASE="$LESSONS_BASE" LESSONS_DEBUG="${LESSONS_DEBUG:-}" \
        timeout 2 \
        "$GO_RECALL" score-local "$query" \
            --top "$RELEVANCE_TOP_N" \
            --min-score "$MIN_RELEVANCE_SCORE" 2>"$stderr_file") || {
        rm -f "$stderr_file"
        exit 0
    }
    rm -f "$stderr_file"

    [[ -z "$result" ]] && exit 0
    [[ "$result" == *"No lessons found"* ]] && exit 0

    local context="RELEVANT LESSONS after subagent work:
$result

Cite [ID] when applying."

    local escaped=$(printf '%s' "$context" | jq -Rs .)
    cat << EOF
{"hookSpecificOutput":{"hookEventName":"SubagentStop","additionalContext":$escaped}}
EOF
}

main
```

**Step 2: Add to hooks-config.json**

Add `SubagentStop` event:
```json
"SubagentStop": [
  {
    "type": "command",
    "command": "bash {{HOOKS_DIR}}/subagent-stop-hook.sh",
    "timeout": 3000
  }
]
```

**Step 3: Test manually**

```bash
echo '{"cwd":"/tmp","output":"I found the git commit formatting function at src/utils.py line 45. It uses a simple string format."}' | bash plugins/claude-recall/hooks/scripts/subagent-stop-hook.sh
```

**Step 4: Commit**

```bash
git add plugins/claude-recall/hooks/scripts/subagent-stop-hook.sh adapters/claude-code/hooks-config.json
git commit -m "feat: add SubagentStop hook for lesson injection"
```

---

### Task 8: Session Deduplication

**Files:**
- Modify: `plugins/claude-recall/hooks/scripts/smart-inject-hook.sh`
- Modify: `plugins/claude-recall/hooks/scripts/subagent-stop-hook.sh`
- Modify: `plugins/claude-recall/hooks/scripts/inject-hook.sh` (clear dedup state on session start)
- Modify: `plugins/claude-recall/hooks/scripts/hook-lib.sh` (shared dedup functions)

**Step 1: Add dedup functions to hook-lib.sh**

```bash
# Session dedup state file
get_dedup_file() {
    local session_id="${CLAUDE_SESSION_ID:-unknown}"
    echo "${CLAUDE_RECALL_STATE:-$HOME/.local/state/claude-recall}/session-dedup-${session_id}.json"
}

# Get already-injected lesson IDs as space-separated string
get_injected_ids() {
    local dedup_file=$(get_dedup_file)
    [[ -f "$dedup_file" ]] && jq -r '.[]' "$dedup_file" 2>/dev/null | tr '\n' ' ' || echo ""
}

# Record lesson IDs as injected
record_injected() {
    local dedup_file=$(get_dedup_file)
    local ids=("$@")
    local existing="[]"
    [[ -f "$dedup_file" ]] && existing=$(cat "$dedup_file" 2>/dev/null || echo "[]")
    # Merge and deduplicate
    printf '%s\n' "${ids[@]}" | jq -R -s 'split("\n") | map(select(. != ""))' | \
        jq -s --argjson existing "$existing" '$existing + .[0] | unique' > "$dedup_file"
}

# Clear dedup state (called on SessionStart)
clear_dedup() {
    local dedup_file=$(get_dedup_file)
    rm -f "$dedup_file"
}
```

**Step 2: Use dedup in smart-inject-hook.sh**

After scoring, before injecting, filter out already-injected IDs:
```bash
# Filter out already-injected lessons
local injected=$(get_injected_ids)
if [[ -n "$injected" ]]; then
    # Use Go binary or jq to filter
    scored_lessons=$(echo "$scored_lessons" | grep -v -F "$injected" || echo "$scored_lessons")
fi

# Record newly injected IDs
local new_ids=$(echo "$scored_lessons" | grep -oP '\[([LS]\d{3})\]' | tr -d '[]')
[[ -n "$new_ids" ]] && record_injected $new_ids
```

**Step 3: Use dedup in subagent-stop-hook.sh**

Same pattern as step 2.

**Step 4: Clear dedup on SessionStart**

In `inject-hook.sh`, add near the top of `main()`:
```bash
clear_dedup
```

**Step 5: Commit**

```bash
git add plugins/claude-recall/hooks/scripts/hook-lib.sh plugins/claude-recall/hooks/scripts/smart-inject-hook.sh plugins/claude-recall/hooks/scripts/subagent-stop-hook.sh plugins/claude-recall/hooks/scripts/inject-hook.sh
git commit -m "feat: add session deduplication for lesson injection"
```

---

### Task 9: Update CLAUDE.md and Documentation

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/plans/2026-02-18-better-lesson-injection-design.md` (mark as implemented)

**Step 1: Update CLAUDE.md**

- Remove handoff references from hook flow diagram
- Update `How It Works` section to mention BM25 instead of Haiku
- Remove handoff hook entries from Quick Reference
- Update hook listing (remove deleted hooks, add SubagentStop)

**Step 2: Mark design as implemented**

Add `> Status: Implemented` at top of design doc.

**Step 3: Commit**

```bash
git add CLAUDE.md docs/plans/2026-02-18-better-lesson-injection-design.md
git commit -m "docs: update for BM25 scoring and handoff removal"
```

---

### Task 10: Integration Test - End to End

**Step 1: Manual integration test**

Verify the full flow works:
1. Start a new Claude Code session in a project with lessons
2. Verify SessionStart injects top lessons by stars
3. Type a substantive prompt - verify BM25-scored lessons inject
4. Type another prompt - verify different relevant lessons inject (dedup working)
5. Verify no handoff duty prompts appear
6. Verify stop hook still tracks citations

**Step 2: Run full test suite**

Run: `./run-tests.sh -v`
Expected: All PASS

**Step 3: Final commit if any fixes needed**

---

Plan complete and saved to `docs/plans/2026-02-18-better-lesson-injection-plan.md`. Two execution options:

**1. Subagent-Driven (this session)** - I dispatch fresh subagent per task, review between tasks, fast iteration

**2. Parallel Session (separate)** - Open new session with executing-plans, batch execution with checkpoints

Which approach?