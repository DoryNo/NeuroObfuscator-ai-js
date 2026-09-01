function validateEmail(email) {
  if (typeof email !== "string") return false;
  const at = email.indexOf("@");
  if (at < 1) return false;
  const dot = email.lastIndexOf(".");
  if (dot < at + 2 || dot === email.length - 1) return false;
  for (let i = 0; i < email.length; i++) {
    if (email[i] === " ") return false;
  }
  return true;
}

function parseQueryString(str) {
  if (!str || str.length === 0) return {};
  if (str[0] === "?") str = str.substring(1);
  const result = {};
  const pairs = str.split("&");
  for (let i = 0; i < pairs.length; i++) {
    const idx = pairs[i].indexOf("=");
    if (idx === -1) {
      result[decodeURIComponent(pairs[i])] = "";
    } else {
      const key = decodeURIComponent(pairs[i].substring(0, idx));
      const value = decodeURIComponent(pairs[i].substring(idx + 1));
      result[key] = value;
    }
  }
  return result;
}

function formatNumber(num) {
  if (typeof num !== "number") return "";
  const str = String(Math.abs(num));
  const parts = str.split(".");
  let integer = parts[0];
  let result = "";
  let count = 0;
  for (let i = integer.length - 1; i >= 0; i--) {
    result = integer[i] + result;
    count++;
    if (count % 3 === 0 && i > 0) {
      result = "," + result;
    }
  }
  if (parts.length > 1) result += "." + parts[1];
  if (num < 0) result = "-" + result;
  return result;
}

function slugify(str) {
  let result = "";
  for (let i = 0; i < str.length; i++) {
    const ch = str[i].toLowerCase();
    if (ch >= "a" && ch <= "z") {
      result += ch;
    } else if (ch >= "0" && ch <= "9") {
      result += ch;
    } else if (ch === " " || ch === "-" || ch === "_") {
      if (result.length > 0 && result[result.length - 1] !== "-") {
        result += "-";
      }
    }
  }
  if (result[result.length - 1] === "-") {
    result = result.substring(0, result.length - 1);
  }
  return result;
}

function truncate(str, maxLen, suffix) {
  if (suffix === undefined) suffix = "...";
  if (str.length <= maxLen) return str;
  return str.substring(0, maxLen - suffix.length) + suffix;
}

function retry(fn, attempts, delay) {
  let lastError = null;
  for (let i = 0; i < attempts; i++) {
    try {
      return fn();
    } catch (err) {
      lastError = err;
    }
  }
  throw lastError;
}

function mapValues(obj, fn) {
  const result = {};
  const keys = Object.keys(obj);
  for (let i = 0; i < keys.length; i++) {
    result[keys[i]] = fn(obj[keys[i]], keys[i]);
  }
  return result;
}

function deepEqual(a, b) {
  if (a === b) return true;
  if (a === null || b === null) return false;
  if (typeof a !== "object" || typeof b !== "object") return false;
  const keysA = Object.keys(a);
  const keysB = Object.keys(b);
  if (keysA.length !== keysB.length) return false;
  for (let i = 0; i < keysA.length; i++) {
    if (!deepEqual(a[keysA[i]], b[keysA[i]])) return false;
  }
  return true;
}

function compose(fns) {
  return function composed(value) {
    let result = value;
    for (let i = fns.length - 1; i >= 0; i--) {
      result = fns[i](result);
    }
    return result;
  };
}

function pipe(fns) {
  return function piped(value) {
    let result = value;
    for (let i = 0; i < fns.length; i++) {
      result = fns[i](result);
    }
    return result;
  };
}

function once(fn) {
  let called = false;
  let result;
  return function onced() {
    if (!called) {
      called = true;
      result = fn.apply(this, arguments);
    }
    return result;
  };
}

function curry(fn) {
  return function curried() {
    const args = Array.prototype.slice.call(arguments);
    if (args.length >= fn.length) {
      return fn.apply(this, args);
    }
    return function () {
      return curried.apply(this, args.concat(Array.prototype.slice.call(arguments)));
    };
  };
}

function weightedAverage(values, weights) {
  if (values.length !== weights.length) return 0;
  let sum = 0;
  let weightSum = 0;
  for (let i = 0; i < values.length; i++) {
    sum += values[i] * weights[i];
    weightSum += weights[i];
  }
  if (weightSum === 0) return 0;
  return sum / weightSum;
}

function linearInterpolate(a, b, t) {
  if (t <= 0) return a;
  if (t >= 1) return b;
  return a + (b - a) * t;
}

