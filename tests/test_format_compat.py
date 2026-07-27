#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Cross-implementation compatibility for the LESSONS.md on-disk format.

The Go CLI owns writes in normal operation; the Python manager and the
OpenCode adapter read the same files. When the stats
split moved Uses/Velocity/Last into `.claude-recall/stats.json` and dropped
the inline rating from headers, only the Go parser learned the new shape.

These tests pin both shapes for every Python reader, so a file written by
either implementation is readable by the other.

Post-split (current):  ### [L001] Title
                       - **Learned**: 2026-01-01 | **Category**: pattern
Pre-split (legacy):    ### [L001] [***--|****-] Title
                       - **Uses**: 12 | **Velocity**: 3.6 | **Learned**: ... | **Last**: ... | **Category**: pattern
"""

import json
from datetime import date
from pathlib import Path

import pytest

CURRENT = """# LESSONS.md - Project Level

## Active Lessons

### [L001] Delimiter conflicts
- **Learned**: 2025-12-27 | **Category**: pattern | **Type**: informational
> Watch out for delimiter collisions.

### [L002] Two-phase file updates
- **Learned**: 2026-01-02 | **Category**: gotcha
> Collect first, then apply.
"""

LEGACY = """# LESSONS.md - Project Level

## Active Lessons

### [L001] [***--|****-] Delimiter conflicts
- **Uses**: 12 | **Velocity**: 3.67 | **Learned**: 2025-12-27 | **Last**: 2026-07-26 | **Category**: pattern | **Type**: informational
> Watch out for delimiter collisions.

