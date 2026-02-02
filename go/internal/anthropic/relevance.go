package anthropic

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/pbrown/claude-recall/internal/models"
)

const (
	// RelevanceCacheTTLDays is the cache expiration time
	RelevanceCacheTTLDays = 7

	// RelevanceCacheSimilarityThreshold for fuzzy matching
	RelevanceCacheSimilarityThreshold = 0.7

	// MaxQueryLength to prevent huge prompts
	MaxQueryLength = 5000
)

// ScoredLesson represents a lesson with a relevance score
type ScoredLesson struct {
	Lesson *models.Lesson
	Score  int // 0-10
}

// RelevanceResult contains the scored lessons
type RelevanceResult struct {
	ScoredLessons []ScoredLesson
	QueryText     string
	CacheHit      bool
	Error         string
}

// cacheEntry stores cached scores
type cacheEntry struct {
	NormalizedQuery string         `json:"normalized_query"`
	Scores          map[string]int `json:"scores"`
	Timestamp       float64        `json:"timestamp"`
}

// relevanceCache stores all cache entries
type relevanceCache struct {
	Entries map[string]cacheEntry `json:"entries"`
}

// ScoreRelevance scores lessons by relevance to a query
func ScoreRelevance(lessons []*models.Lesson, query string, stateDir string, timeout time.Duration) (*RelevanceResult, error) {
	if len(lessons) == 0 {
		return &RelevanceResult{
			ScoredLessons: []ScoredLesson{},
			QueryText:     query,
		}, nil
	}

	// Truncate query if too long
	if len(query) > MaxQueryLength {
		query = query[:MaxQueryLength]
	}

	// Load cache
	cachePath := filepath.Join(stateDir, "relevance-cache.json")
	cache := loadCache(cachePath)

	// Check cache
	queryHash := hashQuery(query)
	normalizedQuery := normalizeQuery(query)

	// Check exact match
	if entry, ok := cache.Entries[queryHash]; ok {
		if isEntryValid(entry) {
			return buildResultFromCache(lessons, entry.Scores, query, true), nil
		}
	}

	// Check similarity match
	for _, entry := range cache.Entries {
		if isEntryValid(entry) {
			if jaccardSimilarity(normalizedQuery, entry.NormalizedQuery) >= RelevanceCacheSimilarityThreshold {
				return buildResultFromCache(lessons, entry.Scores, query, true), nil
			}
		}
	}

	// Cache miss - call API
	client, err := NewClient()
	if err != nil {
		return &RelevanceResult{
			ScoredLessons: []ScoredLesson{},
			QueryText:     query,
			Error:         err.Error(),
		}, nil
	}

	prompt := buildRelevancePrompt(lessons, query)
	response, err := client.CompleteWithTimeout(prompt, timeout)
	if err != nil {
		return &RelevanceResult{
			ScoredLessons: []ScoredLesson{},
			QueryText:     query,
			Error:         err.Error(),
		}, nil
	}

	// Parse scores from response
	scores := parseScores(response)

	// Update cache
	cache.Entries[queryHash] = cacheEntry{
		NormalizedQuery: normalizedQuery,
		Scores:          scores,
		Timestamp:       float64(time.Now().Unix()),
	}
	saveCache(cachePath, cache)

	return buildResultFromCache(lessons, scores, query, false), nil
}

// buildRelevancePrompt creates the prompt for Haiku
func buildRelevancePrompt(lessons []*models.Lesson, query string) string {
	var sb strings.Builder

	sb.WriteString("Score each lesson's relevance (0-10) to this query. 10 = highly relevant, 0 = not relevant.\n\n")
	sb.WriteString(fmt.Sprintf("Query: %s\n\n", query))
	sb.WriteString("Lessons:\n")

	for _, l := range lessons {
		sb.WriteString(fmt.Sprintf("[%s] %s: %s\n", l.ID, l.Title, l.Content))
	}

	sb.WriteString("\nOutput ONLY lines in format: ID: SCORE\n")
	sb.WriteString("Example:\n")
	sb.WriteString("L001: 8\n")
	sb.WriteString("S002: 3\n\n")
	sb.WriteString("No explanations, just ID: SCORE lines.")

	return sb.String()
}

