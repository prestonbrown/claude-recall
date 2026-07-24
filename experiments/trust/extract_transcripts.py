"""Read-only extractor: Claude Code session transcripts -> judge records.

A *judge record* is the raw material for an offline LLM judge that decides
whether an injected lesson was actually APPLIED in the session that received it,
independent of whether the agent explicitly cited it. This module never writes
runtime state: it reads the event log (``session-log.jsonl``) and the Claude
Code transcripts under ``~/.claude/projects/`` and emits one JSONL record per
relevance-injected ``(session, lesson)`` pair whose session has a transcript.

Key facts about the inputs (see the module tests for the exact shapes):

* The event log's relevance injections are
  ``{"type":"injection","hook":"prompt_submit","session":<uuid>,"lesson":"L###",
     "score":N,"project":..}`` with a non-empty session. Citations are
  ``{"type":"citation","session":<uuid>,"lesson":"L###",..}``.

* Transcripts live at ``~/.claude/projects/<slug>/<session-id>.jsonl``. The
  directory does **not** track the project path (worktree sessions live under
  the parent repo's slug), so we build a global index keyed by session id (the
  36-char UUID basename) across every ``*.jsonl`` under the projects root.

* Inside a transcript, a relevance injection is an *attachment*, not a message:
  ``{"attachment":{"type":"hook_additional_context",
     "content":["RELEVANT LESSONS for your query:\\n[L081] ... (relevance: 10/10)
                 <title>\\n    -> <full body>\\n..."]}}``.
  The full lesson body is present verbatim and is the authoritative source of
  ``lesson_text``.

* Assistant turns are ``{"message":{"role":"assistant","content":[
     {"type":"text","text":..}, {"type":"tool_use","name":"Edit"/"Write"/
     "Read"/"Bash","input":{"file_path":..,"command":..}}]}}``. Literal
  ``[L###]`` in assistant text is a citation.
"""

from __future__ import annotations

import glob
import json
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# Default text budgets keep the per-record judge cost bounded.
DEFAULT_TEXT_BUDGET = 6000
DEFAULT_BASH_LIMIT = 40
DEFAULT_BASH_CMD_BUDGET = 500

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

# A lesson header line inside an injection attachment, e.g.
#   "[L061] ⭐⭐⭐⭐⭐ (relevance: 10/10) AD5M test printer environment"
_LESSON_HEADER_RE = re.compile(
    r"^\[([LS]\d+)\]\s*(.*?)\(relevance:\s*(\d+)\s*/\s*10\)\s*(.*)$"
)

# The footer the hook appends after the last lesson body.
_FOOTER_RE = re.compile(r"^\s*Cite \[ID\] when applying")

_INJECTION_MARKER = "RELEVANT LESSONS for your query"
_FILE_TOOLS = {"Edit", "Write", "Read", "MultiEdit", "NotebookEdit"}


def default_log_path() -> str:
    state = os.environ.get("CLAUDE_RECALL_STATE")
    if state:
        return os.path.join(state, "session-log.jsonl")
    return os.path.expanduser("~/.local/state/claude-recall/session-log.jsonl")


def default_projects_dir() -> str:
    return os.path.expanduser("~/.claude/projects")


# ---------------------------------------------------------------------------
# transcript index
# ---------------------------------------------------------------------------

def build_transcript_index(projects_dir: str) -> Dict[str, str]:
    """Map ``session-id -> transcript path`` for every UUID-named transcript.

    The session id is the file *basename* (worktree sessions live under the
    parent repo's slug, so the directory is not a reliable project key). Only
    basenames that are 36-char UUIDs are indexed; on a duplicate id the first
    path wins (deterministic via sorted iteration).
    """
    index: Dict[str, str] = {}
    for path in sorted(glob.glob(os.path.join(projects_dir, "**", "*.jsonl"),
                                 recursive=True)):
        base = os.path.basename(path)[:-len(".jsonl")]
        if _UUID_RE.match(base) and base not in index:
            index[base] = path
    return index


# ---------------------------------------------------------------------------
# attachment parsing
# ---------------------------------------------------------------------------

@dataclass
class InjectedLesson:
    lesson: str
    title: str
    text: str
    relevance: Optional[int]


