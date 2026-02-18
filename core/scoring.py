#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
BM25 local relevance scoring for lessons.

Provides fast, zero-dependency relevance scoring to replace Haiku API calls.
Designed for <50ms latency with ~100 lessons.
"""

import math
import re
from typing import List

from core.models import Lesson, ScoredLesson


# Stop words - common English words that add noise to scoring
STOP_WORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "not", "no", "nor",
    "in", "on", "at", "to", "for", "of", "with", "by", "from",
    "is", "am", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did",
    "will", "would", "shall", "should", "may", "might", "can", "could",
    "this", "that", "these", "those",
    "it", "its", "he", "she", "we", "they", "you", "me", "him", "her", "us", "them",
    "my", "your", "his", "our", "their",
    "if", "then", "else", "when", "where", "how", "what", "which", "who", "whom",
    "so", "as", "up", "out", "about", "into", "over", "after", "before",
    "very", "just", "also", "more", "most", "some", "any", "all", "each", "every",
})

# Regex to split on non-alphanumeric characters
_SPLIT_RE = re.compile(r"[^a-z0-9]+")


class BM25Scorer:
    """BM25 relevance scorer for lessons.

    Builds an inverted index from lesson title+content, then scores queries
    using standard BM25 with k1=1.5, b=0.75.

    Scores are normalized to 0-10 integer scale. Ties break by uses descending.
    """

    def __init__(self, lessons: List[Lesson], k1: float = 1.5, b: float = 0.75):
        self.lessons = lessons
        self.k1 = k1
        self.b = b

        # Build document representations
        self._doc_tokens: List[List[str]] = []
        self._doc_lengths: List[int] = []
        self._avg_dl: float = 0.0
        # term -> document frequency (number of docs containing term)
        self._df: dict = {}
        self._n = len(lessons)

        if self._n == 0:
            return

        # Tokenize each lesson (title + content)
        for lesson in lessons:
            text = f"{lesson.title} {lesson.content}"
            tokens = self.tokenize(text)
            self._doc_tokens.append(tokens)
            self._doc_lengths.append(len(tokens))

        self._avg_dl = sum(self._doc_lengths) / self._n if self._n > 0 else 0.0

        # Build document frequency counts
        for tokens in self._doc_tokens:
            seen = set(tokens)
            for term in seen:
                self._df[term] = self._df.get(term, 0) + 1

    @staticmethod
    def tokenize(text: str) -> List[str]:
        """Tokenize text: lowercase, split on non-alphanumeric, remove stop words, min length 2."""
        if not text:
            return []
        lowered = text.lower()
        parts = _SPLIT_RE.split(lowered)
        return [t for t in parts if t and len(t) >= 2 and t not in STOP_WORDS]

    def _idf(self, term: str) -> float:
        """Compute IDF for a term using the standard BM25 formula."""
        df = self._df.get(term, 0)
        if df == 0:
            return 0.0
        # Standard BM25 IDF: log((N - df + 0.5) / (df + 0.5) + 1)
        return math.log((self._n - df + 0.5) / (df + 0.5) + 1.0)

    def _score_doc(self, doc_idx: int, query_terms: List[str]) -> float:
        """Compute raw BM25 score for a single document against query terms."""
        tokens = self._doc_tokens[doc_idx]
        dl = self._doc_lengths[doc_idx]

        if dl == 0:
            return 0.0

        # Build term frequency map for this document
        tf_map: dict = {}
        for t in tokens:
            tf_map[t] = tf_map.get(t, 0) + 1

        score = 0.0
        for term in query_terms:
            tf = tf_map.get(term, 0)
            if tf == 0:
                continue
            idf = self._idf(term)
            # BM25 term frequency saturation
            numerator = tf * (self.k1 + 1.0)
            denominator = tf + self.k1 * (1.0 - self.b + self.b * dl / self._avg_dl)
            score += idf * numerator / denominator

        return score

    def score(self, query: str) -> List[ScoredLesson]:
        """Score all lessons against a query.

        Returns list of ScoredLesson sorted by score descending,
        with ties broken by uses descending.
        """
        if not self.lessons:
            return []

        query_terms = self.tokenize(query)

        # Compute raw BM25 scores
        raw_scores: List[float] = []
        for i in range(self._n):
            if not query_terms:
                raw_scores.append(0.0)
            else:
                raw_scores.append(self._score_doc(i, query_terms))

        # Normalize to 0-10 integer scale
        max_raw = max(raw_scores) if raw_scores else 0.0
        normalized: List[int] = []
        for raw in raw_scores:
            if max_raw <= 0.0:
                normalized.append(0)
            else:
                # Scale to 0-10 and round
                normalized.append(round(10.0 * raw / max_raw))

        # Build results
        results = [
            ScoredLesson(lesson=self.lessons[i], score=normalized[i])
            for i in range(self._n)
        ]

        # Sort by score descending, tiebreak by uses descending
        results.sort(key=lambda s: (s.score, s.lesson.uses), reverse=True)

        return results


def score_lessons_local(
    lessons: List[Lesson],
    query: str,
    top_n: int = 5,
    min_score: int = 0,
) -> List[ScoredLesson]:
    """Score lessons locally using BM25 and return top results.

    Args:
        lessons: List of lessons to score
        query: Query text to score against
        top_n: Maximum number of results to return
        min_score: Minimum score threshold (0-10)

    Returns:
        List of ScoredLesson sorted by score descending, filtered and capped.
    """
    if not lessons:
        return []

    scorer = BM25Scorer(lessons)
    results = scorer.score(query)

    # Filter by min_score
    results = [r for r in results if r.score >= min_score]

    # Return top N
    return results[:top_n]
