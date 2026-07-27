// SPDX-License-Identifier: MIT
// OpenCode adapter - thin wrapper delegating to the Go CLI (recall opencode <cmd>).
//
// Rewritten for @opencode-ai/plugin 1.17.5 (OpenCode 1.18.x):
//   - Lifecycle arrives via the single `event` hook (Event union from the SDK);
//     the old top-level "session.created"/"session.idle"/"message.created"/
//     "session.compacted"/"command.executed" hooks no longer exist.
//   - Session-start context (lessons + duty reminders +
//     MEMORY.md) is injected via experimental.chat.system.transform.
//   - First-prompt relevance + periodic reminders append synthetic parts in
//     chat.message instead of client.session.prompt({ noReply: true }).
//   - /lessons is a native OpenCode command (command/*.md): the
//     agent runs the claude-recall CLI itself. The command.executed +
//     client.session.revert interception hack is deleted.
//   - WRITE BRIDGE: lessons captured by `recall opencode session-idle` are
//     mirrored as feedback_<slug>.md files + a bridge-owned MEMORY.md section
//     (lib/memory.ts), so Claude Code sessions read them via auto-memory.
//   - DEEP READ: the first prompt of a session also ranks the actual memory
//     FILES (not just the MEMORY.md index) and injects the top matches as a
//     <relevant-memory> synthetic part.

import type { Plugin } from "@opencode-ai/plugin"
import type { Part, TextPart } from "@opencode-ai/sdk"
import { readFileSync, existsSync, appendFileSync, mkdirSync, readdirSync, accessSync, constants } from 'fs';
import { join, delimiter, dirname } from 'path';
import { homedir } from 'os';
import { spawn } from 'child_process';
// Pure MEMORY.md logic lives in lib/ (OpenCode auto-loads every top-level
// plugins/*.ts as a plugin entry; subdirectories are import-safe).
import {
  readMemoryContext, memoryDirOrCreate, parseLessonsFile, mirrorLessonsBatch,
  rankMemoryFiles, MEMORY_INJECT_FILE_CAP,
} from "./lib/memory";

// Configuration
const DEFAULT_CONFIG = {
  enabled: true, topLessonsToShow: 5, relevanceTopN: 5, remindEvery: 12, debugLevel: 1,
  memoryMaxBytes: 8192,
  mirrorMemory: true,            // write bridge: opencode lessons -> memory files
  mirrorMemoryMaxPerSession: 10, // runaway cap on mirrored files per session
  memoryRelevance: true,         // deep read: rank memory files on first prompt
  memoryRelevanceTopN: 2,        // how many top-scoring memory files to inject
};
type Config = typeof DEFAULT_CONFIG;
let CONFIG: Config = DEFAULT_CONFIG;

function loadConfig(): Config {
  const configPath = process.env.CLAUDE_RECALL_CONFIG || join(homedir(), '.config', 'claude-recall', 'config.json');
  const debugEnv = process.env.CLAUDE_RECALL_DEBUG ?? process.env.RECALL_DEBUG ?? process.env.LESSONS_DEBUG;
  const base = existsSync(configPath) ? { ...DEFAULT_CONFIG, ...JSON.parse(readFileSync(configPath, 'utf8') || '{}') } : DEFAULT_CONFIG;
  return debugEnv ? { ...base, debugLevel: Number(debugEnv) || base.debugLevel } : base;
}
try { CONFIG = loadConfig(); } catch { /* use defaults */ }

// Logging
type LogLevel = 'debug' | 'info' | 'warn' | 'error';
const LOG_PATH = join(process.env.CLAUDE_RECALL_STATE || process.env.XDG_STATE_HOME || join(homedir(), '.local', 'state'), 'claude-recall', 'debug.log');

function log(level: LogLevel, event: string, data?: Record<string, any>): void {
  const minLevel = CONFIG.debugLevel === 0 ? 4 : CONFIG.debugLevel === 1 ? 2 : CONFIG.debugLevel === 2 ? 1 : 0;
  const levelNum = { debug: 0, info: 1, warn: 2, error: 3 }[level];
  if (levelNum < minLevel) return;
  try {
    mkdirSync(dirname(LOG_PATH), { recursive: true });
    appendFileSync(LOG_PATH, JSON.stringify({ timestamp: new Date().toISOString(), level, event, ...data }) + '\n');
  } catch { /* ignore */ }
}

