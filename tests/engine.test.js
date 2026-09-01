'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { applyPlan } = require('../engine/apply_plan');
const { extractFeatures } = require('../engine/extract_features');
const { extractFunctions } = require('../engine/extract_functions');
const { validateEquivalent } = require('../engine/test_runner');

const code = `function calculate(price, tier) {
  const discount = tier === "gold" ? 0.8 : 1;
  return price * discount;
}`;

const plan = {
  seed: 42,
  transforms: {
    rename: { enabled: true, keep: ['calculate'] },
    string_encode: { enabled: true, method: 'charcode_array', min_length: 2 },
    dead_code: { enabled: true, count: 2 },
  },
  order: ['rename', 'string_encode', 'dead_code'],
};

test('applies a deterministic plan and preserves behavior', () => {
  const first = applyPlan(code, plan);
  const second = applyPlan(code, plan);
  assert.equal(first, second);
  assert.match(first, /_0x/);
  assert.match(first, /String\.fromCharCode/);
  assert.match(first, /if \(false\)/);
  assert.deepEqual(validateEquivalent(code, first), {
    tests_passed: true,
    cases_passed: 50,
    reason: null,
  });
});

test('operator_sub preserves behavior for non-numeric left operands', () => {
  const input = `function checkout(price) {
  const total = price - 5;
  return Math.round(total * 100) / 100;
}`;
  const output = applyPlan(input, {
    seed: 7,
    transforms: { operator_sub: { enabled: true, rate: 1 } },
    order: ['operator_sub'],
  });
  const result = validateEquivalent(input, output);
  assert.equal(result.tests_passed, true);
  assert.equal(result.reason, null);
});

test('rejects invalid transform order', () => {
  assert.throws(
    () => applyPlan(code, { ...plan, order: ['dead_code', 'rename', 'string_encode'] }),
    /Invalid transform order/,
  );
});

test('does not encode directives, property keys, or import sources', () => {
  const input = `'use strict'; import thing from "module-name";
function read(object) { return object["value"] + object.label + "suffix"; }`;
  const output = applyPlan(input, {
    seed: 1,
    transforms: { string_encode: { enabled: true, method: 'charcode_array', min_length: 1 } },
    order: ['string_encode'],
  });
  assert.match(output, /['"]use strict['"]/);
  assert.match(output, /from ['"]module-name['"]/);
  assert.match(output, /String\.fromCharCode\(118, 97, 108, 117, 101\)/);
  assert.match(output, /\.label/);
});

test('preserves UTF-16 surrogate pairs while encoding strings', () => {
  const input = `function emoji() { return "A😀B"; }`;
  const output = applyPlan(input, {
    seed: 1,
    transforms: { string_encode: { enabled: true, method: 'charcode_array', min_length: 1 } },
    order: ['string_encode'],
  });
  assert.match(output, /String\.fromCharCode\(65, 55357, 56832, 66\)/);
  assert.equal(validateEquivalent(input, output, { argument_sets: [[]], minimum_cases: 1 }).tests_passed, true);
});

test('escape string methods preserve runtime values', () => {
  for (const method of ['hex_escape', 'unicode_escape']) {
    const input = `function text() { return "Aé😀B"; }`;
    const output = applyPlan(input, {
      seed: 1,
      transforms: { string_encode: { enabled: true, method, min_length: 1 } },
      order: ['string_encode'],
    });
    assert.equal(validateEquivalent(input, output, { argument_sets: [[]], minimum_cases: 1 }).tests_passed, true);
    assert.match(output, method === 'hex_escape' ? /\\x41/ : /\\u0041/);
  }
});

test('opaque predicates are deterministic for a seed', () => {
  const opaquePlan = {
    seed: 123,
    transforms: { opaque_predicates: { enabled: true, count: 3 } },
    order: ['opaque_predicates'],
  };
  assert.equal(applyPlan(code, opaquePlan), applyPlan(code, opaquePlan));
});

test('fails validation when transformed code throws for a supported input', () => {
  const result = validateEquivalent(
    'function stable(value) { return value; }',
    'function broken(value) { throw new Error("broken"); }',
    { argument_sets: [[1]], minimum_cases: 1 },
  );
  assert.equal(result.tests_passed, false);
  assert.equal(result.reason, 'transformed_execution_error');
});

test('extracts top-level named synchronous functions', () => {
  const functions = extractFunctions(`${code}\nconst hidden = () => 1;`, 'fixture.js');
  assert.equal(functions.length, 1);
  assert.equal(functions[0].name, 'calculate');
  assert.equal(functions[0].source, 'fixture.js');
  assert.equal(functions[0].construct_type, 'function_decl');
});

test('extracts standalone class methods without receiver dependencies', () => {
  const functions = extractFunctions(`class Calculator {
    add(left, right) { return left + right; }
    format(value) { return String(value); }
    getValue() { return this.value; }
    constructor(value) { this.value = value; }
  }`, 'class.js');
  assert.deepEqual(functions.map(fn => fn.name), ['add', 'format']);
  assert.equal(functions[0].construct_type, 'class_method');
  assert.match(functions[0].code, /^function add\(/);
});

test('extracts structural features', () => {
  const features = extractFeatures(`function f(items) { for (const item of items) { if (item && item.ok) return "yes"; } return "no"; }`);
  assert.equal(features.loop_count, 1);
  assert.equal(features.branch_count, 1);
  assert.equal(features.string_count, 2);
  assert.equal(features.cyclomatic_complexity, 4);
  assert.ok(features.ast_depth > 3);
  assert.equal(features.identifier_count, 3);
  assert.equal(features.param_count, 1);
  assert.equal(features.return_count, 2);
});

test('extracts modern syntax feature flags', () => {
  const features = extractFeatures(`function f({ value = 1 }, ...rest) {
    const [first] = rest;
    return () => value + first;
  }`);
  assert.equal(features.has_destructuring, true);
  assert.equal(features.has_default_params, true);
  assert.equal(features.has_spread, true);
  assert.equal(features.has_closure, true);
});

test('applies plans to modern synchronous syntax', () => {
  const cases = [
    {
      code: `function readValue(input) {
        const { value = 2 } = input || {};
        const [first = 0] = input?.items || [];
        return value + first;
      }`,
      args: [{ value: 3, items: [4] }],
    },
    {
      code: `function closureTotal(value) {
        let total = value || 0;
        const add = (part) => { total += part; return total; };
        add(1);
        return add(2);
      }`,
      args: [5],
    },
    {
      code: `function pipeline(values) {
        return (values || []).filter(value => value > 1).map(value => value * 2).reduce((sum, value) => sum + value, 0);
      }`,
      args: [[1, 2, 3]],
    },
    {
      code: `function defaults(left = 2, right = 3, ...rest) {
        return left * right + rest.reduce((sum, value) => sum + value, 0);
      }`,
      args: [4, 5, 6],
    },
  ];
  const modernPlan = {
    seed: 77,
    transforms: {
      rename: { enabled: true },
      string_encode: { enabled: false },
      operator_sub: { enabled: true, rate: 0.5 },
      dead_code: { enabled: true, count: 1 },
    },
    order: ['rename', 'operator_sub', 'dead_code'],
  };
  for (const { code: input, args } of cases) {
    const output = applyPlan(input, modernPlan);
    const result = validateEquivalent(input, output, {
      argument_sets: [args],
      minimum_cases: 1,
    });
    assert.equal(result.tests_passed, true, result.reason || 'modern syntax validation failed');
  }
});
