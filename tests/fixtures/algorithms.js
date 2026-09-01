function binarySearch(arr, target) {
  let low = 0;
  let high = arr.length - 1;
  while (low <= high) {
    const mid = Math.floor((low + high) / 2);
    if (arr[mid] === target) return mid;
    if (arr[mid] < target) low = mid + 1;
    else high = mid - 1;
  }
  return -1;
}

function bubbleSort(arr) {
  const result = arr.slice();
  for (let i = 0; i < result.length; i++) {
    for (let j = 0; j < result.length - i - 1; j++) {
      if (result[j] > result[j + 1]) {
        const tmp = result[j];
        result[j] = result[j + 1];
        result[j + 1] = tmp;
      }
    }
  }
  return result;
}

function fibonacci(n) {
  if (n <= 0) return 0;
  if (n === 1) return 1;
  let a = 0;
  let b = 1;
  for (let i = 2; i <= n; i++) {
    const temp = a + b;
    a = b;
    b = temp;
  }
  return b;
}

function isPrime(n) {
  if (n < 2) return false;
  if (n === 2) return true;
  if (n % 2 === 0) return false;
  for (let i = 3; i <= Math.sqrt(n); i += 2) {
    if (n % i === 0) return false;
  }
  return true;
}

function gcd(a, b) {
  while (b !== 0) {
    const temp = b;
    b = a % b;
    a = temp;
  }
  return a;
}

function factorial(n) {
  if (n <= 1) return 1;
  let result = 1;
  for (let i = 2; i <= n; i++) {
    result *= i;
  }
  return result;
}

function reverseString(str) {
  let result = "";
  for (let i = str.length - 1; i >= 0; i--) {
    result += str[i];
  }
  return result;
}

function countVowels(str) {
  const vowels = "aeiouAEIOU";
  let count = 0;
  for (let i = 0; i < str.length; i++) {
    if (vowels.indexOf(str[i]) !== -1) {
      count++;
    }
  }
  return count;
}

function flatten(arr) {
  const result = [];
  for (let i = 0; i < arr.length; i++) {
    if (Array.isArray(arr[i])) {
      const nested = flatten(arr[i]);
      for (let j = 0; j < nested.length; j++) {
        result.push(nested[j]);
      }
    } else {
      result.push(arr[i]);
    }
  }
  return result;
}

function removeDuplicates(arr) {
  const seen = {};
  const result = [];
  for (let i = 0; i < arr.length; i++) {
    const key = String(arr[i]);
    if (!seen[key]) {
      seen[key] = true;
      result.push(arr[i]);
    }
  }
  return result;
}

function maxSubarraySum(arr) {
  if (arr.length === 0) return 0;
  let maxSum = arr[0];
  let currentSum = arr[0];
  for (let i = 1; i < arr.length; i++) {
    if (currentSum + arr[i] < arr[i]) {
      currentSum = arr[i];
    } else {
      currentSum += arr[i];
    }
    if (currentSum > maxSum) {
      maxSum = currentSum;
    }
  }
  return maxSum;
}

function mergeSort(arr) {
  if (arr.length <= 1) return arr.slice();
  const mid = Math.floor(arr.length / 2);
  const left = mergeSort(arr.slice(0, mid));
  const right = mergeSort(arr.slice(mid));
  const result = [];
  let i = 0;
  let j = 0;
  while (i < left.length && j < right.length) {
    if (left[i] <= right[j]) {
      result.push(left[i]);
      i++;
    } else {
      result.push(right[j]);
      j++;
    }
  }
  while (i < left.length) {
    result.push(left[i]);
    i++;
  }
  while (j < right.length) {
    result.push(right[j]);
    j++;
  }
  return result;
}

function isPalindrome(str) {
  const cleaned = str.toLowerCase().replace(/[^a-z0-9]/g, "");
  let left = 0;
  let right = cleaned.length - 1;
  while (left < right) {
    if (cleaned[left] !== cleaned[right]) return false;
    left++;
    right--;
  }
  return true;
}

