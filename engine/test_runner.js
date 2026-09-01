'use strict';

const vm = require('node:vm');

const ARGUMENT_SETS = [
  // scalars
  [], [0], [1], [-1], [2, 3], [0, 1], [5, 10], [-3, 7], [0, 0], [100, 1],
  [3, 5], [7, 7], [10, 0], [0, 10],
  // booleans
  [true], [false],
  // strings
  ['test'], ['hello'], ['gold', 10], ['silver', 50], ['bronze', 200],
  ['abc123'], ['aeiou'], ['no spaces'], ['add', 5, 3], ['multiply', 4, 7],
  ['hello', 'world'],
  // arrays - single
  [[1, 2, 3]], [[1, -2, 3, -4, 5]], [[-1, 0, 1]], [[10, 20, 30, 40, 50]],
  [[0]], [[100]], [[]], [[1, 2, 3, 4, 5, 6, 7, 8, 9, 10]],
  [[5, 3, 8, 1, 9, 2, 7, 4, 6]],
  // arrays - pairs
  [[1, 2, 3], [4, 5, 6]], [[1, 2], [2, 3]], [[-1, 2], [3, -4]],
  // nested arrays (matrix/dp)
  [[[1, 2], [3, 4], [5, 6]]], [[[1, 0], [0, 1]]],
  // objects - generic
  [{ value: 2 }], [{ a: 1, b: 2, c: 3 }], [{ x: 10, y: -5 }],
  // reducer-style objects
  [{ type: 'increment' }], [{ type: 'reset' }], [{ type: 'double' }],
  [{ type: 'negate' }],
  // edge cases
  [null], [undefined],
];

function execute(code, args, timeoutMs) {
  const context = vm.createContext({ __args: structuredClone(args) });
  const script = new vm.Script(`JSON.stringify((${code})(...__args))`);
  return script.runInContext(context, { timeout: timeoutMs });
}

function validateEquivalent(originalCode, obfuscatedCode, options = {}) {
  const timeoutMs = options.timeout_ms ?? 100;
  const minimumCases = options.minimum_cases ?? 2;
  const maxCases = options.max_cases ?? ARGUMENT_SETS.length;
  const argumentSets = options.argument_sets ?? ARGUMENT_SETS;
  const matches = [];

  for (const args of argumentSets) {
    let originalFirst;
    try {
      originalFirst = execute(originalCode, args, timeoutMs);
      const originalSecond = execute(originalCode, args, timeoutMs);
      if (originalFirst === undefined || originalFirst !== originalSecond) continue;
    } catch {
      continue;
    }

    try {
      const transformed = execute(obfuscatedCode, args, timeoutMs);
      if (originalFirst !== transformed) {
        return { tests_passed: false, cases_passed: matches.length, reason: 'output_mismatch', args };
      }
      matches.push(args);
      if (matches.length >= maxCases) break;
    } catch {
      return { tests_passed: false, cases_passed: matches.length, reason: 'transformed_execution_error', args };
    }
  }

  return {
    tests_passed: matches.length >= minimumCases,
    cases_passed: matches.length,
    reason: matches.length >= minimumCases ? null : 'insufficient_stable_cases',
  };
}

module.exports = { validateEquivalent };