### [L002] [**---|***--] Two-phase file updates
- **Uses**: 5 | **Velocity**: 1.01 | **Learned**: 2026-01-02 | **Last**: 2026-02-21 | **Category**: gotcha
> Collect first, then apply.
"""

STATS = {
    "L001": {"uses": 12, "velocity": 3.67, "last": "2026-07-26"},
    "L002": {"uses": 5, "velocity": 1.01, "last": "2026-02-21"},
}


def write_store(directory: Path, markdown: str, stats: dict | None = None) -> Path:
    """Write a LESSONS.md (and optional sidecar) into directory."""
    directory.mkdir(parents=True, exist_ok=True)
    lessons_file = directory / "LESSONS.md"
    lessons_file.write_text(markdown)
    if stats is not None:
        (directory / "stats.json").write_text(json.dumps(stats))
    return lessons_file


# =============================================================================
# core/parsing.py - parse_lesson
# =============================================================================


class TestParseLesson:
    """The shared markdown->Lesson parser used by the manager."""

    def test_parses_current_format(self):
        from core.parsing import parse_lesson

        result = parse_lesson(CURRENT.split("\n"), 4, "project")

        assert result is not None, "current-format lesson must parse"
        lesson, _ = result
        assert lesson.id == "L001"
        assert lesson.title == "Delimiter conflicts"
        assert lesson.category == "pattern"
        assert lesson.learned == date(2025, 12, 27)
        assert lesson.content == "Watch out for delimiter collisions."

    def test_current_format_defaults_volatile_fields_to_zero(self):
        """Uses/Velocity/Last are absent from the file; the sidecar supplies them."""
        from core.parsing import parse_lesson

        lesson, _ = parse_lesson(CURRENT.split("\n"), 4, "project")

        assert lesson.uses == 0
        assert lesson.velocity == 0.0

    def test_still_parses_legacy_format(self):
        from core.parsing import parse_lesson

        lesson, _ = parse_lesson(LEGACY.split("\n"), 4, "project")

        assert lesson.id == "L001"
        assert lesson.title == "Delimiter conflicts"
        assert lesson.uses == 12
        assert lesson.velocity == pytest.approx(3.67)
        assert lesson.last_used == date(2026, 7, 26)

    def test_rejects_non_lesson_block(self):
        """A header without a valid metadata line is not a lesson."""
        from core.parsing import parse_lesson

        lines = ["### [L001] Title", "not a metadata line", "> content"]
        assert parse_lesson(lines, 0, "project") is None


# =============================================================================
# Stats sidecar
# =============================================================================


class TestStatsSidecar:
    """Volatile counters load from stats.json beside LESSONS.md."""

    def test_stats_path_sits_beside_lessons_file(self):
        from core.parsing import stats_path

        assert stats_path(Path("/x/.claude-recall/LESSONS.md")) == Path(
            "/x/.claude-recall/stats.json"
        )

    def test_missing_sidecar_is_not_an_error(self, tmp_path):
        from core.parsing import load_stats

        assert load_stats(tmp_path / "stats.json") == {}

    def test_corrupt_sidecar_is_not_an_error(self, tmp_path):
        from core.parsing import load_stats

        bad = tmp_path / "stats.json"
        bad.write_text("{not json")
        assert load_stats(bad) == {}

    def test_apply_overlays_counters(self):
        from core.parsing import apply_stats, parse_lesson

        lesson, _ = parse_lesson(CURRENT.split("\n"), 4, "project")
        apply_stats([lesson], STATS)

        assert lesson.uses == 12
        assert lesson.velocity == pytest.approx(3.67)
        assert lesson.last_used == date(2026, 7, 26)

    def test_apply_leaves_lessons_absent_from_sidecar_alone(self):
        """A half-migrated store keeps whatever the markdown supplied."""
        from core.parsing import apply_stats, parse_lesson

        lesson, _ = parse_lesson(LEGACY.split("\n"), 4, "project")
        apply_stats([lesson], {"L999": {"uses": 1, "velocity": 1.0, "last": "2026-01-01"}})

        assert lesson.uses == 12, "inline value must survive when sidecar lacks the ID"


# =============================================================================
# core/lessons.py - manager read/write round trip
# =============================================================================


class TestManagerRoundTrip:
    """The manager must not write a file the Go CLI would have to re-migrate."""

    def _manager(self, tmp_path, markdown, stats):
        from core.manager import LessonsManager

        project = tmp_path / "proj"
        write_store(project / ".claude-recall", markdown, stats)
        base = tmp_path / "base"
        base.mkdir()
        return LessonsManager(lessons_base=base, project_root=project), project

    def test_reads_current_format_and_sidecar(self, tmp_path):
        manager, _ = self._manager(tmp_path, CURRENT, STATS)

        lessons = manager.list_lessons()

        by_id = {l.id: l for l in lessons}
        assert "L001" in by_id, "current format must parse"
        assert by_id["L001"].uses == 12, "counters must come from the sidecar"

    def test_write_emits_current_format(self, tmp_path):
        """Citing bumps a counter: markdown stays durable, sidecar takes the bump."""
        manager, project = self._manager(tmp_path, CURRENT, STATS)

        manager.cite_lesson("L001")

        text = (project / ".claude-recall" / "LESSONS.md").read_text()
        assert "### [L001] Delimiter conflicts" in text, "no inline rating in headers"
        assert "**Uses**" not in text, "counters must not return to the markdown"
        assert "**Velocity**" not in text

        stats = json.loads((project / ".claude-recall" / "stats.json").read_text())
        assert stats["L001"]["uses"] == 13, "the bump lands in the sidecar"

    def test_write_migrates_a_legacy_file(self, tmp_path):
        """A pre-split file is converted on first write, not left half-and-half."""
        manager, project = self._manager(tmp_path, LEGACY, None)

        manager.cite_lesson("L001")

        text = (project / ".claude-recall" / "LESSONS.md").read_text()
        assert "**Uses**" not in text
        assert "[***--" not in text

        stats = json.loads((project / ".claude-recall" / "stats.json").read_text())
        assert stats["L001"]["uses"] == 13, "inline counter carried into the sidecar"
        assert stats["L002"]["uses"] == 5, "untouched lesson keeps its counter"
