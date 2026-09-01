'use strict';

const traverse = require('@babel/traverse').default;
const { parseCode } = require('./apply_plan');

function extractFeatures(code) {
  const ast = parseCode(code);
  const features = {
    line_count: code.split(/\r?\n/).length,
    branch_count: 0,
    loop_count: 0,
    string_count: 0,
    operator_count: 0,
    function_count: 0,
    ast_depth: 0,
    cyclomatic_complexity: 1,
    // New features
    identifier_count: 0,
    param_count: 0,
    return_count: 0,
    literal_count: 0,
    array_count: 0,
    object_count: 0,
    call_count: 0,
    max_nesting: 0,
    try_catch_count: 0,
    template_literal_count: 0,
    has_destructuring: false,
    has_default_params: false,
    has_spread: false,
    has_closure: false,
  };

  let blockDepth = 0;
  const bindingNames = new Set();

  traverse(ast, {
    enter(path) {
      features.ast_depth = Math.max(features.ast_depth, path.getAncestry().length);
      if (path.isBlockStatement()) {
        blockDepth += 1;
        features.max_nesting = Math.max(features.max_nesting, blockDepth);
      }
    },
    exit(path) {
      if (path.isBlockStatement()) blockDepth -= 1;
    },
    Function(path) {
      features.function_count += 1;
      features.param_count += path.node.params ? path.node.params.length : 0;
      if (path.get('params').some(paramPath => {
        let found = false;
        paramPath.traverse({ AssignmentPattern() { found = true; } });
        return found || paramPath.node.type === 'AssignmentPattern';
      })) features.has_default_params = true;
      if (path.node.params?.some(param => param.type === 'RestElement')) features.has_spread = true;
      if (path.parentPath && !path.parentPath.isProgram()) features.has_closure = true;
    },
    IfStatement() { features.branch_count += 1; features.cyclomatic_complexity += 1; },
    ConditionalExpression() { features.branch_count += 1; features.cyclomatic_complexity += 1; },
    SwitchCase(path) {
      if (path.node.test) { features.branch_count += 1; features.cyclomatic_complexity += 1; }
    },
    ForStatement() { features.loop_count += 1; features.cyclomatic_complexity += 1; },
    ForInStatement() { features.loop_count += 1; features.cyclomatic_complexity += 1; },
    ForOfStatement() { features.loop_count += 1; features.cyclomatic_complexity += 1; },
    WhileStatement() { features.loop_count += 1; features.cyclomatic_complexity += 1; },
    DoWhileStatement() { features.loop_count += 1; features.cyclomatic_complexity += 1; },
    LogicalExpression(path) {
      features.operator_count += 1;
      if (path.node.operator === '&&' || path.node.operator === '||' || path.node.operator === '??') {
        features.cyclomatic_complexity += 1;
      }
    },
    BinaryExpression() { features.operator_count += 1; },
    UnaryExpression() { features.operator_count += 1; },
    UpdateExpression() { features.operator_count += 1; },
    StringLiteral() { features.string_count += 1; },
    Identifier(path) {
      if (path.isBindingIdentifier()) bindingNames.add(path.node.name);
    },
    ReturnStatement() { features.return_count += 1; },
    NumericLiteral() { features.literal_count += 1; },
    BooleanLiteral() { features.literal_count += 1; },
    NullLiteral() { features.literal_count += 1; },
    ArrayExpression() { features.array_count += 1; },
    ObjectExpression() { features.object_count += 1; },
    CallExpression() { features.call_count += 1; },
    TryStatement() { features.try_catch_count += 1; },
    TemplateLiteral() { features.template_literal_count += 1; },
    ObjectPattern() { features.has_destructuring = true; },
    ArrayPattern() { features.has_destructuring = true; },
    RestElement() { features.has_spread = true; },
    SpreadElement() { features.has_spread = true; },
  });
  features.identifier_count = bindingNames.size;
  return features;
}

module.exports = { extractFeatures };