function hexToRgb(hex) {
  if (hex[0] === "#") hex = hex.substring(1);
  if (hex.length !== 6) return null;
  const r = parseInt(hex.substring(0, 2), 16);
  const g = parseInt(hex.substring(2, 4), 16);
  const b = parseInt(hex.substring(4, 6), 16);
  if (isNaN(r) || isNaN(g) || isNaN(b)) return null;
  return [r, g, b];
}

function rgbToHex(r, g, b) {
  if (r < 0 || r > 255 || g < 0 || g > 255 || b < 0 || b > 255) return null;
  let result = "#";
  const parts = [r, g, b];
  for (let i = 0; i < parts.length; i++) {
    const hex = Math.round(parts[i]).toString(16);
    if (hex.length === 1) result += "0";
    result += hex;
  }
  return result;
}

function tokenize(expression) {
  const tokens = [];
  let i = 0;
  while (i < expression.length) {
    if (expression[i] === " ") {
      i++;
      continue;
    }
    if (expression[i] >= "0" && expression[i] <= "9") {
      let num = "";
      while (i < expression.length && expression[i] >= "0" && expression[i] <= "9") {
        num += expression[i];
        i++;
      }
      tokens.push({ type: "number", value: Number(num) });
    } else {
      tokens.push({ type: "operator", value: expression[i] });
      i++;
    }
  }
  return tokens;
}

function evaluatePostfix(tokens) {
  const stack = [];
  for (let i = 0; i < tokens.length; i++) {
    if (tokens[i].type === "number") {
      stack.push(tokens[i].value);
    } else {
      const b = stack.pop();
      const a = stack.pop();
      if (tokens[i].value === "+") stack.push(a + b);
      else if (tokens[i].value === "-") stack.push(a - b);
      else if (tokens[i].value === "*") stack.push(a * b);
      else if (tokens[i].value === "/") stack.push(a / b);
    }
  }
  return stack[0];
}

function encodeRLE(str) {
  if (str.length === 0) return "";
  let result = "";
  let count = 1;
  for (let i = 1; i <= str.length; i++) {
    if (i < str.length && str[i] === str[i - 1]) {
      count++;
    } else {
      if (count > 1) result += String(count);
      result += str[i - 1];
      count = 1;
    }
  }
  return result;
}

function decodeRLE(str) {
  let result = "";
  let i = 0;
  while (i < str.length) {
    let num = "";
    while (i < str.length && str[i] >= "0" && str[i] <= "9") {
      num += str[i];
      i++;
    }
    const count = num.length > 0 ? Number(num) : 1;
    if (i < str.length) {
      for (let j = 0; j < count; j++) {
        result += str[i];
      }
      i++;
    }
  }
  return result;
}

function padStart(str, length, char) {
  if (char === undefined) char = " ";
  while (str.length < length) {
    str = char + str;
  }
  return str;
}

function padEnd(str, length, char) {
  if (char === undefined) char = " ";
  while (str.length < length) {
    str = str + char;
  }
  return str;
}

function frequencySort(arr) {
  const freq = {};
  for (let i = 0; i < arr.length; i++) {
    const key = String(arr[i]);
    freq[key] = (freq[key] || 0) + 1;
  }
  return arr.slice().sort(function (a, b) {
    const diff = freq[String(b)] - freq[String(a)];
    if (diff !== 0) return diff;
    return a - b;
  });
}

function slidingWindowMax(arr, k) {
  if (k <= 0 || arr.length === 0) return [];
  const result = [];
  for (let i = 0; i <= arr.length - k; i++) {
    let max = arr[i];
    for (let j = i + 1; j < i + k; j++) {
      if (arr[j] > max) max = arr[j];
    }
    result.push(max);
  }
  return result;
}

function spiralOrder(matrix) {
  if (matrix.length === 0) return [];
  const result = [];
  let top = 0;
  let bottom = matrix.length - 1;
  let left = 0;
  let right = matrix[0].length - 1;
  while (top <= bottom && left <= right) {
    for (let i = left; i <= right; i++) result.push(matrix[top][i]);
    top++;
    for (let i = top; i <= bottom; i++) result.push(matrix[i][right]);
    right--;
    if (top <= bottom) {
      for (let i = right; i >= left; i--) result.push(matrix[bottom][i]);
      bottom--;
    }
    if (left <= right) {
      for (let i = bottom; i >= top; i--) result.push(matrix[i][left]);
      left++;
    }
  }
  return result;
}
