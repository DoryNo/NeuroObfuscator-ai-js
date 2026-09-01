from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import read_jsonl, write_jsonl

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


def _complexity_class(cc: int) -> str:
    if cc <= 2:
        return "light"
    elif cc <= 5:
        return "medium"
    return "heavy"


def sanitize_source(source, source_type=None) -> str:
    if source_type in {"synthetic", "real"}:
        return source_type
    if isinstance(source, list):
        labels = set()
        for s in source:
            labels.add("synthetic" if "synthetic" in str(s).lower() else "real")
        return ",".join(sorted(labels))
    if isinstance(source, str):
        return "synthetic" if "synthetic" in source.lower() else "real"
    return "unknown"


def build_instruction(code: str, features: dict, seed: int, target_intensity: str | None = None) -> str:
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


def format_record(record: dict, conditional: bool = False) -> dict:
    features = record["features"]
    cc = features.get("cyclomatic_complexity", 1)
    cc_class = _complexity_class(cc)
    features_json = json.dumps(features, separators=(",", ":"))
    seed = record["plan"].get("seed", 42)
    intensity = record["plan"].get("intensity", "medium")

    instruction = build_instruction(
        record["original_code"], features, seed,
        target_intensity=intensity if conditional else None,
    )
    # Seed is excluded from the training target: the model cannot learn to
    # predict a random number. The runtime injects the prompt's seed at
    # inference time (inference.py already does this when "seed" is missing).
    plan_no_seed = {k: v for k, v in record["plan"].items() if k != "seed"}
    # Conditional (v7): the same function can appear with several intensity
    # variants; the @intensity suffix keeps ids unique and marks the variant.
    record_id = f"{record['id']}@{intensity}" if conditional else record["id"]
    metadata = {
        "source": sanitize_source(record.get("source"), record.get("source_type")),
        "repository": record.get("repository"),
        "license": record.get("license"),
        "score": record["metrics"]["score"],
        "intensity": intensity,
        "complexity_class": cc_class,
        "cyclomatic_complexity": cc,
        "generator_type": record.get("generator_type"),
    }
    if conditional:
        metadata["base_id"] = record["id"]
    return {
        "id": record_id,
        "instruction": instruction,
        "output": json.dumps(plan_no_seed, separators=(",", ":")),
        "metadata": metadata,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("data/candidates/scored.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("data/final/formatted.jsonl"))
    parser.add_argument("--conditional", action="store_true",
                        help="v7: put 'Target intensity' into the prompt and suffix ids with @intensity")
    args = parser.parse_args()

    count = write_jsonl(args.output, (format_record(r, args.conditional) for r in read_jsonl(args.input)))
    print(f"formatted={count} conditional={args.conditional} output={args.output}")


if __name__ == "__main__":
    main()
