from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path

ADJECTIVES = [
    "alpha", "beta", "gamma", "delta", "epsilon", "zeta", "theta", "kappa",
    "lambda", "sigma", "omega", "prime", "super", "hyper", "micro", "macro",
    "ultra", "mega", "nano", "crypto", "matrix", "vector", "quantum", "delta",
]
NOUNS = [
    "sum", "count", "merge", "split", "filter", "reduce", "transform", "parse",
    "encode", "decode", "rotate", "shift", "swap", "reverse", "group", "flatten",
    "compress", "expand", "normalize", "aggregate", "compute", "resolve", "build",
    "scan", "collect", "verify", "estimate", "project", "dispatch", "compose",
]

BUILTIN_OK = True  # generated code only uses Math/JSON/Array/Object/Number/String


def make_name(rng: random.Random, used: set[str]) -> str:
    while True:
        name = rng.choice(ADJECTIVES) + rng.choice(NOUNS) + str(rng.randint(0, 9999))
        if name not in used:
            used.add(name)
            return name


def indent(code: str, level: int) -> str:
    pad = "  " * level
    return "\n".join(pad + line if line else line for line in code.split("\n"))


def gen_array_loop(rng: random.Random, p: list[str]) -> str:
    op = rng.choice(["sum", "product", "max", "count"])
    cond = rng.choice(["x > 0", "x % 2 === 0", "x < 0", "x !== 0"])
    if op == "sum":
        acc = "0"
        step = "total += arr[i];"
    elif op == "product":
        acc = "1"
        step = "total *= arr[i];"
    elif op == "max":
        acc = "arr[0]"
        step = "if (arr[i] > total) total = arr[i];"
    else:
        acc = "0"
        step = f"if ({cond}) total += 1;"
    return (
        f"function {p[0]}({p[1]}) {{\n"
        f"  let total = {acc};\n"
        f"  for (let i = 0; i < {p[1]}.length; i++) {{\n"
        f"    const x = {p[1]}[i];\n"
        f"    {step}\n"
        f"  }}\n"
        f"  return total;\n"
        f"}}"
    )


def gen_string_process(rng: random.Random, p: list[str]) -> str:
    mode = rng.choice(["vowels", "digits", "repeat", "reverse"])
    if mode == "vowels":
        body = (
            "let result = '';\n"
            "const vowels = 'aeiou';\n"
            "for (let i = 0; i < str.length; i++) {\n"
            "  if (vowels.indexOf(str[i]) !== -1) result += str[i];\n"
            "}\n"
            "return result;"
        )
    elif mode == "digits":
        body = (
            "let count = 0;\n"
            "for (let i = 0; i < str.length; i++) {\n"
            "  if (str[i] >= '0' && str[i] <= '9') count += 1;\n"
            "}\n"
            "return count;"
        )
    elif mode == "repeat":
        body = (
            "let out = '';\n"
            "for (let i = 0; i < str.length; i++) {\n"
            "  for (let j = 0; j < 2; j++) out += str[i];\n"
            "}\n"
            "return out;"
        )
    else:
        body = (
            "let out = '';\n"
            "for (let i = str.length - 1; i >= 0; i--) out += str[i];\n"
            "return out;"
        )
    return f"function {p[0]}({p[1]}) {{\n  {indent(body, 1)}\n}}"


def gen_math_branch(rng: random.Random, p: list[str]) -> str:
    a, b, c = rng.randint(1, 9), rng.randint(1, 9), rng.randint(1, 9)
    return (
        f"function {p[0]}({p[1]}, {p[2]}) {{\n"
        f"  if ({p[1]} < 0) return 0;\n"
        f"  if ({p[1]} > {p[2]}) return {p[1]} - {p[2]};\n"
        f"  let r = {p[1]} * {a};\n"
        f"  if (r % {b} === 0) r = r + {c};\n"
        f"  return r;\n"
        f"}}"
    )


def gen_nested_loop(rng: random.Random, p: list[str]) -> str:
    return (
        f"function {p[0]}({p[1]}) {{\n"
        f"  let found = 0;\n"
        f"  for (let i = 0; i < {p[1]}.length; i++) {{\n"
        f"    for (let j = i + 1; j < {p[1]}.length; j++) {{\n"
        f"      if ({p[1]}[i] + {p[1]}[j] === 0) found += 1;\n"
        f"    }}\n"
        f"  }}\n"
        f"  return found;\n"
        f"}}"
    )


def gen_recursion(rng: random.Random, p: list[str]) -> str:
    variant = rng.choice(["pow", "sumto", "digitsum"])
    if variant == "pow":
        return (
            f"function {p[0]}({p[1]}, {p[2]}) {{\n"
            f"  if ({p[2]} === 0) return 1;\n"
            f"  return {p[1]} * {p[0]}({p[1]}, {p[2]} - 1);\n"
            f"}}"
        )
    if variant == "sumto":
        return (
            f"function {p[0]}({p[1]}) {{\n"
            f"  if ({p[1]} <= 0) return 0;\n"
            f"  return {p[1]} + {p[0]}({p[1]} - 1);\n"
            f"}}"
        )
    return (
        f"function {p[0]}({p[1]}) {{\n"
        f"  if ({p[1]} < 10) return {p[1]};\n"
        f"  return ({p[1]} % 10) + {p[0]}(Math.floor({p[1]} / 10));\n"
        f"}}"
    )


