// SPDX-License-Identifier: MIT
// Claude Code auto-memory (MEMORY.md) discovery - pure logic, no OpenCode deps.
//
// Lives in lib/ because OpenCode auto-loads every top-level plugins/*.{ts,js}
// file as a plugin entry (and calls every exported function as a plugin).
// Subdirectories are not scanned, so this module is import-safe.
//
// Claude Code hashes a project as its cwd with '/' (and '.') replaced by '-',
// e.g. /home/u/code -> ~/.claude/projects/-home-u-code/memory/MEMORY.md.
// Projects created by older versions only replaced '/', so try both forms.

import { readFileSync, writeFileSync, mkdirSync, readdirSync, existsSync, lstatSync, openSync, readSync, closeSync } from 'fs';
import { join } from 'path';

// Minimum remaining budget required before the global tier is considered.
export const GLOBAL_TIER_MIN_BUDGET = 512;

export function memoryDir(cwd: string, home: string): string | null {
  const base = join(home, '.claude', 'projects');
  const dotted = cwd.replace(/[/.]/g, '-');
  const slashed = cwd.replace(/\//g, '-');
  const candidates = [join(base, dotted, 'memory')];
  if (slashed !== dotted) candidates.push(join(base, slashed, 'memory'));
  for (const dir of candidates) {
    try { if (existsSync(dir)) return dir; } catch { /* try next */ }
  }
  return null;
}

export function readFileCapped(path: string, budget: number): { text: string; note: string } | null {
  try {
    if (!existsSync(path)) return null;
    const raw = readFileSync(path, 'utf8');
    if (!raw.trim()) return null;
    if (raw.length <= budget) return { text: raw.trim(), note: '' };
    const note = `\n\n[claude-recall: MEMORY.md is ${raw.length} bytes; injected the first ${budget}. Read the full file at ${path} if needed.]`;
    return { text: raw.slice(0, budget).trimEnd(), note };
  } catch { return null; }
}

// Read project MEMORY.md plus the global tier (person-level memory shared via
// the memory/global symlink). Missing files are silently skipped; total
// injected content is capped at maxBytes.
export function readMemoryContext(cwd: string, home: string, maxBytes: number): string | null {
  const dir = memoryDir(cwd, home);
  if (!dir) return null;
  const sections: string[] = [];
  let budget = maxBytes;

  const projectPath = join(dir, 'MEMORY.md');
  const project = readFileCapped(projectPath, budget);
  if (project) {
    sections.push(`## Project memory (${projectPath})\n\n${project.text}${project.note}`);
    budget -= project.text.length;
  }

  let hasGlobalTier = false;
  try { hasGlobalTier = lstatSync(join(dir, 'global')).isSymbolicLink(); } catch { hasGlobalTier = false; }
  if (hasGlobalTier && budget > GLOBAL_TIER_MIN_BUDGET) {
    const globalPath = join(home, '.claude', 'memory-global', 'MEMORY.md');
    const globalMem = readFileCapped(globalPath, budget);
    if (globalMem) sections.push(`## Global memory (${globalPath})\n\n${globalMem.text}${globalMem.note}`);
  }

  return sections.length ? sections.join('\n\n') : null;
}

// =============================================================================
// WRITE BRIDGE: opencode lessons -> Claude Code auto-memory files
// =============================================================================
//
// When the Go `session-idle` call reports newly captured lessons, the plugin
// mirrors each one as a `feedback_<slug>.md` memory file plus a link in
// MEMORY.md under a dedicated bridge-owned section, so a later Claude Code
// session on the same project sees them through its native auto-memory read.
//
// PROJECT lessons only (L###). SYSTEM lessons (S###) are user-level memory;
// the global tier (~/.claude/memory-global) is Claude Code's domain and this
// bridge deliberately never writes there.

// Bridge-owned section header in MEMORY.md. Only lines inside this section
// are ever added by the bridge; every other section is left byte-identical.
export const BRIDGE_SECTION_HEADER = '## From opencode (claude-recall)';

const MAX_SLUG = 60;
const MAX_COLLISION_SUFFIX = 100; // paranoia bound for -2, -3, ... suffixes
const MAX_DESC = 120;

// Slug for the memory filename: lowercase, non-alnum runs -> '-', dashes
// collapsed and edge-trimmed, capped at 60 chars (on a dash boundary when
// possible). Empty titles fall back to "lesson".
export function slugify(title: string): string {
  let slug = (title || '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/-{2,}/g, '-')
    .replace(/^-+|-+$/g, '');
  if (slug.length > MAX_SLUG) {
    slug = slug.slice(0, MAX_SLUG);
    const lastDash = slug.lastIndexOf('-');
    if (lastDash > MAX_SLUG - 15) slug = slug.slice(0, lastDash); // cut on word boundary when close
    slug = slug.replace(/-+$/g, '');
  }
  return slug || 'lesson';
}

// YAML frontmatter scalar: plain when safe (matching the hand-written memory
// files), JSON double-quoted otherwise (valid YAML flow scalar).
function yamlScalar(s: string): string {
  const plainSafe = s.length > 0 &&
    !/^[\s\-?:,\[\]{}#&*!|>'"%@`]/.test(s) &&
    !/:\s/.test(s) && !/\s#/.test(s) &&
    !/[\r\n]/.test(s) &&
    s === s.trim();
  return plainSafe ? s : JSON.stringify(s);
}

// One-line description: content with whitespace collapsed, first <=120 chars.
export function memoryDescription(content: string): string {
  return (content || '').replace(/\s+/g, ' ').trim().slice(0, MAX_DESC).trimEnd();
}

// Full memory-file body: YAML frontmatter + lesson content + provenance line.
export function feedbackFileContent(title: string, content: string, lessonId: string, isoDate: string): string {
  const desc = memoryDescription(content);
  const body = (content || '').trim();
  return `---\nname: ${yamlScalar(title)}\ndescription: ${yamlScalar(desc)}\ntype: feedback\n---\n\n${body}\n\nSource: claude-recall lesson ${lessonId} via opencode, ${isoDate}\n`;
}

// Insert `- [title](filename) — desc` under the bridge section, creating the
// section (and the file) when absent. Idempotent: if a link to `filename`
// already exists anywhere in MEMORY.md, nothing changes. Lines outside the
// bridge section are never modified.
export function upsertBridgeIndexEntry(
  memoryMd: string | null,
  filename: string,
  title: string,
  desc: string,
): { text: string; changed: boolean; reason?: string } {
  const link = `- [${title}](${filename}) — ${desc}`;
  if (memoryMd && memoryMd.includes(`](${filename})`)) {
    return { text: memoryMd, changed: false, reason: 'already_indexed' };
  }
  const lines = (memoryMd ?? '').split('\n');
  const start = lines.findIndex(l => l.trim() === BRIDGE_SECTION_HEADER);
  if (start === -1) {
    const base = (memoryMd ?? '').trimEnd() || '# Project Memory';
    return { text: `${base}\n\n${BRIDGE_SECTION_HEADER}\n\n${link}\n`, changed: true };
  }
  // Section exists: append after its last non-blank line, before the next
  // '## ' header (or EOF).
  let end = lines.length;
  for (let i = start + 1; i < lines.length; i++) {
    if (lines[i].startsWith('## ')) { end = i; break; }
  }
  let insertAt = end;
  while (insertAt - 1 > start && lines[insertAt - 1].trim() === '') insertAt--;
  lines.splice(insertAt, 0, link);
  return { text: lines.join('\n'), changed: true };
}

// Parse the project LESSONS.md store into id -> { title, content }. Mirrors
// the Go parser (go/internal/lessons/parser.go): header, metadata line, content
// as `> `-prefixed lines. AI-source titles keep no trailing robot emoji.
//
// The header rating is optional. It derives from counters that now live in the
// stats.json sidecar and renders at display time, so current files read
// `### [L001] Title` while pre-split ones read `### [L001] [***--|-----] Title`.
// The optional group accepts only rating characters, so a title that starts
// with '[' is not mistaken for a rating.
export function parseLessonsFile(text: string): Map<string, { title: string; content: string }> {
  const out = new Map<string, { title: string; content: string }>();
  const headerRe = /^### \[([LS]\d{3})\](?: \[[-*+|/ ]+\])? (.*)$/;
  const contentRe = /^> ?(.*)$/;
  let id: string | null = null;
  let title = '';
  let buf: string[] = [];
  const flush = () => {
    if (id) out.set(id, { title, content: buf.join('\n').trim() });
  };
  for (const line of (text || '').split('\n')) {
    const h = headerRe.exec(line);
    if (h) {
      flush();
      id = h[1];
      title = h[2].replace(/\s*🤖\s*$/, '').trim();
      buf = [];
      continue;
    }
    if (id) {
      const c = contentRe.exec(line);
      if (c) buf.push(c[1]);
    }
  }
  flush();
  return out;
}

// Resolve the memory dir for WRITING: reuse an existing hash dir (either
// form) or create the modern dotted-hash one. Null when nothing could be
// resolved/created (caller logs memory.mirror_error).
export function memoryDirOrCreate(cwd: string, home: string): string | null {
  const existing = memoryDir(cwd, home);
  if (existing) return existing;
  const dir = join(home, '.claude', 'projects', cwd.replace(/[/.]/g, '-'), 'memory');
  try {
    mkdirSync(dir, { recursive: true });
    return dir;
  } catch {
    return null;
  }
}

export interface MirrorFileOutcome {
  id: string;
  status: 'written' | 'skipped' | 'error';
  reason?: string;   // skipped: 'identical_content' | 'session_cap'
  error?: string;    // error: fs failure message
  filename?: string; // feedback_<slug>.md (written or already-present)
  path?: string;
  indexChanged?: boolean;
}

// Mirror one lesson into the memory dir. Failure-isolated: fs errors come
// back as status 'error' instead of throwing, so the session.idle flow is
// never broken. Idempotent: an already-mirrored lesson (identical file
// content) is skipped silently; a filename collision with DIFFERENT content
// (e.g. a hand-written memory) gets -2, -3, ... suffixes.
export function mirrorLessonToMemory(opts: {
  memoryDir: string;
  lessonId: string;
  title: string;
  content: string;
  date?: string; // ISO date for provenance; defaults to now (tests pass a fixed value)
}): MirrorFileOutcome {
  const { memoryDir: dir, lessonId, title, content } = opts;
  const isoDate = opts.date ?? new Date().toISOString();
  const slug = slugify(title);
  const desc = memoryDescription(content);
  const wanted = feedbackFileContent(title, content, lessonId, isoDate);

  let filename = '';
  let path = '';
  let freeSlotFound = false;
  try {
    for (let i = 1; i <= MAX_COLLISION_SUFFIX; i++) {
      filename = `feedback_${slug}${i === 1 ? '' : `-${i}`}.md`;
      path = join(dir, filename);
      if (!existsSync(path)) { freeSlotFound = true; break; }
      let existing: string | null = null;
      try { existing = readFileSync(path, 'utf8'); } catch { existing = null; }
      if (existing === wanted) {
        // Identical mirror already on disk: skip the write, but still
        // reconcile the index entry if it somehow went missing.
        const idx = upsertBridgeIndexEntry(readIndex(dir), filename, title, desc);
        let indexChanged = false;
        if (idx.changed) {
          try { writeFileSync(join(dir, 'MEMORY.md'), idx.text, 'utf8'); indexChanged = true; } catch { /* index reconcile is best-effort */ }
        }
        return { id: lessonId, status: 'skipped', reason: 'identical_content', filename, path, indexChanged };
      }
      // Different content under the same name -> try the next suffix.
    }
  } catch (e) {
    return { id: lessonId, status: 'error', error: String(e) };
  }
  if (!freeSlotFound) {
    return { id: lessonId, status: 'error', error: `collision suffixes exhausted for ${slug}` };
  }

  try {
    mkdirSync(dir, { recursive: true });
    writeFileSync(path, wanted, 'utf8');
  } catch (e) {
    return { id: lessonId, status: 'error', error: `write ${filename}: ${String(e)}` };
  }

  let indexChanged = false;
  try {
    const idx = upsertBridgeIndexEntry(readIndex(dir), filename, title, desc);
    if (idx.changed) {
      writeFileSync(join(dir, 'MEMORY.md'), idx.text, 'utf8');
      indexChanged = true;
    }
  } catch (e) {
    return { id: lessonId, status: 'error', error: `index update for ${filename}: ${String(e)}`, filename, path };
  }
  return { id: lessonId, status: 'written', filename, path, indexChanged };
}

function readIndex(dir: string): string | null {
  try { return readFileSync(join(dir, 'MEMORY.md'), 'utf8'); } catch { return null; }
}

// Batch mirror with the runaway cap: at most `maxToWrite` files are written
// per call; the rest come back as skipped('session_cap'). The per-session
// counter lives in the plugin (it owns session state).
export function mirrorLessonsBatch(opts: {
  memoryDir: string;
  lessons: { id: string; title: string; content: string }[];
  maxToWrite: number;
  date?: string;
}): MirrorFileOutcome[] {
  const outcomes: MirrorFileOutcome[] = [];
  let written = 0;
  for (const lesson of opts.lessons) {
    if (written >= opts.maxToWrite) {
      outcomes.push({ id: lesson.id, status: 'skipped', reason: 'session_cap' });
      continue;
    }
    const o = mirrorLessonToMemory({
      memoryDir: opts.memoryDir, lessonId: lesson.id,
      title: lesson.title, content: lesson.content, date: opts.date,
    });
    if (o.status === 'written') written++;
    outcomes.push(o);
  }
  return outcomes;
}

// =============================================================================
// DEEP READ: relevance over the full memory dir (not just the MEMORY.md index)
// =============================================================================
//
// The session-start injection only carries the MEMORY.md INDEX (one-line
// pointers). For the first prompt of a session we additionally rank the
// actual memory files against the prompt and inject the top few in full
// (capped), so the model gets the content, not just the pointers.
//
// Scoring (dependency-free, deterministic): tokenize prompt and files on
// non-alphanumeric runs, case-folded, keeping tokens of >=3 chars. Each file
// scores the sum over unique prompt terms of idf(term) * (1 + ln(tf)), where
// tf is the term's frequency in the file and idf(term) = ln(1 + N/(1+df))
// with df = number of candidate files containing the term (N = candidate
// count) - so rare terms dominate and ubiquitous terms ("the") fade. Ties
// break by filename ascending. Only files with score > 0 are returned.

export const MEMORY_FILE_READ_CAP = 4096;   // bytes read per file for scoring
export const MEMORY_INJECT_FILE_CAP = 1500; // bytes injected per file

export interface MemoryFileRef { name: string; path: string }
export interface RankedMemoryFile extends MemoryFileRef { score: number; content: string }

// List candidate memory files: *.md in the dir (MEMORY.md itself excluded -
// the index is already injected at session start), plus *.md under the
// `global/` symlink when it resolves (namespaced as `global/<file>`; its
// MEMORY.md is excluded for the same reason).
export function listMemoryFiles(dir: string): MemoryFileRef[] {
  const out: MemoryFileRef[] = [];
  const collect = (sub: string | null, prefix: string) => {
    const target = sub ? join(dir, sub) : dir;
    let entries: string[];
    try { entries = readdirSync(target); } catch { return; }
    for (const name of entries) {
      if (!name.endsWith('.md') || name === 'MEMORY.md') continue;
      try { if (!lstatSync(join(target, name)).isFile()) continue; } catch { continue; }
      out.push({ name: prefix + name, path: join(target, name) });
    }
  };
  collect(null, '');
  try {
    if (lstatSync(join(dir, 'global')).isSymbolicLink()) collect('global', 'global/');
  } catch { /* no global tier */ }
  out.sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
  return out;
}

// Read at most `cap` BYTES from a file (true byte cap - no full-file read of
// a pathological file). A truncated multi-byte char degrades to U+FFFD at the
// tail, which is harmless for scoring and injection.
function readBytesCapped(path: string, cap: number): string | null {
  let fd: number;
  try { fd = openSync(path, 'r'); } catch { return null; }
  try {
    const buf = Buffer.alloc(cap);
    const n = readSync(fd, buf, 0, cap, 0);
    const text = buf.toString('utf8', 0, n);
    return text.trim() ? text : null;
  } catch {
    return null;
  } finally {
    try { closeSync(fd); } catch { /* ignore */ }
  }
}

function tokenize(text: string): string[] {
  return text.toLowerCase().split(/[^a-z0-9]+/).filter(t => t.length >= 3);
}

export function rankMemoryFiles(
  prompt: string,
  cwd: string,
  home: string,
  opts?: { topN?: number; readCap?: number },
): RankedMemoryFile[] {
  const dir = memoryDir(cwd, home);
  if (!dir) return [];
  const topN = opts?.topN ?? 2;
  const readCap = opts?.readCap ?? MEMORY_FILE_READ_CAP;
  if (topN <= 0) return [];

  const promptTerms = [...new Set(tokenize(prompt || ''))];
  if (!promptTerms.length) return [];

  const files: { ref: MemoryFileRef; content: string; tokens: string[] }[] = [];
  for (const ref of listMemoryFiles(dir)) {
    const content = readBytesCapped(ref.path, readCap);
    if (!content) continue;
    files.push({ ref, content, tokens: tokenize(content) });
  }
  if (!files.length) return [];

  const n = files.length;
  // Document frequency per prompt term across the whole corpus (hoisted -
  // df does not depend on the file being scored).
  const tokenSets = files.map(f => new Set(f.tokens));
  const df = new Map<string, number>();
  for (const term of promptTerms) {
    let c = 0;
    for (const set of tokenSets) if (set.has(term)) c++;
    if (c > 0) df.set(term, Math.log(1 + n / (1 + c))); // store idf directly
  }

  const ranked: RankedMemoryFile[] = [];
  for (const f of files) {
    const counts = new Map<string, number>();
    for (const tok of f.tokens) counts.set(tok, (counts.get(tok) ?? 0) + 1);
    let score = 0;
    for (const term of promptTerms) {
      const tf = counts.get(term) ?? 0;
      const idf = df.get(term);
      if (!tf || idf === undefined) continue;
      score += idf * (1 + Math.log(tf));
    }
    if (score > 0) ranked.push({ ...f.ref, score, content: f.content });
  }
  ranked.sort((a, b) => (b.score - a.score) || (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
  return ranked.slice(0, topN);
}
