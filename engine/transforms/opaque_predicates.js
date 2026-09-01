'use strict';

const traverse = require('@babel/traverse').default;
const t = require('@babel/types');

// Inserts opaque predicates — conditions that always evaluate to true or false
// but appear complex.  They are injected as guard ifs that wrap existing
// BlockStatement bodies or prepended to them.
//
// Always-true  examples:  (x * 0 + 1 === 1), (x | 0) >= (x | 0) - 1
// Always-false examples:  (x * 0 !== 0), (x + 1 === x)

const TRUE_TEMPLATES = [
  (random) => {
    // (0 * x | 0) === 0   — always true for any x
    const x = t.numericLiteral(Math.floor(random() * 99) + 1);
    return t.binaryExpression(
      '===',
      t.binaryExpression('|', t.binaryExpression('*', t.numericLiteral(0), x), t.numericLiteral(0)),
      t.numericLiteral(0),
    );
  },
  (random) => {
    // 1 === 1
    const v = Math.floor(random() * 1000) + 1;
    return t.binaryExpression('===', t.numericLiteral(v), t.numericLiteral(v));
  },
  (random) => {
    // (n % 2 === 0 || n % 2 !== 0)  — always true, but n is a literal
    const n = Math.floor(random() * 100) + 2;
    const nLit = () => t.numericLiteral(n);
    return t.logicalExpression(
      '||',
      t.binaryExpression('===', t.binaryExpression('%', nLit(), t.numericLiteral(2)), t.numericLiteral(0)),
      t.binaryExpression('!==', t.binaryExpression('%', nLit(), t.numericLiteral(2)), t.numericLiteral(0)),
    );
  },
];

const FALSE_TEMPLATES = [
  () => {
    // 1 === 2
    return t.binaryExpression('===', t.numericLiteral(1), t.numericLiteral(2));
  },
  () => {
    // (0 !== 0)
    return t.binaryExpression('!==', t.numericLiteral(0), t.numericLiteral(0));
  },
];

function makeOpaquePredicate(context, alwaysTrue) {
  const templates = alwaysTrue ? TRUE_TEMPLATES : FALSE_TEMPLATES;
  const idx = Math.floor(context.random() * templates.length);
  return templates[idx](context.random);
}

function opaquePredicates(ast, options = {}, context) {
  const count = Math.max(0, Math.min(Number.isInteger(options.count) ? options.count : 2, 10));
  const targets = [];

  traverse(ast, {
    BlockStatement(path) {
      if (path.parentPath.isFunction() || path.parentPath.isIfStatement() ||
          path.parentPath.isForStatement() || path.parentPath.isWhileStatement()) {
        targets.push(path);
      }
    },
  });

  if (targets.length === 0) return;

  for (let i = 0; i < count; i++) {
    const target = targets[Math.floor(context.random() * targets.length)];
    const alwaysTrue = context.random() < 0.6;
    const predicate = makeOpaquePredicate(context, alwaysTrue);

    // dead branch body: just a numeric expression statement
    const deadValue = Math.floor(context.random() * 99999);
    const deadBody = t.blockStatement([
      t.expressionStatement(t.numericLiteral(deadValue)),
    ]);

    if (alwaysTrue) {
      // if (always_true) { original_block } else { dead }
      // We prepend: if (predicate) { noop } — simpler: wrap a statement
      const stmt = t.ifStatement(predicate, t.blockStatement([
        t.expressionStatement(t.numericLiteral(deadValue)),
      ]), deadBody);
      target.pushContainer('body', stmt);
    } else {
      // if (always_false) { dead }
      const stmt = t.ifStatement(predicate, deadBody);
      target.pushContainer('body', stmt);
    }
  }
}

module.exports = opaquePredicates;