def gen_filter_map(rng: random.Random, p: list[str]) -> str:
    threshold = rng.randint(1, 50)
    return (
        f"function {p[0]}({p[1]}) {{\n"
        f"  const out = [];\n"
        f"  for (let i = 0; i < {p[1]}.length; i++) {{\n"
        f"    const v = {p[1]}[i];\n"
        f"    if (v >= {threshold}) out.push(v * 2);\n"
        f"  }}\n"
        f"  return out;\n"
        f"}}"
    )


def gen_bitwise(rng: random.Random, p: list[str]) -> str:
    k = rng.randint(1, 7)
    return (
        f"function {p[0]}({p[1]}) {{\n"
        f"  let r = {p[1]};\n"
        f"  if (r < 0) r = -r;\n"
        f"  for (let i = 0; i < 8; i++) {{\n"
        f"    if ((r & (1 << i)) !== 0) r = r ^ (1 << {k});\n"
        f"  }}\n"
        f"  return r;\n"
        f"}}"
    )


def gen_object_scan(rng: random.Random, p: list[str]) -> str:
    return (
        f"function {p[0]}({p[1]}) {{\n"
        f"  const keys = Object.keys({p[1]});\n"
        f"  let maxKey = keys[0];\n"
        f"  for (let i = 1; i < keys.length; i++) {{\n"
        f"    if ({p[1]}[keys[i]] > {p[1]}[maxKey]) maxKey = keys[i];\n"
        f"  }}\n"
        f"  return maxKey;\n"
        f"}}"
    )


def gen_nested_if(rng: random.Random, p: list[str]) -> str:
    """Multi-branch if/else with strings."""
    tiers = rng.sample(["gold", "silver", "bronze", "platinum", "diamond", "basic"], k=rng.randint(3, 5))
    discounts = [rng.randint(5, 50) for _ in tiers]
    branches = ""
    for i, (tier, disc) in enumerate(zip(tiers, discounts)):
        kw = "if" if i == 0 else "} else if"
        branches += f'  {kw} ({p[1]} === "{tier}") {{\n    return {p[2]} * {100 - disc} / 100;\n'
    branches += "  } else {\n    return " + p[2] + ";\n  }"
    return f"function {p[0]}({p[1]}, {p[2]}) {{\n{branches}\n}}"


def gen_switch_case(rng: random.Random, p: list[str]) -> str:
    """Switch statement with string cases."""
    actions = rng.sample(["add", "subtract", "multiply", "divide", "modulo", "power", "negate", "abs"], k=rng.randint(4, 6))
    cases = ""
    for action in actions:
        if action == "add":
            body = f"return {p[1]} + {p[2]};"
        elif action == "subtract":
            body = f"return {p[1]} - {p[2]};"
        elif action == "multiply":
            body = f"return {p[1]} * {p[2]};"
        elif action == "divide":
            body = f"if ({p[2]} === 0) return 0;\n      return {p[1]} / {p[2]};"
        elif action == "modulo":
            body = f"if ({p[2]} === 0) return 0;\n      return {p[1]} % {p[2]};"
        elif action == "power":
            body = f"return Math.pow({p[1]}, {p[2]});"
        elif action == "negate":
            body = f"return -{p[1]};"
        else:
            body = f"return Math.abs({p[1]});"
        cases += f'    case "{action}":\n      {body}\n'
    return (
        f"function {p[0]}({p[3]}, {p[1]}, {p[2]}) {{\n"
        f"  switch ({p[3]}) {{\n"
        f"{cases}"
        f"    default:\n      return 0;\n"
        f"  }}\n"
        f"}}"
    )


def gen_state_machine(rng: random.Random, p: list[str]) -> str:
    """While loop with state transitions — complex control flow."""
    states = rng.randint(3, 6)
    lines = [
        f"function {p[0]}({p[1]}) {{",
        f"  let state = 0;",
        f"  let result = 0;",
        f"  let steps = 0;",
        f"  while (state !== {states} && steps < 100) {{",
        f"    steps += 1;",
    ]
    for i in range(states):
        cond = rng.choice([f"{p[1]} > {rng.randint(0, 10)}", f"result % {rng.randint(2, 5)} === 0", f"steps < {rng.randint(5, 20)}"])
        op = rng.choice([f"result += {p[1]}", f"result += steps", f"result *= 2", f"result += {rng.randint(1, 10)}"])
        next_true = min(i + 1, states)
        next_false = min(i + 2, states)
        prefix = "if" if i == 0 else "} else if"
        lines.append(f"    {prefix} (state === {i}) {{")
        lines.append(f"      {op};")
        lines.append(f"      state = {cond} ? {next_true} : {next_false};")
    lines.append("    }")
    lines.append("  }")
    lines.append("  return result;")
    lines.append("}")
    return "\n".join(lines)


