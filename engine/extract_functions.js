'use strict';

const traverse = require('@babel/traverse').default;
const generate = require('@babel/generator').default;
const t = require('@babel/types');
const { parseCode } = require('./apply_plan');

function extractFunctions(code, source = '<input>') {
  const ast = parseCode(code);
  const functions = [];
  const seen = new Set();

  function hasReceiverDependency(path) {
    let dependsOnReceiver = false;
    path.get('body').traverse({
      ThisExpression() { dependsOnReceiver = true; },
      Super() { dependsOnReceiver = true; },
    });
    return dependsOnReceiver;
  }

  function add(name, node, path, constructType = 'function_decl', normalizedNode = node) {
    if (!name || !node.body) return;
    if (node.async || node.generator) return;
    const generated = generate(normalizedNode, { comments: false }).code;
    // Normalize: wrap arrow expression bodies for consistency
    const normalized = generated.startsWith('function') ? generated : `function ${name}${generated.slice(generated.indexOf('('))}`;
    const key = `${name}:${node.loc?.start.line ?? 0}`;
    if (seen.has(key)) return;
    seen.add(key);
    functions.push({
      name,
      code: generated,
      source,
      construct_type: constructType,
      line_start: node.loc?.start.line ?? null,
      line_end: node.loc?.end.line ?? null,
      arity: node.params.length,
    });
  }

  traverse(ast, {
    // Standard: function foo() {}
    FunctionDeclaration(path) {
      if (!path.node.id || path.node.async || path.node.generator) return;
      // Accept top-level or one level inside module wrapper
      if (!path.parentPath.isProgram() && !path.parentPath.isExportNamedDeclaration() && !path.parentPath.isExportDefaultDeclaration()) return;
      add(path.node.id.name, path.node, path, 'function_decl');
    },
    // const fn = function() {} or const fn = () => {}
    VariableDeclarator(path) {
      if (!path.parentPath.parentPath?.isProgram() && !path.parentPath.parentPath?.isExportNamedDeclaration()) return;
      const id = path.node.id;
      const init = path.node.init;
      if (!id || id.type !== 'Identifier' || !init) return;
      if (init.type === 'FunctionExpression' || init.type === 'ArrowFunctionExpression') {
        if (init.async || init.generator) return;
        // Only extract if body is a BlockStatement (not expression shorthand)
        if (init.type === 'ArrowFunctionExpression' && init.body.type !== 'BlockStatement') return;
         add(id.name, init, path, init.type === 'ArrowFunctionExpression' ? 'arrow' : 'function_expr');
      }
    },
    // module.exports = function name() {} or exports.name = function() {}
    AssignmentExpression(path) {
      if (!path.parentPath.isExpressionStatement()) return;
      const left = path.node.left;
      const right = path.node.right;
      if (!right || (right.type !== 'FunctionExpression' && right.type !== 'ArrowFunctionExpression')) return;
      if (right.async || right.generator) return;
      if (right.type === 'ArrowFunctionExpression' && right.body.type !== 'BlockStatement') return;
      let name = null;
      if (right.id) {
        name = right.id.name;
      } else if (left.type === 'MemberExpression' && left.property.type === 'Identifier') {
        // exports.foo = function() {} -> name = foo
        name = left.property.name;
        if (name === 'exports') name = null; // module.exports = ... without named id
      }
      if (name) {
         add(name, right, path, right.type === 'ArrowFunctionExpression' ? 'arrow' : 'function_expr');
      }
    },
    ClassMethod(path) {
      const node = path.node;
      if (node.kind === 'constructor' || node.async || node.generator || hasReceiverDependency(path)) return;
      if (node.computed || node.key.type !== 'Identifier') return;
      const name = node.key.name;
      const functionNode = t.functionDeclaration(
        t.identifier(name),
        node.params,
        node.body,
        false,
        false,
      );
      add(name, node, path, 'class_method', functionNode);
    },
  });
  return functions;
}

module.exports = { extractFunctions };
