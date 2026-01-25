// SPDX-License-Identifier: MIT
// OpenCode adapter for coding-agent-lessons
//
// Hooks into OpenCode events to:
// 1. Inject lessons context at session start
// 2. Inject active handoffs at session start
// 3. Track lesson citations when AI responds (with checkpointing)
// 4. Capture LESSON: commands from user input
// 5. Sync TodoWrite to active handoff
// 6. Capture HANDOFF: patterns from assistant output

import type { Plugin } from "@opencode-ai/plugin"
import * as os from "os"
import { readFileSync, existsSync, appendFileSync, mkdirSync, writeFileSync, readdirSync, accessSync, constants } from 'fs';
import { join, delimiter, dirname } from 'path';
import { homedir } from 'os';

interface Config {
  enabled: boolean;
  maxLessons: number;
  topLessonsToShow: number;
  relevanceTopN: number;
  remindEvery: number;
  promotionThreshold: number;
  decayIntervalDays: number;
  debugLevel: number;
  small_model?: string;
}

const DEFAULT_CONFIG: Config = {
  enabled: true,
  maxLessons: 30,
  topLessonsToShow: 5,
  relevanceTopN: 5,
  remindEvery: 12,
  promotionThreshold: 50,
  decayIntervalDays: 7,
  debugLevel: 1,
};

let CONFIG: Config | undefined = DEFAULT_CONFIG;

function loadConfig(): Config {
  const configPath = process.env.CLAUDE_RECALL_CONFIG
    ? process.env.CLAUDE_RECALL_CONFIG
    : join(homedir(), '.config', 'claude-recall', 'config.json');
  const debugEnv = process.env.CLAUDE_RECALL_DEBUG
    ?? process.env.RECALL_DEBUG
    ?? process.env.LESSONS_DEBUG;

  const applyDebugOverride = (config: Config): Config => {
    if (debugEnv === undefined || debugEnv === "") return config;
    const parsed = Number(debugEnv);
    if (Number.isNaN(parsed)) {
      log('warn', 'config.debug_env_invalid', { value: debugEnv });
      return config;
    }
    return { ...config, debugLevel: parsed };
  };

  if (!existsSync(configPath)) {
    log('warn', 'config.not_found', { using_defaults: true });
    return applyDebugOverride({ ...DEFAULT_CONFIG });
  }

  try {
    const config = JSON.parse(readFileSync(configPath, 'utf8'));
    const configValues = typeof config === 'object' && config ? config : {};

    const merged = { ...DEFAULT_CONFIG, ...configValues };
    const finalConfig = applyDebugOverride(merged);

    if (finalConfig.debugLevel >= 2) {
      log('debug', 'config.loaded', finalConfig);
    }

    return finalConfig;
  } catch (e) {
    log('error', 'config.load_failed', { error: String(e) });
    return applyDebugOverride({ ...DEFAULT_CONFIG });
  }
}

CONFIG = loadConfig();

// =============================================================================
// Debug Logging
// =============================================================================

type LogLevel = 'debug' | 'info' | 'warn' | 'error';

interface LogEntry {
  timestamp: string;
  level: LogLevel;
  event: string;
  data?: Record<string, any>;
}

function getDebugLogPath(): string {
  const stateEnv = process.env.CLAUDE_RECALL_STATE || process.env.XDG_STATE_HOME;
  if (stateEnv) {
    return join(stateEnv, 'claude-recall', 'debug.log');
  }
  return join(homedir(), '.local', 'state', 'claude-recall', 'debug.log');
}

function shouldLog(level: LogLevel): boolean {
  const debugLevel = CONFIG?.debugLevel ?? DEFAULT_CONFIG.debugLevel;

  if (debugLevel === 0) return false;
  if (debugLevel === 1) return level === 'warn' || level === 'error';
  if (debugLevel === 2) return level === 'info' || level === 'warn' || level === 'error';
  return true;
}

function log(level: LogLevel, event: string, data?: Record<string, any>): void {
  if (!shouldLog(level)) return;

  const entry: LogEntry = {
    timestamp: new Date().toISOString(),
    level,
    event,
    ...data,
  };

  try {
    const logPath = getDebugLogPath();
    const logDir = dirname(logPath);

    mkdirSync(logDir, { recursive: true });
    appendFileSync(logPath, JSON.stringify(entry) + '\n', 'utf8');
  } catch (e) {
  }
}

interface ModelInfo {
  name: string;
  tool_call: boolean;
  reasoning: boolean;
  cost?: { input: number; output: number };
}

interface Provider {
  id: string;
  models: Record<string, ModelInfo>;
}

interface ProviderListResponse {
  data: {
    all: Provider[];
    default: { [providerId: string]: string };
    connected: string[];
  };
}

const PREFERRED_MODELS = [
  'grok-code-fast-1',
  'claude-3-5-haiku-latest',
  'gpt-5-mini',
  'gpt-4o-mini',
];

let cachedFastModel: string | null = null;

