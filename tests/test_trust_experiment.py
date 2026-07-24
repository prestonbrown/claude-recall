"""Tests for the offline trust-model backtest harness (experiments/trust/).

Test-first: these describe the required behavior of replay labeling (no
lookahead), the candidate estimators, and the imbalance-aware metrics. All
inputs are synthetic in-memory logs written to a tmp .jsonl so the tests never
touch the real session log or any runtime state.
"""

import json
import math

import pytest

from experiments.trust import replay as R
from experiments.trust import estimators as E
from experiments.trust import evaluate as V
from experiments.trust import extract_transcripts as X


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _write_log(tmp_path, events):
    p = tmp_path / "log.jsonl"
    with p.open("w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")
    return p


def inj(ts, session, lesson, hook="prompt_submit", score=10):
    return {
        "ts": ts,
        "type": "injection",
        "session": session,
        "lesson": lesson,
        "score": score,
        "hook": hook,
        "project": "/p",
    }


def cit(ts, session, lesson):
    return {
        "ts": ts,
        "type": "citation",
        "session": session,
        "lesson": lesson,
        "project": "/p",
    }


def T(n):
    """A monotonic ISO-8601 timestamp with a tz offset (n seconds apart)."""
    hh = n // 3600
    mm = (n % 3600) // 60
    ss = n % 60
    return f"2026-01-01T{hh:02d}:{mm:02d}:{ss:02d}.000000000-04:00"


def hist(hits, start=0):
    """Build a LessonHistory from a list of 0/1 outcomes."""
    return R.LessonHistory.from_hits(hits, start_ts=start)


# --------------------------------------------------------------------------
# timestamp parsing
# --------------------------------------------------------------------------

class TestParseTs:
    def test_nanosecond_offset_parsed(self):
        a = R.parse_ts("2026-01-01T00:00:00.000000000-04:00")
        b = R.parse_ts("2026-01-01T00:00:01.000000000-04:00")
        assert b - a == 1_000_000_000

    def test_offset_normalized_to_utc(self):
        # Same instant expressed in two offsets must compare equal.
        a = R.parse_ts("2026-01-01T00:00:00.000000000-04:00")
        b = R.parse_ts("2026-01-01T04:00:00.000000000+00:00")
        assert a == b

    def test_zulu_suffix(self):
        a = R.parse_ts("2026-01-01T00:00:00Z")
        b = R.parse_ts("2026-01-01T00:00:00.500000000Z")
        assert b - a == 500_000_000


# --------------------------------------------------------------------------
# replay labeling
# --------------------------------------------------------------------------