def gen_string_builder(rng: random.Random, p: list[str]) -> str:
    """String manipulation with multiple string literals."""
    sep = rng.choice(["-", "_", ".", "/", "::", " | "])
    prefix = rng.choice(["item", "node", "key", "val", "entry"])
    return (
        f"function {p[0]}({p[1]}, {p[2]}) {{\n"
        f'  let result = "{prefix}";\n'
        f"  for (let i = 0; i < {p[1]}.length; i++) {{\n"
        f'    if (typeof {p[1]}[i] === "string") {{\n'
        f'      result += "{sep}" + {p[1]}[i];\n'
        f"    }} else {{\n"
        f'      result += "{sep}" + String({p[1]}[i]);\n'
        f"    }}\n"
        f"  }}\n"
        f'  if ({p[2]}) result += "{sep}end";\n'
        f"  return result;\n"
        f"}}"
    )


def gen_validation(rng: random.Random, p: list[str]) -> str:
    """Input validation with multiple string checks."""
    min_len = rng.randint(3, 8)
    max_len = rng.randint(20, 50)
    return (
        f"function {p[0]}({p[1]}) {{\n"
        f'  if (typeof {p[1]} !== "string") return "invalid_type";\n'
        f'  if ({p[1]}.length < {min_len}) return "too_short";\n'
        f'  if ({p[1]}.length > {max_len}) return "too_long";\n'
        f"  for (let i = 0; i < {p[1]}.length; i++) {{\n"
        f'    if ({p[1]}[i] === " ") return "no_spaces";\n'
        f"  }}\n"
        f'  return "valid";\n'
        f"}}"
    )


def gen_accumulator_complex(rng: random.Random, p: list[str]) -> str:
    """Nested loops with multiple conditions — high complexity."""
    threshold = rng.randint(5, 20)
    return (
        f"function {p[0]}({p[1]}, {p[2]}) {{\n"
        f"  let total = 0;\n"
        f"  for (let i = 0; i < {p[1]}.length; i++) {{\n"
        f"    if ({p[1]}[i] <= 0) continue;\n"
        f"    for (let j = 0; j < {p[2]}.length; j++) {{\n"
        f"      if ({p[2]}[j] <= 0) continue;\n"
        f"      const product = {p[1]}[i] * {p[2]}[j];\n"
        f"      if (product > {threshold}) {{\n"
        f"        total += product;\n"
        f"      }} else if (product === {threshold}) {{\n"
        f"        total += 1;\n"
        f"      }}\n"
        f"    }}\n"
        f"  }}\n"
        f"  return total;\n"
        f"}}"
    )


def gen_dp_table(rng: random.Random, p: list[str]) -> str:
    """Dynamic programming with 2D table."""
    return (
        f"function {p[0]}({p[1]}, {p[2]}) {{\n"
        f"  const m = {p[1]}.length;\n"
        f"  const n = {p[2]}.length;\n"
        f"  if (m === 0 || n === 0) return 0;\n"
        f"  const dp = [];\n"
        f"  for (let i = 0; i <= m; i++) {{\n"
        f"    dp[i] = [];\n"
        f"    for (let j = 0; j <= n; j++) {{\n"
        f"      if (i === 0 || j === 0) {{\n"
        f"        dp[i][j] = 0;\n"
        f"      }} else if ({p[1]}[i - 1] === {p[2]}[j - 1]) {{\n"
        f"        dp[i][j] = dp[i - 1][j - 1] + 1;\n"
        f"      }} else {{\n"
        f"        dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1]);\n"
        f"      }}\n"
        f"    }}\n"
        f"  }}\n"
        f"  return dp[m][n];\n"
        f"}}"
    )



def gen_sorting(rng: random.Random, p: list[str]) -> str:
    """Bubble / insertion / selection sort variants."""
    variant = rng.choice(["bubble", "insertion", "selection"])
    if variant == "bubble":
        return (
            f"function {p[0]}({p[1]}) {{\n"
            f"  const arr = {p[1]}.slice();\n"
            f"  for (let i = 0; i < arr.length; i++) {{\n"
            f"    for (let j = 0; j < arr.length - i - 1; j++) {{\n"
            f"      if (arr[j] > arr[j + 1]) {{\n"
            f"        const tmp = arr[j]; arr[j] = arr[j+1]; arr[j+1] = tmp;\n"
            f"      }}\n"
            f"    }}\n"
            f"  }}\n"
            f"  return arr;\n"
            f"}}"
        )
    elif variant == "insertion":
        return (
            f"function {p[0]}({p[1]}) {{\n"
            f"  const arr = {p[1]}.slice();\n"
            f"  for (let i = 1; i < arr.length; i++) {{\n"
            f"    const key = arr[i];\n"
            f"    let j = i - 1;\n"
            f"    while (j >= 0 && arr[j] > key) {{\n"
            f"      arr[j + 1] = arr[j];\n"
            f"      j -= 1;\n"
            f"    }}\n"
            f"    arr[j + 1] = key;\n"
            f"  }}\n"
            f"  return arr;\n"
            f"}}"
        )
    else:
        return (
            f"function {p[0]}({p[1]}) {{\n"
            f"  const arr = {p[1]}.slice();\n"
            f"  for (let i = 0; i < arr.length; i++) {{\n"
            f"    let minIdx = i;\n"
            f"    for (let j = i + 1; j < arr.length; j++) {{\n"
            f"      if (arr[j] < arr[minIdx]) minIdx = j;\n"
            f"    }}\n"
            f"    if (minIdx !== i) {{\n"
            f"      const tmp = arr[i]; arr[i] = arr[minIdx]; arr[minIdx] = tmp;\n"
            f"    }}\n"
            f"  }}\n"
            f"  return arr;\n"
            f"}}"
        )


