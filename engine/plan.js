'use strict';

const TRANSFORM_ORDER = ['rename', 'string_encode', 'operator_sub', 'dead_code', 'opaque_predicates'];

function validatePlan(plan) {
  if (!plan || typeof plan !== 'object' || Array.isArray(plan)) {
    throw new TypeError('Plan must be an object');
  }
  if (!Number.isInteger(plan.seed) || plan.seed < 0 || plan.seed > 0xffffffff) {
    throw new TypeError('plan.seed must be an unsigned 32-bit integer');
  }
  if (!plan.transforms || typeof plan.transforms !== 'object' || Array.isArray(plan.transforms)) {
    throw new TypeError('plan.transforms must be an object');
  }
  if (!Array.isArray(plan.order)) {
    throw new TypeError('plan.order must be an array');
  }

  const unknown = Object.keys(plan.transforms).filter((name) => !TRANSFORM_ORDER.includes(name));
  if (unknown.length > 0) {
    throw new Error(`Unknown transforms: ${unknown.join(', ')}`);
  }

  const enabled = TRANSFORM_ORDER.filter((name) => plan.transforms[name]?.enabled === true);
  if (new Set(plan.order).size !== plan.order.length) {
    throw new Error('plan.order contains duplicates');
  }
  if (plan.order.some((name) => !TRANSFORM_ORDER.includes(name))) {
    throw new Error('plan.order contains unknown transforms');
  }
  if (enabled.length !== plan.order.length || enabled.some((name) => !plan.order.includes(name))) {
    throw new Error('plan.order must contain every enabled transform exactly once');
  }

  let previous = -1;
  for (const name of plan.order) {
    const position = TRANSFORM_ORDER.indexOf(name);
    if (position <= previous) {
      throw new Error(`Invalid transform order: ${plan.order.join(' -> ')}`);
    }
    previous = position;
  }
  return plan;
}

module.exports = { TRANSFORM_ORDER, validatePlan };