class TestReplayLabeling:
    def test_injected_then_cited_same_session_is_cited(self, tmp_path):
        log = _write_log(tmp_path, [
            inj(T(0), "S1", "L1"),
            cit(T(10), "S1", "L1"),
        ])
        evs = R.replay(log)
        assert len(evs) == 1
        assert evs[0].lesson_id == "L1"
        assert evs[0].session_id == "S1"
        assert evs[0].cited is True

    def test_injected_never_cited_is_uncited(self, tmp_path):
        log = _write_log(tmp_path, [inj(T(0), "S1", "L2")])
        evs = R.replay(log)
        assert len(evs) == 1
        assert evs[0].cited is False

    def test_citation_before_injection_not_credited(self, tmp_path):
        # citation timestamp precedes the injection -> cannot be caused by it
        log = _write_log(tmp_path, [
            inj(T(100), "S1", "L1"),
            cit(T(50), "S1", "L1"),
        ])
        evs = R.replay(log)
        assert len(evs) == 1
        assert evs[0].cited is False

    def test_citation_at_exact_injection_ts_is_credited(self, tmp_path):
        log = _write_log(tmp_path, [
            inj(T(100), "S1", "L1"),
            cit(T(100), "S1", "L1"),
        ])
        evs = R.replay(log)
        assert evs[0].cited is True

    def test_three_injections_one_session_single_event(self, tmp_path):
        log = _write_log(tmp_path, [
            inj(T(0), "S1", "L1"),
            inj(T(1), "S1", "L1"),
            inj(T(2), "S1", "L1"),
        ])
        evs = R.replay(log)
        assert len(evs) == 1

    def test_first_injection_ts_used_for_credit_guard(self, tmp_path):
        # cite falls between the 2nd and 3rd injection but after the FIRST ->
        # credited, because the guard uses the earliest injection ts.
        log = _write_log(tmp_path, [
            inj(T(0), "S1", "L1"),
            inj(T(100), "S1", "L1"),
            cit(T(10), "S1", "L1"),
        ])
        evs = R.replay(log)
        assert evs[0].cited is True

    def test_empty_session_injection_dropped(self, tmp_path):
        log = _write_log(tmp_path, [inj(T(0), "", "L1")])
        evs = R.replay(log)
        assert evs == []

    def test_session_start_injection_excluded(self, tmp_path):
        log = _write_log(tmp_path, [
            inj(T(0), "S1", "L1", hook="session_start"),
            inj(T(1), "S1", "L2", hook="prompt_submit"),
        ])
        evs = R.replay(log)
        # only the prompt_submit lesson survives
        assert [e.lesson_id for e in evs] == ["L2"]

    def test_citation_only_credits_same_session(self, tmp_path):
        log = _write_log(tmp_path, [
            inj(T(0), "S1", "L1"),
            cit(T(10), "S2", "L1"),  # different session
        ])
        evs = R.replay(log)
        assert len(evs) == 1
        assert evs[0].cited is False

    def test_sessions_ordered_chronologically(self, tmp_path):
        # S_late has an earlier alphabetical id but a later first-injection ts.
        log = _write_log(tmp_path, [
            inj(T(500), "Aaa", "L1"),
            inj(T(10), "Zzz", "L1"),
        ])
        evs = R.replay(log)
        assert [e.session_id for e in evs] == ["Zzz", "Aaa"]


# --------------------------------------------------------------------------
# no lookahead / prequential history
# --------------------------------------------------------------------------

class TestNoLookahead:
    def test_first_prediction_sees_empty_history(self, tmp_path):
        log = _write_log(tmp_path, [inj(T(0), "S1", "L1")])
        evs = R.replay(log)
        assert evs[0].history.injections == 0
        assert evs[0].history.cites == 0

    def test_history_reflects_only_prior_sessions(self, tmp_path):
        # L1 across three sessions: S1 hit, S2 miss, S3 (predicted).
        log = _write_log(tmp_path, [
            inj(T(0), "S1", "L1"),
            cit(T(1), "S1", "L1"),        # S1 -> hit
            inj(T(100), "S2", "L1"),      # S2 -> miss
            inj(T(200), "S3", "L1"),      # S3 -> predicted
        ])
        evs = R.replay(log)
        by_session = {e.session_id: e for e in evs}

        # S1 is the first prediction: empty history.
        assert by_session["S1"].history.injections == 0
        # S2 sees only S1's outcome (a hit).
        assert by_session["S2"].history.injections == 1
        assert by_session["S2"].history.cites == 1
        # S3 sees S1 (hit) + S2 (miss) but NOT its own outcome.
        assert by_session["S3"].history.injections == 2
        assert by_session["S3"].history.cites == 1

    def test_event_outcome_absent_from_its_own_history(self, tmp_path):
        # A cited event must not have that citation folded into its history.
        log = _write_log(tmp_path, [
            inj(T(0), "S1", "L1"),
            cit(T(1), "S1", "L1"),
        ])
        evs = R.replay(log)
        assert evs[0].cited is True
        assert evs[0].history.cites == 0  # own outcome excluded


# --------------------------------------------------------------------------
# estimators
# --------------------------------------------------------------------------