function deepClone(obj) {
  if (obj === null || typeof obj !== "object") return obj;
  if (Array.isArray(obj)) {
    const result = [];
    for (let i = 0; i < obj.length; i++) {
      result.push(deepClone(obj[i]));
    }
    return result;
  }
  const result = {};
  const keys = Object.keys(obj);
  for (let i = 0; i < keys.length; i++) {
    result[keys[i]] = deepClone(obj[keys[i]]);
  }
  return result;
}

function throttle(fn, delay) {
  let lastCall = 0;
  return function throttled() {
    const now = Date.now();
    if (now - lastCall >= delay) {
      lastCall = now;
      return fn.apply(this, arguments);
    }
    return undefined;
  };
}

function chunk(arr, size) {
  if (size <= 0) return [];
  const result = [];
  for (let i = 0; i < arr.length; i += size) {
    result.push(arr.slice(i, i + size));
  }
  return result;
}

function intersection(arr1, arr2) {
  const set = {};
  const result = [];
  for (let i = 0; i < arr1.length; i++) {
    set[String(arr1[i])] = true;
  }
  for (let i = 0; i < arr2.length; i++) {
    if (set[String(arr2[i])]) {
      result.push(arr2[i]);
      set[String(arr2[i])] = false;
    }
  }
  return result;
}

function camelToSnake(str) {
  let result = "";
  for (let i = 0; i < str.length; i++) {
    const ch = str[i];
    if (ch >= "A" && ch <= "Z") {
      if (i > 0) result += "_";
      result += ch.toLowerCase();
    } else {
      result += ch;
    }
  }
  return result;
}

function clamp(value, min, max) {
  if (value < min) return min;
  if (value > max) return max;
  return value;
}

function range(start, end, step) {
  if (step === undefined) step = 1;
  if (step <= 0) return [];
  const result = [];
  for (let i = start; i < end; i += step) {
    result.push(i);
  }
  return result;
}

function sumDigits(n) {
  let num = Math.abs(n);
  let sum = 0;
  while (num > 0) {
    sum += num % 10;
    num = Math.floor(num / 10);
  }
  return sum;
}

function powerOf(base, exp) {
  if (exp === 0) return 1;
  let result = 1;
  for (let i = 0; i < exp; i++) {
    result *= base;
  }
  return result;
}

function longestCommonPrefix(strs) {
  if (strs.length === 0) return "";
  let prefix = strs[0];
  for (let i = 1; i < strs.length; i++) {
    while (strs[i].indexOf(prefix) !== 0) {
      prefix = prefix.substring(0, prefix.length - 1);
      if (prefix === "") return "";
    }
  }
  return prefix;
}

function zip(arr1, arr2) {
  const result = [];
  const len = Math.min(arr1.length, arr2.length);
  for (let i = 0; i < len; i++) {
    result.push([arr1[i], arr2[i]]);
  }
  return result;
}

function twoSum(nums, target) {
  const map = {};
  for (let i = 0; i < nums.length; i++) {
    const complement = target - nums[i];
    if (map[complement] !== undefined) {
      return [map[complement], i];
    }
    map[nums[i]] = i;
  }
  return null;
}

function rotateArray(arr, k) {
  if (arr.length === 0) return [];
  const n = arr.length;
  const shift = ((k % n) + n) % n;
  const result = [];
  for (let i = 0; i < n; i++) {
    result.push(arr[(i - shift + n) % n]);
  }
  return result;
}

function matrixMultiply(a, b) {
  if (a[0].length !== b.length) return null;
  const rows = a.length;
  const cols = b[0].length;
  const inner = b.length;
  const result = [];
  for (let i = 0; i < rows; i++) {
    result[i] = [];
    for (let j = 0; j < cols; j++) {
      let sum = 0;
      for (let k = 0; k < inner; k++) {
        sum += a[i][k] * b[k][j];
      }
      result[i][j] = sum;
    }
  }
  return result;
}