def gen_binary_search(rng: random.Random, p: list[str]) -> str:
    """Binary search returning index or -1."""
    return (
        f"function {p[0]}({p[1]}, {p[2]}) {{\n"
        f"  let lo = 0;\n"
        f"  let hi = {p[1]}.length - 1;\n"
        f"  while (lo <= hi) {{\n"
        f"    const mid = Math.floor((lo + hi) / 2);\n"
        f"    if ({p[1]}[mid] === {p[2]}) return mid;\n"
        f"    if ({p[1]}[mid] < {p[2]}) lo = mid + 1;\n"
        f"    else hi = mid - 1;\n"
        f"  }}\n"
        f"  return -1;\n"
        f"}}"
    )


def gen_stack_queue(rng: random.Random, p: list[str]) -> str:
    """Stack or queue simulation returning final result."""
    variant = rng.choice(["stack", "queue"])
    ops = rng.randint(3, 6)
    lines = [
        f"function {p[0]}({p[1]}) {{",
        f"  const store = [];",
        f"  let result = 0;",
        f"  for (let i = 0; i < {p[1]}.length; i++) {{",
        f"    if ({p[1]}[i] > 0) {{",
    ]
    if variant == "stack":
        lines.append(f"      store.push({p[1]}[i]);")
        lines += [
            "    } else if (store.length > 0) {",
            "      result += store.pop();",
        ]
    else:
        lines.append(f"      store.push({p[1]}[i]);")
        lines += [
            "    } else if (store.length > 0) {",
            "      result += store.shift();",
        ]
    lines += ["    }", "  }", "  return result + store.length;", "}"]
    return "\n".join(lines)


def gen_matrix_ops(rng: random.Random, p: list[str]) -> str:
    """Matrix transpose or row-sum."""
    variant = rng.choice(["transpose", "rowsum", "trace"])
    if variant == "rowsum":
        return (
            f"function {p[0]}({p[1]}) {{\n"
            f"  const result = [];\n"
            f"  for (let i = 0; i < {p[1]}.length; i++) {{\n"
            f"    let s = 0;\n"
            f"    for (let j = 0; j < {p[1]}[i].length; j++) {{\n"
            f"      s += {p[1]}[i][j];\n"
            f"    }}\n"
            f"    result.push(s);\n"
            f"  }}\n"
            f"  return result;\n"
            f"}}"
        )
    elif variant == "trace":
        return (
            f"function {p[0]}({p[1]}) {{\n"
            f"  let s = 0;\n"
            f"  const n = Math.min({p[1]}.length, {p[1]}[0] ? {p[1]}[0].length : 0);\n"
            f"  for (let i = 0; i < n; i++) {{\n"
            f"    s += {p[1]}[i][i];\n"
            f"  }}\n"
            f"  return s;\n"
            f"}}"
        )
    else:
        return (
            f"function {p[0]}({p[1]}) {{\n"
            f"  if (!{p[1]}.length) return [];\n"
            f"  const rows = {p[1]}.length;\n"
            f"  const cols = {p[1]}[0].length;\n"
            f"  const out = [];\n"
            f"  for (let j = 0; j < cols; j++) {{\n"
            f"    out.push([]);\n"
            f"    for (let i = 0; i < rows; i++) {{\n"
            f"      out[j].push({p[1]}[i][j]);\n"
            f"    }}\n"
            f"  }}\n"
            f"  return out;\n"
            f"}}"
        )


def gen_hash_table(rng: random.Random, p: list[str]) -> str:
    """Count frequencies or group items."""
    variant = rng.choice(["freq", "group"])
    if variant == "freq":
        return (
            f"function {p[0]}({p[1]}) {{\n"
            f"  const freq = {{}};\n"
            f"  for (let i = 0; i < {p[1]}.length; i++) {{\n"
            f"    const k = String({p[1]}[i]);\n"
            f"    freq[k] = (freq[k] || 0) + 1;\n"
            f"  }}\n"
            f"  return freq;\n"
            f"}}"
        )
    return (
        f"function {p[0]}({p[1]}, {p[2]}) {{\n"
        f"  const groups = {{}};\n"
        f"  for (let i = 0; i < {p[1]}.length; i++) {{\n"
        f"    const key = String({p[1]}[i][{p[2]}]);\n"
        f"    if (!groups[key]) groups[key] = [];\n"
        f"    groups[key].push({p[1]}[i]);\n"
        f"  }}\n"
        f"  return groups;\n"
        f"}}"
    )