async function detectFastModel(
  client: any,
  configuredSmallModel?: string
): Promise<string | null> {
  if (configuredSmallModel) {
    try {
      const providers = await client.provider.list() as ProviderListResponse;
      const isAvailable = providers.data.all.some(p =>
        configuredSmallModel in p.models
      );
      if (isAvailable) {
        log('debug', 'model.using_configured', { model: configuredSmallModel });
        return configuredSmallModel;
      }
    } catch (e) {
      log('warn', 'model.check_failed', { error: String(e) });
    }
  }

  try {
    const providers = await client.provider.list() as ProviderListResponse;

    const qualityModels: Array<{provider: string; model: string; info: ModelInfo}> = [];
    for (const provider of providers.data.all) {
      for (const [modelId, info] of Object.entries(provider.models)) {
        if (info.tool_call && info.reasoning) {
          qualityModels.push({ provider: provider.id, model: modelId, info });
        }
      }
    }

    if (qualityModels.length === 0) {
      log('warn', 'model.no_quality_models', {});
      return null;
    }

    log('debug', 'model.quality_found', { count: qualityModels.length });

    for (const pref of PREFERRED_MODELS) {
      const found = qualityModels.find(m => m.model === pref);
      if (found) {
        log('debug', 'model.using_preferred', { model: found.model });
        return found.model;
      }
    }

    const fallback = qualityModels[0];
    log('debug', 'model.using_fallback', { model: fallback.model });
    return fallback.model;

  } catch (e) {
    log('error', 'model.detection_failed', { error: String(e) });
    return null;
  }
}

// Detect CLI: wrapper → installed python → legacy → dev
function isExecutable(filePath: string): boolean {
  try {
    accessSync(filePath, constants.X_OK);
    return true;
  } catch {
    return false;
  }
}

function findCliWrapper(): string | null {
  const pathEnv = process.env.PATH || '';
  for (const entry of pathEnv.split(delimiter)) {
    if (!entry) continue;
    const candidate = join(entry, 'claude-recall');
    if (isExecutable(candidate)) return candidate;
  }

  const localBin = join(os.homedir(), '.local', 'bin', 'claude-recall');
  if (isExecutable(localBin)) return localBin;

  const legacyPlugin = join(os.homedir(), '.claude', 'plugins', 'claude-recall', 'bin', 'claude-recall');
  if (isExecutable(legacyPlugin)) return legacyPlugin;

  const cacheRoot = join(os.homedir(), '.claude', 'plugins', 'cache', 'claude-recall', 'claude-recall');
  if (existsSync(cacheRoot)) {
    const versions = readdirSync(cacheRoot)
      .filter((entry) => entry && !entry.startsWith('.'))
      .sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
    const latest = versions[versions.length - 1];
    if (latest) {
      const cachedWrapper = join(cacheRoot, latest, 'bin', 'claude-recall');
      if (isExecutable(cachedWrapper)) return cachedWrapper;
    }
  }

  return null;
}

function findPythonManager(): string {
  const installed = join(os.homedir(), '.config', 'claude-recall', 'core', 'cli.py');
  const legacy = join(os.homedir(), '.config', 'claude-recall', 'cli.py');
  const dev = join(__dirname, '..', '..', 'core', 'cli.py');

  if (existsSync(installed)) return installed;
  if (existsSync(legacy)) return legacy;
  return dev;
}

const MANAGER = findCliWrapper() ?? findPythonManager()

/**
 * Sanitize user input for shell commands.
 * Strips shell metacharacters that could enable command injection.
 * The bun shell's $ template literal does escape arguments, but we add
 * defense-in-depth by removing dangerous patterns before passing to shell.
 */