def parse_injection_blocks(content: str) -> List[InjectedLesson]:
    """Parse one ``RELEVANT LESSONS`` attachment string into lesson blocks.

    Each block is a header line ``[L###] <stars> (relevance: N/10) <title>``
    followed by a body: the first body line is prefixed ``    -> `` and the body
    may continue over subsequent unindented lines until the next header or the
    trailing ``Cite [ID] when applying`` footer. The body is returned verbatim
    (arrow prefix stripped, trailing whitespace trimmed).
    """
    lines = content.split("\n")
    blocks: List[InjectedLesson] = []
    i = 0
    n = len(lines)
    while i < n:
        m = _LESSON_HEADER_RE.match(lines[i])
        if not m:
            i += 1
            continue
        lesson, _stars, rel, title = m.groups()
        relevance = int(rel)
        body_lines: List[str] = []
        i += 1
        while i < n:
            ln = lines[i]
            if _LESSON_HEADER_RE.match(ln) or _FOOTER_RE.match(ln):
                break
            body_lines.append(ln)
            i += 1
        # Strip the leading "    -> " from the first body line if present.
        if body_lines:
            body_lines[0] = re.sub(r"^\s*->\s?", "", body_lines[0])
        text = "\n".join(body_lines).strip()
        blocks.append(InjectedLesson(
            lesson=lesson,
            title=title.strip(),
            text=text,
            relevance=relevance,
        ))
    return blocks


def _attachment_content_str(obj: dict) -> Optional[str]:
    """Return the injection content string of a transcript line, or None.

    The attachment ``content`` is a list of strings; we only care about the one
    carrying the relevance-injection marker.
    """
    att = obj.get("attachment")
    if not isinstance(att, dict):
        return None
    content = att.get("content")
    parts: List[str]
    if isinstance(content, list):
        parts = [c for c in content if isinstance(c, str)]
    elif isinstance(content, str):
        parts = [content]
    else:
        return None
    for p in parts:
        if _INJECTION_MARKER in p:
            return p
    return None


# ---------------------------------------------------------------------------
# assistant / tool_use extraction
# ---------------------------------------------------------------------------

def _assistant_blocks(obj: dict):
    """Yield content blocks from an assistant message line (list or bare str)."""
    msg = obj.get("message")
    if not isinstance(msg, dict) or msg.get("role") != "assistant":
        return
    content = msg.get("content")
    if isinstance(content, str):
        yield {"type": "text", "text": content}
    elif isinstance(content, list):
        for b in content:
            if isinstance(b, dict):
                yield b


@dataclass
class _LineInfo:
    """Per-line extraction results, indexed by file position (chronological)."""
    is_injection: bool = False
    asst_text: str = ""
    tool_uses: List[Tuple[str, dict]] = field(default_factory=list)


def _scan_transcript(path: str):
    """Read a transcript once into (line_infos, first_injection_by_lesson).

    ``line_infos`` is a list parallel to transcript position. Non-JSON lines
    still occupy a slot (empty _LineInfo) so indices stay chronological.
    ``first_injection_by_lesson`` maps lesson id -> (line_index, InjectedLesson)
    for the earliest attachment mentioning that lesson.
    """
    infos: List[_LineInfo] = []
    first_inj: Dict[str, Tuple[int, InjectedLesson]] = {}
    with open(path, "r", encoding="utf-8") as f:
        for idx, raw in enumerate(f):
            info = _LineInfo()
            infos.append(info)
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue

            content = _attachment_content_str(obj)
            if content is not None:
                info.is_injection = True
                for block in parse_injection_blocks(content):
                    if block.lesson not in first_inj:
                        first_inj[block.lesson] = (idx, block)

            texts: List[str] = []
            for block in _assistant_blocks(obj):
                btype = block.get("type")
                if btype == "text":
                    t = block.get("text")
                    if isinstance(t, str):
                        texts.append(t)
                elif btype == "tool_use":
                    name = block.get("name") or ""
                    binput = block.get("input")
                    info.tool_uses.append(
                        (name, binput if isinstance(binput, dict) else {})
                    )
            if texts:
                info.asst_text = "\n".join(texts)
    return infos, first_inj