class TestEstimators:
    def test_always_one(self):
        assert E.always_one(hist([]), 0) == 1.0
        assert E.always_one(hist([0, 0, 0, 0, 0, 0]), 0) == 1.0

    def test_smoothed_ratio_known_value(self):
        # C=3, I=10; (3+2)/(10+2+1) = 5/13
        h = hist([1, 1, 1, 0, 0, 0, 0, 0, 0, 0])
        f = E.smoothed_ratio(2, 1)
        assert f(h, 0) == pytest.approx(5 / 13)

    def test_smoothed_ratio_empty_history_is_prior_mean(self):
        f = E.smoothed_ratio(1, 1)
        assert f(hist([]), 0) == pytest.approx(0.5)

    def test_ema_known_sequence(self):
        # eta=0.5, init=0.0, sequence [1,0,1]:
        # 0 -> .5 -> .25 -> .625
        f = E.ema(0.5, init=0.0)
        assert f(hist([1, 0, 1]), 0) == pytest.approx(0.625)

    def test_ema_empty_history_returns_init(self):
        f = E.ema(0.3, init=0.42)
        assert f(hist([]), 0) == pytest.approx(0.42)

    def test_updown_clamps_at_floor(self):
        # init .5, -0.3 per miss, floor 0.1 -> .5,.2,.1(clamped),.1
        f = E.updown(u=0.2, d=0.3, floor=0.1, init=0.5)
        assert f(hist([0, 0, 0, 0, 0]), 0) == pytest.approx(0.1)

    def test_updown_clamps_at_one(self):
        f = E.updown(u=0.2, d=0.05, floor=0.0, init=0.9)
        assert f(hist([1, 1, 1]), 0) == pytest.approx(1.0)

    def test_updown_empty_history_returns_init(self):
        f = E.updown(u=0.2, d=0.05, floor=0.0, init=0.7)
        assert f(hist([]), 0) == pytest.approx(0.7)

    def test_binary_penalty_boundary_exact_ratio(self):
        # 5 injections, 1 cite -> ratio exactly 0.2 -> NOT penalized
        assert E.binary_penalty(hist([1, 0, 0, 0, 0]), 0) == 1.0

    def test_binary_penalty_below_ratio_and_enough_injections(self):
        # 5 injections, 0 cites -> ratio 0 (<0.2) -> penalized
        assert E.binary_penalty(hist([0, 0, 0, 0, 0]), 0) == 0.5

    def test_binary_penalty_too_few_injections(self):
        # 4 injections, 0 cites -> below the 5-injection floor -> not penalized
        assert E.binary_penalty(hist([0, 0, 0, 0]), 0) == 1.0

    def test_binary_penalty_more_injections_low_ratio(self):
        # 6 injections, 1 cite -> ratio 0.167 (<0.2) -> penalized
        assert E.binary_penalty(hist([1, 0, 0, 0, 0, 0]), 0) == 0.5

    def test_registry_all_return_unit_interval(self):
        h = hist([1, 0, 1, 0, 0])
        assert len(E.REGISTRY) >= 6
        for name, fn in E.REGISTRY.items():
            v = fn(h, 0)
            assert 0.0 <= v <= 1.0, f"{name} -> {v} out of [0,1]"

    def test_registry_contains_baselines(self):
        assert "always_one" in E.REGISTRY
        assert "binary_penalty" in E.REGISTRY


# --------------------------------------------------------------------------
# metrics
# --------------------------------------------------------------------------

