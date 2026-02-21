// SPDX-License-Identifier: MIT
// OpenCode adapter - thin wrapper delegating to Go CLI (recall opencode <cmd>)

import type { Plugin } from "@opencode-ai/plugin"
import { readFileSync, existsSync, appendFileSync, mkdirSync, readdirSync, accessSync, constants } from 'fs';
import { join, delimiter, dirname } from 'path';
import { homedir } from 'os';
import { spawn } from 'child_process';

// Configuration
const DEFAULT_CONFIG = { enabled: true, topLessonsToShow: 5, relevanceTopN: 5, remindEvery: 12, debugLevel: 1 };
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

// CLI Detection
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
  const recall = findBinary('recall') || findBinary('claude-recall');
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
try { RECALL_BINARY = findRecallBinary(); } catch { /* will handle in execGo */ }

// Whitelist of allowed Go commands for subprocess calls
const ALLOWED_GO_COMMANDS = new Set(['session-start', 'session-idle', 'pre-compact', 'post-compact', 'session-end']);

async function execGo(cmd: string, input: object): Promise<Record<string, any>> {
  if (!ALLOWED_GO_COMMANDS.has(cmd)) {
    throw new Error(`Invalid Go command: ${cmd}`);
  }

  // Validate input is JSON-serializable (defense-in-depth)
  let inputJson: string;
  try {
    inputJson = JSON.stringify(input);
  } catch (e) {
    throw new Error(`Invalid input for command ${cmd}: not JSON-serializable`);
  }

  if (!RECALL_BINARY) {
    log('error', 'binary.not_found', { cmd });
    throw new Error("recall binary not found - run ./install.sh --opencode");
  }
  const binary = RECALL_BINARY;
  return new Promise((resolve, reject) => {
    const proc = spawn(binary, ["opencode", cmd], { env: { ...process.env, PROJECT_DIR: process.cwd() } });
    let out = "", err = "";
    const timer = setTimeout(() => { proc.kill(); reject(new Error(`timeout: recall opencode ${cmd}`)); }, 30000);
    try {
      proc.stdin.write(inputJson);
      proc.stdin.end();
    } catch (e) {
      clearTimeout(timer);
      proc.kill();
      reject(e);
      return;
    }
    proc.stdout.on("data", d => out += d);
    proc.stderr.on("data", d => err += d);
    proc.on("close", code => {
      clearTimeout(timer);
      if (code !== 0) return reject(new Error(`recall opencode ${cmd}: ${err || out}`));
      try { resolve(JSON.parse(out)); } catch { reject(new Error(`invalid JSON: ${out}`)); }
    });
    proc.on("error", e => { clearTimeout(timer); reject(e); });
  });
}

// Legacy CLI for slash commands
const LEGACY_CLI = findBinary('claude-recall') || join(homedir(), '.config', 'claude-recall', 'core', 'cli.py');

// Helpers
const COMMANDS = new Set(["lessons", "handoffs"]);
const normCmd = (s: string) => s.trim().replace(/^\/+/, "").toLowerCase();
const parseCmd = (t: string) => { const m = t.trim().match(/^\/?(\S+)(?:\s+([\s\S]+))?$/); return m ? { name: normCmd(m[1]), args: m[2]?.trim() ?? "" } : null; };
const getText = (parts: any[]) => (parts || []).filter((p: any) => p?.type === "text").map((p: any) => p.text).join(" ").trim();
const quote = (s: string) => s === "" ? "''" : `'${s.replace(/'/g, "'\"'\"'")}'`;
const shellCmd = (exe: string, args: string[]) => [exe, ...args].map(quote).join(" ");

function buildArgs(cmd: string, argText: string): string[] {
  const args = argText.split(/\s+/).filter(Boolean);
  if (cmd === "lessons") return args.length ? args : ["list"];
  if (cmd === "handoffs") return args.length === 0 ? ["handoff", "list"] : args[0] !== "handoff" ? ["handoff", ...args] : args;
  return args;
}

