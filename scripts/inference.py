"""Inference wrapper for NeuroObfuscator model.

Supports:
- Loading fine-tuned model (Unsloth merged or LoRA adapter)
- Prompt formatting matching 07_format_for_training.py
- JSON extraction + schema validation
- Retry logic (up to 3 attempts)
- Deterministic fallback plan on failure
- Batch inference for evaluation
"""
from __future__ import annotations

import json
import random
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from common import call_engine_batch

# --- Prompt template (must match 07_format_for_training.py) ---

SYSTEM_PROMPT = """You are NeuroObfuscator. Given JavaScript code and its AST features, generate an optimal obfuscation plan as a JSON object.

Available transformations (apply in this order when enabled):
1. rename         - Rename local identifiers to hex-like names. Almost always recommended.
2. string_encode  - Encode string literals. Methods: charcode_array, charcode_concat, hex_escape, unicode_escape. Only enable if string_count > 0.
3. operator_sub   - Substitute arithmetic/comparison operators (a+b -> a-(-b), a===b -> !(a!==b)). Use when operator_count > 2.
4. dead_code      - Insert unreachable code blocks. count: 1-5. More complex code tolerates more.
5. opaque_predicates - Insert always-true/always-false conditions. count: 1-3. Primarily for medium/heavy intensity; may also be used sparingly on light functions when extra diversity is needed.

Intensity guide:
- light:  cyclomatic_complexity <= 2. Prefer rename + dead_code only.
- medium: complexity 3-5. Add string_encode and operator_sub if applicable.
- heavy:  complexity > 5. Use all relevant transforms aggressively.

Rules:
- You MUST honor the requested "Target intensity" when it is provided, even if
  it differs from what the complexity alone would suggest. Intensity determines
  the plan shape:
  light  -> minimal plan: rename + dead_code ONLY (no string_encode,
            no operator_sub, no opaque_predicates),
  medium -> moderate plan: rename + dead_code + string_encode/operator_sub
            when applicable, NO opaque_predicates,
  heavy  -> aggressive plan: all relevant transforms INCLUDING opaque_predicates.
- Only include enabled transforms in "order" array.
- Order MUST follow: rename, string_encode, operator_sub, dead_code, opaque_predicates.
- Do NOT include a "seed" field in your JSON; the runtime injects the provided seed automatically.
- Avoid over-bloating small functions.

Output ONLY valid JSON. No explanations, no markdown."""

ORDER = ["rename", "string_encode", "operator_sub", "dead_code", "opaque_predicates"]

def _complexity_class(cc: int) -> str:
    if cc <= 2:
        return "light"
    elif cc <= 5:
        return "medium"
    return "heavy"


def format_prompt(code: str, features: dict, seed: int, target_intensity: str | None = None) -> str:
    """Format the instruction prompt for the model (matches 07 --conditional)."""
    cc = features.get("cyclomatic_complexity", 1)
    cc_class = _complexity_class(cc)
    features_json = json.dumps(features, separators=(",", ":"))
    intensity_line = f"Target intensity: {target_intensity}\n" if target_intensity else ""

    return (
        f"[INST] <<SYS>>\n{SYSTEM_PROMPT}\n<</SYS>>\n\n"
        f"=== CODE ===\n{code}\n=== END CODE ===\n\n"
        f"=== AST FEATURES ===\n{features_json}\n=== END AST FEATURES ===\n\n"
        f"complexity_class={cc_class} (cyclomatic_complexity={cc})\n"
        f"{intensity_line}"
        f"seed={seed}\n\n"
        f"Generate the obfuscation plan JSON: [/INST]"
    )


def extract_json(text: str) -> dict | None:
    """Extract the first valid JSON object from model output."""
    # Try direct parse first
    text = text.strip()
    if text.startswith("{"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

    # Scan every opening brace and let the JSON decoder handle nesting.
    decoder = json.JSONDecoder()
    for start, char in enumerate(text):
        if char != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[start:])
            if "transforms" in obj or "order" in obj:
                return obj
        except json.JSONDecodeError:
            continue
    return None