class TestMetrics:
    def test_auc_perfect_separation(self):
        pairs = [(0.9, 1), (0.8, 1), (0.2, 0), (0.1, 0)]
        assert V.roc_auc(pairs) == pytest.approx(1.0)

    def test_auc_perfect_inversion(self):
        pairs = [(0.1, 1), (0.2, 1), (0.8, 0), (0.9, 0)]
        assert V.roc_auc(pairs) == pytest.approx(0.0)

    def test_auc_random_interleaved_is_half(self):
        # symmetric: each score value carries one pos and one neg
        pairs = [(0.6, 1), (0.6, 0), (0.4, 1), (0.4, 0)]
        assert V.roc_auc(pairs) == pytest.approx(0.5)

    def test_auc_all_tied_is_half(self):
        pairs = [(0.5, 1), (0.5, 0), (0.5, 1), (0.5, 0)]
        assert V.roc_auc(pairs) == pytest.approx(0.5)

    def test_known_ece_single_bin(self):
        # all predictions land in the 0.9 decile; empirical rate 0.5
        pairs = [(0.9, 1), (0.9, 1), (0.9, 0), (0.9, 0)]
        bins, ece = V.calibration(pairs, bins=10)
        assert ece == pytest.approx(0.4)

    def test_ece_perfectly_calibrated_is_zero(self):
        # bin 0.1 -> empirical 0.1; bin 0.9 -> empirical 0.9
        pairs = ([(0.1, 1)] + [(0.1, 0)] * 9) + ([(0.9, 1)] * 9 + [(0.9, 0)])
        bins, ece = V.calibration(pairs, bins=10)
        assert ece == pytest.approx(0.0, abs=1e-9)

    def test_operational_curve_monotonic_in_cutoff(self):
        pairs = [
            (0.05, 0), (0.1, 0), (0.3, 1), (0.4, 0),
            (0.5, 1), (0.7, 0), (0.8, 1), (0.95, 0),
        ]
        curve = V.tradeoff_curve(pairs)
        cs = [row["cutoff"] for row in curve]
        assert cs == sorted(cs)
        ns = [row["noise_suppressed"] for row in curve]
        sl = [row["signal_lost"] for row in curve]
        assert ns == sorted(ns), "noise_suppressed must be non-decreasing in c"
        assert sl == sorted(sl), "signal_lost must be non-decreasing in c"
        for row in curve:
            assert 0.0 <= row["noise_suppressed"] <= 1.0
            assert 0.0 <= row["signal_lost"] <= 1.0

    def test_noise_suppressed_at_zero_signal_lost(self):
        # positives strictly above 0.5, negatives strictly below:
        # a cutoff of 0.5 suppresses ALL noise while losing NO signal.
        pairs = [(0.1, 0), (0.2, 0), (0.3, 0), (0.9, 1), (0.8, 1)]
        s = V.summarize(pairs, tol=0.0)
        assert s == pytest.approx(1.0)

    def test_summarize_respects_signal_loss_tolerance(self):
        # 10 cited spread across trust; suppressing the lowest cited one
        # costs 10% signal. At tol=0.0 we cannot touch it; at tol=0.1 we can.
        cited = [(t, 1) for t in [0.05, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95]]
        uncited = [(t, 0) for t in [0.01, 0.02, 0.03, 0.04, 0.06]]
        pairs = cited + uncited
        # tol 0: cannot suppress below 0.05 (would lose the 0.05 citation),
        # so only uncited with trust < 0.05 (0.01..0.04 => 4 of 5) suppressed.
        s0 = V.summarize(pairs, tol=0.0)
        assert s0 == pytest.approx(4 / 5)
        # tol 0.1: may lose the single 0.05 citation, letting cutoff rise to
        # just above 0.06 and suppress all 5 uncited.
        s1 = V.summarize(pairs, tol=0.1)
        assert s1 == pytest.approx(1.0)

    def test_lift_at_top_decile(self):
        # 10 events, 1 citation, and it sits in the top-trust decile ->
        # top-decile cite rate 1.0 vs overall 0.1 -> lift 10x
        pairs = [(0.99, 1)] + [(0.1 * i, 0) for i in range(1, 10)]
        assert V.lift_at_decile(pairs) == pytest.approx(10.0)


# --------------------------------------------------------------------------
# end-to-end on a synthetic log
# --------------------------------------------------------------------------

class TestEndToEnd:
    def test_report_runs_on_synthetic_log(self, tmp_path):
        from experiments.trust import report

        events = []
        t = 0
        # A "good" lesson: cited most sessions. A "noise" lesson: never cited.
        for s in range(20):
            t += 100
            events.append(inj(T(t), f"S{s}", "GOOD"))
            if s % 2 == 0:
                events.append(cit(T(t + 1), f"S{s}", "GOOD"))
            events.append(inj(T(t + 2), f"S{s}", "NOISE"))
        log = _write_log(tmp_path, events)

        evs = R.replay(log)
        assert len(evs) == 40  # 20 sessions x 2 lessons

        results = report.evaluate_all(evs)
        # every registered estimator produced a metrics row
        assert set(results.keys()) == set(E.REGISTRY.keys())
        for name, row in results.items():
            assert "auc" in row and "ece" in row
            assert "noise_at_1pct" in row and "noise_at_5pct" in row


# --------------------------------------------------------------------------
# transcript extractor
# --------------------------------------------------------------------------