function isAnagram(str1, str2) {
  if (str1.length !== str2.length) return false;
  const count = {};
  for (let i = 0; i < str1.length; i++) {
    count[str1[i]] = (count[str1[i]] || 0) + 1;
    count[str2[i]] = (count[str2[i]] || 0) - 1;
  }
  const keys = Object.keys(count);
  for (let i = 0; i < keys.length; i++) {
    if (count[keys[i]] !== 0) return false;
  }
  return true;
}

function insertionSort(arr) {
  const result = arr.slice();
  for (let i = 1; i < result.length; i++) {
    const current = result[i];
    let j = i - 1;
    while (j >= 0 && result[j] > current) {
      result[j + 1] = result[j];
      j--;
    }
    result[j + 1] = current;
  }
  return result;
}

function uniquePaths(m, n) {
  const dp = [];
  for (let i = 0; i < m; i++) {
    dp[i] = [];
    for (let j = 0; j < n; j++) {
      if (i === 0 || j === 0) {
        dp[i][j] = 1;
      } else {
        dp[i][j] = dp[i - 1][j] + dp[i][j - 1];
      }
    }
  }
  return dp[m - 1][n - 1];
}

function pascalTriangle(rows) {
  if (rows <= 0) return [];
  const result = [[1]];
  for (let i = 1; i < rows; i++) {
    const prev = result[i - 1];
    const row = [1];
    for (let j = 1; j < prev.length; j++) {
      row.push(prev[j - 1] + prev[j]);
    }
    row.push(1);
    result.push(row);
  }
  return result;
}

function compress(str) {
  if (str.length === 0) return "";
  let result = "";
  let count = 1;
  for (let i = 1; i <= str.length; i++) {
    if (i < str.length && str[i] === str[i - 1]) {
      count++;
    } else {
      result += str[i - 1];
      if (count > 1) result += String(count);
      count = 1;
    }
  }
  return result;
}

function groupBy(arr, key) {
  const result = {};
  for (let i = 0; i < arr.length; i++) {
    const group = String(arr[i][key]);
    if (!result[group]) result[group] = [];
    result[group].push(arr[i]);
  }
  return result;
}

function memoize(fn) {
  const cache = {};
  return function memoized() {
    const key = JSON.stringify(Array.prototype.slice.call(arguments));
    if (cache[key] !== undefined) return cache[key];
    cache[key] = fn.apply(this, arguments);
    return cache[key];
  };
}

function debounce(fn, wait) {
  let timer = null;
  return function debounced() {
    if (timer !== null) clearTimeout(timer);
    const args = arguments;
    const context = this;
    timer = setTimeout(function () {
      fn.apply(context, args);
      timer = null;
    }, wait);
  };
}

function flattenObject(obj, prefix) {
  if (prefix === undefined) prefix = "";
  const result = {};
  const keys = Object.keys(obj);
  for (let i = 0; i < keys.length; i++) {
    const newKey = prefix ? prefix + "." + keys[i] : keys[i];
    if (obj[keys[i]] !== null && typeof obj[keys[i]] === "object" && !Array.isArray(obj[keys[i]])) {
      const nested = flattenObject(obj[keys[i]], newKey);
      const nestedKeys = Object.keys(nested);
      for (let j = 0; j < nestedKeys.length; j++) {
        result[nestedKeys[j]] = nested[nestedKeys[j]];
      }
    } else {
      result[newKey] = obj[keys[i]];
    }
  }
  return result;
}

function compact(arr) {
  const result = [];
  for (let i = 0; i < arr.length; i++) {
    if (arr[i]) {
      result.push(arr[i]);
    }
  }
  return result;
}

function difference(arr1, arr2) {
  const set = {};
  for (let i = 0; i < arr2.length; i++) {
    set[String(arr2[i])] = true;
  }
  const result = [];
  for (let i = 0; i < arr1.length; i++) {
    if (!set[String(arr1[i])]) {
      result.push(arr1[i]);
    }
  }
  return result;
}

