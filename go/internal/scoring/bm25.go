package scoring

import (
	"math"
	"regexp"
	"sort"
	"strings"

	"github.com/pbrown/claude-recall/internal/models"
)

// ScoredLesson represents a lesson with a relevance score (0-10)
type ScoredLesson struct {
	Lesson *models.Lesson
	Score  int
}

// stopWords are common English words that add noise to scoring
var stopWords = map[string]bool{
	"a": true, "an": true, "the": true, "and": true, "or": true, "but": true, "not": true, "no": true, "nor": true,
	"in": true, "on": true, "at": true, "to": true, "for": true, "of": true, "with": true, "by": true, "from": true,
	"is": true, "am": true, "are": true, "was": true, "were": true, "be": true, "been": true, "being": true,
	"have": true, "has": true, "had": true, "do": true, "does": true, "did": true,
	"will": true, "would": true, "shall": true, "should": true, "may": true, "might": true, "can": true, "could": true,
	"this": true, "that": true, "these": true, "those": true,
	"it": true, "its": true, "he": true, "she": true, "we": true, "they": true, "you": true, "me": true, "him": true, "her": true, "us": true, "them": true,
	"my": true, "your": true, "his": true, "our": true, "their": true,
	"if": true, "then": true, "else": true, "when": true, "where": true, "how": true, "what": true, "which": true, "who": true, "whom": true,
	"so": true, "as": true, "up": true, "out": true, "about": true, "into": true, "over": true, "after": true, "before": true,
	"very": true, "just": true, "also": true, "more": true, "most": true, "some": true, "any": true, "all": true, "each": true, "every": true,
}

// splitRe splits on non-alphanumeric characters
var splitRe = regexp.MustCompile(`[^a-z0-9]+`)

// BM25Scorer scores lessons against queries using BM25
type BM25Scorer struct {
	lessons   []*models.Lesson
	k1        float64
	b         float64
	docTokens [][]string
	docLens   []int
	avgDL     float64
	df        map[string]int // term -> document frequency
	n         int
}

// NewBM25Scorer creates a scorer from a set of lessons
func NewBM25Scorer(lessons []*models.Lesson) *BM25Scorer {
	s := &BM25Scorer{
		lessons: lessons,
		k1:      1.5,
		b:       0.75,
		df:      make(map[string]int),
		n:       len(lessons),
	}

	if s.n == 0 {
		return s
	}

	// Tokenize each lesson (title + content)
	totalLen := 0
	for _, l := range lessons {
		text := l.Title + " " + l.Content
		tokens := Tokenize(text)
		s.docTokens = append(s.docTokens, tokens)
		s.docLens = append(s.docLens, len(tokens))
		totalLen += len(tokens)
	}

	s.avgDL = float64(totalLen) / float64(s.n)

	// Build document frequency counts
	for _, tokens := range s.docTokens {
		seen := make(map[string]bool)
		for _, t := range tokens {
			seen[t] = true
		}
		for term := range seen {
			s.df[term]++
		}
	}

	return s
}

// Tokenize converts text to tokens: lowercase, split on non-alphanumeric, remove stop words, min length 2
func Tokenize(text string) []string {
	if text == "" {
		return nil
	}
	lowered := strings.ToLower(text)
	parts := splitRe.Split(lowered, -1)

	var tokens []string
	for _, t := range parts {
		if len(t) >= 2 && !stopWords[t] {
			tokens = append(tokens, t)
		}
	}
	return tokens
}

// idf computes IDF for a term using standard BM25 formula
func (s *BM25Scorer) idf(term string) float64 {
	df := s.df[term]
	if df == 0 {
		return 0.0
	}
	// log((N - df + 0.5) / (df + 0.5) + 1)
	return math.Log((float64(s.n-df)+0.5)/(float64(df)+0.5) + 1.0)
}

// scoreDoc computes raw BM25 score for a single document
func (s *BM25Scorer) scoreDoc(docIdx int, queryTerms []string) float64 {
	tokens := s.docTokens[docIdx]
	dl := s.docLens[docIdx]

	if dl == 0 {
		return 0.0
	}

	// Build term frequency map
	tfMap := make(map[string]int)
	for _, t := range tokens {
		tfMap[t]++
	}

	score := 0.0
	for _, term := range queryTerms {
		tf := tfMap[term]
		if tf == 0 {
			continue
		}
		idf := s.idf(term)
		numerator := float64(tf) * (s.k1 + 1.0)
		denominator := float64(tf) + s.k1*(1.0-s.b+s.b*float64(dl)/s.avgDL)
		score += idf * numerator / denominator
	}

	return score
}

// Score scores all lessons against a query, returning sorted results (0-10 scale)
func (s *BM25Scorer) Score(query string) []ScoredLesson {
	if len(s.lessons) == 0 {
		return nil
	}

	queryTerms := Tokenize(query)

	// Compute raw BM25 scores
	rawScores := make([]float64, s.n)
	for i := 0; i < s.n; i++ {
		if len(queryTerms) == 0 {
			rawScores[i] = 0.0
		} else {
			rawScores[i] = s.scoreDoc(i, queryTerms)
		}
	}

	// Find max for normalization
	maxRaw := 0.0
	for _, r := range rawScores {
		if r > maxRaw {
			maxRaw = r
		}
	}

	// Normalize to 0-10 integer scale
	results := make([]ScoredLesson, s.n)
	for i := 0; i < s.n; i++ {
		normalized := 0
		if maxRaw > 0.0 {
			normalized = int(math.Round(10.0 * rawScores[i] / maxRaw))
		}
		results[i] = ScoredLesson{
			Lesson: s.lessons[i],
			Score:  normalized,
		}
	}

	// Sort by score descending, tiebreak by uses descending
	sort.Slice(results, func(i, j int) bool {
		if results[i].Score != results[j].Score {
			return results[i].Score > results[j].Score
		}
		return results[i].Lesson.Uses > results[j].Lesson.Uses
	})

	return results
}
