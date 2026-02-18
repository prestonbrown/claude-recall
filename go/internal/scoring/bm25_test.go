package scoring

import (
	"testing"

	"github.com/pbrown/claude-recall/internal/models"
)

func TestTokenize_Basic(t *testing.T) {
	tokens := Tokenize("Hello World testing")
	expected := []string{"hello", "world", "testing"}
	if len(tokens) != len(expected) {
		t.Fatalf("expected %d tokens, got %d: %v", len(expected), len(tokens), tokens)
	}
	for i, tok := range tokens {
		if tok != expected[i] {
			t.Errorf("token %d: expected %q, got %q", i, expected[i], tok)
		}
	}
}

func TestTokenize_StopWords(t *testing.T) {
	tokens := Tokenize("the quick and the slow")
	// "the", "and" are stop words; "quick" and "slow" remain
	expected := []string{"quick", "slow"}
	if len(tokens) != len(expected) {
		t.Fatalf("expected %d tokens, got %d: %v", len(expected), len(tokens), tokens)
	}
	for i, tok := range tokens {
		if tok != expected[i] {
			t.Errorf("token %d: expected %q, got %q", i, expected[i], tok)
		}
	}
}

func TestTokenize_Punctuation(t *testing.T) {
	tokens := Tokenize("git-commit: use --no-verify flag!")
	// splits on non-alphanumeric, removes short tokens and stop words
	expected := []string{"git", "commit", "use", "verify", "flag"}
	if len(tokens) != len(expected) {
		t.Fatalf("expected %d tokens, got %d: %v", len(expected), len(tokens), tokens)
	}
	for i, tok := range tokens {
		if tok != expected[i] {
			t.Errorf("token %d: expected %q, got %q", i, expected[i], tok)
		}
	}
}

func TestTokenize_Empty(t *testing.T) {
	tokens := Tokenize("")
	if len(tokens) != 0 {
		t.Errorf("expected empty tokens, got %v", tokens)
	}
}

func TestTokenize_MinLength(t *testing.T) {
	tokens := Tokenize("I a go run it")
	// "go" and "run" pass length >= 2; "I", "a" are too short; "it" is a stop word
	expected := []string{"go", "run"}
	if len(tokens) != len(expected) {
		t.Fatalf("expected %d tokens, got %d: %v", len(expected), len(tokens), tokens)
	}
}

func makeLessons() []*models.Lesson {
	return []*models.Lesson{
		{ID: "L001", Title: "Git commit hooks", Content: "Always run pre-commit hooks before pushing code", Uses: 10},
		{ID: "L002", Title: "Python virtual environments", Content: "Use venv for Python project isolation", Uses: 5},
		{ID: "L003", Title: "Docker container networking", Content: "Containers communicate via bridge networks by default", Uses: 3},
	}
}

func TestScore_RelevantVsIrrelevant(t *testing.T) {
	lessons := makeLessons()
	scorer := NewBM25Scorer(lessons)

	results := scorer.Score("git commit hooks pre-commit")
	if len(results) == 0 {
		t.Fatal("expected results")
	}

	// L001 should rank first (most relevant to git commit query)
	if results[0].Lesson.ID != "L001" {
		t.Errorf("expected L001 first, got %s", results[0].Lesson.ID)
	}
	// L001 should have highest score
	if results[0].Score < results[1].Score {
		t.Errorf("L001 score (%d) should be >= L002 score (%d)", results[0].Score, results[1].Score)
	}
}

func TestScore_Ranking(t *testing.T) {
	lessons := makeLessons()
	scorer := NewBM25Scorer(lessons)

	results := scorer.Score("python virtual environment venv")
	if len(results) == 0 {
		t.Fatal("expected results")
	}

	// L002 should rank first
	if results[0].Lesson.ID != "L002" {
		t.Errorf("expected L002 first, got %s", results[0].Lesson.ID)
	}
}

func TestScore_EmptyQuery(t *testing.T) {
	lessons := makeLessons()
	scorer := NewBM25Scorer(lessons)

	results := scorer.Score("")
	// All scores should be 0
	for _, r := range results {
		if r.Score != 0 {
			t.Errorf("expected score 0 for empty query, got %d for %s", r.Score, r.Lesson.ID)
		}
	}
}

func TestScore_EmptyLessons(t *testing.T) {
	scorer := NewBM25Scorer(nil)
	results := scorer.Score("anything")
	if len(results) != 0 {
		t.Errorf("expected no results, got %d", len(results))
	}
}

func TestScore_Normalization(t *testing.T) {
	lessons := makeLessons()
	scorer := NewBM25Scorer(lessons)

	results := scorer.Score("git commit hooks")
	for _, r := range results {
		if r.Score < 0 || r.Score > 10 {
			t.Errorf("score %d out of 0-10 range for %s", r.Score, r.Lesson.ID)
		}
	}
	// The top result should be normalized to 10
	if results[0].Score != 10 {
		t.Errorf("expected top score to be 10, got %d", results[0].Score)
	}
}

func TestScore_TiebreakByUses(t *testing.T) {
	// Two lessons with identical content but different uses
	lessons := []*models.Lesson{
		{ID: "L001", Title: "Testing patterns", Content: "unit test patterns", Uses: 5},
		{ID: "L002", Title: "Testing patterns", Content: "unit test patterns", Uses: 20},
	}
	scorer := NewBM25Scorer(lessons)

	results := scorer.Score("testing patterns unit")
	// Both should have same score (10), but L002 should come first (more uses)
	if len(results) < 2 {
		t.Fatal("expected 2 results")
	}
	if results[0].Lesson.ID != "L002" {
		t.Errorf("expected L002 first (higher uses), got %s", results[0].Lesson.ID)
	}
	if results[0].Score != results[1].Score {
		t.Errorf("expected same scores, got %d and %d", results[0].Score, results[1].Score)
	}
}
