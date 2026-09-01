'use strict';

const traverse = require('@babel/traverse').default;
const t = require('@babel/types');

const SUPPORTED_METHODS = new Set(['charcode_array', 'charcode_concat', 'hex_escape', 'unicode_escape']);

function shouldSkip(path) {
  if (path.parentPath.isExpressionStatement() && path.parentPath.node.directive) return true;
  if (path.parentPath.isImportDeclaration() || path.parentPath.isExportNamedDeclaration() || path.parentPath.isExportAllDeclaration()) return true;
  if ((path.parentPath.isObjectProperty() || path.parentPath.isObjectMethod() || path.parentPath.isClassMethod()) && path.key === 'key' && !path.parent.computed) return true;
  return false;
}

function encodeCharcodeArray(str) {
  const codes = str.split('').map((ch) => t.numericLiteral(ch.charCodeAt(0)));
  return t.callExpression(
    t.memberExpression(t.identifier('String'), t.identifier('fromCharCode')),
    codes,
  );
}

function encodeCharcodeConcat(str) {
  const calls = str.split('').map((ch) =>
    t.callExpression(
      t.memberExpression(t.identifier('String'), t.identifier('fromCharCode')),
      [t.numericLiteral(ch.charCodeAt(0))],
    ),
  );
  return calls.reduce((acc, call) =>
    t.binaryExpression('+', acc, call),
  );
}

function encodeHexEscape(str) {
  const escaped = str.split('').map((ch) => {
    const code = ch.charCodeAt(0);
    return code <= 0xff
      ? `\\x${code.toString(16).padStart(2, '0')}`
      : `\\u${code.toString(16).padStart(4, '0')}`;
  }).join('');
  const literal = t.stringLiteral(str);
  literal.extra = { raw: `"${escaped}"`, rawValue: str };
  return literal;
}

function encodeUnicodeEscape(str) {
  const escaped = str.split('').map((ch) => {
    const code = ch.charCodeAt(0);
    return `\\u${code.toString(16).padStart(4, '0')}`;
  }).join('');
  const literal = t.stringLiteral(str);
  literal.extra = { raw: `"${escaped}"`, rawValue: str };
  return literal;
}

function stringEncode(ast, options = {}) {
  const minLength = Number.isInteger(options.min_length) ? options.min_length : 2;
  const method = options.method ?? 'charcode_array';
  if (!SUPPORTED_METHODS.has(method)) {
    throw new Error(`Unsupported string encoding method: ${method}`);
  }

  traverse(ast, {
    StringLiteral(path) {
      if (path.node.value.length < minLength || shouldSkip(path)) return;
      const value = path.node.value;
      let replacement;
      if (method === 'charcode_array') {
        replacement = encodeCharcodeArray(value);
      } else if (method === 'charcode_concat') {
        replacement = encodeCharcodeConcat(value);
      } else if (method === 'hex_escape') {
        replacement = encodeHexEscape(value);
        // hex_escape produces a StringLiteral — skip to avoid infinite loop
        path.replaceWith(replacement);
        path.skip();
        return;
      } else {
        replacement = encodeUnicodeEscape(value);
        path.replaceWith(replacement);
        path.skip();
        return;
      }
      path.replaceWith(replacement);
      path.skip();
    },
  });
}

module.exports = stringEncode;