def _following_signals(infos: List[_LineInfo], start: int, lesson: str,
                       text_budget: int, bash_limit: int, bash_cmd_budget: int):
    """Aggregate assistant signals strictly AFTER line index ``start``.

    ``cited`` is True iff this lesson's own literal citation token ``[<lesson>]``
    appears in assistant text after the injection (a generic ``[L###]`` for a
    *different* lesson does not count). The citation scan covers all following
    text, not just the budget-truncated slice.
    """
    token = f"[{lesson}]"
    text_parts: List[str] = []
    text_len = 0
    cited = False
    touched: List[str] = []
    touched_seen = set()
    bash_cmds: List[str] = []

    for info in infos[start + 1:]:
        if info.asst_text:
            if not cited and token in info.asst_text:
                cited = True
            if text_len < text_budget:
                text_parts.append(info.asst_text)
                text_len += len(info.asst_text) + 1
        for name, binput in info.tool_uses:
            if name in _FILE_TOOLS:
                fp = binput.get("file_path")
                if isinstance(fp, str) and fp and fp not in touched_seen:
                    touched_seen.add(fp)
                    touched.append(fp)
            elif name == "Bash":
                cmd = binput.get("command")
                if isinstance(cmd, str) and cmd and len(bash_cmds) < bash_limit:
                    bash_cmds.append(cmd[:bash_cmd_budget])

    following_text = "\n".join(text_parts)[:text_budget]
    return following_text, cited, touched, bash_cmds


# ---------------------------------------------------------------------------
# event-log side
# ---------------------------------------------------------------------------

@dataclass
class _SessionLog:
    """Per-session view of the event log: injected lessons and citations."""
    # lesson -> best (max) relevance score observed in the log
    injected: Dict[str, Optional[int]] = field(default_factory=dict)
    cited: set = field(default_factory=set)
    project: Optional[str] = None


def load_log(path: str) -> Dict[str, _SessionLog]:
    """Load relevance injections and citations from the event log by session.

    Only ``prompt_submit`` injections with a non-empty session count (SessionStart
    top-by-stars injections are duty reminders, not relevance claims).
    """
    sessions: Dict[str, _SessionLog] = {}
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            try:
                ev = json.loads(raw)
            except json.JSONDecodeError:
                continue
            etype = ev.get("type")
            session = ev.get("session") or ""
            lesson = ev.get("lesson")
            if not session or not lesson:
                continue
            sl = sessions.setdefault(session, _SessionLog())
            if etype == "injection":
                if ev.get("hook") != "prompt_submit":
                    continue
                score = ev.get("score")
                score = int(score) if isinstance(score, (int, float)) else None
                prev = sl.injected.get(lesson)
                if lesson not in sl.injected or (
                    score is not None and (prev is None or score > prev)
                ):
                    sl.injected[lesson] = score
                if sl.project is None:
                    sl.project = ev.get("project")
            elif etype == "citation":
                sl.cited.add(lesson)
                if sl.project is None:
                    sl.project = ev.get("project")
    return sessions


# ---------------------------------------------------------------------------
# per-session record extraction
# ---------------------------------------------------------------------------

def extract_session_records(
    transcript_path: str,
    session_id: str,
    slog: _SessionLog,
    text_budget: int = DEFAULT_TEXT_BUDGET,
    bash_limit: int = DEFAULT_BASH_LIMIT,
    bash_cmd_budget: int = DEFAULT_BASH_CMD_BUDGET,
) -> List[dict]:
    """Emit one judge record per event-log injected lesson in this session.

    Lesson text/title/relevance come from the transcript's injection attachment
    (authoritative). When a logged lesson has no matching attachment in the
    transcript (compaction, truncation), the record is still emitted with
    ``text_recovered=False`` and the session's earliest injection point is used
    to bound the "following" window.
    """
    infos, first_inj = _scan_transcript(transcript_path)

    # Earliest injection line in the whole transcript (fallback anchor).
    earliest_inj_line = min(
        (line for line, _ in first_inj.values()), default=-1
    )

    records: List[dict] = []
    for lesson in sorted(slog.injected):
        entry = first_inj.get(lesson)
        if entry is not None:
            inj_line, block = entry
            lesson_title = block.title
            lesson_text = block.text
            relevance = block.relevance
            text_recovered = bool(lesson_text)
        else:
            inj_line = earliest_inj_line
            lesson_title = ""
            lesson_text = ""
            relevance = slog.injected.get(lesson)
            text_recovered = False

        if relevance is None:
            relevance = slog.injected.get(lesson)

        following_text, cited_tx, touched, bash_cmds = _following_signals(
            infos, inj_line, lesson, text_budget, bash_limit, bash_cmd_budget
        )

        records.append({
            "session": session_id,
            "project": slog.project,
            "lesson": lesson,
            "lesson_title": lesson_title,
            "lesson_text": lesson_text,
            "relevance_score": relevance,
            "cited_in_log": lesson in slog.cited,
            "cited_in_transcript": cited_tx,
            "following_assistant_text": following_text,
            "touched_files": touched,
            "bash_commands": bash_cmds,
            "text_recovered": text_recovered,
        })
    return records


