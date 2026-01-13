#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Tests for StateReader handoff parsing.

Focuses on edge cases in handoff markdown parsing.
"""

import pytest
from pathlib import Path


class TestNextStepsParsing:
    """Tests for parsing the **Next**: field in handoffs."""

    def test_next_steps_semicolon_separated_are_split(self, tmp_path: Path):
        """Semicolon-separated next steps should be split into list items.

        When handoffs store multiple pending items as:
            **Next**: Item A; Item B; Item C

        The parser should split them into a list:
            next_steps = ["Item A", "Item B", "Item C"]

        This is a regression test for a bug where the entire semicolon-separated
        string was kept as a single item, causing the TUI to display:
            Pending (1):
              ○ Item A; Item B; Item C
        Instead of:
            Pending (3):
              ○ Item A
              ○ Item B
              ○ Item C
        """
        from core.tui.state_reader import StateReader

        # Create a minimal handoffs file with semicolon-separated next steps
        handoffs_dir = tmp_path / ".claude-recall"
        handoffs_dir.mkdir()
        handoffs_file = handoffs_dir / "HANDOFFS.md"
        handoffs_file.write_text("""# Handoffs

### [hf-test123] Test Handoff
- **Status**: in_progress | **Phase**: implementing | **Agent**: user
- **Created**: 2026-01-12 | **Updated**: 2026-01-12

**Next**: Do first thing; Do second thing; Do third thing

---
""")

        # Also need empty LESSONS.md
        lessons_file = handoffs_dir / "LESSONS.md"
        lessons_file.write_text("# Lessons\n")

        # Create state reader
        state_dir = tmp_path / ".state"
        state_dir.mkdir()
        reader = StateReader(state_dir=state_dir, project_root=tmp_path)

        # Get handoffs
        handoffs = reader.get_handoffs()

        # Find our test handoff
        test_handoff = next((h for h in handoffs if h.id == "hf-test123"), None)
        assert test_handoff is not None, "Test handoff should be found"

        # CRITICAL: next_steps should be a list of 3 items, not 1
        assert len(test_handoff.next_steps) == 3, (
            f"Expected 3 next steps, got {len(test_handoff.next_steps)}: {test_handoff.next_steps}"
        )
        assert test_handoff.next_steps[0].strip() == "Do first thing"
        assert test_handoff.next_steps[1].strip() == "Do second thing"
        assert test_handoff.next_steps[2].strip() == "Do third thing"

    def test_next_steps_single_item_no_semicolon(self, tmp_path: Path):
        """Single next step without semicolon should work normally."""
        from core.tui.state_reader import StateReader

        handoffs_dir = tmp_path / ".claude-recall"
        handoffs_dir.mkdir()
        handoffs_file = handoffs_dir / "HANDOFFS.md"
        handoffs_file.write_text("""# Handoffs

### [hf-single] Single Step Handoff
- **Status**: in_progress | **Phase**: implementing | **Agent**: user
- **Created**: 2026-01-12 | **Updated**: 2026-01-12

**Next**: Just one thing to do

---
""")

        lessons_file = handoffs_dir / "LESSONS.md"
        lessons_file.write_text("# Lessons\n")

        state_dir = tmp_path / ".state"
        state_dir.mkdir()
        reader = StateReader(state_dir=state_dir, project_root=tmp_path)

        handoffs = reader.get_handoffs()
        test_handoff = next((h for h in handoffs if h.id == "hf-single"), None)
        assert test_handoff is not None

        assert len(test_handoff.next_steps) == 1
        assert test_handoff.next_steps[0].strip() == "Just one thing to do"

    def test_next_steps_empty_segments_filtered(self, tmp_path: Path):
        """Empty segments from splitting should be filtered out."""
        from core.tui.state_reader import StateReader

        handoffs_dir = tmp_path / ".claude-recall"
        handoffs_dir.mkdir()
        handoffs_file = handoffs_dir / "HANDOFFS.md"
        handoffs_file.write_text("""# Handoffs

### [hf-empty] Handoff with empty segments
- **Status**: in_progress | **Phase**: implementing | **Agent**: user
- **Created**: 2026-01-12 | **Updated**: 2026-01-12

**Next**: First thing; ; Second thing;