function capitalize(str) {
  if (str.length === 0) return "";
  let result = str[0].toUpperCase();
  for (let i = 1; i < str.length; i++) {
    if (str[i - 1] === " ") {
      result += str[i].toUpperCase();
    } else {
      result += str[i];
    }
  }
  return result;
}

function median(arr) {
  if (arr.length === 0) return 0;
  const sorted = arr.slice().sort(function (a, b) { return a - b; });
  const mid = Math.floor(sorted.length / 2);
  if (sorted.length % 2 === 0) {
    return (sorted[mid - 1] + sorted[mid]) / 2;
  }
  return sorted[mid];
}

function modes(arr) {
  if (arr.length === 0) return [];
  const freq = {};
  let maxCount = 0;
  for (let i = 0; i < arr.length; i++) {
    const key = String(arr[i]);
    freq[key] = (freq[key] || 0) + 1;
    if (freq[key] > maxCount) maxCount = freq[key];
  }
  const result = [];
  const keys = Object.keys(freq);
  for (let i = 0; i < keys.length; i++) {
    if (freq[keys[i]] === maxCount) {
      result.push(Number(keys[i]));
    }
  }
  return result;
}

function transpose(matrix) {
  if (matrix.length === 0) return [];
  const rows = matrix.length;
  const cols = matrix[0].length;
  const result = [];
  for (let j = 0; j < cols; j++) {
    result[j] = [];
    for (let i = 0; i < rows; i++) {
      result[j][i] = matrix[i][j];
    }
  }
  return result;
}

function pick(obj, keys) {
  const result = {};
  for (let i = 0; i < keys.length; i++) {
    if (obj[keys[i]] !== undefined) {
      result[keys[i]] = obj[keys[i]];
    }
  }
  return result;
}

function omit(obj, keys) {
  const exclude = {};
  for (let i = 0; i < keys.length; i++) {
    exclude[keys[i]] = true;
  }
  const result = {};
  const all = Object.keys(obj);
  for (let i = 0; i < all.length; i++) {
    if (!exclude[all[i]]) {
      result[all[i]] = obj[all[i]];
    }
  }
  return result;
}

function partition(arr, predicate) {
  const truthy = [];
  const falsy = [];
  for (let i = 0; i < arr.length; i++) {
    if (predicate(arr[i])) {
      truthy.push(arr[i]);
    } else {
      falsy.push(arr[i]);
    }
  }
  return [truthy, falsy];
}

function uniq(arr) {
  const seen = {};
  const result = [];
  for (let i = 0; i < arr.length; i++) {
    const key = typeof arr[i] + ":" + String(arr[i]);
    if (!seen[key]) {
      seen[key] = true;
      result.push(arr[i]);
    }
  }
  return result;
}

function countBy(arr, fn) {
  const result = {};
  for (let i = 0; i < arr.length; i++) {
    const key = String(fn(arr[i]));
    result[key] = (result[key] || 0) + 1;
  }
  return result;
}

function levenshtein(a, b) {
  const m = a.length;
  const n = b.length;
  const dp = [];
  for (let i = 0; i <= m; i++) {
    dp[i] = [i];
  }
  for (let j = 0; j <= n; j++) {
    dp[0][j] = j;
  }
  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      if (a[i - 1] === b[j - 1]) {
        dp[i][j] = dp[i - 1][j - 1];
      } else {
        dp[i][j] = 1 + Math.min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1]);
      }
    }
  }
  return dp[m][n];
}

function findIndex(arr, predicate) {
  for (let i = 0; i < arr.length; i++) {
    if (predicate(arr[i], i)) return i;
  }
  return -1;
}

function last(arr, n) {
  if (n === undefined) return arr[arr.length - 1];
  if (n >= arr.length) return arr.slice();
  return arr.slice(arr.length - n);
}
