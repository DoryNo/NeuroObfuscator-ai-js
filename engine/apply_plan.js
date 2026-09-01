'use strict';

const parser = require('@babel/parser');
const generate = require('@babel/generator').default;
const { createRandom } = require('./random');
const { validatePlan } = require('./plan');

const transforms = {
  rename: require('./transforms/rename'),
  string_encode: require('./transforms/string_encode'),
  operator_sub: require('./transforms/operator_sub'),
  dead_code: require('./transforms/dead_code'),
  opaque_predicates: require('./transforms/opaque_predicates'),
};

function parseCode(code) {
  return parser.parse(code, {
    sourceType: 'unambiguous',
    allowReturnOutsideFunction: false,
  });
}

function applyPlan(code, plan) {
  if (typeof code !== 'string') throw new TypeError('code must be a string');
  validatePlan(plan);
  const ast = parseCode(code);
  const context = { random: createRandom(plan.seed) };

  for (const name of plan.order) {
    transforms[name](ast, plan.transforms[name], context);
  }

  return generate(ast, { comments: false, compact: false }).code;
}

module.exports = { applyPlan, parseCode };