def extract_all(
    log_path: str,
    projects_dir: str,
    text_budget: int = DEFAULT_TEXT_BUDGET,
    bash_limit: int = DEFAULT_BASH_LIMIT,
    bash_cmd_budget: int = DEFAULT_BASH_CMD_BUDGET,
) -> Tuple[List[dict], dict]:
    """Extract judge records for every logged injection whose session has a
    transcript. Returns ``(records, summary)``."""
    sessions = load_log(log_path)
    index = build_transcript_index(projects_dir)

    records: List[dict] = []
    sessions_with_transcript = 0
    sessions_without_transcript = 0
    for session_id, slog in sessions.items():
        if not slog.injected:
            continue
        path = index.get(session_id)
        if not path:
            sessions_without_transcript += 1
            continue
        sessions_with_transcript += 1
        records.extend(extract_session_records(
            path, session_id, slog,
            text_budget=text_budget,
            bash_limit=bash_limit,
            bash_cmd_budget=bash_cmd_budget,
        ))

    cited_true = sum(1 for r in records if r["cited_in_log"])
    unrecovered = sum(1 for r in records if not r["text_recovered"])
    summary = {
        "total_records": len(records),
        "distinct_sessions": len({r["session"] for r in records}),
        "distinct_lessons": len({r["lesson"] for r in records}),
        "cited_in_log_true": cited_true,
        "cited_in_log_false": len(records) - cited_true,
        "text_unrecovered": unrecovered,
        "sessions_with_transcript": sessions_with_transcript,
        "sessions_without_transcript": sessions_without_transcript,
        "projects": sorted({r["project"] for r in records if r["project"]}),
    }
    return records, summary


def write_records(records: List[dict], out_path: str) -> None:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def format_summary(summary: dict) -> List[str]:
    lines = [
        f"judge records      : {summary['total_records']}",
        f"distinct sessions  : {summary['distinct_sessions']}",
        f"distinct lessons   : {summary['distinct_lessons']}",
        f"cited_in_log True  : {summary['cited_in_log_true']}",
        f"cited_in_log False : {summary['cited_in_log_false']}",
        f"text unrecovered   : {summary['text_unrecovered']}",
        f"sessions w/ transcript  : {summary['sessions_with_transcript']}",
        f"sessions w/o transcript : {summary['sessions_without_transcript']}",
        f"projects covered   : {len(summary['projects'])}",
    ]
    for p in summary["projects"]:
        lines.append(f"    - {p}")
    return lines


DEFAULT_OUT = os.path.join(os.path.dirname(__file__), "data", "judge_records.jsonl")


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(
        prog="python -m experiments.trust.extract_transcripts",
        description="Read-only: turn Claude Code transcripts into judge "
                    "records for an offline lesson-applied judge.",
    )
    parser.add_argument("--log", default=default_log_path(),
                        help="Path to session-log.jsonl")
    parser.add_argument("--projects", default=default_projects_dir(),
                        help="Root of ~/.claude/projects transcripts")
    parser.add_argument("--out", default=DEFAULT_OUT,
                        help="Output JSONL path for judge records")
    parser.add_argument("--text-budget", type=int, default=DEFAULT_TEXT_BUDGET,
                        help="Max chars of following assistant text per record")
    args = parser.parse_args(argv)

    if not os.path.exists(args.log):
        print(f"error: log not found: {args.log}")
        return 1
    if not os.path.isdir(args.projects):
        print(f"error: projects dir not found: {args.projects}")
        return 1

    records, summary = extract_all(
        args.log, args.projects, text_budget=args.text_budget
    )
    write_records(records, args.out)
    for line in format_summary(summary):
        print(line)
    print(f"records written to: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