def gen_memoize(rng: random.Random, p: list[str]) -> str:
    """Memoized fibonacci or factorial."""
    variant = rng.choice(["fib", "factorial"])
    if variant == "fib":
        return (
            f"function {p[0]}({p[1]}) {{\n"
            f"  const cache = {{}};\n"
            f"  function solve(n) {{\n"
            f"    if (n <= 1) return n;\n"
            f"    if (cache[n] !== undefined) return cache[n];\n"
            f"    cache[n] = solve(n - 1) + solve(n - 2);\n"
            f"    return cache[n];\n"
            f"  }}\n"
            f"  return solve({p[1]});\n"
            f"}}"
        )
    return (
        f"function {p[0]}({p[1]}) {{\n"
        f"  const cache = {{}};\n"
        f"  function fact(n) {{\n"
        f"    if (n <= 1) return 1;\n"
        f"    if (cache[n]) return cache[n];\n"
        f"    cache[n] = n * fact(n - 1);\n"
        f"    return cache[n];\n"
        f"  }}\n"
        f"  return fact({p[1]});\n"
        f"}}"
    )


def gen_string_parser(rng: random.Random, p: list[str]) -> str:
    """Parse simple delimited string."""
    sep = rng.choice([",", ":", "|", ";"])
    return (
        f"function {p[0]}({p[1]}) {{\n"
        f"  const parts = [];\n"
        f"  let current = '';\n"
        f"  for (let i = 0; i < {p[1]}.length; i++) {{\n"
        f"    if ({p[1]}[i] === '{sep}') {{\n"
        f"      if (current.length > 0) parts.push(current);\n"
        f"      current = '';\n"
        f"    }} else {{\n"
        f"      current += {p[1]}[i];\n"
        f"    }}\n"
        f"  }}\n"
        f"  if (current.length > 0) parts.push(current);\n"
        f"  return parts;\n"
        f"}}"
    )


def gen_reducer(rng: random.Random, p: list[str]) -> str:
    """Dispatch-style reducer with multiple action types."""
    actions = rng.sample(["increment", "decrement", "reset", "double", "negate", "square"], k=rng.randint(3, 5))
    cases = ""
    for action in actions:
        if action == "increment":
            body = f"return state + 1;"
        elif action == "decrement":
            body = f"return state - 1;"
        elif action == "reset":
            body = f"return 0;"
        elif action == "double":
            body = f"return state * 2;"
        elif action == "negate":
            body = f"return -state;"
        else:
            body = f"return state * state;"
        cases += f'    case "{action}": {body}\n'
    return (
        f"function {p[0]}(state, {p[1]}) {{\n"
        f"  switch ({p[1]}.type) {{\n"
        f"{cases}"
        f"    default: return state;\n"
        f"  }}\n"
        f"}}"
    )


def gen_try_catch(rng: random.Random, p: list[str]) -> str:
    """Safe accessor with try/catch error handling."""
    fallback = rng.choice(["null", "undefined", "0", '""', "false"])
    path_len = rng.randint(2, 4)
    acc = p[1]
    chain = ""
    for i in range(path_len):
        key = rng.choice(["value", "data", "result", "item", "node", "payload"])
        chain += f".{key}"
    return (
        f"function {p[0]}({p[1]}) {{\n"
        f"  try {{\n"
        f"    const val = {p[1]}{chain};\n"
        f"    if (val === undefined || val === null) return {fallback};\n"
        f"    return val;\n"
        f"  }} catch (e) {{\n"
        f"    return {fallback};\n"
        f"  }}\n"
        f"}}"
    )


def gen_multi_return(rng: random.Random, p: list[str]) -> str:
    """Function with multiple early-return paths and varied conditions."""
    n = rng.randint(3, 5)
    thresholds = sorted(rng.sample(range(1, 100), k=n))
    lines = [f"function {p[0]}({p[1]}) {{"]
    labels = rng.sample(["tiny", "small", "medium", "large", "huge", "giant", "micro"], k=n + 1)
    for i, threshold in enumerate(thresholds):
        lines.append(f'  if ({p[1]} < {threshold}) return "{labels[i]}";')
    lines.append(f'  return "{labels[n]}";')
    lines.append("}")
    return "\n".join(lines)


def gen_graph_bfs(rng: random.Random, p: list[str]) -> str:
    """BFS traversal — queue + visited map, CC 6-10."""
    return (
        f"function {p[0]}({p[1]}, {p[2]}) {{\n"
        f"  const visited = {{}};\n"
        f"  const queue = [{p[2]}];\n"
        f"  const order = [];\n"
        f"  visited[{p[2]}] = true;\n"
        f"  while (queue.length > 0) {{\n"
        f"    const node = queue.shift();\n"
        f"    order.push(node);\n"
        f"    const neighbors = {p[1]}[node] || [];\n"
        f"    for (let i = 0; i < neighbors.length; i++) {{\n"
        f"      const next = neighbors[i];\n"
        f"      if (!visited[next]) {{\n"
        f"        visited[next] = true;\n"
        f"        queue.push(next);\n"
        f"      }}\n"
        f"    }}\n"
        f"  }}\n"
        f"  return order;\n"
        f"}}"
    )


def gen_balanced_brackets(rng: random.Random, p: list[str]) -> str:
    """Check balanced brackets, CC 4-6."""
    open_b = rng.choice(["(", "[", "{"])
    close_b = {"(": ")", "[": "]", "{": "}"}[open_b]
    return (
        f"function {p[0]}({p[1]}) {{\n"
        f"  const stack = [];\n"
        f"  for (let i = 0; i < {p[1]}.length; i++) {{\n"
        f"    const ch = {p[1]}[i];\n"
        f"    if (ch === '{open_b}') {{\n"
        f"      stack.push(ch);\n"
        f"    }} else if (ch === '{close_b}') {{\n"
        f"      if (stack.length === 0) return false;\n"
        f"      stack.pop();\n"
        f"    }}\n"
        f"  }}\n"
        f"  return stack.length === 0;\n"
        f"}}"
    )


