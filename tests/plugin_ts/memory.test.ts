// SPDX-License-Identifier: MIT
// Unit tests for the pure MEMORY.md logic in adapters/opencode/lib/memory.ts.
//
// Run with: ./run-tests.sh bun   (tsc + node --test on stock Node)

import { describe, test, expect, beforeEach, afterEach } from "./test-shim.js";
import { mkdtempSync, mkdirSync, writeFileSync, symlinkSync, rmSync } from "fs";
import { tmpdir } from "os";
import { join } from "path";

import { memoryDir, readFileCapped, readMemoryContext, GLOBAL_TIER_MIN_BUDGET } from "../../adapters/opencode/lib/memory.js";
import {
  slugify, memoryDescription, feedbackFileContent, upsertBridgeIndexEntry,
  parseLessonsFile, memoryDirOrCreate, mirrorLessonToMemory, mirrorLessonsBatch,
  listMemoryFiles, rankMemoryFiles,
  BRIDGE_SECTION_HEADER, MEMORY_FILE_READ_CAP,
} from "../../adapters/opencode/lib/memory.js";
import { readFileSync, readdirSync, existsSync } from "fs";

// Mirror of the plugin's hash: cwd with '/' and '.' replaced by '-'.
const dottedHash = (cwd: string) => cwd.replace(/[/.]/g, "-");
// Legacy form: only '/' replaced.
const slashedHash = (cwd: string) => cwd.replace(/\//g, "-");

let home: string;

beforeEach(() => {
  home = mkdtempSync(join(tmpdir(), "cr-mem-test-"));
});

afterEach(() => {
  rmSync(home, { recursive: true, force: true });
});

function makeMemoryDir(cwd: string, form: "dotted" | "slashed" = "dotted"): string {
  const hash = form === "dotted" ? dottedHash(cwd) : slashedHash(cwd);
  const dir = join(home, ".claude", "projects", hash, "memory");
  mkdirSync(dir, { recursive: true });
  return dir;
}

describe("memoryDir", () => {
  test("finds the dotted hash form (/ and . -> -)", () => {
    const cwd = join(home, "my.proj"); // contains a dot
    const dir = makeMemoryDir(cwd, "dotted");
    expect(memoryDir(cwd, home)).toBe(dir);
  });

  test("finds the slash-only hash form for plain paths", () => {
    const cwd = join(home, "plain"); // no dots: both forms identical
    const dir = makeMemoryDir(cwd, "dotted");
    expect(memoryDir(cwd, home)).toBe(dir);
  });

  test("falls back to the legacy slash-only form when dotted is absent", () => {
    const cwd = join(home, "my.proj");
    // cwd has a dot, so the two hash forms differ; create only the legacy one.
    expect(slashedHash(cwd)).not.toBe(dottedHash(cwd));
    const legacy = makeMemoryDir(cwd, "slashed");
    expect(memoryDir(cwd, home)).toBe(legacy);
  });

  test("prefers the dotted form when both exist", () => {
    const cwd = join(home, "my.proj");
    const dotted = makeMemoryDir(cwd, "dotted");
    makeMemoryDir(cwd, "slashed");
    expect(memoryDir(cwd, home)).toBe(dotted);
  });

  test("returns null when no hash dir exists", () => {
    expect(memoryDir(join(home, "nope"), home)).toBeNull();
  });

  test("returns null when the projects base is missing entirely", () => {
    expect(memoryDir("/nonexistent/path", home)).toBeNull();
  });
});

describe("readFileCapped", () => {
  test("returns null for a missing file", () => {
    expect(readFileCapped(join(home, "nope.md"), 100)).toBeNull();
  });

  test("returns null for an empty file", () => {
    const p = join(home, "empty.md");
    writeFileSync(p, "");
    expect(readFileCapped(p, 100)).toBeNull();
  });

  test("returns null for a whitespace-only file", () => {
    const p = join(home, "ws.md");
    writeFileSync(p, "  \n\n \t\n");
    expect(readFileCapped(p, 100)).toBeNull();
  });

  test("returns the full trimmed text when under budget", () => {
    const p = join(home, "small.md");
    writeFileSync(p, "  hello memory  \n");
    const r = readFileCapped(p, 100);
    expect(r).not.toBeNull();
    expect(r!.text).toBe("hello memory");
    expect(r!.note).toBe("");
  });

  test("returns the full text when exactly at budget", () => {
    const p = join(home, "exact.md");
    const body = "x".repeat(100);
    writeFileSync(p, body);
    const r = readFileCapped(p, 100);
    expect(r!.text).toBe(body);
    expect(r!.note).toBe("");
  });

  test("truncates over-budget files and adds a skip-note", () => {
    const p = join(home, "big.md");
    const body = "y".repeat(500);
    writeFileSync(p, body);
    const r = readFileCapped(p, 100);
    expect(r!.text.length).toBeLessThanOrEqual(100);
    expect(r!.text).toBe("y".repeat(100));
    expect(r!.note).toContain("Read the full file");
    expect(r!.note).toContain("500");
    expect(r!.note).toContain("100");
    expect(r!.note).toContain(p);
  });
});

describe("readMemoryContext", () => {
  const MAX = 8192;

  test("returns null when no memory dir exists", () => {
    expect(readMemoryContext(join(home, "proj"), home, MAX)).toBeNull();
  });

  test("returns null for a whitespace-only MEMORY.md", () => {
    const cwd = join(home, "proj");
    const dir = makeMemoryDir(cwd);
    writeFileSync(join(dir, "MEMORY.md"), "   \n ");
    expect(readMemoryContext(cwd, home, MAX)).toBeNull();
  });

  test("reads the project MEMORY.md", () => {
    const cwd = join(home, "proj");
    const dir = makeMemoryDir(cwd);
    writeFileSync(join(dir, "MEMORY.md"), "remember the flux capacitor");
    const ctx = readMemoryContext(cwd, home, MAX);
    expect(ctx).toContain("## Project memory");
    expect(ctx).toContain("remember the flux capacitor");
    expect(ctx).not.toContain("## Global memory");
  });

  test("includes the global tier only when memory/global is a symlink", () => {
    const cwd = join(home, "proj");
    const dir = makeMemoryDir(cwd);
    writeFileSync(join(dir, "MEMORY.md"), "project stuff");
    // Global tier target
    const globalDir = join(home, ".claude", "memory-global");
    mkdirSync(globalDir, { recursive: true });
    writeFileSync(join(globalDir, "MEMORY.md"), "global persona stuff");
    // Without the symlink: no global section
    let ctx = readMemoryContext(cwd, home, MAX);
    expect(ctx).toContain("## Project memory");
    expect(ctx).not.toContain("## Global memory");
    // With the symlink: global section appears
    symlinkSync(globalDir, join(dir, "global"));
    ctx = readMemoryContext(cwd, home, MAX);
    expect(ctx).toContain("## Global memory");
    expect(ctx).toContain("global persona stuff");
  });

  test("global tier is gated on remaining budget (> 512 bytes)", () => {
    const cwd = join(home, "proj");
    const dir = makeMemoryDir(cwd);
    // Project content consumes the budget down to <= GLOBAL_TIER_MIN_BUDGET.
    const cap = 2000;
    const body = "z".repeat(cap - GLOBAL_TIER_MIN_BUDGET);
    writeFileSync(join(dir, "MEMORY.md"), body);
    const globalDir = join(home, ".claude", "memory-global");
    mkdirSync(globalDir, { recursive: true });
    writeFileSync(join(globalDir, "MEMORY.md"), "global persona stuff");
    symlinkSync(globalDir, join(dir, "global"));
    const ctx = readMemoryContext(cwd, home, cap);
    expect(ctx).toContain("## Project memory");
    expect(ctx).not.toContain("## Global memory");
  });

  test("caps oversized project memory and annotates the skip-note", () => {
    const cwd = join(home, "proj");
    const dir = makeMemoryDir(cwd);
    writeFileSync(join(dir, "MEMORY.md"), "q".repeat(10000));
    const ctx = readMemoryContext(cwd, home, 8192);
    expect(ctx).toContain("Read the full file");
    // The skip-note embeds an absolute path, so total length varies by platform
    // (macOS tmpdir runs ~100 chars vs /tmp on Linux). Bound the injected body
    // instead: everything before the note must stay within budget + header.
    const body = ctx!.slice(0, ctx!.indexOf("[claude-recall:"));
    expect(body.length).toBeLessThan(8192 + 400);
  });

  test("missing global MEMORY.md is silently skipped", () => {
    const cwd = join(home, "proj");
    const dir = makeMemoryDir(cwd);
    writeFileSync(join(dir, "MEMORY.md"), "project stuff");
    // Symlink points at a location without MEMORY.md
    const globalDir = join(home, ".claude", "memory-global");
    mkdirSync(globalDir, { recursive: true });
    symlinkSync(globalDir, join(dir, "global"));
    const ctx = readMemoryContext(cwd, home, MAX);
    expect(ctx).toContain("## Project memory");
    expect(ctx).not.toContain("## Global memory");
  });
});

// =============================================================================
// WRITE BRIDGE: opencode lessons -> Claude Code auto-memory files
// =============================================================================

const FIXED_DATE = "2026-07-19T00:00:00.000Z";

describe("slugify", () => {
  test("lowercases and dashes non-alnum runs", () => {
    expect(slugify("Hello World!")).toBe("hello-world");
    expect(slugify("ARM GCC: aarch64 host LTO bug")).toBe("arm-gcc-aarch64-host-lto-bug");
  });

  test("collapses repeated dashes and trims edges", () => {
    expect(slugify("a  --  b")).toBe("a-b");
    expect(slugify("--lead trail--")).toBe("lead-trail");
    expect(slugify("!!!focus!!!")).toBe("focus");
  });

  test("caps at 60 chars without a trailing dash", () => {
    const slug = slugify("word ".repeat(30).trim());
    expect(slug.length).toBeLessThanOrEqual(60);
    expect(slug).not.toMatch(/-$/);
  });

  test("falls back to 'lesson' for titles with no alnum characters", () => {
    expect(slugify("!!!")).toBe("lesson");
    expect(slugify("")).toBe("lesson");
  });

  test("non-ascii letters become dashes", () => {
    expect(slugify("héllo wörld")).toBe("h-llo-w-rld");
  });
});

describe("memoryDescription", () => {
  test("passes short content through", () => {
    expect(memoryDescription("short body")).toBe("short body");
  });

  test("collapses whitespace for single-line frontmatter", () => {
    expect(memoryDescription("line one\nline   two\tend")).toBe("line one line two end");
  });

  test("caps at 120 chars", () => {
    const desc = memoryDescription("x".repeat(200));
    expect(desc.length).toBe(120);
  });
});

describe("feedbackFileContent", () => {
  test("emits frontmatter, body and provenance line", () => {
    const file = feedbackFileContent("My Title", "Body text", "L007", FIXED_DATE);
    expect(file).toBe(
      "---\nname: My Title\ndescription: Body text\ntype: feedback\n---\n\n" +
      "Body text\n\n" +
      `Source: claude-recall lesson L007 via opencode, ${FIXED_DATE}\n`);
  });

  test("quotes YAML-unsafe scalars (colon in title)", () => {
    const file = feedbackFileContent("Bug: crash", "Body", "L001", FIXED_DATE);
    expect(file).toContain('name: "Bug: crash"');
  });

  test("truncates a long description but keeps the full body", () => {
    const file = feedbackFileContent("T", "y".repeat(300), "L001", FIXED_DATE);
    expect(file).toContain(`description: ${"y".repeat(120)}`);
    expect(file).toContain(`\n\n${"y".repeat(300)}\n\nSource:`);
  });
});

describe("upsertBridgeIndexEntry", () => {
  const link = (f: string) => `- [T](${f}) — d`;

  test("creates MEMORY.md from scratch when absent", () => {
    const r = upsertBridgeIndexEntry(null, "feedback_a.md", "T", "d");
    expect(r.changed).toBe(true);
    expect(r.text).toBe(`# Project Memory\n\n${BRIDGE_SECTION_HEADER}\n\n${link("feedback_a.md")}\n`);
  });

  test("creates the bridge section at EOF when missing, preserving prior content", () => {
    const prior = "# My Memory\n\n## Who\n- [A](a.md) — x\n";
    const r = upsertBridgeIndexEntry(prior, "feedback_a.md", "T", "d");
    expect(r.changed).toBe(true);
    expect(r.text.startsWith("# My Memory\n\n## Who\n- [A](a.md) — x\n")).toBe(true);
    expect(r.text).toContain(`${BRIDGE_SECTION_HEADER}\n\n${link("feedback_a.md")}\n`);
    expect(r.text.endsWith("\n")).toBe(true);
  });

  test("appends under an existing bridge section, before the next section", () => {
    const prior = [
      "# Mem",
      "",
      "## Who",
      "- [A](a.md) — x",
      "",
      BRIDGE_SECTION_HEADER,
      "",
      "- [Old](feedback_old.md) — old",
      "",
      "## Notes",
      "tail",
    ].join("\n");
    const r = upsertBridgeIndexEntry(prior, "feedback_new.md", "T", "d");
    expect(r.changed).toBe(true);
    // new link lands inside the bridge section, after the old entry
    const bridgeStart = r.text.indexOf(BRIDGE_SECTION_HEADER);
    const notesStart = r.text.indexOf("## Notes");
    const newLink = r.text.indexOf(link("feedback_new.md"));
    expect(newLink).toBeGreaterThan(bridgeStart);
    expect(newLink).toBeLessThan(notesStart);
    expect(r.text.indexOf(link("feedback_new.md"))).toBeGreaterThan(r.text.indexOf("feedback_old.md"));
    // other sections are byte-identical
    expect(r.text).toContain("## Who\n- [A](a.md) — x");
    expect(r.text.endsWith("## Notes\ntail")).toBe(true);
  });

  test("is idempotent when the filename link already exists anywhere", () => {
    const prior = `# Mem\n\n## Random\n\n${link("feedback_a.md")} somewhere\n`;
    const r = upsertBridgeIndexEntry(prior, "feedback_a.md", "T", "d");
    expect(r.changed).toBe(false);
    expect(r.reason).toBe("already_indexed");
    expect(r.text).toBe(prior);
  });
});

describe("parseLessonsFile", () => {
  test("parses ids, titles and content lines", () => {
    const text = `# LESSONS.md - Project Level

## Active Lessons

### [L001] [***--|-----] First Lesson
- **Uses**: 3 | **Velocity**: 0.5 | **Learned**: 2026-01-01 | **Last**: 2026-01-02 | **Category**: pattern
> Content line one
> content line two

### [S001] [*----|-----] System Lesson
- **Uses**: 1 | **Velocity**: 0.1 | **Learned**: 2026-01-01 | **Last**: 2026-01-02 | **Category**: gotcha
> System content
`;
    const m = parseLessonsFile(text);
    expect(m.get("L001")).toEqual({ title: "First Lesson", content: "Content line one\ncontent line two" });
    expect(m.get("S001")).toEqual({ title: "System Lesson", content: "System content" });
  });

  test("parses the current format, where the header carries no rating", () => {
    // Ratings render at display time and the counters live in stats.json, so
    // headers written by the Go CLI are bare.
    const text = `## Active Lessons

### [L001] First Lesson
- **Learned**: 2026-01-01 | **Category**: pattern
> Content line one
> content line two

### [S001] System Lesson
- **Learned**: 2026-01-01 | **Category**: gotcha | **Superseded**: S002
> System content
`;
    const m = parseLessonsFile(text);
    expect(m.get("L001")).toEqual({ title: "First Lesson", content: "Content line one\ncontent line two" });
    expect(m.get("S001")).toEqual({ title: "System Lesson", content: "System content" });
  });

  test("strips the AI-source robot emoji from titles", () => {
    const text = "### [L002] [**---|-----] AI Lesson 🤖\n> body\n";
    expect(parseLessonsFile(text).get("L002")!.title).toBe("AI Lesson");
  });

  test("strips the robot emoji in the current format too", () => {
    expect(parseLessonsFile("### [L002] AI Lesson 🤖\n> body\n").get("L002")!.title).toBe("AI Lesson");
  });

  test("empty input yields an empty map", () => {
    expect(parseLessonsFile("").size).toBe(0);
  });
});

describe("memoryDirOrCreate", () => {
  test("reuses an existing hash dir", () => {
    const cwd = join(home, "my.proj");
    const dir = makeMemoryDir(cwd, "dotted");
    expect(memoryDirOrCreate(cwd, home)).toBe(dir);
  });

  test("creates the dotted-hash dir when absent", () => {
    const cwd = join(home, "new.proj");
    const dir = memoryDirOrCreate(cwd, home);
    expect(dir).toBe(join(home, ".claude", "projects", dottedHash(cwd), "memory"));
    expect(existsSync(dir!)).toBe(true);
  });
});

describe("mirrorLessonToMemory", () => {
  const lesson = { memoryDir: "", lessonId: "L003", title: "My Lesson", content: "Do the thing" };
  let dir: string;
  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), "cr-mirror-"));
    rmSync(dir, { recursive: true, force: true });
    mkdirSync(dir, { recursive: true });
  });

  test("writes the feedback file and creates the MEMORY.md section", () => {
    const o = mirrorLessonToMemory({ ...lesson, memoryDir: dir, date: FIXED_DATE });
    expect(o.status).toBe("written");
    expect(o.filename).toBe("feedback_my-lesson.md");
    expect(o.indexChanged).toBe(true);
    const file = readFileSync(join(dir, "feedback_my-lesson.md"), "utf8");
    expect(file).toContain("name: My Lesson");
    expect(file).toContain("type: feedback");
    expect(file).toContain(`Source: claude-recall lesson L003 via opencode, ${FIXED_DATE}`);
    const index = readFileSync(join(dir, "MEMORY.md"), "utf8");
    expect(index).toContain(BRIDGE_SECTION_HEADER);
    expect(index).toContain("- [My Lesson](feedback_my-lesson.md) — Do the thing");
  });

  test("appends under a pre-existing bridge section without touching others", () => {
    writeFileSync(join(dir, "MEMORY.md"),
      `# Mem\n\n## Who\n- [A](a.md) — x\n\n${BRIDGE_SECTION_HEADER}\n\n- [Old](feedback_old.md) — old\n`);
    const o = mirrorLessonToMemory({ ...lesson, memoryDir: dir, date: FIXED_DATE });
    expect(o.status).toBe("written");
    const index = readFileSync(join(dir, "MEMORY.md"), "utf8");
    expect(index).toContain("## Who\n- [A](a.md) — x");
    expect(index.indexOf("feedback_old.md")).toBeLessThan(index.indexOf("feedback_my-lesson.md"));
  });

  test("identical re-mirror is skipped silently (no rewrite, no dup index)", () => {
    const first = mirrorLessonToMemory({ ...lesson, memoryDir: dir, date: FIXED_DATE });
    expect(first.status).toBe("written");
    const second = mirrorLessonToMemory({ ...lesson, memoryDir: dir, date: FIXED_DATE });
    expect(second.status).toBe("skipped");
    expect(second.reason).toBe("identical_content");
    expect(second.filename).toBe("feedback_my-lesson.md");
    expect(readdirSync(dir).filter(f => f.startsWith("feedback_")).length).toBe(1);
    const index = readFileSync(join(dir, "MEMORY.md"), "utf8");
    expect(index.split("feedback_my-lesson.md").length - 1).toBe(1);
  });

  test("filename collision with different content suffixes -2, then -3", () => {
    writeFileSync(join(dir, "feedback_my-lesson.md"), "hand-written memory, not ours");
    const o2 = mirrorLessonToMemory({ ...lesson, memoryDir: dir, date: FIXED_DATE });
    expect(o2.status).toBe("written");
    expect(o2.filename).toBe("feedback_my-lesson-2.md");
    // the hand-written file is untouched
    expect(readFileSync(join(dir, "feedback_my-lesson.md"), "utf8")).toBe("hand-written memory, not ours");
    // and a second collision chain step works too
    writeFileSync(join(dir, "feedback_my-lesson-2.md"), "also different");
    const o3 = mirrorLessonToMemory({ ...lesson, memoryDir: dir, date: FIXED_DATE });
    expect(o3.filename).toBe("feedback_my-lesson-3.md");
    const index = readFileSync(join(dir, "MEMORY.md"), "utf8");
    expect(index).toContain("](feedback_my-lesson-2.md)");
    expect(index).toContain("](feedback_my-lesson-3.md)");
  });

  test("unwritable memory dir comes back as an error outcome (no throw)", () => {
    const o = mirrorLessonToMemory({ ...lesson, memoryDir: join(dir, "no\x00such-dir"), date: FIXED_DATE });
    expect(o.status).toBe("error");
    expect(o.error).toBeTruthy();
  });
});