# A valid 36-char UUID basename so build_transcript_index picks it up.
_SESSION_UUID = "01688767-7f74-4167-abcf-71d2466e5956"


def _attachment_content(*blocks):
    """Build a RELEVANT LESSONS attachment content string.

    Each block is (lesson, stars, relevance, title, body). The body may contain
    newlines; the first line is arrow-prefixed exactly as the hook emits it.
    """
    parts = ["RELEVANT LESSONS for your query:"]
    for lesson, stars, rel, title, body in blocks:
        parts.append(f"[{lesson}] {stars} (relevance: {rel}/10) {title}")
        body_lines = body.split("\n")
        parts.append("    -> " + body_lines[0])
        parts.extend(body_lines[1:])
    parts.append("")
    parts.append("Cite [ID] when applying. LESSON: [category:] title - content")
    return "\n".join(parts)


def _inj_line(*blocks):
    return {"attachment": {
        "type": "hook_additional_context",
        "hookName": "UserPromptSubmit",
        "hookEvent": "UserPromptSubmit",
        "content": [_attachment_content(*blocks)],
    }}


def _asst_text_line(text):
    return {"message": {"role": "assistant",
                        "content": [{"type": "text", "text": text}]}}


def _tool_line(name, **input_kwargs):
    return {"message": {"role": "assistant", "content": [
        {"type": "tool_use", "name": name, "input": dict(input_kwargs)}]}}


def _user_line(text):
    return {"message": {"role": "user", "content": text}}


def _write_transcript(projects_dir, session_id, lines):
    slug_dir = projects_dir / "-home-pbrown-Code-demo"
    slug_dir.mkdir(parents=True, exist_ok=True)
    p = slug_dir / f"{session_id}.jsonl"
    with p.open("w") as f:
        for ln in lines:
            f.write(json.dumps(ln) + "\n")
    return p


class TestParseInjectionBlocks:
    def test_parses_multiple_blocks_verbatim(self):
        content = _attachment_content(
            ("L001", "⭐⭐", 8, "Title one", "Body one line1\nBody one line2"),
            ("L002", "⭐", 3, "Title two", "Body two"),
        )
        blocks = X.parse_injection_blocks(content)
        assert [b.lesson for b in blocks] == ["L001", "L002"]
        assert blocks[0].title == "Title one"
        assert blocks[0].relevance == 8
        # arrow prefix stripped, multi-line body preserved verbatim
        assert blocks[0].text == "Body one line1\nBody one line2"
        assert blocks[1].text == "Body two"
        assert blocks[1].relevance == 3

    def test_footer_excluded_from_body(self):
        content = _attachment_content(
            ("L001", "⭐", 5, "T", "the body"),
        )
        blocks = X.parse_injection_blocks(content)
        assert blocks[0].text == "the body"
        assert "Cite [ID]" not in blocks[0].text