// Plugin Export
export const LessonsPlugin: Plugin = async ({ $, client }) => {
  log('info', 'plugin.loaded', { legacy_cli: LEGACY_CLI });

  // Session state
  const checkpoints = new Map<string, number>();
  const state = new Map<string, { isFirstPrompt: boolean; promptCount: number; compactionOccurred: boolean }>();
  const processing = new Set<string>();
  const processed = new Map<string, Set<string>>();
  const lastActivity = new Map<string, number>(); // Track last activity time per session

  const wasProcessed = (sid: string, mid: string) => processed.get(sid)?.has(mid) ?? false;
  const markProcessed = (sid: string, mid: string) => { if (!processed.has(sid)) processed.set(sid, new Set()); processed.get(sid)!.add(mid); };
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
        processed.delete(sid);
        lastActivity.delete(sid);
        log('debug', 'session.stale_cleanup', { session_id: sid });
      }
    }
  };
  // Run cleanup every 15 minutes
  const cleanupInterval = setInterval(cleanupStaleSessions, 15 * 60 * 1000);

  const runCmd = async (sid: string, cmd: string, args: string) => {
    const cmdLine = shellCmd(LEGACY_CLI, buildArgs(cmd, args));
    try {
      await client.session.shell({ path: { id: sid }, body: { agent: "claude-recall", command: cmdLine } });
      log('info', 'command.executed', { cmd, args });
    } catch (e) {
      log('warn', 'command.failed', { error: String(e), cmd });
      try { await client.session.prompt({ path: { id: sid }, body: { noReply: true, parts: [{ type: "text", text: `claude-recall failed: ${e}` }] } }); } catch (e2) { log('debug', 'command.notification_failed', { error: String(e2) }); }
    }
  };

  return {
    "session.created": async (input) => {
      const sid = input.session.id;
      log('info', 'session.start', { session_id: sid });

      try {
        const result = await execGo("session-start", { cwd: process.cwd(), top_n: CONFIG.topLessonsToShow, include_duties: true, include_todos: true });

        // Only initialize state AFTER successful injection
        state.set(sid, { isFirstPrompt: true, promptCount: 0, compactionOccurred: false });
        touchSession(sid);

        const parts: string[] = [];
        if (result.lessons_context) parts.push(`<lessons-context>\n${result.lessons_context}\n</lessons-context>`);
        if (result.handoffs_context) parts.push(`<handoffs-context>\n${result.handoffs_context}\n</handoffs-context>`);
        if (result.todos_prompt) parts.push(`<todos-prompt>\n${result.todos_prompt}\n</todos-prompt>`);
        if (result.duty_reminders) parts.push(result.duty_reminders);
        if (parts.length) await client.session.prompt({ path: { id: sid }, body: { noReply: true, parts: [{ type: "text", text: parts.join("\n\n") }] } });
      } catch (e) {
        log('error', 'session.injection_failed', { error: String(e) });
        // Still initialize state but mark as degraded
        state.set(sid, { isFirstPrompt: true, promptCount: 0, compactionOccurred: false });
        touchSession(sid);
      }
    },

    // TODO: OpenCode does not have a session.end event (as of @opencode-ai/plugin 1.1.49).
    // When/if they add one, we should call execGo("session-end", ...) to capture final handoff context.
    // For now, session.deleted is the closest we have, but it doesn't provide conversation state.
    // The Go CLI has session-end support ready: recall opencode session-end
    "session.deleted": async (input) => {
      const sid = input.session.id;
      checkpoints.delete(sid); state.delete(sid); processing.delete(sid); processed.delete(sid); lastActivity.delete(sid);
      log('debug', 'session.cleanup', { session_id: sid });
    },

    "tool.execute.after": async (input) => {
      if (input.tool !== "TodoWrite") return;
      const todos = input.result?.todos;
      if (!Array.isArray(todos)) return;
      const valid = todos.filter((t: any) => t?.content && t?.status);
      if (!valid.length) return;
      const json = JSON.stringify(valid);
      const sid = input.session?.id;
      try {
        const { stdout } = sid ? await $`${LEGACY_CLI} handoff sync-todos ${json} --session-id ${sid}` : await $`${LEGACY_CLI} handoff sync-todos ${json}`;
        if (stdout) log('info', 'handoff.sync_todos', { result: stdout });
      } catch (e) { log('debug', 'handoff.sync_failed', { error: String(e) }); }
    },

    "command.executed": (input) => {
      void (async () => {
        if (!CONFIG.enabled) return;
        const rawName = String(input.command?.name ?? input.name ?? input.command ?? "");
        let cmd = normCmd(rawName);
        let args = String(input.command?.arguments ?? input.arguments ?? input.args ?? "");
        const sid = input.session?.id ?? input.sessionID ?? input.sessionId;
        const mid = input.message?.id ?? input.messageID ?? input.messageId;
        if (!sid) return;
        if (mid && wasProcessed(sid, mid)) return;

        if (mid && (!cmd || !args)) {
          try { const msg = await client.session.message({ path: { id: sid, messageID: mid } }); const parsed = parseCmd(getText(msg.parts)); if (parsed) { cmd = parsed.name; args = args || parsed.args; } } catch { /* ignore */ }
        }
        if (!COMMANDS.has(cmd)) return;
        if (mid) { markProcessed(sid, mid); try { await client.session.revert({ path: { id: sid }, body: { messageID: mid } }); } catch { /* ignore */ } }
        await runCmd(sid, cmd, args);
      })().catch(e => log('error', 'command.executed.failed', { error: String(e) }));
    },

    "message.created": async (input) => {
      if (input.message.role !== "user") return;
      const sid = input.session.id;
      touchSession(sid);
      const mid = input.message.id;
      const text = getText(input.message.parts);

      if (mid && text) {
        const parsed = parseCmd(text);
        if (parsed && COMMANDS.has(parsed.name)) {
          if (wasProcessed(sid, mid)) return;
          markProcessed(sid, mid);
          try { await client.session.revert({ path: { id: sid }, body: { messageID: mid } }); } catch { /* ignore */ }
          await runCmd(sid, parsed.name, parsed.args);
          return;
        }
      }

      const s = state.get(sid);
      if (!s || !text.trim()) return;

      if (s.isFirstPrompt) {
        try {
          const { stdout } = await $`${LEGACY_CLI} score-relevance ${text} --top ${CONFIG.relevanceTopN}`;
          if (stdout?.trim()) await client.session.prompt({ path: { id: sid }, body: { noReply: true, parts: [{ type: "text", text: `<relevant-lessons>\n${stdout}\n</relevant-lessons>` }] } });
        } catch (e) { log('debug', 'injection.smart_failed', { error: String(e) }); }
        s.isFirstPrompt = false;
      }

      s.promptCount++;
      if (s.promptCount % CONFIG.remindEvery === 0) {
        try {
          const { stdout } = await $`${LEGACY_CLI} inject ${CONFIG.topLessonsToShow}`;
          if (stdout?.trim()) await client.session.prompt({ path: { id: sid }, body: { noReply: true, parts: [{ type: "text", text: `<periodic-reminder>\n${stdout}\n</periodic-reminder>` }] } });
        } catch (e) { log('debug', 'injection.periodic_failed', { error: String(e) }); }
        s.promptCount = 0;
      }
    },

    "session.idle": async (input) => {
      const sid = input.session.id;
      touchSession(sid);
      if (processing.has(sid)) return;
      processing.add(sid);

      try {
        const msgs = await client.session.messages({ path: { id: sid } });
        const cp = checkpoints.get(sid) ?? 0;
        const arr = msgs.slice(cp).map(m => ({ role: m.info.role, content: m.parts.filter(p => p.type === "text").map((p: any) => p.text).join("") }));
        const result = await execGo("session-idle", { cwd: process.cwd(), session_id: sid, messages: arr, checkpoint_offset: 0 });

        // Check for errors before advancing checkpoint
        if (result.error) {
          log('error', 'session.idle_error', { error: result.error });
          return; // Don't advance checkpoint on error
        }

        // Log successful operations
        if (result.citations?.length) log('info', 'lessons.cited', { citations: result.citations });
        if (result.lessons_added?.length) log('info', 'lessons.added', { lessons: result.lessons_added });
        if (result.handoff_ops?.length) log('info', 'handoff.ops', { ops: result.handoff_ops });

        // Update checkpoint ONLY after successful processing
        checkpoints.set(sid, msgs.length);
      } catch (e) { log('debug', 'session.idle_failed', { error: String(e) }); }
      finally { processing.delete(sid); }
    },

    "experimental.session.compacting": async (input) => {
      const sid = input.session.id;
      if (!state.has(sid)) return;
      log('info', 'compaction.start', { session_id: sid });

      try {
        let hid = "";
        try { const { stdout } = await $`${LEGACY_CLI} handoff list --json`; const hs = JSON.parse(stdout || "[]"); const a = hs.find((h: any) => h.status !== "completed"); if (a) hid = a.id; } catch { /* ignore */ }
        const result = await execGo("pre-compact", { cwd: process.cwd(), session_id: sid, handoff_id: hid, files_modified: [], todos: [] });
        if (result.context_to_inject) await client.session.prompt({ path: { id: sid }, body: { noReply: true, parts: [{ type: "text", text: result.context_to_inject }] } });
      } catch (e) { log('debug', 'compaction.pre_failed', { error: String(e) }); }
    },

    "session.compacted": async (input) => {
      const sid = input.session.id;
      const s = state.get(sid);
      if (!s) return;
      log('info', 'compaction.end', { session_id: sid });
      s.compactionOccurred = true;

      try {
        const msgs = await client.session.messages({ path: { id: sid } });
        const recent = msgs.filter(m => m.info.role === "assistant").slice(-5);
        const indicators = ["completed", "finished", "done", "implemented", "ready for review", "successfully", "all tests pass"];
        let hasCompletion = false;
        for (const m of recent) {
          const c = m.parts.filter((p: any) => p.type === "text").map((p: any) => p.text).join(" ").toLowerCase();
          if (indicators.some(i => c.includes(i)) && !c.includes("not completed") && !c.includes("not finished") && !c.includes("not done")) { hasCompletion = true; break; }
        }
        const result = await execGo("post-compact", { cwd: process.cwd(), session_id: sid, handoff_id: "", phase: "", summary: "", completion_indicators: hasCompletion, all_todos_complete: false });
        if (result.suggest_complete) log('info', 'handoff.completion_suggested', { session_id: sid });
      } catch (e) { log('debug', 'compaction.post_failed', { error: String(e) }); }
    },
  };
};


