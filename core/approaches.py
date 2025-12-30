#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Approaches mixin for the LessonsManager class.

This module contains all approach-related methods as a mixin class.
"""

import re
from datetime import date, timedelta
from pathlib import Path
from typing import List, Optional

# Handle both module import and direct script execution
try:
    from core.debug_logger import get_logger
    from core.file_lock import FileLock
    from core.models import (
        # Constants
        APPROACH_MAX_COMPLETED,
        APPROACH_MAX_AGE_DAYS,
        # Dataclasses
        TriedApproach,
        Approach,
        ApproachCompleteResult,
    )
except ImportError:
    from debug_logger import get_logger
    from file_lock import FileLock
    from models import (
        # Constants
        APPROACH_MAX_COMPLETED,
        APPROACH_MAX_AGE_DAYS,
        # Dataclasses
        TriedApproach,
        Approach,
        ApproachCompleteResult,
    )


class ApproachesMixin:
    """
    Mixin containing approach-related methods.

    This mixin expects the following attributes to be set on the class:
    - self.project_root: Path to project root
    """

    # Valid status and outcome values
    VALID_STATUSES = {"not_started", "in_progress", "blocked", "completed"}
    VALID_OUTCOMES = {"success", "fail", "partial"}
    VALID_PHASES = {"research", "planning", "implementing", "review"}
    VALID_AGENTS = {"explore", "general-purpose", "plan", "review", "user"}

    # -------------------------------------------------------------------------
    # Approaches Tracking
    # -------------------------------------------------------------------------

    @property
    def project_approaches_file(self) -> Path:
        """Path to the project approaches file."""
        return self.project_root / ".coding-agent-lessons" / "APPROACHES.md"

    @property
    def project_approaches_archive(self) -> Path:
        """Path to the project approaches archive file."""
        return self.project_root / ".coding-agent-lessons" / "APPROACHES_ARCHIVE.md"

    def _init_approaches_file(self) -> None:
        """Initialize approaches file with header if it doesn't exist."""
        file_path = self.project_approaches_file
        file_path.parent.mkdir(parents=True, exist_ok=True)

        if file_path.exists():
            return

        header = """# APPROACHES.md - Active Work Tracking

> Track ongoing work with tried approaches and next steps.
> When completed, review for lessons to extract.

## Active Approaches

"""
        file_path.write_text(header)

    def _parse_approaches_file(self, file_path: Path) -> List[Approach]:
        """Parse all approaches from a file."""
        if not file_path.exists():
            return []

        content = file_path.read_text()
        if not content.strip():
            return []

        approaches = []
        lines = content.split("\n")

        # Pattern for approach header: ### [A001] Title
        header_pattern = re.compile(r"^###\s*\[([A-Z]\d{3})\]\s*(.+)$")
        # New format status line: - **Status**: status | **Phase**: phase | **Agent**: agent
        status_pattern_new = re.compile(
            r"^\s*-\s*\*\*Status\*\*:\s*(\w+)"
            r"\s*\|\s*\*\*Phase\*\*:\s*([\w-]+)"
            r"\s*\|\s*\*\*Agent\*\*:\s*([\w-]+)"
        )
        # Old format status line: - **Status**: status | **Created**: date | **Updated**: date
        status_pattern_old = re.compile(
            r"^\s*-\s*\*\*Status\*\*:\s*(\w+)"
            r"\s*\|\s*\*\*Created\*\*:\s*(\d{4}-\d{2}-\d{2})"
            r"\s*\|\s*\*\*Updated\*\*:\s*(\d{4}-\d{2}-\d{2})"
        )
        # Pattern for dates line: - **Created**: date | **Updated**: date
        dates_pattern = re.compile(
            r"^\s*-\s*\*\*Created\*\*:\s*(\d{4}-\d{2}-\d{2})"
            r"\s*\|\s*\*\*Updated\*\*:\s*(\d{4}-\d{2}-\d{2})"
        )
        # Pattern for files line: - **Files**: file1, file2
        files_pattern = re.compile(r"^\s*-\s*\*\*Files\*\*:\s*(.*)$")
        # Pattern for description line: - **Description**: desc
        desc_pattern = re.compile(r"^\s*-\s*\*\*Description\*\*:\s*(.*)$")
        # Pattern for tried item: N. [outcome] description
        tried_pattern = re.compile(r"^\s*\d+\.\s*\[(\w+)\]\s*(.+)$")

        idx = 0
        while idx < len(lines):
            header_match = header_pattern.match(lines[idx])
            if not header_match:
                idx += 1
                continue

            approach_id = header_match.group(1)
            title = header_match.group(2).strip()
            idx += 1

            # Parse status line - try new format first, then old format
            if idx >= len(lines):
                continue

            status = None
            phase = "research"  # default
            agent = "user"  # default
            created = None
            updated = None

            status_match_new = status_pattern_new.match(lines[idx])
            status_match_old = status_pattern_old.match(lines[idx])

            if status_match_new:
                # New format: status, phase, agent on first line
                status = status_match_new.group(1)
                phase = status_match_new.group(2)
                agent = status_match_new.group(3)
                idx += 1

                # Parse dates from next line
                if idx < len(lines):
                    dates_match = dates_pattern.match(lines[idx])
                    if dates_match:
                        try:
                            created = date.fromisoformat(dates_match.group(1))
                            updated = date.fromisoformat(dates_match.group(2))
                        except ValueError:
                            continue
                        idx += 1
                    else:
                        # Malformed - skip
                        continue
                else:
                    continue
            elif status_match_old:
                # Old format: status, created, updated on same line
                status = status_match_old.group(1)
                try:
                    created = date.fromisoformat(status_match_old.group(2))
                    updated = date.fromisoformat(status_match_old.group(3))
                except ValueError:
                    continue
                idx += 1
            else:
                # Malformed - skip this approach
                continue

            # Parse files line
            files = []
            if idx < len(lines):
                files_match = files_pattern.match(lines[idx])
                if files_match:
                    files_str = files_match.group(1).strip()
                    if files_str:
                        files = [f.strip() for f in files_str.split(",") if f.strip()]
                    idx += 1

            # Parse description line
            description = ""
            if idx < len(lines):
                desc_match = desc_pattern.match(lines[idx])
                if desc_match:
                    description = desc_match.group(1).strip()
                    idx += 1

            # Parse checkpoint line (optional)
            checkpoint = ""
            checkpoint_pattern = re.compile(r"^\s*-\s*\*\*Checkpoint\*\*:\s*(.*)$")
            if idx < len(lines):
                checkpoint_match = checkpoint_pattern.match(lines[idx])
                if checkpoint_match:
                    checkpoint = checkpoint_match.group(1).strip()
                    idx += 1

            # Parse last session line (optional)
            last_session = None
            last_session_pattern = re.compile(r"^\s*-\s*\*\*Last Session\*\*:\s*(\d{4}-\d{2}-\d{2})$")
            if idx < len(lines):
                last_session_match = last_session_pattern.match(lines[idx])
                if last_session_match:
                    try:
                        last_session = date.fromisoformat(last_session_match.group(1))
                    except ValueError:
                        pass
                    idx += 1

            # Parse tried section
            tried = []
            # Look for **Tried**: header
            while idx < len(lines) and not lines[idx].strip().startswith("**Tried**"):
                idx += 1
            if idx < len(lines) and "**Tried**:" in lines[idx]:
                idx += 1
                while idx < len(lines):
                    line = lines[idx].strip()
                    if not line or line.startswith("**Next**:") or line == "---":
                        break
                    tried_match = tried_pattern.match(lines[idx])
                    if tried_match:
                        tried.append(TriedApproach(
                            outcome=tried_match.group(1),
                            description=tried_match.group(2).strip()
                        ))
                    idx += 1

            # Parse next steps
            next_steps = ""
            while idx < len(lines) and not lines[idx].strip().startswith("**Next**"):
                idx += 1
            if idx < len(lines) and "**Next**:" in lines[idx]:
                # Extract text after **Next**:
                next_match = re.match(r"^\*\*Next\*\*:\s*(.*)$", lines[idx].strip())
                if next_match:
                    next_steps = next_match.group(1).strip()
                idx += 1

            # Skip to separator or next approach
            while idx < len(lines) and lines[idx].strip() != "---":
                idx += 1
            idx += 1  # Skip the separator

            approaches.append(Approach(
                id=approach_id,
                title=title,
                status=status,
                created=created,
                updated=updated,
                files=files,
                description=description,
                tried=tried,
                next_steps=next_steps,
                phase=phase,
                agent=agent,
                checkpoint=checkpoint,
                last_session=last_session,
            ))

        return approaches

    def _format_approach(self, approach: Approach) -> str:
        """Format an approach for markdown storage."""
        lines = [
            f"### [{approach.id}] {approach.title}",
            f"- **Status**: {approach.status} | **Phase**: {approach.phase} | **Agent**: {approach.agent}",
            f"- **Created**: {approach.created.isoformat()} | **Updated**: {approach.updated.isoformat()}",
            f"- **Files**: {', '.join(approach.files)}",
            f"- **Description**: {approach.description}",
        ]

        # Add checkpoint if present
        if approach.checkpoint:
            session_str = approach.last_session.isoformat() if approach.last_session else ""
            lines.append(f"- **Checkpoint**: {approach.checkpoint}")
            if session_str:
                lines.append(f"- **Last Session**: {session_str}")

        lines.append("")

        lines.append("**Tried**:")
        for i, tried in enumerate(approach.tried, 1):
            lines.append(f"{i}. [{tried.outcome}] {tried.description}")

        lines.append("")
        lines.append(f"**Next**: {approach.next_steps}")
        lines.append("")
        lines.append("---")

        return "\n".join(lines)

    def _write_approaches_file(self, approaches: List[Approach]) -> None:
        """Write approaches back to file."""
        self._init_approaches_file()

        header = """# APPROACHES.md - Active Work Tracking

> Track ongoing work with tried approaches and next steps.
> When completed, review for lessons to extract.

## Active Approaches

"""
        parts = [header]
        for approach in approaches:
            parts.append(self._format_approach(approach))
            parts.append("")

        self.project_approaches_file.write_text("\n".join(parts))

    def _get_next_approach_id(self) -> str:
        """Get the next available approach ID."""
        max_id = 0

        # Check main file
        if self.project_approaches_file.exists():
            approaches = self._parse_approaches_file(self.project_approaches_file)
            for approach in approaches:
                try:
                    num = int(approach.id[1:])
                    max_id = max(max_id, num)
                except ValueError:
                    pass

        # Also check archive to prevent ID reuse
        if self.project_approaches_archive.exists():
            content = self.project_approaches_archive.read_text()
            for match in re.finditer(r"\[A(\d{3})\]", content):
                try:
                    num = int(match.group(1))
                    max_id = max(max_id, num)
                except ValueError:
                    pass

        return f"A{max_id + 1:03d}"

    def approach_add(
        self,
        title: str,
        desc: Optional[str] = None,
        files: Optional[List[str]] = None,
        phase: str = "research",
        agent: str = "user",
    ) -> str:
        """
        Add a new approach.

        Args:
            title: Approach title
            desc: Optional description
            files: Optional list of files
            phase: Initial phase (research, planning, implementing, review)
            agent: Agent working on this (explore, general-purpose, plan, review, user)

        Returns:
            The assigned approach ID (e.g., 'A001')

        Raises:
            ValueError: If invalid phase or agent
        """
        if phase not in self.VALID_PHASES:
            raise ValueError(f"Invalid phase: {phase}")
        if agent not in self.VALID_AGENTS:
            raise ValueError(f"Invalid agent: {agent}")

        self._init_approaches_file()

        with FileLock(self.project_approaches_file):
            approaches = self._parse_approaches_file(self.project_approaches_file)
            approach_id = self._get_next_approach_id()
            today = date.today()

            approach = Approach(
                id=approach_id,
                title=title,
                status="not_started",
                created=today,
                updated=today,
                files=files or [],
                description=desc or "",
                tried=[],
                next_steps="",
                phase=phase,
                agent=agent,
            )

            approaches.append(approach)
            self._write_approaches_file(approaches)

        # Log approach created
        logger = get_logger()
        logger.approach_created(
            approach_id=approach_id,
            title=title,
            phase=phase,
            agent=agent,
        )

        return approach_id

    def approach_update_status(self, approach_id: str, status: str) -> None:
        """
        Update an approach's status.

        Args:
            approach_id: The approach ID
            status: New status (not_started, in_progress, blocked, completed)

        Raises:
            ValueError: If approach not found or invalid status
        """
        if status not in self.VALID_STATUSES:
            raise ValueError(f"Invalid status: {status}")

        old_status = None
        with FileLock(self.project_approaches_file):
            approaches = self._parse_approaches_file(self.project_approaches_file)

            found = False
            for approach in approaches:
                if approach.id == approach_id:
                    old_status = approach.status
                    approach.status = status
                    approach.updated = date.today()
                    found = True
                    break

            if not found:
                raise ValueError(f"Approach {approach_id} not found")

            self._write_approaches_file(approaches)

        # Log status change
        logger = get_logger()
        logger.approach_change(
            approach_id=approach_id,
            action="status_change",
            old_value=old_status,
            new_value=status,
        )

    def approach_update_phase(self, approach_id: str, phase: str) -> None:
        """
        Update an approach's phase.

        Args:
            approach_id: The approach ID
            phase: New phase (research, planning, implementing, review)

        Raises:
            ValueError: If approach not found or invalid phase
        """
        if phase not in self.VALID_PHASES:
            raise ValueError(f"Invalid phase: {phase}")

        old_phase = None
        with FileLock(self.project_approaches_file):
            approaches = self._parse_approaches_file(self.project_approaches_file)

            found = False
            for approach in approaches:
                if approach.id == approach_id:
                    old_phase = approach.phase
                    approach.phase = phase
                    approach.updated = date.today()
                    found = True
                    break

            if not found:
                raise ValueError(f"Approach {approach_id} not found")

            self._write_approaches_file(approaches)

        # Log phase change
        logger = get_logger()
        logger.approach_change(
            approach_id=approach_id,
            action="phase_change",
            old_value=old_phase,
            new_value=phase,
        )

    def approach_update_agent(self, approach_id: str, agent: str) -> None:
        """
        Update an approach's agent.

        Args:
            approach_id: The approach ID
            agent: New agent (explore, general-purpose, plan, review, user)

        Raises:
            ValueError: If approach not found or invalid agent
        """
        if agent not in self.VALID_AGENTS:
            raise ValueError(f"Invalid agent: {agent}")

        old_agent = None
        with FileLock(self.project_approaches_file):
            approaches = self._parse_approaches_file(self.project_approaches_file)

            found = False
            for approach in approaches:
                if approach.id == approach_id:
                    old_agent = approach.agent
                    approach.agent = agent
                    approach.updated = date.today()
                    found = True
                    break

            if not found:
                raise ValueError(f"Approach {approach_id} not found")

            self._write_approaches_file(approaches)

        # Log agent change
        logger = get_logger()
        logger.approach_change(
            approach_id=approach_id,
            action="agent_change",
            old_value=old_agent,
            new_value=agent,
        )

    def approach_add_tried(
        self,
        approach_id: str,
        outcome: str,
        description: str,
    ) -> None:
        """
        Add a tried approach.

        Args:
            approach_id: The approach ID
            outcome: success, fail, or partial
            description: Description of what was tried

        Raises:
            ValueError: If approach not found or invalid outcome
        """
        if outcome not in self.VALID_OUTCOMES:
            raise ValueError(f"Invalid outcome: {outcome}")

        with FileLock(self.project_approaches_file):
            approaches = self._parse_approaches_file(self.project_approaches_file)

            found = False
            for approach in approaches:
                if approach.id == approach_id:
                    approach.tried.append(TriedApproach(
                        outcome=outcome,
                        description=description,
                    ))
                    approach.updated = date.today()
                    found = True
                    break

            if not found:
                raise ValueError(f"Approach {approach_id} not found")

            self._write_approaches_file(approaches)

    def approach_update_next(self, approach_id: str, text: str) -> None:
        """
        Update an approach's next steps.

        Args:
            approach_id: The approach ID
            text: Next steps text

        Raises:
            ValueError: If approach not found
        """
        with FileLock(self.project_approaches_file):
            approaches = self._parse_approaches_file(self.project_approaches_file)

            found = False
            for approach in approaches:
                if approach.id == approach_id:
                    approach.next_steps = text
                    approach.updated = date.today()
                    found = True
                    break

            if not found:
                raise ValueError(f"Approach {approach_id} not found")

            self._write_approaches_file(approaches)

    def approach_update_files(self, approach_id: str, files_list: List[str]) -> None:
        """
        Update an approach's file list.

        Args:
            approach_id: The approach ID
            files_list: List of files

        Raises:
            ValueError: If approach not found
        """
        with FileLock(self.project_approaches_file):
            approaches = self._parse_approaches_file(self.project_approaches_file)

            found = False
            for approach in approaches:
                if approach.id == approach_id:
                    approach.files = files_list
                    approach.updated = date.today()
                    found = True
                    break

            if not found:
                raise ValueError(f"Approach {approach_id} not found")

            self._write_approaches_file(approaches)

    def approach_update_desc(self, approach_id: str, description: str) -> None:
        """
        Update an approach's description.

        Args:
            approach_id: The approach ID
            description: New description

        Raises:
            ValueError: If approach not found
        """
        with FileLock(self.project_approaches_file):
            approaches = self._parse_approaches_file(self.project_approaches_file)

            found = False
            for approach in approaches:
                if approach.id == approach_id:
                    approach.description = description
                    approach.updated = date.today()
                    found = True
                    break

            if not found:
                raise ValueError(f"Approach {approach_id} not found")

            self._write_approaches_file(approaches)

    def approach_update_checkpoint(self, approach_id: str, checkpoint: str) -> None:
        """
        Update an approach's checkpoint (progress summary from PreCompact hook).

        Args:
            approach_id: The approach ID
            checkpoint: Progress summary text

        Raises:
            ValueError: If approach not found
        """
        with FileLock(self.project_approaches_file):
            approaches = self._parse_approaches_file(self.project_approaches_file)

            found = False
            for approach in approaches:
                if approach.id == approach_id:
                    approach.checkpoint = checkpoint
                    approach.last_session = date.today()
                    approach.updated = date.today()
                    found = True
                    break

            if not found:
                raise ValueError(f"Approach {approach_id} not found")

            self._write_approaches_file(approaches)

    def approach_complete(self, approach_id: str) -> ApproachCompleteResult:
        """
        Mark an approach as completed and return extraction prompt.

        Args:
            approach_id: The approach ID

        Returns:
            ApproachCompleteResult with approach data and extraction prompt

        Raises:
            ValueError: If approach not found
        """
        with FileLock(self.project_approaches_file):
            approaches = self._parse_approaches_file(self.project_approaches_file)

            target = None
            for approach in approaches:
                if approach.id == approach_id:
                    target = approach
                    break

            if target is None:
                raise ValueError(f"Approach {approach_id} not found")

            target.status = "completed"
            target.updated = date.today()
            self._write_approaches_file(approaches)

        # Generate extraction prompt
        tried_summary = ""
        if target.tried:
            tried_lines = []
            for tried in target.tried:
                tried_lines.append(f"- [{tried.outcome}] {tried.description}")
            tried_summary = "\n".join(tried_lines)

        extraction_prompt = f"""Review this completed approach for potential lessons to extract:

**Title**: {target.title}
**Description**: {target.description}

**Tried approaches**:
{tried_summary if tried_summary else "(none)"}

**Files affected**: {', '.join(target.files) if target.files else "(none)"}

Consider extracting lessons about:
1. What worked and why
2. What didn't work and why
3. Patterns or gotchas discovered
4. Decisions made and their rationale
"""

        # Log approach completed
        duration_days = (date.today() - target.created).days if target.created else None
        logger = get_logger()
        logger.approach_completed(
            approach_id=approach_id,
            tried_count=len(target.tried),
            duration_days=duration_days,
        )

        return ApproachCompleteResult(
            approach=target,
            extraction_prompt=extraction_prompt,
        )

    def approach_archive(self, approach_id: str) -> None:
        """
        Archive an approach to APPROACHES_ARCHIVE.md.

        Args:
            approach_id: The approach ID

        Raises:
            ValueError: If approach not found
        """
        with FileLock(self.project_approaches_file):
            approaches = self._parse_approaches_file(self.project_approaches_file)

            target = None
            remaining = []
            for approach in approaches:
                if approach.id == approach_id:
                    target = approach
                else:
                    remaining.append(approach)

            if target is None:
                raise ValueError(f"Approach {approach_id} not found")

            # Append to archive file
            archive_file = self.project_approaches_archive
            archive_file.parent.mkdir(parents=True, exist_ok=True)

            if archive_file.exists():
                archive_content = archive_file.read_text()
            else:
                archive_content = """# APPROACHES_ARCHIVE.md - Archived Approaches

> Previously completed or archived approaches.

"""

            archive_content += "\n" + self._format_approach(target) + "\n"
            archive_file.write_text(archive_content)

            # Remove from main file
            self._write_approaches_file(remaining)

    def approach_delete(self, approach_id: str) -> None:
        """
        Delete an approach permanently (no archive).

        Args:
            approach_id: The approach ID

        Raises:
            ValueError: If approach not found
        """
        with FileLock(self.project_approaches_file):
            approaches = self._parse_approaches_file(self.project_approaches_file)

            original_count = len(approaches)
            approaches = [a for a in approaches if a.id != approach_id]

            if len(approaches) == original_count:
                raise ValueError(f"Approach {approach_id} not found")

            self._write_approaches_file(approaches)

        logger = get_logger()
        logger.mutation("delete_approach", approach_id)

    def approach_get(self, approach_id: str) -> Optional[Approach]:
        """
        Get an approach by ID.

        Args:
            approach_id: The approach ID

        Returns:
            The Approach object, or None if not found
        """
        if not self.project_approaches_file.exists():
            return None

        approaches = self._parse_approaches_file(self.project_approaches_file)
        for approach in approaches:
            if approach.id == approach_id:
                return approach

        return None

    def approach_list(
        self,
        status_filter: Optional[str] = None,
        include_completed: bool = False,
    ) -> List[Approach]:
        """
        List approaches with optional filtering.

        Args:
            status_filter: Filter by specific status
            include_completed: Include completed approaches (default False)

        Returns:
            List of matching approaches
        """
        if not self.project_approaches_file.exists():
            return []

        approaches = self._parse_approaches_file(self.project_approaches_file)

        if status_filter:
            approaches = [a for a in approaches if a.status == status_filter]
        elif not include_completed:
            approaches = [a for a in approaches if a.status != "completed"]

        return approaches

    def approach_list_completed(
        self,
        max_count: Optional[int] = None,
        max_age_days: Optional[int] = None,
    ) -> List[Approach]:
        """
        List completed approaches with hybrid visibility rules.

        Uses OR logic: shows approaches that are either:
        - Within the last max_count completions, OR
        - Completed within max_age_days

        Args:
            max_count: Max number of recent completions to show (default: APPROACH_MAX_COMPLETED)
            max_age_days: Max age in days for completed approaches (default: APPROACH_MAX_AGE_DAYS)

        Returns:
            List of visible completed approaches, sorted by updated date (newest first)
        """
        if max_count is None:
            max_count = APPROACH_MAX_COMPLETED
        if max_age_days is None:
            max_age_days = APPROACH_MAX_AGE_DAYS

        if not self.project_approaches_file.exists():
            return []

        approaches = self._parse_approaches_file(self.project_approaches_file)

        # Filter to completed only
        completed = [a for a in approaches if a.status == "completed"]

        if not completed:
            return []

        # Sort by updated date (newest first)
        completed.sort(key=lambda a: a.updated, reverse=True)

        # Calculate cutoff date
        cutoff_date = date.today() - timedelta(days=max_age_days)

        # Apply hybrid logic: keep if in top N OR recent enough
        visible = []
        for i, approach in enumerate(completed):
            # In top N by recency
            in_top_n = i < max_count
            # Updated within age limit
            is_recent = approach.updated >= cutoff_date

            if in_top_n or is_recent:
                visible.append(approach)

        return visible

    def approach_inject(
        self,
        max_completed: Optional[int] = None,
        max_completed_age: Optional[int] = None,
    ) -> str:
        """
        Generate context injection string with active and recent completed approaches.

        Args:
            max_completed: Max completed approaches to show (default: APPROACH_MAX_COMPLETED)
            max_completed_age: Max age in days for completed (default: APPROACH_MAX_AGE_DAYS)

        Returns:
            Formatted string for context injection, empty if no approaches
        """
        active_approaches = self.approach_list(include_completed=False)
        completed_approaches = self.approach_list_completed(
            max_count=max_completed,
            max_age_days=max_completed_age,
        )

        if not active_approaches and not completed_approaches:
            return ""

        lines = []

        # Active approaches section
        if active_approaches:
            lines.append("## Active Approaches")
            lines.append("")

            for approach in active_approaches:
                lines.append(f"### [{approach.id}] {approach.title}")
                lines.append(f"- **Status**: {approach.status} | **Phase**: {approach.phase} | **Agent**: {approach.agent}")
                if approach.files:
                    lines.append(f"- **Files**: {', '.join(approach.files)}")
                if approach.description:
                    lines.append(f"- **Description**: {approach.description}")

                # Show checkpoint prominently if present (key for session handoff)
                if approach.checkpoint:
                    session_ago = ""
                    if approach.last_session:
                        days = (date.today() - approach.last_session).days
                        if days == 0:
                            session_ago = " (today)"
                        elif days == 1:
                            session_ago = " (yesterday)"
                        else:
                            session_ago = f" ({days}d ago)"
                    lines.append(f"- **Checkpoint{session_ago}**: {approach.checkpoint}")

                if approach.tried:
                    lines.append("")
                    lines.append("**Tried**:")
                    for i, tried in enumerate(approach.tried, 1):
                        lines.append(f"{i}. [{tried.outcome}] {tried.description}")

                if approach.next_steps:
                    lines.append("")
                    lines.append(f"**Next**: {approach.next_steps}")

                lines.append("")

        # Recent completions section
        if completed_approaches:
            lines.append("## Recent Completions")
            lines.append("")

            for approach in completed_approaches:
                # Calculate days since completion
                days_ago = (date.today() - approach.updated).days
                if days_ago == 0:
                    time_str = "today"
                elif days_ago == 1:
                    time_str = "1d ago"
                else:
                    time_str = f"{days_ago}d ago"

                lines.append(f"  [{approach.id}] ✓ {approach.title} (completed {time_str})")

            lines.append("")

        return "\n".join(lines)

    def approach_sync_todos(self, todos: List[dict]) -> Optional[str]:
        """
        Sync TodoWrite todos to an approach.

        Bridges ephemeral TodoWrite with persistent APPROACHES.md:
        - completed todos → tried entries (outcome=success)
        - in_progress todo → checkpoint (current focus)
        - pending todos → next_steps

        Args:
            todos: List of todo dicts with 'content', 'status', 'activeForm'

        Returns:
            Approach ID that was updated/created, or None if no todos
        """
        if not todos:
            return None

        # Categorize todos by status
        completed = [t for t in todos if t.get("status") == "completed"]
        in_progress = [t for t in todos if t.get("status") == "in_progress"]
        pending = [t for t in todos if t.get("status") == "pending"]

        # Find or create an approach
        active_approaches = self.approach_list(include_completed=False)

        if active_approaches:
            # Use the most recently updated active approach
            approach = max(active_approaches, key=lambda a: a.updated)
            approach_id = approach.id
        else:
            # Create new approach from first todo
            first_todo = todos[0].get("content", "Work in progress")
            # Truncate title to 50 chars
            title = first_todo[:50] + ("..." if len(first_todo) > 50 else "")
            approach_id = self.approach_add(title=title)

        # Sync completed todos as tried entries (success)
        # Only add new ones - check if description already exists
        existing_tried = set()
        approach = self.approach_get(approach_id)
        if approach and approach.tried:
            existing_tried = {t.description for t in approach.tried}

        for todo in completed:
            content = todo.get("content", "")
            if content and content not in existing_tried:
                self.approach_add_tried(approach_id, "success", content)

        # Sync in_progress as checkpoint
        if in_progress:
            checkpoint_text = in_progress[0].get("content", "")
            if len(in_progress) > 1:
                checkpoint_text += f" (and {len(in_progress) - 1} more)"
            self.approach_update_checkpoint(approach_id, checkpoint_text)

        # Sync pending as next_steps
        if pending:
            next_items = [t.get("content", "") for t in pending[:5]]  # Max 5
            next_text = "; ".join(next_items)
            if len(pending) > 5:
                next_text += f" (and {len(pending) - 5} more)"
            self.approach_update_next(approach_id, next_text)

        # Update status based on todo states
        if in_progress:
            self.approach_update_status(approach_id, "in_progress")
        elif pending and not completed:
            self.approach_update_status(approach_id, "not_started")

        logger = get_logger()
        logger.mutation("sync_todos", approach_id, {
            "completed": len(completed),
            "in_progress": len(in_progress),
            "pending": len(pending),
        })

        return approach_id

    def approach_inject_todos(self) -> str:
        """
        Format active approach as TodoWrite continuation prompt.

        Generates a prompt that helps the agent continue work from a previous session
        by showing the approach state formatted as suggested todos.

        Returns:
            Formatted string with todo continuation prompt, or empty if no active approach
        """
        import json as json_module

        active_approaches = self.approach_list(include_completed=False)
        if not active_approaches:
            return ""

        # Use the most recently updated active approach
        approach = max(active_approaches, key=lambda a: a.updated)

        # Build todo list from approach state
        todos = []

        # Add completed tried entries (already done)
        for tried in approach.tried:
            if tried.outcome == "success":
                todos.append({
                    "content": tried.description,
                    "status": "completed",
                    "activeForm": tried.description[:50] + "..." if len(tried.description) > 50 else tried.description
                })

        # Add checkpoint as in_progress
        if approach.checkpoint:
            todos.append({
                "content": approach.checkpoint,
                "status": "in_progress",
                "activeForm": approach.checkpoint[:50] + "..." if len(approach.checkpoint) > 50 else approach.checkpoint
            })

        # Add next_steps as pending (split by semicolon)
        if approach.next_steps:
            for step in approach.next_steps.split(";"):
                step = step.strip()
                if step:
                    todos.append({
                        "content": step,
                        "status": "pending",
                        "activeForm": step[:50] + "..." if len(step) > 50 else step
                    })

        if not todos:
            return ""

        # Calculate session age
        session_ago = ""
        if approach.last_session:
            days = (date.today() - approach.last_session).days
            if days == 0:
                session_ago = "today"
            elif days == 1:
                session_ago = "yesterday"
            else:
                session_ago = f"{days}d ago"

        # Format as continuation prompt
        lines = []
        lines.append(f"**CONTINUE PREVIOUS WORK** ({approach.id}: {approach.title})")
        if session_ago:
            lines.append(f"Last session: {session_ago}")
        lines.append("")
        lines.append("Previous state:")
        for todo in todos:
            status_icon = {"completed": "✓", "in_progress": "→", "pending": "○"}.get(todo["status"], "?")
            lines.append(f"  {status_icon} {todo['content']}")
        lines.append("")
        lines.append("**Use TodoWrite to resume tracking.** Copy this starting point:")
        lines.append("```json")
        # Only include non-completed todos in the suggested JSON
        active_todos = [t for t in todos if t["status"] != "completed"]
        lines.append(json_module.dumps(active_todos, indent=2))
        lines.append("```")

        return "\n".join(lines)