def gen_roman_numeral(rng: random.Random, p: list[str]) -> str:
    """Convert integer to Roman numeral, CC 8-12."""
    return (
        f"function {p[0]}({p[1]}) {{\n"
        f"  const vals = [1000,900,500,400,100,90,50,40,10,9,5,4,1];\n"
        f"  const syms = ['M','CM','D','CD','C','XC','L','XL','X','IX','V','IV','I'];\n"
        f"  let result = '';\n"
        f"  let num = {p[1]};\n"
        f"  if (num <= 0 || num > 3999) return '';\n"
        f"  for (let i = 0; i < vals.length; i++) {{\n"
        f"    while (num >= vals[i]) {{\n"
        f"      result += syms[i];\n"
        f"      num -= vals[i];\n"
        f"    }}\n"
        f"  }}\n"
        f"  return result;\n"
        f"}}"
    )


def gen_deep_nested(rng: random.Random, p: list[str]) -> str:
    """Deep nested conditions 5+ levels, CC 10-20."""
    depth = rng.randint(5, 7)
    thresholds = sorted(rng.sample(range(0, 50), k=depth))
    labels = rng.sample(["critical","high","medium","low","minimal","zero","extreme","severe"], k=depth + 1)
    lines = [f"function {p[0]}({p[1]}, {p[2]}) {{"]
    indent = "  "
    open_count = 0
    for i, t in enumerate(thresholds):
        lines.append(f"{indent}if ({p[1]} > {t}) {{")
        indent += "  "
        open_count += 1
        if i < depth - 1:
            lines.append(f"{indent}if ({p[2]} !== null && {p[2]} !== undefined) {{")
            indent += "  "
            open_count += 1
    lines.append(f'{indent}return "{labels[depth]}";')
    for _ in range(open_count):
        indent = indent[:-2]
        lines.append(f"{indent}}}")
    lines.append(f'  return "{labels[0]}";')
    lines.append("}")
    return "\n".join(lines)


def gen_multi_array_zip(rng: random.Random, p: list[str]) -> str:
    """Zip two arrays with transform, CC 5-8."""
    op = rng.choice(["+", "-", "*", "Math.max", "Math.min"])
    expr = f"{op}({p[1]}[i], {p[2]}[i])" if op.startswith("Math") else f"{p[1]}[i] {op} {p[2]}[i]"
    return (
        f"function {p[0]}({p[1]}, {p[2]}) {{\n"
        f"  const len = Math.min({p[1]}.length, {p[2]}.length);\n"
        f"  const result = [];\n"
        f"  for (let i = 0; i < len; i++) {{\n"
        f"    if ({p[1]}[i] === undefined || {p[2]}[i] === undefined) continue;\n"
        f"    result.push({expr});\n"
        f"  }}\n"
        f"  if ({p[1]}.length > len) {{\n"
        f"    for (let i = len; i < {p[1]}.length; i++) result.push({p[1]}[i]);\n"
        f"  }} else if ({p[2]}.length > len) {{\n"
        f"    for (let i = len; i < {p[2]}.length; i++) result.push({p[2]}[i]);\n"
        f"  }}\n"
        f"  return result;\n"
        f"}}"
    )


def gen_event_emitter(rng: random.Random, p: list[str]) -> str:
    """Event emitter pattern, CC 4-7."""
    return "\n".join([
        f"function {p[0]}() {{",
        f"  const handlers = {{}};",
        f"  return {{",
        f"    on: function(event, fn) {{",
        f"      if (!handlers[event]) handlers[event] = [];",
        f"      handlers[event].push(fn);",
        f"      return this;",
        f"    }},",
        f"    emit: function(event, data) {{",
        f"      const fns = handlers[event] || [];",
        f"      for (let i = 0; i < fns.length; i++) fns[i](data);",
        f"      return fns.length;",
        f"    }},",
        f"    off: function(event) {{",
        f"      delete handlers[event];",
        f"      return this;",
        f"    }}",
        f"  }};",
        f"}}",
    ])


def gen_rate_limiter(rng: random.Random, p: list[str]) -> str:
    """Rate limiter closure, CC 3-5."""
    limit = rng.randint(3, 20)
    window_ms = rng.choice([1000, 5000, 10000, 60000])
    return (
        f"function {p[0]}({p[1]}) {{\n"
        f"  const limit = {limit};\n"
        f"  const windowMs = {window_ms};\n"
        f"  let count = 0;\n"
        f"  let windowStart = Date.now();\n"
        f"  return function() {{\n"
        f"    const now = Date.now();\n"
        f"    if (now - windowStart > windowMs) {{\n"
        f"      count = 0;\n"
        f"      windowStart = now;\n"
        f"    }}\n"
        f"    if (count >= limit) return false;\n"
        f"    count += 1;\n"
        f"    return {p[1]}();\n"
        f"  }};\n"
        f"}}"
    )