def validate_plan_schema(plan: dict) -> bool:
    """Validate the model plan against the engine's JSON contract."""
    if not isinstance(plan, Mapping) or isinstance(plan, list):
        return False
    # "seed" is optional: the model no longer generates it (training target
    # excludes it); infer_plan injects the prompt seed when missing.
    if not set(plan) <= {"seed", "intensity", "transforms", "order"} or not set(plan) >= {"intensity", "transforms", "order"}:
        return False
    if plan["intensity"] not in {"light", "medium", "heavy"}:
        return False
    if not isinstance(plan["transforms"], dict):
        return False
    if set(plan["transforms"]) != set(ORDER):
        return False
    if not isinstance(plan["order"], list):
        return False
    if len(plan["order"]) != len(set(plan["order"])):
        return False
    if any(name not in ORDER for name in plan["order"]):
        return False

    transforms = plan["transforms"]
    for name, config in transforms.items():
        if not isinstance(config, dict) or not isinstance(config.get("enabled"), bool):
            return False
    string_config = transforms["string_encode"]
    if string_config["enabled"]:
        if string_config.get("method") not in {"charcode_array", "charcode_concat", "hex_escape", "unicode_escape"}:
            return False
        if not isinstance(string_config.get("min_length"), int) or string_config["min_length"] < 1:
            return False
    operator_config = transforms["operator_sub"]
    if operator_config["enabled"] and not isinstance(operator_config.get("rate"), (int, float)):
        return False
    if operator_config.get("rate") is not None and not 0 <= operator_config["rate"] <= 1:
        return False
    for name, maximum in (("dead_code", 5), ("opaque_predicates", 3)):
        config = transforms[name]
        if config["enabled"]:
            if not isinstance(config.get("count"), int) or not 0 <= config["count"] <= maximum:
                return False

    enabled = [name for name in ORDER if transforms[name]["enabled"]]
    if plan["order"] != [name for name in ORDER if name in plan["order"]]:
        return False
    if plan["order"] != enabled:
        return False
    return True


def make_transformers_generator(model, tokenizer, **generation_kwargs) -> Callable[[str], str]:
    """Create a ``generate_fn`` from a Transformers-compatible causal LM.

    Model loading stays outside this module so Unsloth, merged checkpoints, and
    plain Transformers models can all provide their own loading strategy.
    """
    defaults = {"max_new_tokens": 256, "do_sample": False, "return_full_text": False}
    defaults.update(generation_kwargs)

    def generate(prompt: str) -> str:
        encoded = tokenizer(prompt, return_tensors="pt")
        device = next(model.parameters()).device
        encoded = {key: value.to(device) for key, value in encoded.items()}
        generated = model.generate(**encoded, **defaults)
        prompt_length = encoded["input_ids"].shape[-1]
        tokens = generated[0][prompt_length:]
        return tokenizer.decode(tokens, skip_special_tokens=True)

    return generate


def generate_fallback_plan(features: dict, seed: int, target_intensity: str | None = None) -> dict:
    """Deterministic fallback plan when model fails."""
    has_strings = features.get("string_count", 0) > 0
    has_operators = features.get("operator_count", 0) > 0
    complexity = features.get("cyclomatic_complexity", 1)

    if complexity >= 5:
        dead_count, opaque_count = 3, 2
    elif complexity >= 3:
        dead_count, opaque_count = 2, 1
    else:
        dead_count, opaque_count = 1, 0

    transforms = {
        "rename": {"enabled": True},
        "string_encode": {"enabled": has_strings, "method": "charcode_array", "min_length": 2},
        "operator_sub": {"enabled": has_operators and complexity >= 3, "rate": 0.7},
        "dead_code": {"enabled": True, "count": dead_count},
        "opaque_predicates": {"enabled": opaque_count > 0, "count": max(opaque_count, 1)},
    }
    # v7.1: intensity determines the plan shape (matches the training data).
    if target_intensity == "light":
        transforms["string_encode"]["enabled"] = False
        transforms["operator_sub"]["enabled"] = False
        transforms["opaque_predicates"] = {"enabled": False, "count": 1}
        transforms["dead_code"] = {"enabled": True, "count": 1}
    elif target_intensity == "medium":
        transforms["string_encode"]["enabled"] = has_strings
        transforms["operator_sub"]["enabled"] = has_operators and complexity >= 3
        transforms["opaque_predicates"] = {"enabled": False, "count": 1}
    elif target_intensity == "heavy":
        transforms["string_encode"]["enabled"] = True
        transforms["operator_sub"]["enabled"] = has_operators
        transforms["opaque_predicates"] = {"enabled": True, "count": max(opaque_count, 2)}
    intensity = target_intensity or _complexity_class(complexity)
    order = [name for name in ORDER if transforms[name]["enabled"]]

    return {
        "seed": seed,
        "intensity": intensity,
        "transforms": transforms,
        "order": order,
    }


