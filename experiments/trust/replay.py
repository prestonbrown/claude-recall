"""Replay the session log into a chronological, no-lookahead stream of
prediction events.

The raw log is JSONL, one event per line. Two event kinds matter:

    {"ts":..,"type":"injection","session":..,"lesson":"L066","hook":"prompt_submit",..}
    {"ts":..,"type":"citation","session":..,"lesson":"L060",..}

Only relevance-scored injections count toward trust: we keep ``injection``
events whose ``hook == "prompt_submit"`` and whose ``session`` is non-empty
(SessionStart top-by-stars injections are duty reminders, not relevance claims,
and are excluded per the design). All ``citation`` events are kept.

Labeling is per **(session, lesson)** pair, deduped so a lesson counts once per
session no matter how many times it was injected. A pair is ``cited`` iff a
citation for that lesson exists in the same session with a timestamp at or after
the lesson's *first* injection ts in that session (a citation cannot be caused
by a later injection).

The walk is **prequential**: sessions are visited in chronological order, and
each lesson's PredictionEvent is emitted using only the outcomes of *prior*
sessions before this session's outcome is folded into that lesson's history. No
formula ever sees the outcome it is being asked to predict.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Tuple

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

_TS_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[T ]"
    r"(\d{2}):(\d{2}):(\d{2})"
    r"(?:\.(\d+))?"
    r"(Z|[+-]\d{2}:?\d{2})?$"
)


def parse_ts(s: str) -> int:
    """Parse an ISO-8601 timestamp into epoch **nanoseconds** (int).

    Handles nanosecond fractional precision and tz offsets (including ``Z``),
    both of which the log emits and which ``datetime.fromisoformat`` cannot
    portably parse across Python versions. Timestamps are normalized to UTC so
    events logged under different offsets order correctly.
    """
    m = _TS_RE.match(s.strip())
    if not m:
        raise ValueError(f"unparseable timestamp: {s!r}")
    year, mon, day, hh, mm, ss, frac, off = m.groups()

    base = datetime(
        int(year), int(mon), int(day), int(hh), int(mm), int(ss),
        tzinfo=timezone.utc,
    )
    secs = int((base - _EPOCH).total_seconds())
    ns = int((frac + "000000000")[:9]) if frac else 0
    total = secs * 1_000_000_000 + ns

    if off and off != "Z":
        sign = 1 if off[0] == "+" else -1
        digits = off[1:].replace(":", "")
        offset_sec = sign * (int(digits[:2]) * 3600 + int(digits[2:]) * 60)
        total -= offset_sec * 1_000_000_000

    return total


@dataclass(frozen=True)
class LessonHistory:
    """Immutable snapshot of a lesson's *prior* outcomes at prediction time.

    ``outcomes`` is an ordered tuple of ``(ts_ns, hit)`` where ``hit`` is 1 if
    that prior injection was cited in its session, else 0. This is exactly what
    the estimators consume; the current event's own outcome is never included.
    """

    outcomes: Tuple[Tuple[int, int], ...] = ()

    @classmethod
    def from_hits(cls, hits: Iterable[int], start_ts: int = 0) -> "LessonHistory":
        """Build a history from a bare 0/1 sequence (timestamps auto-assigned)."""
        return cls(tuple((start_ts + i, int(h)) for i, h in enumerate(hits)))

    @property
    def injections(self) -> int:
        return len(self.outcomes)

    @property
    def cites(self) -> int:
        return sum(h for _, h in self.outcomes)

    @property
    def cite_ratio(self) -> float:
        return self.cites / self.injections if self.outcomes else 0.0


@dataclass(frozen=True)
class PredictionEvent:
    """One (session, relevance-injected lesson) pair to predict.

    ``ts`` is the lesson's first-injection ts in that session (epoch ns).
    ``history`` is the prior-only snapshot the estimators score.
    """

    lesson_id: str
    session_id: str
    ts: int
    cited: bool
    history: LessonHistory


def _load_events(path) -> Tuple[dict, dict]:
    """Read the JSONL log once.

    Returns ``(first_inj, cites)`` where:
      * ``first_inj[session][lesson]`` = earliest prompt_submit injection ts,
      * ``cites[session][lesson]``     = list of citation timestamps.
    """
    first_inj: dict = {}
    cites: dict = {}

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue

            etype = ev.get("type")
            session = ev.get("session") or ""
            lesson = ev.get("lesson")
            raw_ts = ev.get("ts")
            if not lesson or not raw_ts:
                continue

            if etype == "injection":
                if ev.get("hook") != "prompt_submit":
                    continue
                if not session:  # empty-session injections are dropped
                    continue
                ts = parse_ts(raw_ts)
                by_lesson = first_inj.setdefault(session, {})
                cur = by_lesson.get(lesson)
                if cur is None or ts < cur:
                    by_lesson[lesson] = ts

            elif etype == "citation":
                if not session:
                    continue
                ts = parse_ts(raw_ts)
                cites.setdefault(session, {}).setdefault(lesson, []).append(ts)

    return first_inj, cites


LabelOverride = Dict[Tuple[str, str], bool]


def replay(
    path,
    label_override: Optional[LabelOverride] = None,
) -> List[PredictionEvent]:
    """Replay ``path`` into a chronological, no-lookahead list of events.

    ``label_override`` optionally supplies an external ground truth for the
    ``cited`` field, keyed by ``(session_id, lesson_id)``. When a pair is present
    in the override its boolean value replaces the citation-derived label for
    both the emitted event AND the outcome folded into that lesson's future
    history; pairs absent from the override keep their citation-derived label.
    Timestamps, session ordering, and the prequential (no-lookahead) history
    walk are identical regardless of the override, so passing ``None`` (the
    default) reproduces the citation-labeled backtest byte-for-byte.
    """
    first_inj, cites = _load_events(path)

    # Order sessions by their earliest injection ts (chronological). Ties are
    # broken by session id for deterministic output.
    def session_key(session: str):
        return (min(first_inj[session].values()), session)

    ordered_sessions = sorted(first_inj.keys(), key=session_key)

    # Mutable running history per lesson: list of (ts, hit).
    running: dict = {}
    events: List[PredictionEvent] = []

    for session in ordered_sessions:
        lesson_ts = first_inj[session]
        session_cites = cites.get(session, {})

        # Emit in a stable order: by first-injection ts, then lesson id.
        for lesson in sorted(lesson_ts, key=lambda l: (lesson_ts[l], l)):
            inj_ts = lesson_ts[lesson]
            cite_tss = session_cites.get(lesson, ())
            cited = any(ct >= inj_ts for ct in cite_tss)
            if label_override is not None:
                override = label_override.get((session, lesson))
                if override is not None:
                    cited = bool(override)

            prior = running.get(lesson, ())
            history = LessonHistory(tuple(prior))
            events.append(PredictionEvent(
                lesson_id=lesson,
                session_id=session,
                ts=inj_ts,
                cited=cited,
                history=history,
            ))

            # Fold this session's outcome into the lesson's history AFTER the
            # prediction is emitted -- prequential, no lookahead.
            running[lesson] = prior + ((inj_ts, 1 if cited else 0),)

    return events


def _coerce_bool(v) -> Optional[bool]:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", "1", "yes", "applied", "y"):
            return True
        if s in ("false", "0", "no", "not_applied", "n"):
            return False
    return None


def _record_pair(obj: dict) -> Optional[Tuple[Tuple[str, str], bool]]:
    """Coerce one ``{session, lesson, applied}`` record into a label entry."""
    session = obj.get("session")
    lesson = obj.get("lesson")
    if not session or not lesson:
        return None
    raw = obj.get("applied")
    if raw is None:
        raw = obj.get("label", obj.get("cited"))
    label = _coerce_bool(raw)
    if label is None:
        return None
    return (str(session), str(lesson)), label


def load_label_file(path) -> LabelOverride:
    """Load an external ``(session, lesson) -> applied`` label file.

    Accepts three shapes so the offline judge can emit whichever is convenient:

    * ``.jsonl`` -- one ``{"session":..,"lesson":..,"applied":true}`` per line.
    * ``.json`` list -- an array of those same record objects.
    * ``.json`` object -- ``{"<session>|<lesson>": true, ...}`` (session ids are
      UUIDs and lesson ids are ``L###``/``S###``, so ``|`` is an unambiguous
      separator; the last ``|`` splits session from lesson).
    """
    labels: LabelOverride = {}

    def _add_obj(obj):
        pair = _record_pair(obj)
        if pair is not None:
            labels[pair[0]] = pair[1]

    with open(path, "r", encoding="utf-8") as f:
        text = f.read()

    stripped = text.lstrip()
    is_json = str(path).endswith(".json") or (
        not str(path).endswith(".jsonl") and stripped[:1] in ("[", "{")
    )

    if is_json:
        data = json.loads(text)
        if isinstance(data, list):
            for obj in data:
                if isinstance(obj, dict):
                    _add_obj(obj)
        elif isinstance(data, dict):
            for key, val in data.items():
                label = _coerce_bool(val)
                if label is None or "|" not in key:
                    continue
                session, lesson = key.rsplit("|", 1)
                if session and lesson:
                    labels[(session, lesson)] = label
        return labels

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            _add_obj(obj)
    return labels