// CLI detection. The `recall` Go binary handles everything this adapter needs
// (`opencode <sub>`, `score-relevance`, `inject`). The
// `claude-recall` wrapper is NOT a fallback: it routes unknown commands to the
// Python TUI, which would hang on `opencode <sub>`.
const isExec = (p: string) => { try { accessSync(p, constants.X_OK); return true; } catch { return false; } };

function findBinary(name: string): string | null {
  for (const dir of (process.env.PATH || '').split(delimiter)) {
    const p = join(dir, name);
    if (isExec(p)) return p;
  }
  const local = join(homedir(), '.local', 'bin', name);
  if (isExec(local)) return local;
  return null;
}

function findRecallBinary(): string | null {
  const recall = findBinary('recall');
  if (recall) return recall;
  const cache = join(homedir(), '.claude', 'plugins', 'cache', 'claude-recall', 'claude-recall');
  if (existsSync(cache)) {
    const versions = readdirSync(cache).filter(e => !e.startsWith('.')).sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
    const bin = versions.length ? join(cache, versions[versions.length - 1], 'bin', 'recall') : null;
    if (bin && isExec(bin)) return bin;
  }
  return null;
}

// Cache binary lookup at module load
let RECALL_BINARY: string | null = null;
try { RECALL_BINARY = findRecallBinary(); } catch { /* handled in execRecall */ }

// Whitelists for subprocess calls (defense-in-depth; args are passed as an
// argv array to spawn, never through a shell).
const ALLOWED_GO_COMMANDS = new Set(['session-start', 'session-idle']);
const ALLOWED_CLI_COMMANDS = new Set(['score-relevance', 'inject']);

// Claude Code auto-memory (MEMORY.md): memoryDir / readFileCapped /
// readMemoryContext are imported from ./lib/memory (pure, unit-tested in
// tests/plugin_ts/). The plugin reads project memory plus the global tier
// (memory/global symlink), capped at CONFIG.memoryMaxBytes (default 8192).

// Helpers
const getText = (parts: Part[]) => (parts || [])
  .filter((p): p is TextPart => p?.type === "text" && !(p as TextPart).synthetic)
  .map(p => p.text).join(" ").trim();

let partCounter = 0;
function syntheticTextPart(sessionID: string, messageID: string, text: string): TextPart {
  // OpenCode validates part IDs with a "prt" prefix schema (Session.updatePart);
  // any other prefix fails the whole user-message save with a SchemaError.
  return { id: `prt_cr${Date.now().toString(36)}${(partCounter++).toString(36)}`, sessionID, messageID, type: "text", text, synthetic: true };
}

interface SessionState { isFirstPrompt: boolean; promptCount: number; compactionOccurred: boolean }