class TestExtractor:
    def _slog(self, injected, cited, project="/home/pbrown/Code/demo"):
        return X._SessionLog(
            injected=dict(injected), cited=set(cited), project=project
        )

    def test_record_fields_and_ordering(self, tmp_path):
        projects = tmp_path / "projects"
        lines = [
            _user_line("please help"),
            # citation-looking token BEFORE injection must not count
            _asst_text_line("earlier note mentioning [L001] before injection"),
            _tool_line("Read", file_path="/before/only.py"),
            _inj_line(
                ("L001", "⭐⭐", 8, "Title one", "Body one A\nBody one B"),
                ("L002", "⭐", 3, "Title two", "Body two"),
            ),
            _asst_text_line("Applying [L001] to the fix now."),
            _tool_line("Edit", file_path="/after/foo.py"),
            _tool_line("Write", file_path="/after/bar.py"),
            _tool_line("Edit", file_path="/after/foo.py"),  # dup -> unique
            _tool_line("Bash", command="git commit -m wip"),
            _tool_line("Bash", command="./run-tests.sh"),
        ]
        path = _write_transcript(projects, _SESSION_UUID, lines)

        slog = self._slog(
            injected={"L001": 8, "L002": 3},
            cited={"L001"},  # cited_in_log for L001
        )
        recs = X.extract_session_records(str(path), _SESSION_UUID, slog)
        by = {r["lesson"]: r for r in recs}
        assert set(by) == {"L001", "L002"}

        r1 = by["L001"]
        # lesson_text parsed verbatim from the attachment (arrow stripped)
        assert r1["lesson_text"] == "Body one A\nBody one B"
        assert r1["lesson_title"] == "Title one"
        assert r1["relevance_score"] == 8
        assert r1["text_recovered"] is True
        assert r1["cited_in_log"] is True
        # [L001] appears in assistant text AFTER injection -> cited_in_transcript
        assert r1["cited_in_transcript"] is True
        # following text excludes the pre-injection turn
        assert "before injection" not in r1["following_assistant_text"]
        assert "Applying [L001]" in r1["following_assistant_text"]
        # touched_files gathered from tool_use AFTER injection, unique, and the
        # pre-injection Read is excluded
        assert r1["touched_files"] == ["/after/foo.py", "/after/bar.py"]
        assert "/before/only.py" not in r1["touched_files"]
        # bash commands captured (outcome signals)
        assert r1["bash_commands"] == ["git commit -m wip", "./run-tests.sh"]

        # L002 was never cited anywhere after injection
        r2 = by["L002"]
        assert r2["cited_in_log"] is False
        assert r2["cited_in_transcript"] is False

    def test_cited_only_before_injection_is_false(self, tmp_path):
        projects = tmp_path / "projects"
        lines = [
            _asst_text_line("mentioning [L001] way before"),
            _inj_line(("L001", "⭐", 5, "T", "body")),
            _asst_text_line("no citation token in this later turn"),
        ]
        path = _write_transcript(projects, _SESSION_UUID, lines)
        slog = self._slog(injected={"L001": 5}, cited=set())
        recs = X.extract_session_records(str(path), _SESSION_UUID, slog)
        assert recs[0]["cited_in_transcript"] is False

    def test_text_budget_truncates_following(self, tmp_path):
        projects = tmp_path / "projects"
        big = "x" * 5000
        lines = [
            _inj_line(("L001", "⭐", 5, "T", "body")),
            _asst_text_line(big),
            _asst_text_line(big),
        ]
        path = _write_transcript(projects, _SESSION_UUID, lines)
        slog = self._slog(injected={"L001": 5}, cited=set())
        recs = X.extract_session_records(
            str(path), _SESSION_UUID, slog, text_budget=6000
        )
        assert len(recs[0]["following_assistant_text"]) == 6000

    def test_logged_lesson_missing_from_transcript(self, tmp_path):
        projects = tmp_path / "projects"
        lines = [
            _inj_line(("L001", "⭐", 5, "T", "body")),
            _asst_text_line("work happens"),
        ]
        path = _write_transcript(projects, _SESSION_UUID, lines)
        # L009 is in the event log but has no attachment in the transcript
        slog = self._slog(injected={"L001": 5, "L009": 7}, cited=set())
        recs = X.extract_session_records(str(path), _SESSION_UUID, slog)
        by = {r["lesson"]: r for r in recs}
        assert by["L009"]["text_recovered"] is False
        assert by["L009"]["lesson_text"] == ""
        # relevance falls back to the event-log score
        assert by["L009"]["relevance_score"] == 7

    def test_extract_all_end_to_end(self, tmp_path):
        projects = tmp_path / "projects"
        _write_transcript(projects, _SESSION_UUID, [
            _inj_line(("L001", "⭐", 9, "Env", "the body text")),
            _asst_text_line("Using [L001]."),
            _tool_line("Edit", file_path="/x/y.py"),
        ])
        # a second logged session with NO transcript on disk -> skipped
        log = _write_log(tmp_path, [
            inj(T(0), _SESSION_UUID, "L001", score=9),
            cit(T(5), _SESSION_UUID, "L001"),
            inj(T(1), "no-transcript-session", "L001"),
        ])
        records, summary = X.extract_all(str(log), str(projects))
        assert summary["total_records"] == 1
        assert summary["distinct_sessions"] == 1
        assert summary["cited_in_log_true"] == 1
        assert summary["sessions_without_transcript"] == 1
        r = records[0]
        assert r["session"] == _SESSION_UUID
        assert r["lesson"] == "L001"
        assert r["lesson_text"] == "the body text"
        assert r["cited_in_log"] is True
        assert r["cited_in_transcript"] is True
        assert r["touched_files"] == ["/x/y.py"]