function sanitizeForShell(str: string): string {
  if (!str || typeof str !== 'string') return '';
  // Remove backticks, $(), ${}, and other shell expansion patterns
  return str
    .replace(/`/g, '')           // backticks for command substitution
    .replace(/\$\(/g, '')        // $() command substitution
    .replace(/\$\{/g, '')        // ${} variable expansion
    .replace(/\$[a-zA-Z_]/g, '') // $VAR variable references
    .replace(/[;&|<>]/g, '')     // command separators and redirects
    .replace(/\n/g, ' ')         // newlines could break commands
    .trim();
}

/**
 * Check if an error indicates a critical/broken plugin state.
 * These errors should be logged at warn/error level, not debug.
 */
function isCriticalError(e: unknown): boolean {
  const errorStr = String(e);
  return errorStr.includes('command not found') ||
         errorStr.includes('ENOENT') ||
         errorStr.includes('permission denied') ||
         errorStr.includes('No such file or directory');
}

const CLAUDE_RECALL_COMMANDS = new Set(["lessons", "handoffs"]);

function normalizeCommandName(name: string): string {
  return name.trim().replace(/^\/+/, "").toLowerCase();
}

function splitCommandArguments(argumentText: string): string[] {
  if (!argumentText) return [];
  return argumentText.trim().split(/\s+/).filter(Boolean);
}

function parseCommandText(text: string): { name: string; args: string } | null {
  const trimmed = text.trim();
  if (!trimmed) return null;
  const match = trimmed.match(/^\/?(\S+)(?:\s+([\s\S]+))?$/);
  if (!match) return null;
  return {
    name: normalizeCommandName(match[1]),
    args: match[2]?.trim() ?? "",
  };
}

function buildClaudeRecallArgs(commandName: string, argumentText: string): string[] {
  const rawArgs = splitCommandArguments(argumentText)
    .map(sanitizeForShell)
    .filter(Boolean);

  if (commandName === "lessons") {
    return rawArgs.length > 0 ? rawArgs : ["list"];
  }

  if (commandName === "handoffs") {
    if (rawArgs.length === 0) return ["handoff", "list"];
    if (rawArgs[0] !== "handoff") return ["handoff", ...rawArgs];
    return rawArgs;
  }

  return rawArgs;
}

function extractTextFromParts(parts: any[]): string {
  if (!Array.isArray(parts)) return "";
  return parts
    .filter((p: any) => p && p.type === "text")
    .map((p: { text: string }) => p.text)
    .join(" ")
    .trim();
}

function quoteShellArg(value: string): string {
  if (value === "") return "''";
  return `'${value.replace(/'/g, "'\"'\"'")}'`;
}

function buildShellCommand(executable: string, args: string[]): string {
  return [executable, ...args].map(quoteShellArg).join(" ");
}

