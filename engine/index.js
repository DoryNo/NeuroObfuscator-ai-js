#!/usr/bin/env node
'use strict';

const fs = require('node:fs');
const { applyPlan } = require('./apply_plan');
const { extractFunctions } = require('./extract_functions');
const { extractFeatures } = require('./extract_features');
const { validateEquivalent } = require('./test_runner');

function runRequest(request) {
  switch (request.operation) {
    case 'apply': return { code: applyPlan(request.code, request.plan) };
    case 'extract_functions': return { functions: extractFunctions(request.code, request.source) };
    case 'extract_features': return { features: extractFeatures(request.code) };
    case 'validate': return validateEquivalent(request.original_code, request.obfuscated_code, request.options);
    default: throw new Error(`Unknown operation: ${request.operation}`);
  }
}

function parseArgs(args) {
  const values = {};
  for (let index = 0; index < args.length; index += 2) values[args[index]] = args[index + 1];
  return values;
}

function main() {
  if (process.argv.includes('--json')) {
    const input = fs.readFileSync(0, 'utf8').trim();
    if (!input) return;
    const lines = input.split(/\r?\n/);
    const outputs = lines.map((line) => {
      try {
        return { ok: true, value: runRequest(JSON.parse(line)) };
      } catch (error) {
        return { ok: false, error: error.message };
      }
    });
    process.stdout.write(`${outputs.map((item) => JSON.stringify(item)).join('\n')}\n`);
    return;
  }

  const args = parseArgs(process.argv.slice(2));
  if (!args['--input'] || !args['--plan'] || !args['--output']) {
    throw new Error('Usage: node engine/index.js --input file.js --plan plan.json --output out.js');
  }
  const code = fs.readFileSync(args['--input'], 'utf8');
  const plan = JSON.parse(fs.readFileSync(args['--plan'], 'utf8'));
  fs.writeFileSync(args['--output'], `${applyPlan(code, plan)}\n`);
}

try {
  main();
} catch (error) {
  process.stderr.write(`${error.stack ?? error.message}\n`);
  process.exitCode = 1;
}