// Plugin export
export const LessonsPlugin: Plugin = async ({ client, directory }) => {
  const projectDir = directory || process.cwd();
  log('info', 'plugin.loaded', { recall_binary: RECALL_BINARY, directory: projectDir });

  // Session state
  const checkpoints = new Map<string, number>();
  const state = new Map<string, SessionState>();
  const processing = new Set<string>();
  const systemContext = new Map<string, string>(); // cached session-start injection per session
  const pendingInit = new Map<string, Promise<void>>(); // dedupe concurrent init
  const lastActivity = new Map<string, number>();
  const mirrorCounts = new Map<string, number>(); // write-bridge files written per session

  const touchSession = (sid: string) => lastActivity.set(sid, Date.now());

  // Cleanup stale sessions (no activity for 1 hour)
  const STALE_SESSION_MS = 60 * 60 * 1000;
  const cleanupStaleSessions = () => {
    const now = Date.now();
    for (const [sid, lastTime] of lastActivity) {
      if (now - lastTime > STALE_SESSION_MS) {
        checkpoints.delete(sid);
        state.delete(sid);
        processing.delete(sid);
        systemContext.delete(sid);
        pendingInit.delete(sid);
        lastActivity.delete(sid);
        mirrorCounts.delete(sid);
        log('debug', 'session.stale_cleanup', { session_id: sid });
      }
    }
  };
  const cleanupInterval = setInterval(cleanupStaleSessions, 15 * 60 * 1000);
  cleanupInterval.unref?.(); // never keep the host process alive for this

  // MEMORY.md is project-scoped; read lazily, once per plugin instance.
  let memoryContext: string | null | undefined;
  const getMemoryContext = (): string | null => {
    if (memoryContext === undefined) {
      memoryContext = readMemoryContext(projectDir, homedir(), CONFIG.memoryMaxBytes);
      log('debug', memoryContext ? 'memory.loaded' : 'memory.none', { bytes: memoryContext?.length ?? 0 });
    }
    return memoryContext;
  };

  // Subprocess execution
  function execRecall(args: string[], stdinJson?: string): Promise<{ stdout: string; stderr: string }> {
    if (!RECALL_BINARY) {
      log('error', 'binary.not_found', { cmd: args[0] });
      return Promise.reject(new Error("recall binary not found - run ./install.sh --opencode"));
    }
    const binary = RECALL_BINARY;
    return new Promise((resolve, reject) => {
      const proc = spawn(binary, args, { env: { ...process.env, PROJECT_DIR: projectDir } });
      let out = "", err = "";
      const timer = setTimeout(() => { proc.kill(); reject(new Error(`timeout: recall ${args.join(' ')}`)); }, 30000);
      if (stdinJson !== undefined) {
        try {
          proc.stdin.write(stdinJson);
          proc.stdin.end();
        } catch (e) {
          clearTimeout(timer);
          proc.kill();
          reject(e);
          return;
        }
      }
      proc.stdout.on("data", d => out += d);
      proc.stderr.on("data", d => err += d);
      proc.on("close", code => {
        clearTimeout(timer);
        if (code !== 0) return reject(new Error(`recall ${args.join(' ')}: ${err || out}`));
        resolve({ stdout: out, stderr: err });
      });
      proc.on("error", e => { clearTimeout(timer); reject(e); });
    });
  }

  async function execGo(cmd: string, input: object): Promise<Record<string, any>> {
    if (!ALLOWED_GO_COMMANDS.has(cmd)) {
      throw new Error(`Invalid Go command: ${cmd}`);
    }
    let inputJson: string;
    try {
      inputJson = JSON.stringify(input);
    } catch {
      throw new Error(`Invalid input for command ${cmd}: not JSON-serializable`);
    }
    const { stdout } = await execRecall(["opencode", cmd], inputJson);
    try { return JSON.parse(stdout); } catch { throw new Error(`invalid JSON: ${stdout}`); }
  }

  async function execCli(args: string[]): Promise<{ stdout: string; stderr: string }> {
    if (!args.length || !ALLOWED_CLI_COMMANDS.has(args[0])) {
      throw new Error(`Invalid CLI command: ${args[0] ?? ''}`);
    }
    return execRecall(args);
  }

  // Session-start context: Go session-start output + MEMORY.md, cached per session.
  async function buildSessionContext(sid: string): Promise<string> {
    const parts: string[] = [];
    const sections: string[] = [];
    try {
      const result = await execGo("session-start", { cwd: projectDir, top_n: CONFIG.topLessonsToShow, include_duties: true, include_todos: true });
      if (result.lessons_context) { parts.push(`<lessons-context>\n${result.lessons_context}\n</lessons-context>`); sections.push('lessons'); }
      if (result.duty_reminders) { parts.push(result.duty_reminders); sections.push('duties'); }
    } catch (e) {
      log('error', 'session.injection_failed', { error: String(e), session_id: sid });
    }
    const mem = getMemoryContext();
    if (mem) { parts.push(`<claude-memory>\n${mem}\n</claude-memory>`); sections.push('memory'); }
    const ctx = parts.join("\n\n");
    log('info', 'session.context_built', { session_id: sid, sections, bytes: ctx.length });
    log('debug', 'session.context_content', { session_id: sid, content: ctx });
    return ctx;
  }

  // Idempotent, concurrency-safe session init. Called from session.created and
  // lazily from the injection hooks (covers resumed sessions / plugin reloads).
  function ensureSession(sid: string): Promise<void> {
    if (state.has(sid)) return Promise.resolve();
    let pending = pendingInit.get(sid);
    if (!pending) {
      pending = (async () => {
        log('info', 'session.start', { session_id: sid });
        const ctx = await buildSessionContext(sid);
        state.set(sid, { isFirstPrompt: true, promptCount: 0, compactionOccurred: false });
        systemContext.set(sid, ctx);
        touchSession(sid);
      })().finally(() => pendingInit.delete(sid));
      pendingInit.set(sid, pending);
    }
    return pending;
  }

  const cleanupSession = (sid: string) => {
    checkpoints.delete(sid);
    state.delete(sid);
    processing.delete(sid);
    systemContext.delete(sid);
    lastActivity.delete(sid);
    mirrorCounts.delete(sid);
  };

  // WRITE BRIDGE: mirror newly captured project lessons into Claude Code
  // auto-memory (feedback_<slug>.md + a bridge-owned MEMORY.md section), so
  // Claude Code sessions on this project pick them up natively. PROJECT
  // lessons only: system lessons (S###) are user-level memory and the global
  // tier (~/.claude/memory-global) is Claude Code's domain - we never write
  // there. Every step is failure-isolated: mirroring must never break the
  // session.idle flow.
  function mirrorAddedLessons(sid: string, ids: string[]): void {
    try {
      if (!CONFIG.mirrorMemory) {
        log('debug', 'memory.mirror_skipped', { session_id: sid, reason: 'disabled_by_config', count: ids.length });
        return;
      }
      const projectIds = ids.filter(id => /^L\d{3}$/.test(id));
      const systemSkipped = ids.length - projectIds.length;
      if (systemSkipped > 0) {
        log('debug', 'memory.mirror_skipped', { session_id: sid, reason: 'system_lesson_not_mirrored', count: systemSkipped });
      }
      if (!projectIds.length) return;

      const already = mirrorCounts.get(sid) ?? 0;
      const remaining = Math.max(0, CONFIG.mirrorMemoryMaxPerSession - already);
      if (remaining <= 0) {
        log('info', 'memory.mirror_skipped', { session_id: sid, reason: 'session_cap', count: projectIds.length });
        return;
      }

      const dir = memoryDirOrCreate(projectDir, homedir());
      if (!dir) {
        log('warn', 'memory.mirror_error', { session_id: sid, error: 'memory dir unavailable', lessons: projectIds });
        return;
      }

      // The Go side just wrote these lessons to the project store; read it
      // back to resolve titles/content (session-idle returns IDs only).
      let store: Map<string, { title: string; content: string }>;
      try {
        store = parseLessonsFile(readFileSync(join(projectDir, '.claude-recall', 'LESSONS.md'), 'utf8'));
      } catch (e) {
        log('warn', 'memory.mirror_error', { session_id: sid, error: `lessons store unreadable: ${String(e)}`, lessons: projectIds });
        return;
      }

      const lessons: { id: string; title: string; content: string }[] = [];
      for (const id of projectIds) {
        const l = store.get(id);
        if (!l) {
          log('info', 'memory.mirror_skipped', { session_id: sid, lesson_id: id, reason: 'lesson_not_found' });
          continue;
        }
        lessons.push({ id, title: l.title, content: l.content });
      }
      if (!lessons.length) return;

      const outcomes = mirrorLessonsBatch({ memoryDir: dir, lessons, maxToWrite: remaining });
      for (const o of outcomes) {
        if (o.status === 'written') {
          log('info', 'memory.mirror_written', { session_id: sid, lesson_id: o.id, filename: o.filename, index_changed: o.indexChanged === true });
        } else if (o.status === 'skipped') {
          log('info', 'memory.mirror_skipped', { session_id: sid, lesson_id: o.id, reason: o.reason });
        } else {
          log('warn', 'memory.mirror_error', { session_id: sid, lesson_id: o.id, error: o.error });
        }
      }
      mirrorCounts.set(sid, already + outcomes.filter(o => o.status === 'written').length);
    } catch (e) {
      log('warn', 'memory.mirror_error', { session_id: sid, error: String(e) });
    }
  }

  async function onSessionIdle(sid: string): Promise<void> {
    touchSession(sid);
    if (processing.has(sid)) return;
    processing.add(sid);
    try {
      const res = await client.session.messages({ path: { id: sid } });
      const msgs = res.data ?? [];
      const cp = checkpoints.get(sid) ?? 0;
      const arr = msgs.slice(cp).map(m => ({ role: m.info.role, content: getText(m.parts) }));
      const result = await execGo("session-idle", { cwd: projectDir, session_id: sid, messages: arr, checkpoint_offset: 0 });

      if (result.error) {
        log('error', 'session.idle_error', { error: result.error });
        return; // don't advance checkpoint on error
      }
      if (result.citations?.length) log('info', 'lessons.cited', { citations: result.citations });
      if (result.lessons_added?.length) {
        log('info', 'lessons.added', { lessons: result.lessons_added });
        mirrorAddedLessons(sid, result.lessons_added);
      }
      checkpoints.set(sid, msgs.length);
    } catch (e) {
      log('debug', 'session.idle_failed', { error: String(e) });
    } finally {
      processing.delete(sid);
    }
  }

  return {
    dispose: async () => {
      clearInterval(cleanupInterval);
    },

    // All lifecycle events arrive through this single hook in 1.17.5.
    event: async ({ event }) => {
      try {
        switch (event.type) {
          case "session.created":
            await ensureSession(event.properties.info.id);
            break;
          case "session.deleted":
            // OpenCode still has no session.end event (as of 1.17.5), and
            // session.deleted carries no conversation state. Cleanup only.
            cleanupSession(event.properties.info.id);
            log('debug', 'session.cleanup', { session_id: event.properties.info.id });
            break;
          case "session.idle":
            await onSessionIdle(event.properties.sessionID);
            break;
        }
      } catch (e) {
        log('error', 'event.handler_failed', { error: String(e), event_type: event.type });
      }
    },

    // Session-start injection: system-prompt level, persists for the session.
    "experimental.chat.system.transform": async (input, output) => {
      if (!CONFIG.enabled) return;
      const sid = input.sessionID;
      if (!sid) return;
      try {
        await ensureSession(sid);
        const ctx = systemContext.get(sid);
        if (ctx && !output.system.includes(ctx)) {
          output.system.push(ctx);
          log('info', 'system.transform_injected', {
            session_id: sid, bytes: ctx.length,
            has_memory: ctx.includes('<claude-memory>'),
            has_lessons: ctx.includes('<lessons-context>'),
          });
          log('debug', 'system.transform_content', { session_id: sid, content: ctx });
        }
      } catch (e) {
        log('debug', 'system.transform_failed', { error: String(e) });
      }
    },

    // First-prompt relevance injection + periodic reminders, appended as
    // synthetic parts on the incoming user message.
    "chat.message": async (input, output) => {
      if (!CONFIG.enabled) return;
      const sid = input.sessionID;
      try {
        await ensureSession(sid);
        touchSession(sid);
        const s = state.get(sid)!;
        const text = getText(output.parts);
        if (!text) return;
        const messageID = input.messageID ?? output.message.id;

        if (s.isFirstPrompt) {
          try {
            const { stdout } = await execCli(["score-relevance", text, "--top", String(CONFIG.relevanceTopN)]);
            if (stdout.trim()) {
              const part = `<relevant-lessons>\n${stdout.trim()}\n</relevant-lessons>`;
              output.parts.push(syntheticTextPart(sid, messageID, part));
              log('info', 'chat.smart_injected', { session_id: sid, bytes: part.length });
              log('debug', 'chat.smart_content', { session_id: sid, content: part });
            }
          } catch (e) { log('debug', 'injection.smart_failed', { error: String(e) }); }

          // DEEP READ: rank the actual memory files against the prompt and
          // inject the top matches in full (capped). The session-start
          // injection only carries the MEMORY.md index (one-line pointers);
          // overlapping pointers are fine - this adds the content behind
          // them. One-time per session; failure-isolated like the rest.
          if (CONFIG.memoryRelevance) {
            try {
              const t0 = Date.now();
              const ranked = rankMemoryFiles(text, projectDir, homedir(), { topN: CONFIG.memoryRelevanceTopN });
              if (ranked.length) {
                const blocks = ranked.map(r => {
                  const body = r.content.length > MEMORY_INJECT_FILE_CAP
                    ? `${r.content.slice(0, MEMORY_INJECT_FILE_CAP).trimEnd()}\n[…truncated]`
                    : r.content;
                  return `### ${r.name}\n${body}`;
                });
                const part = `<relevant-memory>\n${blocks.join('\n\n')}\n</relevant-memory>`;
                output.parts.push(syntheticTextPart(sid, messageID, part));
                log('info', 'chat.memory_relevance_injected', {
                  session_id: sid, bytes: part.length, ms: Date.now() - t0,
                  files: ranked.map(r => ({ name: r.name, score: Math.round(r.score * 1000) / 1000 })),
                });
                log('debug', 'chat.memory_relevance_content', { session_id: sid, content: part });
              } else {
                log('debug', 'chat.memory_relevance_none', { session_id: sid, ms: Date.now() - t0 });
              }
            } catch (e) { log('debug', 'injection.memory_relevance_failed', { error: String(e) }); }
          }
          s.isFirstPrompt = false;
        }

        s.promptCount++;
        if (s.promptCount % CONFIG.remindEvery === 0) {
          try {
            const { stdout } = await execCli(["inject", String(CONFIG.topLessonsToShow)]);
            if (stdout.trim()) {
              const part = `<periodic-reminder>\n${stdout.trim()}\n</periodic-reminder>`;
              output.parts.push(syntheticTextPart(sid, messageID, part));
              log('info', 'chat.reminder_injected', { session_id: sid, bytes: part.length });
            }
          } catch (e) { log('debug', 'injection.periodic_failed', { error: String(e) }); }
          s.promptCount = 0;
        }
      } catch (e) {
        log('debug', 'chat.message_failed', { error: String(e) });
      }
    },

  };
};