# --------------------------------------------------------------------------
# external label override
# --------------------------------------------------------------------------

class TestLabelOverride:
    def _log(self, tmp_path):
        # L1 cited in S1 (citation-derived True), never cited in S2.
        return _write_log(tmp_path, [
            inj(T(0), "S1", "L1"),
            cit(T(1), "S1", "L1"),
            inj(T(100), "S2", "L1"),
        ])

    def test_default_matches_citation_labels(self, tmp_path):
        log = self._log(tmp_path)
        evs = R.replay(log)
        by = {e.session_id: e for e in evs}
        assert by["S1"].cited is True
        assert by["S2"].cited is False

    def test_override_flips_label(self, tmp_path):
        log = self._log(tmp_path)
        # Flip S1/L1 from cited->False and S2/L1 from uncited->True.
        override = {("S1", "L1"): False, ("S2", "L1"): True}
        evs = R.replay(log, label_override=override)
        by = {e.session_id: e for e in evs}
        assert by["S1"].cited is False
        assert by["S2"].cited is True

    def test_override_folds_into_future_history_no_lookahead(self, tmp_path):
        log = self._log(tmp_path)
        override = {("S1", "L1"): False, ("S2", "L1"): True}
        evs = R.replay(log, label_override=override)
        by = {e.session_id: e for e in evs}
        # ordering preserved (S1 before S2)
        assert [e.session_id for e in evs] == ["S1", "S2"]
        # S1 predicted with empty history (no lookahead into its own outcome)
        assert by["S1"].history.injections == 0
        # S2 sees S1's OVERRIDDEN outcome (now a miss), not the citation hit
        assert by["S2"].history.injections == 1
        assert by["S2"].history.cites == 0
        # and S2's own overridden outcome is not folded into its own history
        assert by["S2"].cited is True

    def test_partial_override_keeps_citation_label_for_absent_pairs(self, tmp_path):
        log = self._log(tmp_path)
        # Only override S2; S1 keeps its citation-derived True.
        evs = R.replay(log, label_override={("S2", "L1"): True})
        by = {e.session_id: e for e in evs}
        assert by["S1"].cited is True
        assert by["S2"].cited is True

    def test_load_label_file_jsonl(self, tmp_path):
        p = tmp_path / "labels.jsonl"
        p.write_text(
            json.dumps({"session": "S1", "lesson": "L1", "applied": False}) + "\n"
            + json.dumps({"session": "S2", "lesson": "L1", "applied": True}) + "\n"
        )
        labels = R.load_label_file(str(p))
        assert labels == {("S1", "L1"): False, ("S2", "L1"): True}

    def test_load_label_file_json_object(self, tmp_path):
        p = tmp_path / "labels.json"
        p.write_text(json.dumps({"S1|L1": False, "S2|L1": True}))
        labels = R.load_label_file(str(p))
        assert labels == {("S1", "L1"): False, ("S2", "L1"): True}

    def test_load_label_file_json_list(self, tmp_path):
        p = tmp_path / "labels.json"
        p.write_text(json.dumps([
            {"session": "S1", "lesson": "L1", "applied": True},
        ]))
        labels = R.load_label_file(str(p))
        assert labels == {("S1", "L1"): True}

    def test_main_labels_flag_changes_base_rate(self, tmp_path, capsys):
        from experiments.trust import __main__ as M
        log = self._log(tmp_path)
        # Flip the single citation off -> base cite rate should drop to 0.
        labels = tmp_path / "labels.jsonl"
        labels.write_text(
            json.dumps({"session": "S1", "lesson": "L1", "applied": False}) + "\n"
        )
        out_dir = tmp_path / "out"
        rc = M.main(["--log", str(log), "--labels", str(labels),
                     "--out", str(out_dir)])
        assert rc == 0
        captured = capsys.readouterr().out
        assert "loaded 1 external labels" in captured
        assert "cited events      : 0" in captured