describe("mirrorLessonsBatch", () => {
  let dir: string;
  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), "cr-batch-"));
    rmSync(dir, { recursive: true, force: true });
    mkdirSync(dir, { recursive: true });
  });
  const lessons = [1, 2, 3].map(i => ({ id: `L00${i}`, title: `Lesson ${i}`, content: `body ${i}` }));

  test("enforces the per-call runaway cap", () => {
    const out = mirrorLessonsBatch({ memoryDir: dir, lessons, maxToWrite: 2, date: FIXED_DATE });
    expect(out.map(o => o.status)).toEqual(["written", "written", "skipped"]);
    expect(out[2].reason).toBe("session_cap");
    expect(readdirSync(dir).filter(f => f.startsWith("feedback_")).length).toBe(2);
  });

  test("cap of zero skips everything", () => {
    const out = mirrorLessonsBatch({ memoryDir: dir, lessons, maxToWrite: 0, date: FIXED_DATE });
    expect(out.every(o => o.status === "skipped" && o.reason === "session_cap")).toBe(true);
    expect(readdirSync(dir).filter(f => f.startsWith("feedback_")).length).toBe(0);
  });
});

// =============================================================================
// DEEP READ: relevance over the full memory dir
// =============================================================================

describe("listMemoryFiles", () => {
  test("lists *.md excluding MEMORY.md, sorted by name", () => {
    const cwd = join(home, "proj");
    const dir = makeMemoryDir(cwd);
    writeFileSync(join(dir, "MEMORY.md"), "index");
    writeFileSync(join(dir, "b_file.md"), "b");
    writeFileSync(join(dir, "a_file.md"), "a");
    writeFileSync(join(dir, "notes.txt"), "not markdown");
    const files = listMemoryFiles(dir);
    expect(files.map(f => f.name)).toEqual(["a_file.md", "b_file.md"]);
  });

  test("includes files under the global/ symlink (MEMORY.md excluded there too)", () => {
    const cwd = join(home, "proj");
    const dir = makeMemoryDir(cwd);
    writeFileSync(join(dir, "local.md"), "local");
    const globalDir = join(home, ".claude", "memory-global");
    mkdirSync(globalDir, { recursive: true });
    writeFileSync(join(globalDir, "MEMORY.md"), "global index");
    writeFileSync(join(globalDir, "user_persona.md"), "persona");
    symlinkSync(globalDir, join(dir, "global"));
    const files = listMemoryFiles(dir);
    expect(files.map(f => f.name)).toEqual(["global/user_persona.md", "local.md"]);
  });

  test("a broken global symlink is skipped without throwing", () => {
    const cwd = join(home, "proj");
    const dir = makeMemoryDir(cwd);
    writeFileSync(join(dir, "local.md"), "local");
    symlinkSync(join(home, "does-not-exist"), join(dir, "global"));
    expect(listMemoryFiles(dir).map(f => f.name)).toEqual(["local.md"]);
  });
});