export const LessonsPlugin: Plugin = async ({ $, client }) => {
  log('info', 'plugin.loaded', { manager: MANAGER });
  // Detect fast model in background - don't block plugin initialization
  // The result is logged but not currently used for scoring (Python CLI handles that)
  detectFastModel(client, CONFIG.small_model).then(model => {
    cachedFastModel = model;
    if (!model) {
      log('warn', 'plugin.no_fast_model', {});
    }
  }).catch(e => {
    log('warn', 'plugin.model_detection_failed', { error: String(e) });
  });

  const sessionCheckpoints = new Map<string, number>();
  const sessionState = new Map<string, { isFirstPrompt: boolean; promptCount: number; compactionOccurred: boolean }>();
  const processingCitations = new Set<string>();
  const processedCommandMessages = new Map<string, Set<string>>();

  const getProcessedCommandSet = (sessionId: string): Set<string> => {
    let set = processedCommandMessages.get(sessionId);
    if (!set) {
      set = new Set<string>();
      processedCommandMessages.set(sessionId, set);
    }
    return set;
  };

  const isCommandMessageProcessed = (sessionId: string, messageId: string): boolean =>
    processedCommandMessages.get(sessionId)?.has(messageId) ?? false;

  const markCommandMessageProcessed = (sessionId: string, messageId: string): void => {
    getProcessedCommandSet(sessionId).add(messageId);
  };

  const runClaudeRecallCommand = async (
    sessionId: string,
    commandName: string,
    argumentText: string,
    source: string
  ): Promise<void> => {
    const cliArgs = buildClaudeRecallArgs(commandName, argumentText);
    const commandLine = buildShellCommand(MANAGER, cliArgs);

    try {
      await client.session.shell({
        path: { id: sessionId },
        body: {
          agent: "claude-recall",
          command: commandLine,
        },
      });
      log('info', 'command.cli_executed', { name: commandName, args: cliArgs, source });
    } catch (e) {
      log(isCriticalError(e) ? 'warn' : 'debug', 'command.cli_failed', {
        error: String(e),
        name: commandName,
        args: cliArgs,
        source,
      });
      try {
        await client.session.prompt({
          path: { id: sessionId },
          body: {
            noReply: true,
            parts: [{
              type: "text",
              text: `claude-recall command failed: ${String(e)}`,
            }],
          },
        });
      } catch (err) {
        log('debug', 'command.error_prompt_failed', { error: String(err), source });
      }
    }
  };

  return {
    // Inject lessons and handoffs at session start
    "session.created": async (input) => {
      try {
        log('info', 'session.start', { session_id: input.session.id });

        // Initialize session state
        sessionState.set(input.session.id, {
          isFirstPrompt: true,
          promptCount: 0,
          compactionOccurred: false
        });

        // Run decay if it's been more than CONFIG.decayIntervalDays since last run
        try {
          await $`${MANAGER} decay ${CONFIG.decayIntervalDays}`
          log('debug', 'decay.run', { interval_days: CONFIG.decayIntervalDays });
        } catch (e) {
          log(isCriticalError(e) ? 'warn' : 'debug', 'decay.failed', { error: String(e) });
        }

        // Get lesson context to inject
        const { stdout: lessonsOutput } = await $`${MANAGER} inject ${CONFIG.topLessonsToShow}`

        // Get active handoffs to inject
        const { stdout: handoffsOutput } = await $`${MANAGER} handoff inject`

        // Combine lessons and handoffs
        const contextParts = []
        if (lessonsOutput && lessonsOutput.trim() && lessonsOutput.trim() !== "(no lessons)") {
          contextParts.push(`<lessons-context>\n${lessonsOutput}\n</lessons-context>`)
        }
        if (handoffsOutput && handoffsOutput.trim() && handoffsOutput.trim() !== "(no active handoffs)") {
          contextParts.push(`<handoffs-context>\n${handoffsOutput}\n</handoffs-context>`)
        }

        if (contextParts.length > 0) {
          log('debug', 'injection.context', { parts: contextParts.length });
          // Inject into session as context without triggering AI response
          await client.session.prompt({
            path: { id: input.session.id },
            body: {
              noReply: true,
              parts: [{
                type: "text",
                text: contextParts.join("\n\n")
              }],
            },
          })
        }
      } catch (e) {
        log('error', 'session.injection_failed', { error: String(e) });
      }
    },

    // Clean up session state when session is deleted (memory leak prevention)
    "session.deleted": async (input) => {
      sessionCheckpoints.delete(input.session.id);
      sessionState.delete(input.session.id);
      processingCitations.delete(input.session.id);
      processedCommandMessages.delete(input.session.id);
      log('debug', 'session.cleanup', { session_id: input.session.id });
    },

    // Sync TodoWrite to handoff
    "tool.execute.after": async (input) => {
      try {
        // Only process TodoWrite tool calls
        if (input.tool !== "TodoWrite") return;

        // Extract todos from tool result with validation
        const todos = input.result?.todos;
        if (!todos || !Array.isArray(todos)) return;

        // Validate todos have required fields
        const validTodos = todos.filter((t: any) =>
          t && typeof t === 'object' &&
          typeof t.content === 'string' &&
          typeof t.status === 'string'
        );
        if (validTodos.length === 0) return;

        // Convert validated todos to JSON for CLI
        const todosJson = JSON.stringify(validTodos);

        // Get session ID for cross-session pollution prevention
        const sessionId = input.session?.id;

        // Sync todos to active handoff
        try {
          const { stdout } = sessionId
            ? await $`${MANAGER} handoff sync-todos ${todosJson} --session-id ${sessionId}`
            : await $`${MANAGER} handoff sync-todos ${todosJson}`;
          if (stdout) {
            log('info', 'handoff.sync_todos', { result: stdout, sessionId });
          }
        } catch (e) {
          log(isCriticalError(e) ? 'warn' : 'debug', 'handoff.sync_failed', { error: String(e) });
        }
      } catch (e) {
        log('debug', 'handoff.sync_error', { error: String(e) });
      }
    },

    // Execute claude-recall slash commands directly
    "command.executed": (input) => {
      void (async () => {
        if (!CONFIG.enabled) return;

        if (CONFIG.debugLevel >= 2) {
          log('info', 'command.event', { payload: input });
        }

        const rawNameValue = input.command?.name ?? input.name ?? input.command ?? "";
        const rawName = typeof rawNameValue === "string" ? rawNameValue : String(rawNameValue ?? "");
        let commandName = normalizeCommandName(rawName);
        let argumentText = input.command?.arguments ?? input.arguments ?? input.args ?? "";
        if (typeof argumentText !== "string") {
          argumentText = String(argumentText ?? "");
        }
        const sessionId = input.session?.id ?? input.sessionID ?? input.sessionId;
        const messageId = input.message?.id ?? input.messageID ?? input.messageId;

        if (!sessionId) return;

        if (messageId && isCommandMessageProcessed(sessionId, messageId)) {
          log('debug', 'command.duplicate_skipped', { session_id: sessionId, message_id: messageId });
          return;
        }

        let messageRole: string | undefined;
        let messageText = "";

        if (messageId && (!commandName || !argumentText)) {
          try {
            const message = await client.session.message({
              path: { id: sessionId, messageID: messageId },
            });
            messageRole = message.info?.role;
            messageText = extractTextFromParts(message.parts);
          } catch (e) {
            log('debug', 'command.message_fetch_failed', { error: String(e) });
          }
        }

        if ((!commandName || !CLAUDE_RECALL_COMMANDS.has(commandName)) && messageText) {
          const parsed = parseCommandText(messageText);
          if (parsed) {
            commandName = parsed.name;
            if (!argumentText) argumentText = parsed.args;
          }
        }

        if (!CLAUDE_RECALL_COMMANDS.has(commandName)) return;

        if (messageId) {
          markCommandMessageProcessed(sessionId, messageId);
        }

        if (messageId) {
          try {
            await client.session.revert({
              path: { id: sessionId },
              body: { messageID: messageId },
            });
            log('debug', 'command.reverted', { session_id: sessionId, message_id: messageId });
          } catch (e) {
            log('debug', 'command.revert_failed', { error: String(e), message_id: messageId });
          }
        }

        await runClaudeRecallCommand(sessionId, commandName, argumentText, 'command.executed');
      })();
    },

    // Smart injection on first prompt, periodic reminders
    "message.created": async (input) => {
      if (input.message.role !== "user") return;

      const sessionId = input.session.id;
      const messageId = input.message.id;
      const messageText = extractTextFromParts(input.message.parts);

      if (messageId && messageText) {
        const parsed = parseCommandText(messageText);
        if (parsed && CLAUDE_RECALL_COMMANDS.has(parsed.name)) {
          if (isCommandMessageProcessed(sessionId, messageId)) return;
          markCommandMessageProcessed(sessionId, messageId);

          if (CONFIG.debugLevel >= 2) {
            log('info', 'command.message_created', {
              session_id: sessionId,
              message_id: messageId,
              name: parsed.name,
              args: parsed.args,
            });
          }

          try {
            await client.session.revert({
              path: { id: sessionId },
              body: { messageID: messageId },
            });
            log('debug', 'command.reverted', { session_id: sessionId, message_id: messageId });
          } catch (e) {
            log('debug', 'command.revert_failed', { error: String(e), message_id: messageId });
          }

          await runClaudeRecallCommand(sessionId, parsed.name, parsed.args, 'message.created');
          return;
        }
      }

      const state = sessionState.get(sessionId);
      if (!state) return;

      // Extract user query for relevance scoring
      const userQuery = messageText.trim();

      if (!userQuery) return;

      // Smart injection on first prompt
      if (state.isFirstPrompt) {
        try {
          log('debug', 'injection.smart_start', { query_length: userQuery.length });
          // Score lessons by relevance to user's query
          const sanitizedQuery = sanitizeForShell(userQuery);
          const { stdout } = await $`${MANAGER} score-relevance ${sanitizedQuery} --top ${CONFIG.relevanceTopN}`

          if (stdout && stdout.trim()) {
            log('debug', 'injection.smart_success', { output_length: stdout.length });
            // Inject relevant lessons as context
            await client.session.prompt({
              path: { id: input.session.id },
              body: {
                noReply: true,
                parts: [{
                  type: "text",
                  text: `<relevant-lessons>\n${stdout}\n</relevant-lessons>`
                }],
              },
            })
          }
        } catch (e) {
          log(isCriticalError(e) ? 'warn' : 'debug', 'injection.smart_failed', { error: String(e) });
        }
        state.isFirstPrompt = false;
      }

      // Periodic reminders: show top lessons every Nth prompt
      state.promptCount++;
      if (state.promptCount % CONFIG.remindEvery === 0) {
        try {
          log('debug', 'injection.periodic_start', { prompt_count: state.promptCount });
          // Get top lessons by stars
          const { stdout } = await $`${MANAGER} inject ${CONFIG.topLessonsToShow}`

          if (stdout && stdout.trim()) {
            log('debug', 'injection.periodic_success', { output_length: stdout.length });
            // Inject top lessons as reminder
            await client.session.prompt({
              path: { id: input.session.id },
              body: {
                noReply: true,
                parts: [{
                  type: "text",
                  text: `<periodic-reminder>\n${stdout}\n</periodic-reminder>`
                }],
              },
            })
          }
        } catch (e) {
          log('debug', 'injection.periodic_failed', { error: String(e) });
        }
        // Reset count after showing reminder
        state.promptCount = 0;
      }
    },

    // Track citations when session goes idle (AI finished responding)
    "session.idle": async (input) => {
      const sessionId = input.session.id

      // Prevent concurrent processing for the same session
      if (processingCitations.has(sessionId)) return;
      processingCitations.add(sessionId);

      try {
        // Get the messages from this session
        const messages = await client.session.messages({
          path: { id: sessionId }
        })

        // Get checkpoint: last processed message index
        const checkpoint = sessionCheckpoints.get(sessionId) ?? 0

        // Find assistant messages after the checkpoint
        const assistantMessages = messages
          .map((m, idx) => ({ ...m, idx }))
          .filter(m => m.info.role === "assistant" && m.idx >= checkpoint)

        if (assistantMessages.length === 0) {
          // Update checkpoint even if no new messages
          sessionCheckpoints.set(sessionId, messages.length)
          return
        }

        // Extract text content from all new assistant messages
        const allCitations = new Set<string>()

        for (const msg of assistantMessages) {
          const content = msg.parts
            .filter(p => p.type === "text")
            .map(p => (p as { type: "text"; text: string }).text)
            .join("")

          // Find [L###] or [S###] citations
          const citations = content.match(/\[(L|S)\d{3}\]/g) || []

          // Filter out lesson listings (e.g., "[L001] [*****" format)
          for (const cite of citations) {
            // Check if this is a real citation (not followed by star rating)
            if (!content.includes(`${cite} [*`)) {
              allCitations.add(cite)
            }
          }
        }

        // Cite each lesson in parallel
        await Promise.all(
          [...allCitations].map(cite => {
            const lessonId = cite.slice(1, -1) // Remove brackets
            return $`${MANAGER} cite ${lessonId}`.catch(e =>
              log('debug', 'citation.failed', { lessonId, error: String(e) })
            );
          })
        );

        // Update checkpoint to current message count
        sessionCheckpoints.set(sessionId, messages.length)

        if (allCitations.size > 0) {
          log('info', 'lessons.cited', { citations: [...allCitations], count: allCitations.size });
        }
      } catch (e) {
        log('debug', 'session.idle_failed', { error: String(e) });
      } finally {
        processingCitations.delete(sessionId);
      }
    },

    // Capture LESSON: commands from user messages, AI LESSON: from assistant
    "message.updated": async (input) => {
      const text = input.message.parts
        .filter(p => p.type === "text")
        .map(p => (p as { type: "text"; text: string }).text)
        .join("")

      if (input.message.role === "user") {
        try {
          // Check for LESSON: or SYSTEM LESSON: prefix
          const systemMatch = text.match(/^SYSTEM\s+LESSON:\s*(.+)$/im)
          const projectMatch = text.match(/^LESSON:\s*(.+)$/im)

          if (systemMatch || projectMatch) {
            const isSystem = !!systemMatch
            const lessonText = (systemMatch?.[1] || projectMatch?.[1] || "").trim()

            // Parse category: title - content
            let category = "correction"
            let title = lessonText
            let content = lessonText

            const catMatch = lessonText.match(/^([a-z]+):\s*(.+)$/i)
            if (catMatch) {
              category = catMatch[1].toLowerCase()
              const rest = catMatch[2]
              const dashMatch = rest.match(/^(.+?)\s*-\s*(.+)$/)
              if (dashMatch) {
                title = dashMatch[1].trim()
                content = dashMatch[2].trim()
              } else {
                title = rest
                content = rest
              }
            } else {
              const dashMatch = lessonText.match(/^(.+?)\s*-\s*(.+)$/)
              if (dashMatch) {
                title = dashMatch[1].trim()
                content = dashMatch[2].trim()
              }
            }

            // Add the lesson (sanitize user inputs)
            const cmd = isSystem ? "add-system" : "add"
            const safeCategory = sanitizeForShell(category)
            const safeTitle = sanitizeForShell(title)
            const safeContent = sanitizeForShell(content)
            const result = await $`${MANAGER} ${cmd} ${safeCategory} ${safeTitle} ${safeContent}`
            log('info', 'lessons.user_added', { category: safeCategory, title: safeTitle, is_system: isSystem, result: result.stdout });
          }
        } catch (e) {
          log('debug', 'lessons.user_add_failed', { error: String(e) });
        }
      } else if (input.message.role === "assistant") {
        try {
          // Capture AI LESSON: patterns
          const aiLessonMatch = text.match(/AI LESSON:\s*(.+)$/im)

          if (aiLessonMatch) {
            const lessonText = aiLessonMatch[1].trim()

            // Parse category: title - content
            let category = "pattern"
            let title = lessonText
            let content = lessonText

            const catMatch = lessonText.match(/^([a-z]+):\s*(.+)$/i)
            if (catMatch) {
              category = catMatch[1].toLowerCase()
              const rest = catMatch[2]
              const dashMatch = rest.match(/^(.+?)\s*-\s*(.+)$/)
              if (dashMatch) {
                title = dashMatch[1].trim()
                content = dashMatch[2].trim()
              } else {
                title = rest
                content = rest
              }
            } else {
              const dashMatch = lessonText.match(/^(.+?)\s*-\s*(.+)$/)
              if (dashMatch) {
                title = dashMatch[1].trim()
                content = dashMatch[2].trim()
              }
            }

            // Add the AI lesson (always as system level, sanitize inputs)
            const safeCategory = sanitizeForShell(category)
            const safeTitle = sanitizeForShell(title)
            const safeContent = sanitizeForShell(content)
            const result = await $`${MANAGER} add-ai ${safeCategory} ${safeTitle} ${safeContent} --system`
            log('info', 'lessons.ai_added', { category: safeCategory, title: safeTitle, result: result.stdout });
          }

          // Capture HANDOFF: patterns
          const handoffStartMatch = text.match(/^HANDOFF:\s*(.+)$/im)
          if (handoffStartMatch) {
            const title = handoffStartMatch[1].trim()
            // Extract description if present: "HANDOFF: title - description"
            let handoffTitle = title
            let description = ""
            const descMatch = title.match(/^(.+?)\s*-\s*(.+)$/)
            if (descMatch) {
              handoffTitle = descMatch[1].trim()
              description = descMatch[2].trim()
            }

            // Create handoff (sanitize user inputs)
            try {
              const safeTitle = sanitizeForShell(handoffTitle)
              const safeDesc = sanitizeForShell(description)
              const cmd = safeDesc
                ? $`${MANAGER} handoff add ${safeTitle} --desc ${safeDesc}`
                : $`${MANAGER} handoff add ${safeTitle}`
              const result = await cmd
              log('info', 'handoff.created', { title: safeTitle, result: result.stdout });
            } catch (e) {
              log('debug', 'handoff.create_failed', { error: String(e) });
            }
          }

          // Capture HANDOFF COMPLETE patterns
          const handoffCompleteMatch = text.match(/^HANDOFF COMPLETE\s+(.+)$/im)
          if (handoffCompleteMatch) {
            const handoffId = handoffCompleteMatch[1].trim()
            try {
              const result = await $`${MANAGER} handoff complete ${handoffId}`
              log('info', 'handoff.completed', { handoff_id: handoffId, result: result.stdout });
            } catch (e) {
              log('debug', 'handoff.complete_failed', { handoff_id: handoffId, error: String(e) });
            }
          }

          // Capture HANDOFF UPDATE patterns
          const handoffUpdateMatch = text.match(/^HANDOFF UPDATE\s+(.+?):\s*(.+)$/im)
          if (handoffUpdateMatch) {
            const handoffId = handoffUpdateMatch[1].trim()
            const updateText = handoffUpdateMatch[2].trim()

            // Parse tried attempts: "tried success|fail|partial - description"
            const triedMatch = updateText.match(/^tried\s+(success|fail|partial)\s*-\s*(.+)$/i)
            if (triedMatch) {
              const outcome = triedMatch[1].toLowerCase()
              const description = triedMatch[2].trim()
              try {
                // Sanitize user-provided description
                const safeDesc = sanitizeForShell(description)
                const result = await $`${MANAGER} handoff update ${handoffId} --tried ${outcome} ${safeDesc}`
                log('info', 'handoff.updated', { handoff_id: handoffId, outcome, result: result.stdout });
              } catch (e) {
                log('debug', 'handoff.update_failed', { handoff_id: handoffId, error: String(e) });
              }
            }
          }
        } catch (e) {
          log('debug', 'message.updated_failed', { error: String(e) });
        }
      }
    },

    // Pre-compact context injection - preserve critical context before session compaction
    "experimental.session.compacting": async (input) => {
      try {
        const sessionId = input.session.id
        const state = sessionState.get(sessionId)
        if (!state) return

        log('info', 'compaction.start', { session_id: sessionId });

        // Get active handoffs to determine what to inject
        const { stdout: handoffsOutput } = await $`${MANAGER} handoff inject`

        const contextParts: string[] = []

        // If there's an active handoff, inject handoff context + top lessons
        if (handoffsOutput && handoffsOutput.trim() && handoffsOutput.trim() !== "(no active handoffs)") {
          contextParts.push(`<handoffs-context>\n${handoffsOutput}\n</handoffs-context>`)

          // Inject top lessons by stars
          const { stdout: lessonsOutput } = await $`${MANAGER} inject ${CONFIG.topLessonsToShow}`
          if (lessonsOutput && lessonsOutput.trim() && lessonsOutput.trim() !== "(no lessons)") {
            contextParts.push(`<lessons-context>\n${lessonsOutput}\n</lessons-context>`)
          }

          log('debug', 'compaction.handoff_context', { parts: contextParts.length });
        } else {
          // No active handoff - inject top lessons + session summary
          const { stdout: lessonsOutput } = await $`${MANAGER} inject ${CONFIG.topLessonsToShow}`
          if (lessonsOutput && lessonsOutput.trim() && lessonsOutput.trim() !== "(no lessons)") {
            contextParts.push(`<lessons-context>\n${lessonsOutput}\n</lessons-context>`)
          }

          // Get session messages to create a summary
          const messages = await client.session.messages({
            path: { id: sessionId }
          })

          // Extract recent messages (last 10 user/assistant exchanges)
          const recentMessages = messages.slice(-20)

          // Create a session summary from recent context
          const summaryLines: string[] = ["## Recent Session Context"]

          for (const msg of recentMessages) {
            const role = msg.info.role
            const content = msg.parts
              .filter((p: any) => p.type === "text")
              .map((p: { type: string; text: string }) => p.text)
              .join(" ")
              .trim()
              .slice(0, 200) // Limit each message to 200 chars

            if (content) {
              summaryLines.push(`**${role}**: ${content}${content.length >= 200 ? "..." : ""}`)
            }
          }

          if (summaryLines.length > 1) {
            contextParts.push(summaryLines.join("\n"))
          }

          log('debug', 'compaction.summary_context', { parts: contextParts.length });
        }

        // Inject context with high priority (noReply) to ensure it survives compaction
        if (contextParts.length > 0) {
          await client.session.prompt({
            path: { id: sessionId },
            body: {
              noReply: true,
              parts: [{
                type: "text",
                text: contextParts.join("\n\n")
              }],
            },
          })
        }
      } catch (e) {
        log('debug', 'compaction.pre_failed', { error: String(e) });
      }
    },

    // Post-compact handoff update and session snapshot
    "session.compacted": async (input) => {
      try {
        const sessionId = input.session.id
        const state = sessionState.get(sessionId)
        if (!state) return

        log('info', 'compaction.end', { session_id: sessionId });

        // Track that compaction occurred
        state.compactionOccurred = true

        // Check for active handoffs
        const { stdout: handoffsOutput } = await $`${MANAGER} handoff list --active-only`
        const hasActiveHandoff = handoffsOutput &&
          handoffsOutput.trim() &&
          handoffsOutput.trim() !== "(no active handoffs)"

        if (hasActiveHandoff) {
          // Post-compact handoff update (Task 5.2)
          // Try to detect if work was completed or progress made
          const messages = await client.session.messages({
            path: { id: sessionId }
          })

          // Look at recent assistant messages for completion indicators
          const recentAssistantMessages = messages
            .filter(m => m.info.role === "assistant")
            .slice(-5) // Last 5 assistant messages

          let completed = false
          const completionIndicators = [
            "completed",
            "finished",
            "done",
            "implemented",
            "ready for review",
            "successfully",
            "all tests pass"
          ]

          for (const msg of recentAssistantMessages) {
            const content = msg.parts
              .filter((p: any) => p.type === "text")
              .map((p: { type: string; text: string }) => p.text)
              .join(" ")
              .toLowerCase()

            // Check for completion indicators (not in negative context)
            if (completionIndicators.some(indicator => content.includes(indicator))) {
              // Make sure it's not negated
              if (!content.includes("not completed") &&
                  !content.includes("not finished") &&
                  !content.includes("not done")) {
                completed = true
                break
              }
            }
          }

          // Get the active handoff ID (first one from list)
          const handoffMatch = handoffsOutput.match(/\[(hf-[a-f0-9]+|A\d{3})\]/)
          if (handoffMatch) {
            const handoffId = handoffMatch[1]

            // Update handoff status if work appears completed
            if (completed) {
              try {
                await $`${MANAGER} handoff update ${handoffId} --status completed`
                log('info', 'handoff.status_updated', { handoff_id: handoffId, status: 'completed' });
              } catch (e) {
                log('debug', 'handoff.status_update_failed', { handoff_id: handoffId, error: String(e) });
              }
            } else {
              // Update phase based on completion indicators (more conservative)
              let newPhase: string | null = null
              const recentContent = recentAssistantMessages
                .map(m => m.parts
                  .filter((p: any) => p.type === "text")
                  .map((p: { type: string; text: string }) => p.text)
                  .join(" ")
                  .toLowerCase())

              const content = recentContent.join(" ")

              if (content.includes("researching") || content.includes("investigating")) {
                newPhase = "research"
              } else if (content.includes("planning") || content.includes("design")) {
                newPhase = "planning"
              } else if (content.includes("implementing") || content.includes("coding") || content.includes("writing")) {
                newPhase = "implementing"
              } else if (content.includes("reviewing") || content.includes("testing") || content.includes("verifying")) {
                newPhase = "review"
              }

              if (newPhase) {
                try {
                  await $`${MANAGER} handoff update ${handoffId} --phase ${newPhase}`
                  log('info', 'handoff.phase_updated', { handoff_id: handoffId, phase: newPhase });
                } catch (e) {
                  log('debug', 'handoff.phase_update_failed', { handoff_id: handoffId, error: String(e) });
  }
}

export default LessonsPlugin;

            }
          }
        } else {
          // Session snapshot when no active handoff (Task 5.3)
          try {
            const messages = await client.session.messages({
              path: { id: sessionId }
            })

            // Create a session snapshot
            const snapshotLines: string[] = [
              `## Session Snapshot - ${new Date().toISOString()}`,
              `Session ID: ${sessionId}`,
              "",
              "### Recent Messages (last 10)"
            ]

            const recentMessages = messages.slice(-20)
            for (const msg of recentMessages) {
              const role = msg.info.role
              const content = msg.parts
                .filter((p: any) => p.type === "text")
                .map((p: { type: string; text: string }) => p.text)
                .join(" ")
                .trim()
                .slice(0, 300) // Limit to 300 chars per message

              if (content) {
                snapshotLines.push(`**${role}**: ${content}${content.length >= 300 ? "..." : ""}`)
              }
            }

            const snapshot = snapshotLines.join("\n")

            // Save snapshot to project directory (similar to inject-hook.sh pattern)
            const cwd = process.cwd()
            const fs = require('fs')
            const path = require('path')
            const snapshotPath = path.join(cwd, '.claude-recall', '.session-snapshot')

            // Ensure .claude-recall directory exists
            const snapshotDir = path.dirname(snapshotPath)
            if (!fs.existsSync(snapshotDir)) {
              fs.mkdirSync(snapshotDir, { recursive: true })
            }

            // Write snapshot
            fs.writeFileSync(snapshotPath, snapshot, 'utf8')

            log('info', 'snapshot.created', { path: snapshotPath, messages_count: recentMessages.length });
          } catch (e) {
            log('debug', 'snapshot.creation_failed', { error: String(e) });
          }
        }
      } catch (e) {
        log('debug', 'compaction.post_failed', { error: String(e) });
      }
    },
  }
}
