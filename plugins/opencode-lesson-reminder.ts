// SPDX-License-Identifier: MIT
// opencode-lesson-reminder.ts - Periodic lesson reminders for OpenCode
//
// Install: Copy to ~/.config/opencode/plugins/ and add to opencode.json
// Config in opencode.json:
//   "plugins": { "lesson-reminder": { "enabled": true } }

import { readFileSync, writeFileSync, existsSync, unlinkSync } from 'fs';
import { homedir } from 'os';
import { join } from 'path';

const LESSONS_BASE = join(homedir(), '.config', 'coding-agent-lessons');
const STATE_FILE = join(LESSONS_BASE, '.reminder-state');
const REMIND_EVERY = parseInt(process.env.LESSON_REMIND_EVERY || '12', 10);

interface PluginContext {
  // Add context fields as needed
}

function getCount(): number {
  try {
    if (existsSync(STATE_FILE)) {
      return parseInt(readFileSync(STATE_FILE, 'utf8').trim(), 10) || 0;
    }
  } catch {
    // Ignore errors
  }
  return 0;
}

function setCount(count: number): void {
  try {
    writeFileSync(STATE_FILE, count.toString());
  } catch {
    // Ignore errors
  }
}

function resetCount(): void {
  try {
    if (existsSync(STATE_FILE)) {
      unlinkSync(STATE_FILE);
    }
  } catch {
    // Ignore errors
  }
}

function findLessonsFile(): string | null {
  // Check project first, then system
  const projectRoot = process.cwd();
  const projectLessons = join(projectRoot, '.coding-agent-lessons', 'LESSONS.md');
  const systemLessons = join(LESSONS_BASE, 'LESSONS.md');

  if (existsSync(projectLessons)) return projectLessons;
  if (existsSync(systemLessons)) return systemLessons;
  return null;
}

function getHighStarLessons(filePath: string): string[] {
  try {
    const content = readFileSync(filePath, 'utf8');
    const lines = content.split('\n');

    // Match lines like: ### [L014] [*****/+----] Register all XML components
    const pattern = /^###\s*\[[LS]\d+\].*\[\*{3,}/;

    return lines
      .filter(line => pattern.test(line))
      .slice(0, 3);
  } catch {
    return [];
  }
}

export default {
  name: 'lesson-reminder',
  version: '1.0.0',

  // Reset counter on session start
  activate: async (_context: PluginContext) => {
    resetCount();
  },

  // Track prompts via tool execution events
  tool: {
    execute: {
      before: async () => {
        const count = getCount() + 1;
        setCount(count);

        // Only remind every Nth prompt
        if (count % REMIND_EVERY !== 0) {
          return;
        }

        const lessonsFile = findLessonsFile();
        if (!lessonsFile) return;

        const highStarLessons = getHighStarLessons(lessonsFile);
        if (highStarLessons.length === 0) return;

        // Output reminder (will be captured in session context)
        console.log('\n📚 LESSON CHECK - High-priority lessons to keep in mind:');
        highStarLessons.forEach(lesson => console.log(lesson));
        console.log('');
      }
    }
  }
};
