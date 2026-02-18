#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Tests for BM25 local relevance scoring.

Run with: ./run-tests.sh tests/test_scoring.py -v
"""

import pytest
from datetime import date

from core.scoring import BM25Scorer, score_lessons_local
from core.models import Lesson, ScoredLesson


# =============================================================================
# Helpers
# =============================================================================


def _make_lesson(id, title, content, uses=5, velocity=3.0):
    """Create a Lesson with sensible defaults for testing."""
    return Lesson(
        id=id,
        title=title,
        content=content,
        uses=uses,
        velocity=velocity,
        learned=date(2025, 1, 1),
        last_used=date(2025, 6, 1),
        category="pattern",
        level="project",
    )


# =============================================================================
# Tokenization tests
# =============================================================================


class TestTokenization:
    """Test the BM25Scorer tokenizer."""

    def test_basic_tokenization(self):
        """Lowercase and split on whitespace."""
        scorer = BM25Scorer([])
        tokens = scorer.tokenize("Hello World Test")
        assert "hello" in tokens
        assert "world" in tokens
        assert "test" in tokens

    def test_punctuation_stripped(self):
        """Punctuation and special characters are split boundaries."""
        scorer = BM25Scorer([])
        tokens = scorer.tokenize("git-rebase, force-push! file.txt")
        assert "git" in tokens
        assert "rebase" in tokens
        assert "force" in tokens
        assert "push" in tokens
        assert "file" in tokens
        assert "txt" in tokens
        # No punctuation in tokens
        for t in tokens:
            assert t.isalnum(), f"Token '{t}' contains non-alphanumeric chars"

    def test_empty_string(self):
        """Empty string returns empty token list."""
        scorer = BM25Scorer([])
        assert scorer.tokenize("") == []

    def test_stop_words_removed(self):
        """Common stop words are filtered out."""
        scorer = BM25Scorer([])
        tokens = scorer.tokenize("the quick brown fox is a very good animal")
        assert "the" not in tokens
        assert "is" not in tokens
        assert "a" not in tokens
        # Content words survive
        assert "quick" in tokens
        assert "brown" in tokens
        assert "fox" in tokens

    def test_short_tokens_removed(self):
        """Tokens shorter than 2 characters are filtered."""
        scorer = BM25Scorer([])
        tokens = scorer.tokenize("I am a go to x y z person")
        # Single-char tokens removed
        for t in tokens:
            assert len(t) >= 2, f"Token '{t}' is too short"

    def test_numeric_tokens_kept(self):
        """Numeric tokens are preserved."""
        scorer = BM25Scorer([])
        tokens = scorer.tokenize("python 3 version 12")
        assert "python" in tokens
        assert "version" in tokens
        assert "12" in tokens


# =============================================================================
# BM25 scoring tests
# =============================================================================


class TestBM25Scoring:
    """Test BM25 scoring behavior."""

    def test_relevant_lesson_scores_higher(self):
        """A lesson matching the query scores higher than an unrelated one."""
        lessons = [
            _make_lesson("L001", "Git rebase workflow", "Always rebase before merging to keep history clean"),
            _make_lesson("L002", "Python venv setup", "Use python3 -m venv for virtual environments"),
        ]
        scorer = BM25Scorer(lessons)
        scores = scorer.score("git rebase merge")
        # L001 should score higher (matches git, rebase, merge-related)
        score_l001 = next(s for s in scores if s.lesson.id == "L001")
        score_l002 = next(s for s in scores if s.lesson.id == "L002")
        assert score_l001.score > score_l002.score

    def test_irrelevant_lesson_scores_zero(self):
        """A lesson with no query term overlap scores 0."""
        lessons = [
            _make_lesson("L001", "Docker networking", "Configure bridge networks for containers"),
        ]
        scorer = BM25Scorer(lessons)
        scores = scorer.score("python asyncio coroutines")
        assert scores[0].score == 0

    def test_ranking_multiple_lessons(self):
        """Lessons rank by relevance to the query."""
        lessons = [
            _make_lesson("L001", "TypeScript generics", "Use generics for type-safe collections"),
            _make_lesson("L002", "TypeScript testing", "Use jest for TypeScript unit tests"),
            _make_lesson("L003", "Python testing", "Use pytest for Python unit tests"),
        ]
        scorer = BM25Scorer(lessons)
        scores = scorer.score("TypeScript testing jest")
        # L002 should be top (matches typescript + testing + jest)
        assert scores[0].lesson.id == "L002"
        # L001 and L003 each match partially
        # L001 matches typescript, L003 matches testing
        ids_after = [s.lesson.id for s in scores[1:]]
        assert "L001" in ids_after
        assert "L003" in ids_after

    def test_empty_query_returns_all_zero(self):
        """An empty query gives all lessons score 0."""
        lessons = [
            _make_lesson("L001", "Some lesson", "Some content"),
            _make_lesson("L002", "Another lesson", "Other content"),
        ]
        scorer = BM25Scorer(lessons)
        scores = scorer.score("")
        for s in scores:
            assert s.score == 0

    def test_empty_lessons_returns_empty(self):
        """No lessons means empty results."""
        scorer = BM25Scorer([])
        scores = scorer.score("anything")
        assert scores == []

    def test_scores_are_integers_0_to_10(self):
        """All scores are integers in the 0-10 range."""
        lessons = [
            _make_lesson("L001", "Git workflow", "Use feature branches and pull requests"),
            _make_lesson("L002", "Git commits", "Write clear commit messages with conventional commits"),
            _make_lesson("L003", "Unrelated docker", "Docker compose for local development"),
        ]
        scorer = BM25Scorer(lessons)
        scores = scorer.score("git commit messages branches")
        for s in scores:
            assert isinstance(s.score, int)
            assert 0 <= s.score <= 10

    def test_title_and_content_both_searched(self):
        """Matches in either title or content contribute to score."""
        lessons = [
            _make_lesson("L001", "Keyword in title: banana", "Unrelated content about clouds"),
            _make_lesson("L002", "Unrelated title about clouds", "The banana is a useful keyword here"),
        ]
        scorer = BM25Scorer(lessons)
        scores = scorer.score("banana")
        # Both should score > 0 since "banana" appears in each
        for s in scores:
            assert s.score > 0

    def test_returns_scored_lesson_objects(self):
        """Results are ScoredLesson dataclass instances."""
        lessons = [_make_lesson("L001", "Test", "Content")]
        scorer = BM25Scorer(lessons)
        scores = scorer.score("test")
        assert len(scores) == 1
        assert isinstance(scores[0], ScoredLesson)
        assert scores[0].lesson is lessons[0]


# =============================================================================
# Tiebreaking tests
# =============================================================================


class TestTiebreaking:
    """Test that ties in BM25 score break by uses descending."""

    def test_tiebreak_by_uses(self):
        """When two lessons have the same BM25 score, higher uses wins."""
        # Identical titles/content so BM25 scores are equal
        lessons = [
            _make_lesson("L001", "Python testing patterns", "Use pytest fixtures", uses=10),
            _make_lesson("L002", "Python testing patterns", "Use pytest fixtures", uses=50),
        ]
        scorer = BM25Scorer(lessons)
        scores = scorer.score("python testing pytest fixtures")
        # Both should have the same score
        assert scores[0].score == scores[1].score
        # But L002 (50 uses) should come first due to tiebreaking
        assert scores[0].lesson.id == "L002"
        assert scores[1].lesson.id == "L001"


# =============================================================================
# score_lessons_local() tests
# =============================================================================


class TestScoreLessonsLocal:
    """Test the convenience wrapper function."""

    def test_top_n_filtering(self):
        """Only returns top N results."""
        lessons = [
            _make_lesson(f"L{i:03d}", f"Lesson {i}", f"Content about topic {i}")
            for i in range(1, 11)
        ]
        results = score_lessons_local(lessons, "lesson content topic", top_n=3)
        assert len(results) <= 3

    def test_min_score_filtering(self):
        """Filters out results below min_score."""
        lessons = [
            _make_lesson("L001", "Git rebase", "Rebase workflow for clean history"),
            _make_lesson("L002", "Unrelated docker", "Docker compose networking bridge"),
        ]
        results = score_lessons_local(lessons, "git rebase", min_score=1)
        # L002 should be filtered out (no matching terms, score=0)
        ids = [r.lesson.id for r in results]
        assert "L002" not in ids

    def test_sorted_descending(self):
        """Results are sorted by score descending."""
        lessons = [
            _make_lesson("L001", "Git rebase workflow", "Always rebase before merging"),
            _make_lesson("L002", "Git commit messages", "Write conventional commits for git"),
            _make_lesson("L003", "Unrelated python", "Python virtual environments"),
        ]
        results = score_lessons_local(lessons, "git rebase merge commit", top_n=10)
        for i in range(len(results) - 1):
            assert results[i].score >= results[i + 1].score

    def test_empty_lessons(self):
        """Empty lesson list returns empty results."""
        results = score_lessons_local([], "anything", top_n=5)
        assert results == []

    def test_empty_query(self):
        """Empty query returns empty results (all scores 0, filtered by min_score=1 default or all zero)."""
        lessons = [_make_lesson("L001", "Test", "Content")]
        results = score_lessons_local(lessons, "", top_n=5, min_score=1)
        assert results == []

    def test_returns_scored_lessons(self):
        """Results are ScoredLesson instances."""
        lessons = [_make_lesson("L001", "Git workflow", "Feature branches")]
        results = score_lessons_local(lessons, "git workflow", top_n=5)
        for r in results:
            assert isinstance(r, ScoredLesson)
