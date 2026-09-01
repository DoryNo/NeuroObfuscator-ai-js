'use strict';

const traverse = require('@babel/traverse').default;
const t = require('@babel/types');

function deadCode(ast, options = {}, context) {
  const count = Math.max(0, Math.min(Number.isInteger(options.count) ? options.count : 1, 20));
  const targets = [];

  traverse(ast, {
    BlockStatement(path) {
      if (path.parentPath.isFunction() || path.parentPath.isProgram()) targets.push(path);
    },
  });

  if (targets.length === 0) return;
  for (let index = 0; index < count; index += 1) {
    const target = targets[Math.floor(context.random() * targets.length)];
    const identifier = target.scope.generateUidIdentifier('guard');
    const value = Math.floor(context.random() * 100000);
    const statement = t.ifStatement(
      t.booleanLiteral(false),
      t.blockStatement([
        t.variableDeclaration('const', [
          t.variableDeclarator(identifier, t.numericLiteral(value)),
        ]),
        t.expressionStatement(t.binaryExpression('*', identifier, t.numericLiteral(2))),
      ]),
    );
    target.pushContainer('body', statement);
  }
}

module.exports = deadCode;
