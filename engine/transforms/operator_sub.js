'use strict';

const traverse = require('@babel/traverse').default;
const t = require('@babel/types');

// Supported substitutions (semantics-preserving under JS type coercion):
//  a - b   -> +a + (-b)   ('-' coerces numerically; a bare '+' would concatenate
//                          for non-number left operands, e.g. [100] + -5 -> "100-5")
//  a + b   -> a - (-b)    (only when both operands are numeric literals)
//  a * 2   -> +a + +a     (only when right is literal 2; "5"*2=10 but "5"+"5"="55")
//  a === b -> !(a !== b)
//  a !== b -> !(a === b)

function wrapNeg(node) {
  return t.unaryExpression('-', node, true);
}

function operatorSub(ast, options = {}, context) {
  const rate = typeof options.rate === 'number' ? Math.min(1, Math.max(0, options.rate)) : 0.7;

  traverse(ast, {
    BinaryExpression: {
      exit(path) {
        if (context.random() > rate) return;
        const { operator, left, right } = path.node;

        if (operator === '-') {
          // '-' applies ToNumber to both operands, so a bare '+' rewrite would
          // concatenate for non-number left operands. Coerce the left side to
          // keep the rewrite equivalent.
          const coercedLeft = t.isNumericLiteral(left)
            ? left
            : t.unaryExpression('+', left);
          path.replaceWith(t.binaryExpression('+', coercedLeft, wrapNeg(right)));
          path.skip();
        } else if (operator === '+' && t.isNumericLiteral(left) && t.isNumericLiteral(right)) {
          path.replaceWith(t.binaryExpression('-', left, wrapNeg(right)));
          path.skip();
        } else if (operator === '*' && t.isNumericLiteral(right) && right.value === 2) {
          if (t.isIdentifier(left) || t.isNumericLiteral(left)) {
            path.replaceWith(t.binaryExpression(
              '+',
              t.unaryExpression('+', t.cloneNode(left)),
              t.unaryExpression('+', t.cloneNode(left)),
            ));
            path.skip();
          }
        } else if (operator === '===') {
          path.replaceWith(t.unaryExpression('!', t.binaryExpression('!==', left, right)));
          path.skip();
        } else if (operator === '!==') {
          path.replaceWith(t.unaryExpression('!', t.binaryExpression('===', left, right)));
          path.skip();
        }
      },
    },
  });
}

module.exports = operatorSub;