class NeuroObfuscatorInference:
    """Inference wrapper for NeuroObfuscator model."""

    def __init__(self, generate_fn: Callable[[str], str] | None = None, max_retries: int = 3):
        """
        Args:
            generate_fn: Function that takes a prompt string and returns model output string.
                         If None, only fallback plans are used.
            max_retries: Maximum number of generation attempts before fallback.
        """
        self.generate_fn = generate_fn
        self.max_retries = max_retries
        self.stats = {"total": 0, "json_ok": 0, "schema_ok": 0, "fallback": 0, "retries": 0}

    def get_features(self, code: str) -> dict | None:
        """Extract AST features from code."""
        resp = call_engine_batch([{"operation": "extract_features", "code": code}])
        if resp and resp[0].get("ok"):
            return resp[0]["value"]["features"]
        return None

    def infer_plan(self, code: str, seed: int | None = None, target_intensity: str | None = None) -> dict:
        """Generate obfuscation plan for given code.

        Returns a valid plan dict. Falls back to deterministic plan on failure.
        target_intensity (v7): optional 'light'|'medium'|'heavy' steering that is
        injected into the prompt as "Target intensity" (conditional training format).
        """
        if target_intensity is not None and target_intensity not in {"light", "medium", "heavy"}:
            raise ValueError(f"target_intensity must be light/medium/heavy, got {target_intensity!r}")
        self.stats["total"] += 1

        features = self.get_features(code)
        if features is None:
            self.stats["fallback"] += 1
            return generate_fallback_plan({}, seed if seed is not None else random.randint(0, 0xFFFFFFFF), target_intensity)

        if seed is None:
            seed = random.randint(0, 0xFFFFFFFF)

        if self.generate_fn is None:
            self.stats["fallback"] += 1
            return generate_fallback_plan(features, seed, target_intensity)

        prompt = format_prompt(code, features, seed, target_intensity=target_intensity)

        for attempt in range(self.max_retries):
            if attempt > 0:
                self.stats["retries"] += 1

            try:
                output = self.generate_fn(prompt)
            except Exception:
                continue

            plan = extract_json(output)
            if plan is None:
                continue
            self.stats["json_ok"] += 1

            # Inject seed if missing (model no longer generates it)
            if "seed" not in plan:
                plan["seed"] = seed
            elif not isinstance(plan["seed"], int) or isinstance(plan["seed"], bool) or not 0 <= plan["seed"] <= 0xFFFFFFFF:
                plan["seed"] = seed

            if validate_plan_schema(plan):
                self.stats["schema_ok"] += 1
                return plan

        # All retries exhausted
        self.stats["fallback"] += 1
        return generate_fallback_plan(features, seed)

    def infer_batch(self, codes: list[str], seeds: list[int] | None = None,
                    target_intensities: list[str | None] | None = None) -> list[dict]:
        """Batch inference for multiple code snippets."""
        if seeds is None:
            seeds = [random.randint(0, 0xFFFFFFFF) for _ in codes]
        if target_intensities is None:
            target_intensities = [None] * len(codes)
        return [self.infer_plan(code, seed, target_intensity=intensity)
                for code, seed, intensity in zip(codes, seeds, target_intensities)]

    def report(self) -> dict:
        """Return inference statistics."""
        total = max(self.stats["total"], 1)
        return {
            **self.stats,
            "json_rate": self.stats["json_ok"] / total,
            "schema_rate": self.stats["schema_ok"] / total,
            "fallback_rate": self.stats["fallback"] / total,
        }


# --- CLI ---

def main():
    """CLI: read JS from stdin or file, print plan JSON."""
    import argparse

    parser = argparse.ArgumentParser(description="Generate obfuscation plan for JavaScript code.")
    parser.add_argument("--input", type=Path, help="Input .js file (default: stdin)")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for plan")
    parser.add_argument("--intensity", choices=("light", "medium", "heavy"), default=None,
                        help="v7: target intensity injected into the prompt")
    parser.add_argument("--output", type=Path, help="Output plan JSON file (default: stdout)")
    args = parser.parse_args()

    if args.input:
        code = args.input.read_text(encoding="utf-8")
    else:
        code = sys.stdin.read()

    engine = NeuroObfuscatorInference(generate_fn=None)  # fallback only until model loaded
    plan = engine.infer_plan(code, seed=args.seed, target_intensity=args.intensity)

    result = json.dumps(plan, indent=2)
    if args.output:
        args.output.write_text(result, encoding="utf-8")
        print(f"Plan written to {args.output}")
    else:
        print(result)


if __name__ == "__main__":
    main()
