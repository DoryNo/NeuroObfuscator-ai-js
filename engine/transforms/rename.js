'use strict';

const traverse = require('@babel/traverse').default;

function rename(ast, options = {}, context) {
  const keep = new Set(options.keep ?? []);
  const renamed = new Set();
  let sequence = 0;

  traverse(ast, {
    Scope(path) {
      if (path.isProgram()) return;

      for (const name of Object.keys(path.scope.bindings).sort()) {
        const binding = path.scope.bindings[name];
        if (renamed.has(binding) || keep.has(name)) continue;
        if (binding.scope.path.isProgram()) continue;

        let nextName;
        do {
          const randomPart = Math.floor(context.random() * 0xffffff).toString(16).padStart(6, '0');
          nextName = `_0x${randomPart}${(sequence++).toString(16)}`;
        } while (path.scope.hasBinding(nextName) || path.scope.hasGlobal(nextName));

        binding.scope.rename(name, nextName);
        renamed.add(binding);
      }
    },
  });
}

module.exports = rename;
