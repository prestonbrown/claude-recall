// SPDX-License-Identifier: MIT
// Minimal test shim: replaces `bun:test` with node:test + node:assert so the
// suite runs on a stock Node install (no 89MB runtime download).
import assert from "node:assert/strict";
import {
  after,
  afterEach,
  before,
  beforeEach,
  describe,
  it,
} from "node:test";

export { describe, beforeEach, afterEach };
export const test = it;
export const beforeAll = before;
export const afterAll = after;

export function expect(actual: unknown) {
  return {
    toBe(expected: unknown) {
      assert.strictEqual(actual, expected);
    },
    toEqual(expected: unknown) {
      assert.deepStrictEqual(actual, expected);
    },
    toContain(expected: string) {
      const text = String(actual);
      assert.ok(
        text.includes(expected),
        `expected output to contain ${JSON.stringify(expected)}`,
      );
    },
    toBeNull() {
      assert.strictEqual(actual, null);
    },
    toBeTruthy() {
      assert.ok(actual);
    },
    toBeGreaterThan(expected: number) {
      assert.ok((actual as number) > expected, `expected ${actual} > ${expected}`);
    },
    toBeGreaterThanOrEqual(expected: number) {
      assert.ok((actual as number) >= expected, `expected ${actual} >= ${expected}`);
    },
    toBeLessThan(expected: number) {
      assert.ok((actual as number) < expected, `expected ${actual} < ${expected}`);
    },
    toBeLessThanOrEqual(expected: number) {
      assert.ok((actual as number) <= expected, `expected ${actual} <= ${expected}`);
    },
    toMatch(pattern: RegExp) {
      assert.match(String(actual), pattern);
    },
    not: {
      toBe(expected: unknown) {
        assert.notStrictEqual(actual, expected);
      },
      toBeNull() {
        assert.notStrictEqual(actual, null);
      },
      toContain(expected: string) {
        const text = String(actual);
        assert.ok(
          !text.includes(expected),
          `expected output NOT to contain ${JSON.stringify(expected)}`,
        );
      },
      toMatch(pattern: RegExp) {
        assert.doesNotMatch(String(actual), pattern);
      },
    },
  };
}