def gen_lru_cache(rng: random.Random, p: list[str]) -> str:
    """LRU cache simulation, CC 8-12."""
    capacity = rng.randint(3, 8)
    return (
        f"function {p[0]}({p[1]}) {{\n"
        f"  const cap = {p[1]} || {capacity};\n"
        f"  const cache = {{}};\n"
        f"  const order = [];\n"
        f"  return {{\n"
        f"    get: function(key) {{\n"
        f"      if (cache[key] === undefined) return -1;\n"
        f"      const idx = order.indexOf(key);\n"
        f"      if (idx !== -1) order.splice(idx, 1);\n"
        f"      order.push(key);\n"
        f"      return cache[key];\n"
        f"    }},\n"
        f"    put: function(key, value) {{\n"
        f"      if (cache[key] !== undefined) {{\n"
        f"        const idx = order.indexOf(key);\n"
        f"        if (idx !== -1) order.splice(idx, 1);\n"
        f"      }} else if (order.length >= cap) {{\n"
        f"        const evict = order.shift();\n"
        f"        delete cache[evict];\n"
        f"      }}\n"
        f"      cache[key] = value;\n"
        f"      order.push(key);\n"
        f"    }},\n"
        f"    size: function() {{ return order.length; }},\n"
        f"  }};\n"
        f"}}"
    )


def gen_destructuring(rng: random.Random, p: list[str]) -> str:
    """Object and array destructuring with a stable scalar result."""
    fallback = rng.randint(1, 9)
    return (
        f"function {p[0]}({p[1]}) {{\n"
        f"  const {{ value = {fallback}, offset = 0 }} = {p[1]} || {{}};\n"
        f"  const [first = 0, second = 0] = Array.isArray({p[1]}?.items) ? {p[1]}.items : [];\n"
        f"  return value + offset + first + second;\n"
        f"}}"
    )


def gen_closure_counter(rng: random.Random, p: list[str]) -> str:
    """Closure over private state, exercised immediately for deterministic validation."""
    step = rng.randint(1, 4)
    return (
        f"function {p[0]}({p[1]}) {{\n"
        f"  let total = {p[1]} || 0;\n"
        f"  const add = function(value) {{ total += value * {step}; return total; }};\n"
        f"  add(1);\n"
        f"  return add(2);\n"
        f"}}"
    )


def gen_callback_pipeline(rng: random.Random, p: list[str]) -> str:
    """Map/filter/reduce callback pipeline using local arrow functions."""
    threshold = rng.randint(0, 5)
    multiplier = rng.randint(2, 4)
    return (
        f"function {p[0]}({p[1]}) {{\n"
        f"  const values = Array.isArray({p[1]}) ? {p[1]} : [];\n"
        f"  return values\n"
        f"    .filter(value => value > {threshold})\n"
        f"    .map(value => value * {multiplier})\n"
        f"    .reduce((total, value) => total + value, 0);\n"
        f"}}"
    )


def gen_default_params(rng: random.Random, p: list[str]) -> str:
    """Default, rest, and optional object parameters without external dependencies."""
    default_value = rng.randint(1, 5)
    return (
        f"function {p[0]}({p[1]} = {default_value}, {p[2]} = 1, ...rest) {{\n"
        f"  const extra = rest.reduce((sum, value) => sum + value, 0);\n"
        f"  return {p[1]} * {p[2]} + extra;\n"
        f"}}"
    )

def gen_i18n_messages(rng: random.Random, p: list[str]) -> str:
    """Format i18n message with placeholders — many string literals. CC 4-6."""
    keys = ["greeting", "farewell", "error", "warning", "success", "info", "debug", "confirm"]
    chosen = rng.sample(keys, k=rng.randint(4, 6))
    arg_name = p[1]
    lines = [f"function {p[0]}({arg_name}) {{"]
    lines.append(f"  const messages = {{")
    for key in chosen:
        placeholder = "{" + arg_name + "}"
        lines.append(f'    {key}: "{key}_{placeholder}_msg",')
    lines.append("  };")
    lines.append(f"  if (!{arg_name}) return messages.error;")
    lines.append(f"  if ({arg_name} < 0) return messages.warning;")
    lines.append(f"  if ({arg_name} > 100) return messages.success;")
    lines.append(f'  return messages.info.replace("{{}}", String({arg_name}));')
    lines.append("}")
    return "\n".join(lines)


def gen_log_formatter(rng: random.Random, p: list[str]) -> str:
    """Format log line with level, timestamp prefix, message. Many strings. CC 3-5."""
    levels = ["INFO", "WARN", "ERROR", "DEBUG", "TRACE"]
    chosen = rng.sample(levels, k=rng.randint(3, 5))
    arg = p[1]
    lines = [f"function {p[0]}({arg}) {{"]
    lines.append("  const prefixes = {")
    for level in chosen:
        lines.append(f'    {level}: "[{level}] [{{ts}}]",')
    lines.append("  };")
    lines.append(f"  const level = {arg}.level || \"INFO\";")
    lines.append(f"  const msg = {arg}.message || \"no message\";")
    lines.append(f"  const ts = {arg}.timestamp || Date.now();")
    lines.append("  const prefix = prefixes[level] || prefixes.INFO;")
    lines.append("  const formatted = prefix.replace(\"{ts}\", String(ts));")
    lines.append(f"  if (level === \"ERROR\") return formatted + \" \" + msg + \" (code=\" + String({arg}.code || 0) + \")\";")
    lines.append("  if (level === \"WARN\") return formatted + \" \" + msg;")
    lines.append("  return formatted + \" \" + msg;")
    lines.append("}")
    return "\n".join(lines)