describe("rankMemoryFiles", () => {
  function seedMemory(cwd: string): string {
    const dir = makeMemoryDir(cwd);
    writeFileSync(join(dir, "MEMORY.md"), "# Index\n\n- [Zorblax](reference_zorblax.md) — pointer only\n");
    writeFileSync(join(dir, "reference_zorblax.md"),
      "---\nname: Zorblax\ntype: reference\n---\n\nThe zorblax recalibration ritual: drain coolant, twist the zorblax housing, recalibrate cold.");
    writeFileSync(join(dir, "reference_knitting.md"),
      "Garter stitch scarf patterns: cast on forty stitches and knit every row until winter ends.");
    writeFileSync(join(dir, "feedback_both.md"),
      "Common ground: the zorblax note plus knitting scarf patterns together.");
    return dir;
  }

  test("ranks the file with the rare prompt term first, deterministically", () => {
    const cwd = join(home, "proj");
    seedMemory(cwd);
    const prompt = "How do I recalibrate the zorblax housing?";
    const a = rankMemoryFiles(prompt, cwd, home, { topN: 3 });
    const b = rankMemoryFiles(prompt, cwd, home, { topN: 3 });
    expect(a.map(f => [f.name, f.score])).toEqual(b.map(f => [f.name, f.score]));
    expect(a[0].name).toBe("reference_zorblax.md");
    expect(a[0].score).toBeGreaterThan(a[1]?.score ?? 0);
    // the knitting-only file has zero prompt-term overlap and is excluded
    expect(a.map(f => f.name)).not.toContain("reference_knitting.md");
  });

  test("topN caps the result count", () => {
    const cwd = join(home, "proj");
    seedMemory(cwd);
    const all = rankMemoryFiles("zorblax knitting scarf recalibrate", cwd, home, { topN: 10 });
    expect(all.length).toBe(3); // all three files share at least one term
    const top2 = rankMemoryFiles("zorblax knitting scarf recalibrate", cwd, home, { topN: 2 });
    expect(top2.length).toBe(2);
    expect(top2.map(f => f.name)).toEqual(all.slice(0, 2).map(f => f.name));
  });

  test("scores are positive and sorted descending", () => {
    const cwd = join(home, "proj");
    seedMemory(cwd);
    const r = rankMemoryFiles("zorblax recalibrate knitting scarf", cwd, home, { topN: 10 });
    for (let i = 0; i < r.length; i++) {
      expect(r[i].score).toBeGreaterThan(0);
      if (i > 0) expect(r[i - 1].score).toBeGreaterThanOrEqual(r[i].score);
    }
  });

  test("readCap bounds the returned content", () => {
    const cwd = join(home, "proj");
    const dir = seedMemory(cwd);
    writeFileSync(join(dir, "big.md"), `zorblax ${"filler ".repeat(2000)}`);
    const r = rankMemoryFiles("zorblax", cwd, home, { topN: 5 });
    const big = r.find(f => f.name === "big.md")!;
    expect(Buffer.byteLength(big.content)).toBeLessThanOrEqual(MEMORY_FILE_READ_CAP);
  });

  test("files under the global/ symlink participate in ranking", () => {
    const cwd = join(home, "proj");
    const dir = makeMemoryDir(cwd);
    writeFileSync(join(dir, "local.md"), "unrelated local content");
    const globalDir = join(home, ".claude", "memory-global");
    mkdirSync(globalDir, { recursive: true });
    writeFileSync(join(globalDir, "user_quixotic.md"), "The quixotic wrench preference: left-handed only.");
    symlinkSync(globalDir, join(dir, "global"));
    const r = rankMemoryFiles("tell me about the quixotic wrench", cwd, home, { topN: 2 });
    expect(r.map(f => f.name)).toContain("global/user_quixotic.md");
  });

  test("empty prompt, stopword-only prompt, missing dir and topN=0 all yield []", () => {
    const cwd = join(home, "proj");
    seedMemory(cwd);
    expect(rankMemoryFiles("", cwd, home)).toEqual([]);
    expect(rankMemoryFiles("a an be", cwd, home)).toEqual([]); // all tokens < 3 chars
    expect(rankMemoryFiles("zorblax", join(home, "no-proj"), home)).toEqual([]);
    expect(rankMemoryFiles("zorblax", cwd, home, { topN: 0 })).toEqual([]);
  });
});