---
""")

        lessons_file = handoffs_dir / "LESSONS.md"
        lessons_file.write_text("# Lessons\n")

        state_dir = tmp_path / ".state"
        state_dir.mkdir()
        reader = StateReader(state_dir=state_dir, project_root=tmp_path)

        handoffs = reader.get_handoffs()
        test_handoff = next((h for h in handoffs if h.id == "hf-empty"), None)
        assert test_handoff is not None

        # Should have 2 items, empty segments filtered
        assert len(test_handoff.next_steps) == 2
        assert "First thing" in test_handoff.next_steps[0]
        assert "Second thing" in test_handoff.next_steps[1]


class TestTriedHeaderParsing:
    """Tests for parsing the **Tried** header in handoffs."""

    def test_tried_header_with_count(self, tmp_path: Path):
        """**Tried** header with step count should be parsed correctly."""
        from core.tui.state_reader import StateReader

        handoffs_dir = tmp_path / ".claude-recall"
        handoffs_dir.mkdir()
        handoffs_file = handoffs_dir / "HANDOFFS.md"
        handoffs_file.write_text("""# Handoffs

### [hf-tried1] Handoff with tried count
- **Status**: in_progress | **Phase**: implementing | **Agent**: user
- **Created**: 2026-01-12 | **Updated**: 2026-01-12

**Tried** (2 steps):
1. [success] Did the first thing
2. [fail] Second thing failed

---
""")

        lessons_file = handoffs_dir / "LESSONS.md"
        lessons_file.write_text("# Lessons\n")

        state_dir = tmp_path / ".state"
        state_dir.mkdir()
        reader = StateReader(state_dir=state_dir, project_root=tmp_path)

        handoffs = reader.get_handoffs()
        test_handoff = next((h for h in handoffs if h.id == "hf-tried1"), None)
        assert test_handoff is not None, "Test handoff should be found"

        assert len(test_handoff.tried_steps) == 2
        assert test_handoff.tried_steps[0].outcome == "success"
        assert test_handoff.tried_steps[0].description == "Did the first thing"
        assert test_handoff.tried_steps[1].outcome == "fail"
        assert test_handoff.tried_steps[1].description == "Second thing failed"

    def test_tried_header_without_count(self, tmp_path: Path):
        """**Tried** header without step count should be parsed correctly.

        This is a regression test - the parser previously required the count,
        but now it should be optional to handle both:
            **Tried** (2 steps):
            **Tried**:
        """
        from core.tui.state_reader import StateReader

        handoffs_dir = tmp_path / ".claude-recall"
        handoffs_dir.mkdir()
        handoffs_file = handoffs_dir / "HANDOFFS.md"
        handoffs_file.write_text("""# Handoffs

### [hf-tried2] Handoff without tried count
- **Status**: in_progress | **Phase**: implementing | **Agent**: user
- **Created**: 2026-01-12 | **Updated**: 2026-01-12

**Tried**:
1. [success] Completed task A
2. [partial] Partially done task B

---
""")

        lessons_file = handoffs_dir / "LESSONS.md"
        lessons_file.write_text("# Lessons\n")

        state_dir = tmp_path / ".state"
        state_dir.mkdir()
        reader = StateReader(state_dir=state_dir, project_root=tmp_path)

        handoffs = reader.get_handoffs()
        test_handoff = next((h for h in handoffs if h.id == "hf-tried2"), None)
        assert test_handoff is not None, "Test handoff should be found"

        assert len(test_handoff.tried_steps) == 2
        assert test_handoff.tried_steps[0].outcome == "success"
        assert test_handoff.tried_steps[0].description == "Completed task A"
        assert test_handoff.tried_steps[1].outcome == "partial"
        assert test_handoff.tried_steps[1].description == "Partially done task B"

    def test_tried_header_singular_step(self, tmp_path: Path):
        """**Tried** header with singular 'step' should work."""
        from core.tui.state_reader import StateReader

        handoffs_dir = tmp_path / ".claude-recall"
        handoffs_dir.mkdir()
        handoffs_file = handoffs_dir / "HANDOFFS.md"
        handoffs_file.write_text("""# Handoffs

### [hf-tried3] Handoff with singular step
- **Status**: in_progress | **Phase**: implementing | **Agent**: user
- **Created**: 2026-01-12 | **Updated**: 2026-01-12

**Tried** (1 step):
1. [success] Only one thing

---
""")

        lessons_file = handoffs_dir / "LESSONS.md"
        lessons_file.write_text("# Lessons\n")

        state_dir = tmp_path / ".state"
        state_dir.mkdir()
        reader = StateReader(state_dir=state_dir, project_root=tmp_path)

        handoffs = reader.get_handoffs()
        test_handoff = next((h for h in handoffs if h.id == "hf-tried3"), None)
        assert test_handoff is not None, "Test handoff should be found"

        assert len(test_handoff.tried_steps) == 1
        assert test_handoff.tried_steps[0].outcome == "success"
        assert test_handoff.tried_steps[0].description == "Only one thing"