def gen_url_parser(rng: random.Random, p: list[str]) -> str:
    """Parse URL-like string with multiple delimiters. CC 4-6, many strings."""
    delim = rng.choice([":", "/", "?", "&", "="])
    lines = [f"function {p[0]}({p[1]}) {{"]
    lines.append(f"  const parts = {p[1]}.split(\"{delim}\");")
    lines.append(f"  if (parts.length < 2) return {p[1]};")
    lines.append("  const head = parts[0];")
    lines.append(f"  const tail = parts.slice(1).join(\"{delim}\");")
    lines.append(f'  if (head === "http" || head === "https") return {p[1]};')
    lines.append(f'  if (head === "prefix" && tail.length > 0) return tail;')
    lines.append(f"  return {p[1]}.toUpperCase();")
    lines.append("}")
    return "\n".join(lines)

GENERATORS = [
    gen_array_loop, gen_string_process, gen_math_branch, gen_nested_loop,
    gen_recursion, gen_filter_map, gen_bitwise, gen_object_scan,
    gen_nested_if, gen_switch_case, gen_state_machine, gen_string_builder,
    gen_validation, gen_accumulator_complex, gen_dp_table,
    # Wave 2 generators
    gen_sorting, gen_binary_search, gen_stack_queue, gen_matrix_ops,
    gen_hash_table, gen_memoize, gen_string_parser, gen_reducer,
    gen_try_catch, gen_multi_return,
    # Wave 3 generators (high complexity, CC 6-20)
    gen_graph_bfs, gen_balanced_brackets, gen_roman_numeral, gen_deep_nested,
    gen_multi_array_zip, gen_event_emitter, gen_rate_limiter, gen_lru_cache,
    # Wave 4 generators (modern JavaScript syntax)
    gen_destructuring, gen_closure_counter, gen_callback_pipeline, gen_default_params,
    # v6 string-rich generators
    gen_i18n_messages, gen_log_formatter, gen_url_parser,
]
MODERN_GENERATORS = [
    ("destructuring", gen_destructuring),
    ("closure", gen_closure_counter),
    ("callback", gen_callback_pipeline),
    ("default_params", gen_default_params),
]
MODERN_GENERATOR_FUNCTIONS = {generator for _, generator in MODERN_GENERATORS}
LEGACY_GENERATORS = [generator for generator in GENERATORS if generator not in MODERN_GENERATOR_FUNCTIONS]


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic JavaScript functions for the dataset.")
    parser.add_argument("--count", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--output", type=Path, default=Path("data/raw"))
    parser.add_argument(
        "--modern-share", type=float, default=0.25,
        help="Minimum share of generated functions from modern syntax families (0..1).",
    )
    args = parser.parse_args()
    if not 0 <= args.modern_share <= 1:
        parser.error("--modern-share must be between 0 and 1")

    rng = random.Random(args.seed)
    args.output.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output / "manifest.jsonl"
    manifest = {}
    if manifest_path.exists():
        for line in manifest_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                manifest[rec["id"]] = rec

    written = 0
    modern_target = round(args.count * args.modern_share)
    modern_names = [name for name, _ in MODERN_GENERATORS]
    per_family, remainder = divmod(modern_target, len(modern_names))
    modern_targets = {
        name: per_family + (index < remainder)
        for index, name in enumerate(modern_names)
    }
    modern_written = 0
    modern_counts = {name: 0 for name in modern_names}
    used_names = set()
    attempts = 0
    while written < args.count and attempts < args.count * 3:
        attempts += 1
        params = [make_name(rng, used_names) for _ in range(4)]
        if modern_written < modern_target:
            eligible = [
                item for item in MODERN_GENERATORS
                if modern_counts[item[0]] < modern_targets[item[0]]
            ]
            generator_type, generator = rng.choice(eligible)
        else:
            generator = rng.choice(LEGACY_GENERATORS)
            generator_type = generator.__name__.removeprefix("gen_")
        code = generator(rng, params)
        digest = hashlib.sha256(code.encode("utf-8")).hexdigest()
        if digest in manifest:
            continue
        destination = args.output / f"{digest}.js"
        destination.write_text(code + "\n", encoding="utf-8")
        manifest[digest] = {
            "id": digest,
            "file": destination.name,
            "sources": ["synthetic"],
            "source_type": "synthetic",
            "generator_type": generator_type,
        }
        written += 1
        if generator_type in modern_counts:
            modern_written += 1
            modern_counts[generator_type] += 1

    manifest_path.write_text(
        "".join(json.dumps(manifest[k], ensure_ascii=False, separators=(",", ":")) + "\n" for k in sorted(manifest)),
        encoding="utf-8",
        newline="\n",
    )
    family_summary = ",".join(f"{name}={modern_counts[name]}" for name in modern_names)
    print(f"synthetic={written} modern={modern_written} modern_target={modern_target} {family_summary} output={args.output}")


if __name__ == "__main__":
    main()
