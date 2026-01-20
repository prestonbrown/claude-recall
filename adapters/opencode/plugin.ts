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
import { readFileSync, existsSync, appendFileSync, mkdirSync, writeFileSync } from 'fs';
import { join } from 'path';
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

function loadConfig(): Config {
  const opencodeConfig = join(homedir(), '.config', 'opencode', 'opencode.json');

  if (!existsSync(opencodeConfig)) {
    log('warn', 'config.not_found', { using_defaults: true });
    return DEFAULT_CONFIG;
  }

  try {
    const config = JSON.parse(readFileSync(opencodeConfig, 'utf8'));
    const claudeRecall = config.claudeRecall || {};

    const merged = { ...DEFAULT_CONFIG, ...claudeRecall };

    if (merged.debugLevel >= 2) {
      log('debug', 'config.loaded', merged);
    }

    return merged;
  } catch (e) {
    log('error', 'config.load_failed', { error: String(e) });
    return DEFAULT_CONFIG;
  }
}

const CONFIG = loadConfig();

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
  const debugLevel = CONFIG.debugLevel;

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
    const logDir = join(logPath, '..');

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

// Detect Python CLI: installed → legacy → dev
function findPythonManager(): string {
  const fs = require('fs');
  const path = require('path');

  const installed = path.join(os.homedir(), '.config', 'claude-recall', 'core', 'cli.py');
  const legacy = path.join(os.homedir(), '.config', 'claude-recall', 'cli.py');
  const dev = path.join(__dirname, '..', '..', 'core', 'cli.py');

  if (fs.existsSync(installed)) return installed;
  if (fs.existsSync(legacy)) return legacy;
  return dev;
}

const MANAGER = findPythonManager()

export const LessonsPlugin: Plugin = async ({ $, client }) => {
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
          log('debug', 'decay.failed', { error: String(e) });
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

    // Sync TodoWrite to handoff
    "tool.execute.after": async (input) => {
      try {
        // Only process TodoWrite tool calls
        if (input.tool !== "TodoWrite") return;

        // Extract todos from tool result
        const todos = input.result?.todos;

        if (!todos || !Array.isArray(todos)) return;

        // Convert todos to JSON for CLI
        const todosJson = JSON.stringify(todos);

        // Get session ID for cross-session pollution prevention
        const sessionId = input.session?.id;

        // Sync todos to active handoff
        try {
          const sessionIdArg = sessionId ? `--session-id ${sessionId}` : '';
          const { stdout } = await $`${MANAGER} handoff sync-todos ${todosJson} ${sessionIdArg}`
          if (stdout) {
            log('info', 'handoff.sync_todos', { result: stdout, sessionId });
          }
        } catch (e) {
          log('debug', 'handoff.sync_failed', { error: String(e) });
        }
      } catch (e) {
        log('debug', 'handoff.sync_error', { error: String(e) });
      }
    },

    // Smart injection on first prompt, periodic reminders
    "message.created": async (input) => {
      if (input.message.role !== "user") return;

      const state = sessionState.get(input.session.id);
      if (!state) return;

      // Extract user query for relevance scoring
      const userQuery = input.message.parts
        .filter((p: any) => p.type === "text")
        .map((p: { type: string; text: string }) => p.text)
        .join(" ")
        .trim();

      if (!userQuery) return;

      // Smart injection on first prompt
      if (state.isFirstPrompt) {
        try {
          log('debug', 'injection.smart_start', { query_length: userQuery.length });
          // Score lessons by relevance to user's query
          const { stdout } = await $`${MANAGER} score-relevance ${userQuery} --top ${CONFIG.relevanceTopN}`

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
          log('debug', 'injection.smart_failed', { error: String(e) });
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
      try {
        const sessionId = input.session.id

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

        // Cite each lesson
        for (const cite of allCitations) {
          const lessonId = cite.slice(1, -1) // Remove brackets
          await $`${MANAGER} cite ${lessonId}`
        }

        // Update checkpoint to current message count
        sessionCheckpoints.set(sessionId, messages.length)

        if (allCitations.size > 0) {
          log('info', 'lessons.cited', { citations: [...allCitations], count: allCitations.size });
        }
      } catch (e) {
        log('debug', 'session.idle_failed', { error: String(e) });
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

            // Add the lesson
            const cmd = isSystem ? "add-system" : "add"
            const result = await $`${MANAGER} ${cmd} ${category} ${title} ${content}`
            log('info', 'lessons.user_added', { category, title, is_system: isSystem, result: result.stdout });
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

            // Add the AI lesson (always as system level)
            const result = await $`${MANAGER} add-ai ${category} ${title} ${content} --system`
            log('info', 'lessons.ai_added', { category, title, result: result.stdout });
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

            // Create handoff
            try {
              const cmd = description
                ? $`${MANAGER} handoff add ${handoffTitle} --desc ${description}`
                : $`${MANAGER} handoff add ${handoffTitle}`
              const result = await cmd
              log('info', 'handoff.created', { title: handoffTitle, result: result.stdout });
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
                const result = await $`${MANAGER} handoff update ${handoffId} --tried ${outcome} ${description}`
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