// parseScores extracts scores from the API response
func parseScores(response string) map[string]int {
	scores := make(map[string]int)
	pattern := regexp.MustCompile(`^\[?([LS]\d{3})\]?:\s*(\d+)`)

	for _, line := range strings.Split(response, "\n") {
		match := pattern.FindStringSubmatch(strings.TrimSpace(line))
		if len(match) >= 3 {
			id := match[1]
			score, err := strconv.Atoi(match[2])
			if err == nil {
				// Clamp to 0-10
				if score < 0 {
					score = 0
				}
				if score > 10 {
					score = 10
				}
				scores[id] = score
			}
		}
	}

	return scores
}

// buildResultFromCache creates a RelevanceResult from cached scores
func buildResultFromCache(lessons []*models.Lesson, scores map[string]int, query string, cacheHit bool) *RelevanceResult {
	var scored []ScoredLesson

	for _, l := range lessons {
		score := 0
		if s, ok := scores[l.ID]; ok {
			score = s
		}
		scored = append(scored, ScoredLesson{
			Lesson: l,
			Score:  score,
		})
	}

	// Sort by score descending, then by uses descending
	sort.Slice(scored, func(i, j int) bool {
		if scored[i].Score != scored[j].Score {
			return scored[i].Score > scored[j].Score
		}
		return scored[i].Lesson.Uses > scored[j].Lesson.Uses
	})

	return &RelevanceResult{
		ScoredLessons: scored,
		QueryText:     query,
		CacheHit:      cacheHit,
	}
}

// Cache helpers

func loadCache(path string) *relevanceCache {
	cache := &relevanceCache{
		Entries: make(map[string]cacheEntry),
	}

	data, err := os.ReadFile(path)
	if err != nil {
		return cache
	}

	json.Unmarshal(data, cache)
	if cache.Entries == nil {
		cache.Entries = make(map[string]cacheEntry)
	}

	return cache
}

func saveCache(path string, cache *relevanceCache) {
	// Ensure directory exists
	os.MkdirAll(filepath.Dir(path), 0755)

	// Evict expired entries
	cutoff := float64(time.Now().AddDate(0, 0, -RelevanceCacheTTLDays).Unix())
	for k, v := range cache.Entries {
		if v.Timestamp < cutoff {
			delete(cache.Entries, k)
		}
	}

	data, err := json.MarshalIndent(cache, "", "  ")
	if err != nil {
		return
	}

	os.WriteFile(path, data, 0644)
}

func isEntryValid(entry cacheEntry) bool {
	cutoff := float64(time.Now().AddDate(0, 0, -RelevanceCacheTTLDays).Unix())
	return entry.Timestamp >= cutoff
}

// Query normalization helpers

func normalizeQuery(query string) string {
	// Lowercase
	query = strings.ToLower(query)

	// Remove punctuation (keep alphanumeric and spaces)
	var sb strings.Builder
	for _, r := range query {
		if (r >= 'a' && r <= 'z') || (r >= '0' && r <= '9') || r == ' ' {
			sb.WriteRune(r)
		}
	}
	query = sb.String()

	// Split into words, sort, rejoin
	words := strings.Fields(query)
	sort.Strings(words)

	return strings.Join(words, " ")
}

func hashQuery(query string) string {
	normalized := normalizeQuery(query)
	hash := sha256.Sum256([]byte(normalized))
	return hex.EncodeToString(hash[:])[:16]
}

func jaccardSimilarity(a, b string) float64 {
	wordsA := make(map[string]bool)
	for _, w := range strings.Fields(a) {
		wordsA[w] = true
	}

	wordsB := make(map[string]bool)
	for _, w := range strings.Fields(b) {
		wordsB[w] = true
	}

	// Calculate intersection
	intersection := 0
	for w := range wordsA {
		if wordsB[w] {
			intersection++
		}
	}

	// Calculate union
	union := make(map[string]bool)
	for w := range wordsA {
		union[w] = true
	}
	for w := range wordsB {
		union[w] = true
	}

	if len(union) == 0 {
		return 0
	}

	return float64(intersection) / float64(len(union))
}
