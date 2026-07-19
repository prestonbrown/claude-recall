#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
End-to-end tests proving the OpenCode adapter works inside a LIVE opencode
session - not just structurally, but with a real `opencode` subprocess, a real
model, and the real plugin loaded from an isolated HOME.

Hermetic strategy:
  - Fixture HOME (tmp): plugins/lessons.ts + plugins/lib/memory.ts copied from
    the repo, command/*.md, node_modules symlinked from the real global config
    (read-only), auth.json COPIED from the real data dir (never printed,
    shredded on teardown).
  - Fixture project (tmp): git repo with a .gitignore ("*") so nothing leaks;
    .claude-recall/LESSONS.md holds a lesson whose title carries a UNIQUE
    marker; an active handoff (created via the recall CLI) carries another.
  - Fixture MEMORY.md at ~/.claude/projects/<hash>/memory/MEMORY.md where
    <hash> = cwd with '/' and '.' replaced by '-' (mirrors lib/memory.ts);
    plus a deep-read memory file (marker NOT in the index) and a decoy.
  - Plugin config via CLAUDE_RECALL_CONFIG, state via CLAUDE_RECALL_STATE
    (debug.log lands at <state>/claude-recall/debug.log as JSON lines).

Assertions only inspect ARTIFACTS: debug.log JSON events, the opencode.db
sqlite part table, and CLI stdout - never model prose.

Skipped gracefully when prerequisites are missing (opencode/recall binaries,
provider auth, model availability, global node_modules).

Run with: ./run-tests.sh e2e      (or: pytest tests/test_opencode_e2e.py -m e2e)
Model override: E2E_MODEL=provider/model (default: moonshotai/kimi-k3)
"""

import json
import os
import re
import shutil
import signal
import socket
import sqlite3
import subprocess
import time
import urllib.request
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.e2e

PROJECT_ROOT = Path(__file__).parent.parent
E2E_MODEL = os.environ.get("E2E_MODEL", "moonshotai/kimi-k3")

OPENCODE = shutil.which("opencode")
RECALL = shutil.which("recall")
CLAUDE_RECALL_WRAPPER = PROJECT_ROOT / "bin" / "claude-recall"
REPO_GO_RECALL = PROJECT_ROOT / "go" / "bin" / "recall"

_REAL_DATA_HOME = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
REAL_AUTH_JSON = _REAL_DATA_HOME / "opencode" / "auth.json"
_REAL_CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
REAL_NODE_MODULES = _REAL_CONFIG_HOME / "opencode" / "node_modules"
REAL_PACKAGE_JSON = _REAL_CONFIG_HOME / "opencode" / "package.json"

# Unique markers per test session - collisions with real data are impossible.
LESSON_MARKER = f"E2ELESSON-{uuid.uuid4().hex[:12].upper()}"
MEMORY_MARKER = f"E2EMEMORY-{uuid.uuid4().hex[:12].upper()}"
HANDOFF_MARKER = f"E2EHANDOFF-{uuid.uuid4().hex[:12].upper()}"
# Deep-read / write-bridge markers are DASH-FREE on purpose: the Go lesson
# regex splits `LESSON: <title> - <content>` at the first ' - ', and the
# write-bridge slugifier turns non-alnum runs into dashes - a dashed marker
# would make the expected filename ambiguous.
DEEP_MEMORY_MARKER = f"E2EDEEP{uuid.uuid4().hex[:12].upper()}"
BRIDGE_MARKER = f"E2EBRIDGE{uuid.uuid4().hex[:12].upper()}"
BRIDGE_TITLE = f"e2e opencode bridge {BRIDGE_MARKER}"
BRIDGE_CONTENT = f"bridged body {BRIDGE_MARKER}"

PROMPT = "Reply with exactly: PONG"


# =============================================================================
# Fixture environment
# =============================================================================


def _plugin_hash(cwd: str) -> str:
    """Mirror of memoryDir() in adapters/opencode/lib/memory.ts."""
    return re.sub(r"[/.]", "-", cwd)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def fx(tmp_path_factory):
    """Build the hermetic fixture (module-scoped; shredded on teardown)."""
    if not OPENCODE:
        pytest.skip("opencode binary not found on PATH")
    if not RECALL:
        pytest.skip("recall Go binary not found on PATH")
    if not CLAUDE_RECALL_WRAPPER.exists():
        pytest.skip("bin/claude-recall wrapper not found in repo")
    if not REAL_AUTH_JSON.exists():
        pytest.skip(f"no opencode provider auth at {REAL_AUTH_JSON}")
    if not REAL_NODE_MODULES.exists():
        pytest.skip(f"global opencode node_modules not found at {REAL_NODE_MODULES}")

    root = tmp_path_factory.mktemp("opencode-e2e")
    home = root / "home"
    state = root / "state"
    proj = root / "proj"
    fixture_bin = root / "bin"
    for d in (home, state, proj, fixture_bin):
        d.mkdir(parents=True)

    # --- fixture project: git repo, everything ignored ---
    proj.joinpath(".gitignore").write_text("*\n")
    if shutil.which("git"):
        subprocess.run(["git", "init", "-q"], cwd=proj, check=False,
                       capture_output=True)

    # --- fixture lessons store (project level), unique marker in title ---
    recall_dir = proj / ".claude-recall"
    recall_dir.mkdir()
    recall_dir.joinpath("LESSONS.md").write_text(f"""# LESSONS.md - Project Level

## Active Lessons

### [L001] [*****|-----] E2E Lesson {LESSON_MARKER}
- **Uses**: 9 | **Velocity**: 1.0 | **Learned**: 2026-07-19 | **Last**: 2026-07-19 | **Category**: pattern | **Type**: informational
> Lesson content for live e2e injection proof. Marker: {LESSON_MARKER}.
""")

    # --- fixture MEMORY.md at the plugin-hashed location ---
    mem_dir = home / ".claude" / "projects" / _plugin_hash(str(proj)) / "memory"
    mem_dir.mkdir(parents=True)
    mem_dir.joinpath("MEMORY.md").write_text(
        f"# Project memory\n\nUnique e2e memory marker: {MEMORY_MARKER}.\n")

    # --- deep-read fixture: a memory file whose marker is NOT in the MEMORY.md
    # index (only ranking the actual file content can surface it), plus a
    # zero-overlap decoy to prove ranking picks the right file ---
    mem_dir.joinpath("reference_zorblaxflange.md").write_text(f"""---
name: Zorblaxflange recalibration
description: Recalibrate the zorblaxflange housing before cold starts
type: reference
---

The zorblaxflange recalibration ritual ({DEEP_MEMORY_MARKER}): drain the
coolant loop, then recalibrate the zorblaxflange housing counterclockwise
until the gauge reads zero. Never recalibrate a hot zorblaxflange.
""")
    mem_dir.joinpath("reference_knitting_decoy.md").write_text(
        "Garter stitch scarf patterns: cast on forty stitches and knit "
        "every row until winter ends.\n")

    # --- plugin config (debugLevel 3: capture info+debug events) ---
    plugin_config = root / "plugin-config.json"
    plugin_config.write_text(json.dumps({
        "enabled": True, "topLessonsToShow": 5, "relevanceTopN": 5,
        "remindEvery": 12, "debugLevel": 3, "memoryMaxBytes": 8192,
    }))

    # --- fixture opencode config dir ---
    oc = home / ".config" / "opencode"
    (oc / "plugins" / "lib").mkdir(parents=True)
    (oc / "command").mkdir()
    shutil.copy2(PROJECT_ROOT / "adapters" / "opencode" / "plugin.ts",
                 oc / "plugins" / "lessons.ts")
    shutil.copy2(PROJECT_ROOT / "adapters" / "opencode" / "lib" / "memory.ts",
                 oc / "plugins" / "lib" / "memory.ts")
    for cmd in ("lessons.md", "handoffs.md"):
        shutil.copy2(PROJECT_ROOT / "adapters" / "opencode" / "command" / cmd,
                     oc / "command" / cmd)
    if REAL_PACKAGE_JSON.exists():
        shutil.copy2(REAL_PACKAGE_JSON, oc / "package.json")
    os.symlink(REAL_NODE_MODULES, oc / "node_modules")
    oc.joinpath("opencode.json").write_text(json.dumps({
        "$schema": "https://opencode.ai/config.json",
        "permission": {
            "bash": "allow",
            "edit": "allow",
            "read": "allow",
            "external_directory": "allow",
        },
    }))

    # --- auth isolation: COPY the real auth.json into the fixture data dir ---
    data_dir = home / ".local" / "share" / "opencode"
    data_dir.mkdir(parents=True)
    auth_copy = data_dir / "auth.json"
    shutil.copy2(REAL_AUTH_JSON, auth_copy)
    auth_copy.chmod(0o600)

    # --- claude-recall wrapper: symlink into the repo so its dev-mode
    # detection finds core/ and go/bin/recall ---
    os.symlink(CLAUDE_RECALL_WRAPPER, fixture_bin / "claude-recall")

    # --- subprocess environment (fully replaced, like env -i) ---
    path_dirs = [
        str(fixture_bin),
        str(Path(OPENCODE).parent),
        str(Path(RECALL).parent),
        "/usr/local/bin", "/usr/bin", "/bin",
    ]
    env = {
        "HOME": str(home),
        "PATH": ":".join(path_dirs),
        "CLAUDE_RECALL_CONFIG": str(plugin_config),
        "CLAUDE_RECALL_STATE": str(state),
    }

    # --- fixture handoff via the recall CLI (exercises the real writer) ---
    handoff_env = {**env, "PROJECT_DIR": str(proj)}
    hr = subprocess.run(
        [RECALL, "handoff", "add", f"E2E Handoff {HANDOFF_MARKER}",
         "--desc", f"handoff description marker {HANDOFF_MARKER}"],
        env=handoff_env, capture_output=True, text=True, timeout=30)
    if hr.returncode != 0:
        pytest.skip(f"could not create fixture handoff: {hr.stderr.strip()}")

    # --- model availability (with the fixture's copied auth) ---
    mr = subprocess.run([OPENCODE, "models"], env=env, cwd=proj,
                        capture_output=True, text=True, timeout=60)
    if mr.returncode != 0 or E2E_MODEL not in mr.stdout:
        pytest.skip(f"model {E2E_MODEL} not available (set E2E_MODEL); "
                    f"`opencode models` rc={mr.returncode}")

    ns = SimpleNamespace(
        root=root, home=home, state=state, proj=proj, env=env,
        db_path=data_dir / "opencode.db",
        log_path=state / "claude-recall" / "debug.log",
        auth_copy=auth_copy,
        mem_dir=mem_dir,
    )
    yield ns

    # teardown: shred the copied credentials, then let pytest remove the tree
    try:
        if auth_copy.exists():
            auth_copy.write_bytes(b"\0" * auth_copy.stat().st_size)
            auth_copy.unlink()
    except OSError:
        pass


# =============================================================================
# Artifact helpers (debug.log JSON events, opencode.db parts, CLI stdout)
# =============================================================================


def _log_size(fx) -> int:
    try:
        return fx.log_path.stat().st_size
    except OSError:
        return 0


def _read_events(fx, since: int = 0) -> list[dict]:
    """Read JSON log events appended after byte offset `since`."""
    if not fx.log_path.exists():
        return []
    with open(fx.log_path, "rb") as fh:
        fh.seek(since)
        out = []
        for line in fh.read().decode("utf-8", "replace").splitlines():
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return out


def _events_by_name(events: list[dict]) -> dict[str, list[dict]]:
    by: dict[str, list[dict]] = {}
    for e in events:
        by.setdefault(e.get("event", "?"), []).append(e)
    return by


def _parts_since(fx, epoch_ms: int) -> list[str]:
    """All persisted part payloads (JSON strings) created at/after epoch_ms."""
    if not fx.db_path.exists():
        return []
    uri = f"file:{fx.db_path}?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        rows = db.execute(
            "SELECT data FROM part WHERE time_created >= ?", (epoch_ms,)
        ).fetchall()
    return [r[0] for r in rows]


def _run(fx, args: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run([OPENCODE, *args], cwd=fx.proj, env=fx.env,
                          capture_output=True, text=True, timeout=timeout)


def _run_cooperative(fx, args: list[str], attempts: int = 3,
                     timeout: int = 300) -> subprocess.CompletedProcess:
    """Retry up to 2x (3 attempts) when the model/run does not cooperate."""
    last = None
    for _ in range(attempts):
        last = _run(fx, args, timeout=timeout)
        if last.returncode == 0:
            return last
    return last


def _now_ms() -> int:
    return int(time.time() * 1000)


# =============================================================================
# Scenario a: session-start injection (lessons store read, context injected)
# =============================================================================


def test_session_start_injects_lessons(fx):
    offset = _log_size(fx)
    t0 = _now_ms()
    r = _run_cooperative(fx, ["run", "-m", E2E_MODEL, PROMPT])
    assert r.returncode == 0, f"opencode run failed: {r.stderr[-500:]}"

    by = _events_by_name(_read_events(fx, offset))

    # plugin loaded + session initialized, lessons store read
    assert "plugin.loaded" in by, "plugin never loaded"
    assert "session.start" in by, "session.start never logged"

    built = by.get("session.context_built", [])
    assert built, "session.context_built never logged"
    sections = built[-1].get("sections", [])
    assert "lessons" in sections, f"lessons section missing from {sections}"
    assert "duties" in sections, f"duties section missing from {sections}"

    # context actually pushed into the system prompt
    inj = by.get("system.transform_injected", [])
    assert inj, "system.transform_injected never logged - injection unproven"
    assert inj[-1].get("has_lessons") is True

    # the unique lesson marker is inside the injected context
    content = "\n".join(e.get("content", "")
                        for e in by.get("system.transform_content", []))
    assert LESSON_MARKER in content, \
        "fixture lesson marker absent from injected session-start context"

    # first-prompt relevance injection produced a synthetic part (persisted)
    assert "chat.smart_injected" in by, "first-prompt score-relevance never injected"
    parts = _parts_since(fx, t0)
    assert any("<relevant-lessons>" in p for p in parts), \
        "synthetic relevant-lessons part not persisted in opencode.db"


# =============================================================================
# Scenario b: MEMORY.md injection (Claude Code auto-memory)
# =============================================================================


def test_memory_md_injected(fx):
    offset = _log_size(fx)
    r = _run_cooperative(fx, ["run", "-m", E2E_MODEL, PROMPT])
    assert r.returncode == 0, f"opencode run failed: {r.stderr[-500:]}"

    by = _events_by_name(_read_events(fx, offset))

    loaded = by.get("memory.loaded", [])
    assert loaded, "memory.loaded never logged"
    assert loaded[-1].get("bytes", 0) > 0

    inj = by.get("system.transform_injected", [])
    assert inj and inj[-1].get("has_memory") is True, \
        "system transform did not include the claude-memory section"

    content = "\n".join(e.get("content", "")
                        for e in by.get("system.transform_content", []))
    assert "<claude-memory>" in content
    assert MEMORY_MARKER in content, \
        "fixture MEMORY.md marker absent from injected context"


# =============================================================================
# Scenario c: compaction (experimental.session.compacting + session.compacted)
# =============================================================================


def _http_json(url: str, payload: dict | None, timeout: int = 300):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode()
    return json.loads(body) if body else None


def test_compaction_hooks_fire(fx):
    provider, _, model = E2E_MODEL.partition("/")
    assert provider and model, f"E2E_MODEL must be provider/model, got {E2E_MODEL}"
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen(
        [OPENCODE, "serve", "--port", str(port), "--hostname", "127.0.0.1"],
        cwd=fx.proj, env=fx.env, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True)
    try:
        # wait for the server (up to 60s; model warmup can be slow)
        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                urllib.request.urlopen(f"{base}/session?directory={fx.proj}",
                                       timeout=3)
                break
            except Exception:
                if proc.poll() is not None:
                    pytest.fail(f"opencode serve exited early rc={proc.returncode}")
                time.sleep(1)
        else:
            pytest.fail("opencode serve never came up")

        offset = _log_size(fx)

        sid = _http_json(f"{base}/session?directory={fx.proj}",
                         {"title": "e2e-compaction"}, timeout=30)["id"]
        _http_json(f"{base}/session/{sid}/message?directory={fx.proj}",
                   {"model": {"providerID": provider, "modelID": model},
                    "parts": [{"type": "text", "text": PROMPT}]}, timeout=300)
        _http_json(f"{base}/session/{sid}/summarize?directory={fx.proj}",
                   {"providerID": provider, "modelID": model}, timeout=300)

        # compaction is async - poll the log for the end event
        by: dict[str, list[dict]] = {}
        deadline = time.time() + 120
        while time.time() < deadline:
            by = _events_by_name(_read_events(fx, offset))
            if "compaction.end" in by:
                break
            time.sleep(2)

        assert "compaction.start" in by, \
            "experimental.session.compacting hook never fired"
        assert "compaction.context_injected" in by, \
            "pre-compact context was never pushed to output.context"
        content = "\n".join(e.get("content", "")
                            for e in by.get("compaction.context_content", []))
        assert HANDOFF_MARKER in content, \
            "active handoff marker absent from pre-compact context"
        assert "compaction.end" in by, \
            "session.compacted event never fired post-compact handler"
    finally:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=15)
        except Exception:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except Exception:
                pass


# =============================================================================
# Scenario d: /lessons native command (model runs the CLI itself)
# =============================================================================


def test_lessons_command_executes_cli(fx):
    t0 = _now_ms()
    r = _run_cooperative(fx, ["run", "-m", E2E_MODEL, "--command", "lessons"])
    assert r.returncode == 0, f"opencode run --command lessons failed: {r.stderr[-500:]}"

    # CLI output is an artifact: `claude-recall list` prints the fixture lesson
    # (unique marker in its title) to stdout.
    combined = r.stdout + r.stderr
    assert LESSON_MARKER in combined, \
        "fixture lesson not listed - `claude-recall list` output missing"

    # the tool result part (CLI stdout) is persisted in opencode.db
    parts = _parts_since(fx, t0)
    assert any(LESSON_MARKER in p for p in parts), \
        "claude-recall tool result not persisted in opencode.db"


# =============================================================================
# Scenario e: DEEP READ - first-prompt relevance over the full memory dir
# =============================================================================


def test_deep_read_injects_relevant_memory(fx):
    """The fixture memory dir holds reference_zorblaxflange.md whose marker
    does NOT appear in the MEMORY.md index - only ranking the actual file
    contents against the prompt can surface it."""
    offset = _log_size(fx)
    t0 = _now_ms()
    r = _run_cooperative(
        fx, ["run", "-m", E2E_MODEL,
             "How do I recalibrate the zorblaxflange housing?"])
    assert r.returncode == 0, f"opencode run failed: {r.stderr[-500:]}"

    by = _events_by_name(_read_events(fx, offset))

    # structured log event: file list + scores, zorblaxflange ranked first
    inj = by.get("chat.memory_relevance_injected", [])
    assert inj, "chat.memory_relevance_injected never logged - deep read unproven"
    files = inj[-1].get("files", [])
    assert files, "memory_relevance_injected carried no file list"
    assert files[0].get("name") == "reference_zorblaxflange.md", \
        f"zorblaxflange file should rank first, got {files}"
    assert files[0].get("score", 0) > 0

    # the injected synthetic part (full file content) is persisted
    parts = _parts_since(fx, t0)
    assert any("<relevant-memory>" in p for p in parts), \
        "synthetic relevant-memory part not persisted in opencode.db"
    assert any(DEEP_MEMORY_MARKER in p for p in parts), \
        "deep-read marker absent from persisted parts"


# =============================================================================
# Scenario f: WRITE BRIDGE - a captured lesson is mirrored into auto-memory
# =============================================================================


def _slugify(title: str) -> str:
    """Mirror of slugify() in adapters/opencode/lib/memory.ts."""
    s = re.sub(r"[^a-z0-9]+", "-", title.lower())
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s[:60].rstrip("-") or "lesson"


def _poll_for_file(path: Path, timeout_s: float) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if path.exists():
            return True
        time.sleep(2)
    return path.exists()


# Cooperative prompt: asks the model to emit the LESSON: line WITHOUT the user
# message itself matching the Go lesson regex (`LESSON:\s*... - ...` on one
# line) - so a capture here proves the model's output went through the real
# session-idle pipeline. ("space hyphen space" avoids a literal ' - '.)
COOPERATIVE_PROMPT = (
    "Do exactly this: output a single line that starts with LESSON: then a "
    "space, then the title, then a space hyphen space, then the content. No "
    "other text, no markdown fences, no quotes.\n"
    f"Title: {BRIDGE_TITLE}\n"
    f"Content: {BRIDGE_CONTENT}"
)
# Deterministic fallback: the user message itself carries a parseable LESSON:
# line (the Go session-idle regex matches user messages too), so the bridge
# capture no longer depends on model cooperation.
FALLBACK_PROMPT = f"LESSON: {BRIDGE_TITLE} - {BRIDGE_CONTENT}"


def test_write_bridge_mirrors_lesson_to_memory(fx):
    """A lesson captured by session-idle must be mirrored into the Claude
    auto-memory dir: feedback_<slug>.md with feedback frontmatter + provenance,
    and a link under the bridge-owned MEMORY.md section."""
    slug = _slugify(BRIDGE_TITLE)
    feedback_file = fx.mem_dir / f"feedback_{slug}.md"

    provider, _, model = E2E_MODEL.partition("/")
    assert provider and model, f"E2E_MODEL must be provider/model, got {E2E_MODEL}"
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen(
        [OPENCODE, "serve", "--port", str(port), "--hostname", "127.0.0.1"],
        cwd=fx.proj, env=fx.env, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True)
    try:
        # wait for the server (up to 60s; model warmup can be slow)
        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                urllib.request.urlopen(f"{base}/session?directory={fx.proj}",
                                       timeout=3)
                break
            except Exception:
                if proc.poll() is not None:
                    pytest.fail(f"opencode serve exited early rc={proc.returncode}")
                time.sleep(1)
        else:
            pytest.fail("opencode serve never came up")

        offset = _log_size(fx)
        sid = _http_json(f"{base}/session?directory={fx.proj}",
                         {"title": "e2e-write-bridge"}, timeout=30)["id"]

        # Attempt 1: cooperative (model emits the LESSON: line itself).
        _http_json(f"{base}/session/{sid}/message?directory={fx.proj}",
                   {"model": {"providerID": provider, "modelID": model},
                    "parts": [{"type": "text", "text": COOPERATIVE_PROMPT}]},
                   timeout=300)

        if not _poll_for_file(feedback_file, 90):
            # Attempt 2: deterministic (user message carries the lesson).
            print("write-bridge: cooperative attempt missed; using fallback")
            _http_json(f"{base}/session/{sid}/message?directory={fx.proj}",
                       {"model": {"providerID": provider, "modelID": model},
                        "parts": [{"type": "text", "text": FALLBACK_PROMPT}]},
                       timeout=300)
            recent = _read_events(fx, offset)[-30:]
            assert _poll_for_file(feedback_file, 90), (
                f"write bridge never mirrored the lesson; "
                f"recent log events: {json.dumps(recent, indent=1)}")
        else:
            print("write-bridge: model emitted the LESSON: line cooperatively")

        # --- feedback file: frontmatter + body + provenance ---
        text = feedback_file.read_text()
        assert text.startswith("---\n"), "memory file missing YAML frontmatter"
        assert f"name: {BRIDGE_TITLE}\n" in text, \
            f"frontmatter name mismatch:\n{text[:400]}"
        assert f"description: {BRIDGE_CONTENT}\n" in text, \
            f"frontmatter description mismatch:\n{text[:400]}"
        assert "\ntype: feedback\n" in text
        assert f"\n{BRIDGE_CONTENT}\n" in text, "lesson body missing"
        assert re.search(
            rf"Source: claude-recall lesson L\d{{3}} via opencode, "
            rf"\d{{4}}-\d{{2}}-\d{{2}}T", text), \
            f"provenance line missing/malformed:\n{text[-300:]}"

        # --- MEMORY.md: bridge section + link, other content untouched ---
        index = (fx.mem_dir / "MEMORY.md").read_text()
        assert "## From opencode (claude-recall)" in index, \
            "bridge-owned section missing from MEMORY.md"
        assert f"](feedback_{slug}.md)" in index, \
            "bridge link missing from MEMORY.md"
        assert MEMORY_MARKER in index, \
            "bridge must never touch pre-existing MEMORY.md content"

        # --- structured log events ---
        by = _events_by_name(_read_events(fx, offset))
        assert "lessons.added" in by, "session-idle never captured the lesson"
        written = by.get("memory.mirror_written", [])
        assert any(e.get("filename") == f"feedback_{slug}.md" for e in written), \
            f"memory.mirror_written missing for {slug}: {written}"
    finally:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=15)
        except Exception:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except Exception:
                pass
